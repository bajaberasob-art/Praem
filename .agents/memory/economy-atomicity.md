---
name: Economy atomicity
description: Durable rules for preventing duplicate rewards, lost XP, and inconsistent wallet transfers.
---

All economy mutations that depend on a prior balance or timestamp must be performed by one SQLite transaction, not by separate read and write calls.

**Why:** concurrent Discord interactions can otherwise both observe the same account state, double-claim a daily reward, lose XP increments, or split a wallet transfer after only one leg commits.

**How to apply:** use an atomic database operation for new economy commands; do not reintroduce command-level read-then-update sequences for balances, XP, or daily claims.

Scaled daily rewards must calculate and claim inside the same transaction that checks the daily timestamp. Live leaderboard configuration belongs in guild settings, while the message ID is replaced only after a successful send or edit.

**Why:** the reward formula depends on the current level, and a deleted leaderboard message must be recoverable without losing the configured target.

**How to apply:** keep reward inputs and claim eligibility in one database operation; treat leaderboard refresh as an idempotent control-plane update.