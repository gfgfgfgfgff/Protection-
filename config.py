# config.py
import os

BOT_TOKEN = os.getenv("BOT_TOKEN")  # Récupère la variable Railway
OWNER_IDS = [497126437258788864]

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN non défini - Vérifie les variables Railway")