import aiosqlite
import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

DB_NAME = "bot_database.db"
logger = logging.getLogger("DatabaseEngine")

# -------------------------------------------------------------
# إعدادات السيرفر: المخطط، القيم الافتراضية، والتحقق
# -------------------------------------------------------------
# key -> (sql type, default, python kind)
SETTINGS_SCHEMA: Dict[str, Tuple[str, Any, str]] = {
    "prefix": ("TEXT", "!", "str"),
    "anti_nuke": ("INTEGER", True, "bool"),
    "anti_alt_days": ("INTEGER", 3, "int"),
    "welcome_channel_id": ("INTEGER", None, "id"),
    "leave_channel_id": ("INTEGER", None, "id"),
    "welcome_message": ("TEXT", "", "str"),
    "welcome_embed_enabled": ("INTEGER", False, "bool"),
    "welcome_embed_color": ("TEXT", "#7c3aed", "str"),
    "welcome_embed_title": ("TEXT", "أهلاً بك في {server} ✨", "str"),
    "welcome_embed_description": ("TEXT", "", "str"),
    "welcome_embed_image_url": ("TEXT", "", "str"),
    "welcome_embed_sticker_id": ("INTEGER", None, "id"),
    "welcome_embed_footer": ("TEXT", "PRIME | TEAM • تطوير abood2026", "str"),
    "welcome_embed_show_avatar": ("INTEGER", True, "bool"),
    "auto_role_id": ("INTEGER", None, "id"),
    "log_channel_id": ("INTEGER", None, "id"),
    "captcha_enabled": ("INTEGER", False, "bool"),
    "captcha_role_id": ("INTEGER", None, "id"),
    "welcome_dm_enabled": ("INTEGER", False, "bool"),
    "member_auto_role_id": ("INTEGER", None, "id"),
    "bot_auto_role_id": ("INTEGER", None, "id"),
    "verified_role_id": ("INTEGER", None, "id"),
    "unverified_role_id": ("INTEGER", None, "id"),
    "rules_channel_id": ("INTEGER", None, "id"),
    "leave_message": ("TEXT", "", "str"),
    "economy_tax": ("REAL", 0.0, "float"),
    "daily_amount": ("INTEGER", 450, "int"),
    # Economy expansion settings (kept additive to the legacy daily_amount).
    "leaderboard_channel_id": ("INTEGER", 0, "id"),
    "leaderboard_message_id": ("INTEGER", 0, "id"),
    "daily_base_amount": ("INTEGER", 200, "int"),
    "level_multiplier_pct": ("INTEGER", 10, "int"),
    "role_multipliers": ("TEXT", {}, "json_map"),
    "economy_support_role_ids": ("TEXT", [], "json_list"),
    # أعمدة قديمة يتم الإبقاء عليها للتوافق
    "anti_spam_enabled": ("INTEGER", True, "bool"),
    "anti_link_enabled": ("INTEGER", True, "bool"),
    # إعدادات Auto-Mod الحديثة
    "anti_invites": ("INTEGER", True, "bool"),
    "anti_links": ("INTEGER", True, "bool"),
    "anti_spam": ("INTEGER", True, "bool"),
    "anti_mass_mention": ("INTEGER", True, "bool"),
    "banned_words_list": ("TEXT", [], "json_list"),
}
SETTINGS_DEFAULTS: Dict[str, Any] = {k: v[1] for k, v in SETTINGS_SCHEMA.items()}
# الأعمدة القديمة التي تُغذّي الأعمدة الجديدة عند الترحيل (new <- legacy)
LEGACY_ALIASES = {
    "welcome_channel_id": "welcome_channel",
    "log_channel_id": "mod_log_channel",
    "anti_spam": "anti_spam_enabled",
    "anti_links": "anti_link_enabled",
}

CACHE_TTL = 60.0
CACHE_MAX = 1024
_settings_cache: "OrderedDict[int, Tuple[float, Dict[str, Any]]]" = OrderedDict()
_stats_cache: "OrderedDict[int, Tuple[float, Dict[str, Any]]]" = OrderedDict()
COMMAND_CACHE: Dict[int, Dict[str, Dict[str, Any]]] = {}
LOG_ROUTING_CACHE: Dict[int, Dict[str, int]] = {}
LEGACY_LOG_ROUTING_KEYS = (
    "log_messages",
    "log_roles",
    "log_channels",
    "log_moderation",
    "log_warnings",
    "log_voice",
)
LOG_ROUTING_KEYS = (
    "log_sanctions",
    "log_violations",
    "log_automod",
    "log_ticket",
    "log_channel",
    "log_server",
    "log_member",
    "log_message",
    "log_voice",
    "log_react",
    "log_roles",
)
LOG_ROUTING_ALIASES = {
    "log_moderation": "log_sanctions",
    "log_warnings": "log_violations",
    "log_messages": "log_message",
    "log_channels": "log_channel",
}
LOG_ROUTING_ALL_KEYS = tuple(dict.fromkeys((*LOG_ROUTING_KEYS, *LEGACY_LOG_ROUTING_KEYS)))
_guild_locks: Dict[int, asyncio.Lock] = {}
_db_semaphore: Optional[asyncio.Semaphore] = None


class SettingsConflict(Exception):
    """تعارض في رقم الإصدار: تم تعديل الإعدادات من جهة أخرى."""

    def __init__(self, current: Dict[str, Any]):
        super().__init__("settings revision conflict")
        self.current = current


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


async def _configure(db: aiosqlite.Connection) -> None:
    """تطبيق إعدادات الأداء والسلامة على كل اتصال."""
    await db.execute("PRAGMA foreign_keys = ON;")
    await db.execute("PRAGMA journal_mode = WAL;")
    await db.execute("PRAGMA synchronous = NORMAL;")
    await db.execute("PRAGMA cache_size = -64000;")
    await db.execute("PRAGMA temp_store = MEMORY;")
    await db.execute("PRAGMA busy_timeout = 5000;")


class _Connection:
    """اتصال محدود العدد (الكاش 64MB لكل اتصال) مع تطبيق PRAGMA تلقائياً."""

    def __init__(self, row_factory=None):
        self._row_factory = row_factory
        self._db: Optional[aiosqlite.Connection] = None

    async def __aenter__(self) -> aiosqlite.Connection:
        global _db_semaphore
        if _db_semaphore is None:
            _db_semaphore = asyncio.Semaphore(8)
        await _db_semaphore.acquire()
        try:
            self._db = await aiosqlite.connect(DB_NAME)
            if self._row_factory:
                self._db.row_factory = self._row_factory
            await _configure(self._db)
            return self._db
        except Exception:
            if self._db is not None:
                await self._db.close()
            _db_semaphore.release()
            raise

    async def __aexit__(self, *exc) -> None:
        try:
            await self._db.close()
        finally:
            _db_semaphore.release()


def connect(row_factory=None) -> _Connection:
    return _Connection(row_factory)


async def _migrate_guild_settings(db: aiosqlite.Connection) -> None:
    """إضافة الأعمدة الناقصة فقط دون حذف أي بيانات قديمة، مع تعبئة القيم القديمة."""
    async with db.execute("PRAGMA table_info(guild_settings);") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    wanted = dict(SETTINGS_SCHEMA)
    wanted["revision"] = ("INTEGER", 0, "int")
    wanted["updated_at"] = ("TEXT", None, "str")
    missing = set()
    for column, (sql_type, default, kind) in wanted.items():
        if column in existing:
            continue
        missing.add(column)
        if default is None:
            await db.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} {sql_type} DEFAULT NULL;")
        else:
            if kind in ("bool", "int"):
                literal = str(int(default))
            elif kind == "float":
                literal = repr(float(default))
            else:
                literal = "'" + str(default).replace("'", "''") + "'"
            # ALTER TABLE لا يقبل معاملات مرتبطة في DEFAULT؛ القيم هنا من المخطط الثابت فقط.
            await db.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} {sql_type} DEFAULT {literal};")
    for new_col, legacy in LEGACY_ALIASES.items():
        if legacy in existing and new_col in missing:
            await db.execute(
                f"UPDATE guild_settings SET {new_col} = {legacy} "
                f"WHERE {legacy} IS NOT NULL;"
            )
    await db.execute("UPDATE guild_settings SET revision = 0 WHERE revision IS NULL;")
    await db.execute("UPDATE guild_settings SET updated_at = ? WHERE updated_at IS NULL;", (_utc_now(),))


async def _ensure_canonical_views(db: aiosqlite.Connection) -> None:
    """Expose one stable read contract while preserving existing live tables."""
    views = {
        "infractions": """
            SELECT id, guild_id, user_id, moderator_id AS mod_id,
                   'warning' AS type, reason, timestamp
            FROM warnings
        """,
        "auto_responses": """
            SELECT id, guild_id, trigger AS trigger_word,
                   response AS response_text, match_type
            FROM guild_auto_responders
        """,
        "economy_vault": """
            SELECT user_id, guild_id, balance AS wallet,
                   bank, xp, level
            FROM users
        """,
    }
    for name, query in views.items():
        async with db.execute(
            "SELECT type FROM sqlite_master WHERE name = ?",
            (name,),
        ) as cursor:
            existing = await cursor.fetchone()
        if existing and existing[0] != "view":
            logger.warning(
                "[DB_SCHEMA] canonical name %s is already a table; keeping it intact",
                name,
            )
            continue
        await db.execute(f"CREATE VIEW IF NOT EXISTS {name} AS {query}")


async def _migrate_logging_channels(db: aiosqlite.Connection) -> None:
    """Add the dedicated audit routes without rebuilding the live table."""
    async with db.execute("PRAGMA table_info(logging_channels);") as cur:
        existing = {row[1] for row in await cur.fetchall()}
    missing = [key for key in LOG_ROUTING_KEYS if key not in existing]
    for key in missing:
        await db.execute(
            f"ALTER TABLE logging_channels ADD COLUMN {key} INTEGER DEFAULT 0;"
        )
    # Existing installations used six legacy names. Seed only newly added
    # columns from their matching legacy values, preserving every old value.
    for legacy, dedicated in LOG_ROUTING_ALIASES.items():
        if legacy in existing and dedicated in missing:
            await db.execute(
                f"UPDATE logging_channels SET {dedicated} = {legacy} "
                f"WHERE {legacy} IS NOT NULL AND {legacy} != 0;"
            )


async def _migrate_auto_responder_uniqueness(db: aiosqlite.Connection) -> None:
    """Allow one trigger to have a fallback, role, and member rule together."""
    async with db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'guild_auto_responders'"
    ) as cur:
        row = await cur.fetchone()
    schema = str(row[0] or "") if row else ""
    if "UNIQUE (guild_id, trigger, match_type)" not in schema:
        return

    async with db.execute(
        "SELECT type FROM sqlite_master WHERE name = 'auto_responses'"
    ) as cur:
        canonical = await cur.fetchone()
    if canonical and canonical[0] == "view":
        # ALTER TABLE ... RENAME updates dependent view SQL to the staging
        # name. Drop it before the swap so the canonical view can be rebuilt
        # against the final table name.
        await db.execute("DROP VIEW auto_responses")

    await db.execute("""
        CREATE TABLE guild_auto_responders_v2 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            trigger TEXT NOT NULL,
            match_type TEXT NOT NULL,
            response TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1,
            cooldown_seconds REAL NOT NULL DEFAULT 5,
            bucket_capacity INTEGER NOT NULL DEFAULT 1,
            channel_id INTEGER DEFAULT NULL,
            target_type TEXT NOT NULL DEFAULT 'everyone',
            target_id INTEGER NOT NULL DEFAULT 0,
            reaction_emoji TEXT NOT NULL DEFAULT '',
            execution_count INTEGER NOT NULL DEFAULT 0,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (guild_id, trigger, match_type, target_type, target_id)
        );
    """)
    await db.execute("""
        INSERT INTO guild_auto_responders_v2
            (id, guild_id, trigger, match_type, response, enabled,
             cooldown_seconds, bucket_capacity, channel_id, target_type,
             target_id, reaction_emoji, execution_count, updated_at)
        SELECT id, guild_id, trigger, match_type, response, enabled,
               cooldown_seconds, bucket_capacity, channel_id, target_type,
               target_id, reaction_emoji, execution_count, updated_at
        FROM guild_auto_responders
    """)
    await db.execute("DROP TABLE guild_auto_responders")
    await db.execute(
        "ALTER TABLE guild_auto_responders_v2 RENAME TO guild_auto_responders"
    )


