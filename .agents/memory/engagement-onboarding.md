---
name: Engagement onboarding rules
description: Durable constraints for invite attribution, onboarding templates, and persistent Discord UI panels.
---

Invite attribution must compare usage snapshots while serializing member-join reads; reconnect refreshes are baselines, not invite events. Persist panel message IDs and re-register timeout-free views after each ready event.

**Why:** Discord invite usage and component dispatch state are both process-local, while joins and reconnects can happen concurrently or after a restart.

**How to apply:** Keep invite statistics in durable storage, refresh the cache on ready/create/delete, and restore role/rules views by message ID before relying on interactions.