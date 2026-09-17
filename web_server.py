import asyncio
import json
import logging
import os
import secrets
import time
from collections import deque
from html import escape
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import aiohttp
import discord
from aiohttp import web

from database import (
    SETTINGS_SCHEMA,
    SettingsConflict,
    get_warning,
    get_guild_settings,
    update_guild_settings,
    validate_setting,
)

routes = web.RouteTableDef()
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
bot_ref: discord.Client = None

C_ID = os.getenv("CLIENT_ID")
C_SEC = os.getenv("CLIENT_SECRET")
R_URI = os.getenv("REDIRECT_URI")
DISCORD_API = "https://discord.com/api/v10"
ADMIN_BIT = 0x8
SESSIONS: dict[str, dict] = {}
STATES: dict[str, float] = {}
STATE_TTL, SESSION_TTL = 300, 604800
# حدود معدل الطلبات: (عدد الطلبات، النافذة بالثواني)
SAVE_LIMIT, READ_LIMIT = (5, 10.0), (60, 10.0)
MAX_BODY = 16 * 1024
GRANT_TTL = 60.0
RATE_BUCKETS: dict[tuple, deque] = {}
GRANT_CACHE: dict[tuple[str, int], tuple[float, bool]] = {}
SETTINGS_LISTENERS: dict[int, set[asyncio.Queue]] = {}
logger = logging.getLogger("DashboardOAuth")


def prune_expired():
    now = time.time()
    for state, created in list(STATES.items()):
        if now - created >= STATE_TTL:
            STATES.pop(state, None)
    for sid, session in list(SESSIONS.items()):
        if now >= session.get("expires_at", 0):
            SESSIONS.pop(sid, None)


def current_session(req):
    prune_expired()
    return SESSIONS.get(req.cookies.get("bot_session"))


@web.middleware
async def private_responses(req, handler):
    try:
        response = await handler(req)
    except web.HTTPException as error:
        response = error
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@routes.get('/login')
async def login(req):
    if not C_ID or not C_SEC or not R_URI:
        return web.Response(
            text="⚠️ يلزم إعداد CLIENT_ID وCLIENT_SECRET وREDIRECT_URI لتسجيل الدخول.",
            status=503,
        )
    prune_expired()
    STATES.pop(req.cookies.get("oauth_state"), None)
    state = secrets.token_urlsafe(32)
    STATES[state] = time.time()
    query = urlencode({
        "client_id": C_ID, "redirect_uri": R_URI,
        "response_type": "code", "scope": "identify guilds",
        "state": state, "prompt": "none",
    })
    response = web.HTTPFound(f"{DISCORD_API}/oauth2/authorize?{query}")
    response.set_cookie(
        "oauth_state", state, max_age=STATE_TTL, httponly=True,
        secure=True, samesite="Lax", path="/",
    )
    return response

