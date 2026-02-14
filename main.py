import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
from typing import Optional, List, Dict
import re
import os
import io
import json
import time
import aiohttp
import aiofiles
from collections import defaultdict, deque
from datetime import datetime, timedelta
from config import BOT_TOKEN, OWNER_IDS, ADMIN_IDS

# Configuration
DISCORD_INVITE_REGEX = r'(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|com)|discordapp\.com/invite)/[a-zA-Z0-9]+'

# Structure pour stocker les actions des utilisateurs
class ActionTracker:
    def __init__(self):
        self.user_actions: Dict[int, deque] = defaultdict(lambda: deque(maxlen=100))
        self.action_timestamps: Dict[int, List[float]] = defaultdict(list)
    
    def add_action(self, user_id: int, action_type: str):
        """Ajoute une action pour un utilisateur"""
        timestamp = time.time()
        self.user_actions[user_id].append({
            'type': action_type,
            'timestamp': timestamp
        })
        self.action_timestamps[user_id].append(timestamp)
    
    def get_recent_actions(self, user_id: int, action_type: str, seconds: int) -> int:
        """Compte les actions d'un type dans les X dernières secondes"""
        current_time = time.time()
        cutoff = current_time - seconds
        
        count = 0
        for action in self.user_actions[user_id]:
            if action['type'] == action_type and action['timestamp'] > cutoff:
                count += 1
        
        return count
    
    def clear_user(self, user_id: int):
        """Efface les actions d'un utilisateur"""
        if user_id in self.user_actions:
            self.user_actions[user_id].clear()
        if user_id in self.action_timestamps:
            self.action_timestamps[user_id].clear()

# Gestionnaire d'assets pour sauvegarder images
class GuildAssetManager:
    def __init__(self):
        self.backup_dir = "guild_assets"
        os.makedirs(self.backup_dir, exist_ok=True)
    
    async def backup_guild_assets(self, guild):
        """Sauvegarde tous les assets du serveur"""
        guild_dir = f"{self.backup_dir}/{guild.id}"
        os.makedirs(guild_dir, exist_ok=True)
        
        # Sauvegarder l'icône
        if guild.icon:
            await self._download_file(guild.icon.url, f"{guild_dir}/icon.png")
        
        # Sauvegarder la bannière
        if guild.banner:
            await self._download_file(guild.banner.url, f"{guild_dir}/banner.png")
        
        # Sauvegarder la splash (si existe)
        if guild.splash:
            await self._download_file(guild.splash.url, f"{guild_dir}/splash.png")
        
        # Sauvegarder le nom et autres infos
        with open(f"{guild_dir}/info.txt", 'w') as f:
            f.write(f"name={guild.name}\n")
            f.write(f"verification={guild.verification_level}\n")
            f.write(f"backup_date={datetime.now()}\n")
    
    async def _download_file(self, url, path):
        """Télécharge un fichier"""
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        async with aiofiles.open(path, 'wb') as f:
                            await f.write(await resp.read())
                            return True
        except Exception as e:
            print(f"❌ Erreur téléchargement: {e}")
        return False
    
    async def restore_guild_icon(self, guild):
        """Restaure l'icône du serveur"""
        icon_path = f"{self.backup_dir}/{guild.id}/icon.png"
        if os.path.exists(icon_path):
            try:
                async with aiofiles.open(icon_path, 'rb') as f:
                    icon_data = await f.read()
                    await guild.edit(icon=icon_data)
                    return True
            except Exception as e:
                print(f"❌ Erreur restauration icône: {e}")
        return False
    
    async def restore_guild_banner(self, guild):
        """Restaure la bannière du serveur"""
        banner_path = f"{self.backup_dir}/{guild.id}/banner.png"
        if os.path.exists(banner_path):
            try:
                async with aiofiles.open(banner_path, 'rb') as f:
                    banner_data = await f.read()
                    await guild.edit(banner=banner_data)
                    return True
            except Exception as e:
                print(f"❌ Erreur restauration bannière: {e}")
        return False

