---
name: Durable background jobs
description: The persistence and restart-safety rule for delayed Discord actions.
---

Delayed Discord actions that must survive a bot restart should be represented by a database row with an explicit due time and lifecycle status. A short polling worker can claim and complete due rows, with a DM fallback when the original channel is unavailable.

**Why:** Command-local `asyncio.sleep` tasks disappear during reconnects or process restarts, while Discord interactions and channels may also be unavailable when a delayed action becomes due.

**How to apply:** Use UTC timestamps, idempotent status transitions, bounded batches, and only mark a row complete after delivery succeeds. Add cancellation and list operations where users need control.