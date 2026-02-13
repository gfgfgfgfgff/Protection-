import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
from typing import Optional, List
import re
import os
from config import BOT_TOKEN, OWNER_IDS

# Configuration
DISCORD_INVITE_REGEX = r'(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|com)|discordapp\.com/invite)/[a-zA-Z0-9]+'

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
                          sanction TEXT)''')
        
        # Table pour les status des modules
        self.c.execute('''CREATE TABLE IF NOT EXISTS modules
                         (module TEXT PRIMARY KEY, 
                          status INTEGER)''')
        
        # Table pour les rôles limités
        self.c.execute('''CREATE TABLE IF NOT EXISTS limit_roles
                         (role_id INTEGER PRIMARY KEY,
                          role_name TEXT)''')
        
        # Initialisation des punitions par défaut
        default_punishments = [
            ('antibot', 'kick'),
            ('antilink', 'warn'),
            ('antiping', 'warn'),
            ('antideco', 'warn'),
            ('antichannel', 'derank'),
            ('antirank', 'derank'),
            ('antiban', 'ban')
        ]
        
        for action, sanction in default_punishments:
            self.c.execute('INSERT OR IGNORE INTO punishments VALUES (?, ?)', (action, sanction))
        
        # Initialisation des modules par défaut (désactivés)
        default_modules = [
            ('antibot', 0),
            ('antilink', 0),
            ('antiping', 0),
            ('antideco', 0),
            ('antichannel', 0),
            ('antirank', 0),
            ('antiban', 0)
        ]
        
        for module, status in default_modules:
            self.c.execute('INSERT OR IGNORE INTO modules VALUES (?, ?)', (module, status))
        
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
    
    def set_punishment(self, action: str, sanction: str):
        self.c.execute('INSERT OR REPLACE INTO punishments VALUES (?, ?)', (action, sanction))
        self.conn.commit()
    
    def get_punishment(self, action: str):
        self.c.execute('SELECT sanction FROM punishments WHERE action = ?', (action,))
        result = self.c.fetchone()
        return result[0] if result else None
    
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
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"Bot prêt: {self.user}")
    
    async def on_guild_remove(self, guild):
        # Notification quand le bot est kick
        for owner_id in OWNER_IDS:
            try:
                user = await self.fetch_user(owner_id)
                await user.send("j'ai ete kick")
            except:
                pass
    
    async def on_guild_join(self, guild):
        # Notification quand le bot est ajouté à un serveur
        for owner_id in OWNER_IDS:
            try:
                user = await self.fetch_user(owner_id)
                await user.send(f"{guild.name} a ete ajoute au serveur")
            except:
                pass

bot = SecurityBot()

# Vérification propriétaire
def is_owner():
    async def predicate(interaction: discord.Interaction):
        return interaction.user.id in OWNER_IDS
    return app_commands.check(predicate)

# Vérification sys
def is_sys():
    async def predicate(interaction: discord.Interaction):
        return bot.db.is_sys(interaction.user.id)
    return app_commands.check(predicate)

# Commandes de configuration
@bot.tree.command(name="punition", description="Gerer les punitions pour chaque action")
@app_commands.describe(
    action="L'action a configurer",
    sanction="La sanction a appliquer"
)
@app_commands.choices(action=[
    app_commands.Choice(name="antibot", value="antibot"),
    app_commands.Choice(name="antilink", value="antilink"),
    app_commands.Choice(name="antiping", value="antiping"),
    app_commands.Choice(name="antideco", value="antideco"),
    app_commands.Choice(name="antichannel", value="antichannel"),
    app_commands.Choice(name="antirank", value="antirank"),
    app_commands.Choice(name="antiban", value="antiban")
])
@app_commands.choices(sanction=[
    app_commands.Choice(name="derank", value="derank"),
    app_commands.Choice(name="tempmute", value="tempmute"),
    app_commands.Choice(name="kick", value="kick"),
    app_commands.Choice(name="ban", value="ban")
])
@is_owner()
async def punition(interaction: discord.Interaction, action: str, sanction: str):
    bot.db.set_punishment(action, sanction)
    embed = discord.Embed(
        title="Configuration",
        description=f"Punition pour {action} : {sanction}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="antilink", description="Activer/desactiver la protection anti-lien")
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
    
    # Notification du changement
    for owner_id in OWNER_IDS:
        try:
            user = await bot.fetch_user(owner_id)
            await user.send(f"antilink a ete change")
        except:
            pass
    
    # Remise en configuration si désactivé
    if not status:
        await asyncio.sleep(1)
        bot.db.set_module_status('antilink', 1)

@bot.tree.command(name="antibot", description="Activer/desactiver la protection anti-bot")
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

@bot.tree.command(name="antiban", description="Activer/desactiver la protection anti-ban")
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

@bot.tree.command(name="antiping", description="Activer/desactiver la protection anti-ping")
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

@bot.tree.command(name="antideco", description="Activer/desactiver la protection anti-deco")
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

@bot.tree.command(name="antichannel", description="Activer/desactiver la protection anti-channel")
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

@bot.tree.command(name="antirank", description="Activer/desactiver la protection anti-rank")
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

# Commandes de whitelist
@bot.tree.command(name="add-wl", description="Ajouter un utilisateur a la whitelist")
@app_commands.describe(
    user="L'utilisateur a ajouter",
    action="Les actions pour lesquelles il est whitelist (separer par des virgules)"
)
@is_owner()
async def add_wl(interaction: discord.Interaction, user: discord.User, action: str):
    bot.db.add_whitelist(user.id, action)
    embed = discord.Embed(
        title="Whitelist",
        description=f"{user.mention} ajouté à la whitelist pour: {action}",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="del-wl", description="Enlever un utilisateur de la whitelist")
@app_commands.describe(user="L'utilisateur a enlever")
@is_owner()
async def del_wl(interaction: discord.Interaction, user: discord.User):
    bot.db.remove_whitelist(user.id)
    embed = discord.Embed(
        title="Whitelist",
        description=f"{user.mention} enlevé de la whitelist",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="list-wl", description="Afficher la liste des utilisateurs whitelist")
@is_owner()
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
@app_commands.describe(user="L'utilisateur a qui attribuer le grade")
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
@app_commands.describe(user="L'utilisateur a qui enlever le grade")
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
@is_owner()
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

# Commandes roles limites
@bot.tree.command(name="add-limitrole", description="Ajouter un role limite")
@app_commands.describe(role="Le role a limiter")
@is_owner()
async def add_limitrole(interaction: discord.Interaction, role: discord.Role):
    bot.db.add_limit_role(role.id, role.name)
    embed = discord.Embed(
        title="Roles limites",
        description=f"{role.mention} est maintenant un role limite",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="del-limitrole", description="Enlever un role limite")
@app_commands.describe(role="Le role a ne plus limiter")
@is_owner()
async def del_limitrole(interaction: discord.Interaction, role: discord.Role):
    bot.db.remove_limit_role(role.id)
    embed = discord.Embed(
        title="Roles limites",
        description=f"{role.mention} n'est plus un role limite",
        color=0xFFFFFF
    )
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="limit-list", description="Afficher la liste des roles limites")
async def limit_list(interaction: discord.Interaction):
    limit_roles = bot.db.get_limit_roles()
    
    if not limit_roles:
        embed = discord.Embed(
            title="**Liste des roles limit**",
            description="Aucun role limite",
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
            title="**Liste des roles limit**",
            description=description,
            color=0xFFFFFF
        )
        embed.set_footer(text=f"roles : {len(limit_roles)}")
    
    await interaction.response.send_message(embed=embed)

# Events de protection
@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    # Vérification antilink
    if bot.db.get_module_status('antilink'):
        if re.search(DISCORD_INVITE_REGEX, message.content, re.IGNORECASE):
            # Vérifier si l'utilisateur est sys ou whitelist pour link
            if not (bot.db.is_sys(message.author.id) or bot.db.is_whitelisted(message.author.id, 'link')):
                await message.delete()
                # Appliquer la punition
                sanction = bot.db.get_punishment('antilink')
                if sanction == 'kick':
                    await message.author.kick(reason="Anti-link")
                elif sanction == 'ban':
                    await message.author.ban(reason="Anti-link")
    
    await bot.process_commands(message)

@bot.event
async def on_member_join(member):
    # Vérification antibot
    if bot.db.get_module_status('antibot') and member.bot:
        sanction = bot.db.get_punishment('antibot')
        if sanction == 'kick':
            await member.kick(reason="Anti-bot")
        elif sanction == 'ban':
            await member.ban(reason="Anti-bot")

@bot.event
async def on_member_ban(guild, user):
    # Vérification antiban
    if bot.db.get_module_status('antiban'):
        async for entry in guild.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if entry.target.id == user.id:
                if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'ban')):
                    sanction = bot.db.get_punishment('antiban')
                    if sanction == 'kick':
                        await entry.user.kick(reason="Anti-ban")
                    elif sanction == 'ban':
                        await entry.user.ban(reason="Anti-ban")

@bot.event
async def on_voice_state_update(member, before, after):
    # Vérification antideco
    if bot.db.get_module_status('antideco'):
        if before.channel and not after.channel:
            if not (bot.db.is_sys(member.id) or bot.db.is_whitelisted(member.id, 'deco')):
                sanction = bot.db.get_punishment('antideco')
                if sanction == 'kick':
                    await member.kick(reason="Anti-deco")
                elif sanction == 'ban':
                    await member.ban(reason="Anti-deco")

@bot.event
async def on_guild_channel_create(channel):
    # Vérification antichannel
    if bot.db.get_module_status('antichannel'):
        async for entry in channel.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'channel')):
                await channel.delete()
                sanction = bot.db.get_punishment('antichannel')
                if sanction == 'derank':
                    member = channel.guild.get_member(entry.user.id)
                    if member:
                        await member.edit(roles=[], reason="Anti-channel")
                elif sanction == 'kick':
                    await entry.user.kick(reason="Anti-channel")
                elif sanction == 'ban':
                    await entry.user.ban(reason="Anti-channel")

@bot.event
async def on_guild_role_create(role):
    # Vérification antirank - création de rôle
    if bot.db.get_module_status('antirank'):
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                await role.delete()
                sanction = bot.db.get_punishment('antirank')
                if sanction == 'derank':
                    member = role.guild.get_member(entry.user.id)
                    if member:
                        await member.edit(roles=[], reason="Anti-rank")
                elif sanction == 'kick':
                    await entry.user.kick(reason="Anti-rank")
                elif sanction == 'ban':
                    await entry.user.ban(reason="Anti-rank")

@bot.event
async def on_guild_role_delete(role):
    # Vérification antirank - suppression de rôle
    if bot.db.get_module_status('antirank'):
        async for entry in role.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                sanction = bot.db.get_punishment('antirank')
                if sanction == 'derank':
                    member = role.guild.get_member(entry.user.id)
                    if member:
                        await member.edit(roles=[], reason="Anti-rank: suppression rôle")
                elif sanction == 'kick':
                    await entry.user.kick(reason="Anti-rank: suppression rôle")
                elif sanction == 'ban':
                    await entry.user.ban(reason="Anti-rank: suppression rôle")

@bot.event
async def on_guild_role_update(before, after):
    # Vérification antirank - modification de rôle
    if bot.db.get_module_status('antirank') and before.permissions != after.permissions:
        async for entry in before.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'rank')):
                await after.edit(permissions=before.permissions)
                sanction = bot.db.get_punishment('antirank')
                if sanction == 'derank':
                    member = before.guild.get_member(entry.user.id)
                    if member:
                        await member.edit(roles=[], reason="Anti-rank: modification rôle")
                elif sanction == 'kick':
                    await entry.user.kick(reason="Anti-rank: modification rôle")
                elif sanction == 'ban':
                    await entry.user.ban(reason="Anti-rank: modification rôle")

@bot.event
async def on_member_update(before, after):
    # Vérification des rôles limités
    if len(before.roles) < len(after.roles):
        new_roles = [r for r in after.roles if r not in before.roles]
        for role in new_roles:
            if bot.db.is_limit_role(role.id):
                if not (bot.db.is_sys(after.id) or bot.db.is_whitelisted(after.id)):
                    await after.remove_roles(role, reason="Role limite")
    
    # Vérification antiping (mute)
    if bot.db.get_module_status('antiping'):
        if before.timed_out_until != after.timed_out_until and after.timed_out_until:
            async for entry in after.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_update):
                if not (bot.db.is_sys(entry.user.id) or bot.db.is_whitelisted(entry.user.id, 'ping')):
                    await after.edit(timed_out_until=None)
                    sanction = bot.db.get_punishment('antiping')
                    if sanction == 'kick':
                        await entry.user.kick(reason="Anti-ping")
                    elif sanction == 'ban':
                        await entry.user.ban(reason="Anti-ping")

# Lancer le bot
if __name__ == "__main__":
    bot.run(BOT_TOKEN)