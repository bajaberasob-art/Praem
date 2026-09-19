import asyncio
import json
import logging
import os
import re
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
    get_auto_responders,
    get_shortcuts,
    get_warning,
    get_recent_warnings,
    get_dashboard_stats,
    get_guild_settings,
    delete_shortcut,
    save_shortcut,
    update_guild_settings,
    validate_setting,
)

routes = web.RouteTableDef()
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
bot_ref: discord.Client = None

C_ID = os.getenv("CLIENT_ID")
C_SEC = os.getenv("CLIENT_SECRET")
R_URI = os.getenv("REDIRECT_URI")
DASHBOARD_BASE_PATH = os.getenv("DASHBOARD_BASE_PATH", "/").rstrip("/") + "/"
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
        logger.info("Stale or invalid dashboard OAuth state; starting a fresh login.")
        login_url = f"{DASHBOARD_BASE_PATH}login"
        return web.Response(
            text=(
                "<!doctype html><meta charset='utf-8'>"
                f"<meta http-equiv='refresh' content='0;url={login_url}'>"
                f"<p>انتهت جلسة تسجيل الدخول. <a href='{login_url}'>إعادة تسجيل الدخول</a></p>"
            ),
            status=403,
            content_type="text/html",
            headers={"Refresh": f"0; url={login_url}"},
        )
    STATES.pop(state, None)
    if req.query.get("error") or not code:
        return web.Response(text="لم يكتمل تسجيل الدخول عبر ديسكورد.", status=400)
    if not C_ID or not C_SEC or not R_URI:
        return web.Response(text="إعدادات تسجيل الدخول غير مكتملة.", status=503)
    try:
        session = getattr(bot_ref, "session", None)
        owns_session = session is None
        if owns_session:
            session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        if getattr(session, "closed", False):
            return web.Response(text="خدمة الاتصال غير جاهزة.", status=503)
        data = {
            "client_id": C_ID, "client_secret": C_SEC,
            "grant_type": "authorization_code", "code": code,
            "redirect_uri": R_URI,
        }
        async with session.post(f"{DISCORD_API}/oauth2/token", data=data) as response:
            if response.status != 200:
                logger.warning(
                    "Discord OAuth token exchange rejected with status=%s",
                    response.status,
                )
                return web.Response(
                    text=(
                        "فشل تسجيل الدخول عبر Discord. تحقق من أن CLIENT_SECRET هو "
                        "Client Secret الموجود في OAuth2 → General، وليس Bot Token "
                        "أو Public Key، وأن Redirect URI مطابق تماماً."
                    ),
                    status=400,
                )
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
        if owns_session:
            close = getattr(session, "close", None)
            if close:
                await close()

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
    res = web.HTTPFound(DASHBOARD_BASE_PATH)
    res.del_cookie("oauth_state", path="/")
    res.set_cookie("bot_session", sid, max_age=SESSION_TTL, httponly=True, secure=True, samesite="Lax", path="/")
    return res

@routes.get('/logout')
async def logout(req):
    SESSIONS.pop(req.cookies.get("bot_session"), None)
    STATES.pop(req.cookies.get("oauth_state"), None)
    res = web.HTTPFound(DASHBOARD_BASE_PATH)
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


