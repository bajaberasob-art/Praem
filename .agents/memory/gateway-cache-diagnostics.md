---
name: Gateway cache readiness diagnostics
description: Discord gateway startup behavior when privileged intents and member chunking are enabled.
---

Full privileged intents with startup guild chunking can delay `on_ready` even after the gateway transport connects. A connected session is not necessarily a usable, fully hydrated cache; member chunk completion and guild availability must be observed separately.

**Why:** The dashboard and responder metadata depend on cached members, roles, and emojis. In this environment, the guild member chunk completed successfully before `on_ready`, but the delay was long enough that a transport-only log looked like a startup hang.

**How to apply:** Keep explicit gateway diagnostics for transport connection, per-guild availability, ready status, cached member counts, chunked state, roles, and emojis. Treat the final ready diagnostics—not only the gateway connection line—as the startup verification point.