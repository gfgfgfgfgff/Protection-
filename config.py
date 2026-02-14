# config.py
import os
OWNER_IDS = [1399234120214909010, 1425947830463365120]
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN non defini")