async def read_json_body(req) -> dict:
    """Read a bounded JSON object for action endpoints."""
    if req.content_length and req.content_length > MAX_BODY:
        raise web.HTTPRequestEntityTooLarge(max_size=MAX_BODY, actual_size=req.content_length)
    if not req.content_type.startswith("application/json"):
        raise web.HTTPUnsupportedMediaType()
    try:
        body = json.loads((await req.content.read(MAX_BODY + 1))[:MAX_BODY].decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        raise web.HTTPBadRequest(text=json.dumps({"error": "invalid_json"}), content_type="application/json") from error
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(text=json.dumps({"error": "validation"}), content_type="application/json")
    return body


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
    origin_host = urlsplit(origin).netloc.lower()
    expected_hosts = {req.host.lower()}
    # The dashboard is served through Replit's path proxy. In that path,
    # aiohttp can see the internal host while the browser sends the public
    # forwarded host in Origin/Referer.
    forwarded = req.headers.get("X-Forwarded-Host", "")
    expected_hosts.update(
        item.strip().lower().split(",", 1)[0]
        for item in forwarded.split(",")
        if item.strip()
    )
    return origin_host in expected_hosts


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


def parse_custom_emoji(value: str):
    match = re.fullmatch(r"<(a?):([A-Za-z0-9_~]+):(\d+)>", str(value or "").strip())
    if not match:
        return None
    return discord.PartialEmoji(
        name=match.group(2),
        id=int(match.group(3)),
        animated=bool(match.group(1)),
    )


async def guild_meta(guild) -> dict:
    if not getattr(guild, "chunked", True):
        try:
            await guild.chunk()
        except (discord.Forbidden, discord.HTTPException, asyncio.TimeoutError):
            logger.warning("[META] Unable to chunk guild %s", guild.id, exc_info=True)
    icon = getattr(guild, "icon", None)
    me = guild.me
    top = me.top_role if me else None
    text_channels = list(guild.text_channels)
    fetch_channels = getattr(guild, "fetch_channels", None)
    if fetch_channels is not None:
        try:
            fetched_channels = await fetch_channels()
            fetched_text = [
                channel for channel in fetched_channels
                if isinstance(channel, discord.TextChannel)
            ]
            if fetched_text:
                text_channels = fetched_text
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to refresh channel list for guild %s", guild.id, exc_info=True)
    channels = []
    for channel in sorted(
        text_channels,
        key=lambda c: (c.category.position if c.category else -1, c.position),
    ):
        try:
            channel_type = str(channel.type)
        except (AttributeError, TypeError):
            # Lightweight test doubles may inherit TextChannel without its
            # internal _type field; real Discord channels always expose type.
            channel_type = "text"
        channels.append({
            "id": str(channel.id),
            "name": channel.name,
            "type": channel_type,
            "category": channel.category.name if channel.category else None,
        })
    roles = []
    for role in reversed(guild.roles):
        if role.is_default():
            continue
        roles.append({
            "id": str(role.id), "name": role.name,
            "color": str(role.color),
            "assignable": bool(top and role < top and not role.managed),
        })
    stickers = list(getattr(guild, "stickers", ()) or ())
    fetch_stickers = getattr(guild, "fetch_stickers", None)
    if fetch_stickers is not None:
        try:
            fetched_stickers = await fetch_stickers()
            if fetched_stickers:
                stickers = list(fetched_stickers)
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to refresh stickers for guild %s", guild.id, exc_info=True)
    emojis = list(getattr(guild, "emojis", ()) or ())
    fetch_emojis = getattr(guild, "fetch_emojis", None)
    if fetch_emojis is not None:
        try:
            fetched_emojis = await fetch_emojis()
            if fetched_emojis:
                emojis = list(fetched_emojis)
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to refresh emojis for guild %s", guild.id, exc_info=True)
    members = [
        {
            "id": str(member.id),
            "name": member.display_name,
            "avatar": str(getattr(getattr(member, "display_avatar", None), "url", "")),
        }
        for member in getattr(guild, "members", ())
        if not getattr(member, "bot", False)
    ]
    serialized_emojis = [
        {
            "id": str(emoji.id),
            "name": emoji.name,
            "url": str(emoji.url),
            "animated": bool(getattr(emoji, "animated", False)),
            "token": str(emoji),
        }
        for emoji in emojis
        if getattr(emoji, "available", True)
    ]
    logger.info(
        "[META] Guild: %s | Members: %d | Roles: %d | Emojis: %d",
        guild.name,
        len(members),
        len(roles),
        len(serialized_emojis),
    )
    return {
        "guild": {"id": str(guild.id), "name": guild.name, "icon": icon.url if icon else None,
                  "members": guild.member_count},
        "channels": channels,
        "roles": roles,
        "members": members,
        "stickers": [
            {"id": str(sticker.id), "name": sticker.name, "url": str(sticker.url)}
            for sticker in stickers
            if getattr(sticker, "available", True)
        ],
        "emojis": serialized_emojis,
    }


async def resolve_text_channel(guild, channel_id: int):
    channel = guild.get_channel(int(channel_id))
    if isinstance(channel, discord.TextChannel):
        return channel
    fetch_channels = getattr(guild, "fetch_channels", None)
    if fetch_channels is not None:
        try:
            for fetched in await fetch_channels():
                if fetched.id == int(channel_id) and isinstance(fetched, discord.TextChannel):
                    return fetched
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to fetch channel %s in guild %s", channel_id, guild.id, exc_info=True)
    return None


async def resolve_guild_sticker(guild, sticker_id: int):
    for sticker in getattr(guild, "stickers", ()) or ():
        if sticker.id == int(sticker_id):
            return sticker
    fetch_stickers = getattr(guild, "fetch_stickers", None)
    if fetch_stickers is not None:
        try:
            for sticker in await fetch_stickers():
                if sticker.id == int(sticker_id):
                    return sticker
        except (discord.Forbidden, discord.HTTPException):
            logger.debug("Unable to fetch sticker %s in guild %s", sticker_id, guild.id, exc_info=True)
    return None


async def validate_changes(guild, changes: dict) -> tuple[dict, dict]:
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
            channel = await resolve_text_channel(guild, value)
            if channel is None:
                errors[key] = "القناة غير موجودة في هذا السيرفر"
                continue
        if value is not None and key == "welcome_embed_sticker_id":
            if await resolve_guild_sticker(guild, value) is None:
                errors[key] = "ملصق السيرفر غير موجود أو غير متاح للبوت"
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
    raw_guild_id = req.match_info.get("guild_id", "")
    try:
        guild_id = int(raw_guild_id)
    except (TypeError, ValueError):
        raise web.HTTPNotFound(
            text=json.dumps({"error": "not_found"}),
            content_type="application/json",
        )
    _, authorized_guild = await authorize(req)
    guild = bot_ref.get_guild(guild_id) if bot_ref else None
    if guild is None or guild.id != authorized_guild.id:
        raise web.HTTPNotFound(
            text=json.dumps({"error": "not_found"}),
            content_type="application/json",
        )
    return web.json_response(await guild_meta(guild))


@routes.get('/api/guild/{guild_id}/stats')
async def api_guild_stats(req):
    _, guild = await authorize(req)
    metrics = (
        bot_ref.metrics_for_guild(guild.id)
        if bot_ref and hasattr(bot_ref, "metrics_for_guild")
        else []
    )
    return web.json_response(
        await get_dashboard_stats(
            guild.id,
            member_count=guild.member_count,
            latency_series=metrics,
        )
    )


def _security_cog():
    return bot_ref.get_cog("Security") if bot_ref else None


def _moderation_cog():
    return bot_ref.get_cog("Moderation") if bot_ref else None


@routes.get('/api/guild/{guild_id}/actions')
async def api_guild_actions(req):
    _, guild = await authorize(req)
    security = _security_cog()
    incidents = security.get_incidents(guild.id) if security else []
    warnings = await get_recent_warnings(guild.id, 50)
    actions = [
        {
            "id": f"security-{index}",
            "kind": "security",
            "action": item.get("action_type", item.get("action", "security")),
            "reason": item.get("mitigation_taken", item.get("reason", "")),
            "timestamp": item.get("timestamp"),
        }
        for index, item in enumerate(incidents)
    ]
    actions.extend(
        {
            "id": f"infraction-{item['id']}",
            "kind": "moderation",
            "action": "warning",
            "reason": item.get("reason", ""),
            "timestamp": item.get("timestamp"),
        }
        for item in warnings
    )
    actions.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
    return web.json_response({"actions": actions[:100]})


@routes.post('/api/guild/{guild_id}/actions')
async def api_guild_action(req):
    session, guild = await authorize(req, write=True)
    body = await read_json_body(req)
    action = str(body.get("action", "")).strip()
    result: dict
    if action == "lockdown":
        security = _security_cog()
        if security is None or "locked" not in body:
            return json_error(503, "security_unavailable")
        result = await security.emergency_lockdown(guild.id, bool(body["locked"]))
    elif action == "revoke_warning":
        moderation = _moderation_cog()
        warning_id = body.get("warning_id")
        if moderation is None or not str(warning_id).isdigit():
            return json_error(400, "validation", fields={"warning_id": "رقم المخالفة غير صالح"})
        result = {"deleted": bool(await moderation.revoke_warning(int(warning_id)))}
    elif action == "quick_unmute":
        moderation = _moderation_cog()
        user_id = body.get("user_id")
        if moderation is None or not str(user_id).isdigit():
            return json_error(400, "validation", fields={"user_id": "رقم العضو غير صالح"})
        result = await moderation.quick_unmute(guild.id, int(user_id))
    else:
        return json_error(400, "unsupported_action")
    logger.info(
        "Dashboard action %s applied in guild %s by user %s",
        action,
        guild.id,
        session["id"],
    )
    broadcast(guild.id, {"type": "action", "action": action, "result": result})
    return web.json_response({"ok": True, "action": action, "result": result})


def _utilities_cog():
    return bot_ref.get_cog("Utilities") if bot_ref else None


def _community_cog():
    return bot_ref.get_cog("Community") if bot_ref else None


def _command_roles(guild, role_ids):
    if not isinstance(role_ids, list) or len(role_ids) > 25:
        return None, "اختر من 0 إلى 25 رتبة"
    clean = []
    for role_id in role_ids:
        try:
            role = guild.get_role(int(role_id))
        except (TypeError, ValueError):
            role = None
        if role is None or role.is_default():
            return None, "توجد رتبة غير موجودة في هذا السيرفر"
        clean.append(str(role.id))
    return list(dict.fromkeys(clean)), None


def _command_channels(guild, channel_ids):
    if not isinstance(channel_ids, list) or len(channel_ids) > 25:
        return None, "اختر من 0 إلى 25 قناة"
    clean = []
    for channel_id in channel_ids:
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            channel = None
        if channel is None:
            return None, "توجد قناة غير موجودة في هذا السيرفر"
        clean.append(str(channel.id))
    return list(dict.fromkeys(clean)), None


@routes.get('/api/guild/{guild_id}/commands')
async def api_guild_commands(req):
    _, guild = await authorize(req)
    utilities = _utilities_cog()
    if utilities is None:
        return json_error(503, "utilities_unavailable")
    status = await utilities.get_guild_commands_status(guild.id)
    meta = await guild_meta(guild)
    status["roles"] = meta["roles"]
    status["channels"] = meta["channels"]
    status["shortcuts"] = await get_shortcuts(guild.id)
    return web.json_response(status)


@routes.post('/api/guild/{guild_id}/commands/toggle')
async def api_guild_commands_toggle(req):
    _, guild = await authorize(req, write=True)
    utilities = _utilities_cog()
    if utilities is None:
        return json_error(503, "utilities_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    command_name = str(body.get("command_name", "")).strip().lower()
    if not command_name or len(command_name) > 100:
        return json_error(400, "validation", fields={"command_name": "اسم الأمر غير صالح"})
    if not isinstance(body.get("enabled"), bool):
        return json_error(400, "validation", fields={"enabled": "القيمة يجب أن تكون تشغيل/إيقاف"})
    roles, role_error = _command_roles(guild, body.get("allowed_roles", []))
    if role_error:
        return json_error(400, "validation", fields={"allowed_roles": role_error})
    channels, channel_error = _command_channels(guild, body.get("allowed_channels", []))
    if channel_error:
        return json_error(400, "validation", fields={"allowed_channels": channel_error})
    result = await utilities.toggle_command(
        guild.id,
        command_name,
        body["enabled"],
        roles,
        channels,
    )
    return web.json_response({"command": result})


@routes.post('/api/guild/{guild_id}/shortcuts')
async def api_guild_shortcut_save(req):
    _, guild = await authorize(req, write=True)
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    trigger = str(body.get("trigger") or "").strip()
    target_type = str(body.get("target_type") or "command").strip().lower()
    target = str(body.get("target") or "").strip()
    if not trigger or len(trigger) > 80 or any(char.isspace() for char in trigger):
        return json_error(400, "validation", fields={"trigger": "الاختصار يجب أن يكون كلمة واحدة من 1 إلى 80 حرفاً"})
    if target_type not in {"command", "help"} or not target:
        return json_error(400, "validation", fields={"target": "أمر الهدف غير صالح"})
    command_name = target.lstrip("!/").split()[0].lower()
    utilities = _utilities_cog()
    command_bot = getattr(utilities, "bot", None) or bot_ref
    prefix_commands = getattr(command_bot, "commands", []) if command_bot else []
    tree = getattr(command_bot, "tree", None) if command_bot else None
    slash_commands = tree.walk_commands() if tree and hasattr(tree, "walk_commands") else []
    known = {
        command.qualified_name.lower()
        for command in prefix_commands
        if not getattr(command, "hidden", False)
    }
    known.update(
        command.qualified_name.lower()
        for command in slash_commands
        if not getattr(command, "hidden", False)
    )
    if known and command_name not in known:
        return json_error(400, "validation", fields={"target": "الأمر الهدف غير موجود"})
    try:
        shortcut = await save_shortcut(
            guild.id,
            trigger,
            target_type,
            target=target if target.startswith("/") else f"/{command_name}",
        )
        utilities = _utilities_cog()
        if utilities and hasattr(utilities, "sync_auto_responders"):
            await utilities.sync_auto_responders(guild.id)
    except ValueError as error:
        return json_error(400, "validation", fields={"trigger": str(error)})
    return web.json_response({"shortcut": shortcut})


@routes.delete('/api/guild/{guild_id}/shortcuts/{shortcut_id}')
async def api_guild_shortcut_delete(req):
    _, guild = await authorize(req, write=True)
    try:
        shortcut_id = int(req.match_info["shortcut_id"])
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"shortcut_id": "معرف الاختصار غير صالح"})
    if not await delete_shortcut(guild.id, shortcut_id):
        return json_error(404, "shortcut_not_found")
    utilities = _utilities_cog()
    if utilities and hasattr(utilities, "sync_auto_responders"):
        await utilities.sync_auto_responders(guild.id)
    return web.json_response({"deleted": True, "shortcut_id": shortcut_id})


