import os

# IDs des propriétaires du BOT (reçoivent les notifications)
OWNER_IDS = [1399234120214909010, 1425947830463365120]

# IDs des administrateurs (peuvent utiliser /savedb et /setdb)
ADMIN_IDS = [1399234120214909010, 1425947830463365120]

# Token depuis les variables d'environnement
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("Le token BOT_TOKEN n'est pas défini dans les variables d'environnement")