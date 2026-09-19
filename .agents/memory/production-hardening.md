---
name: Production hardening
description: Non-obvious constraints for PWA delivery, health monitoring, API protection, and SQLite performance.
---

PWA assets and service-worker registration must use paths relative to the dashboard mount, while health probes remain public and separate from authenticated dashboard APIs.

**Why:** The Python dashboard is mounted behind an artifact path in the public router; root-absolute browser URLs can escape that mount. External uptime monitors also cannot authenticate, so probes must not depend on a dashboard session.

**How to apply:** Keep manifest, service worker, icon, stylesheet, and script references relative to the dashboard page. Keep `/healthz` and `/api/status` read-only and unauthenticated, and avoid caching API responses.

SQLite performance changes are additive connection pragmas: WAL, `synchronous=NORMAL`, a bounded negative cache size, and a 20-second busy timeout. Passive checkpoints must run in a cancellable background task.

**Why:** The bot has many short-lived SQLite connections and must tolerate concurrent dashboard and Discord writes without table replacement or data reset.

**How to apply:** Configure every connection consistently, checkpoint passively, cancel the worker during bot shutdown, and never use WAL tuning as a reason to drop, rebuild, or clear existing tables.