@routes.get('/api/guild/{guild_id}/auto-responses')
async def api_guild_auto_responses(req):
    _, guild = await authorize(req)
    rules = await get_auto_responders(guild.id)
    meta = await guild_meta(guild)
    return web.json_response({
        "rules": rules,
        "channels": [
            {"id": str(channel.id), "name": channel.name}
            for channel in guild.text_channels
        ],
        "roles": meta["roles"],
        "emojis": meta["emojis"],
        "members": meta["members"],
    })


@routes.post('/api/guild/{guild_id}/auto-responses')
async def api_guild_auto_responses_save(req):
    _, guild = await authorize(req, write=True)
    utilities = _utilities_cog()
    if utilities is None:
        return json_error(503, "utilities_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})

    trigger = str(body.get("trigger", "")).strip()
    match_type = str(body.get("match_type", "")).strip().lower()
    response = str(body.get("response", ""))
    target_type = str(body.get("target_type", "everyone")).strip().lower()
    reaction_emoji = str(body.get("reaction_emoji", "") or "").strip()
    if not trigger or len(trigger) > 500:
        return json_error(400, "validation", fields={"trigger": "المشغل يجب أن يكون بين 1 و500 حرف"})
    if match_type not in {"exact", "contains", "regex"}:
        return json_error(400, "validation", fields={"match_type": "نوع المطابقة غير صالح"})
    if len(response) > 2000:
        return json_error(400, "validation", fields={"response": "الرد يجب ألا يتجاوز 2000 حرف"})
    if target_type not in {"everyone", "role", "user"}:
        return json_error(400, "validation", fields={"target_type": "نطاق الاستهداف غير صالح"})
    try:
        target_id = max(0, int(body.get("target_id") or 0))
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"target_id": "معرف الاستهداف غير صالح"})
    if target_type == "role":
        role = guild.get_role(target_id)
        if role is None or role.is_default():
            return json_error(400, "validation", fields={"target_id": "الرتبة غير موجودة في هذا السيرفر"})
    elif target_type == "user":
        member = guild.get_member(target_id)
        if member is None:
            try:
                member = await guild.fetch_member(target_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                member = None
        if member is None:
            return json_error(400, "validation", fields={"target_id": "العضو غير موجود في هذا السيرفر"})
    elif target_id:
        return json_error(400, "validation", fields={"target_id": "لا تستخدم معرفاً مع نطاق الجميع"})
    if reaction_emoji.startswith("<") and reaction_emoji.endswith(">"):
        parsed_emoji = parse_custom_emoji(reaction_emoji)
        if not parsed_emoji or not parsed_emoji.id or guild.get_emoji(parsed_emoji.id) is None:
            return json_error(400, "validation", fields={"reaction_emoji": "الإيموجي المخصص غير موجود في هذا السيرفر"})
        reaction_emoji = str(parsed_emoji)
    if not response.strip() and not reaction_emoji:
        return json_error(400, "validation", fields={"response": "أدخل نص الرد أو اختر إيموجي تفاعلاً"})
    try:
        cooldown = float(body.get("cooldown_seconds", 5))
    except (TypeError, ValueError):
        cooldown = -1
    if cooldown < 0 or cooldown > 60:
        return json_error(400, "validation", fields={"cooldown_seconds": "التبريد يجب أن يكون بين 0 و60 ثانية"})

    channel_id = body.get("channel_id")
    if channel_id in ("", None):
        channel_id = None
    else:
        try:
            channel = guild.get_channel(int(channel_id))
        except (TypeError, ValueError):
            channel = None
        if not isinstance(channel, discord.TextChannel):
            return json_error(400, "validation", fields={"channel_id": "القناة النصية غير موجودة في هذا السيرفر"})
        channel_id = int(channel.id)

    try:
        rule = await utilities.add_auto_responder(
            guild.id,
            trigger,
            match_type,
            response,
            enabled=bool(body.get("enabled", True)),
            cooldown_seconds=cooldown,
            bucket_capacity=max(1, min(20, int(body.get("bucket_capacity", 1)))),
            channel_id=channel_id,
            target_type=target_type,
            target_id=target_id,
            reaction_emoji=reaction_emoji,
        )
    except (ValueError, re.error) as error:
        return json_error(400, "validation", fields={"trigger": str(error)})
    return web.json_response({"rule": rule})


@routes.delete('/api/guild/{guild_id}/auto-responses/{rule_id}')
async def api_guild_auto_responses_delete(req):
    _, guild = await authorize(req, write=True)
    utilities = _utilities_cog()
    if utilities is None:
        return json_error(503, "utilities_unavailable")
    try:
        rule_id = int(req.match_info["rule_id"])
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"rule_id": "معرف القاعدة غير صالح"})
    if rule_id <= 0:
        return json_error(400, "validation", fields={"rule_id": "معرف القاعدة غير صالح"})
    deleted = await utilities.delete_auto_responder(guild.id, rule_id)
    if not deleted:
        return json_error(404, "auto_responder_not_found")
    return web.json_response({"deleted": True, "rule_id": rule_id})