async def init_db() -> None:
    """تهيئة الجداول، العلاقات، والفهارس مع تفعيل قيود المفاتيح الخارجية."""
    try:
        async with connect() as db:

            # 1. جدول الاقتصاد والمستويات
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    xp INTEGER DEFAULT 0,
                    level INTEGER DEFAULT 1,
                    balance INTEGER DEFAULT 100,
                    bank INTEGER DEFAULT 0,
                    last_daily TEXT DEFAULT NULL,
                    PRIMARY KEY (user_id, guild_id)
                );
            """)

            # 2. جدول الإنذارات الإدارية
            await db.execute("""
                CREATE TABLE IF NOT EXISTS warnings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    moderator_id INTEGER NOT NULL,
                    reason TEXT NOT NULL,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 3. جدول إعدادات السيرفر والتذاكر
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    mod_log_channel INTEGER DEFAULT NULL,
                    welcome_channel INTEGER DEFAULT NULL,
                    auto_role_id INTEGER DEFAULT NULL,
                    anti_spam_enabled BOOLEAN DEFAULT 1,
                    anti_link_enabled BOOLEAN DEFAULT 1
                );
            """)
            # ترحيل تدريجي غير مدمّر لبقية الأعمدة (prefix, anti_nuke, captcha, ...)
            await _migrate_guild_settings(db)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS logging_channels (
                    guild_id INTEGER PRIMARY KEY,
                    log_messages INTEGER DEFAULT 0,
                    log_roles INTEGER DEFAULT 0,
                    log_channels INTEGER DEFAULT 0,
                    log_moderation INTEGER DEFAULT 0,
                    log_warnings INTEGER DEFAULT 0,
                    log_voice INTEGER DEFAULT 0,
                    log_sanctions INTEGER DEFAULT 0,
                    log_violations INTEGER DEFAULT 0,
                    log_automod INTEGER DEFAULT 0,
                    log_ticket INTEGER DEFAULT 0,
                    log_channel INTEGER DEFAULT 0,
                    log_server INTEGER DEFAULT 0,
                    log_member INTEGER DEFAULT 0,
                    log_message INTEGER DEFAULT 0,
                    log_react INTEGER DEFAULT 0
                );
            """)
            # Additive migration for the dedicated audit destinations. Existing
            # columns and rows remain untouched; only missing columns are added.
            await _migrate_logging_channels(db)

            # فهارس لتسريع استعلامات الرتب ولوحة الشرف (Leaderboard)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_xp ON users(guild_id, xp DESC);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);")
            await db.execute("""
                CREATE TABLE IF NOT EXISTS level_rewards (
                    guild_id INTEGER NOT NULL,
                    level INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, level, role_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS economy_audit_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    actor_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    wallet_delta INTEGER NOT NULL DEFAULT 0,
                    level_delta INTEGER NOT NULL DEFAULT 0,
                    details TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_economy_audit_guild "
                "ON economy_audit_logs(guild_id, created_at DESC);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS economy_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    from_user_id INTEGER DEFAULT NULL,
                    to_user_id INTEGER DEFAULT NULL,
                    amount INTEGER NOT NULL,
                    kind TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_economy_transactions_guild "
                "ON economy_transactions(guild_id, created_at DESC);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournament_scores (
                    guild_id INTEGER NOT NULL,
                    team_name TEXT NOT NULL,
                    points INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, team_name)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS giveaways (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL DEFAULT 0,
                    prize TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_by INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS giveaway_entries (
                    giveaway_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (giveaway_id, user_id)
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_giveaways_due "
                "ON giveaways(status, ends_at);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournaments (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL DEFAULT 0,
                    title TEXT NOT NULL,
                    max_players INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_by INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tournament_entries (
                    tournament_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tournament_id, user_id)
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tournaments_open "
                "ON tournaments(status, guild_id);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS invite_stats (
                    guild_id INTEGER NOT NULL,
                    inviter_id INTEGER NOT NULL,
                    uses INTEGER NOT NULL DEFAULT 0,
                    last_used_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, inviter_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rules_agreements (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    verified_role_id INTEGER,
                    agreed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, user_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS role_panels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    role_ids TEXT NOT NULL,
                    PRIMARY KEY (guild_id, channel_id, message_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS rules_panels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    PRIMARY KEY (guild_id, channel_id, message_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS self_role_panels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    color TEXT NOT NULL DEFAULT '#5865f2',
                    emoji TEXT NOT NULL DEFAULT '🏷️',
                    role_specs TEXT NOT NULL DEFAULT '[]',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, message_id)
                );
            """)
            async with db.execute("PRAGMA table_info(self_role_panels)") as cur:
                self_role_panel_columns = {row[1] for row in await cur.fetchall()}
            # The self-role studio predates level-gated panels. Extend its
            # existing rows instead of replacing the live table or its
            # role_specs payload.
            if "min_level" not in self_role_panel_columns:
                await db.execute(
                    "ALTER TABLE self_role_panels ADD COLUMN min_level INTEGER NOT NULL DEFAULT 0"
                )
            if "color_hex" not in self_role_panel_columns:
                await db.execute(
                    "ALTER TABLE self_role_panels ADD COLUMN color_hex TEXT NOT NULL DEFAULT '#5865F2'"
                )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS self_role_buttons (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    panel_id INTEGER NOT NULL,
                    role_id INTEGER NOT NULL,
                    label TEXT NOT NULL,
                    emoji TEXT NOT NULL DEFAULT '',
                    custom_min_level INTEGER NOT NULL DEFAULT 0,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_self_role_buttons_panel "
                "ON self_role_buttons(panel_id, id);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_self_role_panels_guild "
                "ON self_role_panels(guild_id);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_command_controls (
                    guild_id INTEGER NOT NULL,
                    command_name TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    allowed_roles TEXT NOT NULL DEFAULT '[]',
                    allowed_channels TEXT NOT NULL DEFAULT '[]',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, command_name)
                );
            """)
            async with db.execute("PRAGMA table_info(guild_command_controls)") as cur:
                command_control_columns = {row[1] for row in await cur.fetchall()}
            if "allowed_channels" not in command_control_columns:
                await db.execute(
                    "ALTER TABLE guild_command_controls "
                    "ADD COLUMN allowed_channels TEXT NOT NULL DEFAULT '[]'"
                )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_controls_guild "
                "ON guild_command_controls(guild_id);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS command_policies (
                    guild_id INTEGER NOT NULL,
                    command_name TEXT NOT NULL,
                    is_enabled INTEGER NOT NULL DEFAULT 1,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    allowed_roles TEXT NOT NULL DEFAULT '[]',
                    allowed_channels TEXT NOT NULL DEFAULT '[]',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, command_name)
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_policies_guild "
                "ON command_policies(guild_id);"
            )
            async with db.execute("PRAGMA table_info(command_policies)") as cur:
                command_policy_columns = {row[1] for row in await cur.fetchall()}
            policy_migrations = {
                "is_enabled": "INTEGER NOT NULL DEFAULT 1",
                "aliases": "TEXT NOT NULL DEFAULT '[]'",
                "allowed_roles": "TEXT NOT NULL DEFAULT '[]'",
                "allowed_channels": "TEXT NOT NULL DEFAULT '[]'",
                "updated_at": "TEXT DEFAULT NULL",
            }
            for column, definition in policy_migrations.items():
                if column not in command_policy_columns:
                    await db.execute(
                        f"ALTER TABLE command_policies ADD COLUMN {column} {definition}"
                    )
            # Preserve policies created by older dashboard versions while
            # making command_policies the canonical store for new writes.
            await db.execute("""
                INSERT OR IGNORE INTO command_policies
                    (guild_id, command_name, is_enabled, aliases,
                     allowed_roles, allowed_channels, updated_at)
                SELECT guild_id, command_name, enabled, '[]',
                       allowed_roles, allowed_channels, updated_at
                FROM guild_command_controls
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_auto_responders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    trigger TEXT NOT NULL,
                    match_type TEXT NOT NULL,
                    response TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    cooldown_seconds REAL NOT NULL DEFAULT 5,
                    bucket_capacity INTEGER NOT NULL DEFAULT 1,
                    channel_id INTEGER DEFAULT NULL,
                    target_type TEXT NOT NULL DEFAULT 'everyone',
                    target_id INTEGER NOT NULL DEFAULT 0,
                    reaction_emoji TEXT NOT NULL DEFAULT '',
                    execution_count INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, trigger, match_type, target_type, target_id)
                );
            """)
            async with db.execute("PRAGMA table_info(guild_auto_responders)") as cur:
                responder_columns = {row[1] for row in await cur.fetchall()}
            if "channel_id" not in responder_columns:
                await db.execute(
                    "ALTER TABLE guild_auto_responders ADD COLUMN channel_id INTEGER DEFAULT NULL"
                )
            if "execution_count" not in responder_columns:
                await db.execute(
                    "ALTER TABLE guild_auto_responders ADD COLUMN execution_count INTEGER NOT NULL DEFAULT 0"
                )
            if "target_type" not in responder_columns:
                await db.execute(
                    "ALTER TABLE guild_auto_responders "
                    "ADD COLUMN target_type TEXT NOT NULL DEFAULT 'everyone'"
                )
            if "target_id" not in responder_columns:
                await db.execute(
                    "ALTER TABLE guild_auto_responders "
                    "ADD COLUMN target_id INTEGER NOT NULL DEFAULT 0"
                )
            if "reaction_emoji" not in responder_columns:
                await db.execute(
                    "ALTER TABLE guild_auto_responders "
                    "ADD COLUMN reaction_emoji TEXT NOT NULL DEFAULT ''"
                )
            await _migrate_auto_responder_uniqueness(db)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_auto_responders_guild "
                "ON guild_auto_responders(guild_id, enabled);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS guild_shortcuts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    trigger TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    target TEXT NOT NULL DEFAULT '',
                    announcement TEXT NOT NULL DEFAULT '',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, trigger)
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_shortcuts_guild "
                "ON guild_shortcuts(guild_id, enabled);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_panels (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    message_id INTEGER NOT NULL,
                    categories TEXT NOT NULL DEFAULT '[]',
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, channel_id, message_id)
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL UNIQUE,
                    user_id INTEGER NOT NULL,
                    category_key TEXT NOT NULL,
                    category_label TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    details TEXT NOT NULL DEFAULT '',
                    support_role_ids TEXT NOT NULL DEFAULT '[]',
                    senior_role_ids TEXT NOT NULL DEFAULT '[]',
                    priority TEXT NOT NULL DEFAULT 'normal',
                    status TEXT NOT NULL DEFAULT 'active',
                    claimed_by INTEGER DEFAULT NULL,
                    opened_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    first_response_at DATETIME DEFAULT NULL,
                    closed_at DATETIME DEFAULT NULL,
                    closed_by INTEGER DEFAULT NULL,
                    close_reason TEXT NOT NULL DEFAULT '',
                    rating INTEGER DEFAULT NULL
                );
            """)
            async with db.execute("PRAGMA table_info(tickets)") as cur:
                ticket_columns = {row[1] for row in await cur.fetchall()}
            ticket_migrations = {
                "intake_data": "TEXT NOT NULL DEFAULT '{}'",
                "waiting_since": "DATETIME DEFAULT NULL",
                "escalated_at": "DATETIME DEFAULT NULL",
                "last_user_message_at": "DATETIME DEFAULT NULL",
            }
            for column, definition in ticket_migrations.items():
                if column not in ticket_columns:
                    await db.execute(
                        f"ALTER TABLE tickets ADD COLUMN {column} {definition}"
                    )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_tickets_guild_status "
                "ON tickets(guild_id, status);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_notes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    staff_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket "
                "ON ticket_notes(guild_id, ticket_id, created_at DESC);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_transcripts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    content_text TEXT NOT NULL,
                    content_html TEXT NOT NULL,
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_transcripts_guild "
                "ON ticket_transcripts(guild_id, created_at DESC);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS ticket_ratings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL UNIQUE,
                    guild_id INTEGER NOT NULL,
                    staff_id INTEGER DEFAULT NULL,
                    user_id INTEGER NOT NULL,
                    stars INTEGER NOT NULL,
                    feedback TEXT NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ticket_ratings_staff "
                "ON ticket_ratings(guild_id, staff_id);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS canned_responses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    category TEXT NOT NULL DEFAULT 'عام',
                    shortcut TEXT DEFAULT NULL,
                    sticker_id INTEGER DEFAULT NULL,
                    created_by INTEGER DEFAULT NULL,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, title)
                );
            """)
            async with db.execute("PRAGMA table_info(canned_responses)") as cur:
                canned_columns = {row[1] for row in await cur.fetchall()}
            if "shortcut" not in canned_columns:
                await db.execute(
                    "ALTER TABLE canned_responses ADD COLUMN shortcut TEXT DEFAULT NULL"
                )
            if "sticker_id" not in canned_columns:
                await db.execute(
                    "ALTER TABLE canned_responses ADD COLUMN sticker_id INTEGER DEFAULT NULL"
                )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_canned_responses_guild "
                "ON canned_responses(guild_id, updated_at DESC);"
            )
            await db.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    reminder TEXT NOT NULL,
                    due_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_reminders_due "
                "ON reminders(status, due_at);"
            )
            # Gaming & esports additions are intentionally isolated from the
            # existing tournament, giveaway, and ticket tables.
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scrim_configs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    title TEXT,
                    game_type TEXT,
                    team_size INTEGER,
                    max_slots INTEGER,
                    message_id INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
            await db.execute("""
                CREATE TABLE IF NOT EXISTS scrim_registrations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scrim_id INTEGER,
                    slot_number INTEGER,
                    team_name TEXT,
                    leader_id INTEGER,
                    members_json TEXT,
                    checked_in INTEGER DEFAULT 0,
                    UNIQUE(scrim_id, slot_number)
                );
            """)
            async with db.execute("PRAGMA table_info(scrim_configs)") as cur:
                scrim_config_columns = {row[1] for row in await cur.fetchall()}
            if "message_id" not in scrim_config_columns:
                await db.execute(
                    "ALTER TABLE scrim_configs ADD COLUMN message_id INTEGER DEFAULT 0"
                )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_scrim_configs_guild_active "
                "ON scrim_configs(guild_id, is_active);"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_scrim_registrations_scrim "
                "ON scrim_registrations(scrim_id, slot_number);"
            )
            await _ensure_canonical_views(db)

            await db.commit()
            logger.info("[DB] جميع الجداول والفهارس تعمل بكفاءة عالية.")
    except Exception as e:
        logger.error(f"[DB_FATAL] خطأ أثناء إنشاء الجداول: {e}")
        raise
    _settings_cache.clear()
    _stats_cache.clear()
    COMMAND_CACHE.clear()
    LOG_ROUTING_CACHE.clear()


# -------------------------------------------------------------
# إعدادات السيرفر (Guild Settings API) مع كاش LRU/TTL
# -------------------------------------------------------------
def _empty_log_routing() -> Dict[str, int]:
    return {key: 0 for key in LOG_ROUTING_ALL_KEYS}


def get_cached_logging_channels(guild_id: int) -> Dict[str, int]:
    """Return the last committed routing snapshot without touching SQLite."""
    snapshot = LOG_ROUTING_CACHE.get(int(guild_id))
    return dict(snapshot) if snapshot is not None else _empty_log_routing()


async def get_logging_channels(guild_id: int) -> Dict[str, int]:
    """Read all dedicated and legacy log destinations and warm the cache."""
    guild_id = int(guild_id)
    cached = LOG_ROUTING_CACHE.get(guild_id)
    if cached is not None:
        return dict(cached)
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT " + ", ".join(LOG_ROUTING_ALL_KEYS)
            + " FROM logging_channels WHERE guild_id = ?",
            (guild_id,),
        ) as cur:
            row = await cur.fetchone()
    snapshot = _empty_log_routing()
    if row:
        snapshot.update({
            key: int(row[key] or 0)
            for key in LOG_ROUTING_KEYS
        })
    LOG_ROUTING_CACHE[guild_id] = snapshot
    return dict(snapshot)


async def set_logging_channels(
    guild_id: int,
    channels_dict: Dict[str, Any],
) -> Dict[str, int]:
    """Atomically upsert routing and publish it only after commit."""
    guild_id = int(guild_id)
    snapshot = _empty_log_routing()
    for key in LOG_ROUTING_KEYS:
        value = channels_dict.get(key, 0)
        if not value:
            value = next(
                (
                    legacy
                    for legacy, dedicated in LOG_ROUTING_ALIASES.items()
                    if dedicated == key and channels_dict.get(legacy)
                ),
                0,
            )
        try:
            snapshot[key] = max(0, int(value or 0))
        except (TypeError, ValueError):
            raise ValueError(f"invalid logging channel for {key}") from None
    for legacy, dedicated in LOG_ROUTING_ALIASES.items():
        snapshot[legacy] = snapshot[dedicated]
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO logging_channels
                (guild_id, """ + ", ".join(LOG_ROUTING_ALL_KEYS) + """)
            VALUES (?, """ + ", ".join("?" for _ in LOG_ROUTING_ALL_KEYS) + """)
            ON CONFLICT(guild_id) DO UPDATE SET
                """ + ", ".join(
                    f"{key} = excluded.{key}" for key in LOG_ROUTING_ALL_KEYS
                ) + """
            """,
            (guild_id, *(snapshot[key] for key in LOG_ROUTING_ALL_KEYS)),
        )
        await db.commit()
    LOG_ROUTING_CACHE[guild_id] = snapshot
    return dict(snapshot)


