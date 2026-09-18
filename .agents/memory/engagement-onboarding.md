---
name: Engagement onboarding rules
description: Durable constraints for invite attribution, onboarding templates, and persistent Discord UI panels.
---

Invite attribution must compare usage snapshots while serializing member-join reads; reconnect refreshes are baselines, not invite events. Persist panel message IDs and re-register timeout-free views after each ready event.

**Why:** Discord invite usage and component dispatch state are both process-local, while joins and reconnects can happen concurrently or after a restart.

**How to apply:** Keep invite statistics in durable storage, refresh the cache on ready/create/delete, and restore role/rules views by message ID before relying on interactions.

Dashboard onboarding settings and self-role panel deployment share the guild settings revision; successful panel deployment must update the dashboard's local panel list immediately, while a fresh onboarding read remains the source of truth after reload.

**Why:** The deployment response is the only reliable way to show the operator the newly created Discord message before the next read, while revisioned settings prevent stale dashboard sessions from overwriting onboarding changes.

**How to apply:** Send onboarding mutations with the current revision, rebase on conflicts, and refresh or patch the self-role panel collection after every successful deployment.