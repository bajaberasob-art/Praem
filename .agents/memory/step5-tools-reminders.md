---
name: Step 5 tools and reminders
description: Durable conventions for the member-tools command family and its restart-safe reminders.
---

The Step 5 reminder flow uses a dedicated `user_reminders` table and does not replace the legacy `reminders` contract used by the community cog. The tools cog owns its delivery loop, retries through DM when channel delivery fails, and deletes rows only after successful delivery.

**Why:** The project already had a live reminder API and background worker; changing that contract during the tools expansion would risk losing existing reminders or breaking compatibility.

**How to apply:** Add future Step 5 reminder changes through `add_reminder`, `get_due_user_reminders`, and `delete_reminder`. Keep new member/channel tools under `ToolsChannelsCog` and route their command policy and audit behavior through the existing policy/cache and Analytics contracts.