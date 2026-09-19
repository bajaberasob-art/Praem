---
name: SQLite table rebuilds with dependent views
description: Safe migration pattern for rebuilding SQLite tables that have canonical views.
---

When rebuilding a SQLite table to replace a table-level uniqueness constraint, drop dependent views before renaming the staging table, then recreate them after the swap.

**Why:** SQLite updates dependent view SQL during `ALTER TABLE ... RENAME`, which can leave a canonical view pointing at the staging table name after the staging table is renamed.

**How to apply:** Detect and temporarily drop the view inside the same migration transaction, preserve all rows and IDs in the staging table, rename it to the canonical table name, and let the normal schema pass recreate the view.

For migrations that copy rows with `INSERT ... SELECT`, use SQLite-compatible conflict syntax such as `INSERT OR IGNORE` when the statement does not need an update arm.

**Why:** Some SQLite builds parse `ON CONFLICT ... DO NOTHING` after a `SELECT` as a syntax error near `DO`, even though the equivalent insert behavior is supported.

**How to apply:** Prefer the simpler conflict form for additive backfills and reserve `ON CONFLICT DO UPDATE` for statements that actually need to replace existing values.