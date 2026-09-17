import aiosqlite
import logging
from typing import Any, Dict, List, Optional, Tuple

DB_NAME = "bot_database.db"
logger = logging.getLogger("DatabaseEngine")


async def init_db() -> None:
    """تهيئة الجداول، العلاقات، والفهارس مع تفعيل قيود المفاتيح الخارجية."""
    try:
        async with aiosqlite.connect(DB_NAME) as db:
            await db.execute("PRAGMA foreign_keys = ON;")
            await db.execute("PRAGMA journal_mode = WAL;")

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

            # فهارس لتسريع استعلامات الرتب ولوحة الشرف (Leaderboard)
            await db.execute("CREATE INDEX IF NOT EXISTS idx_users_guild_xp ON users(guild_id, xp DESC);")
            await db.execute("CREATE INDEX IF NOT EXISTS idx_warnings_guild_user ON warnings(guild_id, user_id);")

            await db.commit()
            logger.info("[DB] جميع الجداول والفهارس تعمل بكفاءة عالية.")
    except Exception as e:
        logger.error(f"[DB_FATAL] خطأ أثناء إنشاء الجداول: {e}")
        raise


# -------------------------------------------------------------
# دوال الاقتصاد والمستويات (Economy & Levels API)
# -------------------------------------------------------------
async def get_or_create_user(user_id: int, guild_id: int) -> Dict[str, Any]:
    """جلب بيانات العضو أو إنشائه بقيم افتراضية بأقل استهلاك للموارد."""
    async with aiosqlite.connect(DB_NAME) as db:
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

    async with aiosqlite.connect(DB_NAME) as db:
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
    async with aiosqlite.connect(DB_NAME) as db:
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
    async with aiosqlite.connect(DB_NAME) as db:
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
    async with aiosqlite.connect(DB_NAME) as db:
        async with db.execute(
            "SELECT id, reason, timestamp FROM warnings "
            "WHERE user_id = ? AND guild_id = ? ORDER BY id DESC LIMIT 10",
            (user_id, guild_id),
        ) as cur:
            return await cur.fetchall()