# Base de données
class Database:
    def __init__(self):
        self.conn = sqlite3.connect('security.db')
        self.c = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        # Table pour la whitelist
        self.c.execute('''CREATE TABLE IF NOT EXISTS whitelist
                         (user_id INTEGER PRIMARY KEY, 
                          actions TEXT)''')
        
        # Table pour les sys
        self.c.execute('''CREATE TABLE IF NOT EXISTS sys_users
                         (user_id INTEGER PRIMARY KEY)''')
        
        # Table pour la configuration des punitions
        self.c.execute('''CREATE TABLE IF NOT EXISTS punishments
                         (action TEXT PRIMARY KEY, 
                          sanction TEXT,
                          duree TEXT)''')
        
        # Table pour les status des modules
        self.c.execute('''CREATE TABLE IF NOT EXISTS modules
                         (module TEXT PRIMARY KEY, 
                          status INTEGER)''')
        
        # Table pour les rôles limités
        self.c.execute('''CREATE TABLE IF NOT EXISTS limit_roles
                         (role_id INTEGER PRIMARY KEY,
                          role_name TEXT)''')
        
        # Table pour les rôles à ping limité
        self.c.execute('''CREATE TABLE IF NOT EXISTS limit_ping_roles
                         (role_id INTEGER PRIMARY KEY,
                          role_name TEXT)''')
        
        # Table pour la configuration des limites d'actions
        self.c.execute('''CREATE TABLE IF NOT EXISTS action_limits
                         (action TEXT PRIMARY KEY,
                          nombre INTEGER,
                          duree TEXT)''')
        
        # Table pour la sauvegarde du serveur
        self.c.execute('''CREATE TABLE IF NOT EXISTS guild_backup
                         (guild_id INTEGER PRIMARY KEY,
                          name TEXT,
                          icon_url TEXT,
                          banner_url TEXT,
                          vanity_code TEXT,
                          verification_level INTEGER,
                          backup_time TIMESTAMP)''')
        
        # Table pour les logs channels
        self.c.execute('''CREATE TABLE IF NOT EXISTS log_channels
                         (guild_id INTEGER,
                          log_type TEXT,
                          channel_id INTEGER,
                          PRIMARY KEY (guild_id, log_type))''')
        
        # Initialisation des punitions par défaut
        default_punishments = [
            ('antibot', 'kick', '0'),
            ('antilink', 'warn', '0'),
            ('antiping', 'warn', '0'),
            ('antideco', 'warn', '0'),
            ('antichannel', 'derank', '0'),
            ('antirank', 'derank', '0'),
            ('antiban', 'ban', '0'),
            ('antimodif', 'derank', '0')
        ]
        
        for action, sanction, duree in default_punishments:
            self.c.execute('INSERT OR IGNORE INTO punishments VALUES (?, ?, ?)', (action, sanction, duree))
        
        # Initialisation des modules par défaut (désactivés)
        default_modules = [
            ('antibot', 0),
            ('antilink', 0),
            ('antiping', 0),
            ('antideco', 0),
            ('antichannel', 0),
            ('antirank', 0),
            ('antiban', 0),
            ('antimodif', 0)
        ]
        
        for module, status in default_modules:
            self.c.execute('INSERT OR IGNORE INTO modules VALUES (?, ?)', (module, status))
        
        # Initialisation des limites d'actions
        default_limits = [
            ('antideco', 3, '10s'),
            ('antiban', 1, '10s'),
            ('antirole', 2, '10s'),
            ('antichannel', 2, '10s'),
            ('antiping', 5, '10s'),
            ('antimodif', 2, '10s')
        ]
        
        for action, nombre, duree in default_limits:
            self.c.execute('INSERT OR IGNORE INTO action_limits VALUES (?, ?, ?)', (action, nombre, duree))
        
        self.conn.commit()
    
    def export_db(self):
        """Exporte toute la base de données en dictionnaire"""
        data = {
            'whitelist': [],
            'sys_users': [],
            'punishments': [],
            'modules': [],
            'limit_roles': [],
            'limit_ping_roles': [],
            'action_limits': [],
            'log_channels': []
        }
        
        # Export whitelist
        self.c.execute('SELECT user_id, actions FROM whitelist')
        data['whitelist'] = [{'user_id': row[0], 'actions': row[1]} for row in self.c.fetchall()]
        
        # Export sys_users
        self.c.execute('SELECT user_id FROM sys_users')
        data['sys_users'] = [row[0] for row in self.c.fetchall()]
        
        # Export punishments
        self.c.execute('SELECT action, sanction, duree FROM punishments')
        data['punishments'] = [{'action': row[0], 'sanction': row[1], 'duree': row[2]} for row in self.c.fetchall()]
        
        # Export modules
        self.c.execute('SELECT module, status FROM modules')
        data['modules'] = [{'module': row[0], 'status': row[1]} for row in self.c.fetchall()]
        
        # Export limit_roles
        self.c.execute('SELECT role_id, role_name FROM limit_roles')
        data['limit_roles'] = [{'role_id': row[0], 'role_name': row[1]} for row in self.c.fetchall()]
        
        # Export limit_ping_roles
        self.c.execute('SELECT role_id, role_name FROM limit_ping_roles')
        data['limit_ping_roles'] = [{'role_id': row[0], 'role_name': row[1]} for row in self.c.fetchall()]
        
        # Export action_limits
        self.c.execute('SELECT action, nombre, duree FROM action_limits')
        data['action_limits'] = [{'action': row[0], 'nombre': row[1], 'duree': row[2]} for row in self.c.fetchall()]
        
        # Export log_channels
        self.c.execute('SELECT guild_id, log_type, channel_id FROM log_channels')
        data['log_channels'] = [{'guild_id': row[0], 'log_type': row[1], 'channel_id': row[2]} 
                               for row in self.c.fetchall()]
        
        return data
    
    def import_db(self, data):
        """Importe les données dans la base de données"""
        # Nettoyer les tables existantes
        self.c.execute('DELETE FROM whitelist')
        self.c.execute('DELETE FROM sys_users')
        self.c.execute('DELETE FROM punishments')
        self.c.execute('DELETE FROM modules')
        self.c.execute('DELETE FROM limit_roles')
        self.c.execute('DELETE FROM limit_ping_roles')
        self.c.execute('DELETE FROM action_limits')
        self.c.execute('DELETE FROM log_channels')
        
        # Import whitelist
        for item in data.get('whitelist', []):
            self.c.execute('INSERT INTO whitelist VALUES (?, ?)', (item['user_id'], item['actions']))
        
        # Import sys_users
        for user_id in data.get('sys_users', []):
            self.c.execute('INSERT INTO sys_users VALUES (?)', (user_id,))
        
        # Import punishments
        for item in data.get('punishments', []):
            self.c.execute('INSERT INTO punishments VALUES (?, ?, ?)', 
                          (item['action'], item['sanction'], item.get('duree', '0')))
        
        # Import modules
        for item in data.get('modules', []):
            self.c.execute('INSERT INTO modules VALUES (?, ?)', (item['module'], item['status']))
        
        # Import limit_roles
        for item in data.get('limit_roles', []):
            self.c.execute('INSERT INTO limit_roles VALUES (?, ?)', (item['role_id'], item['role_name']))
        
        # Import limit_ping_roles
        for item in data.get('limit_ping_roles', []):
            self.c.execute('INSERT INTO limit_ping_roles VALUES (?, ?)', (item['role_id'], item['role_name']))
        
        # Import action_limits
        for item in data.get('action_limits', []):
            self.c.execute('INSERT INTO action_limits VALUES (?, ?, ?)', 
                          (item['action'], item['nombre'], item['duree']))
        
        # Import log_channels
        for item in data.get('log_channels', []):
            self.c.execute('INSERT INTO log_channels VALUES (?, ?, ?)',
                          (item['guild_id'], item['log_type'], item['channel_id']))
        
        self.conn.commit()
    
    def add_whitelist(self, user_id: int, actions: str):
        self.c.execute('INSERT OR REPLACE INTO whitelist VALUES (?, ?)', (user_id, actions))
        self.conn.commit()
    
    def remove_whitelist(self, user_id: int):
        self.c.execute('DELETE FROM whitelist WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def get_whitelist(self):
        self.c.execute('SELECT user_id, actions FROM whitelist')
        return self.c.fetchall()
    
    def is_whitelisted(self, user_id: int, action: str = None):
        self.c.execute('SELECT actions FROM whitelist WHERE user_id = ?', (user_id,))
        result = self.c.fetchone()
        if not result:
            return False
        if action:
            return action in result[0].split(',')
        return True
    
    def add_sys(self, user_id: int):
        self.c.execute('INSERT OR IGNORE INTO sys_users VALUES (?)', (user_id,))
        self.conn.commit()
    
    def remove_sys(self, user_id: int):
        self.c.execute('DELETE FROM sys_users WHERE user_id = ?', (user_id,))
        self.conn.commit()
    
    def get_sys(self):
        self.c.execute('SELECT user_id FROM sys_users')
        return self.c.fetchall()
    
    def is_sys(self, user_id: int):
        self.c.execute('SELECT 1 FROM sys_users WHERE user_id = ?', (user_id,))
        return self.c.fetchone() is not None
    
    def set_punishment(self, action: str, sanction: str, duree: str = "0"):
        self.c.execute('INSERT OR REPLACE INTO punishments VALUES (?, ?, ?)', (action, sanction, duree))
        self.conn.commit()
    
    def get_punishment(self, action: str):
        self.c.execute('SELECT sanction, duree FROM punishments WHERE action = ?', (action,))
        result = self.c.fetchone()
        return result if result else (None, "0")
    
    def set_module_status(self, module: str, status: int):
        self.c.execute('INSERT OR REPLACE INTO modules VALUES (?, ?)', (module, status))
        self.conn.commit()
    
    def get_module_status(self, module: str):
        self.c.execute('SELECT status FROM modules WHERE module = ?', (module,))
        result = self.c.fetchone()
        return result[0] if result else 0
    
    def add_limit_role(self, role_id: int, role_name: str):
        self.c.execute('INSERT OR IGNORE INTO limit_roles VALUES (?, ?)', (role_id, role_name))
        self.conn.commit()
    
    def remove_limit_role(self, role_id: int):
        self.c.execute('DELETE FROM limit_roles WHERE role_id = ?', (role_id,))
        self.conn.commit()
    
    def get_limit_roles(self):
        self.c.execute('SELECT role_id, role_name FROM limit_roles')
        return self.c.fetchall()
    
    def is_limit_role(self, role_id: int):
        self.c.execute('SELECT 1 FROM limit_roles WHERE role_id = ?', (role_id,))
        return self.c.fetchone() is not None
    
    def add_limit_ping_role(self, role_id: int, role_name: str):
        self.c.execute('INSERT OR IGNORE INTO limit_ping_roles VALUES (?, ?)', (role_id, role_name))
        self.conn.commit()
    
    def remove_limit_ping_role(self, role_id: int):
        self.c.execute('DELETE FROM limit_ping_roles WHERE role_id = ?', (role_id,))
        self.conn.commit()
    
    def get_limit_ping_roles(self):
        self.c.execute('SELECT role_id, role_name FROM limit_ping_roles')
        return self.c.fetchall()
    
    def is_limit_ping_role(self, role_id: int):
        self.c.execute('SELECT 1 FROM limit_ping_roles WHERE role_id = ?', (role_id,))
        return self.c.fetchone() is not None
    
    def set_action_limit(self, action: str, nombre: int, duree: str):
        self.c.execute('INSERT OR REPLACE INTO action_limits VALUES (?, ?, ?)', (action, nombre, duree))
        self.conn.commit()
    
    def get_action_limit(self, action: str):
        self.c.execute('SELECT nombre, duree FROM action_limits WHERE action = ?', (action,))
        result = self.c.fetchone()
        return result if result else (None, None)
    
    def save_guild_backup(self, guild):
        """Sauvegarde l'état actuel du serveur"""
        icon_url = str(guild.icon.url) if guild.icon else None
        banner_url = str(guild.banner.url) if guild.banner else None
        
        self.c.execute('''INSERT OR REPLACE INTO guild_backup 
                         (guild_id, name, icon_url, banner_url, vanity_code, verification_level, backup_time)
                         VALUES (?, ?, ?, ?, ?, ?, ?)''',
                      (guild.id, guild.name, icon_url, banner_url, 
                       guild.vanity_url_code, guild.verification_level.value, 
                       datetime.now()))
        self.conn.commit()
    
    def get_guild_backup(self, guild_id):
        """Récupère la sauvegarde du serveur"""
        self.c.execute('SELECT * FROM guild_backup WHERE guild_id = ?', (guild_id,))
        return self.c.fetchone()
    
    def set_log_channel(self, guild_id: int, channel_id: int, log_type: str):
        """Configure un salon de logs"""
        self.c.execute('INSERT OR REPLACE INTO log_channels VALUES (?, ?, ?)',
                      (guild_id, log_type, channel_id))
        self.conn.commit()
    
    def get_log_channel(self, guild_id: int, log_type: str):
        """Récupère le salon de logs pour un type"""
        self.c.execute('SELECT channel_id FROM log_channels WHERE guild_id = ? AND log_type = ?',
                      (guild_id, log_type))
        result = self.c.fetchone()
        return result[0] if result else None
    
    def remove_log_channel(self, guild_id: int, log_type: str):
        """Supprime un salon de logs"""
        self.c.execute('DELETE FROM log_channels WHERE guild_id = ? AND log_type = ?',
                      (guild_id, log_type))
        self.conn.commit()
    
    def get_all_log_channels(self, guild_id: int):
        """Récupère tous les salons de logs d'un serveur"""
        self.c.execute('SELECT log_type, channel_id FROM log_channels WHERE guild_id = ?',
                      (guild_id,))
        return dict(self.c.fetchall())

# Le bot
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.members = True
intents.moderation = True

class SecurityBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix='!', intents=intents)
        self.db = Database()
        self.tracker = ActionTracker()
        self.asset_manager = GuildAssetManager()
        self.guild_invites = {}
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"Bot prêt: {self.user}")
        
        # Sauvegarder les assets de tous les serveurs au démarrage
        for guild in self.guilds:
            await self.asset_manager.backup_guild_assets(guild)
            self.db.save_guild_backup(guild)
    
    async def on_guild_remove(self, guild):
        # Notification quand le bot est kick
        for owner_id in OWNER_IDS:
            try:
                user = await self.fetch_user(owner_id)
                await user.send("j'ai ete kick")
            except:
                pass
    
    async def on_guild_join(self, guild):
        # Sauvegarder les assets du nouveau serveur
        await self.asset_manager.backup_guild_assets(guild)
        self.db.save_guild_backup(guild)
        
        # Récupérer les invitations du serveur
        try:
            invites = await guild.invites()
            self.guild_invites[guild.id] = invites
        except:
            pass
        
        # Notification quand le bot est ajouté à un serveur
        for owner_id in OWNER_IDS:
            try:
                user = await self.fetch_user(owner_id)
                # Créer une invitation
                try:
                    channel = guild.system_channel or guild.text_channels[0]
                    invite = await channel.create_invite(max_age=3600, max_uses=1)
                    lien = invite.url
                except:
                    lien = "Impossible de créer un lien"
                
                await user.send(f"{self.user} ma ajouter dans {guild.name}\nLien : {lien}")
            except:
                pass