def _row_to_settings(guild_id: int, row: Optional[Any]) -> Dict[str, Any]:
    data = dict(row) if row is not None else {}
    settings: Dict[str, Any] = {}
    for key, (_, default, kind) in SETTINGS_SCHEMA.items():
        value = data.get(key)
        if value is None:
            value = default
        elif kind == "bool":
            value = bool(value)
        elif kind == "float":
            value = float(value)
        elif kind == "json_list":
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                value = []
            if not isinstance(value, list):
                value = []
            value = [str(item) for item in value if isinstance(item, str)]
        elif kind == "json_map":
            try:
                value = json.loads(value) if isinstance(value, str) else value
            except (TypeError, ValueError):
                value = {}
            if not isinstance(value, dict):
                value = {}
            value = {
                str(key): float(multiplier)
                for key, multiplier in value.items()
                if str(key).isdigit()
                and isinstance(multiplier, (int, float))
                and 0.0 < float(multiplier) <= 10.0
            }
        elif kind in ("int", "id"):
            value = int(value)
        settings[key] = value
    return {
        "guild_id": guild_id,
        "revision": int(data.get("revision") or 0),
        "updated_at": data.get("updated_at"),
        "settings": settings,
    }


def _cache_get(guild_id: int) -> Optional[Dict[str, Any]]:
    entry = _settings_cache.get(guild_id)
    if not entry:
        return None
    loaded_at, snapshot = entry
    if time.monotonic() - loaded_at > CACHE_TTL:
        _settings_cache.pop(guild_id, None)
        return None
    _settings_cache.move_to_end(guild_id)
    return {**snapshot, "settings": dict(snapshot["settings"])}


def _cache_put(guild_id: int, snapshot: Dict[str, Any]) -> None:
    _settings_cache[guild_id] = (time.monotonic(), {**snapshot, "settings": dict(snapshot["settings"])})
    _settings_cache.move_to_end(guild_id)
    while len(_settings_cache) > CACHE_MAX:
        _settings_cache.popitem(last=False)


def invalidate_guild_settings(guild_id: Optional[int] = None) -> None:
    """إبطال الكاش لسيرفر واحد أو للجميع (مفيد للاختبارات والكتابات الخارجية)."""
    if guild_id is None:
        _settings_cache.clear()
    else:
        _settings_cache.pop(guild_id, None)


def _lock_for(guild_id: int) -> asyncio.Lock:
    lock = _guild_locks.get(guild_id)
    if lock is None:
        lock = _guild_locks[guild_id] = asyncio.Lock()
    return lock


def _release_lock(guild_id: int) -> None:
    lock = _guild_locks.get(guild_id)
    if lock is not None and not lock.locked() and not getattr(lock, "_waiters", None):
        _guild_locks.pop(guild_id, None)


def validate_setting(key: str, value: Any) -> Any:
    """تحويل القيمة والتحقق منها حسب المخطط؛ يرفع ValueError برسالة عربية."""
    if key not in SETTINGS_SCHEMA:
        raise ValueError("حقل غير معروف")
    kind = SETTINGS_SCHEMA[key][2]
    if isinstance(value, bool) and kind != "bool":
        raise ValueError("نوع القيمة غير صالح")
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError("يجب أن تكون القيمة تشغيل/إيقاف")
        return value
    if kind == "id":
        if value in (None, ""):
            return None
        text = str(value)
        if key in {"leaderboard_channel_id", "leaderboard_message_id"} and text == "0":
            return 0
        if not text.isdigit() or not 15 <= len(text) <= 22:
            raise ValueError("معرّف ديسكورد غير صالح")
        return int(text)
    if kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("يجب أن تكون القيمة عدداً صحيحاً")
        if not isinstance(value, (int, float)):
            raise ValueError("يجب أن تكون القيمة رقماً")
        value = int(value)
        limits = {
            "anti_alt_days": (0, 365),
            "daily_amount": (0, 1_000_000),
            "daily_base_amount": (0, 1_000_000),
            "level_multiplier_pct": (0, 500),
        }
        low, high = limits.get(key, (0, 2**31 - 1))
        if not low <= value <= high:
            raise ValueError(f"القيمة يجب أن تكون بين {low} و {high}")
        return value
    if kind == "float":
        if not isinstance(value, (int, float)):
            raise ValueError("يجب أن تكون القيمة رقماً")
        value = float(value)
        if value != value or not 0.0 <= value <= 100.0:
            raise ValueError("النسبة يجب أن تكون بين 0 و 100")
        return round(value, 2)
    if kind == "json_list":
        if not isinstance(value, list):
            raise ValueError("يجب أن تكون قائمة الكلمات نصية")
        words = []
        for item in value[:200]:
            if not isinstance(item, str):
                raise ValueError("كل كلمة محظورة يجب أن تكون نصاً")
            item = item.strip().replace("\x00", "")
            if item and len(item) <= 80:
                words.append(item)
        return list(dict.fromkeys(words))
    if kind == "json_map":
        if not isinstance(value, dict):
            raise ValueError("يجب أن تكون مضاعفات الرتب في صيغة JSON")
        result = {}
        for role_id, multiplier in list(value.items())[:100]:
            if not str(role_id).isdigit():
                raise ValueError("معرّف الرتبة غير صالح")
            try:
                multiplier = float(multiplier)
            except (TypeError, ValueError):
                raise ValueError("قيمة المضاعف غير صالحة")
            if not 0.0 < multiplier <= 10.0:
                raise ValueError("المضاعف يجب أن يكون أكبر من صفر وحتى 10")
            result[str(role_id)] = round(multiplier, 3)
        return result
    # str
    if not isinstance(value, str):
        raise ValueError("يجب أن تكون القيمة نصاً")
    value = value.replace("\r\n", "\n").replace("\x00", "")
    if key == "prefix":
        value = value.strip()
        if not 1 <= len(value) <= 5 or any(ch.isspace() for ch in value):
            raise ValueError("البادئة يجب أن تكون من 1 إلى 5 أحرف بدون مسافات")
    elif key in {"welcome_message", "leave_message", "welcome_embed_description"} and len(value) > 1000:
        raise ValueError("رسالة الترحيب يجب ألا تتجاوز 1000 حرف")
    elif key == "welcome_embed_title" and len(value) > 256:
        raise ValueError("عنوان الـ Embed يجب ألا يتجاوز 256 حرفاً")
    elif key == "welcome_embed_footer" and len(value) > 2048:
        raise ValueError("تذييل الـ Embed طويل جداً")
    elif key == "welcome_embed_color":
        if not (len(value) == 7 and value.startswith("#") and all(ch in "0123456789abcdefABCDEF" for ch in value[1:])):
            raise ValueError("لون الـ Embed يجب أن يكون بصيغة #RRGGBB")
    elif key == "welcome_embed_image_url":
        if value:
            parsed = urlparse(value)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("رابط صورة الـ Embed غير صالح")
    return value


async def get_guild_settings(guild_id: int) -> Dict[str, Any]:
    """جلب إعدادات السيرفر (مع القيم الافتراضية) من الكاش أو القرص؛ لا يُنشئ صفاً."""
    guild_id = int(guild_id)
    cached = _cache_get(guild_id)
    if cached is not None:
        return cached
    async with connect(aiosqlite.Row) as db:
        async with db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)) as cur:
            row = await cur.fetchone()
    snapshot = _row_to_settings(guild_id, row)
    # لا نستبدل نسخة أحدث وصلت أثناء القراءة (الكتابة تنشر الإصدار الملتزم فقط)
    current = _settings_cache.get(guild_id)
    if current is None or current[1]["revision"] <= snapshot["revision"]:
        _cache_put(guild_id, snapshot)
    return {**snapshot, "settings": dict(snapshot["settings"])}


async def update_guild_settings(
    guild_id: int, expected_revision: Optional[int] = None, **kwargs: Any
) -> Dict[str, Any]:
    """تحديث الحقول المُمرّرة فقط ذرياً مع رفع updated_at والإصدار؛ يرفع SettingsConflict عند التعارض."""
    guild_id = int(guild_id)
    changes = {key: validate_setting(key, value) for key, value in kwargs.items()}
    if not changes:
        return await get_guild_settings(guild_id)
    # مزامنة الأعمدة القديمة مع الجديدة للحفاظ على التوافق
    for new_col, legacy in LEGACY_ALIASES.items():
        if new_col in changes:
            changes[legacy] = changes[new_col]
    columns = list(changes)
    values = [
        int(value)
        if isinstance(value, bool)
        else json.dumps(value, ensure_ascii=False)
        if SETTINGS_SCHEMA.get(key, (None, None, None))[2] in ("json_list", "json_map")
        else value
        for key, value in changes.items()
    ]
    now = _utc_now()
    assignments = ", ".join(f"{col} = excluded.{col}" for col in columns)
    sql = (
        f"INSERT INTO guild_settings (guild_id, {', '.join(columns)}, revision, updated_at) "
        f"VALUES (?, {', '.join('?' for _ in columns)}, 1, ?) "
        f"ON CONFLICT(guild_id) DO UPDATE SET {assignments}, "
        "revision = guild_settings.revision + 1, updated_at = excluded.updated_at"
    )
    params: List[Any] = [guild_id, *values, now]
    if expected_revision is not None:
        expected_revision = int(expected_revision)
        if expected_revision < 0:
            raise ValueError("رقم الإصدار غير صالح")
        if expected_revision == 0:
            # صف جديد أو صف قائم لم يُعدَّل بعد
            sql += " WHERE guild_settings.revision = 0"
        else:
            # يجب أن يكون الصف موجوداً بالإصدار المتوقع؛ لا إدراج ضمني هنا
            sets = ", ".join(f"{col} = ?" for col in columns)
            sql = (
                f"UPDATE guild_settings SET {sets}, revision = revision + 1, updated_at = ? "
                "WHERE guild_id = ? AND revision = ?"
            )
            params = [*values, now, guild_id, expected_revision]
    lock = _lock_for(guild_id)
    try:
        async with lock:
            async with connect(aiosqlite.Row) as db:
                try:
                    cur = await db.execute(sql, params)
                    changed = cur.rowcount
                    await cur.close()
                    if changed == 0:
                        await db.rollback()
                        async with db.execute(
                            "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
                        ) as cur:
                            current = _row_to_settings(guild_id, await cur.fetchone())
                        raise SettingsConflict(current)
                    async with db.execute(
                        "SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,)
                    ) as cur:
                        row = await cur.fetchone()
                    await db.commit()
                except BaseException:
                    # فشل أو إلغاء: لا ننشر بيانات غير ملتزمة
                    invalidate_guild_settings(guild_id)
                    raise
            snapshot = _row_to_settings(guild_id, row)
            _cache_put(guild_id, snapshot)  # النشر بعد الالتزام فقط
            return {**snapshot, "settings": dict(snapshot["settings"])}
    finally:
        _release_lock(guild_id)  # بعد تحرير القفل فعلياً


