---
name: Interaction runtime
description: Central Discord.py acknowledgement and callback safety contract.
---

The project uses a central runtime boundary for Discord interactions. Slash callbacks receive a follow-up-aware proxy after early acknowledgement; View and Modal dispatch is guarded centrally, with modal-opening callbacks kept on the immediate-response path because Discord cannot defer and then open a modal in the same interaction.

**Why:** The cogs were authored independently and many of them perform database or Discord API work before responding. Per-command fixes drift and direct response calls fail after an early defer.

**How to apply:** New Slash commands and UI callbacks should keep their normal response style; load them through the main bot so the runtime wrapper, global logging, and error delivery are installed. Do not create a second unguarded bot entrypoint.