@routes.get('/api/auth/callback')
async def callback(req):
    prune_expired()
    code, state = req.query.get("code"), req.query.get("state")
    browser_state = req.cookies.get("oauth_state")
    if (
        not state or not browser_state or state not in STATES
        or not secrets.compare_digest(state, browser_state)
    ):
        return web.Response(text="⛔ فشل التحقق الأمني: انتهاء صلاحية جلسة التسجيل أو محاولة غير مصرح بها.", status=403)
    STATES.pop(state, None)
    if req.query.get("error") or not code:
        return web.Response(text="لم يكتمل تسجيل الدخول عبر ديسكورد.", status=400)
    if not C_ID or not C_SEC or not R_URI:
        return web.Response(text="إعدادات تسجيل الدخول غير مكتملة.", status=503)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as session:
            data = {
                "client_id": C_ID, "client_secret": C_SEC,
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": R_URI,
            }
            async with session.post(f"{DISCORD_API}/oauth2/token", data=data) as response:
                if response.status != 200:
                    return web.Response(text="فشل استخراج توكن المصادقة.", status=400)
                token = (await response.json()).get("access_token")
                if not token:
                    return web.Response(text="استجابة المصادقة غير صالحة.", status=502)
            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{DISCORD_API}/users/@me", headers=headers) as response:
                if response.status != 200:
                    return web.Response(text="تعذر جلب بيانات المستخدم.", status=502)
                user_data = await response.json()
            guild_data, after = [], None
            while True:
                params = {"limit": "200"}
                if after:
                    params["after"] = after
                async with session.get(
                    f"{DISCORD_API}/users/@me/guilds", headers=headers, params=params,
                ) as response:
                    if response.status != 200:
                        return web.Response(text="تعذر جلب السيرفرات.", status=502)
                    page = await response.json()
                if not isinstance(page, list):
                    raise ValueError("Invalid guild list")
                guild_data.extend(page)
                if len(page) < 200:
                    break
                next_after = str(page[-1]["id"])
                if next_after == after:
                    raise ValueError("Invalid pagination")
                after = next_after

        guilds = []
        for guild in guild_data:
            if (int(guild.get("permissions", 0)) & ADMIN_BIT) or guild.get("owner", False):
                if bot_ref and (bg := bot_ref.get_guild(int(guild["id"]))):
                    icon = getattr(bg, "icon", None)
                    guilds.append({
                        "id": str(bg.id), "name": bg.name,
                        "members": bg.member_count,
                        "icon": icon.url if icon else None,
                        "is_owner": guild.get("owner", False),
                    })
        user_session = {
            "id": user_data["id"], "username": user_data["username"],
            "avatar": (
                f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png"
                if user_data.get("avatar")
                else "https://cdn.discordapp.com/embed/avatars/0.png"
            ),
            "guilds": guilds, "expires_at": time.time() + SESSION_TTL,
            "csrf": secrets.token_urlsafe(32),
        }
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
        logger.warning("Discord OAuth request failed or returned invalid data.")
        return web.Response(text="تسجيل الدخول غير متاح مؤقتاً.", status=502)

    SESSIONS.pop(req.cookies.get("bot_session"), None)
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = user_session
    res = web.HTTPFound('/')
    res.del_cookie("oauth_state", path="/")
    res.set_cookie("bot_session", sid, max_age=SESSION_TTL, httponly=True, secure=True, samesite="Lax", path="/")
    return res

@routes.get('/logout')
async def logout(req):
    SESSIONS.pop(req.cookies.get("bot_session"), None)
    STATES.pop(req.cookies.get("oauth_state"), None)
    res = web.HTTPFound('/')
    res.del_cookie("bot_session", path="/")
    res.del_cookie("oauth_state", path="/")
    return res

@routes.get('/api/me')
async def api_me(req):
    session = current_session(req)
    if not session:
        return web.json_response({"auth": False}, status=401)
    return web.json_response({
        "auth": True,
        "session": {key: value for key, value in session.items() if key != "expires_at"},
    })


# -------------------------------------------------------------
# درع الحماية: التفويض لكل سيرفر، CSRF، وحدود المعدل
# -------------------------------------------------------------
def json_error(status: int, error: str, **extra):
    return web.json_response({"error": error, **extra}, status=status)


def rate_limited(key: tuple, limit: tuple[int, float]) -> float:
    """يعيد ثواني الانتظار المتبقية (0 = مسموح). نافذة منزلقة محدودة الحجم."""
    count, window = limit
    now = time.monotonic()
    if len(RATE_BUCKETS) > 5000:
        for stale_key, stale in list(RATE_BUCKETS.items()):
            if not stale or now - stale[-1] > window:
                RATE_BUCKETS.pop(stale_key, None)
    bucket = RATE_BUCKETS.setdefault(key, deque())
    while bucket and now - bucket[0] >= window:
        bucket.popleft()
    if len(bucket) >= count:
        return max(0.0, window - (now - bucket[0]))
    bucket.append(now)
    return 0.0


