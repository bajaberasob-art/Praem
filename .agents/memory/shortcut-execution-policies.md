---
name: Shortcut execution policies
description: Rules for safely executing dashboard-created command shortcuts inside Discord.
---

Dashboard-created shortcuts are synthetic message-driven invocations, not native Discord command dispatches. They must explicitly pass through the normal Prefix or Slash command policy checks before invoking a callback; otherwise disabled commands and role/channel restrictions can be bypassed.

**Why:** Directly calling a Slash callback or invoking a Prefix command from a shortcut bypasses Discord's normal dispatch pipeline, so global checks and guild command policies are not guaranteed to run.

**How to apply:** When adding or changing shortcut execution, construct an interaction/context that identifies the real target command, run the corresponding policy interceptor first, and keep legacy help-only shortcuts separate from executable command shortcuts.