import asyncio
import html
import logging
import os
import secrets
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

routes, bot_ref = web.RouteTableDef(), None
C_ID, C_SEC = os.getenv("CLIENT_ID"), os.getenv("CLIENT_SECRET")
R_URI = os.getenv("REDIRECT_URI")
API, ADMIN_BIT = "https://discord.com/api/v10", 0x8
SESSIONS, STATES = {}, {}
STATE_TTL, SESSION_TTL = 300, 604800
logger = logging.getLogger("DashboardOAuth")


def prune_expired():
    now = time.time()
    for state, created in list(STATES.items()):
        if now - created >= STATE_TTL:
            STATES.pop(state, None)
    for sid, session in list(SESSIONS.items()):
        if now >= session["expires_at"]:
            SESSIONS.pop(sid, None)


def current_session(req):
    prune_expired()
    return SESSIONS.get(req.cookies.get("bot_session"))


@web.middleware
async def private_responses(req, handler):
    try:
        response = await handler(req)
    except web.HTTPException as response_error:
        response = response_error
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@routes.get("/login")
async def login(req):
    if not C_ID or not C_SEC or not R_URI:
        return web.Response(
            text="Discord OAuth is not configured: CLIENT_ID, CLIENT_SECRET "
            "and REDIRECT_URI are required.",
            status=503,
        )
    prune_expired()
    # A new attempt from the same browser supersedes its earlier attempt.
    STATES.pop(req.cookies.get("oauth_state"), None)
    state = secrets.token_urlsafe(32)
    STATES[state] = time.time()
    query = urlencode({
        "client_id": C_ID,
        "redirect_uri": R_URI,
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "none",
    })
    response = web.HTTPFound(f"{API}/oauth2/authorize?{query}")
    response.set_cookie(
        "oauth_state", state, max_age=STATE_TTL, httponly=True,
        secure=True, samesite="Lax", path="/",
    )
    return response


@routes.get("/api/auth/callback")
async def callback(req):
    prune_expired()
    code, state = req.query.get("code"), req.query.get("state")
    browser_state = req.cookies.get("oauth_state")
    if (
        not state or not browser_state or state not in STATES
        or not secrets.compare_digest(state, browser_state)
    ):
        return web.Response(text="CSRF Error", status=403)
    STATES.pop(state, None)
    if req.query.get("error") or not code:
        return web.Response(text="Discord authorization was not completed.", status=400)
    if not C_ID or not C_SEC or not R_URI:
        return web.Response(text="Discord OAuth is not configured.", status=503)

    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20),
        ) as session:
            data = {
                "client_id": C_ID, "client_secret": C_SEC,
                "grant_type": "authorization_code", "code": code,
                "redirect_uri": R_URI,
            }
            async with session.post(f"{API}/oauth2/token", data=data) as response:
                if response.status != 200:
                    return web.Response(text="Token exchange failed.", status=400)
                token = (await response.json()).get("access_token")
                if not token:
                    return web.Response(text="Invalid token response.", status=502)

            headers = {"Authorization": f"Bearer {token}"}
            async with session.get(f"{API}/users/@me", headers=headers) as response:
                if response.status != 200:
                    return web.Response(text="Unable to fetch Discord profile.", status=502)
                user_data = await response.json()
            # Discord paginates guilds; do not silently omit servers after page one.
            guild_data, after = [], None
            while True:
                params = {"limit": "200"}
                if after:
                    params["after"] = after
                async with session.get(
                    f"{API}/users/@me/guilds", headers=headers, params=params,
                ) as response:
                    if response.status != 200:
                        return web.Response(text="Unable to fetch Discord servers.", status=502)
                    page = await response.json()
                if not isinstance(page, list):
                    raise ValueError("Invalid guild list")
                guild_data.extend(page)
                if len(page) < 200:
                    break
                next_after = str(page[-1]["id"])
                if next_after == after:
                    raise ValueError("Invalid pagination cursor")
                after = next_after

        guilds = []
        for guild in guild_data:
            if (int(guild.get("permissions", 0)) & ADMIN_BIT) or guild.get("owner", False):
                if bot_ref and (bot_guild := bot_ref.get_guild(int(guild["id"]))):
                    guilds.append({
                        "id": str(bot_guild.id), "name": bot_guild.name,
                        "members": bot_guild.member_count,
                        "is_owner": guild.get("owner", False),
                    })

        user_session = {
            "id": user_data["id"], "username": user_data["username"],
            "avatar": user_data.get("avatar"), "guilds": guilds,
            "expires_at": time.time() + SESSION_TTL,
        }
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError, KeyError, TypeError):
        # Never log OAuth codes, access tokens or provider response bodies.
        logger.warning("Discord OAuth request failed or returned invalid data.")
        return web.Response(text="Discord login is temporarily unavailable.", status=502)

    SESSIONS.pop(req.cookies.get("bot_session"), None)
    sid = secrets.token_urlsafe(32)
    SESSIONS[sid] = user_session
    response = web.HTTPFound("/")
    response.del_cookie("oauth_state", path="/")
    response.set_cookie(
        "bot_session", sid, max_age=SESSION_TTL, httponly=True,
        secure=True, samesite="Lax", path="/",
    )
    return response


