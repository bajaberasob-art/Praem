import os
import re
import unittest
from types import SimpleNamespace

import database
from cogs.utilities import Utilities, dynamic_prefix


class FakeChannel:
    id = 300
    name = "general"
    mention = "#general"

    def __init__(self):
        self.sent = []

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))
        return SimpleNamespace(id=900)


class FakeAuthor:
    id = 88
    mention = "<@88>"
    bot = False

    def __init__(self, administrator=False, roles=None):
        self.guild_permissions = SimpleNamespace(administrator=administrator)
        self.roles = [SimpleNamespace(id=role_id) for role_id in (roles or [])]


class FakeGuild:
    id = 700
    name = "Orchestrator Guild"
    member_count = 42


class FakeMessage:
    def __init__(self, content, author=None):
        self.content = content
        self.author = author or FakeAuthor()
        self.guild = FakeGuild()
        self.channel = FakeChannel()


class FakeBot:
    def __init__(self):
        self.commands = []
        self.guilds = []
        self.checks = []
        self.user = SimpleNamespace(id=999)

    def add_check(self, check, **kwargs):
        self.checks.append(check)

    def remove_check(self, check):
        self.checks.remove(check)


class UtilitiesOrchestratorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database.DB_NAME = "/tmp/test_utilities_orchestrator.db"
        if os.path.exists(database.DB_NAME):
            os.remove(database.DB_NAME)
        await database.init_db()
        self.bot = FakeBot()
        self.cog = Utilities(self.bot)

    async def asyncTearDown(self):
        await self.cog.cog_unload()

    async def test_dynamic_prefix_reads_shared_settings_cache(self):
        await database.update_guild_settings(700, prefix="?")
        prefixes = await dynamic_prefix(self.bot, FakeMessage("hello"))
        self.assertIn("?", prefixes)
        self.assertNotIn("!", prefixes)

    async def test_command_interceptor_blocks_disabled_and_roleless_commands(self):
        command = SimpleNamespace(qualified_name="secret")
        ctx = SimpleNamespace(
            guild=FakeGuild(),
            command=command,
            author=FakeAuthor(),
        )
        await self.cog.toggle_command(700, "secret", False, [])
        with self.assertRaises(Exception):
            await self.cog.command_interceptor(ctx)

        await self.cog.toggle_command(700, "secret", True, [123])
        with self.assertRaises(Exception):
            await self.cog.command_interceptor(ctx)
        ctx.author = FakeAuthor(roles=[123])
        self.assertTrue(await self.cog.command_interceptor(ctx))

    async def test_exact_contains_regex_variables_and_cooldown(self):
        await self.cog.add_auto_responder(
            700,
            "hello",
            "exact",
            "Hi {user} in {channel} at {server} ({members})",
            cooldown_seconds=60,
        )
        await self.cog.add_auto_responder(
            700,
            r"^price\\s+\\d+$",
            "regex",
            "price",
        )
        await database.save_auto_responder(
            700,
            "keyword",
            "contains",
            "{random:one|two}",
            cooldown_seconds=0,
        )
        await self.cog.sync_auto_responders(700)
        self.assertTrue(
            self.cog._matches(
                {"trigger": "hello", "match_type": "exact"},
                " Hello ",
            )
        )
        self.assertTrue(
            self.cog._matches(
                {
                    "trigger": r"^price\s+\d+$",
                    "match_type": "regex",
                    "_compiled": re.compile(r"^price\s+\d+$", re.I),
                },
                "price 20",
            )
        )
        rendered = self.cog.render_response(
            "Hi {user} {channel} {server} {members} {random:a|b}",
            FakeMessage("hello"),
        )
        self.assertIn("<@88>", rendered)
        self.assertIn("#general", rendered)
        self.assertIn("Orchestrator Guild", rendered)
        self.assertRegex(rendered, r"\b(?:a|b)\b")

        message = FakeMessage("hello")
        await self.cog.on_message(message)
        await self.cog.on_message(message)
        self.assertEqual(len(message.channel.sent), 1)

    async def test_shortcut_announcement_is_cached_and_rendered(self):
        await self.cog.add_shortcut(
            700,
            "rules",
            "announcement",
            announcement="Read the rules in {channel}, {user}.",
        )
        message = FakeMessage("rules")
        await self.cog.on_message(message)
        self.assertEqual(len(message.channel.sent), 1)
        self.assertIn("Read the rules", message.channel.sent[0][1]["embed"].description)


if __name__ == "__main__":
    unittest.main()