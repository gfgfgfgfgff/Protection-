import discord
from discord.ext import commands
from discord import app_commands
import sqlite3
import asyncio
from typing import Optional, Dict
import re
import os
import io
import json
import time
import aiohttp
import aiofiles
from collections import defaultdict, deque
from datetime import datetime
from config import BOT_TOKEN, OWNER_IDS

DISCORD_INVITE_REGEX = r'(?:https?://)?(?:www\.)?(?:discord\.(?:gg|io|me|com)|discordapp\.com/invite)/[a-zA-Z0-9]+'

class ActionTracker:
    def __init__(self):
        self.user_actions = defaultdict(lambda: deque(maxlen=100))
    
    def add_action(self, user_id: int, action_type: str):
        self.user_actions[user_id].append({
            'type': action_type,
            'timestamp': time.time()
        })
    
    def get_recent_actions(self, user_id: int, action_type: str, seconds: int) -> int:
        cutoff = time.time() - seconds
        return sum(1 for a in self.user_actions[user_id] 
                  if a['type'] == action_type and a['timestamp'] > cutoff)

class GuildAssetManager:
    def __init__(self):
        self.backup_dir = "guild_assets"
        os.makedirs(self.backup_dir, exist_ok=True)
    
    async def backup_guild_assets(self, guild):
        guild_dir = f"{self.backup_dir}/{guild.id}"
        os.makedirs(guild_dir, exist_ok=True)
        if guild.icon:
            await self._download_file(guild.icon.url, f"{guild_dir}/icon.png")
        if guild.banner:
            await self._download_file(guild.banner.url, f"{guild_dir}/banner.png")
    
    async def _download_file(self, url, path):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(url) as r:
                    if r.status == 200:
                        async with aiofiles.open(path, 'wb') as f:
                            await f.write(await r.read())
                            return True
        except: return False
    
    async def restore_guild_icon(self, guild):
        p = f"{self.backup_dir}/{guild.id}/icon.png"
        if os.path.exists(p):
            try:
                async with aiofiles.open(p, 'rb') as f:
                    await guild.edit(icon=await f.read())
                    return True
            except: return False
        return False
    
    async def restore_guild_banner(self, guild):
        p = f"{self.backup_dir}/{guild.id}/banner.png"
        if os.path.exists(p):
            try:
                async with aiofiles.open(p, 'rb') as f:
                    await guild.edit(banner=await f.read())
                    return True
            except: return False
        return False