# -------------------------------------------------------------
# دوال الاقتصاد والمستويات (Economy & Levels API)
# -------------------------------------------------------------
async def get_or_create_user(user_id: int, guild_id: int) -> Dict[str, Any]:
    """جلب بيانات العضو أو إنشاؤه بأمان عند الطلبات المتزامنة."""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
            (int(user_id), int(guild_id)),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
            (int(user_id), int(guild_id)),
        ) as cursor:
            row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("user row disappeared after atomic creation")
            return dict(row)


async def get_user_level(user_id: int, guild_id: int) -> int:
    """Read the current economy level without creating an account."""
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT level FROM users WHERE user_id = ? AND guild_id = ?",
            (int(user_id), int(guild_id)),
        ) as cur:
            row = await cur.fetchone()
    return max(0, int(row["level"])) if row else 0


async def add_xp(user_id: int, guild_id: int, amount: int = 15) -> Tuple[bool, int]:
    """إضافة خبرة وفحص الترقية داخل معاملة قفل واحدة."""
    amount = max(0, int(amount))
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            async with db.execute(
                "SELECT xp, level FROM users WHERE user_id = ? AND guild_id = ?",
                (int(user_id), int(guild_id)),
            ) as cursor:
                row = await cursor.fetchone()
            if row is None:
                raise RuntimeError("user row disappeared during XP update")

            new_xp = int(row["xp"]) + amount
            current_level = int(row["level"])
            xp_needed = current_level * 120
            leveled_up = new_xp >= xp_needed
            if leveled_up:
                current_level += 1
                new_xp -= xp_needed

            await db.execute(
                """
                UPDATE users SET xp = ?, level = ?
                WHERE user_id = ? AND guild_id = ?
                """,
                (new_xp, current_level, int(user_id), int(guild_id)),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return leveled_up, current_level


async def claim_daily_reward(
    user_id: int,
    guild_id: int,
    today: str,
    reward: int,
) -> bool:
    """صرف المكافأة اليومية مرة واحدة، مع إنشاء الحساب ضمن نفس المعاملة."""
    reward = max(0, int(reward))
    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            cursor = await db.execute(
                """
                UPDATE users
                SET balance = balance + ?, last_daily = ?
                WHERE user_id = ? AND guild_id = ?
                  AND (last_daily IS NULL OR last_daily <> ?)
                """,
                (
                    reward,
                    str(today),
                    int(user_id),
                    int(guild_id),
                    str(today),
                ),
            )
            claimed = cursor.rowcount == 1
            await db.commit()
            return claimed
        except Exception:
            await db.rollback()
            raise


async def update_balance(
    user_id: int,
    guild_id: int,
    amount: int,
    account: str = "balance",
) -> int:
    """تعديل رصيد العضو (كاش أو بنك) بأمان وحماية من الرصيد السالب."""
    col = "bank" if account == "bank" else "balance"
    async with connect() as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
            (int(user_id), int(guild_id)),
        )
        # استخدام Parameterized Query لتجنب ثغرات حقن الاستعلامات
        query = f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ? AND guild_id = ?"
        await db.execute(query, (int(amount), int(user_id), int(guild_id)))
        await db.commit()

        async with db.execute(
            f"SELECT {col} FROM users WHERE user_id = ? AND guild_id = ?",
            (int(user_id), int(guild_id)),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


async def adjust_user_balance(
    guild_id: int,
    user_id: int,
    wallet_delta: int = 0,
    bank_delta: int = 0,
) -> Optional[Dict[str, Any]]:
    """Atomically adjust both wallets while preventing either from going negative."""
    wallet_delta, bank_delta = int(wallet_delta), int(bank_delta)
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            cur = await db.execute(
                """
                UPDATE users
                SET balance = balance + ?, bank = bank + ?
                WHERE user_id = ? AND guild_id = ?
                  AND balance + ? >= 0 AND bank + ? >= 0
                """,
                (
                    wallet_delta,
                    bank_delta,
                    int(user_id),
                    int(guild_id),
                    wallet_delta,
                    bank_delta,
                ),
            )
            if cur.rowcount != 1:
                await db.rollback()
                return None
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
                (int(user_id), int(guild_id)),
            ) as cursor:
                row = await cursor.fetchone()
            await db.commit()
            return dict(row) if row else None
        except Exception:
            await db.rollback()
            raise


async def adjust_user_level(
    guild_id: int,
    user_id: int,
    level_delta: int,
    reset_xp: bool = False,
) -> Optional[Dict[str, Any]]:
    """Atomically adjust a member's level, never allowing a level below one."""
    level_delta = int(level_delta)
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            if reset_xp:
                cur = await db.execute(
                    """
                    UPDATE users SET level = MAX(1, level + ?), xp = 0
                    WHERE user_id = ? AND guild_id = ?
                    """,
                    (level_delta, int(user_id), int(guild_id)),
                )
            else:
                cur = await db.execute(
                    """
                    UPDATE users SET level = MAX(1, level + ?)
                    WHERE user_id = ? AND guild_id = ?
                    """,
                    (level_delta, int(user_id), int(guild_id)),
                )
            if cur.rowcount != 1:
                await db.rollback()
                return None
            async with db.execute(
                "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
                (int(user_id), int(guild_id)),
            ) as cursor:
                row = await cursor.fetchone()
            await db.commit()
            return dict(row) if row else None
        except Exception:
            await db.rollback()
            raise


async def claim_scaled_daily_reward(
    user_id: int,
    guild_id: int,
    today: str,
    base_amount: int,
    level_multiplier_pct: int,
    role_multiplier: float,
) -> Optional[Dict[str, Any]]:
    """Calculate and claim a scaled daily reward in one SQLite transaction."""
    base_amount = max(0, int(base_amount))
    level_multiplier_pct = max(0, int(level_multiplier_pct))
    role_multiplier = max(0.0, float(role_multiplier))
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            async with db.execute(
                "SELECT level, last_daily FROM users WHERE user_id = ? AND guild_id = ?",
                (int(user_id), int(guild_id)),
            ) as cur:
                account = await cur.fetchone()
            if account is None or account["last_daily"] == str(today):
                await db.rollback()
                return None
            level = max(1, int(account["level"]))
            level_bonus = 1.0 + level * (level_multiplier_pct / 100.0)
            reward = max(0, round(base_amount * level_bonus * role_multiplier))
            cur = await db.execute(
                """
                UPDATE users SET balance = balance + ?, last_daily = ?
                WHERE user_id = ? AND guild_id = ?
                  AND (last_daily IS NULL OR last_daily <> ?)
                """,
                (reward, str(today), int(user_id), int(guild_id), str(today)),
            )
            if cur.rowcount != 1:
                await db.rollback()
                return None
            await db.commit()
            return {
                "reward": int(reward),
                "base_amount": base_amount,
                "level": level,
                "level_bonus": round(level_bonus, 3),
                "role_multiplier": round(role_multiplier, 3),
            }
        except Exception:
            await db.rollback()
            raise


async def set_leaderboard_embed_target(
    guild_id: int,
    channel_id: int,
    message_id: int = 0,
) -> Dict[str, Any]:
    return await update_guild_settings(
        int(guild_id),
        leaderboard_channel_id=int(channel_id),
        leaderboard_message_id=int(message_id),
    )


async def get_role_multipliers(guild_id: int) -> Dict[str, float]:
    settings = await get_guild_settings(int(guild_id))
    return dict(settings["settings"].get("role_multipliers") or {})


async def set_role_multiplier(
    guild_id: int,
    role_id: int,
    multiplier: float,
) -> Dict[str, Any]:
    multiplier = float(multiplier)
    if not 0.0 < multiplier <= 10.0:
        raise ValueError("المضاعف يجب أن يكون أكبر من صفر وحتى 10")
    multipliers = await get_role_multipliers(int(guild_id))
    multipliers[str(int(role_id))] = round(multiplier, 3)
    return await update_guild_settings(
        int(guild_id),
        role_multipliers=multipliers,
    )


async def get_leaderboard_targets() -> list[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT guild_id, leaderboard_channel_id, leaderboard_message_id
            FROM guild_settings
            WHERE leaderboard_channel_id IS NOT NULL
              AND leaderboard_channel_id > 0
            """
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_level_leaderboard(
    guild_id: int,
    limit: int = 10,
) -> list[Dict[str, Any]]:
    limit = max(1, min(int(limit), 25))
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT user_id, level, balance, bank, xp, (balance + bank) AS total
            FROM users WHERE guild_id = ?
            ORDER BY level DESC, xp DESC, total DESC
            LIMIT ?
            """,
            (int(guild_id), limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def add_economy_audit(
    guild_id: int,
    user_id: int,
    actor_id: int,
    action: str,
    wallet_delta: int = 0,
    level_delta: int = 0,
    details: str = "",
) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO economy_audit_logs
                (guild_id, user_id, actor_id, action, wallet_delta, level_delta, details)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(user_id),
                int(actor_id),
                str(action)[:80],
                int(wallet_delta),
                int(level_delta),
                str(details)[:1000],
            ),
        )
        await db.commit()


async def get_level_rewards(guild_id: int, level: int | None = None) -> list[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        if level is None:
            query = (
                "SELECT guild_id, level, role_id FROM level_rewards "
                "WHERE guild_id = ? ORDER BY level ASC, role_id ASC"
            )
            params = (int(guild_id),)
        else:
            query = (
                "SELECT guild_id, level, role_id FROM level_rewards "
                "WHERE guild_id = ? AND level <= ? ORDER BY level ASC, role_id ASC"
            )
            params = (int(guild_id), int(level))
        async with db.execute(query, params) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def move_balance(
    user_id: int,
    guild_id: int,
    amount: int,
    from_account: str,
    to_account: str,
) -> bool:
    """نقل رصيد بين الكاش والبنك دون نافذة سباق بين عمليتي خصم وإضافة."""
    amount = int(amount)
    columns = {"balance", "bank"}
    if amount <= 0 or from_account not in columns or to_account not in columns:
        return False
    if from_account == to_account:
        return False

    async with connect() as db:
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute(
                "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
                (int(user_id), int(guild_id)),
            )
            cursor = await db.execute(
                f"""
                UPDATE users SET {from_account} = {from_account} - ?
                WHERE user_id = ? AND guild_id = ? AND {from_account} >= ?
                """,
                (amount, int(user_id), int(guild_id), amount),
            )
            if cursor.rowcount != 1:
                await db.rollback()
                return False
            await db.execute(
                f"""
                UPDATE users SET {to_account} = {to_account} + ?
                WHERE user_id = ? AND guild_id = ?
                """,
                (amount, int(user_id), int(guild_id)),
            )
            await db.commit()
            return True
        except Exception:
            await db.rollback()
            raise


async def transfer_balance(
    guild_id: int,
    from_user_id: int,
    to_user_id: int,
    amount: int,
) -> bool:
    """تحويل كاش ذري بين عضوين مع تسجيل العملية."""
    amount = int(amount)
    if amount <= 0 or int(from_user_id) == int(to_user_id):
        return False
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
            (int(from_user_id), int(guild_id)),
        )
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, guild_id) VALUES (?, ?)",
            (int(to_user_id), int(guild_id)),
        )
        cur = await db.execute(
            """
            UPDATE users SET balance = balance - ?
            WHERE user_id = ? AND guild_id = ? AND balance >= ?
            """,
            (amount, int(from_user_id), int(guild_id), amount),
        )
        if cur.rowcount != 1:
            await db.rollback()
            return False
        await db.execute(
            "UPDATE users SET balance = balance + ? WHERE user_id = ? AND guild_id = ?",
            (amount, int(to_user_id), int(guild_id)),
        )
        await db.execute(
            """
            INSERT INTO economy_transactions
                (guild_id, from_user_id, to_user_id, amount, kind)
            VALUES (?, ?, ?, ?, 'transfer')
            """,
            (int(guild_id), int(from_user_id), int(to_user_id), amount),
        )
        await db.commit()
    return True


async def get_economy_leaderboard(
    guild_id: int,
    limit: int = 10,
) -> list[Dict[str, Any]]:
    limit = max(1, min(int(limit), 25))
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT user_id, level, balance, bank, xp, (balance + bank) AS total
            FROM users
            WHERE guild_id = ?
            ORDER BY total DESC, level DESC, xp DESC
            LIMIT ?
            """,
            (int(guild_id), limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def record_tournament_score(
    guild_id: int,
    winner_team: str,
    loser_team: str,
) -> None:
    async with connect() as db:
        for team, won in ((winner_team, True), (loser_team, False)):
            await db.execute(
                """
                INSERT INTO tournament_scores
                    (guild_id, team_name, points, wins, losses)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, team_name) DO UPDATE SET
                    points = tournament_scores.points + excluded.points,
                    wins = tournament_scores.wins + excluded.wins,
                    losses = tournament_scores.losses + excluded.losses,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(guild_id),
                    str(team)[:100],
                    3 if won else 0,
                    1 if won else 0,
                    0 if won else 1,
                ),
            )
        await db.commit()


