import re

from telegram import Message
from telegram.ext import MessageFilter

from bot import config


class IsGroupInWhitelist(MessageFilter):
    name = "is_group_in_whitelist"

    def filter(self, message: Message):
        return message.chat.id == config.GROUP_ID
