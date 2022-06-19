import logging

logger = logging.getLogger(__name__)


def setup(dispatcher):
    logger.info("Setup handlers...")

    import bot.handlers.help as help
    import bot.handlers.scripts as scripts

    scripts.init_handlers(dispatcher)
    help.init_handlers(dispatcher)
