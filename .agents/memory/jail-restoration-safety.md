---
name: Jail restoration safety
description: Preserve jail records until Discord role and private-channel restoration has completed successfully.
---

Jail state must remain recoverable while an unjail operation is restoring Discord state. Read the record first, perform role and channel restoration, and delete the record only after those operations succeed.

**Why:** Discord API failures can occur after the database read. Deleting the record first makes a transient permission or network failure lose the member's saved roles and private jail channel reference.

**How to apply:** Any future unjail, recovery, or restart-resume flow should treat the SQLite jail row as the source of truth until restoration is complete.