import json
import os
import time
import unittest
from unittest.mock import Mock

from aiohttp.streams import StreamReader
from aiohttp.test_utils import make_mocked_request

import database
import web_server as ws
from tests.dashboard_harness import CHANNELS, ROLES, FakeBot, FakeGuild

GID = str(FakeGuild.id)


class TicketCommunityStub:
    def __init__(self):
        self.ticket = {
            "id": 42,
            "guild_id": FakeGuild.id,
            "channel_id": 300000000000000002,
            "subject": "مشكلة في الشحن",
            "category_label": "دعم الشحن",
            "priority": "high",
            "claimed_by": None,
            "status": "active",
        }
        self.responses = []
        self.calls = []

    async def get_active_tickets(self, guild_id):
        self.calls.append(("active", guild_id))
        return [dict(self.ticket)]

    async def get_ticket_archive(self, guild_id, query=""):
        self.calls.append(("archive", guild_id, query))
        return [{
            "id": 7,
            "guild_id": guild_id,
            "subject": "تذكرة مغلقة",
            "category_label": "عام",
            "close_reason": "تم الحل",
        }]

    async def get_ticket_transcript(self, guild_id, ticket_id):
        self.calls.append(("transcript", guild_id, ticket_id))
        return {
            "ticket_id": ticket_id,
            "content_html": "<!doctype html><html><body><p>Transcript</p></body></html>",
        }

    async def get_staff_kpis(self, guild_id):
        self.calls.append(("kpis", guild_id))
        return [{"staff_id": "10", "tickets_handled": 2, "avg_rating": 5.0}]

    async def get_canned_responses(self, guild_id):
        self.calls.append(("canned", guild_id))
        return list(self.responses)

    async def save_canned_response(
        self,
        guild_id,
        title,
        content,
        category,
        created_by,
        response_id=None,
        shortcut=None,
        sticker_id=None,
    ):
        item = {
            "id": response_id or 1,
            "guild_id": guild_id,
            "title": title,
            "content": content,
            "category": category,
            "shortcut": shortcut,
            "sticker_id": sticker_id,
            "created_by": created_by,
        }
        self.responses = [item]
        self.calls.append(("save_canned", guild_id, response_id))
        return item

    async def delete_canned_response(self, guild_id, response_id):
        self.calls.append(("delete_canned", guild_id, response_id))
        self.responses = []
        return True

    async def reassign_ticket(self, guild_id, ticket_id, staff_id):
        self.calls.append(("reassign", guild_id, ticket_id, staff_id))
        return {**self.ticket, "claimed_by": staff_id}

    async def force_close_ticket(self, guild_id, ticket_id, staff_id, reason):
        self.calls.append(("close", guild_id, ticket_id, staff_id, reason))
        return {**self.ticket, "status": "closed", "closed_by": staff_id}


def request(method, path, sid=None, body=None, headers=None):
    h = {"Host": "dash.test", **(headers or {})}
    if sid:
        h["Cookie"] = f"bot_session={sid}"
    payload = json.dumps(body).encode() if body is not None else None
    if payload is not None:
        h.update({"Content-Type": "application/json", "Content-Length": str(len(payload))})
    req = make_mocked_request(method, path, headers=h)
    req.match_info["guild_id"] = GID
    if payload is not None:
        reader = StreamReader(Mock(), 2**16)
        reader.feed_data(payload)
        reader.feed_eof()
        req._payload = reader
    return req


async def call(handler, req):
    try:
        response = await handler(req)
    except ws.web.HTTPException as error:
        response = error
    return response.status, json.loads(response.text)


class SettingsApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        database.DB_NAME = "/tmp/test_settings_api.db"
        if os.path.exists(database.DB_NAME):
            os.remove(database.DB_NAME)
        await database.init_db()
        ws.bot_ref = FakeBot()
        ws.SESSIONS.clear(), ws.RATE_BUCKETS.clear(), ws.GRANT_CACHE.clear()
        self.community = TicketCommunityStub()
        self._community_cog = ws._community_cog
        ws._community_cog = lambda: self.community
        for uid in (10, 11):
            ws.SESSIONS[f"s{uid}"] = {
                "id": str(uid), "username": "u", "avatar": "", "csrf": f"csrf{uid}",
                "guilds": [{"id": GID}], "expires_at": time.time() + 60,
            }
        self.headers = {"X-CSRF-Token": "csrf10", "Origin": "https://dash.test"}

    async def asyncTearDown(self):
        ws._community_cog = self._community_cog

    async def test_authorization_is_enforced_server_side(self):
        self.assertEqual((await call(ws.api_get_settings, request("GET", "/x")))[0], 401)
        # user 11 is in the session guild list but lacks the 0x8 bit on the live guild
        self.assertEqual((await call(ws.api_get_settings, request("GET", "/x", "s11")))[0], 403)
        self.assertEqual(ws.SESSIONS["s11"]["guilds"], [])
        status, data = await call(ws.api_get_settings, request("GET", "/x", "s10"))
        self.assertEqual((status, data["revision"], data["settings"]["prefix"]), (200, 0, "!"))

    async def test_write_requires_csrf_and_same_origin(self):
        body = {"revision": 0, "changes": {"prefix": "?"}}
        bad_token = {**self.headers, "X-CSRF-Token": "nope"}
        self.assertEqual((await call(ws.api_post_settings, request("POST", "/x", "s10", body, bad_token)))[0], 403)
        cross = {**self.headers, "Origin": "https://evil.test"}
        self.assertEqual((await call(ws.api_post_settings, request("POST", "/x", "s10", body, cross)))[0], 403)

    async def test_validation_save_conflict_and_rate_limit(self):
        managed_role, high_role = ROLES[5], ROLES[4]
        bad = {"revision": 0, "changes": {
            "prefix": "a b", "anti_alt_days": 999, "auto_role_id": str(high_role.id),
            "captcha_role_id": str(managed_role.id), "welcome_channel_id": "300000000000000099", "hack": 1,
        }}
        status, data = await call(ws.api_post_settings, request("POST", "/x", "s10", bad, self.headers))
        self.assertEqual(status, 400)
        self.assertEqual(set(data["fields"]), set(bad["changes"]))

        good = {"revision": 0, "changes": {
            "prefix": "?", "captcha_role_id": str(ROLES[2].id), "welcome_channel_id": str(CHANNELS[0].id),
            "welcome_message": "<b>{user}</b>", "economy_tax": 2.5,
        }}
        status, data = await call(ws.api_post_settings, request("POST", "/x", "s10", good, self.headers))
        self.assertEqual((status, data["revision"], data["settings"]["captcha_role_id"]), (200, 1, str(ROLES[2].id)))
        self.assertEqual(data["settings"]["welcome_message"], "<b>{user}</b>")  # stored raw, rendered as text

        stale = {"revision": 0, "changes": {"prefix": "$"}}
        status, data = await call(ws.api_post_settings, request("POST", "/x", "s10", stale, self.headers))
        self.assertEqual((status, data["error"], data["settings"]["prefix"]), (409, "conflict", "?"))

        # three attempts are already counted above (400, 200, 409); the 5/10s save limit trips soon after
        statuses, revision = [], 1
        for amount in range(500, 506):
            body = {"revision": revision, "changes": {"daily_amount": amount}}
            status, data = await call(ws.api_post_settings, request("POST", "/x", "s10", body, self.headers))
            statuses.append(status)
            revision = data.get("revision", revision)
        self.assertEqual(statuses[:2], [200, 200])
        self.assertEqual(statuses[2:], [429] * 4)
        self.assertEqual((await database.get_guild_settings(FakeGuild.id))["settings"]["daily_amount"], 501)

    async def test_meta_marks_roles_the_bot_cannot_assign(self):
        status, meta = await call(ws.api_guild_meta, request("GET", "/x", "s10"))
        assignable = {r["name"]: r["assignable"] for r in meta["roles"]}
        self.assertEqual(status, 200)
        self.assertNotIn("@everyone", assignable)
        self.assertEqual((assignable["مدير"], assignable["Nitro Booster"], assignable["قيد التحقق"]), (False, False, True))

    async def test_commands_and_auto_responses_api(self):
        status, data = await call(ws.api_guild_commands, request("GET", "/x", "s10"))
        self.assertEqual(status, 200)
        self.assertEqual(data["commands"][0]["command_name"], "ping")
        self.assertEqual(data["commands"][0]["enabled"], True)

        body = {
            "command_name": "ping",
            "enabled": False,
            "allowed_roles": [str(ROLES[2].id)],
        }
        status, data = await call(
            ws.api_guild_commands_toggle,
            request("POST", "/x", "s10", body, self.headers),
        )
        self.assertEqual((status, data["command"]["enabled"]), (200, False))
        status, data = await call(ws.api_guild_commands, request("GET", "/x", "s10"))
        command = next(item for item in data["commands"] if item["command_name"] == "ping")
        self.assertEqual((command["enabled"], command["allowed_roles"]), (False, [str(ROLES[2].id)]))

        rule_body = {
            "trigger": "hello",
            "match_type": "contains",
            "response": "Hi {user}",
            "cooldown_seconds": 10,
            "channel_id": str(CHANNELS[1].id),
        }
        status, data = await call(
            ws.api_guild_auto_responses_save,
            request("POST", "/x", "s10", rule_body, self.headers),
        )
        self.assertEqual(status, 200)
        rule_id = data["rule"]["id"]
        self.assertEqual(data["rule"]["channel_id"], str(CHANNELS[1].id))
        status, data = await call(ws.api_guild_auto_responses, request("GET", "/x", "s10"))
        self.assertEqual((status, len(data["rules"])), (200, 1))
        delete_req = request("DELETE", "/x", "s10", headers=self.headers)
        delete_req.match_info["rule_id"] = str(rule_id)
        status, data = await call(
            ws.api_guild_auto_responses_delete,
            delete_req,
        )
        self.assertEqual((status, data["deleted"]), (200, True))

    async def test_ticket_studio_read_and_write_contracts(self):
        status, data = await call(ws.api_guild_tickets_active, request("GET", "/x", "s10"))
        self.assertEqual((status, data["tickets"][0]["id"]), (200, 42))

        status, data = await call(
            ws.api_guild_tickets_archive,
            request("GET", "/x?q=shipping", "s10"),
        )
        self.assertEqual((status, data["query"], data["tickets"][0]["id"]), (200, "shipping", 7))

        status, data = await call(ws.api_guild_tickets_kpis, request("GET", "/x", "s10"))
        self.assertEqual((status, data["kpis"][0]["avg_rating"]), (200, 5.0))

        status, data = await call(ws.api_guild_tickets_canned_get, request("GET", "/x", "s10"))
        self.assertEqual((status, data["responses"]), (200, []))

        body = {
            "title": "سياسة الاسترداد",
            "content": "سنراجع طلبك.",
            "category": "billing",
            "shortcut": "refund",
            "sticker_id": None,
        }
        status, data = await call(
            ws.api_guild_tickets_canned,
            request("POST", "/x", "s10", body, self.headers),
        )
        self.assertEqual(
            (status, data["response"]["title"], data["response"]["shortcut"], data["response"]["sticker_id"]),
            (200, "سياسة الاسترداد", "refund", None),
        )

        status, data = await call(
            ws.api_guild_tickets_action,
            request(
                "POST",
                "/x",
                "s10",
                {"ticket_id": 42, "action": "reassign", "staff_id": 10},
                self.headers,
            ),
        )
        self.assertEqual((status, data["ticket"]["claimed_by"]), (200, 10))

        transcript_request = request("GET", "/x", "s10")
        transcript_request.match_info["ticket_id"] = "42"
        transcript = await ws.api_guild_ticket_transcript(transcript_request)
        self.assertEqual((transcript.status, transcript.content_type), (200, "text/html"))
        self.assertIn("Transcript", transcript.text)
        self.assertEqual(
            transcript.headers["Cache-Control"],
            "no-store",
        )

        status, data = await call(
            ws.api_guild_tickets_canned,
            request(
                "POST",
                "/x",
                "s10",
                {"action": "delete", "id": 1},
                self.headers,
            ),
        )
        self.assertEqual((status, data["deleted"]), (200, True))
        self.assertIn(("reassign", FakeGuild.id, 42, 10), self.community.calls)


if __name__ == "__main__":
    unittest.main()
