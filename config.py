import os

# IDs des owners (ceux qui reçoivent les notifications)
OWNER_IDS = [1399234120214909010, 1425947830463365120]

# IDs des admins (peuvent utiliser /savedb et /setdb)
ADMIN_IDS = [1399234120214909010, 1425947830463365120]  # Même liste ou ajoute d'autres IDs

# Token depuis les variables d'environnement Railway
BOT_TOKEN = os.getenv('BOT_TOKEN')

if not BOT_TOKEN:
    raise ValueError("Le token BOT_TOKEN n'est pas défini dans les variables d'environnement")