bot = SecurityBot()

# Vérifications
def is_owner():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id in OWNER_IDS:
            return True
        embed = discord.Embed(
            title="Permission refusée",
            description="Tu n'as pas les permissions nécessaires",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_admin():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id in ADMIN_IDS:
            return True
        embed = discord.Embed(
            title="Permission refusée",
            description="Tu n'as pas les permissions nécessaires",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_sys():
    async def predicate(interaction: discord.Interaction):
        if bot.db.is_sys(interaction.user.id):
            return True
        embed = discord.Embed(
            title="Permission refusée",
            description="Tu n'as pas les permissions nécessaires",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_sys_or_owner():
    async def predicate(interaction: discord.Interaction):
        if (interaction.user.id in OWNER_IDS or bot.db.is_sys(interaction.user.id)):
            return True
        embed = discord.Embed(
            title="Permission refusée",
            description="Tu n'as pas les permissions nécessaires",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)

def is_sys_or_wl():
    async def predicate(interaction: discord.Interaction):
        if (interaction.user.id in OWNER_IDS or 
            bot.db.is_sys(interaction.user.id) or 
            bot.db.is_whitelisted(interaction.user.id)):
            return True
        embed = discord.Embed(
            title="Permission refusée",
            description="Tu n'as pas les permissions nécessaires",
            color=0xFFFFFF
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)
        return False
    return app_commands.check(predicate)

# Fonctions utilitaires
def parse_duration(duration_str: str) -> Optional[timedelta]:
    """Convertit une chaîne de durée en timedelta"""
    if not duration_str or duration_str == "0":
        return None
    
    unit = duration_str[-1]
    value = int(duration_str[:-1])
    
    if unit == 's':
        return timedelta(seconds=value)
    elif unit == 'm':
        return timedelta(minutes=value)
    elif unit == 'h':
        return timedelta(hours=value)
    elif unit == 'd':
        return timedelta(days=value)
    else:
        return None

def create_log_embed(action: str, user: discord.User, punition: str = None, 
                     role: discord.Role = None, nombre: int = None, 
                     temps: str = None, modification: str = None,
                     details: str = None):
    """Crée un embed de log au format demandé"""
    
    if action == "mentionné un rôle limité" and role:
        # Format spécial pour antiping avec le rôle
        description = f"`@{user}` à mentionné un rôle limité (@{role.name}), je l'ai donc {punition} du serveur."
    
    elif action == "banni un membre" and nombre and temps:
        # Format spécial pour antiban avec nombre et temps
        description = f"`@{user}` à banni {nombre} membres en {temps}, je l'ai donc {punition} du serveur."
    
    elif action == "modifié le serveur" and modification:
        # Format spécial pour antimodif
        description = f"`@{user}` à modifier {modification} du serveur, je l'ai donc {punition} du serveur."
    
    elif punition:
        # Format standard avec punition
        description = f"`@{user}` à {action}, je l'ai donc {punition} du serveur."
    else:
        # Format sans punition
        description = f"`@{user}` à {action}."
    
    embed = discord.Embed(
        title=f"# {action}",
        description=description,
        color=0xFFFFFF
    )
    
    if details and action not in ["mentionné un rôle limité", "banni un membre", "modifié le serveur"]:
        embed.add_field(name="Détails", value=details, inline=False)
    
    return embed

async def send_punishment_log(bot, guild_id: int, log_type: str, action: str, 
                               user: discord.User, punition: str = None, 
                               role: discord.Role = None, nombre: int = None,
                               temps: str = None, modification: str = None,
                               details: str = None):
    """Envoie un log de punition au format demandé"""
    channel_id = bot.db.get_log_channel(guild_id, log_type)
    if not channel_id:
        return
    
    guild = bot.get_guild(guild_id)
    if not guild:
        return
    
    channel = guild.get_channel(channel_id)
    if not channel:
        return
    
    embed = create_log_embed(action, user, punition, role, nombre, temps, modification, details)
    
    try:
        await channel.send(embed=embed)
    except:
        pass

async def apply_sanction(member: discord.Member, action: str, reason: str, count: int = None):
    """Applique une sanction à un utilisateur"""
    sanction, duree = bot.db.get_punishment(action)
    
    # Notification en DM
    try:
        if count:
            await member.send(f"{member.mention} a effectué {count} changements")
    except:
        pass
    
    if sanction == 'kick':
        try:
            await member.kick(reason=reason)
            # Notifier les owners
            for owner_id in OWNER_IDS:
                try:
                    user = await bot.fetch_user(owner_id)
                    await user.send(f"{member.mention} ma kick du serveur")
                except:
                    pass
        except:
            pass
    
    elif sanction == 'ban':
        try:
            await member.ban(reason=reason)
        except:
            pass
    
    elif sanction == 'derank':
        try:
            await member.edit(roles=[], reason=reason)
        except:
            pass
    
    elif sanction == 'tempmute' and duree != "0":
        try:
            duration = parse_duration(duree)
            if duration:
                await member.timeout(duration, reason=reason)
        except:
            pass

# Commandes de backup
@bot.tree.command(name="savedb", description="Sauvegarder la base de données")
@is_admin()
async def savedb(interaction: discord.Interaction):
    await interaction.response.defer()
    
    try:
        data = bot.db.export_db()
        json_data = json.dumps(data, indent=2)
        file = discord.File(io.BytesIO(json_data.encode()), filename="security_backup.json")
        
        embed = discord.Embed(
            title="Backup Database",
            description="✅ Sauvegarde effectuée avec succès",
            color=0xFFFFFF
        )
        await interaction.followup.send(embed=embed, file=file)
    except Exception as e:
        embed = discord.Embed(
            title="Erreur",
            description=f"❌ Erreur lors de la sauvegarde : {str(e)}",
            color=0xFFFFFF
        )
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="setdb", description="Restaurer la base de données")
@app_commands.describe(fichier="Fichier JSON de backup")
@is_admin()
async def setdb(interaction: discord.Interaction, fichier: discord.Attachment):
    await interaction.response.defer()
    
    try:
        if not fichier.filename.endswith('.json'):
            embed = discord.Embed(
                title="Erreur",
                description="❌ Le fichier doit être au format JSON",
                color=0xFFFFFF
            )
            await interaction.followup.send(embed=embed)
            return
        
        file_content = await fichier.read()
        data = json.loads(file_content)
        bot.db.import_db(data)
        
        embed = discord.Embed(
            title="Restoration Database",
            description="✅ Base de données restaurée avec succès",
            color=0xFFFFFF
        )
        await interaction.followup.send(embed=embed)
    except json.JSONDecodeError:
        embed = discord.Embed(
            title="Erreur",
            description="❌ Fichier JSON invalide",
            color=0xFFFFFF
        )
        await interaction.followup.send(embed=embed)
    except Exception as e:
        embed = discord.Embed(
            title="Erreur",
            description=f"❌ Erreur lors de la restauration : {str(e)}",
            color=0xFFFFFF
        )
        await interaction.followup.send(embed=embed)

# Commande /set pour configurer les limites
@bot.tree.command(name="set", description="Configurer les limites d'actions")
@app_commands.describe(
    action="L'action à configurer",
    nombre="Nombre d'actions autorisées",
    duree="Durée (ex: 10s, 5m, 1h)"
)
@app_commands.choices(action=[
    app_commands.Choice(name="antideco", value="antideco"),
    app_commands.Choice(name="antiban", value="antiban"),
    app_commands.Choice(name="antirole", value="antirole"),
    app_commands.Choice(name="antichannel", value="antichannel"),
    app_commands.Choice(name="antiping", value="antiping"),
    app_commands.Choice(name="antimodif", value="antimodif")
])
@is_owner()
async def set_action_limit(interaction: discord.Interaction, action: str, nombre: int, duree: str):
    bot.db.set_action_limit(action, nombre, duree)
    
    action_names = {
        'antideco': 'déconnexions vocales',
        'antiban': 'bans',
        'antirole': 'modifications de rôles',
        'antichannel': 'modifications de salons',
        'antiping': 'mentions de rôles',
        'antimodif': 'modifications du serveur'
    }
    
    embed = discord.Embed(
        title="Configuration des limites",
        description=f"**{action_names.get(action, action)}**\nNombre: {nombre}\nDurée: {duree}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

# Commande /punition
@bot.tree.command(name="punition", description="Gérer les punitions pour chaque action")
@app_commands.describe(
    action="L'action à configurer",
    sanction="La sanction à appliquer",
    duree="Durée pour tempmute (ex: 10m, 1h, 1d) - optionnel"
)
@app_commands.choices(action=[
    app_commands.Choice(name="antibot", value="antibot"),
    app_commands.Choice(name="antilink", value="antilink"),
    app_commands.Choice(name="antiping", value="antiping"),
    app_commands.Choice(name="antideco", value="antideco"),
    app_commands.Choice(name="antichannel", value="antichannel"),
    app_commands.Choice(name="antirank", value="antirank"),
    app_commands.Choice(name="antiban", value="antiban"),
    app_commands.Choice(name="antimodif", value="antimodif")
])
@app_commands.choices(sanction=[
    app_commands.Choice(name="derank", value="derank"),
    app_commands.Choice(name="tempmute", value="tempmute"),
    app_commands.Choice(name="kick", value="kick"),
    app_commands.Choice(name="ban", value="ban")
])
@is_owner()
async def punition(interaction: discord.Interaction, action: str, sanction: str, duree: str = "0"):
    bot.db.set_punishment(action, sanction, duree)
    
    embed = discord.Embed(
        title="Configuration des punitions",
        description=f"**{action}** : {sanction}" + (f" (durée: {duree})" if duree != "0" else ""),
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

# Commandes de configuration des modules
@bot.tree.command(name="antilink", description="Activer/désactiver la protection anti-lien")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antilink(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antilink', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-link : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antilink a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antilink', 1)

@bot.tree.command(name="antibot", description="Activer/désactiver la protection anti-bot")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antibot(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antibot', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-bot : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antibot a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antibot', 1)

@bot.tree.command(name="antiban", description="Activer/désactiver la protection anti-ban")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antiban(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antiban', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-ban : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antiban a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antiban', 1)

@bot.tree.command(name="antiping", description="Activer/désactiver la protection anti-ping")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antiping(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antiping', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-ping : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antiping a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antiping', 1)

@bot.tree.command(name="antideco", description="Activer/désactiver la protection anti-déco")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antideco(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antideco', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-deco : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antideco a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antideco', 1)

@bot.tree.command(name="antichannel", description="Activer/désactiver la protection anti-channel")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antichannel(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antichannel', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-channel : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antichannel a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antichannel', 1)

@bot.tree.command(name="antirank", description="Activer/désactiver la protection anti-rank")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antirank(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antirank', status)
    embed = discord.Embed(
        title="Configuration",
        description=f"Anti-rank : {'activé' if status else 'désactivé'}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antirank a ete change")
        except:
            pass
    
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antirank', 1)

@bot.tree.command(name="antimodif", description="Activer/désactiver la protection anti-modification du serveur")
@app_commands.describe(status="On/Off")
@app_commands.choices(status=[
    app_commands.Choice(name="on", value=1),
    app_commands.Choice(name="off", value=0)
])
@is_owner()
async def antimodif(interaction: discord.Interaction, status: int):
    bot.db.set_module_status('antimodif', status)
    
    if status == 1:
        bot.db.save_guild_backup(interaction.guild)
        await bot.asset_manager.backup_guild_assets(interaction.guild)
        description = "✅ Anti-modification activé\nÉtat du serveur sauvegardé"
    else:
        description = "❌ Anti-modification désactivé"
    
    embed = discord.Embed(
        title="Configuration",
        description=description,
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)
    
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antimodif a ete change")
        except:
            pass

# Commandes de whitelist
@bot.tree.command(name="add-wl", description="Ajouter un utilisateur à la whitelist")
@app_commands.describe(
    user="L'utilisateur à ajouter",
    action="Les actions (séparées par des virgules: link,ping,deco,channel,rank,bot,ban,guild)"
)
@is_sys_or_owner()
async def add_wl(interaction: discord.Interaction, user: discord.User, action: str):
    bot.db.add_whitelist(user.id, action)
    embed = discord.Embed(
        title="Whitelist",
        description=f"{user.mention} ajouté à la whitelist pour: {action}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="del-wl", description="Enlever un utilisateur de la whitelist")
@app_commands.describe(user="L'utilisateur à enlever")
@is_sys_or_owner()
async def del_wl(interaction: discord.Interaction, user: discord.User):
    bot.db.remove_whitelist(user.id)
    embed = discord.Embed(
        title="Whitelist",
        description=f"{user.mention} enlevé de la whitelist",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="list-wl", description="Afficher la liste des utilisateurs whitelist")
@is_sys_or_owner()
async def list_wl(interaction: discord.Interaction):
    whitelist = bot.db.get_whitelist()
    
    if not whitelist:
        embed = discord.Embed(
            title="**Liste des utilisateurs whitelist**",
            description="Aucun utilisateur dans la whitelist",
            color=0xFFFFFF
        )
    else:
        description = ""
        for i, (user_id, actions) in enumerate(whitelist, 1):
            user = bot.get_user(user_id) or f"Utilisateur inconnu ({user_id})"
            description += f"``{i}` {user} - Wl pour {actions}`\n"
            description += f"`{user_id}`\n---\n"
        
        embed = discord.Embed(
            title="**Liste des utilisateurs whitelist**",
            description=description,
            color=0xFFFFFF
        )
    
    await interaction.response.send_message(embed=embed)

# Commandes sys
@bot.tree.command(name="sys", description="Attribuer le grade sys")
@app_commands.describe(user="L'utilisateur à qui attribuer le grade")
@is_owner()
async def sys_add(interaction: discord.Interaction, user: discord.User):
    bot.db.add_sys(user.id)
    embed = discord.Embed(
        title="Grade sys",
        description=f"{user.mention} a maintenant le grade sys",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="unsys", description="Enlever le grade sys")
@app_commands.describe(user="L'utilisateur à qui enlever le grade")
@is_owner()
async def sys_remove(interaction: discord.Interaction, user: discord.User):
    bot.db.remove_sys(user.id)
    embed = discord.Embed(
        title="Grade sys",
        description=f"{user.mention} n'a plus le grade sys",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="list-sys", description="Afficher la liste des utilisateurs sys")
@is_sys_or_owner()
async def list_sys(interaction: discord.Interaction):
    sys_users = bot.db.get_sys()
    
    if not sys_users:
        embed = discord.Embed(
            title="**Liste des utilisateurs sys**",
            description="Aucun utilisateur sys",
            color=0xFFFFFF
        )
    else:
        description = ""
        for i, (user_id,) in enumerate(sys_users, 1):
            user = bot.get_user(user_id) or f"Utilisateur inconnu ({user_id})"
            description += f"``{i}` {user}`\n"
            description += f"`{user_id}`\n---\n"
        
        embed = discord.Embed(
            title="**Liste des utilisateurs sys**",
            description=description,
            color=0xFFFFFF
        )
    
    await interaction.response.send_message(embed=embed)

# Commandes rôles limités
@bot.tree.command(name="add-limitrole", description="Ajouter un rôle limité")
@app_commands.describe(role="Le rôle à limiter")
@is_owner()
async def add_limitrole(interaction: discord.Interaction, role: discord.Role):
    bot.db.add_limit_role(role.id, role.name)
    embed = discord.Embed(
        title="Rôles limités",
        description=f"{role.mention} est maintenant un rôle limité",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="del-limitrole", description="Enlever un rôle limité")
@app_commands.describe(role="Le rôle à ne plus limiter")
@is_owner()
async def del_limitrole(interaction: discord.Interaction, role: discord.Role):
    bot.db.remove_limit_role(role.id)
    embed = discord.Embed(
        title="Rôles limités",
        description=f"{role.mention} n'est plus un rôle limité",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="limit-list", description="Afficher la liste des rôles limités")
@is_sys_or_wl()
async def limit_list(interaction: discord.Interaction):
    limit_roles = bot.db.get_limit_roles()
    
    if not limit_roles:
        embed = discord.Embed(
            title="**Liste des rôles limités**",
            description="Aucun rôle limité",
            color=0xFFFFFF
        )
    else:
        description = ""
        for role_id, role_name in limit_roles:
            role = interaction.guild.get_role(role_id)
            if role:
                description += f"{role.mention}\n"
            else:
                description += f"@{role_name}\n"
        
        embed = discord.Embed(
            title="**Liste des rôles limités**",
            description=description,
            color=0xFFFFFF
        )
        embed.set_footer(text=f"rôles : {len(limit_roles)}")
    
    await interaction.response.send_message(embed=embed)

# Commandes pour les rôles à ping limité
@bot.tree.command(name="limit-ping", description="Configurer les rôles à ping limité")
@app_commands.describe(
    action="Ajouter ou enlever",
    role="Le rôle à configurer"
)
@app_commands.choices(action=[
    app_commands.Choice(name="add", value="add"),
    app_commands.Choice(name="remove", value="remove")
])
@is_owner()
async def limit_ping(interaction: discord.Interaction, action: str, role: discord.Role):
    if action == "add":
        bot.db.add_limit_ping_role(role.id, role.name)
        embed = discord.Embed(
            title="Configuration des pings limités",
            description=f"{role.mention} est maintenant un rôle à ping limité",
            color=0xFFFFFF
        )
    else:
        bot.db.remove_limit_ping_role(role.id)
        embed = discord.Embed(
            title="Configuration des pings limités",
            description=f"{role.mention} n'est plus un rôle à ping limité",
            color=0xFFFFFF
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="list-limit-ping", description="Afficher la liste des rôles à ping limité")
@is_sys_or_wl()
async def list_limit_ping(interaction: discord.Interaction):
    limit_roles = bot.db.get_limit_ping_roles()
    
    if not limit_roles:
        embed = discord.Embed(
            title="**Liste des rôles à ping limité**",
            description="Aucun rôle configuré",
            color=0xFFFFFF
        )
    else:
        description = ""
        for role_id, role_name in limit_roles:
            role = interaction.guild.get_role(role_id)
            if role:
                description += f"{role.mention}\n"
            else:
                description += f"@{role_name}\n"
        
        embed = discord.Embed(
            title="**Liste des rôles à ping limité**",
            description=description,
            color=0xFFFFFF
        )
        embed.set_footer(text=f"rôles : {len(limit_roles)}")
    
    await interaction.response.send_message(embed=embed)

# Commandes de logs
@bot.tree.command(name="setlogs", description="Configurer les salons de logs")
@app_commands.describe(
    type="Type de logs à configurer",
    channel="Le salon pour les logs (laisser vide pour désactiver)"
)
@app_commands.choices(type=[
    app_commands.Choice(name="📝 Modération", value="moderation"),
    app_commands.Choice(name="📋 Tous", value="all")
])
@is_owner()
async def setlogs(interaction: discord.Interaction, type: str, channel: Optional[discord.TextChannel] = None):
    
    if type == "all":
        if channel:
            bot.db.set_log_channel(interaction.guild.id, channel.id, "moderation")
            description = f"✅ Logs de modération configurés dans {channel.mention}"
        else:
            bot.db.remove_log_channel(interaction.guild.id, "moderation")
            description = "❌ Logs de modération désactivés"
    else:
        if channel:
            bot.db.set_log_channel(interaction.guild.id, channel.id, type)
            description = f"✅ Logs **{type}** configurés dans {channel.mention}"
        else:
            bot.db.remove_log_channel(interaction.guild.id, type)
            description = f"❌ Logs **{type}** désactivés"
    
    embed = discord.Embed(
        title="Configuration des logs",
        description=description,
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="logs-status", description="Voir la configuration des logs")
@is_owner()
async def logs_status(interaction: discord.Interaction):
    logs = bot.db.get_all_log_channels(interaction.guild.id)
    
    if not logs:
        embed = discord.Embed(
            title="📋 Configuration des logs",
            description="Aucun salon de logs configuré",
            color=0xFFFFFF
        )
    else:
        description = ""
        for log_type, channel_id in logs.items():
            channel = interaction.guild.get_channel(channel_id)
            if channel:
                description += f"**{log_type.capitalize()}** : {channel.mention}\n"
            else:
                description += f"**{log_type.capitalize()}** : Salon introuvable\n"
        
        embed = discord.Embed(
            title="📋 Configuration des logs",
            description=description,
            color=0xFFFFFF
        )
    
    await interaction.response.send_message(embed=embed)

# Événements de protection
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Anti-link
    if bot.db.get_module_status('antilink'):
        if re.search(DISCORD_INVITE_REGEX, message.content, re.IGNORECASE):
            if not (bot.db.is_sys(message.author.id) or bot.db.is_whitelisted(message.author.id, 'link')):
                await message.delete()
                
                try:
                    await message.author.send(f"{message.author.mention} vous n'êtes pas autorisé à envoyer des liens")
                except:
                    pass
                
                sanction, _ = bot.db.get_punishment('antilink')
                if sanction in ['kick', 'ban']:
                    await apply_sanction(message.author, 'antilink', "Anti-link")
                    
                    await send_punishment_log(
                        bot, message.guild.id, "moderation",
                        "envoyé un lien", message.author, sanction
                    )
    
    # Anti-ping (mentions de rôles limités)
    if bot.db.get_module_status('antiping') and message.role_mentions:
        can_mention = bot.db.is_sys(message.author.id) or bot.db.is_whitelisted(message.author.id, 'ping')
        
        for role in message.role_mentions:
            if bot.db.is_limit_ping_role(role.id) and not can_mention:
                await message.delete()
                
                try:
                    await message.author.send(f"{message.author.mention} vous n'êtes pas autorisé à mentionner le rôle {role.mention}")
                except:
                    pass
                
                bot.tracker.add_action(message.author.id, 'role_ping')
                
                nombre, duree = bot.db.get_action_limit('antiping')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(message.author.id, 'role_ping', duree_secondes)
                    
                    if count >= nombre:
                        sanction, _ = bot.db.get_punishment('antiping')
                        await apply_sanction(message.author, 'antiping', "Anti-ping: mentions de rôles limités", count)
                        
                        await send_punishment_log(
                            bot, message.guild.id, "moderation",
                            "mentionné un rôle limité", message.author, sanction,
                            role=role, nombre=count, temps=duree
                        )
                break
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    if member.bot:
        for owner_id in OWNER_IDS:
            try:
                user = await bot.fetch_user(owner_id)
                await user.send(f"{member.name} a ete ajoute au serveur {member.guild.name}")
            except:
                pass
    
    # Anti-bot
    if bot.db.get_module_status('antibot') and member.bot:
        await asyncio.sleep(1)
        
        async for entry in member.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
            if entry.target.id == member.id:
                inviter = entry.user
                
                if not (bot.db.is_sys(inviter.id) or bot.db.is_whitelisted(inviter.id, 'bot')):
                    sanction, _ = bot.db.get_punishment('antibot')
                    
                    try:
                        await inviter.send(f"{inviter.mention} a effectué 1 changement (ajout de bot)")
                    except:
                        pass
                    
                    if sanction == 'kick':
                        try:
                            await inviter.kick(reason="Anti-bot: ajout de bot non autorisé")
                            await member.kick(reason="Anti-bot")
                            
                            await send_punishment_log(
                                bot, member.guild.id, "moderation",
                                "ajouté un bot", inviter, sanction,
                                details=f"Bot: {member.name}"
                            )
                        except:
                            pass
                    elif sanction == 'ban':
                        try:
                            await inviter.ban(reason="Anti-bot: ajout de bot non autorisé")
                            await member.ban(reason="Anti-bot")
                            
                            await send_punishment_log(
                                bot, member.guild.id, "moderation",
                                "ajouté un bot", inviter, sanction,
                                details=f"Bot: {member.name}"
                            )
                        except:
                            pass
                break

@bot.event
async def on_member_ban(guild, user):
    if bot.db.get_module_status('antiban'):
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'ban')):
                    bot.tracker.add_action(entry.user.id, 'ban')
                    
                    nombre, duree = bot.db.get_action_limit('antiban')
                    if nombre and duree:
                        duree_secondes = int(duree[:-1])
                        count = bot.tracker.get_recent_actions(entry.user.id, 'ban', duree_secondes)
                        
                        if count >= nombre:
                            sanction, _ = bot.db.get_punishment('antiban')
                            await apply_sanction(entry.user, 'antiban', "Anti-ban: trop de bans", count)
                            
                            await send_punishment_log(
                                bot, guild.id, "moderation",
                                "banni un membre", entry.user, sanction,
                                nombre=count, temps=duree,
                                details=f"Membre: {user.name}"
                            )
                    break

@bot.event
async def on_voice_state_update(member, before, after):
    if bot.db.get_module_status('antideco'):
        if before.channel and not after.channel:
            if not (bot.db.is_sys(member.id) or bot.db.is_whitelisted(member.id, 'deco')):
                bot.tracker.add_action(member.id, 'deco')
                
                nombre, duree = bot.db.get_action_limit('antideco')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(member.id, 'deco', duree_secondes)
                    
                    if count >= nombre:
                        sanction, _ = bot.db.get_punishment('antideco')
                        await apply_sanction(member, 'antideco', "Anti-deco: trop de déconnexions", count)
                        
                        await send_punishment_log(
                            bot, member.guild.id, "moderation",
                            "déconnecté trop de fois", member, sanction,
                            nombre=count, temps=duree
                        )

@bot.event
async def on_guild_channel_create(channel):
    if bot.db.get_module_status('antichannel'):
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'channel')):
                bot.tracker.add_action(entry.user.id, 'channel_create')
                
                nombre, duree = bot.db.get_action_limit('antichannel')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(entry.user.id, 'channel_create', duree_secondes)
                    
                    if count >= nombre:
                        await channel.delete()
                        sanction, _ = bot.db.get_punishment('antichannel')
                        await apply_sanction(entry.user, 'antichannel', "Anti-channel: trop de salons créés", count)
                        
                        await send_punishment_log(
                            bot, channel.guild.id, "moderation",
                            "créé un salon", entry.user, sanction,
                            nombre=count, temps=duree,
                            details=f"Salon: {channel.name}"
                        )
                    else:
                        await channel.delete()
                break

@bot.event
async def on_guild_channel_delete(channel):
    if bot.db.get_module_status('antichannel'):
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'channel')):
                bot.tracker.add_action(entry.user.id, 'channel_delete')
                
                nombre, duree = bot.db.get_action_limit('antichannel')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(entry.user.id, 'channel_delete', duree_secondes)
                    
                    if count >= nombre:
                        sanction, _ = bot.db.get_punishment('antichannel')
                        await apply_sanction(entry.user, 'antichannel', "Anti-channel: trop de salons supprimés", count)
                        
                        await send_punishment_log(
                            bot, channel.guild.id, "moderation",
                            "supprimé un salon", entry.user, sanction,
                            nombre=count, temps=duree,
                            details=f"Salon: {channel.name}"
                        )
                break

