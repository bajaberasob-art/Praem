---
name: Economy atomicity
description: Durable rules for preventing duplicate rewards, lost XP, and inconsistent wallet transfers.
---

All economy mutations that depend on a prior balance or timestamp must be performed by one SQLite transaction, not by separate read and write calls.

**Why:** concurrent Discord interactions can otherwise both observe the same account state, double-claim a daily reward, lose XP increments, or split a wallet transfer after only one leg commits.

**How to apply:** use an atomic database operation for new economy commands; do not reintroduce command-level read-then-update sequences for balances, XP, or daily claims.