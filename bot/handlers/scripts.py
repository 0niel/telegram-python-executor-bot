import io
import json
import re
import time
from enum import IntEnum

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ParseMode,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Update,
)
from telegram.ext import (
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    Dispatcher,
    Filters,
    MessageHandler,
)
from telegram.utils.helpers import escape_markdown
from telegram_bot_pagination import InlineKeyboardPaginator

from bot import config
from bot.filters.is_group_in_whitelist import IsGroupInWhitelist
from bot.models.user_script import UserScript
from bot.utils.safe_exec.executor import Executor
from bot.utils.safe_exec.secure_compiler import BUILTINS_WHITELIST

RE_SCRIPT_NAME = r"^[a-zA-Z0-9_-]{1,30}$"


class ScriptSaveStates(IntEnum):
    SELECT_DESC = 0
    SELECT_CODE = 1
    TEST_CODE = 2
    TEST_CODE_WAITING_COMMAND = 3


def safe_exec(exec_command, update: Update, context: CallbackContext) -> None:
    try:
        safe_locals_names = [
            "update",
            # "context", ? must be unsafe
        ]

        safe_locals = {}
        for item in safe_locals_names:
            safe_locals[item] = locals().get(item, None)

        safe_builtins = BUILTINS_WHITELIST
        safe_builtins["print"] = update.message.reply_text
        safe_builtins["BytesIO"] = io.BytesIO

        Executor().execute(
            exec_command,
            {"__builtins__": safe_builtins},
            safe_locals,
        )

    except Exception as msg:
        msg = str(msg)
        msg = msg.replace(
            "'NoneType' object is not subscriptable", "Операция запрещена!"
        )
        update.message.reply_text(text=str(msg))


def save_script_final(update: Update, context: ContextTypes) -> int:
    query = update.callback_query
    query.answer()
    from_user_id = query.from_user.id
    script_name = context.user_data["create_script"]["name"]
    UserScript(
        author_id=from_user_id,
        name=script_name,
        script=context.user_data["create_script"]["code"],
        description=context.user_data["create_script"]["description"],
    ).create()
    query.edit_message_text(
        text=f"✅ Скрипт сохранён с названием {script_name}. "
        f"Используйте <code>/load {script_name}</code>, чтобы запустить его.\n\n"
        "Если ваш скрипт использует параметры, то указывайте их сразу после названия.",
        parse_mode=ParseMode.HTML,
    )
    context.user_data["create_script"] = {}
    return ConversationHandler.END


def edit_test_script_code(update: Update, context: ContextTypes) -> int:
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        "Отправьте отредактированный код для вашего скрипта. "
        "В качестве отступов мы используем 4 пробела. "
        "Чтобы избежать форматирования Markdown, отправьте ваш код как моноширный."
    )

    return ScriptSaveStates.SELECT_CODE


def exec_test_script(update: Update, context: ContextTypes) -> int:
    args = context.args
    args = f"args = {json.dumps(args)}\n" if len(args) > 0 else ""
    safe_exec(args + context.user_data["create_script"]["code"], update, context)
    time.sleep(2)
    reply_keyboard = [
        [
            InlineKeyboardButton("Сохранить", callback_data="Сохранить"),
            InlineKeyboardButton("Изменить", callback_data="Изменить"),
        ]
    ]
    update.message.reply_text(
        "Выполняю...\n\n"
        "Вы хотите сохранить скрипт или продолжить его редактирование?",
        reply_markup=InlineKeyboardMarkup(
            reply_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True,
            input_field_placeholder="Сохранить или Изменить?",
        ),
    )
    return ScriptSaveStates.TEST_CODE_WAITING_COMMAND


def test_script(update: Update, context: ContextTypes) -> int:
    query = update.callback_query
    query.answer()
    query.edit_message_text(
        text="Чтобы протестировать код, введите `/test <опциональные аргументы>`",
        parse_mode=ParseMode.MARKDOWN_V2,
    )

    return ScriptSaveStates.TEST_CODE_WAITING_COMMAND


def save_script_code(update: Update, context: ContextTypes) -> int:
    script_code = update.message.text
    if len(script_code) > 2000:
        update.message.reply_text(
            "❌ Количество символов в скрипте не должно привышать 2000!"
        )
        return
    elif len(script_code) < 7:
        update.message.reply_text("❌ Вы пытаетесь сохранить пустой скрипт")
        return

    context.user_data["create_script"] = context.user_data["create_script"] | {
        "code": script_code
    }

    reply_keyboard = [
        [
            InlineKeyboardButton("Да", callback_data="Да"),
            InlineKeyboardButton("Нет", callback_data="Нет"),
        ]
    ]
    update.message.reply_text(
        "Почти готово.\n\n"
        "Хотите ли вы протестировать ваш скрипт перед тем, как сохранить его?",
        reply_markup=InlineKeyboardMarkup(
            reply_keyboard,
            one_time_keyboard=True,
            resize_keyboard=True,
            input_field_placeholder="Да или Нет?",
        ),
        protect_content=True,
    )

    return ScriptSaveStates.TEST_CODE