def same_origin(req) -> bool:
    origin = req.headers.get("Origin") or req.headers.get("Referer")
    if not origin:
        return False
    return urlsplit(origin).netloc.lower() == req.host.lower()


def csrf_ok(req, session) -> bool:
    token = req.headers.get("X-CSRF-Token", "")
    return bool(token) and secrets.compare_digest(token, session.get("csrf", ""))


async def live_grant(session, guild) -> bool:
    """تحقق حي من الصلاحية عبر البوت: المالك أو بت Administrator (0x8)."""
    user_id = str(session["id"])
    cached = GRANT_CACHE.get((user_id, guild.id))
    now = time.monotonic()
    if cached and now - cached[0] < GRANT_TTL:
        return cached[1]
    if len(GRANT_CACHE) > 5000:
        GRANT_CACHE.clear()
    if str(guild.owner_id) == user_id:
        GRANT_CACHE[(user_id, guild.id)] = (now, True)
        return True
    member = guild.get_member(int(user_id))
    if member is None:
        try:
            member = await guild.fetch_member(int(user_id))
        except discord.NotFound:
            member = None
        except (discord.HTTPException, asyncio.TimeoutError):
            raise web.HTTPServiceUnavailable(reason="permission check unavailable")
    allowed = bool(member and (member.guild_permissions.value & ADMIN_BIT))
    GRANT_CACHE[(user_id, guild.id)] = (now, allowed)
    return allowed


async def authorize(req, *, write: bool = False):
    """يعيد (session, guild) أو يرفع HTTPException. لا يُوثق أي شيء من جهة العميل."""
    session = current_session(req)
    if not session:
        raise web.HTTPUnauthorized(text=json.dumps({"error": "unauthorized"}), content_type="application/json")
    raw = req.match_info.get("guild_id", "")
    if not raw.isdigit() or not 15 <= len(raw) <= 22:
        raise web.HTTPNotFound(text=json.dumps({"error": "not_found"}), content_type="application/json")
    if not any(g["id"] == raw for g in session["guilds"]):
        raise web.HTTPForbidden(text=json.dumps({"error": "forbidden"}), content_type="application/json")
    guild = bot_ref.get_guild(int(raw)) if bot_ref else None
    if guild is None:
        raise web.HTTPNotFound(text=json.dumps({"error": "not_found"}), content_type="application/json")
    if not await live_grant(session, guild):
        session["guilds"] = [g for g in session["guilds"] if g["id"] != raw]
        raise web.HTTPForbidden(text=json.dumps({"error": "forbidden"}), content_type="application/json")
    if write and (not same_origin(req) or not csrf_ok(req, session)):
        raise web.HTTPForbidden(text=json.dumps({"error": "csrf"}), content_type="application/json")
    limit_key = ("save" if write else "read", session["id"], guild.id)
    wait = rate_limited(limit_key, SAVE_LIMIT if write else READ_LIMIT)
    if wait:
        raise web.HTTPTooManyRequests(
            text=json.dumps({"error": "rate_limited", "retry_after": int(wait) + 1}),
            content_type="application/json", headers={"Retry-After": str(int(wait) + 1)},
        )
    return session, guild


def public_settings(snapshot: dict) -> dict:
    settings = {
        key: (str(value) if SETTINGS_SCHEMA[key][2] == "id" and value is not None else value)
        for key, value in snapshot["settings"].items()
    }
    return {"revision": snapshot["revision"], "updated_at": snapshot["updated_at"], "settings": settings}


