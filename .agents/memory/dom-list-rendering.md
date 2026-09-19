---
name: DOM list rendering
description: Preventing accidental stringification when rendering mapped DOM nodes in the dashboard.
---

When a renderer creates DOM nodes with `map`, pass them to `replaceChildren` as separate arguments (`replaceChildren(...nodes)`), or append them in a loop. Passing the array itself as one argument causes the browser to stringify the nodes and visibly render values such as `[object HTMLButtonElement]`.

**Why:** The dashboard's member and emoji pickers use DOM helpers rather than HTML strings, so the bug is easy to miss in code review while producing a literal object string in the UI.

**How to apply:** Check every `replaceChildren` call that receives a mapped array, especially picker/list renderers. Keep selection state and hidden form values updated in the node click handler after the rendering fix.