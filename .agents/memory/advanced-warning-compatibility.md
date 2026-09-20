---
name: Advanced warning compatibility
description: How the Step 4 warning records coexist with the legacy moderation warnings table and commands.
---

The legacy `warnings` table and helper signatures are already used by Auto-Mod, moderation, dashboard code, and tests. Step 4 must keep those APIs unchanged and use the separate `member_warnings` table for advanced administrative records. The existing manual warning command mirrors successful warnings into the additive table.

**Why:** The old warning helper uses the opposite positional argument order from the new administrative design and returns a per-member count. Replacing it would silently break existing moderation behavior and tests.

**How to apply:** Use `add_member_warning`, `get_member_warnings`, `delete_member_warning`, and `clear_member_warnings` for Step 4 flows. Keep legacy `add_warning`, `get_warnings`, and `delete_warning` unchanged; do not register a second `warn` or `warnings` Slash command.