class Database:
    def __init__(self):
        self.conn = sqlite3.connect('security.db')
        self.c = self.conn.cursor()
        self.init_db()
    
    def init_db(self):
        self.c.execute('''CREATE TABLE IF NOT EXISTS whitelist
                         (user_id INTEGER PRIMARY KEY, actions TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS sys_users
                         (user_id INTEGER PRIMARY KEY)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS punishments
                         (action TEXT PRIMARY KEY, sanction TEXT, duree TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS modules
                         (module TEXT PRIMARY KEY, status INTEGER)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS limit_roles
                         (role_id INTEGER PRIMARY KEY, role_name TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS limit_ping_roles
                         (role_id TEXT PRIMARY KEY, role_name TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS action_limits
                         (action TEXT PRIMARY KEY, nombre INTEGER, duree TEXT)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS guild_backup
                         (guild_id INTEGER PRIMARY KEY, name TEXT, icon_url TEXT,
                          banner_url TEXT, vanity_code TEXT, verification_level INTEGER,
                          backup_time TIMESTAMP)''')
        self.c.execute('''CREATE TABLE IF NOT EXISTS log_channels
                         (guild_id INTEGER, log_type TEXT, channel_id INTEGER,
                          PRIMARY KEY (guild_id, log_type))''')
        
        default_punishments = [
            ('antibot', 'kick', '0'), ('antilink', 'warn', '0'),
            ('antiping', 'warn', '0'), ('antideco', 'warn', '0'),
            ('antichannel', 'derank', '0'), ('antirank', 'derank', '0'),
            ('antiban', 'ban', '0'), ('antimodif', 'derank', '0')
        ]
        for a,s,d in default_punishments:
            self.c.execute('INSERT OR IGNORE INTO punishments VALUES (?,?,?)', (a,s,d))
        
        default_modules = [
            ('antibot',0), ('antilink',0), ('antiping',0), ('antideco',0),
            ('antichannel',0), ('antirank',0), ('antiban',0), ('antimodif',0)
        ]
        for m,s in default_modules:
            self.c.execute('INSERT OR IGNORE INTO modules VALUES (?,?)', (m,s))
        
        default_limits = [
            ('antideco',3,'10s'), ('antiban',1,'10s'), ('antirole',2,'10s'),
            ('antichannel',2,'10s'), ('antiping',5,'10s'), ('antimodif',2,'10s')
        ]
        for a,n,d in default_limits:
            self.c.execute('INSERT OR IGNORE INTO action_limits VALUES (?,?,?)', (a,n,d))
        
        self.conn.commit()
    
    def export_db(self):
        data = {}
        for t in ['whitelist','sys_users','punishments','modules','limit_roles',
                  'limit_ping_roles','action_limits','log_channels']:
            self.c.execute(f'SELECT * FROM {t}')
            data[t] = self.c.fetchall()
        return data
    
    def import_db(self, data):
        for t in ['whitelist','sys_users','punishments','modules','limit_roles',
                  'limit_ping_roles','action_limits','log_channels']:
            self.c.execute(f'DELETE FROM {t}')
            for row in data.get(t, []):
                placeholders = ','.join(['?']*len(row))
                self.c.execute(f'INSERT INTO {t} VALUES ({placeholders})', row)
        self.conn.commit()
    
    def add_whitelist(self, uid, acts): self.c.execute('INSERT OR REPLACE INTO whitelist VALUES (?,?)', (uid,acts)); self.conn.commit()
    def remove_whitelist(self, uid): self.c.execute('DELETE FROM whitelist WHERE user_id=?', (uid,)); self.conn.commit()
    def get_whitelist(self): self.c.execute('SELECT user_id,actions FROM whitelist'); return self.c.fetchall()
    def is_whitelisted(self, uid, act=None):
        self.c.execute('SELECT actions FROM whitelist WHERE user_id=?', (uid,))
        r = self.c.fetchone()
        if not r: return False
        return act in r[0].split(',') if act else True
    
    def add_sys(self, uid): self.c.execute('INSERT OR IGNORE INTO sys_users VALUES (?)', (uid,)); self.conn.commit()
    def remove_sys(self, uid): self.c.execute('DELETE FROM sys_users WHERE user_id=?', (uid,)); self.conn.commit()
    def get_sys(self): self.c.execute('SELECT user_id FROM sys_users'); return self.c.fetchall()
    def is_sys(self, uid): self.c.execute('SELECT 1 FROM sys_users WHERE user_id=?', (uid,)); return self.c.fetchone() is not None
    
    def set_punishment(self, a, s, d='0'): self.c.execute('INSERT OR REPLACE INTO punishments VALUES (?,?,?)', (a,s,d)); self.conn.commit()
    def get_punishment(self, a):
        self.c.execute('SELECT sanction,duree FROM punishments WHERE action=?', (a,))
        return self.c.fetchone() or (None,'0')
    
    def set_module_status(self, m, s): self.c.execute('INSERT OR REPLACE INTO modules VALUES (?,?)', (m,s)); self.conn.commit()
    def get_module_status(self, m):
        self.c.execute('SELECT status FROM modules WHERE module=?', (m,))
        r = self.c.fetchone()
        return r[0] if r else 0
    
    def add_limit_role(self, rid, name): self.c.execute('INSERT OR IGNORE INTO limit_roles VALUES (?,?)', (rid,name)); self.conn.commit()
    def remove_limit_role(self, rid): self.c.execute('DELETE FROM limit_roles WHERE role_id=?', (rid,)); self.conn.commit()
    def get_limit_roles(self): self.c.execute('SELECT role_id,role_name FROM limit_roles'); return self.c.fetchall()
    def is_limit_role(self, rid): self.c.execute('SELECT 1 FROM limit_roles WHERE role_id=?', (rid,)); return self.c.fetchone() is not None
    
    def add_limit_ping_role(self, rid, name): self.c.execute('INSERT OR IGNORE INTO limit_ping_roles VALUES (?,?)', (rid,name)); self.conn.commit()
    def remove_limit_ping_role(self, rid): self.c.execute('DELETE FROM limit_ping_roles WHERE role_id=?', (rid,)); self.conn.commit()
    def get_limit_ping_roles(self): self.c.execute('SELECT role_id,role_name FROM limit_ping_roles'); return self.c.fetchall()
    def is_limit_ping_role(self, rid): self.c.execute('SELECT 1 FROM limit_ping_roles WHERE role_id=?', (rid,)); return self.c.fetchone() is not None
    
    def set_action_limit(self, a, n, d): self.c.execute('INSERT OR REPLACE INTO action_limits VALUES (?,?,?)', (a,n,d)); self.conn.commit()
    def get_action_limit(self, a):
        self.c.execute('SELECT nombre,duree FROM action_limits WHERE action=?', (a,))
        return self.c.fetchone() or (None,None)
    
    def save_guild_backup(self, g):
        self.c.execute('''INSERT OR REPLACE INTO guild_backup VALUES (?,?,?,?,?,?,?)''',
                      (g.id, g.name, str(g.icon.url) if g.icon else None,
                       str(g.banner.url) if g.banner else None, g.vanity_url_code,
                       g.verification_level.value, datetime.now()))
        self.conn.commit()
    
    def get_guild_backup(self, gid):
        self.c.execute('SELECT * FROM guild_backup WHERE guild_id=?', (gid,))
        return self.c.fetchone()
    
    def set_log_channel(self, gid, cid, typ): self.c.execute('INSERT OR REPLACE INTO log_channels VALUES (?,?,?)', (gid,typ,cid)); self.conn.commit()
    def get_log_channel(self, gid, typ):
        self.c.execute('SELECT channel_id FROM log_channels WHERE guild_id=? AND log_type=?', (gid,typ))
        r = self.c.fetchone()
        return r[0] if r else None
    def remove_log_channel(self, gid, typ): self.c.execute('DELETE FROM log_channels WHERE guild_id=? AND log_type=?', (gid,typ)); self.conn.commit()

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
    
    async def setup_hook(self):
        await self.tree.sync()
        print(f"Bot pret: {self.user}")
        for g in self.guilds:
            await self.asset_manager.backup_guild_assets(g)
            self.db.save_guild_backup(g)
    
    async def on_guild_remove(self, g):
        for o in OWNER_IDS:
            try:
                u = await self.fetch_user(o)
                await u.send("j'ai ete kick")
            except: pass
    
    async def on_guild_join(self, g):
        await self.asset_manager.backup_guild_assets(g)
        self.db.save_guild_backup(g)
        inviter = None
        try:
            async for e in g.audit_logs(limit=1, action=discord.AuditLogAction.bot_add):
                if e.target.id == self.user.id:
                    inviter = e.user
                    break
        except: pass
        for o in OWNER_IDS:
            try:
                u = await self.fetch_user(o)
                try:
                    chan = g.system_channel or g.text_channels[0]
                    invite = await chan.create_invite(max_age=3600, max_uses=1)
                    lien = invite.url
                except: lien = "Impossible de creer un lien"
                if inviter:
                    await u.send(f"{inviter.mention} ma ajouter dans {g.name}\nLien : {lien}")
                else:
                    await u.send(f"Quelqu'un ma ajouter dans {g.name}\nLien : {lien}")
            except: pass

