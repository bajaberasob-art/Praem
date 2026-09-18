---
name: Ticket system architecture
description: Durable design rules for persistent Discord tickets, transcript storage, and staff KPI calculations.
---

Ticket panels and ticket controls use persistent custom IDs, while ticket records, transcripts, and ratings live in SQLite.

**Why:** Discord reconnects discard in-memory View instances, but open ticket channels and rating outcomes must remain traceable across restarts.

**How to apply:** Register saved panel views during extension setup, keep channel ownership and support-role IDs on each ticket record, and scope every database mutation by guild and ticket ID.

Response time starts at ticket creation and ends at the first verified support-staff message; resolution time ends at the close action. Ratings attach to the closing staff member.

**Why:** These timestamps map directly to support KPIs and avoid counting the ticket owner's messages as staff response.

**How to apply:** Record the first staff message once, preserve null response times for unanswered tickets, and calculate averages with null-safe SQL.