def _ticket_role_ids(guild, categories):
    if not isinstance(categories, list) or not categories or len(categories) > 25:
        return None, "أضف من 1 إلى 25 تصنيفاً"
    clean = []
    for index, raw in enumerate(categories):
        if not isinstance(raw, dict):
            return None, f"التصنيف رقم {index + 1} غير صالح"
        label = str(raw.get("label") or raw.get("name") or "").strip()
        if not label or len(label) > 80:
            return None, f"اسم التصنيف رقم {index + 1} غير صالح"
        role_ids = raw.get("support_role_ids", [])
        senior_ids = raw.get("senior_role_ids", [])
        if not isinstance(role_ids, list) or not isinstance(senior_ids, list):
            return None, f"رتب التصنيف رقم {index + 1} غير صالحة"
        for role_id in [*role_ids, *senior_ids]:
            try:
                role = guild.get_role(int(role_id))
            except (TypeError, ValueError):
                role = None
            if role is None or role.is_default():
                return None, f"توجد رتبة غير موجودة في التصنيف رقم {index + 1}"
        category_id = raw.get("category_id")
        if category_id not in (None, ""):
            try:
                parent = guild.get_channel(int(category_id))
            except (TypeError, ValueError):
                parent = None
            if not isinstance(parent, discord.CategoryChannel):
                return None, f"الفئة الأب للتصنيف رقم {index + 1} غير موجودة"
        intake_fields = raw.get("intake_fields", [])
        if not isinstance(intake_fields, list) or len(intake_fields) > 3:
            return None, f"حقول نموذج التصنيف رقم {index + 1} غير صالحة"
        clean_fields = []
        for field_index, field in enumerate(intake_fields):
            if not isinstance(field, dict):
                return None, f"حقل نموذج غير صالح في التصنيف رقم {index + 1}"
            field_label = str(field.get("label") or "").strip()
            if not field_label or len(field_label) > 45:
                return None, f"اسم حقل نموذج غير صالح في التصنيف رقم {index + 1}"
            field_key = re.sub(
                r"[^a-zA-Z0-9_-]+", "_",
                str(field.get("key") or f"field_{field_index + 1}").strip().lower(),
            ).strip("_")[:40]
            if not field_key:
                return None, f"مفتاح حقل نموذج غير صالح في التصنيف رقم {index + 1}"
            clean_fields.append({
                "key": field_key,
                "label": field_label,
                "placeholder": str(field.get("placeholder") or "").strip()[:100],
                "required": bool(field.get("required", False)),
            })
        normalized = dict(raw)
        normalized["intake_fields"] = clean_fields
        clean.append(normalized)
    return clean, None


