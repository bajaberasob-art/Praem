---
name: Discord emoji tokens
description: The distinction between custom guild emojis and stickers when displaying and sending quick replies.
---

Custom Discord emojis and stickers are different asset types. A quick-response editor can preview a custom emoji with its CDN URL, but the saved reply must contain Discord's serialized token (`<:name:id>` or `<a:name:id>`) so Discord renders it in a message.

**Why:** A CDN image URL only displays an image in the dashboard; it does not make the bot's sent message render the guild emoji.

**How to apply:** Load `guild.emojis` separately from `guild.stickers`, expose both metadata sets to the dashboard, and insert `str(emoji)` into canned-response text. Treat missing or unavailable assets as a safe empty state.