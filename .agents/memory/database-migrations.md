---
name: SQLite table rebuilds with dependent views
description: Safe migration pattern for rebuilding SQLite tables that have canonical views.
---

When rebuilding a SQLite table to replace a table-level uniqueness constraint, drop dependent views before renaming the staging table, then recreate them after the swap.

**Why:** SQLite updates dependent view SQL during `ALTER TABLE ... RENAME`, which can leave a canonical view pointing at the staging table name after the staging table is renamed.

**How to apply:** Detect and temporarily drop the view inside the same migration transaction, preserve all rows and IDs in the staging table, rename it to the canonical table name, and let the normal schema pass recreate the view.