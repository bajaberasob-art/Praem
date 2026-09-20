---
name: Dashboard local port split
description: Development-only separation between the Vite dashboard preview and the Python dashboard service.
---

The Replit development workspace runs the Vite PRIME dashboard on 8099, so the Python dashboard and its API proxy use 8098 locally. Koyeb production remains single-process and uses the injected `PORT`.

**Why:** Both services previously attempted to bind 8099, causing the bot to retry startup, leak client sessions, and leave the Python health probe unavailable even though the Vite preview was responding.

**How to apply:** Preserve the local `DASHBOARD_PORT=8098` split when running the multi-workflow Replit workspace. Do not carry that fallback into Koyeb; production `PORT` must remain authoritative.