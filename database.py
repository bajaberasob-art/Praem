import aiosqlite
import asyncio
import json
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

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
    "welcome_message": ("TEXT", "", "str"),
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

            # فهارس لتسريع استعلامات الرتب ولوحة الشرف (Leaderboard)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_xp ON users(guild_id, xp DESC);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);")
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
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (guild_id, command_name)
                );
            """)
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_command_controls_guild "
                "ON guild_command_controls(guild_id);"
            )
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
                    execution_count INTEGER NOT NULL DEFAULT 0,
                    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE (guild_id, trigger, match_type)
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

            await db.commit()
            logger.info("[DB] جميع الجداول والفهارس تعمل بكفاءة عالية.")
    except Exception as e:
        logger.error(f"[DB_FATAL] خطأ أثناء إنشاء الجداول: {e}")
        raise
    _settings_cache.clear()


# -------------------------------------------------------------
# إعدادات السيرفر (Guild Settings API) مع كاش LRU/TTL
# -------------------------------------------------------------
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
        if not text.isdigit() or not 15 <= len(text) <= 22:
            raise ValueError("معرّف ديسكورد غير صالح")
        return int(text)
    if kind == "int":
        if isinstance(value, float) and not value.is_integer():
            raise ValueError("يجب أن تكون القيمة عدداً صحيحاً")
        if not isinstance(value, (int, float)):
            raise ValueError("يجب أن تكون القيمة رقماً")
        value = int(value)
        limits = {"anti_alt_days": (0, 365), "daily_amount": (0, 1_000_000)}
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
    # str
    if not isinstance(value, str):
        raise ValueError("يجب أن تكون القيمة نصاً")
    value = value.replace("\r\n", "\n").replace("\x00", "")
    if key == "prefix":
        value = value.strip()
        if not 1 <= len(value) <= 5 or any(ch.isspace() for ch in value):
            raise ValueError("البادئة يجب أن تكون من 1 إلى 5 أحرف بدون مسافات")
    elif key in {"welcome_message", "leave_message"} and len(value) > 1000:
        raise ValueError("رسالة الترحيب يجب ألا تتجاوز 1000 حرف")
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
        if SETTINGS_SCHEMA.get(key, (None, None, None))[2] == "json_list"
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
    """جلب بيانات العضو أو إنشائه بقيم افتراضية بأقل استهلاك للموارد."""
    async with connect() as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return dict(row)

        # إنشاء حساب جديد إذا لم يكن موجوداً
        await db.execute(
            "INSERT INTO users (user_id, guild_id) VALUES (?, ?)",
            (user_id, guild_id),
        )
        await db.commit()
        return {
            "user_id": user_id,
            "guild_id": guild_id,
            "xp": 0,
            "level": 1,
            "balance": 100,
            "bank": 0,
            "last_daily": None,
        }


async def add_xp(user_id: int, guild_id: int, amount: int = 15) -> Tuple[bool, int]:
    """إضافة خبرة وفحص الترقية (Level Up) مع منع التضارب."""
    user = await get_or_create_user(user_id, guild_id)
    new_xp = user["xp"] + amount
    current_level = user["level"]
    xp_needed = current_level * 120
    leveled_up = False

    if new_xp >= xp_needed:
        current_level += 1
        new_xp = new_xp - xp_needed
        leveled_up = True

    async with connect() as db:
        await db.execute(
            "UPDATE users SET xp = ?, level = ? WHERE user_id = ? AND guild_id = ?",
            (new_xp, current_level, user_id, guild_id),
        )
        await db.commit()
    return leveled_up, current_level


async def update_balance(
    user_id: int,
    guild_id: int,
    amount: int,
    account: str = "balance",
) -> int:
    """تعديل رصيد العضو (كاش أو بنك) بأمان وحماية من الرصيد السالب."""
    col = "bank" if account == "bank" else "balance"
    async with connect() as db:
        # استخدام Parameterized Query لتجنب ثغرات حقن الاستعلامات
        query = f"UPDATE users SET {col} = MAX(0, {col} + ?) WHERE user_id = ? AND guild_id = ?"
        await db.execute(query, (amount, user_id, guild_id))
        await db.commit()

        async with db.execute(
            f"SELECT {col} FROM users WHERE user_id = ? AND guild_id = ?",
            (user_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0


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
                   color, emoji, role_specs, created_at, updated_at
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


def _json_ids(value: Any) -> list[str]:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = []
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).isdigit()]


async def get_command_controls(guild_id: int) -> dict[str, dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT command_name, enabled, allowed_roles, updated_at
            FROM guild_command_controls
            WHERE guild_id = ?
            ORDER BY command_name
            """,
            (int(guild_id),),
        ) as cur:
            result = {}
            for row in await cur.fetchall():
                item = dict(row)
                item["enabled"] = bool(item["enabled"])
                item["allowed_roles"] = _json_ids(item["allowed_roles"])
                result[item["command_name"]] = item
            return result


async def save_command_control(
    guild_id: int,
    command_name: str,
    enabled: bool,
    allowed_roles: list[int | str] | None = None,
) -> dict[str, Any]:
    roles = [str(role_id) for role_id in (allowed_roles or []) if str(role_id).isdigit()]
    async with connect(aiosqlite.Row) as db:
        await db.execute(
            """
            INSERT INTO guild_command_controls
                (guild_id, command_name, enabled, allowed_roles, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, command_name) DO UPDATE SET
                enabled = excluded.enabled,
                allowed_roles = excluded.allowed_roles,
                updated_at = CURRENT_TIMESTAMP
            """,
            (
                int(guild_id),
                str(command_name).strip().lower(),
                int(bool(enabled)),
                json.dumps(roles, ensure_ascii=False),
            ),
        )
        await db.commit()
    return {
        "command_name": str(command_name).strip().lower(),
        "enabled": bool(enabled),
        "allowed_roles": roles,
    }


async def get_auto_responders(guild_id: int) -> list[dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            """
            SELECT id, guild_id, trigger, match_type, response, enabled,
                   cooldown_seconds, bucket_capacity, channel_id,
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
) -> dict[str, Any]:
    async with connect(aiosqlite.Row) as db:
        cursor = await db.execute(
            """
            INSERT INTO guild_auto_responders
                (guild_id, trigger, match_type, response, enabled,
                 cooldown_seconds, bucket_capacity, channel_id, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(guild_id, trigger, match_type) DO UPDATE SET
                response = excluded.response,
                enabled = excluded.enabled,
                cooldown_seconds = excluded.cooldown_seconds,
                bucket_capacity = excluded.bucket_capacity,
                channel_id = excluded.channel_id,
                updated_at = CURRENT_TIMESTAMP
            RETURNING id, guild_id, trigger, match_type, response, enabled,
                      cooldown_seconds, bucket_capacity, channel_id,
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


async def get_warning(warning_id: int) -> Optional[Dict[str, Any]]:
    async with connect(aiosqlite.Row) as db:
        async with db.execute(
            "SELECT id, user_id, guild_id, moderator_id, reason, timestamp "
            "FROM warnings WHERE id = ?",
            (int(warning_id),),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def delete_warning(warning_id: int) -> bool:
    """حذف إنذار واحد بعد تحقق المستدعي من نطاق السيرفر والصلاحية."""
    async with connect() as db:
        cur = await db.execute("DELETE FROM warnings WHERE id = ?", (int(warning_id),))
        changed = cur.rowcount > 0
        await cur.close()
        await db.commit()
        return changed
