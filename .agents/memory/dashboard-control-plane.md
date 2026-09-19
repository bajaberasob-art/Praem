---
name: Live dashboard control plane
description: Durable constraints for connecting the Discord runtime, dashboard APIs, and existing SQLite state.
---

Dashboard telemetry and operator actions are part of the same control plane as the Discord bot. The dashboard must reuse the `EnterpriseBot`-owned HTTP session in production, and its stats/actions contracts must read existing state without replacing live tables or inventing disconnected controls.

**Why:** The bot and dashboard share one lifecycle, while the SQLite file contains live data under legacy table names. Separate HTTP sessions and destructive schema rewrites create restart, authorization, and data-loss risks.

**How to apply:** Keep browser URLs relative to the proxied dashboard path, perform live guild authorization on every read/write, use additive migrations or compatibility views for canonical contracts, and expose a UI action only when its server-side implementation and audit path already exist.