@bot.event
async def on_guild_channel_update(before, after):
    if bot.db.get_module_status('antichannel'):
        if before.name != after.name or before.category != after.category or before.overwrites != after.overwrites:
            async for entry in before.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
                if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'channel')):
                    bot.tracker.add_action(entry.user.id, 'channel_update')
                    
                    nombre, duree = bot.db.get_action_limit('antichannel')
                    if nombre and duree:
                        duree_secondes = int(duree[:-1])
                        count = bot.tracker.get_recent_actions(entry.user.id, 'channel_update', duree_secondes)
                        
                        if count >= nombre:
                            try:
                                await after.edit(name=before.name, category=before.category, overwrites=before.overwrites)
                            except:
                                pass
                            
                            sanction, _ = bot.db.get_punishment('antichannel')
                            await apply_sanction(entry.user, 'antichannel', "Anti-channel: trop de salons modifiés", count)
                            
                            await send_punishment_log(
                                bot, before.guild.id, "moderation",
                                "modifié un salon", entry.user, sanction,
                                nombre=count, temps=duree,
                                details=f"Salon: {after.name}"
                            )
                        else:
                            try:
                                await after.edit(name=before.name, category=before.category, overwrites=before.overwrites)
                            except:
                                pass
                    break

@bot.event
async def on_guild_role_create(role):
    if bot.db.get_module_status('antirank'):
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                bot.tracker.add_action(entry.user.id, 'role_create')
                
                nombre, duree = bot.db.get_action_limit('antirole')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(entry.user.id, 'role_create', duree_secondes)
                    
                    if count >= nombre:
                        await role.delete()
                        sanction, _ = bot.db.get_punishment('antirank')
                        await apply_sanction(entry.user, 'antirank', "Anti-role: trop de rôles créés", count)
                        
                        await send_punishment_log(
                            bot, role.guild.id, "moderation",
                            "créé un rôle", entry.user, sanction,
                            nombre=count, temps=duree,
                            details=f"Rôle: {role.name}"
                        )
                    else:
                        await role.delete()
                break