@routes.post('/api/guild/{guild_id}/tickets/deploy')
async def api_guild_tickets_deploy(req):
    session, guild = await authorize(req, write=True)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    channel_id = body.get("target_channel_id")
    if isinstance(channel_id, bool) or not str(channel_id).isdigit():
        return json_error(400, "validation", fields={"target_channel_id": "معرف القناة غير صالح"})
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return json_error(400, "validation", fields={"target_channel_id": "القناة النصية غير موجودة"})
    categories, category_error = _ticket_role_ids(guild, body.get("categories"))
    if category_error:
        return json_error(400, "validation", fields={"categories": category_error})
    try:
        result = await community.deploy_ticket_panel(channel.id, categories)
    except (ValueError, discord.Forbidden, discord.HTTPException) as error:
        logger.warning("Ticket panel deployment failed: %s", error)
        return json_error(400, "ticket_panel_deploy_failed")
    logger.info("Ticket panel deployed in guild %s by user %s", guild.id, session["id"])
    return web.json_response({"ok": True, "panel": result})


@routes.get('/api/guild/{guild_id}/tickets/active')
async def api_guild_tickets_active(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    return web.json_response({"tickets": await community.get_active_tickets(guild.id)})


@routes.get('/api/guild/{guild_id}/tickets/archive')
async def api_guild_tickets_archive(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    query = req.query.get("q", req.query.get("query", ""))
    return web.json_response({
        "tickets": await community.get_ticket_archive(guild.id, query[:120]),
        "query": query[:120],
    })


@routes.get('/api/guild/{guild_id}/tickets/transcript/{ticket_id}')
async def api_guild_ticket_transcript(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    try:
        ticket_id = int(req.match_info["ticket_id"])
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"ticket_id": "معرف التذكرة غير صالح"})
    transcript = await community.get_ticket_transcript(guild.id, ticket_id)
    if not transcript:
        return json_error(404, "transcript_not_found")
    return web.Response(
        text=transcript["content_html"],
        content_type="text/html",
        charset="utf-8",
        headers={
            "Content-Disposition": f'inline; filename="ticket-{ticket_id}.html"',
            "Cache-Control": "no-store",
        },
    )


@routes.get('/api/guild/{guild_id}/tickets/detail/{ticket_id}')
async def api_guild_ticket_detail(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    try:
        ticket_id = int(req.match_info["ticket_id"])
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"ticket_id": "معرف التذكرة غير صالح"})
    ticket = await community.get_ticket(guild.id, ticket_id)
    if not ticket:
        return json_error(404, "ticket_not_found")
    return web.json_response({
        "ticket": ticket,
        "notes": await community.get_ticket_notes(guild.id, ticket_id),
    })