def save_script_desc(update: Update, context: ContextTypes) -> int:
    script_description = update.message.text
    if len(script_description) < 2 or len(script_description) > 300:
        update.message.reply_text(
            "❌ Описание скрипта не должно быть пустым и должно быть не длиннее 300 символов!"
        )
        return ScriptSaveStates.SELECT_DESC

    context.user_data["create_script"] = context.user_data["create_script"] | {
        "description": script_description
    }

    update.message.reply_text(
        "Великолепно! А теперь, пожалуйста, отправьте код вашего скрипта. "
        "В качестве отступов мы используем 4 пробела. "
        "Чтобы избежать форматирования Markdown, отправьте ваш код как моноширный."
    )

    return ScriptSaveStates.SELECT_CODE


def save_script(update: Update, context: ContextTypes) -> int:
    if len(context.args) == 0:
        update.message.reply_text(
            "❌ Вы должны ввести название для своего скрипта. "
            "Пример: <code>/save my_new_script</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    script_name = context.args[0]
    if re.match(RE_SCRIPT_NAME, script_name) is None:
        update.message.reply_text("❌ Нельзя создать скрипт с таким названием!")
        return
    elif len(script_name) < 2 or len(script_name) > 40:
        update.message.reply_text(
            "❌ Название скрипта должно быть не короче 2-х сиволов и не длиннее 40"
        )
        return
    elif UserScript.get_by_name(script_name):
        update.message.reply_text(
            "❌ Пользовательский скрипт с таким названием уже существует!"
        )
        return

    context.user_data["create_script"] = {"name": script_name}
    update.message.reply_text(
        "Отлично! Теперь задайте описание своему скрипту. "
        "Описание будет отображаться в списке всех скриптов (/scripst). "
        "Не забудьте указать примеры использования, если это важно.\n\n"
        "Введите /cancel, чтобы отменить создание скрипта."
    )

    return ScriptSaveStates.SELECT_DESC


def cancel(update: Update, context: ContextTypes) -> int:
    context.user_data["create_script"] = {}
    update.message.reply_text(
        "Вы отменили создание скрипта.", reply_markup=ReplyKeyboardRemove()
    )

    return ConversationHandler.END


def load_script_callback(update: Update, context: CallbackContext) -> None:
    command_args = context.args
    script_name = command_args[0]
    user_script = UserScript.get_by_name(script_name)
    if not user_script:
        update.message.reply_text(
            "❌ Пользовательского скрипта с таким названием не существует!"
        )
        return

    args = command_args[1:]
    args = f"args = {json.dumps(args)}\n" if len(args) > 0 else ""
    safe_exec(args + user_script.script, update, context)


def exec_callback(update: Update, context: CallbackContext) -> None:
    if update.message.chat_id != config.GROUP_ID:
        return

    exec_command = update.message.text.replace("/exec", "").strip()
    safe_exec(exec_command, update, context)


def rename_script_callback(update: Update, context: CallbackContext) -> None:
    command_args = context.args
    old_script_name = command_args[0]
    new_script_name = command_args[1]
    user_id = update.message.from_user.id
    user_script = UserScript.get_by_name(old_script_name)

    if not user_script:
        update.message.reply_text(
            "❌ Пользовательского скрипта с таким названием не существует!"
        )
        return
    if user_script.author_id != user_id:
        update.message.reply_text("❌ Переименовать скрипт может только его автор!")
        return
    if re.match(RE_SCRIPT_NAME, new_script_name) is None:
        update.message.reply_text("❌ Нельзя переименовать скрипт в это название!")
        return

    UserScript.rename(old_script_name, new_script_name)
    update.message.reply_text(
        f"✅ Скрипт {old_script_name} успешно переименован в {new_script_name}"
    )


def delete_script_callback(update: Update, context: CallbackContext) -> None:
    command_args = context.args
    script_name = command_args[0]
    user_id = update.message.from_user.id
    user_script = UserScript.get_by_name(script_name)

    if not user_script:
        update.message.reply_text(
            "❌ Пользовательского скрипта с таким названием не существует!"
        )
        return
    if user_script.author_id != user_id:
        update.message.reply_text("❌ Удалить скрипт может только его автор!")
        return

    UserScript.delete_by_name(script_name)
    update.message.reply_text(f"✅ Скрипт {script_name} успешно удалён")


def changedesc_script_callback(update: Update, context: CallbackContext) -> None:
    args = update.message.text.replace("/changedesc", "").strip()
    script_name = args.split()[0].strip()
    new_script_description = args.split("\n")[1].strip()
    user_id = update.message.from_user.id
    user_script = UserScript.get_by_name(script_name)

    if not user_script:
        update.message.reply_text(
            "❌ Пользовательского скрипта с таким названием не существует!"
        )
        return
    if user_script.author_id != user_id:
        update.message.reply_text("❌ Изменить описание скрипта может только его автор!")
        return
    if len(new_script_description) < 2 or len(new_script_description) > 300:
        update.message.reply_text(
            "❌ Описание скрипта не должно быть пустым и должно быть не длиннее 300 символов"
        )
        return

    UserScript.change_desc(script_name, new_script_description)
    update.message.reply_text(f"✅ Описание скрипта {script_name} успешно обновлено")


def get_scripts_data(bot, chat_id) -> list[str]:
    scripts = UserScript.get_all()

    scripts_data = []
    scripts_text = ""

    if scripts:
        for i in range(len(scripts)):
            author = bot.get_chat_member(chat_id, scripts[i].author_id).user

            index = str(i + 1)
            tmp_text = f"{index}\. *{scripts[i].name}* \- {escape_markdown(scripts[i].description, version=2)}\. Автор скрипта \- {author.first_name}\n\n"
            if i % 10 != 0 or i == 0:
                scripts_text += tmp_text
            else:
                scripts_data.append(scripts_text)
                scripts_text = tmp_text

        if scripts_text != "":
            scripts_data.append(scripts_text)

    return scripts_data


def scripts_handler(update: Update, context: CallbackContext) -> None:
    msg = update.effective_message

    logs_data = get_scripts_data(update.message.bot, update.message.chat.id)

    if len(logs_data) > 0:
        paginator = InlineKeyboardPaginator(
            len(logs_data), data_pattern="scripts#{page}#" + str(msg.from_user.id)
        )

        new_message = msg.reply_text(
            text=logs_data[0],
            reply_markup=paginator.markup,
            parse_mode=ParseMode.MARKDOWN_V2,
        )

    else:
        new_message = msg.reply_text("❌ Сейчас нет ни одного скрипта.")


def scripts_callback_page_callback(update: Update, context: CallbackContext) -> None:
    query = update.callback_query
    query.answer()
    user_id = int(query.data.split("#")[2])
    page = int(query.data.split("#")[1])
    if update.callback_query.from_user.id == user_id:
        logs_data = get_scripts_data(
            update.callback_query.bot, update.callback_query.message.chat.id
        )
        paginator = InlineKeyboardPaginator(
            len(logs_data),
            current_page=page,
            data_pattern="scripts#{page}#" + str(user_id),
        )
        query.edit_message_text(
            text=logs_data[page - 1],
            reply_markup=paginator.markup,
            parse_mode=ParseMode.MARKDOWN_V2,
        )
    else:
        query.answer("Вы не можете пользоваться данной клавиатурой")


def init_handlers(dispatcher: Dispatcher):
    dispatcher.add_handler(
        CommandHandler(
            "exec", exec_callback, filters=IsGroupInWhitelist(), run_async=True
        ),
        group=33,
    )
    dispatcher.add_handler(
        CommandHandler(
            "load", load_script_callback, filters=IsGroupInWhitelist(), run_async=True
        ),
        group=34,
    )

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler(
                "save",
                save_script,
                filters=IsGroupInWhitelist(),
                run_async=True,
            ),
        ],
        states={
            ScriptSaveStates.SELECT_DESC: [
                MessageHandler(Filters.text & ~Filters.command, save_script_desc)
            ],
            ScriptSaveStates.SELECT_CODE: [
                MessageHandler(Filters.text & ~Filters.command, save_script_code)
            ],
            ScriptSaveStates.TEST_CODE: [
                CallbackQueryHandler(test_script, pattern="^Да$"),
                CallbackQueryHandler(save_script_final, pattern="^Нет$"),
            ],
            ScriptSaveStates.TEST_CODE_WAITING_COMMAND: [
                CommandHandler("test", exec_test_script),
                CallbackQueryHandler(save_script_final, pattern="^Сохранить$"),
                CallbackQueryHandler(edit_test_script_code, pattern="^Изменить$"),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    dispatcher.add_handler(
        CommandHandler("scripts", scripts_handler, run_async=True), group=36
    )
    dispatcher.add_handler(
        CommandHandler(
            "rename",
            rename_script_callback,
            filters=IsGroupInWhitelist(),
            run_async=True,
        ),
        group=37,
    )
    dispatcher.add_handler(
        CommandHandler(
            "changedesc",
            changedesc_script_callback,
            filters=IsGroupInWhitelist(),
            run_async=True,
        ),
        group=38,
    )
    dispatcher.add_handler(
        CommandHandler(
            "delete",
            delete_script_callback,
            filters=IsGroupInWhitelist(),
            run_async=True,
        ),
        group=39,
    )
    dispatcher.add_handler(conv_handler)
    dispatcher.add_handler(
        CallbackQueryHandler(scripts_callback_page_callback, pattern="^scripts#")
    )