@bot.event
async def on_guild_role_delete(role):
    if bot.db.get_module_status('antirank'):
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                bot.tracker.add_action(entry.user.id, 'role_delete')
                
                nombre, duree = bot.db.get_action_limit('antirole')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(entry.user.id, 'role_delete', duree_secondes)
                    
                    if count >= nombre:
                        sanction, _ = bot.db.get_punishment('antirank')
                        await apply_sanction(entry.user, 'antirank', "Anti-role: trop de rôles supprimés", count)
                        
                        await send_punishment_log(
                            bot, role.guild.id, "moderation",
                            "supprimé un rôle", entry.user, sanction,
                            nombre=count, temps=duree,
                            details=f"Rôle: {role.name}"
                        )
                break

@bot.event
async def on_guild_role_update(before, after):
    if bot.db.get_module_status('antirank') and before.permissions != after.permissions:
        async for entry in before.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                bot.tracker.add_action(entry.user.id, 'role_update')
                
                nombre, duree = bot.db.get_action_limit('antirole')
                if nombre and duree:
                    duree_secondes = int(duree[:-1])
                    count = bot.tracker.get_recent_actions(entry.user.id, 'role_update', duree_secondes)
                    
                    if count >= nombre:
                        try:
                            await after.edit(permissions=before.permissions)
                        except:
                            pass
                        
                        sanction, _ = bot.db.get_punishment('antirank')
                        await apply_sanction(entry.user, 'antirank', "Anti-role: trop de rôles modifiés", count)
                        
                        await send_punishment_log(
                            bot, before.guild.id, "moderation",
                            "modifié un rôle", entry.user, sanction,
                            nombre=count, temps=duree,
                            details=f"Rôle: {after.name}"
                        )
                    else:
                        try:
                            await after.edit(permissions=before.permissions)
                        except:
                            pass
                break

