import asyncio
import logging
import os
import secrets
import time
from html import escape
from urllib.parse import urlencode

import aiohttp
import discord
from aiohttp import web

routes = web.RouteTableDef()
bot_ref: discord.Client = None

C_ID = os.getenv("CLIENT_ID")
C_SEC = os.getenv("CLIENT_SECRET")
R_URI = os.getenv("REDIRECT_URI")
DISCORD_API = "https://discord.com/api/v10"
ADMIN_BIT = 0x8
SESSIONS: dict[str, dict] = {}
STATES: dict[str, float] = {}
STATE_TTL, SESSION_TTL = 300, 604800
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
                <a href="/login" class="btn-login">
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

    # شاشة السيرفرات المصرح بها بعد تسجيل الدخول
    guilds_html = "".join([
        f"""<div style="background:#111625;border:1px solid #1e293b;border-radius:12px;padding:14px;display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
            <div style="display:flex;align-items:center;gap:12px;">
                <img src="{escape(g.get('icon') or 'https://cdn.discordapp.com/embed/avatars/0.png')}" style="width:42px;height:42px;border-radius:50%;border:1px solid #334155;">
                <div>
                    <div style="font-weight:bold;font-size:0.95rem;">{escape(g['name'])}</div>
                    <small style="color:#94a3b8;">الأعضاء: {format(g['members'], ',') if g['members'] is not None else 'غير متاح'} • {('👑 المالك' if g['is_owner'] else '🛡️ مشرف معتمد')}</small>
                </div>
            </div>
            <span style="background:rgba(16,185,129,0.15);color:#34d399;border:1px solid rgba(16,185,129,0.3);padding:4px 10px;border-radius:8px;font-size:0.75rem;font-weight:bold;">صلاحية معتمدة</span>
        </div>"""
        for g in sess["guilds"]
    ]) or """<div style="text-align:center;padding:2rem;background:#111625;border-radius:12px;border:1px dashed #ef4444;color:#fca5a5;">
                ⚠️ لا توجد سيرفرات مشتركة تمتلك فيها صلاحية Administrator حالياً.<br>
                <small style="color:#94a3b8;">تأكد من تواجد البوت في سيرفرك وأن لديك رتبة مسؤول كاملة.</small>
            </div>"""

    html = f"""
    <!DOCTYPE html>
    <html dir="rtl" lang="ar">
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>لوحة التحكم المركزية | التحقق من الهوية</title>
        <style>
            * {{ box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }}
            body {{ background: #000000; color: #f8fafc; margin: 0; padding: 1.2rem; display: flex; justify-content: center; }}
            .container {{ max-width: 650px; width: 100%; }}
            .user-header {{ background: #0a0e17; border: 1px solid #1e293b; border-radius: 14px; padding: 1rem 1.4rem; display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }}
            .user-info {{ display: flex; align-items: center; gap: 12px; }}
            .avatar {{ width: 44px; height: 44px; border-radius: 50%; border: 2px solid #3b82f6; }}
            .btn-logout {{ background: rgba(239,68,68,0.15); color: #f87171; border: 1px solid rgba(239,68,68,0.3); padding: 6px 14px; border-radius: 8px; text-decoration: none; font-size: 0.85rem; font-weight: bold; }}
            .section-title {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }}
            .status-box {{ background: rgba(16,185,129,0.1); border: 1px solid rgba(16,185,129,0.3); border-radius: 12px; padding: 14px; color: #34d399; font-size: 0.88rem; margin-top: 1.5rem; line-height: 1.6; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="user-header">
                <div class="user-info">
                    <img src="{escape(sess['avatar'])}" class="avatar">
                    <div>
                        <div style="font-weight:bold;font-size:1rem;">{escape(sess['username'])}</div>
                        <small style="color:#10b981;">● جلسة ديسكورد مشفرة ونشطة</small>
                    </div>
                </div>
                <a href="/logout" class="btn-logout">تسجيل الخروج</a>
            </div>

            <div class="section-title">
                <h3 style="margin:0;font-size:1.1rem;">السيرفرات المصرح لك بإدارتها:</h3>
                <span style="color:#94a3b8;font-size:0.85rem;">المعتمدة: {len(sess['guilds'])}</span>
            </div>

            {guilds_html}

            <div class="status-box">
                ✅ <b>المرحلة 1 مكتملة بنجاح:</b> تم بناء نظام التوثيق OAuth2 وفحص صلاحيات الأدمن بدقة.<br>
                جاهزون للانتقال إلى <b>المرحلة 2</b> (القائمة الجانبية المنبثقة ☰ ومحدد السيرفرات وشاشات التحكم AMOLED).
            </div>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type='text/html')

async def start_web_server(bot):
    global bot_ref
    bot_ref = bot
    app = web.Application(middlewares=[private_responses])
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
