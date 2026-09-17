import asyncio
import os
import unittest
from types import SimpleNamespace

import database
from cogs import moderation as moderation_module


class FakeGuild:
    id = 1550042204091715634


class FakeMessage:
    def __init__(self, content, user_id=42, mentions=None):
        self.content = content
        self.id = 1
        self.guild = FakeGuild()
        self.author = SimpleNamespace(
            id=user_id,
            bot=False,
            mention=f"<@{user_id}>",
            guild_permissions=SimpleNamespace(manage_messages=False),
        )
        self.mentions = mentions or []
        self.channel = SimpleNamespace(mention="#general")


class FakeBot:
    user = SimpleNamespace(id=999)


class AutoModTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database.DB_NAME = "/tmp/test_moderation_automod.db"
        if os.path.exists(database.DB_NAME):
            os.remove(database.DB_NAME)
        await database.init_db()
        self.mod = moderation_module.Moderation(FakeBot())
        self.actions = []

        async def fake_action(message, reason, **kwargs):
            self.actions.append((reason, kwargs))

        self.mod._apply_violation = fake_action

        async def config(_guild_id):
            return {
                "anti_invites": True,
                "anti_links": True,
                "anti_spam": True,
                "anti_mass_mention": True,
                "banned_words_list": ["forbidden phrase"],
                "log_channel_id": None,
            }

        self.mod.moderation_settings = config

    async def test_dynamic_link_and_word_rules(self):
        await self.mod.on_message(FakeMessage("join https://discord.gg/abc123"))
        self.assertEqual(self.actions[0][0], "نشر رابط دعوة Discord ممنوع")

        self.actions.clear()
        await self.mod.on_message(FakeMessage("this contains forbidden phrase"))
        self.assertEqual(self.actions[0][0], "استخدام كلمة محظورة")

    async def test_mass_mentions_threshold_is_more_than_five(self):
        await self.mod.on_message(FakeMessage("hello", mentions=[object() for _ in range(5)]))
        self.assertEqual(self.actions, [])
        await self.mod.on_message(FakeMessage("hello", mentions=[object() for _ in range(6)]))
        self.assertEqual(self.actions[0][1]["timeout_minutes"], 5)

    async def test_spam_triggers_on_sixth_message_in_three_seconds(self):
        for index in range(5):
            await self.mod.on_message(FakeMessage(f"message {index}"))
        self.assertEqual(self.actions, [])
        await self.mod.on_message(FakeMessage("message 5"))
        self.assertEqual(self.actions[0][1]["timeout_minutes"], 5)

    async def test_warning_helpers_use_database(self):
        await database.add_warning(42, FakeGuild.id, 999, "رابط مشبوه")
        records = await self.mod.get_recent_infractions(FakeGuild.id)
        self.assertEqual(len(records), 1)
        revoked = await self.mod.revoke_warning(records[0]["id"])
        self.assertEqual(revoked["user_id"], 42)
        self.assertEqual(await self.mod.get_recent_infractions(FakeGuild.id), [])


if __name__ == "__main__":
    unittest.main()