async def get_tournament_scores(
    guild_id: int,
    limit: int = 25,
) -> list[Dict[str, Any]]:
    limit = max(1, min(int(limit), 50))
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT team_name, points, wins, losses
            FROM tournament_scores
            WHERE guild_id = ?
            ORDER BY points DESC, wins DESC, team_name ASC
            LIMIT ?
            """,
            (int(guild_id), limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def create_giveaway(
    guild_id: int,
    channel_id: int,
    prize: str,
    ends_at: str,
    created_by: int,
) -> int:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO giveaways
                (guild_id, channel_id, prize, ends_at, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(channel_id),
                str(prize).strip()[:200],
                str(ends_at),
                int(created_by),
            ),
        )
        giveaway_id = cur.lastrowid
        await db.commit()
    return int(giveaway_id)


async def set_giveaway_message(giveaway_id: int, message_id: int) -> None:
    async with connect() as db:
        await db.execute(
            "UPDATE giveaways SET message_id = ? WHERE id = ?",
            (int(message_id), int(giveaway_id)),
        )
        await db.commit()


async def add_giveaway_entry(giveaway_id: int, user_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO giveaway_entries (giveaway_id, user_id)
            SELECT ?, ?
            WHERE EXISTS (
                SELECT 1 FROM giveaways
                WHERE id = ? AND status = 'open'
            )
            """,
            (int(giveaway_id), int(user_id), int(giveaway_id)),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed


async def get_open_giveaways() -> list[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, channel_id, message_id, prize, ends_at
            FROM giveaways
            WHERE status = 'open' AND message_id > 0
            ORDER BY id ASC
            """
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_due_giveaways(now: Optional[str] = None) -> list[Dict[str, Any]]:
    current = now or _utc_now()
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, channel_id, message_id, prize, ends_at
            FROM giveaways
            WHERE status = 'open' AND message_id > 0 AND ends_at <= ?
            ORDER BY ends_at ASC, id ASC
            LIMIT 100
            """,
            (current,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_giveaway_entries(giveaway_id: int) -> list[int]:
    async with connect() as db:
        async with db.execute(
            """
            SELECT user_id FROM giveaway_entries
            WHERE giveaway_id = ? ORDER BY user_id ASC
            """,
            (int(giveaway_id),),
        ) as cur:
            return [int(row[0]) for row in await cur.fetchall()]


async def complete_giveaway(giveaway_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE giveaways SET status = 'completed'
            WHERE id = ? AND status = 'open'
            """,
            (int(giveaway_id),),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed


async def cancel_giveaway(giveaway_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE giveaways SET status = 'cancelled'
            WHERE id = ? AND status = 'open'
            """,
            (int(giveaway_id),),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed


async def create_tournament(
    guild_id: int,
    channel_id: int,
    title: str,
    max_players: int,
    created_by: int,
) -> int:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO tournaments
                (guild_id, channel_id, title, max_players, created_by)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(channel_id),
                str(title).strip()[:150],
                max(2, min(int(max_players), 100)),
                int(created_by),
            ),
        )
        tournament_id = cur.lastrowid
        await db.commit()
    return int(tournament_id)


async def set_tournament_message(tournament_id: int, message_id: int) -> None:
    async with connect() as db:
        await db.execute(
            "UPDATE tournaments SET message_id = ? WHERE id = ?",
            (int(message_id), int(tournament_id)),
        )
        await db.commit()


async def cancel_tournament(tournament_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE tournaments SET status = 'cancelled'
            WHERE id = ? AND status = 'open'
            """,
            (int(tournament_id),),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed


async def add_tournament_entry(tournament_id: int, user_id: int) -> tuple[bool, int, int]:
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            "SELECT max_players, status FROM tournaments WHERE id = ?",
            (int(tournament_id),),
        ) as cur:
            tournament = await cur.fetchone()
        if tournament is None or tournament["status"] != "open":
            return False, 0, 0
        async with db.execute(
            "SELECT COUNT(*) FROM tournament_entries WHERE tournament_id = ?",
            (int(tournament_id),),
        ) as cur:
            count = int((await cur.fetchone())[0])
        if count >= int(tournament["max_players"]):
            return False, count, int(tournament["max_players"])
        cur = await db.execute(
            """
            INSERT OR IGNORE INTO tournament_entries (tournament_id, user_id)
            VALUES (?, ?)
            """,
            (int(tournament_id), int(user_id)),
        )
        if cur.rowcount > 0:
            count += 1
        await db.commit()
        return cur.rowcount > 0, count, int(tournament["max_players"])


async def get_open_tournaments() -> list[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, channel_id, message_id, title, max_players
            FROM tournaments
            WHERE status = 'open' AND message_id > 0
            ORDER BY id ASC
            """
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def create_scrim_config(
    guild_id: int,
    channel_id: int,
    title: str,
    game_type: str,
    team_size: int,
    max_slots: int,
) -> Dict[str, Any]:
    """Create an independent scrim lobby configuration."""
    team_size = max(1, min(int(team_size), 16))
    max_slots = max(1, min(int(max_slots), 128))
    async with connect(aiosqlite.Row) as db:
        cur = await db.execute(
            """
            INSERT INTO scrim_configs
                (guild_id, channel_id, title, game_type, team_size, max_slots)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(channel_id),
                str(title).strip()[:150],
                str(game_type).strip()[:80],
                team_size,
                max_slots,
            ),
        )
        scrim_id = int(cur.lastrowid)
        await db.commit()
        async with db.execute(
            "SELECT * FROM scrim_configs WHERE id = ?", (scrim_id,)
        ) as row_cursor:
            row = await row_cursor.fetchone()
    return dict(row)


async def set_scrim_message(scrim_id: int, message_id: int) -> None:
    async with connect() as db:
        await db.execute(
            "UPDATE scrim_configs SET message_id = ? WHERE id = ?",
            (int(message_id), int(scrim_id)),
        )
        await db.commit()


async def close_scrim(scrim_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            "UPDATE scrim_configs SET is_active = 0 WHERE id = ? AND is_active = 1",
            (int(scrim_id),),
        )
        await db.commit()
    return cur.rowcount > 0


async def get_active_scrims(guild_id: int) -> list[Dict[str, Any]]:
    """Return active scrims with occupancy and roster data for the dashboard."""
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT c.*,
                   COUNT(r.id) AS occupied_slots,
                   COALESCE(
                     json_group_array(
                       CASE WHEN r.id IS NULL THEN NULL ELSE json_object(
                         'id', r.id,
                         'slot_number', r.slot_number,
                         'team_name', r.team_name,
                         'leader_id', r.leader_id,
                         'members_json', r.members_json,
                         'checked_in', r.checked_in
                       ) END
                     ),
                     '[]'
                   ) AS registrations_json
            FROM scrim_configs AS c
            LEFT JOIN scrim_registrations AS r ON r.scrim_id = c.id
            WHERE c.guild_id = ? AND c.is_active = 1
            GROUP BY c.id
            ORDER BY c.created_at DESC, c.id DESC
            """,
            (int(guild_id),),
        ) as cur:
            rows = [dict(row) for row in await cur.fetchall()]
    for row in rows:
        registrations = []
        try:
            raw = json.loads(row.pop("registrations_json") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = []
        for item in raw if isinstance(raw, list) else []:
            if not isinstance(item, dict) or item.get("id") is None:
                continue
            try:
                item["members"] = json.loads(item.pop("members_json") or "[]")
            except (TypeError, ValueError, json.JSONDecodeError):
                item["members"] = []
            item["checked_in"] = bool(item.get("checked_in"))
            registrations.append(item)
        row["occupied_slots"] = int(row.get("occupied_slots") or 0)
        row["registrations"] = registrations
    return rows


async def get_scrims(guild_id: int) -> list[Dict[str, Any]]:
    """Return active and closed scrims using the same dashboard payload shape."""
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT id FROM scrim_configs WHERE guild_id = ? ORDER BY id DESC",
            (int(guild_id),),
        ) as cur:
            ids = [int(row[0]) for row in await cur.fetchall()]
    # Keep one response contract and avoid duplicating roster decoding logic.
    result = []
    for scrim_id in ids:
        async with connect(aiosqlite.Row) as db:
            async with db.execute(
                """
                SELECT c.*, COUNT(r.id) AS occupied_slots
                FROM scrim_configs c
                LEFT JOIN scrim_registrations r ON r.scrim_id = c.id
                WHERE c.id = ? GROUP BY c.id
                """,
                (scrim_id,),
            ) as cur:
                row = await cur.fetchone()
            if row is None:
                continue
            item = dict(row)
            async with db.execute(
                """
                SELECT id, slot_number, team_name, leader_id,
                       members_json, checked_in
                FROM scrim_registrations
                WHERE scrim_id = ? ORDER BY slot_number ASC
                """,
                (scrim_id,),
            ) as cur:
                registrations = []
                for registration in await cur.fetchall():
                    value = dict(registration)
                    try:
                        value["members"] = json.loads(value.pop("members_json") or "[]")
                    except (TypeError, ValueError, json.JSONDecodeError):
                        value["members"] = []
                    value["checked_in"] = bool(value.get("checked_in"))
                    registrations.append(value)
            item["occupied_slots"] = int(item.get("occupied_slots") or 0)
            item["registrations"] = registrations
            result.append(item)
    return result


async def reserve_scrim_slot(
    scrim_id: int,
    team_name: str,
    leader_id: int,
    members_json: str | list[int] | None = None,
) -> Optional[Dict[str, Any]]:
    """Atomically reserve the first free slot, or return None if unavailable."""
    if isinstance(members_json, list):
        members_json = json.dumps(
            [int(member_id) for member_id in members_json if str(member_id).isdigit()]
        )
    members_json = str(members_json or "[]")
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            "SELECT max_slots, is_active FROM scrim_configs WHERE id = ?",
            (int(scrim_id),),
        ) as cur:
            scrim = await cur.fetchone()
        if scrim is None or not bool(scrim["is_active"]):
            return None
        async with db.execute(
            "SELECT slot_number FROM scrim_registrations WHERE scrim_id = ?",
            (int(scrim_id),),
        ) as cur:
            used = {int(row[0]) for row in await cur.fetchall()}
        slot = next(
            (candidate for candidate in range(1, int(scrim["max_slots"]) + 1)
             if candidate not in used),
            None,
        )
        if slot is None:
            return None
        cur = await db.execute(
            """
            INSERT INTO scrim_registrations
                (scrim_id, slot_number, team_name, leader_id, members_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (int(scrim_id), slot, str(team_name).strip()[:100], int(leader_id), members_json),
        )
        await db.commit()
        async with db.execute(
            "SELECT * FROM scrim_registrations WHERE id = ?", (int(cur.lastrowid),)
        ) as row_cursor:
            row = await row_cursor.fetchone()
    result = dict(row)
    try:
        result["members"] = json.loads(result.pop("members_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["members"] = []
    result["checked_in"] = bool(result.get("checked_in"))
    return result


async def cancel_scrim_slot(scrim_id: int, *, leader_id: int | None = None, slot_number: int | None = None) -> bool:
    """Release a reservation, scoped to its leader unless an admin caller bypasses it."""
    if leader_id is None and slot_number is None:
        return False
    async with connect() as db:
        conditions = ["scrim_id = ?"]
        params: list[Any] = [int(scrim_id)]
        if slot_number is not None:
            conditions.append("slot_number = ?")
            params.append(int(slot_number))
        if leader_id is not None:
            conditions.append("leader_id = ?")
            params.append(int(leader_id))
        cur = await db.execute(
            f"DELETE FROM scrim_registrations WHERE {' AND '.join(conditions)}",
            tuple(params),
        )
        await db.commit()
    return cur.rowcount > 0


async def toggle_scrim_checkin(
    scrim_id: int,
    *,
    leader_id: int | None = None,
    slot_number: int | None = None,
    checked_in: bool = True,
) -> Optional[Dict[str, Any]]:
    """Toggle check-in for one reservation and return the updated row."""
    if leader_id is None and slot_number is None:
        return None
    async with connect(aiosqlite.Row) as db:
        conditions = ["scrim_id = ?"]
        params: list[Any] = [int(scrim_id)]
        if slot_number is not None:
            conditions.append("slot_number = ?")
            params.append(int(slot_number))
        if leader_id is not None:
            conditions.append("leader_id = ?")
            params.append(int(leader_id))
        await db.execute(
            f"UPDATE scrim_registrations SET checked_in = ? WHERE {' AND '.join(conditions)}",
            (int(bool(checked_in)), *params),
        )
        await db.commit()
        async with db.execute(
            f"SELECT * FROM scrim_registrations WHERE {' AND '.join(conditions)}",
            tuple(params),
        ) as cur:
            row = await cur.fetchone()
    if row is None:
        return None
    result = dict(row)
    try:
        result["members"] = json.loads(result.pop("members_json") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["members"] = []
    result["checked_in"] = bool(result.get("checked_in"))
    return result


async def get_tournament_entries(tournament_id: int) -> list[int]:
    async with connect() as db:
        async with db.execute(
            """
            SELECT user_id FROM tournament_entries
            WHERE tournament_id = ? ORDER BY created_at ASC, user_id ASC
            """,
            (int(tournament_id),),
        ) as cur:
            return [int(row[0]) for row in await cur.fetchall()]


async def start_tournament(tournament_id: int) -> Optional[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        await db.execute("BEGIN IMMEDIATE")
        async with db.execute(
            "SELECT * FROM tournaments WHERE id = ? AND status = 'open'",
            (int(tournament_id),),
        ) as cur:
            tournament = await cur.fetchone()
        if tournament is None:
            return None
        async with db.execute(
            "SELECT user_id FROM tournament_entries WHERE tournament_id = ? ORDER BY created_at ASC",
            (int(tournament_id),),
        ) as cur:
            entries = [int(row[0]) for row in await cur.fetchall()]
        if len(entries) < 2:
            return None
        await db.execute(
            "UPDATE tournaments SET status = 'started' WHERE id = ? AND status = 'open'",
            (int(tournament_id),),
        )
        await db.commit()
        result = dict(tournament)
        result["entries"] = entries
        return result


# -------------------------------------------------------------
# دوال الإدارة والتحذيرات (Moderation API)
# -------------------------------------------------------------
async def add_warning(user_id: int, guild_id: int, mod_id: int, reason: str) -> int:
    """تسجيل تحذير وإرجاع إجمالي عدد تحذيرات العضو الحالية."""
    async with connect() as db:
        await db.execute(
            "INSERT INTO warnings (user_id, guild_id, moderator_id, reason) VALUES (?, ?, ?, ?)",
            (user_id, guild_id, mod_id, reason),
        )
        await db.commit()

        async with db.execute(
            "SELECT COUNT(*) FROM warnings WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        ) as cur:
            count = (await cur.fetchone())[0]
            return count


async def get_warnings(user_id: int, guild_id: int) -> List[Tuple[int, str, str]]:
    """جلب أرشيف المخالفات (ID, Reason, Timestamp) الخاص بعضو معين."""
    async with connect() as db:
        async with db.execute(
            "SELECT id, reason, timestamp FROM warnings "
            "WHERE user_id = ? AND guild_id = ? ORDER BY id DESC LIMIT 10",
            (user_id, guild_id),
        ) as cur:
            return await cur.fetchall()


async def record_invite_use(guild_id: int, inviter_id: int) -> int:
    """Atomically increment persistent invite usage and return the new total."""
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO invite_stats (guild_id, inviter_id, uses, last_used_at)
            VALUES (?, ?, 1, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, inviter_id) DO UPDATE SET
                uses = invite_stats.uses + 1,
                last_used_at = CURRENT_TIMESTAMP
            """,
            (int(guild_id), int(inviter_id)),
        )
        await db.commit()
        async with db.execute(
            "SELECT uses FROM invite_stats WHERE guild_id = ? AND inviter_id = ?",
            (int(guild_id), int(inviter_id)),
        ) as cur:
            row = await cur.fetchone()
            return int(row[0]) if row else 0


async def record_rules_agreement(
    guild_id: int,
    user_id: int,
    verified_role_id: Optional[int],
) -> str:
    """Upsert the agreement timestamp without creating duplicate rows."""
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO rules_agreements (guild_id, user_id, verified_role_id, agreed_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, user_id) DO UPDATE SET
                verified_role_id = excluded.verified_role_id,
                agreed_at = CURRENT_TIMESTAMP
            """,
            (int(guild_id), int(user_id), verified_role_id),
        )
        await db.commit()
        async with db.execute(
            "SELECT agreed_at FROM rules_agreements WHERE guild_id = ? AND user_id = ?",
            (int(guild_id), int(user_id)),
        ) as cur:
            row = await cur.fetchone()
            return str(row[0]) if row else ""


async def save_role_panel(
    guild_id: int,
    channel_id: int,
    message_id: int,
    role_ids: list[int],
) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO role_panels (guild_id, channel_id, message_id, role_ids)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(guild_id, channel_id, message_id) DO UPDATE SET
                role_ids = excluded.role_ids
            """,
            (int(guild_id), int(channel_id), int(message_id), json.dumps(role_ids)),
        )
        await db.commit()