def guild_meta(guild) -> dict:
    icon = getattr(guild, "icon", None)
    me = guild.me
    top = me.top_role if me else None
    channels = [
        {"id": str(c.id), "name": c.name, "category": c.category.name if c.category else None}
        for c in sorted(guild.text_channels, key=lambda c: (c.category.position if c.category else -1, c.position))
    ]
    roles = []
    for role in sorted(guild.roles, key=lambda r: -r.position):
        if role.is_default():
            continue
        roles.append({
            "id": str(role.id), "name": role.name,
            "color": f"#{role.color.value:06x}" if role.color.value else None,
            "assignable": bool(top and role < top and not role.managed),
        })
    return {
        "guild": {"id": str(guild.id), "name": guild.name, "icon": icon.url if icon else None,
                  "members": guild.member_count},
        "channels": channels, "roles": roles,
    }


def validate_changes(guild, changes: dict) -> tuple[dict, dict]:
    """تنقية المدخلات: مفاتيح مسموحة فقط، أنواع/حدود صحيحة، وقنوات/رتب تخص هذا السيرفر."""
    clean, errors = {}, {}
    if not isinstance(changes, dict) or len(changes) > len(SETTINGS_SCHEMA):
        return {}, {"_": "صيغة التعديلات غير صالحة"}
    for key, value in changes.items():
        if key not in SETTINGS_SCHEMA:
            errors[str(key)[:40]] = "حقل غير مسموح"
            continue
        try:
            value = validate_setting(key, value)
        except ValueError as error:
            errors[key] = str(error)
            continue
        if value is not None and key.endswith("_channel_id"):
            channel = guild.get_channel(value)
            if not isinstance(channel, discord.TextChannel):
                errors[key] = "القناة غير موجودة في هذا السيرفر"
                continue
        if value is not None and key.endswith("_role_id"):
            role = guild.get_role(value)
            me = guild.me
            if role is None or role.is_default():
                errors[key] = "الرتبة غير موجودة في هذا السيرفر"
                continue
            if role.managed or not me or role >= me.top_role:
                errors[key] = "لا يمكن للبوت منح هذه الرتبة (أعلى من رتبته أو مُدارة)"
                continue
        clean[key] = value
    return clean, errors


def broadcast(guild_id: int, payload: dict) -> None:
    for queue in list(SETTINGS_LISTENERS.get(guild_id, ())):
        if queue.full():
            continue
        queue.put_nowait(payload)


@routes.get('/api/health')
async def api_health(req):
    if not current_session(req):
        return json_error(401, "unauthorized")
    return web.json_response({"ok": True, "online": bool(bot_ref and bot_ref.is_ready())})


@routes.get('/api/guild/{guild_id}/meta')
async def api_guild_meta(req):
    _, guild = await authorize(req)
    return web.json_response(guild_meta(guild))


@routes.get('/api/guild/{guild_id}/security/incidents')
async def api_security_incidents(req):
    _, guild = await authorize(req)
    security = bot_ref.get_cog("Security") if bot_ref else None
    if security is None:
        return json_error(503, "security_unavailable")
    return web.json_response({
        "guild_id": str(guild.id),
        "incidents": security.get_incidents(guild.id),
        "whitelist": security.get_whitelist(guild.id),
        "locked": security.is_locked(guild.id),
    })