bot = SecurityBot()

def is_owner():
    async def p(i):
        if i.user.id in OWNER_IDS: return True
        e = discord.Embed(title="Permission refusee", description="Tu n'as pas les permissions necessaires", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return False
    return app_commands.check(p)

def is_sys():
    async def p(i):
        if bot.db.is_sys(i.user.id): return True
        e = discord.Embed(title="Permission refusee", description="Tu n'as pas les permissions necessaires", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return False
    return app_commands.check(p)

def is_sys_or_owner():
    async def p(i):
        if i.user.id in OWNER_IDS or bot.db.is_sys(i.user.id): return True
        e = discord.Embed(title="Permission refusee", description="Tu n'as pas les permissions necessaires", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return False
    return app_commands.check(p)

def is_sys_or_wl():
    async def p(i):
        if i.user.id in OWNER_IDS or bot.db.is_sys(i.user.id) or bot.db.is_whitelisted(i.user.id): return True
        e = discord.Embed(title="Permission refusee", description="Tu n'as pas les permissions necessaires", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return False
    return app_commands.check(p)

def is_sys_and_wl():
    async def p(i):
        if i.user.id in OWNER_IDS: return True
        if bot.db.is_sys(i.user.id) and bot.db.is_whitelisted(i.user.id): return True
        e = discord.Embed(title="Permission refusee", description="Tu n'as pas les permissions necessaires (sys + wl requis)", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return False
    return app_commands.check(p)

def parse_duration(d):
    if not d or d=='0': return None
    u = d[-1]; v = int(d[:-1])
    if u=='s': return timedelta(seconds=v)
    if u=='m': return timedelta(minutes=v)
    if u=='h': return timedelta(hours=v)
    if u=='d': return timedelta(days=v)
    return None

async def send_punishment_log(bt, gid, typ, act, usr, pun=None, role=None, nb=None, tmp=None, mod=None, suc=True, det=None):
    cid = bt.db.get_log_channel(gid, typ)
    if not cid: return
    g = bt.get_guild(gid)
    if not g: return
    c = g.get_channel(cid)
    if not c: return
    
    if act == "mentionné un rôle limité" and role:
        desc = f"{usr.mention} à mentionné un rôle limité (@{role.name}), je l'ai donc {pun} du serveur." if suc else f"{usr.mention} à mentionné un rôle limité (@{role.name}), mais j'ai pas pu le {pun} du serveur."
    elif act == "banni un membre" and nb and tmp:
        desc = f"{usr.mention} à banni {nb} membres en {tmp}, je l'ai donc {pun} du serveur." if suc else f"{usr.mention} à banni {nb} membres en {tmp}, mais j'ai pas pu le {pun} du serveur."
    elif act == "modifié le serveur" and mod:
        desc = f"{usr.mention} à modifier {mod} du serveur, je l'ai donc {pun} du serveur." if suc else f"{usr.mention} à modifier {mod} du serveur, mais j'ai pas pu le {pun} du serveur."
    else:
        desc = f"{usr.mention} à {act}, je l'ai donc {pun} du serveur." if suc else f"{usr.mention} à {act}, mais j'ai pas pu le {pun} du serveur."
    
    e = discord.Embed(title=f"**{act.upper()}**", description=desc, color=0xFFFFFF)
    if det and act not in ["mentionné un rôle limité","banni un membre","modifié le serveur"]:
        e.add_field(name="Details", value=det, inline=False)
    try: await c.send(embed=e)
    except: pass

async def apply_sanction(m, act, reason, cnt=None):
    s, d = bot.db.get_punishment(act)
    if s == 'kick':
        try:
            await m.kick(reason=reason)
            for o in OWNER_IDS:
                try:
                    u = await bot.fetch_user(o)
                    await u.send(f"{m.mention} ma kick du serveur")
                except: pass
        except: pass
    elif s == 'ban':
        try: await m.ban(reason=reason)
        except: pass
    elif s == 'derank':
        try: await m.edit(roles=[], reason=reason)
        except: pass
    elif s == 'tempmute' and d != '0':
        try:
            dur = parse_duration(d)
            if dur: await m.timeout(dur, reason=reason)
        except: pass

@bot.tree.command(name="secur", description="Configuration securite")
@is_sys_or_wl()
async def secur(i):
    mods = {m:bot.db.get_module_status(m) for m in ['antiban','antibot','antichannel','antideco','antiping','antirank','antimodif']}
    lims = {a:bot.db.get_action_limit(a) for a in ['antiban','antideco','antiping','antirole','antichannel','antimodif']}
    puns = {a:bot.db.get_punishment(a) for a in ['antiban','antibot','antichannel','antideco','antiping','antirank','antimodif']}
    
    desc = ""
    for nom,cle,lim,pun in [
        ("Antiban","antiban","antiban","antiban"),
        ("Antibot","antibot",None,"antibot"),
        ("Antichannel","antichannel","antichannel","antichannel"),
        ("Antideco","antideco","antideco","antideco"),
        ("Antieveryone","antiping","antiping","antiping"),
        ("Antirole","antirank","antirole","antirank"),
        ("Antiupdate","antimodif","antimodif","antimodif")
    ]:
        st = "on" if mods.get(cle,0) else "off"
        if lim:
            nb,dr = lims.get(lim,(0,"0s"))
            desc += f"**{nom}**: {st} {nb}/{dr} - {puns.get(pun,('rien','0'))[0]}\n"
        else:
            desc += f"**{nom}**: {st} - {puns.get(pun,('rien','0'))[0]}\n"
    
    e = discord.Embed(title="# Securite", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="savedb", description="Sauvegarder DB")
@is_sys_and_wl()
async def savedb(i):
    await i.response.defer()
    try:
        d = bot.db.export_db()
        f = discord.File(io.BytesIO(json.dumps(d, indent=2).encode()), filename="backup.json")
        e = discord.Embed(title="Backup", description="Sauvegarde effectuee", color=0xFFFFFF)
        await i.followup.send(embed=e, file=f)
    except Exception as ex:
        e = discord.Embed(title="Erreur", description=f"Erreur: {str(ex)}", color=0xFFFFFF)
        await i.followup.send(embed=e)

@bot.tree.command(name="setdb", description="Restaurer DB")
@app_commands.describe(fichier="Fichier backup")
@is_sys_and_wl()
async def setdb(i, fichier: discord.Attachment):
    await i.response.defer()
    try:
        if not fichier.filename.endswith('.json'):
            e = discord.Embed(title="Erreur", description="Format JSON requis", color=0xFFFFFF)
            await i.followup.send(embed=e); return
        d = json.loads(await fichier.read())
        bot.db.import_db(d)
        e = discord.Embed(title="Restoration", description="DB restauree", color=0xFFFFFF)
        await i.followup.send(embed=e)
    except Exception as ex:
        e = discord.Embed(title="Erreur", description=f"Erreur: {str(ex)}", color=0xFFFFFF)
        await i.followup.send(embed=e)

@bot.tree.command(name="set", description="Configurer limites")
@app_commands.describe(action="Action", nombre="Nombre", duree="Duree (10s,5m,1h)")
@app_commands.choices(action=[
    app_commands.Choice(n="antideco", v="antideco"), app_commands.Choice(n="antiban", v="antiban"),
    app_commands.Choice(n="antirole", v="antirole"), app_commands.Choice(n="antichannel", v="antichannel"),
    app_commands.Choice(n="antiping", v="antiping"), app_commands.Choice(n="antimodif", v="antimodif")
])
@is_owner()
async def set_limit(i, action: str, nombre: int, duree: str):
    bot.db.set_action_limit(action, nombre, duree)
    noms = {'antideco':'decos','antiban':'bans','antirole':'roles','antichannel':'salons','antiping':'pings','antimodif':'modifs'}
    e = discord.Embed(title="Configuration limites", description=f"**{noms.get(action,action)}**\nNombre: {nombre}\nDuree: {duree}", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="punition", description="Configurer punitions")
@app_commands.describe(action="Action", sanction="Sanction", duree="Duree pour tempmute")
@app_commands.choices(action=[
    app_commands.Choice(n="antibot", v="antibot"), app_commands.Choice(n="antilink", v="antilink"),
    app_commands.Choice(n="antiping", v="antiping"), app_commands.Choice(n="antideco", v="antideco"),
    app_commands.Choice(n="antichannel", v="antichannel"), app_commands.Choice(n="antirole", v="antirank"),
    app_commands.Choice(n="antiban", v="antiban"), app_commands.Choice(n="antimodif", v="antimodif")
])
@app_commands.choices(sanction=[
    app_commands.Choice(n="derank", v="derank"), app_commands.Choice(n="tempmute", v="tempmute"),
    app_commands.Choice(n="kick", v="kick"), app_commands.Choice(n="ban", v="ban")
])
@is_owner()
async def punition(i, action: str, sanction: str, duree: str = "0"):
    bot.db.set_punishment(action, sanction, duree)
    txt = f"{action} : {sanction}" + (f" ({duree})" if duree!="0" else "")
    e = discord.Embed(title="Configuration punitions", description=txt, color=0xFFFFFF)
    await i.response.send_message(embed=e)

for mod in ['antilink','antibot','antiban','antiping','antideco','antichannel','antirole','antimodif']:
    @bot.tree.command(name=mod, description=f"Activer/desactiver {mod}")
    @app_commands.describe(status="On/Off")
    @app_commands.choices(status=[app_commands.Choice(n="on",v=1), app_commands.Choice(n="off",v=0)])
    @is_owner()
    async def cmd(i, status: int, m=mod):
        bot.db.set_module_status(m, status)
        e = discord.Embed(title="Configuration", description=f"{m} : {'active' if status else 'desactive'}", color=0xFFFFFF)
        await i.response.send_message(embed=e)
        for o in OWNER_IDS:
            try:
                u = await bot.fetch_user(o)
                await u.send(f"{m} a ete change")
            except: pass
        if not status:
            await asyncio.sleep(1)
            bot.db.set_module_status(m, 1)

@bot.tree.command(name="add-wl", description="Ajouter whitelist")
@app_commands.describe(
    user="Utilisateur",
    link="Liens", ping="Pings", deco="Decos", channel="Salons",
    rank="Roles", bot="Bots", ban="Bans", guild="Serveur"
)
@is_sys_or_owner()
async def add_wl(i, user: discord.User,
    link: Optional[bool]=False, ping: Optional[bool]=False,
    deco: Optional[bool]=False, channel: Optional[bool]=False,
    rank: Optional[bool]=False, bot: Optional[bool]=False,
    ban: Optional[bool]=False, guild: Optional[bool]=False
):
    acts = []
    aff = []
    if link: acts.append("link"); aff.append("liens")
    if ping: acts.append("ping"); aff.append("pings")
    if deco: acts.append("deco"); aff.append("decos")
    if channel: acts.append("channel"); aff.append("salons")
    if rank: acts.append("rank"); aff.append("roles")
    if bot: acts.append("bot"); aff.append("bots")
    if ban: acts.append("ban"); aff.append("bans")
    if guild: acts.append("guild"); aff.append("serveur")
    
    if not acts:
        e = discord.Embed(title="Erreur", description="Selectionne au moins une action", color=0xFFFFFF)
        await i.response.send_message(embed=e, ephemeral=True)
        return
    
    bot.db.add_whitelist(user.id, ",".join(acts))
    if len(aff)==1: desc = f"{user.mention} ajoute pour: **{aff[0]}**"
    else:
        dernier = aff.pop()
        desc = f"{user.mention} ajoute pour: **{', '.join(aff)} et {dernier}**"
    
    e = discord.Embed(title="Whitelist", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="del-wl", description="Enlever whitelist")
@app_commands.describe(user="Utilisateur")
@is_sys_or_owner()
async def del_wl(i, user: discord.User):
    bot.db.remove_whitelist(user.id)
    e = discord.Embed(title="Whitelist", description=f"{user.mention} enleve", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="list-wl", description="Liste whitelist")
@is_sys_or_owner()
async def list_wl(i):
    wl = bot.db.get_whitelist()
    if not wl:
        e = discord.Embed(title="**Liste whitelist**", description="Aucun utilisateur", color=0xFFFFFF)
    else:
        desc = ""
        for n,(uid,acts) in enumerate(wl,1):
            u = bot.get_user(uid) or f"Inconnu({uid})"
            desc += f"``{n}` {u} - {acts}`\n`{uid}`\n---\n"
        e = discord.Embed(title="**Liste whitelist**", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="sys", description="Ajouter sys")
@app_commands.describe(user="Utilisateur")
@is_owner()
async def sys_add(i, user: discord.User):
    bot.db.add_sys(user.id)
    e = discord.Embed(title="Grade sys", description=f"{user.mention} a maintenant le grade sys", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="unsys", description="Enlever sys")
@app_commands.describe(user="Utilisateur")
@is_owner()
async def sys_remove(i, user: discord.User):
    bot.db.remove_sys(user.id)
    e = discord.Embed(title="Grade sys", description=f"{user.mention} n'a plus le grade sys", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="list-sys", description="Liste sys")
@is_sys_or_owner()
async def list_sys(i):
    sys = bot.db.get_sys()
    if not sys:
        e = discord.Embed(title="**Liste sys**", description="Aucun utilisateur", color=0xFFFFFF)
    else:
        desc = ""
        for n,(uid,) in enumerate(sys,1):
            u = bot.get_user(uid) or f"Inconnu({uid})"
            desc += f"``{n}` {u}`\n`{uid}`\n---\n"
        e = discord.Embed(title="**Liste sys**", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="add-limitrole", description="Ajouter role limite")
@app_commands.describe(role="Role")
@is_owner()
async def add_limitrole(i, role: discord.Role):
    bot.db.add_limit_role(role.id, role.name)
    e = discord.Embed(title="Roles limites", description=f"{role.mention} est maintenant un role limite", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="del-limitrole", description="Enlever role limite")
@app_commands.describe(role="Role")
@is_owner()
async def del_limitrole(i, role: discord.Role):
    bot.db.remove_limit_role(role.id)
    e = discord.Embed(title="Roles limites", description=f"{role.mention} n'est plus un role limite", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="limit-list", description="Liste roles limites")
@is_sys_or_wl()
async def limit_list(i):
    roles = bot.db.get_limit_roles()
    if not roles:
        e = discord.Embed(title="**Liste roles limites**", description="Aucun role", color=0xFFFFFF)
    else:
        desc = ""
        for rid,name in roles:
            r = i.guild.get_role(rid)
            desc += f"{r.mention if r else '@'+name}\n"
        e = discord.Embed(title="**Liste roles limites**", description=desc, color=0xFFFFFF)
        e.set_footer(text=f"roles : {len(roles)}")
    await i.response.send_message(embed=e)

@bot.tree.command(name="limit-ping", description="Configurer pings limites")
@app_commands.describe(action="Add/Remove", cible="@role/@everyone/@here")
@app_commands.choices(action=[app_commands.Choice(n="add",v="add"), app_commands.Choice(n="remove",v="remove")])
@is_owner()
async def limit_ping(i, action: str, cible: str):
    if cible.lower() in ["@everyone","@here","everyone","here"]:
        nom = cible.lower().replace("@","")
        if action=="add":
            bot.db.add_limit_ping_role(f"special_{nom}", nom)
            desc = f"{cible} est maintenant une mention limitee"
        else:
            bot.db.remove_limit_ping_role(f"special_{nom}")
            desc = f"{cible} n'est plus une mention limitee"
        e = discord.Embed(title="Configuration pings", description=desc, color=0xFFFFFF)
    else:
        try:
            role = await commands.RoleConverter().convert(i, cible)
            if action=="add":
                bot.db.add_limit_ping_role(str(role.id), role.name)
                desc = f"{role.mention} est maintenant un role a ping limite"
            else:
                bot.db.remove_limit_ping_role(str(role.id))
                desc = f"{role.mention} n'est plus un role a ping limite"
            e = discord.Embed(title="Configuration pings", description=desc, color=0xFFFFFF)
        except:
            e = discord.Embed(title="Erreur", description="Cible invalide", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="list-limit-ping", description="Liste pings limites")
@is_sys_or_wl()
async def list_limit_ping(i):
    roles = bot.db.get_limit_ping_roles()
    if not roles:
        e = discord.Embed(title="**Liste pings limites**", description="Aucune configuration", color=0xFFFFFF)
    else:
        desc = ""
        for rid,name in roles:
            if rid.startswith("special_"):
                desc += f"@{name}\n"
            else:
                r = i.guild.get_role(int(rid))
                desc += f"{r.mention if r else '@'+name}\n"
        e = discord.Embed(title="**Liste pings limites**", description=desc, color=0xFFFFFF)
        e.set_footer(text=f"elements : {len(roles)}")
    await i.response.send_message(embed=e)

@bot.tree.command(name="setlogs", description="Configurer logs publics")
@app_commands.describe(salon="Salon (vide pour desactiver)")
@is_owner()
async def setlogs(i, salon: Optional[discord.TextChannel] = None):
    if salon:
        bot.db.set_log_channel(i.guild.id, salon.id, "moderation")
        desc = f"Logs configures dans {salon.mention}"
    else:
        bot.db.remove_log_channel(i.guild.id, "moderation")
        desc = "Logs desactives"
    e = discord.Embed(title="Configuration logs", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="logs-status", description="Status logs publics")
@is_owner()
async def logs_status(i):
    cid = bot.db.get_log_channel(i.guild.id, "moderation")
    if not cid:
        e = discord.Embed(title="Logs publics", description="Aucun salon configure", color=0xFFFFFF)
    else:
        c = i.guild.get_channel(cid)
        e = discord.Embed(title="Logs publics", description=f"Salon : {c.mention if c else 'introuvable'}", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="logsown", description="Configurer logs prives")
@app_commands.describe(salon="Salon (vide pour desactiver)")
@is_owner()
async def logsown(i, salon: Optional[discord.TextChannel] = None):
    if salon:
        bot.db.set_log_channel(i.guild.id, salon.id, "owner_logs")
        desc = f"Logs prives configures dans {salon.mention}"
    else:
        bot.db.remove_log_channel(i.guild.id, "owner_logs")
        desc = "Logs prives desactives"
    e = discord.Embed(title="Configuration logs prives", description=desc, color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.tree.command(name="logsown-status", description="Status logs prives")
@is_owner()
async def logsown_status(i):
    cid = bot.db.get_log_channel(i.guild.id, "owner_logs")
    if not cid:
        e = discord.Embed(title="Logs prives", description="Aucun salon configure", color=0xFFFFFF)
    else:
        c = i.guild.get_channel(cid)
        e = discord.Embed(title="Logs prives", description=f"Salon : {c.mention if c else 'introuvable'}", color=0xFFFFFF)
    await i.response.send_message(embed=e)

@bot.event
async def on_message(msg):
    if msg.author.bot: return
    
    if bot.db.get_module_status('antilink'):
        if re.search(DISCORD_INVITE_REGEX, msg.content, re.IGNORECASE):
            if not (bot.db.is_sys(msg.author.id) or bot.db.is_whitelisted(msg.author.id, 'link')):
                await msg.delete()
                await msg.channel.send(f"{msg.author.mention} vous n'etes pas autorise a envoyer des liens")
                s,_ = bot.db.get_punishment('antilink')
                suc = True
                try:
                    if s=='kick': await msg.author.kick(reason="Anti-link")
                    elif s=='ban': await msg.author.ban(reason="Anti-link")
                except: suc = False
                await send_punishment_log(bot, msg.guild.id, "moderation", "envoye un lien", msg.author, s, suc=suc)
    
    if bot.db.get_module_status('antiping'):
        can = bot.db.is_sys(msg.author.id) or bot.db.is_whitelisted(msg.author.id, 'ping')
        if msg.mention_everyone:
            if bot.db.is_limit_ping_role("special_everyone") and not can:
                await msg.delete()
                await msg.channel.send(f"{msg.author.mention} vous n'etes pas autorise a utiliser @everyone")
                bot.tracker.add_action(msg.author.id, 'everyone_ping')
                n,d = bot.db.get_action_limit('antiping')
                if n and d:
                    sec = int(d[:-1])
                    if bot.tracker.get_recent_actions(msg.author.id, 'everyone_ping', sec) >= n:
                        s,_ = bot.db.get_punishment('antiping')
                        await apply_sanction(msg.author, 'antiping', "Anti-ping: @everyone", n)
                        await send_punishment_log(bot, msg.guild.id, "moderation", "mentionne @everyone", msg.author, s, nb=n, tmp=d)
        if msg.role_mentions:
            for r in msg.role_mentions:
                if bot.db.is_limit_ping_role(str(r.id)) and not can:
                    await msg.delete()
                    await msg.channel.send(f"{msg.author.mention} vous n'etes pas autorise a mentionner le role `@{r.name}`")
                    bot.tracker.add_action(msg.author.id, 'role_ping')
                    n,d = bot.db.get_action_limit('antiping')
                    if n and d:
                        sec = int(d[:-1])
                        if bot.tracker.get_recent_actions(msg.author.id, 'role_ping', sec) >= n:
                            s,_ = bot.db.get_punishment('antiping')
                            await apply_sanction(msg.author, 'antiping', "Anti-ping: roles limites", n)
                            await send_punishment_log(bot, msg.guild.id, "moderation", "mentionne un role limite", msg.author, s, role=r, nb=n, tmp=d)
                    break
    
    await bot.process_commands(msg)

@bot.event
async def on_member_join(m):
    if m.bot:
        for o in OWNER_IDS:
            try:
                u = await bot.fetch_user(o)
                await u.send(f"{m.name} a ete ajoute au serveur {m.guild.name}")
            except: pass
        
        if bot.db.get_module_status('antibot'):
            await asyncio.sleep(1)
            async for e in m.guild.audit_logs(limit=5, action=discord.AuditLogAction.bot_add):
                if e.target.id == m.id:
                    inv = e.user
                    if not (bot.db.is_sys(inv.id) or bot.db.is_whitelisted(inv.id, 'bot')):
                        s,_ = bot.db.get_punishment('antibot')
                        suc = True
                        try:
                            if s=='kick':
                                await inv.kick(reason="Anti-bot")
                                await m.kick(reason="Anti-bot")
                            elif s=='ban':
                                await inv.ban(reason="Anti-bot")
                                await m.ban(reason="Anti-bot")
                            elif s=='derank':
                                await inv.edit(roles=[], reason="Anti-bot")
                                await m.kick(reason="Anti-bot")
                        except: suc = False
                        await send_punishment_log(bot, m.guild.id, "owner_logs", "ajoute un bot", inv, s, suc=suc, det=f"Bot: {m.name}")
                    break

@bot.event
async def on_member_ban(g, u):
    if bot.db.get_module_status('antiban'):
        async for e in g.audit_logs(limit=1, action=discord.AuditLogAction.ban):
            if e.target.id == u.id:
                if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'ban')):
                    bot.tracker.add_action(e.user.id, 'ban')
                    n,d = bot.db.get_action_limit('antiban')
                    if n and d:
                        sec = int(d[:-1])
                        cnt = bot.tracker.get_recent_actions(e.user.id, 'ban', sec)
                        if cnt >= n:
                            s,_ = bot.db.get_punishment('antiban')
                            await apply_sanction(e.user, 'antiban', "Anti-ban: trop de bans", cnt)
                            await send_punishment_log(bot, g.id, "owner_logs", "banni un membre", e.user, s, nb=cnt, tmp=d, det=f"Membre: {u.name}")
                break

@bot.event
async def on_voice_state_update(m, b, a):
    if bot.db.get_module_status('antideco'):
        if (b.channel and not a.channel) or (b.channel and a.channel and b.channel != a.channel):
            async for e in m.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_disconnect):
                if e.target.id == m.id:
                    mod = e.user
                    typ = "deconnecte"
                    break
            else:
                async for e in m.guild.audit_logs(limit=1, action=discord.AuditLogAction.member_move):
                    if e.target.id == m.id:
                        mod = e.user
                        typ = "deplace"
                        break
                else: return
            
            if not (bot.db.is_sys(mod.id) or bot.db.is_whitelisted(mod.id, 'deco')):
                bot.tracker.add_action(mod.id, 'deco')
                n,d = bot.db.get_action_limit('antideco')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(mod.id, 'deco', sec)
                    if cnt >= n:
                        s,_ = bot.db.get_punishment('antideco')
                        await apply_sanction(mod, 'antideco', f"Anti-deco: trop de {typ}s forces", cnt)
                        await send_punishment_log(bot, m.guild.id, "moderation", f"{typ} un membre", mod, s, nb=cnt, tmp=d, det=f"Membre: {m.name}")

@bot.event
async def on_guild_channel_create(c):
    if bot.db.get_module_status('antichannel'):
        async for e in c.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_create):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'channel')):
                bot.tracker.add_action(e.user.id, 'channel_create')
                n,d = bot.db.get_action_limit('antichannel')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(e.user.id, 'channel_create', sec)
                    if cnt >= n:
                        await c.delete()
                        s,_ = bot.db.get_punishment('antichannel')
                        await apply_sanction(e.user, 'antichannel', "Anti-channel: trop de creations", cnt)
                        await send_punishment_log(bot, c.guild.id, "owner_logs", "cree un salon", e.user, s, nb=cnt, tmp=d, det=f"Salon: {c.name}")
                    else: await c.delete()
                break