async def get_role_panels(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT guild_id, channel_id, message_id, role_ids "
            "FROM role_panels WHERE guild_id = ?",
            (int(guild_id),),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                try:
                    item["role_ids"] = [int(value) for value in json.loads(item["role_ids"])]
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["role_ids"] = []
                rows.append(item)
            return rows


async def save_rules_panel(guild_id: int, channel_id: int, message_id: int) -> None:
    async with connect() as db:
        await db.execute(
            """
            INSERT INTO rules_panels (guild_id, channel_id, message_id)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id, channel_id, message_id) DO NOTHING
            """,
            (int(guild_id), int(channel_id), int(message_id)),
        )
        await db.commit()


async def get_rules_panels(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT guild_id, channel_id, message_id FROM rules_panels WHERE guild_id = ?",
            (int(guild_id),),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def save_self_role_panel(
    guild_id: int,
    channel_id: int,
    message_id: int,
    title: str,
    description: str,
    color: str,
    emoji: str,
    role_specs: list[dict[str, Any]],
) -> dict[str, Any]:
    encoded_specs = json.dumps(role_specs, ensure_ascii=False)
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO self_role_panels
                (guild_id, channel_id, message_id, title, description, color, emoji, role_specs)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id, message_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                title = excluded.title,
                description = excluded.description,
                color = excluded.color,
                emoji = excluded.emoji,
                role_specs = excluded.role_specs,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, guild_id, channel_id, message_id, title, description, color, emoji,
                      role_specs, created_at, updated_at
            """,
            (
                int(guild_id),
                int(channel_id),
                int(message_id),
                str(title),
                str(description),
                str(color),
                str(emoji),
                encoded_specs,
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    result = dict(row) if row else {}
    try:
        result["role_specs"] = json.loads(result.get("role_specs") or "[]")
    except (TypeError, ValueError, json.JSONDecodeError):
        result["role_specs"] = []
    return result


async def get_self_role_panels(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, channel_id, message_id, title, description,
                   color, color_hex, emoji, role_specs, min_level, created_at, updated_at
            FROM self_role_panels
            WHERE guild_id = ?
            ORDER BY id DESC
            """,
            (int(guild_id),),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                try:
                    item["role_specs"] = json.loads(item.get("role_specs") or "[]")
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["role_specs"] = []
                rows.append(item)
            return rows


async def create_self_role_panel(
    guild_id: int,
    channel_id: int,
    title: str,
    description: str,
    min_level: int = 0,
    color_hex: str = "#5865F2",
) -> dict[str, Any]:
    """Create a level-gated panel before its Discord message is published."""
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO self_role_panels
                (guild_id, channel_id, message_id, title, description,
                 min_level, color, color_hex, emoji, role_specs)
            VALUES (?, ?, 0, ?, ?, ?, ?, ?, '', '[]')
            RETURNING id, guild_id, channel_id, message_id, title, description,
                      min_level, color_hex, created_at
            """,
            (
                int(guild_id),
                int(channel_id),
                str(title)[:256],
                str(description)[:4000],
                max(0, int(min_level)),
                str(color_hex).upper(),
                str(color_hex).upper(),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        return dict(row) if row else {}


async def add_panel_button(
    panel_id: int,
    role_id: int,
    label: str,
    emoji: str = "",
    custom_min_level: int = 0,
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO self_role_buttons
                (panel_id, role_id, label, emoji, custom_min_level)
            VALUES (?, ?, ?, ?, ?)
            RETURNING id, panel_id, role_id, label, emoji, custom_min_level
            """,
            (
                int(panel_id),
                int(role_id),
                str(label)[:100],
                str(emoji or "")[:100],
                max(0, int(custom_min_level)),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
        return dict(row) if row else {}


async def get_panel_with_buttons(panel_id: int) -> Optional[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, channel_id, message_id, title, description,
                   min_level, color_hex, color, emoji, role_specs, created_at, updated_at
            FROM self_role_panels
            WHERE id = ?
            """,
            (int(panel_id),),
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            return None
        panel = dict(row)
        async with db.execute(
            """
            SELECT id, panel_id, role_id, label, emoji, custom_min_level
            FROM self_role_buttons
            WHERE panel_id = ?
            ORDER BY id
            """,
            (int(panel_id),),
        ) as cur:
            buttons = [dict(item) for item in await cur.fetchall()]
    # Preserve the old studio's role_specs panels while new buttons are
    # introduced. This keeps existing deployed panels interactive.
    if not buttons:
        try:
            legacy_specs = json.loads(panel.get("role_specs") or "[]")
        except (TypeError, ValueError, json.JSONDecodeError):
            legacy_specs = []
        buttons = [
            {
                "id": 0,
                "panel_id": int(panel["id"]),
                "role_id": int(spec["id"]),
                "label": str(spec.get("label") or ""),
                "emoji": str(spec.get("emoji") or ""),
                "custom_min_level": 0,
            }
            for spec in legacy_specs
            if isinstance(spec, dict) and str(spec.get("id", "")).isdigit()
        ]
    panel["buttons"] = buttons
    panel["min_level"] = max(0, int(panel.get("min_level") or 0))
    return panel


async def get_guild_panels(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT id FROM self_role_panels WHERE guild_id = ? ORDER BY id DESC",
            (int(guild_id),),
        ) as cur:
            ids = [int(row["id"]) for row in await cur.fetchall()]
    resolved = await asyncio.gather(
        *(get_panel_with_buttons(panel_id) for panel_id in ids)
    )
    return [panel for panel in resolved if panel]


async def update_panel_message_id(panel_id: int, message_id: int) -> Optional[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            "UPDATE self_role_panels SET message_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (int(message_id), int(panel_id)),
        )
        await db.commit()
        async with db.execute(
            "SELECT id, guild_id, channel_id, message_id, title, description, "
            "min_level, color_hex, created_at FROM self_role_panels WHERE id = ?",
            (int(panel_id),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_panel(panel_id: int) -> bool:
    async with connect() as db:
        await db.execute("DELETE FROM self_role_buttons WHERE panel_id = ?", (int(panel_id),))
        cursor = await db.execute("DELETE FROM self_role_panels WHERE id = ?", (int(panel_id),))
        await db.commit()
        return cursor.rowcount > 0


def _json_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).isdigit()]


def _json_aliases(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = value.split(",")
    if not isinstance(value, list):
        return []
    result = []
    seen = set()
    for item in value:
        alias = str(item or "").strip().lstrip("!/")
        if not alias or len(alias) > 80 or any(char.isspace() for char in alias):
            continue
        key = alias.casefold()
        if key not in seen:
            seen.add(key)
            result.append(alias)
    return result[:20]


async def get_command_controls(guild_id: int) -> dict[str, dict[str, Any]]:
    """Compatibility wrapper for the canonical command policy cache."""
    return await get_command_policies(guild_id)


async def get_command_policies(
    guild_id: int,
    *,
    refresh: bool = False,
) -> dict[str, dict[str, Any]]:
    guild_id = int(guild_id)
    if not refresh and guild_id in COMMAND_CACHE:
        return {
            name: {**policy, "allowed_roles": list(policy["allowed_roles"]),
                   "allowed_channels": list(policy["allowed_channels"]),
                   "aliases": list(policy["aliases"])}
            for name, policy in COMMAND_CACHE[guild_id].items()
        }
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT command_name, is_enabled, aliases, allowed_roles,
                   allowed_channels, updated_at
            FROM command_policies
            WHERE guild_id = ?
            ORDER BY command_name
            """,
            (guild_id,),
        ) as cur:
            result = {}
            for row in await cur.fetchall():
                item = dict(row)
                item["enabled"] = bool(item.pop("is_enabled"))
                item["aliases"] = _json_aliases(item.get("aliases"))
                item["allowed_roles"] = _json_ids(item["allowed_roles"])
                item["allowed_channels"] = _json_ids(item["allowed_channels"])
                result[item["command_name"]] = item
    COMMAND_CACHE[guild_id] = result
    return {
        name: {**policy, "allowed_roles": list(policy["allowed_roles"]),
               "allowed_channels": list(policy["allowed_channels"]),
               "aliases": list(policy["aliases"])}
        for name, policy in result.items()
    }


def invalidate_command_cache(guild_id: Optional[int] = None) -> None:
    if guild_id is None:
        COMMAND_CACHE.clear()
    else:
        COMMAND_CACHE.pop(int(guild_id), None)


async def save_command_control(
    guild_id: int,
    command_name: str,
    enabled: bool,
    allowed_roles: list[int | str] | None = None,
    allowed_channels: list[int | str] | None = None,
) -> dict[str, Any]:
    """Compatibility wrapper that preserves aliases already on the policy."""
    return await save_command_policy(
        guild_id,
        command_name,
        enabled,
        allowed_roles=allowed_roles,
        allowed_channels=allowed_channels,
    )


async def save_command_policy(
    guild_id: int,
    command_name: str,
    enabled: bool,
    allowed_roles: list[int | str] | None = None,
    allowed_channels: list[int | str] | None = None,
    aliases: list[str] | None = None,
) -> dict[str, Any]:
    guild_id = int(guild_id)
    name = str(command_name).strip().lower()
    roles = [str(role_id) for role_id in (allowed_roles or []) if str(role_id).isdigit()]
    channels = [str(channel_id) for channel_id in (allowed_channels or []) if str(channel_id).isdigit()]
    if allowed_roles is None or allowed_channels is None or aliases is None:
        async with connect(aiosqlite.Row) as db:
            async with db.execute(
                """
                SELECT aliases, allowed_roles, allowed_channels
                FROM command_policies
                WHERE guild_id = ? AND command_name = ?
                """,
                (guild_id, name),
            ) as cur:
                existing = await cur.fetchone()
        if existing:
            if allowed_roles is None:
                roles = _json_ids(existing["allowed_roles"])
            if allowed_channels is None:
                channels = _json_ids(existing["allowed_channels"])
            if aliases is None:
                aliases = _json_aliases(existing["aliases"])
    normalized_aliases = _json_aliases(aliases or [])
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO command_policies
                (guild_id, command_name, is_enabled, aliases,
                 allowed_roles, allowed_channels, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, command_name) DO UPDATE SET
                is_enabled = excluded.is_enabled,
                aliases = excluded.aliases,
                allowed_roles = excluded.allowed_roles,
                allowed_channels = excluded.allowed_channels,
                updated_at = CURRENT_TIMESTAMP
            RETURNING command_name, is_enabled, aliases, allowed_roles,
                      allowed_channels, updated_at
            """,
            (
                guild_id,
                name,
                int(bool(enabled)),
                json.dumps(normalized_aliases, ensure_ascii=False),
                json.dumps(roles, ensure_ascii=False),
                json.dumps(channels, ensure_ascii=False),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    item = dict(row) if row else {
        "command_name": name,
        "is_enabled": int(bool(enabled)),
        "aliases": json.dumps(normalized_aliases, ensure_ascii=False),
        "allowed_roles": json.dumps(roles),
        "allowed_channels": json.dumps(channels),
    }
    result = {
        "command_name": name,
        "enabled": bool(enabled),
        "aliases": _json_aliases(item.get("aliases")),
        "allowed_roles": _json_ids(item.get("allowed_roles")),
        "allowed_channels": _json_ids(item.get("allowed_channels")),
        "updated_at": item.get("updated_at"),
    }
    COMMAND_CACHE.setdefault(guild_id, {})[name] = result
    return result


async def get_auto_responders(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, trigger, match_type, response, enabled,
                   cooldown_seconds, bucket_capacity, channel_id,
                   target_type, target_id, reaction_emoji,
                   execution_count, updated_at
            FROM guild_auto_responders
            WHERE guild_id = ? AND enabled = 1
            ORDER BY id
            """,
            (int(guild_id),),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                item["enabled"] = bool(item["enabled"])
                item["cooldown_seconds"] = max(0.0, float(item["cooldown_seconds"]))
                item["bucket_capacity"] = max(1, int(item["bucket_capacity"]))
                item["channel_id"] = (
                    str(item["channel_id"]) if item["channel_id"] is not None else None
                )
                item["target_type"] = (
                    item.get("target_type")
                    if item.get("target_type") in {"everyone", "role", "user"}
                    else "everyone"
                )
                item["target_id"] = max(0, int(item.get("target_id") or 0))
                item["reaction_emoji"] = str(item.get("reaction_emoji") or "")[:100]
                item["execution_count"] = max(0, int(item["execution_count"] or 0))
                rows.append(item)
            return rows


async def save_auto_responder(
    guild_id: int,
    trigger: str,
    match_type: str,
    response: str,
    *,
    enabled: bool = True,
    cooldown_seconds: float = 5.0,
    bucket_capacity: int = 1,
    channel_id: int | str | None = None,
    target_type: str = "everyone",
    target_id: int | str | None = 0,
    reaction_emoji: str = "",
) -> dict[str, Any]:
    target_type = str(target_type).strip().lower()
    if target_type not in {"everyone", "role", "user"}:
        raise ValueError("target_type must be one of everyone, role, user")
    try:
        target_id = max(0, int(target_id or 0))
    except (TypeError, ValueError) as error:
        raise ValueError("target_id must be a numeric Discord ID") from error
    reaction_emoji = str(reaction_emoji or "").strip()[:100]
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO guild_auto_responders
                (guild_id, trigger, match_type, response, enabled,
                 cooldown_seconds, bucket_capacity, channel_id,
                 target_type, target_id, reaction_emoji, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, trigger, match_type, target_type, target_id) DO UPDATE SET
                response = excluded.response,
                enabled = excluded.enabled,
                cooldown_seconds = excluded.cooldown_seconds,
                bucket_capacity = excluded.bucket_capacity,
                channel_id = excluded.channel_id,
                target_type = excluded.target_type,
                target_id = excluded.target_id,
                reaction_emoji = excluded.reaction_emoji,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, guild_id, trigger, match_type, response, enabled,
                      cooldown_seconds, bucket_capacity, channel_id,
                       target_type, target_id, reaction_emoji,
                       execution_count, updated_at
            """,
            (
                int(guild_id),
                str(trigger).strip(),
                str(match_type).strip().lower(),
                str(response)[:2000],
                int(bool(enabled)),
                max(0.0, float(cooldown_seconds)),
                max(1, int(bucket_capacity)),
                int(channel_id) if channel_id is not None else None,
                target_type,
                target_id,
                reaction_emoji,
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    item = dict(row) if row else {}
    item["enabled"] = bool(item.get("enabled", enabled))
    item["channel_id"] = (
        str(item["channel_id"]) if item.get("channel_id") is not None else None
    )
    item["execution_count"] = int(item.get("execution_count") or 0)
    return item


async def delete_auto_responder(guild_id: int, rule_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "DELETE FROM guild_auto_responders WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(rule_id)),
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def record_auto_responder_execution(guild_id: int, rule_id: int) -> int:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE guild_auto_responders
            SET execution_count = execution_count + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ? AND id = ?
            """,
            (int(guild_id), int(rule_id)),
        )
        async with db.execute(
            "SELECT execution_count FROM guild_auto_responders WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(rule_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return int(row["execution_count"]) if row else 0


async def get_shortcuts(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, trigger, target_type, target, announcement,
                   enabled, updated_at
            FROM guild_shortcuts
            WHERE guild_id = ? AND enabled = 1
            ORDER BY id
            """,
            (int(guild_id),),
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                item["enabled"] = bool(item["enabled"])
                rows.append(item)
            return rows


async def save_shortcut(
    guild_id: int,
    trigger: str,
    target_type: str,
    *,
    target: str = "",
    announcement: str = "",
    enabled: bool = True,
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO guild_shortcuts
                (guild_id, trigger, target_type, target, announcement,
                 enabled, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, trigger) DO UPDATE SET
                target_type = excluded.target_type,
                target = excluded.target,
                announcement = excluded.announcement,
                enabled = excluded.enabled,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, guild_id, trigger, target_type, target, announcement,
                      enabled, updated_at
            """,
            (
                int(guild_id),
                str(trigger).strip(),
                str(target_type).strip().lower(),
                str(target)[:100],
                str(announcement)[:2000],
                int(bool(enabled)),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    item = dict(row) if row else {}
    item["enabled"] = bool(item.get("enabled", enabled))
    return item


async def delete_shortcut(guild_id: int, shortcut_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "DELETE FROM guild_shortcuts WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(shortcut_id)),
        )
        await db.commit()
    return cursor.rowcount > 0


def _ticket_json_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
    return [str(item) for item in value] if isinstance(value, list) else []


async def save_ticket_panel(
    guild_id: int,
    channel_id: int,
    message_id: int,
    categories: list[dict[str, Any]],
) -> dict[str, Any]:
    encoded = json.dumps(categories, ensure_ascii=False)
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            INSERT INTO ticket_panels
                (guild_id, channel_id, message_id, categories, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, channel_id, message_id) DO UPDATE SET
                categories = excluded.categories,
                updated_at = CURRENT_TIMESTAMP
            """,
            (int(guild_id), int(channel_id), int(message_id), encoded),
        )
        await db.commit()
    return {
        "guild_id": str(guild_id),
        "channel_id": str(channel_id),
        "message_id": str(message_id),
        "categories": categories,
    }


async def get_ticket_panels() -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT guild_id, channel_id, message_id, categories FROM ticket_panels"
        ) as cur:
            rows = []
            for row in await cur.fetchall():
                item = dict(row)
                item["guild_id"] = int(item["guild_id"])
                item["channel_id"] = int(item["channel_id"])
                item["message_id"] = int(item["message_id"])
                try:
                    item["categories"] = json.loads(item["categories"])
                except (TypeError, ValueError, json.JSONDecodeError):
                    item["categories"] = []
                rows.append(item)
            return rows


async def create_ticket(
    guild_id: int,
    channel_id: int,
    user_id: int,
    category_key: str,
    category_label: str,
    subject: str,
    details: str,
    support_role_ids: list[int | str] | None = None,
    senior_role_ids: list[int | str] | None = None,
    intake_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    support = [str(item) for item in (support_role_ids or [])]
    senior = [str(item) for item in (senior_role_ids or [])]
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO tickets
                (guild_id, channel_id, user_id, category_key, category_label,
                 subject, details, support_role_ids, senior_role_ids, intake_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            RETURNING *
            """,
            (
                int(guild_id), int(channel_id), int(user_id),
                str(category_key)[:80], str(category_label)[:120],
                str(subject)[:200], str(details)[:4000],
                json.dumps(support), json.dumps(senior),
                json.dumps(intake_data or {}, ensure_ascii=False),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    return _ticket_row(dict(row))


def _ticket_row(item: dict[str, Any]) -> dict[str, Any]:
    for key in ("support_role_ids", "senior_role_ids"):
        item[key] = _ticket_json_ids(item.get(key))
    raw_intake = item.get("intake_data")
    if isinstance(raw_intake, str):
        try:
            raw_intake = json.loads(raw_intake)
        except (TypeError, ValueError, json.JSONDecodeError):
            raw_intake = {}
    item["intake_data"] = raw_intake if isinstance(raw_intake, dict) else {}
    for key in ("guild_id", "channel_id", "user_id", "id", "claimed_by", "closed_by"):
        if item.get(key) is not None:
            item[key] = int(item[key])
    return item


async def get_ticket_by_channel(channel_id: int) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT * FROM tickets WHERE channel_id = ?",
            (int(channel_id),),
        ) as cur:
            row = await cur.fetchone()
    return _ticket_row(dict(row)) if row else None


async def get_ticket(guild_id: int, ticket_id: int) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
    return _ticket_row(dict(row)) if row else None


async def get_active_tickets(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT * FROM tickets
            WHERE guild_id = ? AND status != 'closed'
            ORDER BY
                CASE priority WHEN 'management' THEN 0 WHEN 'high' THEN 1 ELSE 2 END,
                CASE status WHEN 'waiting_staff' THEN 0 ELSE 1 END,
                opened_at ASC, id ASC
            """,
            (int(guild_id),),
        ) as cur:
            return [_ticket_row(dict(row)) for row in await cur.fetchall()]


async def claim_ticket(guild_id: int, ticket_id: int, staff_id: int) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets SET claimed_by = ?, status = 'active', waiting_since = NULL
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (int(staff_id), int(guild_id), int(ticket_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def unclaim_ticket(
    guild_id: int, ticket_id: int, staff_id: int
) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets
            SET claimed_by = NULL,
                status = 'waiting_staff',
                waiting_since = COALESCE(waiting_since, CURRENT_TIMESTAMP)
            WHERE guild_id = ? AND id = ? AND claimed_by = ? AND status != 'closed'
            """,
            (int(guild_id), int(ticket_id), int(staff_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def escalate_ticket(
    guild_id: int,
    ticket_id: int,
    priority: str,
) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets SET priority = ?, escalated_at = CURRENT_TIMESTAMP
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (str(priority), int(guild_id), int(ticket_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def record_ticket_response(guild_id: int, ticket_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            """
            UPDATE tickets
            SET first_response_at = COALESCE(first_response_at, CURRENT_TIMESTAMP),
                status = 'active', waiting_since = NULL
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (int(guild_id), int(ticket_id)),
        )
        await db.commit()
    return cursor.rowcount > 0


async def record_ticket_user_message(guild_id: int, ticket_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            """
            UPDATE tickets
            SET status = 'waiting_staff',
                waiting_since = COALESCE(waiting_since, CURRENT_TIMESTAMP),
                last_user_message_at = CURRENT_TIMESTAMP
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (int(guild_id), int(ticket_id)),
        )
        await db.commit()
    return cursor.rowcount > 0


async def set_ticket_status(
    guild_id: int,
    ticket_id: int,
    status: str,
    *,
    staff_id: int | None = None,
) -> dict[str, Any] | None:
    allowed = {"active", "waiting_user", "waiting_staff"}
    if status not in allowed:
        raise ValueError("invalid ticket status")
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets
            SET status = ?,
                waiting_since = CASE WHEN ? = 'active' THEN NULL ELSE CURRENT_TIMESTAMP END,
                claimed_by = COALESCE(?, claimed_by)
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (
                status,
                status,
                int(staff_id) if staff_id is not None else None,
                int(guild_id),
                int(ticket_id),
            ),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def set_ticket_priority(
    guild_id: int, ticket_id: int, priority: str
) -> dict[str, Any] | None:
    allowed = {"normal", "high", "management"}
    if priority not in allowed:
        raise ValueError("invalid ticket priority")
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets SET priority = ?,
                escalated_at = CASE WHEN ? = 'management' THEN CURRENT_TIMESTAMP ELSE escalated_at END
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (priority, priority, int(guild_id), int(ticket_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def reopen_ticket(
    guild_id: int, ticket_id: int, staff_id: int
) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets
            SET status = 'active', closed_at = NULL, closed_by = NULL,
                close_reason = '', waiting_since = NULL, claimed_by = ?
            WHERE guild_id = ? AND id = ? AND status = 'closed'
            """,
            (int(staff_id), int(guild_id), int(ticket_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def add_ticket_note(
    guild_id: int,
    ticket_id: int,
    staff_id: int,
    content: str,
) -> dict[str, Any] | None:
    text = str(content).strip()[:2000]
    if not text:
        return None
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO ticket_notes (ticket_id, guild_id, staff_id, content)
            SELECT ?, ?, ?, ?
            WHERE EXISTS (
                SELECT 1 FROM tickets
                WHERE id = ? AND guild_id = ?
            )
            RETURNING *
            """,
            (int(ticket_id), int(guild_id), int(staff_id), text, int(ticket_id), int(guild_id)),
        )
        row = await cursor.fetchone()
        await db.commit()
    return dict(row) if row else None


async def get_ticket_notes(guild_id: int, ticket_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT * FROM ticket_notes
            WHERE guild_id = ? AND ticket_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 100
            """,
            (int(guild_id), int(ticket_id)),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def close_ticket(
    guild_id: int,
    ticket_id: int,
    staff_id: int,
    reason: str,
) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            UPDATE tickets
            SET status = 'closed', closed_at = CURRENT_TIMESTAMP,
                closed_by = ?, close_reason = ?
            WHERE guild_id = ? AND id = ? AND status != 'closed'
            """,
            (int(staff_id), str(reason)[:1000], int(guild_id), int(ticket_id)),
        )
        async with db.execute(
            "SELECT * FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return _ticket_row(dict(row)) if row else None


async def save_ticket_transcript(
    ticket_id: int,
    guild_id: int,
    channel_id: int,
    content_text: str,
    content_html: str,
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO ticket_transcripts
                (ticket_id, guild_id, channel_id, content_text, content_html)
            VALUES (?, ?, ?, ?, ?)
            RETURNING *
            """,
            (
                int(ticket_id), int(guild_id), int(channel_id),
                str(content_text), str(content_html),
            ),
        )
        row = await cursor.fetchone()
        await db.commit()
    return dict(row)


async def get_ticket_transcripts(
    guild_id: int,
    query: str = "",
) -> list[dict[str, Any]]:
    pattern = f"%{str(query).strip()}%"
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT tt.*, t.user_id, t.category_label, t.subject, t.closed_by
            FROM ticket_transcripts tt
            JOIN tickets t ON t.id = tt.ticket_id
            WHERE tt.guild_id = ?
              AND (
                ? = '' OR t.subject LIKE ? OR t.category_label LIKE ?
                OR tt.content_text LIKE ?
              )
            ORDER BY tt.created_at DESC, tt.id DESC
            LIMIT 100
            """,
            (int(guild_id), str(query).strip(), pattern, pattern, pattern),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_ticket_archive(
    guild_id: int,
    query: str = "",
) -> list[dict[str, Any]]:
    value = str(query).strip()
    pattern = f"%{value}%"
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT t.*, tt.id AS transcript_id, tt.created_at AS transcript_created_at
            FROM tickets t
            LEFT JOIN ticket_transcripts tt ON tt.ticket_id = t.id
            WHERE t.guild_id = ? AND t.status = 'closed'
              AND (
                ? = '' OR t.subject LIKE ? OR t.category_label LIKE ?
                OR t.close_reason LIKE ?
              )
            ORDER BY t.closed_at DESC, t.id DESC
            LIMIT 200
            """,
            (int(guild_id), value, pattern, pattern, pattern),
        ) as cur:
            return [_ticket_row(dict(row)) for row in await cur.fetchall()]


async def get_ticket_transcript(
    guild_id: int,
    ticket_id: int,
) -> dict[str, Any] | None:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT tt.*, t.user_id, t.category_label, t.subject, t.closed_by,
                   t.close_reason
            FROM ticket_transcripts tt
            JOIN tickets t ON t.id = tt.ticket_id
            WHERE tt.guild_id = ? AND tt.ticket_id = ?
            ORDER BY tt.id DESC
            LIMIT 1
            """,
            (int(guild_id), int(ticket_id)),
        ) as cur:
            row = await cur.fetchone()
    return dict(row) if row else None


async def save_ticket_rating(
    ticket_id: int,
    guild_id: int,
    user_id: int,
    stars: int,
    feedback: str = "",
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT closed_by FROM tickets WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(ticket_id)),
        ) as cur:
            ticket = await cur.fetchone()
        staff_id = ticket["closed_by"] if ticket else None
        cursor = await db.execute(
            """
            INSERT INTO ticket_ratings
                (ticket_id, guild_id, staff_id, user_id, stars, feedback)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                stars = excluded.stars,
                feedback = excluded.feedback,
                staff_id = excluded.staff_id
            RETURNING *
            """,
            (
                int(ticket_id), int(guild_id),
                int(staff_id) if staff_id is not None else None,
                int(user_id), max(1, min(5, int(stars))), str(feedback)[:1000],
            ),
        )
        row = await cursor.fetchone()
        await db.execute(
            "UPDATE tickets SET rating = ? WHERE guild_id = ? AND id = ?",
            (max(1, min(5, int(stars))), int(guild_id), int(ticket_id)),
        )
        await db.commit()
    return dict(row)


async def get_staff_kpis(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT
                COALESCE(t.claimed_by, t.closed_by) AS staff_id,
                COUNT(t.id) AS tickets_handled,
                ROUND(AVG(
                    CASE WHEN t.first_response_at IS NOT NULL
                    THEN (julianday(t.first_response_at) - julianday(t.opened_at)) * 86400
                    END
                ), 1) AS avg_response_seconds,
                ROUND(AVG(
                    CASE WHEN t.closed_at IS NOT NULL
                    THEN (julianday(t.closed_at) - julianday(t.opened_at)) * 86400
                    END
                ), 1) AS avg_resolution_seconds,
                COUNT(r.id) AS ratings_count,
                ROUND(AVG(r.stars), 2) AS avg_rating
            FROM tickets t
            LEFT JOIN ticket_ratings r ON r.ticket_id = t.id
            WHERE t.guild_id = ? AND COALESCE(t.claimed_by, t.closed_by) IS NOT NULL
            GROUP BY COALESCE(t.claimed_by, t.closed_by)
            ORDER BY tickets_handled DESC, avg_rating DESC
            """,
            (int(guild_id),),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_canned_responses(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, title, content, category, shortcut, sticker_id,
                   created_by, updated_at
            FROM canned_responses
            WHERE guild_id = ?
            ORDER BY updated_at DESC, id DESC
            """,
            (int(guild_id),),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def save_canned_response(
    guild_id: int,
    title: str,
    content: str,
    category: str = "عام",
    created_by: int | str | None = None,
    response_id: int | None = None,
    shortcut: str | None = None,
    sticker_id: int | str | None = None,
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        if response_id is not None:
            cursor = await db.execute(
                """
                UPDATE canned_responses
                SET title = ?, content = ?, category = ?, shortcut = ?, sticker_id = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE guild_id = ? AND id = ?
                """,
                (
                    str(title)[:120], str(content)[:2000], str(category)[:80],
                    str(shortcut).strip()[:80] if shortcut else None,
                    int(sticker_id) if sticker_id not in (None, "") else None,
                    int(guild_id), int(response_id),
                ),
            )
        else:
            cursor = await db.execute(
                """
                INSERT INTO canned_responses
                    (guild_id, title, content, category, shortcut, sticker_id, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, title) DO UPDATE SET
                    content = excluded.content,
                    category = excluded.category,
                    shortcut = excluded.shortcut,
                    sticker_id = excluded.sticker_id,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    int(guild_id), str(title)[:120], str(content)[:2000],
                    str(category)[:80],
                    str(shortcut).strip()[:80] if shortcut else None,
                    int(sticker_id) if sticker_id not in (None, "") else None,
                    int(created_by) if created_by is not None else None,
                ),
            )
        if response_id is not None and cursor.rowcount == 0:
            await db.commit()
            return {}
        async with db.execute(
            """
            SELECT id, guild_id, title, content, category, shortcut, sticker_id,
                   created_by, updated_at
            FROM canned_responses
            WHERE guild_id = ? AND title = ?
            """,
            (int(guild_id), str(title)[:120]),
        ) as cur:
            row = await cur.fetchone()
        await db.commit()
    return dict(row) if row else {}


async def delete_canned_response(guild_id: int, response_id: int) -> bool:
    async with connect() as db:
        cursor = await db.execute(
            "DELETE FROM canned_responses WHERE guild_id = ? AND id = ?",
            (int(guild_id), int(response_id)),
        )
        deleted = cursor.rowcount > 0
        await db.commit()
    return deleted


async def get_recent_warnings(guild_id: int, limit: int = 50) -> List[Dict[str, Any]]:
    """جلب أحدث مخالفات السيرفر بصيغة مناسبة للـ API."""
    limit = max(1, min(int(limit), 100))
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT id, user_id, guild_id, moderator_id, reason, timestamp "
            "FROM warnings WHERE guild_id = ? ORDER BY id DESC LIMIT ?",
            (int(guild_id), limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_dashboard_stats(
    guild_id: int,
    *,
    member_count: int | None = None,
    latency_series: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return the shared dashboard snapshot used by REST and live charts."""
    guild_id = int(guild_id)
    now = time.monotonic()
    cached = _stats_cache.get(guild_id)
    if cached and now - cached[0] < 5:
        snapshot = dict(cached[1])
        snapshot["series"] = list(latency_series or snapshot.get("series", []))
        if member_count is not None:
            snapshot["guild"]["members"] = int(member_count)
        return snapshot

    async with connect(aiosqlite.Row) as db:
        queries = {
            "tickets_active": (
                "SELECT COUNT(*) AS value FROM tickets "
                "WHERE guild_id = ? AND status NOT IN ('closed', 'archived')"
            ),
            "tickets_archive": (
                "SELECT COUNT(*) AS value FROM tickets "
                "WHERE guild_id = ? AND status IN ('closed', 'archived')"
            ),
            "infractions": "SELECT COUNT(*) AS value FROM warnings WHERE guild_id = ?",
            "auto_responses": (
                "SELECT COUNT(*) AS value FROM guild_auto_responders "
                "WHERE guild_id = ? AND enabled = 1"
            ),
            "commands_enabled": (
                "SELECT COUNT(*) AS value FROM guild_command_controls "
                "WHERE guild_id = ? AND enabled = 1"
            ),
            "economy_accounts": (
                "SELECT COUNT(*) AS value FROM users WHERE guild_id = ?"
            ),
        }
        counts: dict[str, int] = {}
        for key, query in queries.items():
            async with db.execute(query, (guild_id,)) as cursor:
                row = await cursor.fetchone()
            counts[key] = int(row["value"]) if row else 0

    snapshot = {
        "guild": {"id": str(guild_id), "members": member_count},
        "counts": counts,
        "series": list(latency_series or []),
        "updated_at": _utc_now(),
    }
    _stats_cache[guild_id] = (now, snapshot)
    while len(_stats_cache) > 256:
        _stats_cache.popitem(last=False)
    return snapshot


async def get_warning(warning_id: int) -> Optional[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT id, user_id, guild_id, moderator_id, reason, timestamp "
            "FROM warnings WHERE id = ?",
            (int(warning_id),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_warning(guild_id: int, warning_id: int) -> bool:
    """حذف إنذار واحد مع تقييد العملية بسيرفره الأصلي."""
    async with connect() as db:
        cur = await db.execute(
            "DELETE FROM warnings WHERE id = ? AND guild_id = ?",
            (int(warning_id), int(guild_id)),
        )
        changed = cur.rowcount > 0
        await cur.close()
        await db.commit()
        return changed


# -------------------------------------------------------------
# التذكيرات الدائمة (Persistent reminders)
# -------------------------------------------------------------
async def create_reminder(
    guild_id: int,
    user_id: int,
    channel_id: int,
    reminder: str,
    due_at: str,
) -> int:
    async with connect() as db:
        cur = await db.execute(
            """
            INSERT INTO reminders
                (guild_id, user_id, channel_id, reminder, due_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                int(guild_id),
                int(user_id),
                int(channel_id),
                str(reminder).strip()[:1000],
                str(due_at),
            ),
        )
        reminder_id = cur.lastrowid
        await db.commit()
    return int(reminder_id)


async def get_due_reminders(now: Optional[str] = None) -> list[Dict[str, Any]]:
    current = now or _utc_now()
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, user_id, channel_id, reminder, due_at
            FROM reminders
            WHERE status = 'pending' AND due_at <= ?
            ORDER BY due_at ASC, id ASC
            LIMIT 100
            """,
            (current,),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def get_user_reminders(
    guild_id: int,
    user_id: int,
    limit: int = 20,
) -> list[Dict[str, Any]]:
    limit = max(1, min(int(limit), 50))
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, channel_id, reminder, due_at, status
            FROM reminders
            WHERE guild_id = ? AND user_id = ? AND status = 'pending'
            ORDER BY due_at ASC
            LIMIT ?
            """,
            (int(guild_id), int(user_id), limit),
        ) as cur:
            return [dict(row) for row in await cur.fetchall()]


async def cancel_reminder(guild_id: int, user_id: int, reminder_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE reminders SET status = 'cancelled'
            WHERE id = ? AND guild_id = ? AND user_id = ? AND status = 'pending'
            """,
            (int(reminder_id), int(guild_id), int(user_id)),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed


async def complete_reminder(reminder_id: int) -> bool:
    async with connect() as db:
        cur = await db.execute(
            """
            UPDATE reminders SET status = 'completed'
            WHERE id = ? AND status = 'pending'
            """,
            (int(reminder_id),),
        )
        changed = cur.rowcount > 0
        await db.commit()
    return changed
