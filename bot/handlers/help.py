from telegram import ParseMode, Update
from telegram.ext import CallbackContext, CommandHandler, Dispatcher


def help_callback(update: Update, context: CallbackContext) -> None:
    new_message = update.effective_message.reply_text(
        "Беседа поддерживает создания пользовательских скриптов на языке Python. "
        "Скрипты выполняются в изолированной среде, которая имеет доступ к следующим модулям: telegram, requests, PIL, math, re, random\n\n"
        "/scripts <code> - выполнить скрипт на Python\n"
        "/scripts - посмотреть список доступных скриптов\n"
        "/save <script_name> - создать новый скрипт\n"
        "/load <script_name> <script_args>- загрузить скрипт\n"
        "/rename <old_script_name> <new_script_name> - переименовать скрипт\n"
        "/changedesc <script_name>\n(след. строка) <new_script_desc> - изменить описание скрипта\n"
        "/delete <script_name> - удалить скрипт",
    )


def init_handlers(dispatcher: Dispatcher):
    # show about information
    dispatcher.add_handler(CommandHandler("about_scripts", help_callback), group=4)