@bot.event
async def on_guild_channel_delete(c):
    if bot.db.get_module_status('antichannel'):
        async for e in c.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_delete):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'channel')):
                bot.tracker.add_action(e.user.id, 'channel_delete')
                n,d = bot.db.get_action_limit('antichannel')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(e.user.id, 'channel_delete', sec)
                    if cnt >= n:
                        s,_ = bot.db.get_punishment('antichannel')
                        await apply_sanction(e.user, 'antichannel', "Anti-channel: trop de suppressions", cnt)
                        await send_punishment_log(bot, c.guild.id, "owner_logs", "supprime un salon", e.user, s, nb=cnt, tmp=d, det=f"Salon: {c.name}")
                break

@bot.event
async def on_guild_channel_update(b,a):
    if bot.db.get_module_status('antichannel'):
        if b.name!=a.name or b.category!=a.category or b.overwrites!=a.overwrites:
            async for e in b.guild.audit_logs(limit=1, action=discord.AuditLogAction.channel_update):
                if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'channel')):
                    bot.tracker.add_action(e.user.id, 'channel_update')
                    n,d = bot.db.get_action_limit('antichannel')
                    if n and d:
                        sec = int(d[:-1])
                        cnt = bot.tracker.get_recent_actions(e.user.id, 'channel_update', sec)
                        try: await a.edit(name=b.name, category=b.category, overwrites=b.overwrites)
                        except: pass
                        if cnt >= n:
                            s,_ = bot.db.get_punishment('antichannel')
                            await apply_sanction(e.user, 'antichannel', "Anti-channel: trop de modifications", cnt)
                            await send_punishment_log(bot, b.guild.id, "owner_logs", "modifie un salon", e.user, s, nb=cnt, tmp=d, det=f"Salon: {a.name}")
                    break

