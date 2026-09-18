---
name: Dashboard public routing
description: The dashboard's public URL and OAuth callback depend on the workspace artifact router.
---

The bot dashboard is served by the Python process on its own port, while the
public Replit domain is routed through the API artifact. The stable development
entry point is therefore the API artifact prefix followed by the dashboard
path, not the bare domain or the Python port.

**Why:** A bare development-domain request can reach a different artifact or
return a router 404 even when the dashboard service is healthy on localhost.

**How to apply:** Keep the API service proxy and the dashboard's relative URLs
in sync. Register the exact public callback path in Discord OAuth2 Redirects,
and update it if the project's public domain changes after publishing.

The dashboard's OAuth `CLIENT_SECRET` is separate from the bot token, public
key, and application ID. Token exchange failures should point operators to
OAuth2 → General and avoid exposing provider error details or secrets.

**Why:** Discord can complete the authorization redirect and still reject the
token exchange when the client secret is the wrong credential.

**How to apply:** Store the client secret only as a Replit Secret and restart
the bot after replacing it so the process reloads the value.

After OAuth succeeds, redirect the callback to the mounted dashboard base path
rather than `/`; otherwise the public artifact router returns a 404 even though
authentication completed.

**Why:** The Python dashboard is mounted behind the API artifact prefix, so its
root path is not the public domain root.

**How to apply:** Keep the mounted base path configurable and use it for both
successful login and logout redirects.