@routes.post('/api/guild/{guild_id}/security/lockdown')
async def api_security_lockdown(req):
    session, guild = await authorize(req, write=True)
    security = bot_ref.get_cog("Security") if bot_ref else None
    if security is None:
        return json_error(503, "security_unavailable")
    try:
        body = json.loads((await req.content.read(MAX_BODY + 1))[:MAX_BODY].decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    locked = body.get("locked", True)
    if not isinstance(locked, bool):
        return json_error(400, "validation", fields={"locked": "القيمة يجب أن تكون تشغيل/إيقاف"})
    result = await security.emergency_lockdown(guild.id, locked)
    mitigation = (
        f"{'queued_lockdown' if locked else 'queued_unlock'}:{result['channels']}"
        if result["queued"]
        else "queue_rejected"
    )
    security.record_control_action(
        guild.id,
        int(session["id"]),
        session.get("username", session["id"]),
        "dashboard_lockdown" if locked else "dashboard_unlock",
        mitigation,
    )
    return web.json_response({"ok": result["queued"], **result})


@routes.post('/api/guild/{guild_id}/security/whitelist')
async def api_security_whitelist(req):
    session, guild = await authorize(req, write=True)
    security = bot_ref.get_cog("Security") if bot_ref else None
    if security is None:
        return json_error(503, "security_unavailable")
    try:
        body = json.loads((await req.content.read(MAX_BODY + 1))[:MAX_BODY].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    action = body.get("action")
    user_id = body.get("user_id")
    if action not in {"add", "remove"}:
        return json_error(400, "validation", fields={"action": "الإجراء يجب أن يكون add أو remove"})
    if isinstance(user_id, bool) or not str(user_id).isdigit() or not 15 <= len(str(user_id)) <= 22:
        return json_error(400, "validation", fields={"user_id": "معرّف Discord غير صالح"})
    user_id = int(user_id)
    member = guild.get_member(user_id)
    if member is None:
        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            return json_error(404, "member_not_found")
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
            return json_error(503, "member_lookup_unavailable")
    if action == "add" and not member.guild_permissions.administrator:
        return json_error(400, "validation", fields={"user_id": "يجب أن يملك العضو صلاحية Administrator"})
    if action == "add":
        security.whitelist_member(guild.id, user_id)
    else:
        security.remove_whitelisted_member(guild.id, user_id)
    security.record_control_action(
        guild.id,
        int(session["id"]),
        session.get("username", session["id"]),
        f"dashboard_whitelist_{action}",
        f"user:{user_id}",
    )
    return web.json_response({
        "ok": True,
        "action": action,
        "user_id": str(user_id),
        "whitelist": security.get_whitelist(guild.id),
    })


@routes.get('/api/guild/{guild_id}/moderation/infractions')
async def api_moderation_infractions(req):
    _, guild = await authorize(req)
    moderation = bot_ref.get_cog("Moderation") if bot_ref else None
    if moderation is None:
        return json_error(503, "moderation_unavailable")
    return web.json_response({
        "guild_id": str(guild.id),
        "infractions": await moderation.get_recent_infractions(guild.id),
    })


@routes.post('/api/guild/{guild_id}/moderation/warnings/{warning_id}/revoke')
async def api_revoke_warning(req):
    session, guild = await authorize(req, write=True)
    moderation = bot_ref.get_cog("Moderation") if bot_ref else None
    if moderation is None:
        return json_error(503, "moderation_unavailable")
    raw_warning_id = req.match_info.get("warning_id", "")
    if not raw_warning_id.isdigit() or int(raw_warning_id) <= 0:
        return json_error(400, "validation", fields={"warning_id": "معرف إنذار غير صالح"})
    warning = await get_warning(int(raw_warning_id))
    if not warning or int(warning["guild_id"]) != guild.id:
        return json_error(404, "warning_not_found")
    revoked = await moderation.revoke_warning(int(raw_warning_id))
    if revoked is None:
        return json_error(404, "warning_not_found")
    logger.info(
        "Warning %s revoked in guild %s by user %s",
        raw_warning_id,
        guild.id,
        session["id"],
    )
    return web.json_response({"ok": True, "warning": revoked})


@routes.post('/api/guild/{guild_id}/moderation/{user_id}/unmute')
async def api_quick_unmute(req):
    session, guild = await authorize(req, write=True)
    moderation = bot_ref.get_cog("Moderation") if bot_ref else None
    if moderation is None:
        return json_error(503, "moderation_unavailable")
    raw_user_id = req.match_info.get("user_id", "")
    if not raw_user_id.isdigit() or not 15 <= len(raw_user_id) <= 22:
        return json_error(400, "validation", fields={"user_id": "معرف Discord غير صالح"})
    result = await moderation.quick_unmute(guild.id, int(raw_user_id))
    if not result.get("ok"):
        return json_error(
            404 if result.get("error") in {"guild_not_found", "member_not_found"} else 403,
            result.get("error", "unmute_failed"),
        )
    logger.info(
        "User %s unmuted in guild %s by user %s",
        raw_user_id,
        guild.id,
        session["id"],
    )
    return web.json_response(result)


@routes.get('/api/guild/{guild_id}/settings')
async def api_get_settings(req):
    _, guild = await authorize(req)
    return web.json_response(public_settings(await get_guild_settings(guild.id)))


@routes.post('/api/guild/{guild_id}/settings')
async def api_post_settings(req):
    session, guild = await authorize(req, write=True)
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    if not req.content_type.startswith("application/json"):
        return json_error(415, "json_required")
    try:
        body = json.loads((await req.content.read(MAX_BODY + 1))[:MAX_BODY].decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict) or not isinstance(body.get("revision"), int) or isinstance(body.get("revision"), bool):
        return json_error(400, "validation", fields={"_": "رقم الإصدار مطلوب"})
    clean, errors = validate_changes(guild, body.get("changes", {}))
    if errors:
        return json_error(400, "validation", fields=errors)
    if not clean:
        return web.json_response({"ok": True, **public_settings(await get_guild_settings(guild.id))})
    try:
        snapshot = await update_guild_settings(guild.id, expected_revision=body["revision"], **clean)
    except SettingsConflict as conflict:
        return json_error(409, "conflict", **public_settings(conflict.current))
    result = public_settings(snapshot)
    broadcast(guild.id, {"type": "settings", "by": str(session["id"]), **result})
    logger.info("Settings updated for guild %s by user %s: %s", guild.id, session["id"], sorted(clean))
    return web.json_response({"ok": True, **result})


@routes.get('/api/guild/{guild_id}/events')
async def api_guild_events(req):
    session, guild = await authorize(req)
    guild_id = guild.id
    response = web.StreamResponse(headers={
        "Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Accel-Buffering": "no",
    })
    await response.prepare(req)
    queue: asyncio.Queue = asyncio.Queue(maxsize=32)
    listeners = SETTINGS_LISTENERS.setdefault(guild_id, set())
    if len(listeners) >= 200:
        await response.write(b"event: error\ndata: {\"error\":\"too_many_streams\"}\n\n")
        return response

    async def send(event: str, data: dict):
        await response.write(f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8"))

    def ping_payload():
        online = bool(bot_ref and bot_ref.is_ready())
        latency = bot_ref.latency if bot_ref else None
        latency_ms = round(latency * 1000) if online and latency == latency and latency != float("inf") else None
        return {"online": online, "latency_ms": latency_ms, "ts": time.time()}

    listeners.add(queue)
    try:
        await send("ping", ping_payload())
        while True:
            # إعادة التحقق دورياً (بحد أقصى كل 15 ثانية): الجلسة، بقاء البوت في السيرفر، والصلاحية الحية
            live = current_session(req)
            guild = bot_ref.get_guild(guild_id) if bot_ref else None
            if not live or guild is None:
                await send("expired", {})
                break
            try:
                allowed = any(g["id"] == str(guild.id) for g in live["guilds"]) and await live_grant(live, guild)
            except web.HTTPServiceUnavailable:
                allowed = True  # تعذر التحقق مؤقتاً؛ تبقى النتيجة المخبأة سارية حتى المحاولة التالية
            if not allowed:
                live["guilds"] = [g for g in live["guilds"] if g["id"] != str(guild.id)]
                await send("expired", {"reason": "forbidden"})
                break
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=15)
                await send(payload.get("type", "message"), payload)
            except asyncio.TimeoutError:
                await send("ping", ping_payload())
    except (ConnectionResetError, asyncio.CancelledError, aiohttp.ClientConnectionError):
        pass
    finally:
        listeners.discard(queue)
        if not listeners:
            SETTINGS_LISTENERS.pop(guild_id, None)
    return response


@routes.get('/static/{name}')
async def static_asset(req):
    name = req.match_info["name"]
    types = {"app.css": "text/css", "app.js": "application/javascript"}
    if name not in types:
        raise web.HTTPNotFound()
    return web.Response(text=(DASHBOARD_DIR / name).read_text("utf-8"), content_type=types[name], charset="utf-8")


@routes.get('/')
async def index(req):
    sess = current_session(req)

    # شاشة الدخول الاحترافية بالعربية
    if not sess:
        html = """
        <!DOCTYPE html>
        <html dir="rtl" lang="ar">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>بوابة الإدارة والتحكم السحابية | تسجيل الدخول</title>
            <style>
                * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
                body { background: #000000; color: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 1rem; }
                .auth-card { background: #0a0e17; border: 1px solid #1e293b; border-radius: 18px; padding: 2.2rem; max-width: 440px; width: 100%; text-align: center; box-shadow: 0 10px 30px rgba(0,0,0,0.7); }
                .badge { display: inline-flex; align-items: center; gap: 6px; background: rgba(59,130,246,0.1); color: #60a5fa; padding: 5px 14px; border-radius: 30px; font-size: 0.8rem; font-weight: bold; border: 1px solid rgba(59,130,246,0.2); }
                h2 { margin: 1.2rem 0 0.5rem; font-size: 1.5rem; }
                p { color: #94a3b8; font-size: 0.9rem; line-height: 1.6; margin-bottom: 1.8rem; }
                .btn-login { background: #5865F2; color: #fff; text-decoration: none; display: flex; align-items: center; justify-content: center; gap: 12px; padding: 0.9rem 1.4rem; border-radius: 12px; font-weight: bold; font-size: 1rem; transition: 0.2s; box-shadow: 0 4px 15px rgba(88,101,242,0.3); }
                .btn-login:hover { background: #4752c4; }
                .features { display: flex; justify-content: space-around; margin-top: 1.8rem; padding-top: 1.5rem; border-top: 1px solid #1e293b; color: #64748b; font-size: 0.78rem; }
            </style>
        </head>
        <body>
            <div class="auth-card">
                <span class="badge">⚡ نظام التوثيق السحابي الموحد</span>
                <h2>لوحة القيادة المركزية</h2>
                <p>الدخول مخصص لإدارة السيرفرات الرسمية. يتم فحص الهوية والتحقق من صلاحية الإدارة (Administrator) تلقائياً عبر ديسكورد.</p>
                <a href="login" class="btn-login">
                    <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor"><path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994.021-.041.001-.09-.041-.106a13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.929 1.793 8.18 1.793 12.061 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.893.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.028zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/></svg>
                    تسجيل الدخول عبر ديسكورد
                </a>
                <div class="features">
                    <span>🔒 تشفير فوري</span>
                    <span>⚡ بدون كلمات مرور</span>
                    <span>🛡️ فحص الرتب التلقائي</span>
                </div>
            </div>
        </body>
        </html>
        """
        return web.Response(text=html, content_type='text/html')

    # لوحة التحكم التفاعلية (HTML/CSS/JS في مجلد dashboard/)
    page = (DASHBOARD_DIR / "index.html").read_text("utf-8")
    return web.Response(text=page, content_type="text/html", charset="utf-8")


async def start_web_server(bot):
    global bot_ref
    bot_ref = bot
    app = web.Application(middlewares=[private_responses], client_max_size=MAX_BODY)
    app.add_routes(routes)
    # Access logs include callback query strings; do not log authorization codes.
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    try:
        port = int(os.getenv("DASHBOARD_PORT", "8099"))
        await web.TCPSite(runner, '0.0.0.0', port).start()
    except Exception:
        await runner.cleanup()
        raise
    return runner
