---
name: Persistent interactive state
description: Restart-safe design for Discord buttons that collect registrations.
---

Interactive Discord flows that collect participants need both durable rows and stable, resource-specific custom IDs. On cog loading, query open records and re-register each view with its original message ID; do not rely on the View object's in-memory lists.

**Why:** Persistent views can receive new interactions after a restart, but an in-memory participant list cannot reconstruct who already joined and a shared button ID can route unrelated campaigns together.

**How to apply:** Create the campaign record before publishing its message, update the message ID after sending, use idempotent entry inserts, transition the campaign status when it starts or completes, and restore only open records.