@bot.event
async def on_guild_role_create(r):
    if bot.db.get_module_status('antirank'):
        async for e in r.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_create):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'rank')):
                bot.tracker.add_action(e.user.id, 'role_create')
                n,d = bot.db.get_action_limit('antirole')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(e.user.id, 'role_create', sec)
                    if cnt >= n:
                        await r.delete()
                        s,_ = bot.db.get_punishment('antirank')
                        await apply_sanction(e.user, 'antirank', "Anti-role: trop de creations", cnt)
                        await send_punishment_log(bot, r.guild.id, "owner_logs", "cree un role", e.user, s, nb=cnt, tmp=d, det=f"Role: {r.name}")
                    else: await r.delete()
                break

@bot.event
async def on_guild_role_delete(r):
    if bot.db.get_module_status('antirank'):
        async for e in r.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_delete):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'rank')):
                bot.tracker.add_action(e.user.id, 'role_delete')
                n,d = bot.db.get_action_limit('antirole')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(e.user.id, 'role_delete', sec)
                    if cnt >= n:
                        s,_ = bot.db.get_punishment('antirank')
                        await apply_sanction(e.user, 'antirank', "Anti-role: trop de suppressions", cnt)
                        await send_punishment_log(bot, r.guild.id, "owner_logs", "supprime un role", e.user, s, nb=cnt, tmp=d, det=f"Role: {r.name}")
                break

