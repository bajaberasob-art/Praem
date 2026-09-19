---
name: Discord emoji tokens
description: The distinction between custom guild emojis and stickers when displaying and sending quick replies.
---

Custom Discord emojis and stickers are different asset types. A quick-response editor can preview a custom emoji with its CDN URL, but the saved reply must contain Discord's serialized token (`<:name:id>` or `<a:name:id>`) so Discord renders it in a message.

**Why:** A CDN image URL only displays an image in the dashboard; it does not make the bot's sent message render the guild emoji.

**How to apply:** Load `guild.emojis` separately from `guild.stickers`, expose both metadata sets to the dashboard, and insert `str(emoji)` into canned-response text. Treat missing or unavailable assets as a safe empty state.

The installed discord.py runtime may not parse serialized custom emoji strings correctly with `PartialEmoji.from_str`; when parsing user-provided reaction tokens, validate the `<:name:id>` / `<a:name:id>` shape explicitly and construct `PartialEmoji` from its fields.

**Why:** Relying on the convenience parser silently returned an emoji with no ID in this runtime, preventing valid custom reactions from being added.

**How to apply:** Use a strict regex for custom emoji tokens, reject malformed angle-bracket values, and still verify the parsed ID belongs to the current guild before saving.