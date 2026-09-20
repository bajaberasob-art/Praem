---
name: Sanctions and voice command ownership
description: Durable ownership and persistence rules for the sanctions and voice execution engine.
---

The sanctions/voice engine must remain additive. Existing `timeout` and `untimeout` Slash commands stay registered in the moderation cog; the sanctions/voice cog must not register duplicate names. New timed-ban, voice-ban, and text-mute state belongs in isolated SQLite tables and must be resumed or enforced by background/listener logic after reconnects.

**Why:** Discord rejects duplicate application-command registrations, while sanctions must survive a process restart rather than living only in memory.

**How to apply:** When adding a sanctions or voice command, first check the loaded command tree and command metadata. Reuse the canonical command-policy check and analytics categories (`log_sanctions` or `log_voice`), and keep durable state changes behind async database helpers.