@routes.get('/api/guild/{guild_id}/tickets/kpis')
async def api_guild_tickets_kpis(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    return web.json_response({"kpis": await community.get_staff_kpis(guild.id)})


@routes.post('/api/guild/{guild_id}/tickets/action')
async def api_guild_tickets_action(req):
    session, guild = await authorize(req, write=True)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    try:
        ticket_id = int(body.get("ticket_id"))
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"ticket_id": "معرف التذكرة غير صالح"})
    action = str(body.get("action", "")).strip().lower()
    if action == "close":
        result = await community.force_close_ticket(
            guild.id,
            ticket_id,
            int(session["id"]),
            str(body.get("reason") or "أُغلقت من لوحة الإدارة"),
        )
    elif action == "reassign":
        try:
            staff_id = int(body.get("staff_id"))
        except (TypeError, ValueError):
            return json_error(400, "validation", fields={"staff_id": "معرف الموظف غير صالح"})
        member = guild.get_member(staff_id)
        if member is None:
            return json_error(400, "validation", fields={"staff_id": "الموظف غير موجود في السيرفر"})
        result = await community.reassign_ticket(guild.id, ticket_id, staff_id)
    elif action == "status":
        status = str(body.get("status", "")).strip().lower()
        if status not in {"active", "waiting_user", "waiting_staff"}:
            return json_error(400, "validation", fields={"status": "حالة التذكرة غير صالحة"})
        result = await community.set_ticket_status(
            guild.id, ticket_id, status
        )
    elif action == "priority":
        priority = str(body.get("priority", "")).strip().lower()
        if priority not in {"normal", "high", "management"}:
            return json_error(400, "validation", fields={"priority": "أولوية التذكرة غير صالحة"})
        result = await community.update_ticket_priority(guild.id, ticket_id, priority)
    elif action == "reopen":
        result = await community.reopen_ticket(guild.id, ticket_id, int(session["id"]))
    elif action == "note":
        content = str(body.get("content") or "").strip()
        if not content or len(content) > 2000:
            return json_error(400, "validation", fields={"content": "الملاحظة يجب أن تكون بين 1 و2000 حرف"})
        result = await community.add_internal_note(
            guild.id, ticket_id, int(session["id"]), content
        )
    else:
        return json_error(
            400, "validation",
            fields={"action": "الإجراء يجب أن يكون close أو reassign أو status أو priority أو reopen أو note"},
        )
    if not result:
        return json_error(404, "ticket_not_found")
    return web.json_response({"ok": True, "ticket": result})


@routes.get('/api/guild/{guild_id}/tickets/canned')
async def api_guild_tickets_canned_get(req):
    _, guild = await authorize(req)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    return web.json_response({"responses": await community.get_canned_responses(guild.id)})