@bot.event
async def on_guild_update(before, after):
    if bot.db.get_module_status('antimodif'):
        backup = bot.db.get_guild_backup(after.id)
        if not backup:
            bot.db.save_guild_backup(after)
            return
        
        async for entry in after.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'guild')):
                modifications = []
                
                if before.name != after.name:
                    modifications.append("le nom")
                    try:
                        await after.edit(name=backup[1])
                    except:
                        pass
                
                if before.icon != after.icon:
                    modifications.append("la photo")
                    await bot.asset_manager.restore_guild_icon(after)
                
                if before.banner != after.banner:
                    modifications.append("la bannière")
                    await bot.asset_manager.restore_guild_banner(after)
                
                if hasattr(before, 'vanity_url_code') and before.vanity_url_code != after.vanity_url_code:
                    modifications.append("l'url")
                
                if before.verification_level != after.verification_level:
                    modifications.append("le niveau de vérification")
                    try:
                        await after.edit(verification_level=backup[5])
                    except:
                        pass
                
                if modifications:
                    bot.tracker.add_action(entry.user.id, 'guild_modify')
                    
                    if len(modifications) == 1:
                        modif_text = modifications[0]
                    else:
                        modif_text = ", ".join(modifications[:-1]) + " et " + modifications[-1]
                    
                    nombre, duree = bot.db.get_action_limit('antimodif')
                    if nombre and duree:
                        duree_secondes = int(duree[:-1])
                        count = bot.tracker.get_recent_actions(entry.user.id, 'guild_modify', duree_secondes)
                        
                        if count >= nombre:
                            sanction, _ = bot.db.get_punishment('antimodif')
                            await apply_sanction(entry.user, 'antimodif', f"Anti-modif: modification {modif_text}", count)
                            
                            await send_punishment_log(
                                bot, after.id, "moderation",
                                "modifié le serveur", entry.user, sanction,
                                modification=modif_text,
                                details=f"Modifications: {modif_text}"
                            )
                    
                    for owner_id in OWNER_IDS:
                        try:
                            user = await bot.fetch_user(owner_id)
                            await user.send(f"@{entry.user.name} à modifier {modif_text} du serveur")
                        except:
                            pass
                break

@bot.event
async def on_member_update(before, after):
    # Vérification des rôles limités
    if len(before.roles) < len(after.roles):
        new_roles = [r for r in after.roles if r not in before.roles]
        for role in new_roles:
            if bot.db.is_limit_role(role.id):
                if not (bot.db.is_sys(after.id) or bot.db.is_whitelisted(after.id)):
                    await after.remove_roles(role, reason="Rôle limité")

# Lancer le bot
if __name__ == "__main__":
    bot.run(BOT_TOKEN)