@bot.event
async def on_guild_role_update(b,a):
    if bot.db.get_module_status('antirank') and b.permissions != a.permissions:
        async for e in b.guild.audit_logs(limit=1, action=discord.AuditLogAction.role_update):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'rank')):
                bot.tracker.add_action(e.user.id, 'role_update')
                n,d = bot.db.get_action_limit('antirole')
                if n and d:
                    sec = int(d[:-1])
                    cnt = bot.tracker.get_recent_actions(e.user.id, 'role_update', sec)
                    try: await a.edit(permissions=b.permissions)
                    except: pass
                    if cnt >= n:
                        s,_ = bot.db.get_punishment('antirank')
                        await apply_sanction(e.user, 'antirank', "Anti-role: trop de modifications", cnt)
                        await send_punishment_log(bot, b.guild.id, "owner_logs", "modifie un role", e.user, s, nb=cnt, tmp=d, det=f"Role: {a.name}")
                break

@bot.event
async def on_guild_update(b,a):
    if bot.db.get_module_status('antimodif'):
        bk = bot.db.get_guild_backup(a.id)
        if not bk:
            bot.db.save_guild_backup(a)
            return
        
        async for e in a.audit_logs(limit=1, action=discord.AuditLogAction.guild_update):
            if not (bot.db.is_sys(e.user.id) or bot.db.is_whitelisted(e.user.id, 'guild')):
                mods = []
                if b.name != a.name:
                    mods.append("le nom")
                    try: await a.edit(name=bk[1])
                    except: pass
                if b.icon != a.icon:
                    mods.append("la photo")
                    await bot.asset_manager.restore_guild_icon(a)
                if b.banner != a.banner:
                    mods.append("la banniere")
                    await bot.asset_manager.restore_guild_banner(a)
                if hasattr(b,'vanity_url_code') and b.vanity_url_code != a.vanity_url_code:
                    mods.append("l'url")
                if b.verification_level != a.verification_level:
                    mods.append("le niveau de verification")
                    try: await a.edit(verification_level=bk[5])
                    except: pass
                
                if mods:
                    bot.tracker.add_action(e.user.id, 'guild_modify')
                    txt = mods[0] if len(mods)==1 else ", ".join(mods[:-1]) + " et " + mods[-1]
                    n,d = bot.db.get_action_limit('antimodif')
                    if n and d:
                        sec = int(d[:-1])
                        cnt = bot.tracker.get_recent_actions(e.user.id, 'guild_modify', sec)
                        if cnt >= n:
                            s,_ = bot.db.get_punishment('antimodif')
                            await apply_sanction(e.user, 'antimodif', f"Anti-modif: {txt}", cnt)
                            await send_punishment_log(bot, a.id, "owner_logs", "modifie le serveur", e.user, s, mod=txt, nb=cnt, tmp=d)
                    
                    for o in OWNER_IDS:
                        try:
                            u = await bot.fetch_user(o)
                            await u.send(f"@{e.user.name} à modifier {txt} du serveur")
                        except: pass
                break

@bot.event
async def on_member_update(b,a):
    if len(b.roles) < len(a.roles):
        new = [r for r in a.roles if r not in b.roles]
        for r in new:
            if bot.db.is_limit_role(r.id):
                if not (bot.db.is_sys(a.id) or bot.db.is_whitelisted(a.id)):
                    await a.remove_roles(r, reason="Role limite")

if __name__ == "__main__":
    bot.run(BOT_TOKEN)