@routes.post('/api/guild/{guild_id}/tickets/canned')
async def api_guild_tickets_canned(req):
    session, guild = await authorize(req, write=True)
    community = _community_cog()
    if community is None:
        return json_error(503, "community_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        body = await req.json()
    except (json.JSONDecodeError, ValueError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    if body.get("action") == "delete":
        try:
            response_id = int(body.get("id"))
        except (TypeError, ValueError):
            return json_error(400, "validation", fields={"id": "معرف الرد غير صالح"})
        if not await community.delete_canned_response(guild.id, response_id):
            return json_error(404, "canned_not_found")
        return web.json_response({"deleted": True, "id": response_id})
    title = str(body.get("title", "")).strip()
    content = str(body.get("content", "")).strip()
    category = str(body.get("category", "عام")).strip()
    shortcut = str(body.get("shortcut") or "").strip() or None
    sticker_id = body.get("sticker_id")
    response_id = body.get("id")
    if not title or len(title) > 120:
        return json_error(400, "validation", fields={"title": "العنوان يجب أن يكون بين 1 و120 حرفاً"})
    if not content or len(content) > 2000:
        return json_error(400, "validation", fields={"content": "النص يجب أن يكون بين 1 و2000 حرف"})
    if shortcut and len(shortcut) > 80:
        return json_error(400, "validation", fields={"shortcut": "الاختصار يجب ألا يتجاوز 80 حرفاً"})
    if sticker_id in ("", None):
        sticker_id = None
    else:
        try:
            sticker_id = int(sticker_id)
        except (TypeError, ValueError):
            return json_error(400, "validation", fields={"sticker_id": "معرف الملصق غير صالح"})
        if await resolve_guild_sticker(guild, sticker_id) is None:
            return json_error(400, "validation", fields={"sticker_id": "ملصق السيرفر غير موجود أو غير متاح"})
    try:
        response_id = int(response_id) if response_id not in (None, "") else None
    except (TypeError, ValueError):
        return json_error(400, "validation", fields={"id": "معرف الرد غير صالح"})
    result = await community.save_canned_response(
        guild.id,
        title,
        content,
        category,
        session["id"],
        response_id,
        shortcut,
        sticker_id,
    )
    if not result:
        return json_error(404, "canned_not_found")
    return web.json_response({"response": result})


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


@routes.post('/api/guild/{guild_id}/engagement/test-welcome')
async def api_test_welcome(req):
    session, guild = await authorize(req, write=True)
    engagement = bot_ref.get_cog("Engagement") if bot_ref else None
    if engagement is None:
        return json_error(503, "engagement_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        raw_body = await req.content.read(MAX_BODY + 1)
        if len(raw_body) > MAX_BODY:
            return json_error(413, "too_large")
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    raw_channel_id = body.get("target_channel_id")
    if isinstance(raw_channel_id, bool) or not str(raw_channel_id).isdigit():
        return json_error(400, "validation", fields={"target_channel_id": "معرف قناة غير صالح"})
    channel_id = int(raw_channel_id)
    channel = await resolve_text_channel(guild, channel_id)
    if channel is None:
        return json_error(400, "validation", fields={"target_channel_id": "القناة غير موجودة في هذا السيرفر"})
    template_data = body.get("template_data", {})
    if not isinstance(template_data, dict) or len(template_data) > 8:
        return json_error(400, "validation", fields={"template_data": "بيانات المعاينة غير صالحة"})
    result = await engagement.send_test_welcome(guild.id, channel_id, template_data)
    if not result.get("ok"):
        return json_error(
            404 if result.get("error") in {"guild_not_found", "channel_not_found"} else 403,
            result.get("error", "welcome_test_failed"),
        )
    logger.info(
        "Welcome preview sent in guild %s by user %s to channel %s",
        guild.id,
        session["id"],
        channel_id,
    )
    return web.json_response(result)


ONBOARDING_KEYS = {
    "welcome_channel_id",
    "leave_channel_id",
    "welcome_message",
    "leave_message",
    "welcome_dm_enabled",
    "welcome_embed_enabled",
    "welcome_embed_color",
    "welcome_embed_title",
    "welcome_embed_description",
    "welcome_embed_image_url",
    "welcome_embed_sticker_id",
    "welcome_embed_footer",
    "welcome_embed_show_avatar",
    "auto_role_id",
    "member_auto_role_id",
    "bot_auto_role_id",
    "verified_role_id",
    "unverified_role_id",
    "rules_channel_id",
}


async def onboarding_payload(guild, engagement):
    return await engagement.get_onboarding_snapshot(guild.id)


@routes.get('/api/guild/{guild_id}/onboarding')
async def api_get_onboarding(req):
    _, guild = await authorize(req)
    engagement = bot_ref.get_cog("Engagement") if bot_ref else None
    if engagement is None:
        return json_error(503, "engagement_unavailable")
    return web.json_response(await onboarding_payload(guild, engagement))


@routes.post('/api/guild/{guild_id}/onboarding')
async def api_post_onboarding(req):
    session, guild = await authorize(req, write=True)
    engagement = bot_ref.get_cog("Engagement") if bot_ref else None
    if engagement is None:
        return json_error(503, "engagement_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        raw_body = await req.content.read(MAX_BODY + 1)
        if len(raw_body) > MAX_BODY:
            return json_error(413, "too_large")
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    revision = body.get("revision")
    if revision is not None and (
        not isinstance(revision, int) or isinstance(revision, bool)
    ):
        return json_error(400, "validation", fields={"revision": "رقم الإصدار غير صالح"})
    changes = body.get("changes", {})
    if not isinstance(changes, dict):
        return json_error(400, "validation", fields={"changes": "صيغة التعديلات غير صالحة"})
    unknown = set(changes) - ONBOARDING_KEYS
    if unknown:
        return json_error(
            400,
            "validation",
            fields={str(key): "حقل غير مسموح في استوديو الترحيب" for key in unknown},
        )
    clean, errors = await validate_changes(guild, changes)
    if errors:
        return json_error(400, "validation", fields=errors)
    try:
        snapshot = await update_guild_settings(
            guild.id,
            expected_revision=revision,
            **clean,
        ) if clean else await get_guild_settings(guild.id)
    except SettingsConflict as conflict:
        return json_error(409, "conflict", **public_settings(conflict.current))
    result = await onboarding_payload(guild, engagement)
    broadcast(guild.id, {"type": "settings", "by": str(session["id"]), **result})
    return web.json_response(result)


@routes.post('/api/guild/{guild_id}/onboarding/test-welcome')
async def api_onboarding_test_welcome(req):
    session, guild = await authorize(req, write=True)
    engagement = bot_ref.get_cog("Engagement") if bot_ref else None
    if engagement is None:
        return json_error(503, "engagement_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        raw_body = await req.content.read(MAX_BODY + 1)
        if len(raw_body) > MAX_BODY:
            return json_error(413, "too_large")
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    channel_id = body.get("target_channel_id")
    if isinstance(channel_id, bool) or not str(channel_id).isdigit():
        return json_error(400, "validation", fields={"target_channel_id": "معرف قناة غير صالح"})
    channel = await resolve_text_channel(guild, int(channel_id))
    if channel is None:
        return json_error(400, "validation", fields={"target_channel_id": "القناة غير موجودة في هذا السيرفر"})
    template_data = body.get("template_data", {})
    if not isinstance(template_data, dict) or len(template_data) > 8:
        return json_error(400, "validation", fields={"template_data": "بيانات المعاينة غير صالحة"})
    result = await engagement.send_test_welcome(guild.id, int(channel_id), template_data)
    if not result.get("ok"):
        return json_error(
            404 if result.get("error") in {"guild_not_found", "channel_not_found"} else 403,
            result.get("error", "welcome_test_failed"),
        )
    logger.info("Onboarding welcome preview sent in guild %s by user %s", guild.id, session["id"])
    return web.json_response(result)


@routes.post('/api/guild/{guild_id}/onboarding/self-roles')
async def api_deploy_self_roles(req):
    session, guild = await authorize(req, write=True)
    engagement = bot_ref.get_cog("Engagement") if bot_ref else None
    if engagement is None:
        return json_error(503, "engagement_unavailable")
    if req.content_length and req.content_length > MAX_BODY:
        return json_error(413, "too_large")
    try:
        raw_body = await req.content.read(MAX_BODY + 1)
        if len(raw_body) > MAX_BODY:
            return json_error(413, "too_large")
        body = json.loads(raw_body.decode("utf-8") or "{}")
    except (ValueError, UnicodeDecodeError):
        return json_error(400, "invalid_json")
    if not isinstance(body, dict):
        return json_error(400, "validation", fields={"_": "صيغة الطلب غير صالحة"})
    channel_id = body.get("target_channel_id")
    if isinstance(channel_id, bool) or not str(channel_id).isdigit():
        return json_error(400, "validation", fields={"target_channel_id": "معرف قناة غير صالح"})
    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return json_error(400, "validation", fields={"target_channel_id": "القناة غير موجودة في هذا السيرفر"})
    roles = body.get("roles")
    if not isinstance(roles, list) or not 1 <= len(roles) <= 25:
        return json_error(400, "validation", fields={"roles": "اختر من رتبة إلى 25 رتبة"})
    for spec in roles:
        if (
            not isinstance(spec, dict)
            or isinstance(spec.get("id"), bool)
            or not str(spec.get("id", "")).isdigit()
        ):
            return json_error(400, "validation", fields={"roles": "بيانات الرتب غير صالحة"})
    result = await engagement.deploy_self_role_panel(
        guild.id,
        int(channel_id),
        str(body.get("title") or "الرتب الذاتية")[:256],
        str(body.get("description") or "اختر الرتب المناسبة لك:")[:4000],
        str(body.get("color") or "#5865f2")[:20],
        str(body.get("emoji") or "🏷️")[:8],
        roles,
    )
    if not result.get("ok"):
        return json_error(
            400 if result.get("error") in {"roles_invalid", "role_not_assignable"} else 404,
            result.get("error", "self_role_deploy_failed"),
        )
    logger.info("Self-role panel deployed in guild %s by user %s", guild.id, session["id"])
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
    clean, errors = await validate_changes(guild, body.get("changes", {}))
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
        logger.debug("SSE client disconnected for guild %s", guild_id)
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
