---
name: Gaming operations architecture
description: Persistent scrim lobbies use SQLite reservations and Discord message views, with dashboard writes delegated through the Gaming cog.
---

Scrim operations are additive to tournaments: configurations and registrations are stored separately, slot allocation uses an immediate SQLite transaction, and the Discord board is restored from its stored message ID after bot startup.

**Why:** Gaming lobbies must survive restarts without changing the existing tournament or ticket contracts.

**How to apply:** Keep future scrim features on the scrim tables and Gaming cog; use the dashboard only as an authorized control plane that calls the cog for Discord mutations.