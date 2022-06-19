from envparse import env

TELEGRAM_TOKEN = env.str("TELEGRAM_TOKEN")
DATABASE_URI = env.str("DATABASE_URI")
GROUP_ID = env.int("GROUP_ID", default=-567317308)
