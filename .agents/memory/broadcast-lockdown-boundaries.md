---
name: Broadcast and lockdown boundaries
description: Durable safety decisions for live Discord broadcasts and emergency lockdowns.
---

Administrative channels are protected by a server-side name/category policy during emergency lockdowns; the browser never supplies an arbitrary exclusion list. Broadcast history stores the text and embed description separately so reuse restores the original editor state.

**Why:** A client-controlled exclusion list could leave public channels writable during an incident, while collapsing embed fields into one history value makes reuse lossy.

**How to apply:** Keep lockdown exemptions derived from the Discord guild and expose the derived protected list to the dashboard for transparency. Preserve separate broadcast fields whenever the editor gains new reusable content.