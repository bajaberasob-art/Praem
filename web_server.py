import html
import os
import time

import discord
from aiohttp import web


routes = web.RouteTableDef()
bot_ref: discord.Client | None = None
dashboard_runner: web.AppRunner | None = None
start_time = time.time()

# كلمة المرور لحماية اللوحة (يمكنك ضبط DASHBOARD_KEY في Secrets أو استخدام القيمة الافتراضية)
ADMIN_KEY = os.getenv("DASHBOARD_KEY", "admin123")

HTML_TEMPLATE = """
<!DOCTYPE html>
<html dir="rtl" lang="ar">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>لوحة التحكم المركزية | Ultimate Bot Dashboard</title>
    <style>
        :root { --bg: #090d16; --card: #131b2e; --accent: #3b82f6; --text: #f1f5f9; --muted: #94a3b8; --border: #1e293b; --success: #10b981; }
        * { box-sizing: border-box; font-family: system-ui, -apple-system, sans-serif; }
        body { background: var(--bg); color: var(--text); margin: 0; padding: 1.5rem; }
        .container { max-width: 960px; margin: auto; }
        .header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 1rem; margin-bottom: 1.5rem; }
        .badge { background: #064e3b; color: var(--success); padding: 4px 12px; border-radius: 20px; font-size: 0.85rem; font-weight: bold; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem; }
        .card { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.2rem; }
        .card h3 { margin: 0 0 0.5rem; font-size: 0.85rem; color: var(--muted); }
        .card p { margin: 0; font-size: 1.6rem; font-weight: bold; color: var(--accent); }
        .panel { background: var(--card); border: 1px solid var(--border); border-radius: 12px; padding: 1.5rem; margin-bottom: 1.5rem; }
        input, textarea, select, button { width: 100%; padding: 0.75rem; margin-top: 0.5rem; border-radius: 8px; border: 1px solid #334155; background: #090d16; color: #fff; font-size: 0.95rem; }
        button { background: var(--accent); font-weight: bold; cursor: pointer; border: none; margin-top: 1rem; transition: 0.2s; }
        button:hover { opacity: 0.9; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>⚡ لوحة قيادة البوت المتقدمة</h2>
            <span class="badge">● متصل بنجاح</span>
        </div>
        <div class="grid">
            <div class="card"><h3>السيرفرات</h3><p>{guilds}</p></div>
            <div class="card"><h3>إجمالي الأعضاء</h3><p>{members}</p></div>
            <div class="card"><h3>سرعة الاستجابة</h3><p>{ping}ms</p></div>
            <div class="card"><h3>مدة التشغيل</h3><p>{uptime}د</p></div>
        </div>
        <div class="panel">
            <h3>📢 بث إعلان / Embed مخصص</h3>
            <form action="/api/broadcast" method="post">
                <label>مفتاح الأمان (Admin Key):</label>
                <input type="password" name="auth_key" placeholder="أدخل مفتاح الأمان..." required>
                <label style="display:block;margin-top:0.8rem">معرّف الروم (Channel ID):</label>
                <input type="text" name="channel_id" placeholder="مثال: 123456789012345678" required>
                <label style="display:block;margin-top:0.8rem">عنوان الإعلان (اختياري لـ Embed):</label>
                <input type="text" name="title" placeholder="عنوان الرسالة المضمنة...">
                <label style="display:block;margin-top:0.8rem">نص الرسالة:</label>
                <textarea name="message" rows="3" placeholder="محتوى الإعلان..." required></textarea>
                <button type="submit">إرسال الإعلان فوراً 🚀</button>
            </form>
        </div>
    </div>
</body>
</html>
"""


def dashboard_html(guilds: int, members: int, ping: int, uptime: int) -> str:
    """Render only the known dashboard placeholders.

    CSS uses braces too, so str.format() would interpret the stylesheet as
    format fields. Replacing the four data placeholders keeps the template safe.
    """
    return (
        HTML_TEMPLATE
        .replace("{guilds}", str(guilds))
        .replace("{members}", str(members))
        .replace("{ping}", str(ping))
        .replace("{uptime}", str(uptime))
    )


def bot_stats() -> tuple[int, int, int]:
    if not bot_ref:
        return 0, 0, 0
    guilds = len(bot_ref.guilds)
    members = sum(
        guild.member_count for guild in bot_ref.guilds if guild.member_count
    )
    ping = round(bot_ref.latency * 1000)
    return guilds, members, ping


@routes.get("/")
async def index(req: web.Request):
    guilds, members, ping = bot_stats()
    uptime = int((time.time() - start_time) // 60)
    return web.Response(
        text=dashboard_html(guilds, members, ping, uptime),
        content_type="text/html",
    )


@routes.get("/api/stats")
async def api_stats(req: web.Request):
    guilds, members, ping = bot_stats()
    return web.json_response(
        {
            "guilds": guilds,
            "members": members,
            "ping": ping,
            "uptime_min": int((time.time() - start_time) // 60),
            "status": "online" if bot_ref and bot_ref.is_ready() else "starting",
        }
    )


@routes.post("/api/broadcast")
async def api_broadcast(req: web.Request):
    data = await req.post()
    key = data.get("auth_key")
    if key != ADMIN_KEY:
        return web.Response(
            text="<h1>⛔ مفتاح الأمان غير صحيح!</h1><a href='/'>العودة</a>",
            content_type="text/html",
            status=403,
        )

    channel_id = data.get("channel_id")
    message = data.get("message")
    title = data.get("title")
    if not bot_ref or not channel_id or not message:
        return web.Response(text="بيانات غير مكتملة", status=400)

    try:
        channel = bot_ref.get_channel(int(channel_id))
        if channel is None:
            channel = await bot_ref.fetch_channel(int(channel_id))
        if title:
            embed = discord.Embed(
                title=title,
                description=message,
                color=0x3B82F6,
            )
            embed.set_footer(text="بث رسمي عبر لوحة التحكم المركزية")
            await channel.send(embed=embed)
        else:
            await channel.send(f"📢 **إعلان:**\n{message}")
        return web.Response(
            text=(
                "<h1>✅ تم إرسال الإعلان بنجاح!</h1>"
                "<a href='/'>العودة للوحة التحكم</a>"
            ),
            content_type="text/html",
        )
    except (TypeError, ValueError):
        return web.Response(
            text="<h1>❌ معرّف الروم غير صالح.</h1><a href='/'>العودة</a>",
            content_type="text/html",
            status=400,
        )
    except Exception as error:
        safe_error = html.escape(str(error))
        return web.Response(
            text=f"<h1>❌ فشل الإرسال: {safe_error}</h1><a href='/'>العودة</a>",
            content_type="text/html",
            status=500,
        )


async def start_web_server(bot: discord.Client):
    """Start the dashboard and return its runner for graceful shutdown."""
    global bot_ref, dashboard_runner
    bot_ref = bot
    app = web.Application()
    app.add_routes(routes)
    dashboard_runner = web.AppRunner(app)
    await dashboard_runner.setup()
    port = int(os.getenv("DASHBOARD_PORT", "8080"))
    await web.TCPSite(dashboard_runner, "0.0.0.0", port).start()
    return dashboard_runner