@routes.get("/logout")
async def logout(req):
    SESSIONS.pop(req.cookies.get("bot_session"), None)
    STATES.pop(req.cookies.get("oauth_state"), None)
    response = web.HTTPFound("/")
    response.del_cookie("bot_session", path="/")
    response.del_cookie("oauth_state", path="/")
    return response


@routes.get("/api/me")
async def api_me(req):
    session = current_session(req)
    if not session:
        return web.json_response({"auth": False}, status=401)
    public_session = {key: value for key, value in session.items() if key != "expires_at"}
    return web.json_response({"auth": True, "session": public_session})


@routes.get("/")
async def index(req):
    session = current_session(req)
    if not session:
        return web.Response(text="""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Login</title><style>body{background:#000;color:#fff;font-family:sans-serif;display:grid;place-content:center;min-height:95vh;margin:0}.card{background:#0c0f17;border:1px solid #1e293b;padding:2rem;border-radius:14px;text-align:center}a{background:#5865F2;color:#fff;text-decoration:none;padding:.75rem 1.4rem;border-radius:8px;font-weight:700;display:inline-block;margin-top:1rem}</style></head><body><div class="card"><h2>⚡ لوحة الإدارة الموحدة</h2><p style="color:#94a3b8;font-size:.85rem">سجل الدخول لإدارة سيرفراتك المصرح لك بها</p><a href="/login">تسجيل الدخول عبر ديسكورد</a></div></body></html>""", content_type="text/html")

    guild_items = "".join(
        "<li style='background:#111625;padding:10px;margin:6px 0;border-radius:8px;display:flex;justify-content:space-between'>"
        f"<span><b>{html.escape(guild['name'])}</b></span>"
        "<span style='color:#34d399;font-size:.8rem'>أدمن مصرح</span></li>"
        for guild in session["guilds"]
    ) or "<p style='color:#f87171'>لا توجد سيرفرات مشتركة بصلاحية أدمن.</p>"
    username = html.escape(session["username"])
    return web.Response(text=f"""<!DOCTYPE html><html dir="rtl" lang="ar"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Dashboard</title><style>body{{background:#000;color:#fff;font-family:sans-serif;padding:1rem}}.box{{max-width:550px;margin:auto;background:#0c0f17;border:1px solid #1e293b;border-radius:12px;padding:1.2rem}}.hdr{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #1e293b;padding-bottom:.8rem}}a{{color:#ef4444;text-decoration:none;font-weight:bold;font-size:.85rem}}ul{{list-style:none;padding:0}}</style></head><body><div class="box"><div class="hdr"><div><h3 style="margin:0">مرحباً {username}</h3><small style="color:#10b981">● تم التحقق بنجاح</small></div><a href="/logout">خروج</a></div><h4>السيرفرات المتاحة:</h4><ul>{guild_items}</ul></div></body></html>""", content_type="text/html")


async def start_web_server(bot):
    global bot_ref
    bot_ref = bot
    app = web.Application(middlewares=[private_responses])
    app.add_routes(routes)
    runner = web.AppRunner(app)
    await runner.setup()
    try:
        port = int(os.getenv("DASHBOARD_PORT", "8099"))
        await web.TCPSite(runner, "0.0.0.0", port).start()
    except Exception:
        await runner.cleanup()
        raise
    return runner