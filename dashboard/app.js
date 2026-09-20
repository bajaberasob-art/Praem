(() => {
  "use strict";
  // DOM helpers
  const $ = (s, p = document) => p.querySelector(s);
  const el = (tag, props = {}, ...children) => {
    const n = document.createElement(tag);
    Object.entries(props).forEach(([k, v]) => {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2).toLowerCase(), v);
      else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
    });
    children
      .flat()
      .forEach((c) =>
        n.append(c instanceof Node ? c : document.createTextNode(c)),
      );
    return n;
  };
  // State
  const state = {
    session: null,
    guild: null,
    meta: null,
    incidents: [],
    actions: [],
    stats: null,
    whitelist: [],
    lockdown: false,
    incidentTimer: null,
    baseline: null,
    draft: null,
    revision: null,
    updated: null,
    onboarding: null,
    commandStudio: { commands: [], roles: [], channels: [], shortcuts: [] },
    commandRegistry: { categories: [], commands: [], policies: {}, byKey: {} },
    autoResponses: [],
    autoResponderMeta: { roles: [], emojis: [], members: [] },
    commandSearch: "",
    commandCogFilter: "all",
    commandStatusFilter: "all",
    commandRoleFilter: "all",
    commandTab: "commands",
    commandCollapsedGroups: {},
    selectedCommandIds: [],
    commandSimulatorText: "",
    commandDetail: null,
    shortcutCommandId: "",
    shortcutInputText: null,
    tickets: {
      active: [],
      archive: [],
      kpis: [],
      canned: [],
    },
    gaming: [],
    economy: { wealth: [], levels: [], settings: null, multipliers: {} },
    logRouting: { channels: {} },
    ticketSearch: "",
    ticketStatusFilter: "all",
    ticketCategories: [
      { key: "general", label: "شكاوى عامة", emoji: "📣", support_role_ids: [], senior_role_ids: [] },
      { key: "questions", label: "استفسارات", emoji: "❓", support_role_ids: [], senior_role_ids: [] },
      { key: "billing", label: "دعم الشحن", emoji: "💳", support_role_ids: [], senior_role_ids: [] },
      { key: "tournaments", label: "بطولات", emoji: "🏆", support_role_ids: [], senior_role_ids: [] },
    ],
    selfRoleBuilder: null,
    onboardingPreviewTimer: null,
    fields: {},
    saving: false,
    online: navigator.onLine,
    failures: 0,
    source: null,
    newer: false,
    activeView: sessionStorage.getItem("dashboard-view") || "overview",
    drawerOpen: false,
  };
  let deferredInstallPrompt = null;
  let installBanner = null;

  function mobileInstallContext() {
    const standalone = window.matchMedia?.("(display-mode: standalone)")?.matches
      || window.navigator.standalone === true;
    const mobile = window.matchMedia?.("(max-width: 768px)")?.matches
      || /Android|iPhone|iPad|iPod/i.test(window.navigator.userAgent || "");
    return mobile && !standalone;
  }

  function showInstallBanner() {
    if (!deferredInstallPrompt || !mobileInstallContext() || installBanner) return;
    installBanner = el(
      "aside",
      { class: "pwa-install-pill", id: "pwa-install-banner", role: "status" },
      el("span", { text: "📲 تثبيت التطبيق على هاتفك" }),
      el("button", {
        class: "pwa-install-action",
        type: "button",
        text: "تثبيت",
        onClick: async () => {
          const prompt = deferredInstallPrompt;
          deferredInstallPrompt = null;
          installBanner?.remove();
          installBanner = null;
          if (!prompt) return;
          await prompt.prompt();
          await prompt.userChoice.catch(() => null);
        },
      }),
      el("button", {
        class: "pwa-install-dismiss",
        type: "button",
        "aria-label": "إخفاء رسالة التثبيت",
        text: "×",
        onClick: () => {
          installBanner?.remove();
          installBanner = null;
        },
      }),
    );
    document.body.append(installBanner);
  }

  function setupPwa() {
    if ("serviceWorker" in navigator) {
      navigator.serviceWorker.register("sw.js", { scope: "./" }).catch(() => {
        // The dashboard remains fully functional when a browser blocks SWs.
      });
    }
    addEventListener("beforeinstallprompt", (event) => {
      event.preventDefault();
      deferredInstallPrompt = event;
      showInstallBanner();
    });
    addEventListener("appinstalled", () => {
      deferredInstallPrompt = null;
      installBanner?.remove();
      installBanner = null;
    });
  }
  const keys = [
    "prefix",
    "anti_nuke",
    "anti_alt_days",
    "captcha_enabled",
    "captcha_role_id",
    "auto_role_id",
    "leave_channel_id",
    "member_auto_role_id",
    "bot_auto_role_id",
    "verified_role_id",
    "unverified_role_id",
    "rules_channel_id",
    "welcome_dm_enabled",
    "welcome_channel_id",
    "leave_channel_id",
    "welcome_message",
    "leave_message",
    "welcome_embed_enabled",
    "welcome_embed_color",
    "welcome_embed_title",
    "welcome_embed_description",
    "welcome_embed_image_url",
    "welcome_embed_sticker_id",
    "welcome_embed_footer",
    "welcome_embed_show_avatar",
    "log_channel_id",
    "anti_spam_enabled",
    "anti_link_enabled",
    "anti_invites",
    "anti_links",
    "anti_spam",
    "anti_mass_mention",
    "banned_words_list",
    "economy_tax",
    "daily_amount",
  ];
  const onboardingKeys = [
    "welcome_channel_id",
    "welcome_message",
    "leave_message",
    "welcome_dm_enabled",
    "welcome_embed_enabled",
    "welcome_embed_color",
    "welcome_embed_title",
    "welcome_embed_description",
    "welcome_embed_image_url",
    "welcome_embed_sticker_id",
    "welcome_embed_footer",
    "welcome_embed_show_avatar",
    "auto_role_id",
    "member_auto_role_id",
    "bot_auto_role_id",
    "verified_role_id",
    "unverified_role_id",
    "rules_channel_id",
  ];
  const settingsKeys = keys.filter((key) => !onboardingKeys.includes(key));
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const sameValue = (a, b) =>
    a === b ||
    (a != null &&
      b != null &&
      typeof a === "object" &&
      typeof b === "object" &&
      JSON.stringify(a) === JSON.stringify(b));
  const changes = () =>
    !state.baseline || !state.draft
      ? {}
      : Object.fromEntries(
          settingsKeys
            .filter((k) => !sameValue(state.baseline[k], state.draft[k]))
            .map((k) => [k, state.draft[k]]),
        );
  const onboardingChanges = () =>
    !state.baseline || !state.draft
      ? {}
      : Object.fromEntries(
          onboardingKeys
            .filter((k) => !sameValue(state.baseline[k], state.draft[k]))
            .map((k) => [k, state.draft[k]]),
        );
  const dirty = () => Object.keys(changes()).length > 0;
  const onboardingDirty = () => Object.keys(onboardingChanges()).length > 0;
  // اعتماد نسخة أحدث من الخادم مع الإبقاء على تعديلات المستخدم فقط (لا على القيم القديمة غير المعدّلة)
  function adopt(snapshot, keepLocal = true) {
    const local = keepLocal ? { ...changes(), ...onboardingChanges() } : {};
    state.baseline = clone(snapshot.settings);
    state.revision = snapshot.revision;
    state.updated = snapshot.updated_at;
    state.draft = { ...clone(snapshot.settings), ...local };
    state.newer = keepLocal && Object.keys(local).length > 0;
  }
  const redirect = () => location.assign("login");
  const app = $("#app");
  // API and feedback
  function toast(message, type = "error", life = 4000) {
    const old = $(".toast");
    if (old) old.remove();
    const t = el("div", {
      class: `toast ${type}`,
      role: "status",
      text: message,
    });
    document.body.append(t);
    if (life) setTimeout(() => t.remove(), life);
  }
  async function api(url, opts = {}) {
    const r = await fetch(url, opts);
    if (r.status === 401) {
      redirect();
      throw Error("unauth");
    }
    return r;
  }
  async function refreshSession() {
    const r = await api("api/me", { cache: "no-store" });
    const data = await r.json();
    if (!data.auth || !data.session) return false;
    state.session = data.session;
    return true;
  }
  async function writeApi(url, body, retry = true) {
    const options = {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": state.session.csrf,
      },
      body: JSON.stringify(body),
    };
    let response = await api(url, options);
    if (response.status === 403 && retry) {
      let data = {};
      try {
        data = await response.clone().json();
      } catch (_) {
        data = {};
      }
      if (data.error === "csrf" && await refreshSession()) {
        options.headers["X-CSRF-Token"] = state.session.csrf;
        response = await api(url, options);
      }
    }
    return response;
  }
  // Shared components
  function avatar(src, name) {
    const a = el("div", { class: "avatar" });
    if (src) {
      const im = el("img", { src, alt: "" });
      im.onerror = () => {
        im.remove();
        a.textContent = (name || "?").slice(0, 1);
      };
      a.append(im);
    } else a.textContent = (name || "?").slice(0, 1);
    return a;
  }
  function guildIcon(g) {
    const i = el("span", { class: "guild-icon" });
    if (g.icon) {
      const im = el("img", { src: g.icon, alt: "" });
      im.onerror = () => {
        im.remove();
        i.textContent = g.name.slice(0, 1);
      };
      i.append(im);
    } else i.textContent = g.name.slice(0, 1);
    return i;
  }
  function header() {
    const h = el("header", { class: "topbar" }),
      inr = el("div", { class: "topbar-inner" });
    inr.append(
      el(
        "button",
        {
          class: "menu-toggle",
          type: "button",
          "aria-label": "فتح قائمة الأقسام",
          "aria-expanded": String(state.drawerOpen),
          onClick: () => toggleDrawer(),
        },
        el("span", { text: "☰" }),
      ),
      el(
        "div",
        { class: "brand" },
        el("strong", { text: "PRIME | TEAM" }),
        el("i", { text: "تطوير abood2026" }),
      ),
      el("div", { class: "head-grow" }),
    );
    const picker = el("div", { class: "server-picker" }),
      btn = el("button", {
        class: "picker-button",
        "aria-expanded": "false",
        type: "button",
      });
    const setBtn = () => {
      btn.replaceChildren(
        el(
          "span",
          { class: "guild-value" },
          guildIcon(state.guild),
          el("span", { class: "ell", text: state.guild.name }),
        ),
        el("span", { text: "⌄" }),
      );
    };
    setBtn();
    const menu = el("div", { class: "popover", hidden: true });
    state.session.guilds.forEach((g) => {
      const o = el(
        "button",
        { class: "option", type: "button", onClick: () => chooseGuild(g.id) },
        guildIcon(g),
        el("span", { class: "ell", text: g.name }),
      );
      menu.append(o);
    });
    btn.onclick = () => {
      const open = menu.hidden;
      menu.hidden = !open;
      btn.setAttribute("aria-expanded", String(open));
    };
    picker.append(btn, menu);
    const ping = el("div", { class: "ping", id: "ping" });
    inr.append(
      picker,
      ping,
      el(
        "div",
        { class: "user" },
        avatar(state.session.avatar, state.session.username),
        el("span", { text: state.session.username }),
        el("a", { class: "logout", href: "logout", text: "خروج" }),
      ),
    );
    h.append(inr);
    return h;
  }
  const viewLabels = {
    overview: { label: "نظرة عامة", icon: "⌂", hint: "مركز القيادة" },
    tickets: { label: "التذاكر", icon: "▣", hint: "Help Desk" },
    gaming: { label: "السكريمات", icon: "🎮", hint: "Gaming Ops" },
    commands: { label: "الأوامر والأتمتة", icon: "⌘", hint: "Commands" },
    onboarding: { label: "الترحيب والأدوار", icon: "✦", hint: "Onboarding" },
    security: { label: "الحماية", icon: "◈", hint: "Security" },
    moderation: { label: "المراقبة", icon: "⚔", hint: "Moderation" },
    analytics: { label: "السجلات", icon: "◉", hint: "Analytics" },
    economy: { label: "الاقتصاد", icon: "◌", hint: "Economy" },
    community: { label: "المجتمع", icon: "◎", hint: "Community" },
    ai: { label: "الذكاء الاصطناعي", icon: "✧", hint: "AI Tools" },
    settings: { label: "الإعدادات", icon: "⚙", hint: "Configuration" },
    system: { label: "النظام", icon: "⌁", hint: "Runtime" },
  };
  function navigateView(view) {
    if (!viewLabels[view]) return;
    state.activeView = view;
    state.drawerOpen = false;
    sessionStorage.setItem("dashboard-view", view);
    document.querySelectorAll(".mobile-more-menu").forEach((menu) => {
      menu.hidden = true;
      menu.parentElement?.querySelector('[aria-expanded="true"]')?.setAttribute("aria-expanded", "false");
    });
    document.querySelectorAll("[data-nav-view]").forEach((item) => {
      item.classList.toggle("active", item.dataset.navView === view);
      item.setAttribute("aria-current", item.dataset.navView === view ? "page" : "false");
    });
    renderPage();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function toggleDrawer(force = null) {
    state.drawerOpen = force == null ? !state.drawerOpen : Boolean(force);
    $(".workspace-nav")?.classList.toggle("drawer-open", state.drawerOpen);
    $(".drawer-scrim")?.classList.toggle("show", state.drawerOpen);
    document.body.classList.toggle("drawer-visible", state.drawerOpen);
    $(".menu-toggle")?.setAttribute("aria-expanded", String(state.drawerOpen));
    navigator.vibrate?.(12);
  }
  function openCommandPalette() {
    $(".command-palette-back")?.remove();
    const back = el("div", { class: "command-palette-back", role: "dialog", "aria-modal": "true" });
    const input = el("input", {
      class: "command-palette-input",
      type: "search",
      placeholder: "ابحث في أقسام مركز القيادة…",
      "aria-label": "بحث الأقسام",
    });
    const list = el("div", { class: "command-palette-list" });
    const renderMatches = () => {
      const query = input.value.trim().toLocaleLowerCase();
      list.replaceChildren(
        ...Object.entries(viewLabels)
          .filter(([, meta]) => !query || `${meta.label} ${meta.hint}`.toLocaleLowerCase().includes(query))
          .map(([view, meta]) => el(
            "button",
            {
              class: "command-palette-item",
              type: "button",
              onClick: () => {
                back.remove();
                navigateView(view);
              },
            },
            el("span", { class: "nav-icon", text: meta.icon }),
            el("span", {}, el("strong", { text: meta.label }), el("small", { text: meta.hint })),
          )),
      );
    };
    input.addEventListener("input", renderMatches);
    back.append(
      el(
        "div",
        { class: "command-palette", onClick: (event) => event.stopPropagation() },
        el("div", { class: "command-palette-head" }, el("strong", { text: "التنقل السريع" }), el("kbd", { text: "ESC" })),
        input,
        list,
      ),
    );
    back.addEventListener("click", () => back.remove());
    document.body.append(back);
    renderMatches();
    input.focus();
  }
  function navButton(view) {
    const meta = viewLabels[view];
    return el(
      "button",
      {
        class: `nav-item ${state.activeView === view ? "active" : ""}`,
        type: "button",
        "data-nav-view": view,
        "aria-current": state.activeView === view ? "page" : "false",
        onClick: () => navigateView(view),
      },
      el("span", { class: "nav-icon", text: meta.icon, "aria-hidden": "true" }),
      el("span", { class: "nav-copy" }, el("b", { text: meta.label }), el("small", { text: meta.hint })),
    );
  }
  function workspaceNav() {
    return el(
      "aside",
      { class: `workspace-nav ${state.drawerOpen ? "drawer-open" : ""}`, "aria-label": "التنقل الرئيسي" },
      el(
        "div",
        { class: "workspace-nav-head" },
        el("span", { class: "workspace-kicker", text: "PRIME / CONTROL" }),
        el("strong", { text: "مركز القيادة" }),
        el("small", { text: "إدارة البوت من مكان واحد" }),
      ),
      el(
        "nav",
        { class: "nav-list" },
        ...Object.keys(viewLabels).map((view) => navButton(view)),
      ),
      el(
        "div",
        { class: "workspace-nav-foot" },
        el("span", { class: "nav-status-dot" }),
        el("span", { text: state.online ? "الخدمات تعمل بشكل طبيعي" : "الاتصال يحتاج مراجعة" }),
      ),
    );
  }
  function mobileNav() {
    const primary = ["overview", "tickets", "commands"];
    const moreMenu = el(
      "div",
      { class: "mobile-more-menu", hidden: true },
      navButton("onboarding"),
      navButton("gaming"),
      navButton("security"),
      navButton("moderation"),
      navButton("analytics"),
      navButton("economy"),
      navButton("community"),
      navButton("ai"),
      navButton("settings"),
      navButton("system"),
    );
    const moreButton = el(
      "button",
      {
         class: `nav-item ${["onboarding", "gaming", "security", "moderation", "analytics", "economy", "community", "ai", "settings", "system"].includes(state.activeView) ? "active" : ""}`,
        type: "button",
        "aria-expanded": "false",
        onClick: () => {
          const open = moreMenu.hidden;
          moreMenu.hidden = !open;
          moreButton.setAttribute("aria-expanded", String(open));
        },
      },
      el("span", { class: "nav-icon", text: "•••", "aria-hidden": "true" }),
      el("span", { class: "nav-copy" }, el("b", { text: "المزيد" }), el("small", { text: "إدارة" })),
    );
    return el(
      "div",
      { class: "mobile-nav-wrap" },
      moreMenu,
      el("nav", { class: "mobile-nav", "aria-label": "التنقل السريع" }, ...primary.map((view) => navButton(view)), moreButton),
    );
  }
  function updatePing(kind = "online", latency = null) {
    const p = $("#ping");
    if (!p) return;
    p.replaceChildren(
      el("span", {
        class: `dot ${kind === "online" ? "" : kind === "wait" ? "wait" : "off"}`,
      }),
      document.createTextNode(
        kind === "online"
          ? `متصل ${latency == null ? "—" : latency + "ms"}`
          : kind === "wait"
            ? "إعادة الاتصال..."
            : "غير متصل",
      ),
    );
  }
  function renderShell() {
    const main = el(
      "main",
      { class: "page", id: "main" },
      el(
        "div",
        { class: "loading" },
        el("div", { class: "skeleton" }),
        el("p", { text: "جارٍ تحميل إعدادات السيرفر…" }),
      ),
    );
    app.replaceChildren(
      header(),
      el("div", { class: "workspace-layout" }, workspaceNav(), main),
      el("button", {
        class: "drawer-scrim",
        type: "button",
        "aria-label": "إغلاق قائمة الأقسام",
        onClick: () => toggleDrawer(false),
      }),
      mobileNav(),
    );
    updatePing(state.online ? "online" : "offline");
  }
  // Form components
  function field(label, node, key, hint = "") {
    const f = el("div", { class: "field" }),
      target = node.id || node.querySelector?.("[id]")?.id;
    f.append(el("label", { for: target, text: label }), node);
    if (hint) f.append(el("div", { class: "hint", text: hint }));
    f.append(el("div", { class: "field-error", id: `err-${key}` }));
    return f;
  }
  function input(key, label, type, attrs = {}) {
    const n = el("input", { id: `in-${key}`, type, ...attrs });
    n.value = state.draft[key] ?? "";
    n.addEventListener("input", () => {
      state.draft[key] =
        type === "number" ? (n.value === "" ? "" : Number(n.value)) : n.value;
      state.fields[key] = "";
      renderDynamic();
    });
    return field(label, n, key);
  }
  function toggle(key, label) {
    const b = el("button", {
      class: "switch",
      type: "button",
      role: "switch",
      "aria-label": label,
      "aria-checked": String(!!state.draft[key]),
    });
    b.append(el("b"));
    const go = () => {
      state.draft[key] = !state.draft[key];
      b.setAttribute("aria-checked", String(state.draft[key]));
      if (key === "welcome_embed_enabled") renderPage();
      else {
        renderDynamic();
        refreshEmbedPreview();
      }
    };
    b.onclick = go;
    b.onkeydown = (e) => {
      if (e.key === " " || e.key === "Enter") {
        e.preventDefault();
        go();
      }
    };
    return el("div", { class: "switch-row" }, el("label", { text: label }), b);
  }
  function selector(key, label, type) {
    const wrap = el("div", { class: "select-wrap" }),
      b = el("button", {
        class: "select-button",
        id: `in-${key}`,
        type: "button",
        "aria-expanded": "false",
      }),
      pop = el("div", { class: "popover", hidden: true }),
      search = el("input", {
        class: "search",
        type: "text",
        placeholder: "ابحث…",
        "aria-label": "بحث",
      }),
      list = el("div", { class: "options" });
    pop.append(search, list);
    wrap.append(b, pop);
    let choices =
        type === "channel"
          ? state.meta.channels
          : type === "sticker"
            ? state.meta.stickers || []
            : state.meta.roles,
      active = 0;
    const value = () => state.draft[key];
    const nameFor = (id) =>
      choices.find((x) => String(x.id) === String(id));
    function display() {
      const found = nameFor(value());
      let current;
      if (found)
        current = el(
          "span",
          { class: "choice" },
          type === "channel"
            ? el("span", { text: "#" })
            : type === "sticker"
              ? el("span", { text: "✦" })
              : el("span", {
                class: "role-dot",
                style: `background:${found.color || "#64748b"}`,
              }),
          el("span", { class: "ell", text: found.name }),
        );
      else if (value()) current = el("span", { text: `غير موجود: ${value()}` });
      else current = el("span", { class: "choice none", text: "بدون" });
      b.classList.toggle("invalid", !!value() && !found);
      b.replaceChildren(current, el("span", { text: "⌄" }));
      const err = $(`#err-${key}`);
      if (err)
        err.textContent =
          value() && !found
            ? "العنصر المحفوظ لم يعد موجوداً. اختر قيمة أخرى."
            : state.fields[key] || "";
    }
    function select(id) {
      state.draft[key] = id;
      state.fields[key] = "";
      pop.hidden = true;
      b.setAttribute("aria-expanded", "false");
      display();
      renderDynamic();
    }
    function build() {
      choices =
        type === "channel"
          ? state.meta.channels
          : type === "sticker"
            ? state.meta.stickers || []
            : state.meta.roles;
      const q = search.value.trim().toLowerCase();
      list.replaceChildren();
      const add = (x, txt, group) => {
        if (q && !x.name.toLowerCase().includes(q)) return;
        if (group) list.append(el("div", { class: "group", text: group }));
        const blocked = type === "role" && x.assignable === false;
        const o = el(
          "button",
          {
            class: blocked ? "option blocked" : "option",
            type: "button",
            disabled: blocked,
            title: blocked ? "أعلى من رتبة البوت أو رتبة مُدارة" : null,
            onClick: () => select(x.id),
          },
          type === "channel"
            ? el("span", { text: "#" })
            : type === "sticker"
              ? el("span", { text: "✦" })
              : el("span", {
                class: "role-dot",
                style: `background:${x.color || "#64748b"}`,
              }),
          el("span", { text: txt || x.name }),
          blocked ? el("small", { class: "hint", text: "غير متاحة للبوت" }) : [],
        );
        list.append(o);
      };
      const none = el("button", {
        class: "option none",
        type: "button",
        onClick: () => select(null),
        text: "بدون",
      });
      list.append(none);
      if (type === "channel") {
        let last;
        choices.forEach((x) => {
          const group = x.category || "قنوات أخرى";
          add(x, x.name, group !== last ? group : null);
          last = group;
        });
      } else choices.forEach((x) => add(x));
      if (list.children.length === 1)
        list.append(
          el("div", { class: "empty-row", text: "لا توجد نتائج مطابقة" }),
        );
      active = 0;
    }
    function open() {
      build();
      pop.hidden = false;
      b.setAttribute("aria-expanded", "true");
      search.focus();
    }
    function close() {
      pop.hidden = true;
      b.setAttribute("aria-expanded", "false");
    }
    b.onclick = () => (pop.hidden ? open() : close());
    search.oninput = build;
    pop.onkeydown = (e) => {
      const opts = [...list.querySelectorAll(".option")];
      if (e.key === "Escape") {
        close();
        b.focus();
      }
      if (["ArrowDown", "ArrowUp"].includes(e.key)) {
        e.preventDefault();
        active =
          (active + (e.key === "ArrowDown" ? 1 : -1) + opts.length) %
          opts.length;
        opts.forEach((x, i) => x.classList.toggle("active", i === active));
        opts[active]?.focus();
      }
      if (e.key === "Enter" && document.activeElement === search)
        opts[active]?.click();
    };
    display();
    return field(label, wrap, key);
  }
  function appendSafeMarkdown(parent, source) {
    const lines = String(source || "").split("\n");
    const tokenPattern = /(\*\*[^*\n]+\*\*|__[^_\n]+__|\*[^*\n]+\*|`[^`\n]+`)/g;
    lines.forEach((line, lineIndex) => {
      let cursor = 0;
      for (const match of line.matchAll(tokenPattern)) {
        const start = match.index || 0;
        if (start > cursor) parent.append(document.createTextNode(line.slice(cursor, start)));
        const token = match[0];
        const inner = token.slice(token.startsWith("`") ? 1 : 2, token.startsWith("`") ? -1 : -2);
        const tag = token.startsWith("`")
          ? "code"
          : token.startsWith("**") || token.startsWith("__")
            ? "strong"
            : "em";
        parent.append(el(tag, { text: inner }));
        cursor = start + token.length;
      }
      if (cursor < line.length) parent.append(document.createTextNode(line.slice(cursor)));
      if (lineIndex < lines.length - 1) parent.append(el("br"));
    });
  }
  function onboardingTemplate() {
    const guild = state.guild || {};
    return String(state.draft?.welcome_message || "")
      .replace(/\{user\}/g, "@عضو_جديد")
      .replace(/\{username\}/g, "عضو جديد")
      .replace(/\{server\}/g, guild.name || "السيرفر")
      .replace(/\{count\}/g, guild.members == null ? "1,284th" : `${Number(guild.members).toLocaleString("en-US")}th`)
      .replace(/\{inviter\}/g, "دعوة تجريبية");
  }
  function embedTemplate(template) {
    return String(template || "")
      .replace(/\{user\}/g, "@عضو_جديد")
      .replace(/\{username\}/g, "عضو جديد")
      .replace(/\{server\}/g, state.guild?.name || "السيرفر")
      .replace(/\{count\}/g, state.guild?.members == null ? "1,284" : Number(state.guild.members).toLocaleString("en-US"))
      .replace(/\{inviter\}/g, "دعوة تجريبية");
  }
  function normalizeEmbedColor(value) {
    return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? String(value) : "#7c3aed";
  }
  function welcomeEmbedPreview() {
    const draft = state.draft || {};
    const sticker = (state.meta?.stickers || []).find(
      (item) => String(item.id) === String(draft.welcome_embed_sticker_id),
    );
    const image = draft.welcome_embed_image_url || sticker?.url;
    const color = normalizeEmbedColor(draft.welcome_embed_color);
    const title = embedTemplate(draft.welcome_embed_title || "أهلاً بك في {server} ✨");
    const description = embedTemplate(
      draft.welcome_embed_description ||
        draft.welcome_message ||
        "يا هلا {user} في {server}! أنت العضو رقم {count}.",
    );
    const card = el(
      "div",
      { id: "welcome-embed-preview", class: "welcome-embed-preview", style: `--embed-accent:${color}` },
      el("div", { class: "embed-preview-author" },
        el("span", { class: "embed-avatar", text: "✦" }),
        el("strong", { text: "PRIME | TEAM" }),
        el("small", { text: "BOT" }),
      ),
      el("h3", { text: title }),
      el("p", { text: description }),
      el("div", { class: "embed-preview-stats" },
        el("span", { text: `العضو رقم  #${state.guild?.members || "1,284"}` }),
        el("span", { text: `${state.guild?.members || "1,284"} عضو` }),
      ),
    );
    if (draft.welcome_embed_show_avatar !== false) {
      card.append(el("div", { class: "embed-preview-member", text: "@عضو_جديد  •  عضو جديد" }));
    }
    if (image) {
      const imageNode = el("img", { class: "embed-preview-image", src: image, alt: "صورة المعاينة" });
      imageNode.onerror = () => imageNode.remove();
      card.append(imageNode);
    }
    if (draft.welcome_embed_footer || draft.welcome_embed_enabled) {
      card.append(el("small", { class: "embed-preview-footer", text: draft.welcome_embed_footer || "PRIME | TEAM" }));
    }
    return card;
  }
  function refreshEmbedPreview() {
    const current = $("#welcome-embed-preview");
    if (current) current.replaceWith(welcomeEmbedPreview());
  }
  function preview() {
    if (state.draft?.welcome_embed_enabled) {
      return el(
        "div",
        { id: "preview" },
        el("div", { class: "preview-title" }, el("span", { text: "معاينة Embed احترافية" }), el("small", { text: "تتحدث بعد كل تعديل" })),
        welcomeEmbedPreview(),
      );
    }
    const body = el("div", { class: "embed" });
    appendSafeMarkdown(body, onboardingTemplate() || "اكتب رسالة الترحيب لرؤية المعاينة.");
    return el(
      "div",
      { id: "preview" },
      el("div", { class: "preview-title" }, el("span", { text: "معاينة Discord مباشرة" }), el("small", { text: "تتحدث بعد كل تعديل" })),
      el(
        "div",
        { class: "discord" },
        el(
          "div",
          { class: "msg-head" },
          el("span", { class: "bot-face", text: "ب" }),
          el("b", { text: "البوت" }),
          el("span", { class: "bot-tag", text: "BOT" }),
          el("span", { class: "msg-time", text: "الآن" }),
        ),
        body,
      ),
    );
  }
  // Page rendering
  function card(title, content) {
    return el(
      "section",
      { class: "card" },
      el(
        "div",
        { class: "card-head" },
        el("h2", { text: title }),
        el("small", { text: "إعدادات مباشرة" }),
      ),
      content,
    );
  }
  function incidentBody() {
    const body = el("div", { class: "incident-list security-incidents" });
    if (!state.incidents.length) {
      body.append(
        el("div", {
          class: "empty-row",
          text: "لا توجد حوادث أمنية مسجلة مؤخراً",
        }),
      );
    } else {
      state.incidents
        .slice()
        .reverse()
        .forEach((incident) => {
          const date = new Date(incident.timestamp);
          const when = Number.isNaN(date.getTime())
            ? incident.timestamp
            : date.toLocaleString("ar", {
                dateStyle: "short",
                timeStyle: "short",
              });
          body.append(
            el(
              "article",
              { class: "incident-row" },
              el(
                "div",
                { class: "incident-row-head" },
                el("strong", { text: incident.action_type }),
                el("time", { dateTime: incident.timestamp, text: when }),
              ),
              el(
                "div",
                { class: "incident-row-meta" },
                el("span", {
                  text: `${incident.culprit_name} (${incident.culprit_id})`,
                }),
                el("span", { text: incident.mitigation_taken }),
              ),
            ),
          );
        });
    }
    return body;
  }
  function incidentsCard() {
    return el(
      "section",
      { class: "security-feed card" },
      el(
        "div",
        { class: "card-head" },
        el("h2", { text: "بث التهديدات الحي" }),
        el("small", { class: "feed-status", text: "LIVE / 50" }),
      ),
      el(
        "div",
        { class: "terminal-label" },
        el("span", { class: "terminal-dot" }),
        el("span", { text: "SECURITY EVENT STREAM" }),
      ),
      incidentBody(),
    );
  }
  function refreshIncidentBody() {
    const current = $(".security-incidents");
    if (current) current.replaceWith(incidentBody());
  }
  function antiAltTone(value) {
    if (value >= 14) return "critical";
    if (value >= 7) return "warning";
    return "safe";
  }
  function securityView() {
    const section = el("section", { id: "view-security", class: "security-view" });
    const lockButton = el("button", {
      class: "lockdown-trigger",
      type: "button",
      text: state.lockdown
        ? "إلغاء الإغلاق الطارئ"
        : "إغلاق السيرفر الفوري (Emergency Lockdown)",
      onClick: () => confirmLockdown(!state.lockdown),
    });
    const lockCard = el(
      "article",
      { class: `lockdown-card ${state.lockdown ? "is-locked" : ""}` },
      el(
        "div",
        { class: "tactical-heading" },
        el("span", { class: "tactical-kicker", text: "CRISIS CONTROL / 01" }),
        el("h2", { text: "بروتوكول العزل الطارئ" }),
        el("p", {
          text: state.lockdown
            ? "الإغلاق قيد التنفيذ عبر طابور القنوات العامة."
            : "أوقف الكتابة العامة فوراً عند الاشتباه بغارة أو تخريب منسق.",
        }),
      ),
      lockButton,
    );
    const current = Math.max(
      0,
      Math.min(30, Number(state.draft?.anti_alt_days) || 0),
    );
    const output = el("output", {
      class: `anti-alt-value ${antiAltTone(current)}`,
      text: `${current} يوم`,
      for: "anti-alt-range",
    });
    const range = el("input", {
      id: "anti-alt-range",
      class: `anti-alt-range ${antiAltTone(current)}`,
      type: "range",
      min: "0",
      max: "30",
      step: "1",
      value: String(current),
      "aria-label": "الحد الأدنى لعمر الحساب",
    });
    range.addEventListener("input", () => {
      const value = Number(range.value);
      state.draft.anti_alt_days = value;
      state.fields.anti_alt_days = "";
      output.className = `anti-alt-value ${antiAltTone(value)}`;
      output.textContent = `${value} يوم`;
      range.className = `anti-alt-range ${antiAltTone(value)}`;
      renderDynamic();
    });
    const sliderCard = el(
      "article",
      { class: "tactical-card anti-alt-card" },
      el(
        "div",
        { class: "tactical-heading compact" },
        el("span", { class: "tactical-kicker", text: "ACCOUNT AGE GATE / 02" }),
        el("h2", { text: "حد عمر الحساب" }),
        el("p", { text: "الحسابات الأحدث من الحد المحدد ستخضع للحماية." }),
      ),
      el("div", { class: "anti-alt-readout" }, output),
      range,
      el(
        "div",
        { class: "range-scale" },
        el("span", { text: "0" }),
        el("span", { text: "7" }),
        el("span", { text: "14" }),
        el("span", { text: "30 يوم" }),
      ),
    );
    const whitelistInput = el("input", {
      class: "whitelist-input",
      type: "text",
      inputmode: "numeric",
      maxlength: "22",
      placeholder: "أدخل Discord User ID",
      "aria-label": "معرف عضو موثوق",
    });
    const whitelistBody = el("div", { class: "whitelist-chips" });
    const drawWhitelist = () => {
      whitelistBody.replaceChildren();
      if (!state.whitelist.length) {
        whitelistBody.append(
          el("span", { class: "whitelist-empty", text: "لا توجد معرفات موثوقة مضافة" }),
        );
        return;
      }
      state.whitelist.forEach((id) => {
        const chip = el(
          "span",
          { class: "whitelist-chip" },
          el("span", { text: id }),
          el("button", {
            type: "button",
            "aria-label": `إزالة ${id} من القائمة البيضاء`,
            text: "×",
            onClick: () => updateWhitelist("remove", id),
          }),
        );
        whitelistBody.append(chip);
      });
    };
    const addWhitelist = () => {
      const id = whitelistInput.value.trim();
      if (!/^\d{15,22}$/.test(id)) {
        toast("أدخل Discord User ID صالحاً", "warn");
        return;
      }
      updateWhitelist("add", id);
    };
    whitelistInput.onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        addWhitelist();
      }
    };
    const addButton = el("button", {
      class: "btn whitelist-add",
      type: "button",
      text: "إضافة موثوق",
      onClick: addWhitelist,
    });
    drawWhitelist();
    const whitelistCard = el(
      "article",
      { class: "tactical-card whitelist-card" },
      el(
        "div",
        { class: "tactical-heading compact" },
        el("span", { class: "tactical-kicker", text: "TRUSTED OPERATORS / 03" }),
        el("h2", { text: "القائمة البيضاء للمشرفين" }),
        el("p", { text: "أضف معرفات المشرفين الموثوقين لمنع تدخل Anti-Nuke ضدهم." }),
      ),
      el("div", { class: "whitelist-entry" }, whitelistInput, addButton),
      whitelistBody,
    );
    section.append(
      el(
        "div",
        { class: "security-section-head" },
        el("div", { class: "eyebrow", text: "TACTICAL SECURITY / LIVE" }),
        el("h2", { text: "مركز الدفاع والأزمات" }),
        el("p", { text: "تحكم مباشر في عزل السيرفر ومراقبة النشاط الإداري عالي الخطورة." }),
      ),
      el("div", { class: "security-grid" }, lockCard, sliderCard, whitelistCard),
      incidentsCard(),
    );
    return section;
  }
  function confirmLockdown(locked) {
    navigator.vibrate?.([30, 50, 30]);
    const back = el("div", {
        class: "modal-back crisis-modal-back",
        role: "dialog",
        "aria-modal": "true",
      }),
      modal = el(
        "div",
        { class: "modal crisis-modal" },
        el("div", { class: "crisis-modal-icon", text: locked ? "⚠" : "✓" }),
        el("h2", { text: locked ? "تأكيد الإغلاق الطارئ" : "إلغاء الإغلاق الطارئ" }),
        el("p", {
          text: locked
            ? "سيتم منع الإرسال في جميع القنوات النصية العامة. هل تريد المتابعة؟"
            : "سيتم إعادة السماح بالإرسال في القنوات التي تم عزلها.",
        }),
      ),
      actions = el("div", { class: "modal-actions" });
    actions.append(
      el("button", {
        class: locked ? "crisis-confirm" : "save",
        type: "button",
        text: locked ? "نعم، فعّل الإغلاق" : "نعم، ألغِ الإغلاق",
        onClick: () => {
          navigator.vibrate?.([30, 50, 30]);
          back.remove();
          setLockdown(locked);
        },
      }),
      el("button", {
        type: "button",
        text: "إلغاء",
        onClick: () => back.remove(),
      }),
    );
    modal.append(actions);
    back.append(modal);
    document.body.append(back);
  }
  async function setLockdown(locked) {
    if (!state.online) {
      toast("الحفظ معطّل أثناء انقطاع الاتصال", "warn");
      return;
    }
    try {
      const r = await api(`api/guild/${state.guild.id}/security/lockdown`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({ locked }),
      });
      const data = await r.json();
      if (r.ok && data.ok) {
        state.lockdown = locked;
        toast(
          locked ? "🚨 بدأ عزل القنوات العامة" : "✅ تم إلغاء الإغلاق الطارئ",
          locked ? "warn" : "success",
          4000,
        );
        await refreshIncidents(state.guild.id, true);
        renderPage();
      } else if (r.status === 429) {
        toast(`تم تجاوز الحد، حاول بعد ${data.retry_after || 5} ثانية`, "warn");
      } else {
        toast("تعذر تنفيذ بروتوكول الإغلاق");
      }
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بمحرك الأمان");
    }
  }
  async function updateWhitelist(action, userId) {
    try {
      const r = await api(`api/guild/${state.guild.id}/security/whitelist`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({ action, user_id: userId }),
      });
      const data = await r.json();
      if (r.ok && data.ok) {
        state.whitelist = data.whitelist || [];
        toast(action === "add" ? "تمت إضافة المشرف إلى القائمة البيضاء" : "تمت الإزالة", "success", 2600);
        renderPage();
        return;
      }
      toast(data.fields?.user_id || "تعذر تحديث القائمة البيضاء");
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بمحرك الأمان");
    }
  }
  function scheduleOnboardingPreview() {
    clearTimeout(state.onboardingPreviewTimer);
    state.onboardingPreviewTimer = setTimeout(() => {
      const current = $("#preview");
      if (current) current.replaceWith(preview());
    }, 120);
  }
  function insertTemplateVariable(textarea, token) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.value = `${textarea.value.slice(0, start)}${token}${textarea.value.slice(end)}`;
    textarea.selectionStart = textarea.selectionEnd = start + token.length;
    state.draft.welcome_message = textarea.value;
    navigator.vibrate?.(10);
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
  }
  function variableChips(textarea) {
    const wrap = el("div", { class: "variable-chips", "aria-label": "متغيرات الرسالة" });
    [
      ["{user}", "منشن العضو"],
      ["{server}", "اسم السيرفر"],
      ["{count}", "ترتيب العضو"],
      ["{inviter}", "صاحب الدعوة"],
    ].forEach(([token, label]) => {
      wrap.append(
        el("button", {
          class: "variable-chip",
          type: "button",
          title: label,
          text: token,
          onClick: () => insertTemplateVariable(textarea, token),
        }),
      );
    });
    return wrap;
  }
  function roleName(id) {
    return state.meta?.roles?.find((role) => String(role.id) === String(id))?.name || "بدون رتبة";
  }
  function normalizePanelColor(value) {
    return /^#[0-9a-f]{6}$/i.test(String(value || "")) ? String(value) : "#5865f2";
  }
  function ensureSelfRoleBuilder() {
    if (state.selfRoleBuilder) return state.selfRoleBuilder;
    const saved = state.onboarding?.self_roles?.[0];
    state.selfRoleBuilder = {
      target_channel_id: String(
        saved?.channel_id || state.draft?.welcome_channel_id || state.meta?.channels?.[0]?.id || "",
      ),
      title: saved?.title || "اختر رتبتك",
      description: saved?.description || "اختر الرتب التي تناسبك من القائمة التالية:",
      color: normalizePanelColor(saved?.color_hex || saved?.color),
      emoji: saved?.emoji || "🏷️",
      min_level: Math.max(0, Number(saved?.min_level || 0)),
      roles: (saved?.buttons || saved?.role_specs || []).map((role) => ({
        id: String(role.role_id || role.id),
        label: String(role.label || role.name || role.role_id || role.id),
        emoji: String(role.emoji || ""),
        custom_min_level: Math.max(0, Number(role.custom_min_level || 0)),
      })),
    };
    return state.selfRoleBuilder;
  }
  function nativeSelect(label, value, options, onChange) {
    const select = el("select", { class: "studio-select", "aria-label": label });
    options.forEach((option) =>
      select.append(el("option", { value: String(option.value), text: option.label })),
    );
    select.value = String(value ?? "");
    select.onchange = () => onChange(select.value);
    return select;
  }
  function selfRolePreview(builder) {
    const panel = el(
      "div",
      { class: "self-role-preview-panel", style: `--panel-accent:${normalizePanelColor(builder.color)}` },
      el("div", { class: "self-role-preview-kicker", text: "DISCORD / ROLE SELECTOR" }),
      el("h3", { text: `${builder.emoji || "🏷️"} ${builder.title || "اختر رتبتك"}` }),
      el("p", { text: builder.description || "اختر الرتب التي تناسبك:" }),
      el("span", { class: "level-gate-badge", text: builder.min_level > 0 ? `🔒 يتطلب لفل ${builder.min_level}` : "متاح للجميع" }),
    );
    const grid = el("div", { class: "role-button-grid" });
    (builder.roles.length ? builder.roles : [{ id: "preview", label: "رتبة تجريبية", emoji: "✨" }]).forEach(
      (role) => {
        grid.append(
          el("button", {
            class: "role-preview-button",
            type: "button",
            text: `${role.emoji || "🏷️"} ${role.label || roleName(role.id)}`,
          }),
        );
      },
    );
    panel.append(grid);
    return panel;
  }
  function selfRolesBuilder() {
    const builder = ensureSelfRoleBuilder();
    const roles = state.meta?.roles || [];
    const availableRoles = roles.filter(
      (role) =>
        role.assignable !== false &&
        !role.managed &&
        !role.default &&
        !builder.roles.some((selected) => String(selected.id) === String(role.id)),
    );
    const roleRows = el("div", { class: "builder-role-list" });
    if (!builder.roles.length)
      roleRows.append(el("div", { class: "builder-empty", text: "أضف رتبة واحدة على الأقل لتفعيل النشر." }));
    builder.roles.forEach((role, index) => {
      const label = el("input", {
        class: "builder-role-input",
        type: "text",
        maxlength: "100",
        value: role.label || roleName(role.id),
        "aria-label": `اسم الرتبة ${index + 1}`,
      });
      const emoji = el("input", {
        class: "builder-emoji-input",
        type: "text",
        maxlength: "8",
        value: role.emoji || "",
        "aria-label": `إيموجي الرتبة ${index + 1}`,
      });
      const minLevel = el("input", {
        class: "builder-level-input",
        type: "number",
        min: "0",
        max: "1000",
        value: String(role.custom_min_level || 0),
        "aria-label": `المستوى المطلوب للرتبة ${index + 1}`,
      });
      label.oninput = () => (role.label = label.value);
      emoji.oninput = () => (role.emoji = emoji.value);
      minLevel.oninput = () => {
        role.custom_min_level = Math.max(0, Number(minLevel.value || 0));
        scheduleOnboardingPreview();
      };
      roleRows.append(
        el(
          "div",
          { class: "builder-role-row" },
          el("span", { class: "role-dot", style: `background:${roles.find((r) => String(r.id) === String(role.id))?.color || "#64748b"}` }),
          emoji,
          label,
           el("span", { class: "builder-level-prefix", text: "لفل" }),
           minLevel,
          el("small", { class: "builder-role-source", text: roleName(role.id) }),
          el("button", {
            class: "icon-button",
            type: "button",
            "aria-label": "إزالة الرتبة",
            text: "×",
            onClick: () => {
              builder.roles.splice(index, 1);
              renderPage();
            },
          }),
        ),
      );
    });
    const channelOptions = (state.meta?.channels || []).map((channel) => ({
      value: channel.id,
      label: `# ${channel.name}`,
    }));
    const rolePicker = nativeSelect(
      "إضافة رتبة للوحة",
      "",
      [{ value: "", label: "إضافة رتبة…" }, ...availableRoles.map((role) => ({ value: role.id, label: role.name }))],
      (value) => {
        if (!value) return;
        const role = roles.find((item) => String(item.id) === String(value));
        if (!role) return;
        builder.roles.push({ id: String(role.id), label: role.name, emoji: "🏷️" });
        navigator.vibrate?.(10);
        renderPage();
      },
    );
    const title = el("input", {
      class: "builder-input",
      type: "text",
      maxlength: "256",
      value: builder.title,
      "aria-label": "عنوان لوحة الرتب",
    });
    const description = el("textarea", {
      class: "builder-textarea",
      maxlength: "4000",
      "aria-label": "وصف لوحة الرتب",
    });
    description.value = builder.description;
    const color = el("input", {
      class: "builder-color",
      type: "color",
      value: normalizePanelColor(builder.color),
      "aria-label": "لون لوحة الرتب",
    });
    const emoji = el("input", {
      class: "builder-emoji-input panel-emoji",
      type: "text",
      maxlength: "8",
      value: builder.emoji,
      "aria-label": "إيموجي لوحة الرتب",
    });
    const minLevel = el("input", {
      class: "builder-input builder-level-gate-input",
      type: "number",
      min: "0",
      max: "1000",
      value: String(builder.min_level || 0),
      "aria-label": "المستوى الأدنى للوحة",
    });
    title.oninput = () => {
      builder.title = title.value;
      const current = $(".self-role-preview-panel");
      if (current) current.replaceWith(selfRolePreview(builder));
    };
    description.oninput = () => {
      builder.description = description.value;
      const current = $(".self-role-preview-panel");
      if (current) current.replaceWith(selfRolePreview(builder));
    };
    color.oninput = () => {
      builder.color = normalizePanelColor(color.value);
      const current = $(".self-role-preview-panel");
      if (current) current.replaceWith(selfRolePreview(builder));
    };
    emoji.oninput = () => {
      builder.emoji = emoji.value;
      const current = $(".self-role-preview-panel");
      if (current) current.replaceWith(selfRolePreview(builder));
    };
    minLevel.oninput = () => {
      builder.min_level = Math.max(0, Number(minLevel.value || 0));
      const current = $(".self-role-preview-panel");
      if (current) current.replaceWith(selfRolePreview(builder));
    };
    const targetChannel = nativeSelect(
      "قناة لوحة الرتب",
      builder.target_channel_id,
      channelOptions.length ? channelOptions : [{ value: "", label: "لا توجد قنوات" }],
      (value) => (builder.target_channel_id = value),
    );
    const deploy = el("button", {
      class: "btn builder-deploy",
      type: "button",
      text: "نشر لوحة الرتب في Discord",
      onClick: deploySelfRoles,
    });
    const form = el(
      "div",
      { class: "self-role-builder-form" },
      el("div", { class: "builder-form-row" }, el("label", { text: "القناة" }), targetChannel),
      el("div", { class: "builder-form-row" }, el("label", { text: "العنوان" }), title),
      el("div", { class: "builder-form-row" }, el("label", { text: "الوصف" }), description),
      el("div", { class: "builder-inline-fields" }, el("div", { class: "builder-form-row" }, el("label", { text: "الإيموجي" }), emoji), el("div", { class: "builder-form-row" }, el("label", { text: "اللون" }), color)),
      el("div", { class: "builder-form-row level-gate-control" }, el("label", { text: "شرط المستوى العام" }), minLevel, el("small", { text: "0 = متاح للجميع، وأي رقم آخر يقفل اللوحة حتى يصل العضو إليه." })),
      el("div", { class: "builder-form-row" }, el("label", { text: "الرتب" }), rolePicker),
      roleRows,
      deploy,
    );
    const previewPane = el("div", { class: "self-role-builder-preview" }, el("div", { class: "preview-title", text: "المعاينة" }), selfRolePreview(builder));
    const existing = el("div", { class: "deployed-panels" });
    const panels = state.onboarding?.self_roles || [];
    if (panels.length) {
      existing.append(el("div", { class: "deployed-heading", text: "لوحات منشورة" }));
      panels.slice(0, 4).forEach((panel) => {
        existing.append(
          el("div", { class: "deployed-panel" },
            el("span", { class: "deployed-panel-icon", text: panel.emoji || "🏷️" }),
            el("span", { class: "ell", text: panel.title || "لوحة رتب" }),
            el("small", { text: `${panel.buttons?.length || panel.role_specs?.length || 0} رتب · ${panel.min_level ? `لفل ${panel.min_level}` : "مفتوحة"} · رسالة ${panel.message_id}` }),
          ),
        );
      });
    }
    return el("div", { class: "self-role-builder" }, form, previewPane, existing);
  }
  function onboardingView() {
    const section = el("section", { id: "view-onboarding", class: "onboarding-view" });
    const message = el("textarea", {
      id: "in-onboarding-message",
      maxlength: "1000",
      placeholder: "مرحباً {user} في {server} — أنت العضو {count}.",
    });
    message.value = state.draft.welcome_message || "";
    const messageCount = el("div", { class: "counter", text: `${message.value.length} / 1000` });
    message.oninput = () => {
      state.draft.welcome_message = message.value;
      messageCount.textContent = `${message.value.length} / 1000`;
      renderDynamic();
      scheduleOnboardingPreview();
    };
    const onboardingFields = el("div", { class: "fields onboarding-fields" });
    onboardingFields.append(
      selector("welcome_channel_id", "قناة الترحيب", "channel"),
      selector("leave_channel_id", "قناة المغادرة", "channel"),
      toggle("welcome_dm_enabled", "إرسال ترحيب خاص للعضو"),
      selector("rules_channel_id", "قناة القوانين", "channel"),
      selector("verified_role_id", "رتبة العضو الموثق", "role"),
      selector("unverified_role_id", "رتبة العضو غير الموثق", "role"),
      el("div", { class: "field wide role-matrix-field" },
        el("label", { text: "مصفوفة الأدوار التلقائية" }),
        el("div", { class: "role-matrix" },
          el("div", { class: "role-matrix-card human" }, el("span", { class: "matrix-icon", text: "◉" }), el("div", { class: "matrix-copy" }, el("strong", { text: "الأعضاء البشر" }), el("small", { "data-role-matrix-key": "member_auto_role_id", text: roleName(state.draft.member_auto_role_id) })), selector("member_auto_role_id", "رتبة الأعضاء", "role")),
          el("div", { class: "role-matrix-card bot" }, el("span", { class: "matrix-icon", text: "⌘" }), el("div", { class: "matrix-copy" }, el("strong", { text: "البوتات" }), el("small", { "data-role-matrix-key": "bot_auto_role_id", text: roleName(state.draft.bot_auto_role_id) })), selector("bot_auto_role_id", "رتبة البوتات", "role")),
          el("div", { class: "role-matrix-card all" }, el("span", { class: "matrix-icon", text: "✦" }), el("div", { class: "matrix-copy" }, el("strong", { text: "رتبة افتراضية للجميع" }), el("small", { "data-role-matrix-key": "auto_role_id", text: roleName(state.draft.auto_role_id) })), selector("auto_role_id", "رتبة عامة", "role")),
        ),
      ),
    );
    const leave = el("textarea", {
      id: "in-onboarding-leave",
      maxlength: "1000",
      placeholder: "{username} غادر {server}.",
    });
    leave.value = state.draft.leave_message || "";
    const leaveCount = el("div", { class: "counter", text: `${leave.value.length} / 1000` });
    leave.oninput = () => {
      state.draft.leave_message = leave.value;
      leaveCount.textContent = `${leave.value.length} / 1000`;
      renderDynamic();
    };
    const messageField = field("قالب رسالة الترحيب", message, "welcome_message", "يدعم Markdown محدوداً، وسيتم تجاهل أي HTML.");
    messageField.classList.add("wide", "message-template-field");
    messageField.append(variableChips(message), messageCount, preview());
    const leaveField = field("رسالة المغادرة", leave, "leave_message");
    leaveField.classList.add("wide");
    leaveField.append(leaveCount);
    const embedDescription = el("textarea", {
      id: "in-welcome-embed-description",
      maxlength: "1000",
      placeholder: "يا هلا {user} في {server}! أنت العضو رقم {count}.",
    });
    embedDescription.value = state.draft.welcome_embed_description || "";
    embedDescription.oninput = () => {
      state.draft.welcome_embed_description = embedDescription.value;
      renderDynamic();
    };
    const embedDescriptionField = field(
      "وصف الـ Embed",
      embedDescription,
      "welcome_embed_description",
      "استخدم {user} و {server} و {count} و {inviter} لإظهار بيانات العضو تلقائياً.",
    );
    embedDescriptionField.classList.add("wide");
    const embedControls = el(
      "div",
      { class: "embed-builder-grid" },
      toggle("welcome_embed_enabled", "تفعيل ترحيب Embed احترافي"),
      toggle("welcome_embed_show_avatar", "إظهار صورة العضو"),
      input("welcome_embed_title", "عنوان الترحيب", "text", {
        maxlength: "256",
        placeholder: "أهلاً بك في {server} ✨",
      }),
      input("welcome_embed_color", "لون الـ Embed", "color"),
      input("welcome_embed_image_url", "صورة رئيسية اختيارية", "url", {
        maxlength: "2048",
        placeholder: "https://example.com/welcome.png",
      }),
      selector("welcome_embed_sticker_id", "ملصق من السيرفر", "sticker"),
      input("welcome_embed_footer", "التذييل", "text", {
        maxlength: "2048",
        placeholder: "PRIME | TEAM • تطوير abood2026",
      }),
      embedDescriptionField,
    );
    const actions = el(
      "div",
      { class: "onboarding-actions" },
      el("button", { class: "btn onboarding-save", type: "button", text: "حفظ إعدادات onboarding", onClick: saveOnboarding }),
      el("button", { class: "btn onboarding-test", type: "button", text: "إرسال تجربة إلى Discord", onClick: sendTestWelcome }),
    );
    section.append(
      el("div", { class: "studio-hero" },
        el("div", { class: "eyebrow", text: "ONBOARDING STUDIO / LIVE" }),
        el("h2", { text: "استوديو الدخول والهوية" }),
        el("p", { text: "صمّم لحظة دخول العضو، راجعها بصرياً، ثم انشر تجربة حقيقية في قناة Discord." }),
        actions,
      ),
       card("قواعد الدخول والترحيب", el("div", { class: "onboarding-card-body" }, onboardingFields, messageField, leaveField)),
       card("مصمم الترحيب الاحترافي", el("div", { class: "onboarding-card-body embed-builder-card" },
         el("p", { class: "hint", text: "أنشئ رسالة Embed تظهر فيها صورة العضو، عدد الأعضاء، الترتيب، صورة رئيسية أو ملصق من السيرفر." }),
         embedControls,
       )),
      card("منشئ لوحة الرتب الذاتية", selfRolesBuilder()),
    );
    return section;
  }
  function pulse() {
    navigator.vibrate?.(10);
  }
  function commandRoles(command) {
    return new Set((command.allowed_roles || []).map(String));
  }
  function commandShortcuts(command) {
    const name = String(command.command_name || "").toLowerCase();
    const policyAliases = (Array.isArray(command.custom_aliases)
      ? command.custom_aliases
      : (Array.isArray(command.aliases) ? command.aliases : [])
    ).map((trigger) => ({
      trigger: String(trigger),
      target_type: "command",
      target: `/${name}`,
      policyAlias: true,
    }));
    const legacy = (state.commandStudio.shortcuts || []).filter((shortcut) => {
      const target = String(shortcut.target || "").trim().toLowerCase();
      return target.replace(/^[/!]/, "").split(/\s+/)[0] === name;
    });
    const seen = new Set();
    return [...policyAliases, ...legacy].filter((shortcut) => {
      const key = String(shortcut.trigger || "").toLowerCase();
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  function commandPermissionWarnings(command) {
    const raw = [
      ...(Array.isArray(command.permission_warnings) ? command.permission_warnings : []),
      ...(Array.isArray(command.missing_permissions) ? command.missing_permissions : []),
      ...(command.permission_warning ? [command.permission_warning] : []),
    ];
    return raw.filter(Boolean).map((item) => typeof item === "string" ? item : item.name || item.permission || JSON.stringify(item));
  }
  function commandMatchesFilters(command) {
    const query = state.commandSearch.trim().toLowerCase();
    const roleId = String(state.commandRoleFilter || "");
    return (
      (!query || `${command.command_name || ""} ${command.cog || ""}`.toLowerCase().includes(query)) &&
      (state.commandCogFilter === "all" || String(command.cog || "Commands") === state.commandCogFilter) &&
      (state.commandStatusFilter === "all" ||
        (state.commandStatusFilter === "enabled" && command.enabled !== false) ||
        (state.commandStatusFilter === "disabled" && command.enabled === false) ||
        (state.commandStatusFilter === "warning" && commandPermissionWarnings(command).length > 0)) &&
      (state.commandRoleFilter === "all" || commandRoles(command).has(roleId))
    );
  }
  const COMMAND_UI_LABELS = {
    warn: ["تحذير", "إرسال تحذير لعضو من السيرفر", "⚠️", "violet"],
    ban: ["حظر", "حظر عضو ومنعه من دخول السيرفر", "🔨", "red"],
    kick: ["طرد", "طرد عضو من السيرفر", "👤", "red"],
    timeout: ["تايم أوت", "إسكات عضو لمدة محددة", "⏱", "red"],
    untimeout: ["فك التايم أوت", "السماح للعضو بالكلام من جديد", "🔓", "red"],
    clear: ["مسح الرسائل", "حذف رسائل القناة بسرعة", "🗑", "blue"],
    lockdown: ["قفل القناة", "منع الأعضاء من الكتابة في القناة", "🔒", "blue"],
    unlock: ["فتح القناة", "السماح للأعضاء بالكتابة", "🔓", "blue"],
    slowmode: ["الوضع البطيء", "تحديد وقت بين رسائل الأعضاء", "🐌", "blue"],
    mute: ["إسكات", "منع العضو من التحدث", "🔇", "gold"],
    unmute: ["فك الإسكات", "إعادة صلاحية التحدث للعضو", "🔊", "gold"],
    poll: ["استطلاع", "إنشاء استطلاع داخل القناة", "📊", "gold"],
    ticket: ["التذاكر", "إدارة تذاكر الدعم والمساعدة", "🎫", "purple"],
  };
  function commandVisual(command) {
    const name = String(command.command_name || "").toLowerCase().split(/\s+/).pop();
    const metadata = state.commandRegistry?.byKey?.[name];
    const item = COMMAND_UI_LABELS[name];
    return {
      name: metadata?.display_name || item?.[0] || `/${name}`,
      description: metadata?.description || item?.[1] || command.description || "إدارة هذا الأمر من إعدادات السيرفر.",
      icon: item?.[2] || "✦",
      tone: item?.[3] || "slate",
      premium: Boolean(command.premium || command.is_premium || command.pro),
    };
  }
  function commandSectionVisual(cog) {
    const value = String(cog || "").toLowerCase();
    if (value.includes("moder")) return { label: "الطرد والحظر", icon: "📌", tone: "red" };
    if (value.includes("econom")) return { label: "مزایا", icon: "✦", tone: "pink" };
    if (value.includes("engage") || value.includes("community")) return { label: "الإسكات والصوت", icon: "🔇", tone: "gold" };
    if (value.includes("ticket") || value.includes("channel")) return { label: "إدارة القنوات", icon: "🖌", tone: "blue" };
    if (value.includes("security")) return { label: "Blacklist", icon: "⛔", tone: "red" };
    if (value.includes("utility") || value.includes("command")) return { label: "التحذيرات والإدارة", icon: "★", tone: "purple" };
    return { label: cog || "الأوامر", icon: "✦", tone: "slate" };
  }
  function commandRows() {
    const commands = (state.commandStudio.commands || []).filter(commandMatchesFilters);
    const groups = new Map();
    commands.forEach((command) => {
      const key = command.cog || "Commands";
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(command);
    });
    const root = el("div", { id: "command-rows", class: "command-groups" });
    if (!commands.length) {
      root.append(el("div", { class: "empty studio-empty", text: "لا توجد أوامر مطابقة للبحث" }));
      return root;
    }
    groups.forEach((items, cog) => {
      const section = commandSectionVisual(cog);
      const collapsed = Boolean(state.commandCollapsedGroups[cog]);
      const group = el("section", { class: `command-group${collapsed ? " is-collapsed" : ""}` });
      const groupButton = el("button", {
        class: "command-section-head",
        type: "button",
        "aria-expanded": String(!collapsed),
        onClick: () => {
          state.commandCollapsedGroups[cog] = !state.commandCollapsedGroups[cog];
          renderPage();
        },
      },
        el("span", { class: `command-section-icon tone-${section.tone}`, text: section.icon }),
        el("span", { class: "command-section-copy" },
          el("strong", { text: section.label }),
          el("small", { text: `${items.length} أمر` }),
        ),
        el("span", { class: "command-section-chevron", text: collapsed ? "⌄" : "⌃" }),
      );
      group.append(groupButton);
      if (collapsed) {
        root.append(group);
        return;
      }
      const list = el("div", { class: "command-section-list" });
      items.forEach((command) => {
        const roles = commandRoles(command);
        const commandId = String(command.command_name);
        const warnings = commandPermissionWarnings(command);
        const shortcuts = commandShortcuts(command);
        const visual = commandVisual(command);
        const toggleButton = el("button", {
          class: `studio-switch command-list-switch${command.enabled ? " on" : ""}`,
          type: "button",
          role: "switch",
          "aria-checked": String(!!command.enabled),
          "aria-label": `تفعيل ${command.command_name}`,
        }, el("i"));
        toggleButton.onclick = () => {
          pulse();
          updateCommand(command, !command.enabled, [...roles]);
        };
        const select = el("input", {
          class: "command-select command-list-check",
          type: "checkbox",
          checked: state.selectedCommandIds.includes(commandId),
          "aria-label": `تحديد ${command.command_name}`,
        });
        select.onchange = () => {
          state.selectedCommandIds = select.checked
            ? [...new Set([...state.selectedCommandIds, commandId])]
            : state.selectedCommandIds.filter((id) => id !== commandId);
          renderPage();
        };
        const row = el("article", { class: `command-list-row${warnings.length ? " has-warning" : ""}` },
          el("div", { class: `command-list-icon tone-${visual.tone}`, text: visual.icon }),
          el("div", { class: "command-list-copy" },
            el("div", { class: "command-list-title" },
              el("strong", { text: visual.name }),
              visual.premium ? el("span", { class: "command-pro-badge", text: "Pro ✨" }) : [],
            ),
            el("small", { text: visual.description }),
            shortcuts.length ? el("div", { class: "command-list-aliases" }, shortcuts.slice(0, 3).map((item) => el("code", { text: item.trigger }))) : [],
          ),
          el("div", { class: "command-list-actions" },
            select,
            el("button", { class: "command-list-settings", type: "button", text: "⚙", title: "إعدادات الأمر", onClick: () => openCommandDetail(command) }),
            toggleButton,
          ),
        );
        list.append(row);
      });
      group.append(list);
      root.append(group);
    });
    return root;
  }
  async function updateCommand(command, enabled, allowedRoles, allowedChannels = command.allowed_channels || []) {
    try {
      const r = await api(`api/guild/${state.guild.id}/commands/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({
          command_name: command.command_name,
          enabled,
          allowed_roles: allowedRoles,
          allowed_channels: allowedChannels,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر تحديث صلاحية الأمر");
        return;
      }
      Object.assign(command, data.command);
      toast(`✅ تم ${enabled ? "تفعيل" : "تعطيل"} /${command.command_name}`, "success", 2200);
      renderPage();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
    }
  }
  async function saveCommandPolicy(
    command,
    enabled,
    allowedRoles,
    allowedChannels,
    aliases = command.custom_aliases || command.aliases || [],
    policyExtras = {},
  ) {
    try {
      const r = await api(`api/guild/${state.guild.id}/commands/${encodeURIComponent(command.command_name)}/policy`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({
          command_name: command.command_name,
          is_enabled: Boolean(enabled),
          aliases,
          allowed_roles: allowedRoles,
          allowed_channels: allowedChannels,
          auto_delete_seconds: policyExtras.auto_delete_seconds,
          response_style: policyExtras.response_style,
          response_template: policyExtras.response_template,
        }),
      });
      const data = await r.json();
      if (!r.ok || !data.command) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر حفظ إعدادات الأمر", "warn");
        return false;
      }
      Object.assign(command, data.command);
      return true;
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم", "warn");
      return false;
    }
  }
  function parseCommandAliases(input) {
    const aliases = [...new Set(
      String(input?.value || "")
        .split(/[,،\n]+/)
        .map((value) => value.trim().replace(/^[/!]/, ""))
        .filter(Boolean),
    )];
    if (aliases.length > 20) {
      toast("يمكن إضافة 20 اختصاراً كحد أقصى للأمر", "warn");
      return null;
    }
    if (aliases.some((value) => /\s/.test(value) || value.length > 80)) {
      toast("كل اختصار يجب أن يكون كلمة واحدة وبحد أقصى 80 حرفاً", "warn");
      return null;
    }
    return aliases;
  }
  async function saveCommandPrefix(input, feedback) {
    const value = input.value.trim();
    if (!value || value.length > 5 || /\s/.test(value)) {
      feedback.textContent = "استخدم prefix من 1 إلى 5 أحرف بدون مسافات";
      feedback.className = "prefix-feedback bad";
      return;
    }
    try {
      const r = await api(`api/guild/${state.guild.id}/settings`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({ revision: state.revision, changes: { prefix: value } }),
      });
      const data = await r.json();
      if (r.ok && data.revision != null) {
        state.baseline = { ...state.baseline, prefix: data.settings.prefix };
        state.draft = { ...state.draft, prefix: data.settings.prefix };
        state.revision = data.revision;
        feedback.textContent = "تم تطبيق prefix فورياً";
        feedback.className = "prefix-feedback good";
        pulse();
        toast("✅ تم تحديث prefix", "success", 2200);
        setTimeout(() => renderPage(), 700);
      } else if (r.status === 409) {
        feedback.textContent = "توجد نسخة أحدث من الإعدادات، أعد المحاولة";
        feedback.className = "prefix-feedback bad";
      } else {
        feedback.textContent = data.fields?.prefix || "تعذر حفظ prefix";
        feedback.className = "prefix-feedback bad";
      }
    } catch (error) {
      if (error.message !== "unauth") {
        feedback.textContent = "تعذر الاتصال بالخادم";
        feedback.className = "prefix-feedback bad";
      }
    }
  }
  function commandListForWorkspace() {
    return (state.commandStudio.commands || []).filter(commandMatchesFilters);
  }
  function closeCommandDetail() {
    document.querySelector(".command-detail-back")?.remove();
    state.commandDetail = null;
  }
  async function saveCommandShortcuts(command, input, options = {}) {
    const requested = [...new Set(
      input.value
        .split(/[,،\n]+/)
        .map((value) => value.trim().replace(/^[/!]/, ""))
        .filter(Boolean),
    )];
    if (requested.length > 20) {
      toast("يمكن إضافة 20 اختصاراً كحد أقصى للأمر", "warn");
      return false;
    }
    if (requested.some((value) => /\s/.test(value) || value.length > 80)) {
      toast("كل اختصار يجب أن يكون كلمة واحدة وبحد أقصى 80 حرفاً", "warn");
      return false;
    }
    const existing = commandShortcuts(command);
    const existingByTrigger = new Map(existing.map((item) => [String(item.trigger).toLowerCase(), item]));
    const wanted = new Set(requested.map((value) => value.toLowerCase()));
    try {
      for (const trigger of requested) {
        const existingShortcut = existingByTrigger.get(trigger.toLowerCase());
        if (existingShortcut && existingShortcut.target_type === "command") continue;
        const response = await api(`api/guild/${state.guild.id}/shortcuts`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
          body: JSON.stringify({
            trigger,
            target_type: "command",
            target: `/${command.command_name}`,
          }),
        });
        const data = await response.json();
        if (!response.ok) {
          toast(data.fields ? Object.values(data.fields)[0] : "تعذر حفظ الاختصار", "warn");
          return false;
        }
        const shortcutIndex = state.commandStudio.shortcuts.findIndex(
          (item) => item.id === data.shortcut.id
            || String(item.trigger).toLowerCase() === trigger.toLowerCase(),
        );
        if (shortcutIndex >= 0) {
          state.commandStudio.shortcuts[shortcutIndex] = data.shortcut;
        } else {
          state.commandStudio.shortcuts.push(data.shortcut);
        }
      }
      for (const shortcut of existing) {
        if (wanted.has(String(shortcut.trigger).toLowerCase())) continue;
        const response = await api(`api/guild/${state.guild.id}/shortcuts/${shortcut.id}`, {
          method: "DELETE",
          headers: { "X-CSRF-Token": state.session.csrf },
        });
        if (response.ok) {
          state.commandStudio.shortcuts = state.commandStudio.shortcuts.filter((item) => item.id !== shortcut.id);
        }
      }
      pulse();
      toast(`تم حفظ ${requested.length} اختصاراً لـ /${command.command_name}`, "success", 2300);
      state.shortcutCommandId = command.command_name;
      state.shortcutInputText = requested.join("، ");
      if (options.deferRender) return true;
      if (options.reopen !== false) {
        closeCommandDetail();
        openCommandDetail(command);
      } else {
        renderPage();
      }
      return true;
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم", "warn");
      return false;
    }
  }
  function commandChoiceEditor(title, choices, selected, placeholder, icon, formatter) {
    const picked = new Set((selected || []).map(String));
    const search = el("input", {
      class: "studio-input command-policy-search",
      type: "search",
      placeholder,
      "aria-label": title,
    });
    const chips = el("div", { class: "command-policy-chips" });
    const list = el("div", { class: "command-policy-options" });
    const root = el("section", { class: "command-policy-section" },
      el("div", { class: "command-policy-heading" },
        el("span", { class: "command-policy-icon", text: icon }),
        el("div", {}, el("strong", { text: title }), el("small", { text: "اتركه فارغاً للسماح للجميع" })),
      ),
      chips,
      search,
      list,
    );
    const render = () => {
      const query = search.value.trim().toLowerCase();
      const chipNodes = picked.size
        ? [...picked].map((id) => {
            const item = choices.find((choice) => String(choice.id) === id);
            const chip = el("button", { class: "command-policy-chip", type: "button", text: `× ${formatter(item || { id })}` });
            chip.onclick = () => { picked.delete(id); render(); };
            return chip;
          })
        : [el("span", { class: "command-policy-empty", text: "لم يتم تحديد أي عنصر" })];
      chips.replaceChildren(...chipNodes);

      const optionNodes = choices
          .filter((item) => !query || formatter(item).toLowerCase().includes(query))
          .slice(0, 80)
          .map((item) => {
            const id = String(item.id);
            const button = el("button", {
              class: `command-policy-option${picked.has(id) ? " selected" : ""}`,
              type: "button",
              text: `${picked.has(id) ? "✓ " : ""}${formatter(item)}`,
            });
            button.onclick = () => {
              if (picked.has(id)) picked.delete(id);
              else if (picked.size < 25) picked.add(id);
              render();
            };
            return button;
          });
      list.replaceChildren(...optionNodes);
    };
    search.oninput = render;
    render();
    return { root, values: () => [...picked] };
  }
  function openCommandDetail(command) {
    closeCommandDetail();
    state.commandDetail = command;
    const warnings = commandPermissionWarnings(command);
    const visual = commandVisual(command);
    let detailEnabled = command.enabled !== false;
    const back = el("div", { class: "modal-back command-detail-back", role: "dialog", "aria-modal": "true" });
    const input = el("input", {
      class: "studio-input command-simulator-input",
      value: state.commandSimulatorText || `${state.draft?.prefix || "!"}${command.command_name}`,
      placeholder: `${state.draft?.prefix || "!"}${command.command_name} ...`,
      "aria-label": "رسالة المحاكاة",
    });
    const output = el("div", { class: "command-simulator-output" });
    const renderOutput = () => {
      state.commandSimulatorText = input.value;
      const entered = input.value.trim() || `${state.draft?.prefix || "!"}${command.command_name}`;
      output.replaceChildren(
        el("span", { class: "simulator-user", text: "أنت" }),
        el("code", { text: entered }),
        el("span", { class: "simulator-arrow", text: "→" }),
        el("span", { class: "simulator-response", text: command.example_response || command.response_preview || "سيتم تشغيل الأمر حسب سياسة البوت الحالية." }),
      );
    };
    input.oninput = renderOutput;
    renderOutput();
    const permissionBox = warnings.length
      ? el("div", { class: "permission-warning" },
          el("strong", { text: "تنبيه صلاحيات" }),
          el("p", { text: warnings.join("، ") }),
        )
      : el("div", { class: "permission-ok", text: "لا توجد تحذيرات صلاحيات من البيانات الحالية" });
    const roles = [...commandRoles(command)].map((id) => (state.commandStudio.roles || []).find((role) => String(role.id) === id)?.name || id);
    const shortcuts = commandShortcuts(command);
    const shortcutInput = el("textarea", {
      class: "studio-textarea command-alias-input",
      rows: "2",
      placeholder: "مثال: عيب، تحذير، انذار",
      "aria-label": "اختصارات الأمر",
      text: shortcuts.map((item) => item.trigger).join("، "),
    });
    const shortcutChips = el("div", { class: "command-alias-chips" },
      shortcuts.length
        ? shortcuts.map((item) => el("code", { class: "command-alias-chip", text: item.trigger }))
        : el("span", { class: "hint", text: "لا توجد اختصارات مخصصة لهذا الأمر بعد" }),
    );
    const shortcutSection = el("section", { class: "command-aliases" },
      el("div", { class: "section-heading compact" },
        el("div", {}, el("div", { class: "eyebrow", text: "COMMAND ALIASES" }), el("h3", { text: "اختصارات الأمر" })),
        el("span", { class: "alias-count", text: `${shortcuts.length}/20` }),
      ),
      el("p", { class: "hint", text: "اكتب أكثر من اختصار وافصل بينها بفاصلة. مثال: بدال /warn اكتب عيب أو تحذير." }),
      shortcutInput,
      shortcutChips,
      el("button", { class: "btn ghost alias-save-button", type: "button", text: "حفظ الاختصارات", onClick: () => saveCommandShortcuts(command, shortcutInput) }),
    );
    const rolesEditor = commandChoiceEditor(
      "الرتب المسموحة",
      state.commandStudio.roles || [],
      command.allowed_roles || [],
      "ابحث عن رتبة...",
      "♟",
      (item) => `@${item.name || item.id}`,
    );
    const channelsEditor = commandChoiceEditor(
      "القنوات المسموحة",
      state.commandStudio.channels || [],
      command.allowed_channels || [],
      "ابحث عن قناة...",
      "#",
      (item) => `#${item.name || item.id}`,
    );
    const statusSwitch = el("button", {
      class: `studio-switch command-detail-switch${detailEnabled ? " on" : ""}`,
      type: "button",
      role: "switch",
      "aria-checked": String(detailEnabled),
      "aria-label": "حالة الأمر",
    }, el("i"));
    const statusCopy = el("div", { class: "command-detail-status-copy" },
      el("strong", { text: "تفعيل الأمر" }),
      el("small", { text: "عند التعطيل، المستخدمون لن يقدروا على استخدام هذا الأمر." }),
    );
    statusSwitch.onclick = () => {
      detailEnabled = !detailEnabled;
      statusSwitch.classList.toggle("on", detailEnabled);
      statusSwitch.setAttribute("aria-checked", String(detailEnabled));
    };
    const saveDetails = async () => {
      const aliases = parseCommandAliases(shortcutInput);
      if (aliases === null) return;
      const policySaved = await saveCommandPolicy(
        command,
        detailEnabled,
        rolesEditor.values(),
        channelsEditor.values(),
        aliases,
      );
      if (!policySaved) return;
      pulse();
      toast("تم حفظ إعدادات الأمر وتطبيقها على السيرفر", "success", 2600);
      closeCommandDetail();
      renderPage();
    };
    const modal = el("aside", { class: "modal command-detail-drawer" },
      el("div", { class: "drawer-head" },
        el("div", {}, el("span", { class: "eyebrow", text: `${command.cog || "COMMANDS"} / POLICY` }), el("h2", {}, el("span", { text: visual.name }), el("small", { text: ` (${command.command_name})` }))),
        el("button", { class: "icon-action", type: "button", text: "×", title: "إغلاق", onClick: closeCommandDetail }),
      ),
      el("div", { class: "detail-status-line" },
        el("span", { class: `status-pill ${detailEnabled ? "on" : "off"}`, text: detailEnabled ? "مفعّل" : "معطّل" }),
        el("span", { class: "detail-meta", text: command.configured ? "سياسة مخصصة" : "إعداد افتراضي" }),
      ),
      el("p", { class: "command-detail-description", text: visual.description }),
      permissionBox,
      shortcutSection,
      el("section", { class: "command-detail-policy" },
        el("div", { class: "command-detail-policy-heading" },
          el("span", { class: "command-policy-icon", text: "◉" }),
          el("div", {}, el("strong", { text: "حالة الأمر" }), el("small", { text: "هذه القيمة تُحفظ وتُطبق على Discord" })),
        ),
        el("div", { class: "command-detail-status-editor" }, statusCopy, statusSwitch),
      ),
      rolesEditor.root,
      channelsEditor.root,
      el("dl", { class: "command-detail-list" },
        el("div", {}, el("dt", { text: "الـ Cog" }), el("dd", { text: command.cog || "Commands" })),
        el("div", {}, el("dt", { text: "الرتب الحالية" }), el("dd", { text: roles.length ? roles.join("، ") : "كل الرتب" })),
        el("div", {}, el("dt", { text: "القنوات الحالية" }), el("dd", { text: (command.allowed_channels || []).length ? (command.allowed_channels || []).join("، ") : "كل القنوات" })),
        el("div", {}, el("dt", { text: "اختصارات Discord" }), el("dd", { text: command.aliases?.length ? command.aliases.join("، ") : "لا توجد" })),
        el("div", {}, el("dt", { text: "آخر استخدام" }), el("dd", { text: command.last_used_at ? new Date(command.last_used_at).toLocaleString("ar") : "لا توجد بيانات" })),
      ),
      el("section", { class: "command-simulator" },
        el("div", { class: "section-heading compact" }, el("div", {}, el("div", { class: "eyebrow", text: "SAFE SIMULATOR" }), el("h3", { text: "اختبر شكل التنفيذ" }))),
        input,
        output,
        el("small", { class: "hint", text: "محاكاة محلية فقط؛ لا يتم إرسال رسالة إلى Discord." }),
      ),
      el("div", { class: "modal-actions" },
        el("button", { class: "btn ghost", type: "button", text: "إلغاء", onClick: closeCommandDetail }),
        el("button", { class: "btn primary command-detail-save", type: "button", text: "حفظ التعديلات ✓", onClick: saveDetails }),
      ),
    );
    back.onclick = (event) => { if (event.target === back) closeCommandDetail(); };
    back.append(modal);
    document.body.append(back);
    input.focus();
  }
  async function bulkUpdateCommands(enabled) {
    const selected = (state.commandStudio.commands || []).filter((command) => state.selectedCommandIds.includes(String(command.command_name)));
    if (!selected.length) return toast("حدد أمراً واحداً على الأقل", "info", 2200);
    if (!confirm(`${enabled ? "تفعيل" : "تعطيل"} ${selected.length} أوامر؟`)) return;
    let changed = 0;
    for (const command of selected) {
      try {
        const r = await api(`api/guild/${state.guild.id}/commands/toggle`, {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
          body: JSON.stringify({ command_name: command.command_name, enabled, allowed_roles: [...commandRoles(command)] }),
        });
        const data = await r.json();
        if (r.ok && data.command) {
          Object.assign(command, data.command);
          changed++;
        }
      } catch (error) {
        if (error.message === "unauth") return;
      }
    }
    state.selectedCommandIds = [];
    pulse();
    toast(`تم تحديث ${changed} من ${selected.length} أوامر`, changed === selected.length ? "success" : "warn", 2500);
    renderPage();
  }
  function commandPolicyMatrix() {
    const roles = (state.commandStudio.roles || []).slice(0, 6);
    const commands = commandListForWorkspace().slice(0, 30);
    const table = el("div", { class: "policy-matrix", role: "table" });
    const head = el("div", { class: "policy-matrix-row matrix-head", role: "row" },
      el("span", { role: "columnheader", text: "الأمر" }),
      ...roles.map((role) => el("span", { role: "columnheader", text: `@${role.name}` })),
    );
    table.append(head);
    if (!commands.length) {
      table.append(el("div", { class: "empty studio-empty", text: "لا توجد بيانات كافية لبناء مصفوفة السياسات" }));
      return table;
    }
    commands.forEach((command) => {
      const allowed = commandRoles(command);
      table.append(el("div", { class: "policy-matrix-row", role: "row" },
        el("button", { class: "matrix-command", type: "button", text: `/${command.command_name}`, onClick: () => openCommandDetail(command) }),
        ...roles.map((role) => el("button", {
          class: `matrix-cell ${allowed.has(String(role.id)) ? "allowed" : ""}`,
          type: "button",
          title: allowed.has(String(role.id)) ? "مسموح" : "غير مسموح",
          text: allowed.has(String(role.id)) ? "●" : "—",
          onClick: () => openCommandDetail(command),
        })),
      ));
    });
    return table;
  }
  function insertVariable(textarea, value) {
    const start = textarea.selectionStart ?? textarea.value.length;
    const end = textarea.selectionEnd ?? start;
    textarea.setRangeText(value, start, end, "end");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
    textarea.focus();
    pulse();
  }
  function setRuleForm(rule = null) {
    const form = $("#auto-responder-form");
    if (!form) return;
    form.dataset.ruleId = rule?.id || "";
    form.elements.trigger.value = rule?.trigger || "";
    form.elements.response.value = rule?.response || "";
    form.elements.cooldown_seconds.value = rule?.cooldown_seconds ?? 5;
    form.elements.channel_id.value = rule?.channel_id || "";
    form.elements.target_type.value = rule?.target_type || "everyone";
    form.elements.target_role_id.value = rule?.target_type === "role" ? String(rule?.target_id || "") : "";
    if (form._setAutoMember) {
      form._setAutoMember(rule?.target_type === "user" ? String(rule?.target_id || "") : "");
    } else {
      form.elements.target_user_id.value = rule?.target_type === "user" ? String(rule?.target_id || "") : "";
    }
    if (form._setAutoReaction) {
      form._setAutoReaction(rule?.reaction_emoji || "");
    } else {
      form.elements.reaction_emoji.value = rule?.reaction_emoji || "";
    }
    updateAutoTargetFields(form);
    form.elements.trigger.dispatchEvent(new Event("input", { bubbles: true }));
    form.elements.response.dispatchEvent(new Event("input", { bubbles: true }));
    form.querySelectorAll("[data-match-type]").forEach((button) => {
      button.classList.toggle("active", button.dataset.matchType === (rule?.match_type || "exact"));
    });
    const title = $("#auto-form-title");
    if (title) title.textContent = rule ? "تعديل قاعدة الرد" : "إنشاء رد تلقائي";
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  function updateAutoTargetFields(form) {
    const type = form.elements.target_type.value;
    form.querySelector(".auto-role-target")?.toggleAttribute("hidden", type !== "role");
    form.querySelector(".auto-user-target")?.toggleAttribute("hidden", type !== "user");
  }
  async function saveAutoResponder(form) {
    const selected = form.querySelector(".match-badge.active")?.dataset.matchType || "exact";
    const body = {
      trigger: form.elements.trigger.value.trim(),
      match_type: selected,
      response: form.elements.response.value,
      cooldown_seconds: Number(form.elements.cooldown_seconds.value),
      channel_id: form.elements.channel_id.value || null,
      target_type: form.elements.target_type.value,
      target_id: form.elements.target_type.value === "role"
        ? form.elements.target_role_id.value
        : form.elements.target_type.value === "user"
          ? form.elements.target_user_id.value.trim()
          : 0,
      reaction_emoji: form.elements.reaction_emoji.value.trim(),
    };
    if (!body.trigger || (!body.response.trim() && !body.reaction_emoji)) {
      toast("أدخل المشغل ونص الرد أو اختر إيموجي التفاعل");
      return;
    }
    try {
      const r = await api(`api/guild/${state.guild.id}/auto-responses`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر حفظ قاعدة الرد");
        return;
      }
      const index = state.autoResponses.findIndex((item) => String(item.id) === String(data.rule.id));
      if (index >= 0) state.autoResponses[index] = data.rule;
      else state.autoResponses.push(data.rule);
      pulse();
      toast("✅ تم حفظ قاعدة الرد وتفعيلها", "success", 2500);
      renderPage();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
    }
  }
  async function deleteAutoResponder(rule) {
    if (!confirm(`حذف قاعدة «${rule.trigger}»؟`)) return;
    try {
      const r = await api(`api/guild/${state.guild.id}/auto-responses/${rule.id}`, {
        method: "DELETE",
        headers: { "X-CSRF-Token": state.session.csrf },
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.error === "auto_responder_not_found" ? "القاعدة غير موجودة" : "تعذر حذف القاعدة");
        return;
      }
      state.autoResponses = state.autoResponses.filter((item) => String(item.id) !== String(rule.id));
      pulse();
      toast("تم حذف قاعدة الرد", "success", 2200);
      renderPage();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
    }
  }
  function formatDuration(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "—";
    const total = Math.max(0, Math.round(Number(seconds)));
    if (total < 60) return `${total}ث`;
    if (total < 3600) return `${Math.round(total / 60)}د`;
    return `${(total / 3600).toFixed(1)}س`;
  }
  async function refreshTickets() {
    const id = state.guild.id;
    try {
      const [active, archive, kpis, canned] = await Promise.all([
        api(`api/guild/${id}/tickets/active`),
        api(`api/guild/${id}/tickets/archive?q=${encodeURIComponent(state.ticketSearch)}`),
        api(`api/guild/${id}/tickets/kpis`),
        api(`api/guild/${id}/tickets/canned`),
      ]);
      state.tickets = {
        active: active.ok ? (await active.json()).tickets || [] : state.tickets.active,
        archive: archive.ok ? (await archive.json()).tickets || [] : state.tickets.archive,
        kpis: kpis.ok ? (await kpis.json()).kpis || [] : state.tickets.kpis,
        canned: canned.ok ? (await canned.json()).responses || [] : state.tickets.canned,
      };
      renderPage();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر تحديث مركز التذاكر");
    }
  }
  async function deployTicketPanel(form) {
    const channelId = form.elements.target_channel_id.value;
    if (!channelId) return toast("اختر قناة نشر اللوحة");
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/deploy`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({
          target_channel_id: channelId,
          categories: state.ticketCategories,
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر نشر لوحة التذاكر");
        return;
      }
      pulse();
      toast("🚀 نُشرت لوحة التذاكر للسيرفر", "success", 3000);
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال لنشر لوحة التذاكر");
    }
  }
  const ticketStatusLabels = {
    active: "قيد المعالجة",
    waiting_user: "بانتظار العميل",
    waiting_staff: "بانتظار فريق الدعم",
    closed: "مغلقة",
  };
  const ticketPriorityLabels = {
    normal: "عادية",
    high: "عالية",
    management: "تصعيد إداري",
  };
  async function ticketAction(ticket, action, payload = {}) {
    let staffId = null;
    if (action === "reassign") {
      staffId = prompt("أدخل Discord ID للموظف الجديد:", ticket.claimed_by || "");
      if (!staffId) return;
    }
    if (action === "close" && !confirm(`إغلاق التذكرة #${ticket.id} وأرشفتها؟`)) return null;
    try {
      const r = await writeApi(`api/guild/${state.guild.id}/tickets/action`, {
          ticket_id: ticket.id,
          action,
          staff_id: staffId,
          reason: "أُغلقت من لوحة الإدارة",
          ...payload,
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر تنفيذ الإجراء");
        return null;
      }
      pulse();
      const messages = {
        close: "تم إغلاق التذكرة وأرشفتها",
        reassign: "تمت إعادة إسناد التذكرة",
        reopen: "تمت إعادة فتح التذكرة",
        note: "تم حفظ الملاحظة الداخلية",
        status: "تم تحديث حالة التذكرة",
        priority: "تم تحديث أولوية التذكرة",
      };
      toast(messages[action] || "تم تحديث التذكرة", "success", 2400);
      await refreshTickets();
      return data.ticket || data.result || null;
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
      return null;
    }
  }
  async function openTicketDetail(ticket) {
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/detail/${ticket.id}`);
      const data = await r.json();
      if (!r.ok || !data.ticket) return toast("تعذر تحميل تفاصيل التذكرة");
      const current = data.ticket;
      const notes = data.notes || [];
      const closeDrawer = () => $(".ticket-drawer")?.remove();
      const statusSelect = el(
        "select",
        { class: "ticket-detail-select", "aria-label": "حالة التذكرة" },
        Object.entries(ticketStatusLabels).map(([value, label]) =>
          el("option", { value, text: label }),
        ),
      );
      statusSelect.value = current.status || "active";
      statusSelect.disabled = current.status === "closed";
      statusSelect.onchange = async () => {
        await ticketAction(current, "status", { status: statusSelect.value });
        closeDrawer();
      };
      const prioritySelect = el(
        "select",
        { class: "ticket-detail-select", "aria-label": "أولوية التذكرة" },
        Object.entries(ticketPriorityLabels).map(([value, label]) =>
          el("option", { value, text: label }),
        ),
      );
      prioritySelect.value = current.priority || "normal";
      prioritySelect.disabled = current.status === "closed";
      prioritySelect.onchange = async () => {
        await ticketAction(current, "priority", { priority: prioritySelect.value });
        closeDrawer();
      };
      const noteForm = el("form", { class: "ticket-note-form" },
        el("textarea", {
          name: "content",
          class: "studio-textarea",
          maxlength: "2000",
          placeholder: "ملاحظة لا تظهر لصاحب التذكرة…",
          required: true,
        }),
        el("button", { class: "btn primary", type: "submit", text: "حفظ الملاحظة" }),
      );
      noteForm.onsubmit = async (event) => {
        event.preventDefault();
        const content = noteForm.elements.content.value.trim();
        if (!content) return;
        await ticketAction(current, "note", { content });
        closeDrawer();
        await openTicketDetail(current);
      };
      const notesList = el("div", { class: "ticket-notes-list" });
      if (!notes.length) {
        notesList.append(el("div", { class: "empty studio-empty", text: "لا توجد ملاحظات داخلية" }));
      } else {
        notes.forEach((note) => notesList.append(el("article", { class: "ticket-note" },
          el("div", { class: "ticket-note-meta", text: `موظف #${note.staff_id} · ${note.created_at || ""}` }),
          el("p", { text: note.content }),
        )));
      }
      const intake = el("div", { class: "ticket-intake-grid" });
      Object.entries(current.intake_data || {}).forEach(([key, value]) => intake.append(
        el("div", { class: "ticket-intake-item" },
          el("small", { text: key }),
          el("strong", { text: String(value || "—") }),
        ),
      ));
      if (!intake.children.length) intake.append(el("small", { class: "muted", text: "لا توجد بيانات إضافية" }));
      const actions = el("div", { class: "ticket-detail-actions" },
        el("a", {
          class: "btn ghost",
          href: `https://discord.com/channels/${state.guild.id}/${current.channel_id}`,
          target: "_blank",
          text: "فتح القناة ↗",
        }),
      );
      if (current.status === "closed") {
        actions.append(el("button", {
          class: "btn primary",
          type: "button",
          text: "إعادة فتح التذكرة",
          onClick: async () => { await ticketAction(current, "reopen"); closeDrawer(); },
        }));
      } else {
        actions.append(el("button", {
          class: "btn danger",
          type: "button",
          text: "إغلاق وأرشفة",
          onClick: async () => { await ticketAction(current, "close"); closeDrawer(); },
        }));
      }
      const drawer = el("aside", { class: "ticket-drawer ticket-detail-drawer", role: "dialog", "aria-modal": "true" },
        el("div", { class: "ticket-drawer-head" },
          el("div", {},
            el("span", { class: "eyebrow", text: `${current.category_label} / TICKET #${current.id}` }),
            el("h3", { text: current.subject }),
          ),
          el("button", { class: "icon-action", type: "button", text: "×", "aria-label": "إغلاق", onClick: closeDrawer }),
        ),
        el("div", { class: "ticket-detail-body" },
          el("div", { class: "ticket-detail-summary" },
            el("span", { class: `priority-tag ${current.priority || "normal"}`, text: ticketPriorityLabels[current.priority] || current.priority || "عادية" }),
            el("span", { class: "status-tag", text: ticketStatusLabels[current.status] || current.status }),
            el("span", { class: "ticket-detail-id", text: `العضو #${current.user_id}` }),
          ),
          el("p", { class: "ticket-detail-description", text: current.details || "بدون تفاصيل" }),
          el("div", { class: "ticket-detail-controls" },
            el("label", {}, "الحالة", statusSelect),
            el("label", {}, "الأولوية", prioritySelect),
          ),
          el("div", { class: "ticket-detail-section" }, el("h4", { text: "بيانات نموذج الفتح" }), intake),
          el("div", { class: "ticket-detail-section" }, el("h4", { text: "ملاحظة داخلية" }), noteForm),
          el("div", { class: "ticket-detail-section" }, el("h4", { text: "سجل الملاحظات" }), notesList),
          actions,
        ),
      );
      document.body.append(drawer);
      pulse();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر تحميل تفاصيل التذكرة");
    }
  }
  async function openTicketTranscript(ticket) {
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/transcript/${ticket.id}`);
      if (!r.ok) return toast("السجل غير متاح");
      const source = await r.text();
       const frame = el("iframe", {
         class: "ticket-transcript-frame",
         title: `Transcript #${ticket.id}`,
         sandbox: "",
       });
      frame.srcdoc = source;
      const drawer = el("aside", { class: "ticket-drawer", role: "dialog", "aria-modal": "true" },
        el("div", { class: "ticket-drawer-head" },
          el("div", {}, el("span", { class: "eyebrow", text: "TRANSCRIPT VAULT" }), el("h3", { text: `سجل التذكرة #${ticket.id}` })),
          el("button", { class: "icon-action", type: "button", text: "×", "aria-label": "إغلاق", onClick: () => drawer.remove() }),
        ),
        frame,
      );
      document.body.append(drawer);
      pulse();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر تحميل السجل");
    }
  }
  async function saveCannedResponse(form) {
    const body = {
      id: form.dataset.id || null,
      title: form.elements.title.value.trim(),
      content: form.elements.content.value.trim(),
      category: form.elements.category.value.trim() || "عام",
      shortcut: form.elements.shortcut.value.trim() || null,
      sticker_id: form.elements.sticker_id.value || null,
    };
    if (!body.title || !body.content) return toast("أدخل عنوان ونص الرد الجاهز");
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/canned`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify(body),
      });
      const data = await r.json();
      if (!r.ok) return toast(data.fields ? Object.values(data.fields)[0] : "تعذر حفظ الرد الجاهز");
      pulse();
      toast("تم حفظ الرد الجاهز", "success", 2000);
      await refreshTickets();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
    }
  }
  async function deleteCannedResponse(item) {
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/canned`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({ action: "delete", id: item.id }),
      });
      if (!r.ok) return toast("تعذر حذف الرد الجاهز");
      await refreshTickets();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
    }
  }
  function ticketCategoryEditor() {
    const wrap = el("div", { class: "ticket-category-list" });
    state.ticketCategories.forEach((category, index) => {
      const label = el("input", { class: "studio-input", value: category.label, maxlength: "80" });
      label.oninput = () => { state.ticketCategories[index].label = label.value; };
      const emoji = el("input", { class: "studio-input ticket-emoji-input", value: category.emoji || "🎫", maxlength: "2", "aria-label": "رمز التصنيف" });
      emoji.oninput = () => { state.ticketCategories[index].emoji = emoji.value || "🎫"; };
      const roles = el("select", { class: "ticket-role-select", multiple: "multiple", "aria-label": `رتب دعم ${category.label}` });
      (state.commandStudio.roles || []).forEach((role) => {
        const option = el("option", { value: role.id }, role.name);
        option.selected = (category.support_role_ids || []).map(String).includes(String(role.id));
        roles.append(option);
      });
      roles.onchange = () => {
        state.ticketCategories[index].support_role_ids = [...roles.selectedOptions].map((option) => option.value);
      };
      const seniorRoles = el("select", { class: "ticket-role-select ticket-senior-role-select", multiple: "multiple", "aria-label": `رتب التصعيد ${category.label}` });
      (state.commandStudio.roles || []).forEach((role) => {
        const option = el("option", { value: role.id }, role.name);
        option.selected = (category.senior_role_ids || []).map(String).includes(String(role.id));
        seniorRoles.append(option);
      });
      seniorRoles.onchange = () => {
        state.ticketCategories[index].senior_role_ids = [...seniorRoles.selectedOptions].map((option) => option.value);
      };
      const fields = el("div", { class: "ticket-intake-editor" });
      const renderFields = () => {
        fields.replaceChildren();
        const intakeFields = category.intake_fields || [];
        intakeFields.forEach((field, fieldIndex) => {
          const key = el("input", { class: "studio-input", value: field.key || `field_${fieldIndex + 1}`, maxlength: "40", placeholder: "المفتاح" });
          const fieldLabel = el("input", { class: "studio-input", value: field.label || "", maxlength: "45", placeholder: "اسم الحقل" });
          const placeholder = el("input", { class: "studio-input", value: field.placeholder || "", maxlength: "100", placeholder: "النص الإرشادي" });
          const required = el("input", { type: "checkbox", checked: field.required === true });
          key.oninput = () => { field.key = key.value; };
          fieldLabel.oninput = () => { field.label = fieldLabel.value; };
          placeholder.oninput = () => { field.placeholder = placeholder.value; };
          required.onchange = () => { field.required = required.checked; };
          fields.append(el("div", { class: "ticket-intake-row" },
            key, fieldLabel, placeholder,
            el("label", { class: "ticket-required-toggle" }, required, "إلزامي"),
            el("button", { class: "icon-action danger", type: "button", text: "×", title: "حذف الحقل", onClick: () => {
              category.intake_fields.splice(fieldIndex, 1);
              renderFields();
            } }),
          ));
        });
        if (intakeFields.length < 3) {
          fields.append(el("button", { class: "btn ghost ticket-add-field", type: "button", text: "＋ إضافة حقل في نموذج الفتح", onClick: () => {
            category.intake_fields = category.intake_fields || [];
            category.intake_fields.push({ key: `field_${category.intake_fields.length + 1}`, label: "", placeholder: "", required: false });
            renderFields();
          } }));
        }
      };
      category.intake_fields = Array.isArray(category.intake_fields) ? category.intake_fields : [];
      category.support_role_ids = Array.isArray(category.support_role_ids) ? category.support_role_ids : [];
      category.senior_role_ids = Array.isArray(category.senior_role_ids) ? category.senior_role_ids : [];
      renderFields();
      wrap.append(el("div", { class: "ticket-category-row" },
        el("div", { class: "ticket-category-head" },
          el("span", { class: "ticket-category-index", text: String(index + 1).padStart(2, "0") }),
          el("span", { class: "ticket-category-emoji", text: category.emoji }),
          emoji,
          el("button", {
            class: "icon-action danger ticket-remove-category",
            type: "button",
            text: "×",
            title: state.ticketCategories.length > 1 ? "حذف القسم" : "يجب إبقاء قسم واحد على الأقل",
            disabled: state.ticketCategories.length <= 1,
            onClick: () => {
              if (state.ticketCategories.length <= 1) return toast("يجب إبقاء قسم دعم واحد على الأقل");
              if (!confirm(`حذف قسم «${category.label || "بدون اسم"}»؟`)) return;
              state.ticketCategories.splice(index, 1);
              renderPage();
            },
          }),
        ),
        el("label", { class: "ticket-editor-label" }, "اسم القسم", label),
        el("label", { class: "ticket-editor-label" }, "فريق الدعم", roles),
        el("label", { class: "ticket-editor-label" }, "رتب التصعيد", seniorRoles),
        el("small", { class: "ticket-field-caption", text: "الرتب المحددة تمنح صلاحية متابعة هذا القسم والتصعيد الإداري." }),
        el("small", { class: "ticket-field-caption", text: "حقول نموذج الفتح (اختيارية، حتى 3)" }),
        fields,
      ));
    });
    return wrap;
  }
  function ticketsView() {
    const studio = state.commandStudio || { channels: [] };
    const launchForm = el("form", { class: "ticket-launcher-form" },
      el("div", { class: "ticket-preview-card" },
        el("div", { class: "ticket-preview-glow" }),
        el("span", { class: "eyebrow", text: "LIVE LAUNCHER PREVIEW" }),
        el("h3", { text: "🎫 مركز الدعم والتذاكر" }),
        el("p", { text: "اختر التصنيف المناسب وسيتولى فريق الدعم متابعة طلبك في قناة خاصة." }),
        el("div", { class: "ticket-preview-buttons" },
          state.ticketCategories.map((category) => el("span", { class: "ticket-preview-button" }, category.emoji, category.label)),
        ),
      ),
      el("label", { class: "ticket-form-label" }, "قناة نشر لوحة التذاكر",
        el("select", { name: "target_channel_id", class: "studio-input" },
          el("option", { value: "" }, "اختر قناة نصية"),
          (studio.channels || []).map((channel) => el("option", { value: channel.id }, `#${channel.name}`)),
        ),
      ),
      el("div", { class: "ticket-category-heading" },
        el("div", {}, el("h4", { text: "تصنيفات التذاكر" }), el("small", { text: "أضف أقسام الدعم وحدد فريق المتابعة ورتب التصعيد لكل قسم." })),
        el("div", { class: "ticket-category-heading-actions" },
          el("span", { class: "live-dot", text: `${state.ticketCategories.length} تصنيفات` }),
          el("button", {
            class: "btn ghost ticket-add-category",
            type: "button",
            text: "＋ قسم جديد",
            onClick: () => {
              if (state.ticketCategories.length >= 25) return toast("لا يمكن إضافة أكثر من 25 قسماً");
              const next = state.ticketCategories.length + 1;
              state.ticketCategories.push({
                key: `support_${Date.now()}_${next}`,
                label: `قسم دعم ${next}`,
                emoji: "🎫",
                support_role_ids: [],
                senior_role_ids: [],
                intake_fields: [],
              });
              renderPage();
            },
          }),
        ),
      ),
      ticketCategoryEditor(),
      el("button", { class: "btn primary ticket-deploy", type: "submit", text: "نشر لوحة التذاكر للسيرفر 🚀" }),
    );
    launchForm.onsubmit = (event) => { event.preventDefault(); deployTicketPanel(launchForm); };

    const kpis = state.tickets.kpis || [];
    const total = kpis.reduce((sum, item) => sum + Number(item.tickets_handled || 0), 0);
    const responseValues = kpis.filter((item) => item.avg_response_seconds != null).map((item) => Number(item.avg_response_seconds));
    const ratingValues = kpis.filter((item) => item.avg_rating != null).map((item) => Number(item.avg_rating));
    const avgResponse = responseValues.length ? responseValues.reduce((a, b) => a + b, 0) / responseValues.length : null;
    const avgRating = ratingValues.length ? ratingValues.reduce((a, b) => a + b, 0) / ratingValues.length : null;
    const kpiCards = el("div", { class: "ticket-kpi-grid" },
      [["⚡", "متوسط أول رد", formatDuration(avgResponse)], ["✅", "التذاكر المحلولة", total], ["★", "رضا الأعضاء", avgRating == null ? "—" : `${avgRating.toFixed(1)}/5`]].map(([icon, label, value]) =>
        el("article", { class: "ticket-kpi-card" }, el("span", { class: "kpi-icon", text: icon }), el("small", { text: label }), el("strong", { text: String(value) })),
      ),
    );
    const active = el("div", { class: "ticket-radar-grid" });
    const queue = state.tickets.active.reduce((result, ticket) => {
      const status = ticket.status || "active";
      result[status] = (result[status] || 0) + 1;
      return result;
    }, {});
    const queueStats = el("div", { class: "ticket-queue-stats" },
      [["active", "قيد المعالجة"], ["waiting_staff", "بانتظار الدعم"], ["waiting_user", "بانتظار العميل"]].map(([key, label]) =>
        el("button", { class: `queue-stat ${state.ticketStatusFilter === key ? "selected" : ""}`, type: "button", onClick: () => {
          state.ticketStatusFilter = state.ticketStatusFilter === key ? "all" : key;
          renderPage();
        } }, el("strong", { text: String(queue[key] || 0) }), el("small", { text: label })),
      ),
    );
    active.append(queueStats);
    const filteredTickets = state.tickets.active.filter((ticket) =>
      state.ticketStatusFilter === "all" || (ticket.status || "active") === state.ticketStatusFilter
    );
    if (!filteredTickets.length) active.append(el("div", { class: "empty studio-empty", text: "لا توجد تذاكر مطابقة للفترة الحالية" }));
    filteredTickets.forEach((ticket) => {
      const priority = ticket.priority || "normal";
      const label = ticketPriorityLabels[priority] || priority;
      active.append(el("article", { class: `ticket-radar-card ${priority}` },
        el("div", { class: "ticket-radar-top" }, el("span", { class: `priority-tag ${priority}`, text: label }), el("small", { text: `#${ticket.id}` })),
        el("h4", { text: ticket.subject }),
        el("p", { text: `${ticket.category_label} · ${ticketStatusLabels[ticket.status] || "قيد المعالجة"} · ${ticket.claimed_by ? `مستلمة بواسطة ${ticket.claimed_by}` : "بانتظار الاستلام"}` }),
        el("div", { class: "ticket-radar-actions" },
          el("a", { class: "icon-action", href: `https://discord.com/channels/${state.guild.id}/${ticket.channel_id}`, target: "_blank", text: "↗", title: "فتح القناة" }),
          el("button", { class: "icon-action", type: "button", text: "⇄", title: "إعادة إسناد", onClick: () => ticketAction(ticket, "reassign") }),
          el("button", { class: "icon-action", type: "button", text: "◉", title: "التفاصيل والملاحظات", onClick: () => openTicketDetail(ticket) }),
          el("button", { class: "icon-action danger", type: "button", text: "⌫", title: "إغلاق قسري", onClick: () => ticketAction(ticket, "close") }),
        ),
      ));
    });
    const archiveSearch = el("input", { class: "studio-search", type: "search", placeholder: "ابحث في الأرشيف…", value: state.ticketSearch });
    let searchTimer;
    archiveSearch.oninput = () => {
      state.ticketSearch = archiveSearch.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(refreshTickets, 280);
    };
    const archiveRows = el("div", { class: "ticket-archive-list" });
    if (!state.tickets.archive.length) archiveRows.append(el("div", { class: "empty studio-empty", text: "لا توجد سجلات مغلقة" }));
    state.tickets.archive.forEach((ticket) => archiveRows.append(el("div", { class: "ticket-archive-row" },
      el("div", {}, el("strong", { text: `#${ticket.id} · ${ticket.subject}` }), el("small", { text: `${ticket.category_label} · ${ticket.close_reason || "بدون سبب"}` })),
      el("div", { class: "ticket-archive-actions" },
        el("button", { class: "btn ghost", type: "button", text: "التفاصيل", onClick: () => openTicketDetail(ticket) }),
        el("button", { class: "btn ghost", type: "button", text: "السجل", onClick: () => openTicketTranscript(ticket) }),
      ),
    )));
     const serverEmojis = [
       ...(Array.isArray(state.meta?.emojis) ? state.meta.emojis : []),
       ...(Array.isArray(state.meta?.guild_emojis) ? state.meta.guild_emojis : []),
       ...(Array.isArray(state.guild?.emojis) ? state.guild.emojis : []),
     ];
     const cannedForm = el("form", { class: "canned-form" },
       el("div", { class: "canned-form-heading" },
         el("div", {}, el("span", { class: "eyebrow", text: "REPLY KIT" }), el("h4", { text: "رد سريع للموظفين" })),
         el("small", { text: "يستخدمه الموظف داخل التذكرة عبر /ticket_reply" }),
       ),
       el("div", { class: "canned-form-fields" },
         el("label", { class: "canned-field" }, "العنوان",
           el("input", { name: "title", class: "studio-input", maxlength: "120", placeholder: "سياسة الاسترداد" }),
         ),
         el("label", { class: "canned-field" }, "التصنيف",
           el("input", { name: "category", class: "studio-input", maxlength: "80", placeholder: "عام", value: "عام" }),
         ),
         el("label", { class: "canned-field" }, "الاختصار",
           el("input", { name: "shortcut", class: "studio-input", maxlength: "80", placeholder: "refund أو /refund" }),
         ),
         el("label", { class: "canned-field" }, "ملصق اختياري",
           el("select", { name: "sticker_id", class: "studio-input canned-sticker-select" },
             el("option", { value: "" }, "بدون ملصق"),
             (state.meta?.stickers || []).map((sticker) => el("option", { value: sticker.id }, `◇ ${sticker.name}`)),
           ),
         ),
       ),
       el("div", { class: "canned-token-bar" },
         el("small", { text: "متغيرات قابلة للإدراج" }),
         ["{user}", "{staff}", "{channel}", "{server}", "{count}", "{members}", "{ticket}", "{subject}", "{category}", "{random:أهلاً|مرحباً}"].map((token) =>
           el("button", {
             class: "token-chip",
             type: "button",
             text: token,
             title: `إدراج ${token}`,
             onClick: () => {
               const textarea = cannedForm.elements.content;
               const start = textarea.selectionStart ?? textarea.value.length;
               const end = textarea.selectionEnd ?? start;
               textarea.value = `${textarea.value.slice(0, start)}${token}${textarea.value.slice(end)}`;
               textarea.focus();
               textarea.setSelectionRange(start + token.length, start + token.length);
             },
           }),
         ),
       ),
       el("div", { class: "server-emoji-picker" },
         el("div", { class: "server-emoji-heading" },
           el("span", { class: "eyebrow", text: "SERVER EMOJI" }),
           el("small", { text: serverEmojis.length ? "اختر رمزاً لإدراجه في الرد" : "لا توجد رموز سيرفر مقدمة من الخادم" }),
         ),
         el("div", { class: "server-emoji-list" },
           serverEmojis.length
             ? serverEmojis.slice(0, 40).map((emoji) => {
                 const token = emoji.token || `<:${emoji.name || "emoji"}:${emoji.id || ""}>`;
                 const image = emoji.url || emoji.image || emoji.icon_url;
                 const button = el("button", { class: "server-emoji-token", type: "button", title: `إدراج ${token}`, "aria-label": `إدراج ${token}` });
                 if (image) {
                   const imageNode = el("img", { src: image, alt: emoji.name || "emoji" });
                   imageNode.onerror = () => { imageNode.remove(); button.append(el("span", { text: emoji.name || token })); };
                   button.append(imageNode);
                 } else button.append(el("span", { text: emoji.name || token }));
                 button.onclick = () => insertVariable(cannedForm.elements.content, token);
                 return button;
               })
             : [el("span", { class: "empty-row", text: "سيظهر هنا ما يرسله Discord من رموز السيرفر." })],
         ),
       ),
       el("label", { class: "canned-content-field" }, "نص الرد",
         el("textarea", { name: "content", class: "studio-textarea", maxlength: "2000", rows: "5", placeholder: "أهلاً {user}، سيتابع {staff} طلبك في {channel}…" }),
       ),
       el("div", { class: "canned-form-actions" },
         el("button", { class: "btn ghost canned-cancel", type: "button", text: "تفريغ الحقول", onClick: () => {
           delete cannedForm.dataset.id;
           cannedForm.reset();
           cannedForm.elements.category.value = "عام";
           cannedForm.querySelector(".canned-submit").textContent = "حفظ الرد الجاهز";
         } }),
         el("button", { class: "btn primary canned-submit", type: "submit", text: "حفظ الرد الجاهز" }),
       ),
     );
    cannedForm.onsubmit = (event) => { event.preventDefault(); saveCannedResponse(cannedForm); };
    const cannedList = el("div", { class: "canned-list" });
     state.tickets.canned.forEach((item) => cannedList.append(el("div", { class: "canned-row" },
        el("div", { class: "canned-row-copy" },
          el("div", { class: "canned-row-title" },
            el("strong", { text: item.title }),
            ...(item.shortcut ? [el("code", { class: "canned-shortcut", text: item.shortcut })] : []),
          ),
          el("div", { class: "canned-row-meta" },
            el("span", { text: item.category || "عام" }),
            ...(item.sticker_id ? [el("span", { class: "canned-sticker-badge", text: "◇ ملصق مرفق" })] : []),
          ),
          el("p", { text: item.content }),
        ),
       el("div", { class: "canned-actions" },
         el("button", {
           class: "icon-action",
           type: "button",
           text: "✎",
           title: "تحرير الرد",
           onClick: () => {
             cannedForm.dataset.id = item.id;
             cannedForm.elements.title.value = item.title || "";
             cannedForm.elements.category.value = item.category || "عام";
              cannedForm.elements.shortcut.value = item.shortcut || "";
              cannedForm.elements.sticker_id.value = item.sticker_id || "";
             cannedForm.elements.content.value = item.content || "";
             cannedForm.querySelector(".canned-submit").textContent = "تحديث الرد";
             cannedForm.scrollIntoView({ behavior: "smooth", block: "center" });
             cannedForm.elements.title.focus();
           },
         }),
         el("button", { class: "icon-action danger", type: "button", text: "⌫", title: "حذف الرد", onClick: () => deleteCannedResponse(item) }),
       ),
     )));
    return el("section", { id: "view-tickets", class: "tickets-view" },
      el("div", { class: "studio-hero tickets-hero" },
        el("div", { class: "eyebrow", text: `${state.guild.name} / HELP DESK` }),
        el("h2", { text: "منصة التذاكر والأرشيف" }),
        el("p", { text: "انشر لوحة الدعم، راقب سرعة الفريق، وافتح المحادثات المغلقة داخل لوحة AMOLED نفسها." }),
      ),
      card("استوديو لوحة الدعم", launchForm),
      el("section", { class: "ticket-kpi-section" }, el("div", { class: "section-heading" }, el("div", {}, el("div", { class: "eyebrow", text: "STAFF VELOCITY" }), el("h3", { text: "مؤشرات فريق الدعم" })), el("span", { class: "live-dot", text: `${kpis.length} موظفين` })), kpiCards),
       el("section", { class: "ticket-radar-section" }, el("div", { class: "section-heading" }, el("div", {}, el("div", { class: "eyebrow", text: "ACTIVE RADAR" }), el("h3", { text: "التذاكر النشطة" })), el("span", { class: "live-dot", text: `${state.tickets.active.length} مفتوحة` })), active),
       card("خزينة السجلات", el("div", { class: "ticket-vault" }, archiveSearch, archiveRows)),
       card("مكتبة الردود السريعة", el("div", { class: "canned-drawer" }, cannedForm, cannedList)),
    );
  }
  function commandsView() {
    const studio = state.commandStudio || { commands: [], roles: [], channels: [] };
    const prefixInput = el("input", {
      class: "prefix-input",
      value: state.draft?.prefix || "!",
      maxlength: "5",
      "aria-label": "بادئة الأوامر",
    });
    const prefixFeedback = el("span", { class: "prefix-feedback", text: "يؤثر فوراً على أوامر السيرفر" });
    const prefixForm = el("form", { class: "prefix-pill" },
      el("div", { class: "prefix-mark", text: "⌁" }),
      el("div", { class: "prefix-copy" },
        el("span", { class: "eyebrow", text: "DYNAMIC PREFIX" }),
        el("strong", { text: "بادئة الأوامر" }),
        prefixFeedback,
      ),
      prefixInput,
      el("button", { class: "btn prefix-save", type: "submit", text: "تطبيق" }),
    );
    prefixForm.onsubmit = (event) => {
      event.preventDefault();
      saveCommandPrefix(prefixInput, prefixFeedback);
    };
    const prefixExamples = el("div", { class: "prefix-examples" });
    const renderPrefixExamples = () => {
      const prefix = prefixInput.value.trim() || "!";
      prefixExamples.replaceChildren(
        el("span", { class: "eyebrow", text: "LIVE EXAMPLES" }),
        el("code", { text: `${prefix}help` }),
        el("code", { text: `${prefix}ticket status` }),
        el("code", { text: `${prefix}rules` }),
      );
    };
    prefixInput.oninput = renderPrefixExamples;
    renderPrefixExamples();
    const commandTabs = el("nav", { class: "command-tabs", "aria-label": "أقسام مركز الأوامر" });
    [
      ["commands", "الأوامر", "command-panel"],
      ["policy", "مصفوفة السياسات", "policy-panel"],
      ["responders", "الردود التلقائية", "auto-responder-panel"],
      ["audit", "النشاط والتدقيق", "command-audit-panel"],
    ].forEach(([key, label, target]) => commandTabs.append(el("button", {
      class: `command-tab ${state.commandTab === key ? "active" : ""}`,
      type: "button",
      "aria-selected": String(state.commandTab === key),
      text: label,
      onClick: () => {
        state.commandTab = key;
        document.getElementById(target)?.scrollIntoView({ behavior: "smooth", block: "start" });
        commandTabs.querySelectorAll(".command-tab").forEach((item) => item.classList.toggle("active", item.textContent === label));
      },
    })));
    const commandMetrics = el("div", { class: "command-metrics" },
      el("article", { class: "command-metric accent-blue" }, el("small", { text: "إجمالي الأوامر" }), el("strong", { text: String(studio.commands.length) }), el("span", { text: "مسجلة في البوت" })),
      el("article", { class: "command-metric accent-green" }, el("small", { text: "متاحة الآن" }), el("strong", { text: String(studio.commands.filter((command) => command.enabled !== false).length) }), el("span", { text: "أمر مفعّل" })),
      el("article", { class: "command-metric accent-amber" }, el("small", { text: "تحتاج مراجعة" }), el("strong", { text: String(studio.commands.filter((command) => commandPermissionWarnings(command).length).length) }), el("span", { text: "تحذير صلاحيات" })),
      el("article", { class: "command-metric accent-purple" }, el("small", { text: "ردود تلقائية" }), el("strong", { text: String(state.autoResponses.length) }), el("span", { text: "قاعدة نشطة" })),
    );
    const search = el("input", {
      class: "studio-search",
      type: "search",
      placeholder: "ابحث عن أمر أو Cog…",
      value: state.commandSearch,
      "aria-label": "بحث في الأوامر",
    });
    search.oninput = () => {
      state.commandSearch = search.value;
      const rows = $("#command-rows");
      if (rows) rows.replaceWith(commandRows());
    };
    const cogChoices = [...new Set(studio.commands.map((command) => command.cog || "Commands"))].sort();
    const filterSelect = (label, value, options, key) => {
      const select = el("select", { class: "studio-input command-filter", "aria-label": label },
        options.map(([optionValue, optionLabel]) => el("option", { value: optionValue, text: optionLabel })),
      );
      select.value = value;
      select.onchange = () => {
        state[key] = select.value;
        renderPage();
      };
      return select;
    };
    const filterBar = el("div", { class: "command-filter-bar" },
      filterSelect("تصفية حسب Cog", state.commandCogFilter, [["all", "كل الـ Cogs"], ...cogChoices.map((cog) => [cog, cog])], "commandCogFilter"),
      filterSelect("تصفية حسب الحالة", state.commandStatusFilter, [["all", "كل الحالات"], ["enabled", "مفعّلة"], ["disabled", "معطّلة"], ["warning", "تحذير صلاحيات"]], "commandStatusFilter"),
      filterSelect("تصفية حسب الرتبة", state.commandRoleFilter, [["all", "كل الرتب"], ...(studio.roles || []).map((role) => [String(role.id), `@${role.name}`])], "commandRoleFilter"),
    );
    const quickFilters = el("div", { class: "command-quick-filters" },
      [["all", "الكل"], ["enabled", "مفعل"], ["disabled", "معطل"]].map(([value, label]) => el("button", {
        class: `command-quick-filter${state.commandStatusFilter === value ? " active" : ""}`,
        type: "button",
        text: label,
        onClick: () => {
          state.commandStatusFilter = value;
          renderPage();
        },
      })),
    );
    const bulkBar = el("div", { class: "command-bulk-bar" },
      el("label", { class: "bulk-select-all" },
        el("input", { type: "checkbox", checked: commandListForWorkspace().length > 0 && commandListForWorkspace().every((command) => state.selectedCommandIds.includes(String(command.command_name))), onChange: (event) => {
          const ids = commandListForWorkspace().map((command) => String(command.command_name));
          state.selectedCommandIds = event.target.checked ? [...new Set([...state.selectedCommandIds, ...ids])] : state.selectedCommandIds.filter((id) => !ids.includes(id));
          renderPage();
        } }),
        el("span", { text: `${state.selectedCommandIds.length} محدد` }),
      ),
      el("button", { class: "btn ghost", type: "button", disabled: !state.selectedCommandIds.length, text: "تفعيل المحدد", onClick: () => bulkUpdateCommands(true) }),
      el("button", { class: "btn ghost danger-outline", type: "button", disabled: !state.selectedCommandIds.length, text: "تعطيل المحدد", onClick: () => bulkUpdateCommands(false) }),
    );
    const shortcutCommand = studio.commands.find((command) => String(command.command_name) === String(state.shortcutCommandId))
      || studio.commands[0];
    if (shortcutCommand && !state.shortcutCommandId) state.shortcutCommandId = shortcutCommand.command_name;
    const shortcutValue = state.shortcutInputText != null
      ? state.shortcutInputText
      : (shortcutCommand ? commandShortcuts(shortcutCommand).map((item) => item.trigger).join("، ") : "");
    const shortcutCommandSelect = el("select", { class: "studio-input command-shortcut-command", "aria-label": "اختر الأمر لإدارة اختصاراته" },
      studio.commands.map((command) => el("option", {
        value: command.command_name,
        text: `/${command.command_name} · ${command.cog || "Commands"}`,
      })),
    );
    if (shortcutCommand) shortcutCommandSelect.value = shortcutCommand.command_name;
    shortcutCommandSelect.onchange = () => {
      state.shortcutCommandId = shortcutCommandSelect.value;
      const next = studio.commands.find((command) => String(command.command_name) === String(state.shortcutCommandId));
      state.shortcutInputText = next ? commandShortcuts(next).map((item) => item.trigger).join("، ") : "";
      renderPage();
    };
    const shortcutInput = el("textarea", {
      class: "studio-textarea command-shortcut-input",
      rows: "2",
      placeholder: "مثال: عيب، تحذير، انذار",
      "aria-label": "اختصارات الأمر",
      text: shortcutValue,
    });
    shortcutInput.oninput = () => { state.shortcutInputText = shortcutInput.value; };
    const shortcutWorkbench = el("section", { class: "command-shortcut-workbench" },
      el("div", { class: "command-shortcut-workbench-head" },
        el("div", {},
          el("div", { class: "eyebrow", text: "COMMAND ALIASES" }),
          el("h3", { text: "اختصارات الأوامر" }),
          el("p", { text: "اختر أمراً واكتب أكثر من اسم بديل له. ستظهر الاختصارات في البطاقة وتُحفظ دفعة واحدة." }),
        ),
        el("span", { class: "command-shortcut-count", text: shortcutCommand ? `${commandShortcuts(shortcutCommand).length}/20` : "0/20" }),
      ),
      el("div", { class: "command-shortcut-editor" },
        shortcutCommandSelect,
        shortcutInput,
        el("button", { class: "btn primary command-shortcut-save", type: "button", text: "حفظ الاختصارات", disabled: !shortcutCommand, onClick: () => shortcutCommand && saveCommandShortcuts(shortcutCommand, shortcutInput, { reopen: false }) }),
      ),
      el("small", { class: "command-shortcut-hint", text: "مثال: اختر /warn ثم اكتب: عيب، تحذير، انذار. اكتب كل الاختصارات بفواصل أو أسطر." }),
    );
    const commandPanel = card("قائمة الأوامر",
      el("div", { class: "command-panel" },
        el("div", { class: "commands-list-toolbar" }, search, quickFilters),
        filterBar,
        bulkBar,
        commandRows(),
      ),
    );
    commandPanel.id = "command-panel";
    const responderRoles = state.autoResponderMeta?.roles || studio.roles || [];
    const responderEmojis = state.autoResponderMeta?.emojis || [];
    const responderMembers = state.autoResponderMeta?.members || state.meta?.members || [];
    const targetUserId = el("input", { name: "target_user_id", type: "hidden" });
    const memberSearch = el("input", {
      class: "studio-input member-picker-search",
      type: "search",
      placeholder: "ابحث باسم العضو…",
      autocomplete: "off",
      "aria-label": "البحث عن عضو",
    });
    const memberOptions = el("div", { class: "member-picker-options" });
    const memberPicker = el(
      "div",
      { class: "member-picker" },
      memberSearch,
      memberOptions,
      targetUserId,
    );
    const renderMemberOptions = (query = "") => {
      const normalized = query.trim().toLocaleLowerCase();
      const filtered = responderMembers
        .filter((member) => !normalized || String(member.name || "").toLocaleLowerCase().includes(normalized))
        .slice(0, 100);
      memberOptions.replaceChildren(
        ...(filtered.length
          ? filtered.map((member) => el(
              "button",
              {
                type: "button",
                class: `member-picker-option${String(targetUserId.value) === String(member.id) ? " active" : ""}`,
                "data-member-id": member.id,
                onClick: () => {
                  targetUserId.value = String(member.id);
                  memberSearch.value = member.name;
                  memberOptions.querySelectorAll("[data-member-id]").forEach((item) => item.classList.remove("active"));
                  memberOptions.querySelector(`[data-member-id="${member.id}"]`)?.classList.add("active");
                  pulse();
                },
              },
              el("img", { src: member.avatar || "", alt: "", loading: "lazy" }),
              el("span", { text: member.name }),
            ))
          : [el("small", { class: "hint", text: "لا يوجد عضو مطابق" })]),
      );
    };
    memberSearch.oninput = () => renderMemberOptions(memberSearch.value);
    const setAutoMember = (memberId = "") => {
      targetUserId.value = String(memberId || "");
      const selected = responderMembers.find((member) => String(member.id) === String(memberId));
      memberSearch.value = selected?.name || "";
      renderMemberOptions(memberSearch.value);
    };
    renderMemberOptions();
    const targetScope = el(
      "div",
      { class: "auto-target-panel" },
      el("label", { text: "نطاق الاستهداف (Target Scope)" }),
      el(
        "select",
        { name: "target_type", class: "studio-input" },
        el("option", { value: "everyone" }, "الجميع (Everyone)"),
        el("option", { value: "role" }, "رتبة مخصصة (By Role)"),
        el("option", { value: "user" }, "عضو محدد (Specific Member)"),
      ),
      el(
        "label",
        { class: "auto-role-target", hidden: true },
        "الرتبة المستهدفة",
        el(
          "select",
          { name: "target_role_id", class: "studio-input" },
          el("option", { value: "" }, "اختر رتبة"),
          responderRoles.map((role) => el("option", { value: role.id }, `@${role.name}`)),
        ),
      ),
      el(
        "label",
        { class: "auto-user-target", hidden: true },
        "العضو المستهدف",
        memberPicker,
      ),
    );
    const reactionInput = el("input", { name: "reaction_emoji", type: "hidden" });
    const reactionManualInput = el("input", {
      class: "studio-input reaction-manual-input",
      maxlength: "100",
      placeholder: "أو اكتب إيموجي Unicode مثل 👍",
    });
    const reactionPreview = el("span", { class: "reaction-preview-empty", text: "لم يتم الاختيار" });
    const emojiGrid = el("div", { class: "emoji-picker-grid" });
    const emojiSearch = el("input", {
      class: "studio-input emoji-picker-search",
      type: "search",
      placeholder: "ابحث باسم الإيموجي…",
      autocomplete: "off",
      "aria-label": "البحث عن إيموجي",
    });
    const emojiPopover = el(
      "div",
      { class: "emoji-picker-popover", hidden: true },
      emojiSearch,
      emojiGrid,
    );
    const emojiToggle = el("button", {
      class: "emoji-picker-toggle",
      type: "button",
      "aria-expanded": "false",
      text: "😀 اختيار إيموجي التفاعل (انقر لفتح القائمة) ▼",
      onClick: () => {
        const open = emojiPopover.hasAttribute("hidden");
        emojiPopover.toggleAttribute("hidden", !open);
        emojiToggle.setAttribute("aria-expanded", String(open));
        if (open) emojiSearch.focus();
      },
    });
    const reactionPreviewPill = el("div", { class: "reaction-preview-pill", hidden: true }, reactionPreview);
    const setAutoReaction = (value = "", emoji = null) => {
      const normalized = String(value || "").trim();
      reactionInput.value = normalized;
      reactionManualInput.value = normalized.startsWith("<") ? "" : normalized;
      reactionPreviewPill.toggleAttribute("hidden", !normalized);
      reactionPreview.replaceChildren();
      if (!normalized) {
        reactionPreview.textContent = "لم يتم الاختيار";
      } else if (emoji?.url) {
        reactionPreview.append(
          el("img", { src: emoji.url, alt: emoji.name || "" }),
          el("span", { text: emoji.name || normalized }),
        );
      } else {
        reactionPreview.textContent = normalized;
      }
      if (normalized) {
        const clear = el("button", {
          class: "reaction-preview-clear",
          type: "button",
          title: "مسح الإيموجي",
          text: "✕",
          onClick: (event) => {
            event.stopPropagation();
            setAutoReaction("");
          },
        });
        reactionPreviewPill.append(clear);
      }
      emojiGrid.querySelectorAll("[data-reaction-chip]").forEach((chip) => {
        chip.classList.toggle("active", chip.dataset.reactionChip === normalized);
      });
    };
    const renderEmojiGrid = (query = "") => {
      const normalized = query.trim().toLocaleLowerCase();
      const filtered = responderEmojis.filter((emoji) => !normalized || String(emoji.name || "").toLocaleLowerCase().includes(normalized));
      emojiGrid.replaceChildren(
        ...(filtered.length
          ? filtered.map((emoji) => {
              const token = emoji.token || `<${emoji.animated ? "a" : ""}:${emoji.name}:${emoji.id}>`;
              return el("button", {
                class: "emoji-picker-chip",
                type: "button",
                "data-reaction-chip": token,
                title: emoji.name,
                onClick: () => {
                  setAutoReaction(token, emoji);
                  emojiPopover.setAttribute("hidden", "");
                  emojiToggle.setAttribute("aria-expanded", "false");
                  if (navigator.vibrate) navigator.vibrate(10);
                },
              }, el("img", { src: emoji.url, alt: emoji.name }), el("span", { text: emoji.name }));
            })
          : [el("small", { class: "hint", text: "لا يوجد إيموجي مطابق" })]),
      );
    };
    emojiSearch.oninput = () => renderEmojiGrid(emojiSearch.value);
    reactionManualInput.oninput = () => setAutoReaction(reactionManualInput.value);
    renderEmojiGrid();
    const reactionPicker = el(
      "div",
      { class: "auto-reaction-panel" },
      el("label", { text: "إيموجي التفاعل (Reaction Emoji)" }),
      el("div", { class: "reaction-picker-toolbar" }, emojiToggle, reactionPreviewPill),
      emojiPopover,
      reactionManualInput,
      reactionInput,
    );
    const form = el("form", { id: "auto-responder-form", class: "auto-form" },
      el("div", { class: "auto-form-heading" },
        el("div", { class: "eyebrow", text: "TRIGGER ENGINE" }),
        el("h3", { id: "auto-form-title", text: "إنشاء رد تلقائي" }),
        el("p", { text: "حوّل الكلمات المتكررة إلى ردود ذكية قابلة للتخصيص." }),
      ),
      el("label", { text: "المشغل" }),
      el("input", { name: "trigger", class: "studio-input", maxlength: "500", placeholder: "مثال: مرحباً أو ^help$" }),
      el("label", { text: "نوع المطابقة" }),
      el("div", { class: "match-badges" },
        ["exact", "contains", "regex"].map((type, index) => {
          const labels = { exact: "مطابقة تامة", contains: "يحتوي على الكلمة", regex: "تعبير نمطي Regex" };
          const button = el("button", {
            class: `match-badge${index === 0 ? " active" : ""}`,
            type: "button",
            "data-match-type": type,
            text: labels[type],
          });
          button.onclick = () => {
            form.querySelectorAll("[data-match-type]").forEach((item) => item.classList.remove("active"));
            button.classList.add("active");
            pulse();
          };
          return button;
        }),
      ),
      el("label", { text: "نص الرد" }),
      el("textarea", { name: "response", class: "studio-textarea", maxlength: "2000", placeholder: "اكتب الرد هنا…" }),
      el("div", { class: "variable-strip" },
        el("span", { text: "إدراج سريع:" }),
        ["{user}", "{channel}", "{server}", "{random:نعم|لا}"].map((variable) => {
          const chip = el("button", { class: "variable-chip", type: "button", text: variable });
          chip.onclick = () => insertVariable(form.elements.response, variable);
          return chip;
        }),
      ),
      el("div", { class: "auto-form-grid" },
        el("label", {}, "التبريد",
          el("input", { name: "cooldown_seconds", type: "range", min: "0", max: "60", step: "1", value: "5" }),
          el("output", { class: "range-output", text: "5s" }),
        ),
        el("label", {}, "نطاق القناة",
          el("select", { name: "channel_id", class: "studio-input" },
            el("option", { value: "" }, "كل القنوات"),
            (studio.channels || []).map((channel) => el("option", { value: channel.id }, `#${channel.name}`)),
          ),
        ),
      ),
      targetScope,
      reactionPicker,
      el("div", { class: "auto-form-actions" },
        el("button", { class: "btn primary", type: "submit", text: "حفظ القاعدة" }),
        el("button", { class: "btn ghost", type: "button", text: "مسح", onClick: () => setRuleForm() }),
      ),
    );
    const autoPreview = el("section", { class: "auto-live-preview" },
      el("div", { class: "section-heading compact" }, el("div", {}, el("div", { class: "eyebrow", text: "LIVE PREVIEW" }), el("h3", { text: "معاينة الرد" }))),
      el("div", { class: "auto-preview-message", text: "اكتب المشغل والرد لرؤية المعاينة هنا." }),
      el("button", { class: "btn ghost auto-test-button", type: "button", text: "اختبار محلي", onClick: () => {
        const trigger = form.elements.trigger.value.trim() || "المشغل";
        const response = form.elements.response.value.trim() || "لا يوجد رد بعد";
        toast(`اختبار «${trigger}»: ${response.slice(0, 90)}`, "info", 3200);
      } }),
    );
    form.append(autoPreview);
    const updateAutoPreview = () => {
      const trigger = form.elements.trigger.value.trim() || "المشغل";
      const response = form.elements.response.value.trim() || "اكتب نص الرد هنا…";
      autoPreview.querySelector(".auto-preview-message").replaceChildren(
        el("span", { class: "preview-trigger", text: trigger }),
        el("span", { text: response }),
      );
    };
    form.elements.trigger.oninput = updateAutoPreview;
    form.elements.response.oninput = updateAutoPreview;
    form._setAutoMember = setAutoMember;
    form._setAutoReaction = setAutoReaction;
    form.elements.target_type.onchange = () => updateAutoTargetFields(form);
    updateAutoTargetFields(form);
    updateAutoPreview();
    form.elements.cooldown_seconds.oninput = () => {
      form.querySelector(".range-output").textContent = `${form.elements.cooldown_seconds.value}s`;
    };
    form.onsubmit = (event) => {
      event.preventDefault();
      saveAutoResponder(form);
    };
    const cards = el("div", { class: "trigger-grid" });
    if (!state.autoResponses.length) {
      cards.append(el("div", { class: "empty studio-empty", text: "لا توجد ردود تلقائية مفعّلة بعد" }));
    } else {
      state.autoResponses.forEach((rule) => {
        const cardNode = el("article", { class: "trigger-card" },
          el("div", { class: "trigger-card-top" },
            el("span", { class: "trigger-type", text: rule.match_type }),
            el("span", { class: "trigger-count", text: `${rule.execution_count || 0} تنفيذ` }),
          ),
          el("h4", { text: rule.trigger }),
          el("p", { text: rule.response }),
          el("small", { text: `${rule.channel_id ? "قناة محددة" : "كل القنوات"} · تبريد ${rule.cooldown_seconds}s` }),
          el("div", { class: "trigger-actions" },
            el("button", { class: "icon-action", type: "button", title: "نسخ المشغل", text: "⧉", onClick: () => navigator.clipboard?.writeText(rule.trigger).then(() => toast("تم نسخ المشغل", "success", 1600)) }),
            el("button", { class: "icon-action", type: "button", title: "تعديل", text: "✎", onClick: () => setRuleForm(rule) }),
            el("button", { class: "icon-action danger", type: "button", title: "حذف", text: "⌫", onClick: () => deleteAutoResponder(rule) }),
          ),
        );
        cards.append(cardNode);
      });
    }
    const policyPanel = card("Policy Matrix / مصفوفة الوصول", el("div", { class: "policy-panel-body" },
      el("p", { class: "hint", text: "عرض سريع لعلاقة الأوامر بالرتب المسموحة. افتح أي أمر لتعديل السياسة من التفاصيل." }),
      commandPolicyMatrix(),
    ));
    policyPanel.id = "policy-panel";
    const auditEntries = [
      ...(state.incidents || []).map((item) => ({
        title: item.action_type || item.action || item.type || "حدث أمني",
        detail: item.culprit_name || item.reason || item.mitigation_taken || "سجل وارد من محرك الحماية",
        at: item.timestamp,
      })),
      ...(studio.commands || []).filter((command) => command.last_used_at).map((command) => ({
        title: `/${command.command_name}`,
        detail: `آخر استخدام · ${command.cog || "Commands"}`,
        at: command.last_used_at,
      })),
    ].sort((a, b) => new Date(b.at || 0) - new Date(a.at || 0)).slice(0, 8);
    const auditPanel = card("Activity / سجل النشاط والتدقيق", el("div", { class: "command-audit-panel-body" },
      auditEntries.length
        ? auditEntries.map((entry, index) => el("div", { class: "audit-row" },
            el("span", { class: "audit-marker" }),
            el("div", {}, el("strong", { text: entry.title }), el("small", { text: `${entry.detail} · ${entry.at ? new Date(entry.at).toLocaleString("ar") : "وقت غير متاح" }` })),
          ))
        : [el("div", { class: "empty studio-empty", text: "لا توجد أحداث تدقيق مقدمة من الخادم بعد" })],
    ));
    auditPanel.id = "command-audit-panel";
    const autoCard = card("Visual Auto-Responder Studio", form);
    autoCard.id = "auto-responder-panel";
    return el("section", { id: "view-commands", class: "commands-view" },
      el("div", { class: "studio-hero commands-hero" },
        el("div", { class: "eyebrow", text: `${state.guild.name} / COMMANDS` }),
        el("h2", { text: "استوديو الأوامر والاختصارات" }),
        el("p", { text: "اضبط الوصول، بدّل prefix فورياً، وابنِ ردوداً تلقائية بواجهة AMOLED سريعة وواضحة." }),
      ),
      commandMetrics,
      commandPanel,
      prefixForm,
      prefixExamples,
      shortcutWorkbench,
      commandTabs,
      policyPanel,
      autoCard,
      el("section", { class: "active-trigger-section" },
        el("div", { class: "section-heading" },
          el("div", {}, el("div", { class: "eyebrow", text: "LIVE REGISTRY" }), el("h3", { text: "Active Triggers" })),
          el("span", { class: "live-dot", text: `${state.autoResponses.length} مفعّل` }),
        ),
        cards,
      ),
      auditPanel,
    );
  }
  function overviewMetric(label, value, hint, tone, view) {
    return el(
      "button",
      {
        class: `overview-metric metric-${tone}`,
        type: "button",
        onClick: () => navigateView(view),
      },
      el("span", { class: "metric-label", text: label }),
      el("strong", { text: String(value) }),
      el("small", { text: hint }),
    );
  }
  function chartCard(title, subtitle, canvasId, tone = "blue") {
    const canvas = el("canvas", {
      class: `metric-chart chart-${tone}`,
      id: canvasId,
      width: "640",
      height: "220",
      role: "img",
      "aria-label": title,
    });
    return el(
      "section",
      { class: "overview-panel chart-card" },
      el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "LIVE TELEMETRY" }), el("h2", { text: title }), el("small", { text: subtitle })),
      canvas,
    );
  }
  function drawLine(canvas, values, color) {
    if (!canvas || !values.length) return;
    const ratio = window.devicePixelRatio || 1;
    const width = canvas.clientWidth || 640;
    const height = 220;
    canvas.width = width * ratio;
    canvas.height = height * ratio;
    const ctx = canvas.getContext("2d");
    ctx.scale(ratio, ratio);
    const max = Math.max(...values, 1);
    const min = Math.min(...values, 0);
    const span = Math.max(max - min, 1);
    ctx.clearRect(0, 0, width, height);
    ctx.strokeStyle = "#162338";
    ctx.lineWidth = 1;
    for (let row = 1; row < 4; row += 1) {
      const y = (height * row) / 4;
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(width, y);
      ctx.stroke();
    }
    const points = values.map((value, index) => [
      values.length === 1 ? width / 2 : (index / (values.length - 1)) * width,
      height - 18 - ((value - min) / span) * (height - 32),
    ]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 3;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";
    ctx.beginPath();
    points.forEach(([x, y], index) => index ? ctx.lineTo(x, y) : ctx.moveTo(x, y));
    ctx.stroke();
    ctx.fillStyle = color;
    points.slice(-1).forEach(([x, y]) => {
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    });
  }
  function drawDashboardCharts() {
    const series = state.stats?.series || [];
    drawLine(
      $("#latency-chart"),
      series.map((point) => Number(point.latency_ms)).filter(Number.isFinite),
      "#38bdf8",
    );
    drawLine(
      $("#members-chart"),
      series.map((point) => Number(point.members)).filter(Number.isFinite),
      "#34d399",
    );
  }
  function operationsView(view) {
    const counts = state.stats?.counts || {};
    const labels = {
      moderation: ["المراقبة", "أحدث الإنذارات وإجراءات الإدارة", counts.infractions || 0, "infractions"],
      economy: ["الاقتصاد", "الحسابات المسجلة في الخزينة", counts.economy_accounts || 0, "economy"],
      community: ["المجتمع", "التذاكر المفتوحة والأرشيف", counts.tickets_active || 0, "tickets"],
      ai: ["الذكاء الاصطناعي", "أدوات الذكاء متاحة من أوامر Discord", counts.commands_enabled || 0, "commands"],
      system: ["النظام", "حالة الاتصالات والقياسات الحية", state.online ? "ONLINE" : "OFFLINE", "overview"],
    };
    const [title, description, value, target] = labels[view];
    const actions = (state.actions || []).slice(0, 8);
    const actionList = actions.length
      ? actions.map((action) => el(
          "div",
          { class: "activity-row" },
          el("span", { class: "activity-dot" }),
          el("div", {}, el("strong", { text: action.action || "إجراء" }), el("small", { text: action.reason || "تم تسجيل الإجراء" })),
        ))
      : [el("div", { class: "empty-row", text: "لا توجد إجراءات مسجلة لهذا السيرفر" })];
    return el(
      "section",
      { class: "operations-view" },
      el("div", { class: "section-intro" }, el("div", { class: "eyebrow", text: `${state.guild.name} / ${title.toUpperCase()}` }), el("h1", { text: title }), el("p", { text: description })),
      el(
        "div",
        { class: "overview-metrics" },
        overviewMetric("القيمة الحالية", value, "من الحالة الحية", "blue", target),
        overviewMetric("التذاكر المفتوحة", counts.tickets_active || 0, "Help Desk", "purple", "tickets"),
        overviewMetric("الحوادث والمخالفات", counts.infractions || 0, "سجل الإجراءات", "red", "security"),
        overviewMetric("الأتمتة النشطة", counts.auto_responses || 0, "ردود تلقائية", "green", "commands"),
      ),
      el(
        "section",
        { class: "overview-panel" },
        el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "ACTION STREAM" }), el("h2", { text: "آخر الإجراءات" })),
        el("div", { class: "overview-activity" }, ...actionList),
      ),
    );
  }
  function overviewView() {
    const activeTickets = state.tickets.active.length;
    const openIncidents = state.incidents.length;
    const enabledCommands = state.commandStudio.commands.filter((command) => command.enabled !== false).length;
    const responders = state.autoResponses.length;
    const latestIncidents = state.incidents.slice().reverse().slice(0, 3);
    const quickActions = [
      ["التذاكر", "راجع التذاكر المفتوحة والأرشيف", "tickets", "▣"],
      ["الأوامر والأتمتة", "إدارة الأوامر والردود التلقائية", "commands", "⌘"],
      ["الترحيب والأدوار", "صمّم تجربة دخول الأعضاء", "onboarding", "✦"],
      ["الحماية", "راجع الأحداث والإجراءات الحساسة", "security", "◈"],
    ];
    const recent = el("div", { class: "overview-activity" });
    if (!latestIncidents.length) {
      recent.append(el("div", { class: "empty-row", text: "لا توجد أحداث أمنية جديدة" }));
    } else {
      latestIncidents.forEach((incident) => {
        recent.append(
          el(
            "div",
            { class: "activity-row" },
            el("span", { class: "activity-dot" }),
            el(
              "div",
              {},
              el("strong", { text: incident.action || incident.type || "حدث أمني" }),
              el("small", { text: incident.reason || "تم تسجيل الحدث من محرك الحماية" }),
            ),
          ),
        );
      });
    }
    return el(
      "section",
      { class: "overview-view" },
      el(
        "div",
        { class: "overview-hero" },
        el(
          "div",
          { class: "overview-hero-copy" },
          el("div", { class: "eyebrow", text: `${state.guild.name} / CONTROL CENTER` }),
          el("h1", { text: "كل شيء تحت السيطرة." }),
          el("p", { text: "نظرة سريعة على صحة البوت، التذاكر، الأوامر، والحماية في سيرفرك." }),
        ),
        el(
          "div",
          { class: "overview-hero-status" },
          el("span", { class: `status-pulse ${state.online ? "" : "offline"}` }),
          el("strong", { text: state.online ? "البوت متصل" : "الاتصال يحتاج مراجعة" }),
          el("small", { text: `${state.guild.members ?? "—"} عضو` }),
        ),
      ),
      el(
        "div",
        { class: "overview-metrics" },
        overviewMetric("التذاكر المفتوحة", activeTickets, "تحتاج متابعة", "purple", "tickets"),
        overviewMetric("الحوادث الأمنية", openIncidents, "آخر الأحداث", "red", "security"),
        overviewMetric("الأوامر المفعلة", enabledCommands, "أمر متاح", "blue", "commands"),
        overviewMetric("الردود التلقائية", responders, "رد مفعّل", "green", "commands"),
      ),
      el(
        "div",
        { class: "overview-columns" },
        el(
          "section",
          { class: "overview-panel quick-panel" },
          el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "QUICK ACTIONS" }), el("h2", { text: "الوصول السريع" })),
          el(
            "div",
            { class: "quick-grid" },
            quickActions.map(([title, description, view, icon]) =>
              el(
                "button",
                { class: "quick-action", type: "button", onClick: () => navigateView(view) },
                el("span", { class: "quick-icon", text: icon }),
                el("span", {}, el("strong", { text: title }), el("small", { text: description })),
                el("span", { class: "quick-arrow", text: "←" }),
              ),
            ),
          ),
        ),
        el(
          "section",
          { class: "overview-panel" },
          el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "SECURITY FEED" }), el("h2", { text: "آخر النشاطات" })),
          recent,
          el("button", { class: "text-link", type: "button", text: "فتح سجل الحماية ←", onClick: () => navigateView("security") }),
        ),
      ),
      el(
        "section",
        { class: "overview-panel overview-footer-panel" },
        el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "SYSTEM STATUS" }), el("h2", { text: "حالة الخدمات" })),
        el(
          "div",
          { class: "status-grid" },
          el("div", { class: "service-status" }, el("span", { class: "status-pulse" }), el("span", {}, el("strong", { text: "Discord Gateway" }), el("small", { text: "متصل ويستقبل الأحداث" }))),
          el("div", { class: "service-status" }, el("span", { class: "status-pulse" }), el("span", {}, el("strong", { text: "قاعدة البيانات" }), el("small", { text: "الحفظ والمزامنة يعملان" }))),
          el("div", { class: "service-status" }, el("span", { class: "status-pulse" }), el("span", {}, el("strong", { text: "Live Events" }), el("small", { text: "التحديثات تصل لحظياً" }))),
        ),
      ),
      el(
        "div",
        { class: "overview-columns chart-grid" },
        chartCard("زمن استجابة Discord", "قياس gateway بالميلي ثانية", "latency-chart", "blue"),
        chartCard("منحنى الأعضاء", "عدد أعضاء السيرفر في القياسات الحية", "members-chart", "green"),
      ),
    );
  }
  function settingsView() {
    const general = el("div", { class: "fields" });
    general.append(
      input("prefix", "بادئة الأوامر", "text", {
        minlength: "1",
        maxlength: "5",
        required: true,
      }),
    );
    const protect = el("div", { class: "fields" }),
      switches = el("div", { class: "field wide" });
    switches.append(
      toggle("anti_nuke", "حماية من التخريب الجماعي"),
      toggle("captcha_enabled", "تفعيل كابتشا التحقق"),
      toggle("anti_invites", "حظر دعوات Discord"),
      toggle("anti_links", "حظر الروابط المشبوهة"),
      toggle("anti_spam", "تفعيل رادار السبام"),
      toggle("anti_mass_mention", "حماية المنشن الجماعي"),
    );
    protect.append(
      switches,
      input("anti_alt_days", "عمر الحساب الأدنى (أيام)", "number", { min: "0", max: "365" }),
      selector("captcha_role_id", "رتبة اجتياز الكابتشا", "role"),
      selector("log_channel_id", "قناة السجل", "channel"),
    );
    const econ = el("div", { class: "fields" }),
      tax = input("economy_tax", "ضريبة الاقتصاد", "number", { min: "0", max: "100", step: "0.5" });
    tax.classList.add("suffix");
    tax.append(el("span", { text: "%" }));
    econ.append(tax, input("daily_amount", "المبلغ اليومي", "number", { min: "0", max: "1000000", step: "1" }));
    return el(
      "section",
      { class: "settings-view" },
      el("div", { class: "section-intro" }, el("div", { class: "eyebrow", text: `${state.guild.name} / SETTINGS` }), el("h1", { text: "الإعدادات" }), el("p", { text: "الإعدادات المتقدمة للبوت والحماية والاقتصاد." })),
      card("عام", general),
      card("الحماية", protect),
      card("الاقتصاد", econ),
      el("footer", { class: "footer", text: "الإعدادات تُحفظ في قاعدة بيانات البوت وتُطبّق على الميزات المرتبطة بها" }),
    );
  }
  function gamingView() {
    const channels = state.meta?.channels || [];
    const channelOptions = channels
      .filter((channel) => channel.type === "text" || !channel.type)
      .map((channel) => el("option", { value: channel.id, text: `#${channel.name}` }));
    const form = el(
      "form",
      { class: "fields gaming-deploy-form" },
      el("label", {}, el("span", { text: "عنوان السكريم" }), el("input", { name: "title", required: true, maxlength: "150", placeholder: "Friday Night Scrim" })),
      el("label", {}, el("span", { text: "اللعبة" }), el("input", { name: "game_type", required: true, maxlength: "80", placeholder: "Valorant / PUBG / FIFA" })),
      el("label", {}, el("span", { text: "القناة" }), el("select", { name: "target_channel_id", required: true }, el("option", { value: "", text: "اختر قناة النشر" }), channelOptions)),
      el("label", {}, el("span", { text: "حجم الفريق" }), el("input", { name: "team_size", type: "number", min: "1", max: "16", value: "5" })),
      el("label", {}, el("span", { text: "عدد المقاعد" }), el("input", { name: "max_slots", type: "number", min: "1", max: "128", value: "8" })),
      el("button", { class: "btn primary", type: "submit", text: "نشر لوحة سكريم" }),
    );
    form.onsubmit = async (event) => {
      event.preventDefault();
      const body = Object.fromEntries(new FormData(form).entries());
      body.team_size = Number(body.team_size);
      body.max_slots = Number(body.max_slots);
      const response = await writeApi(`api/guild/${state.guild.id}/gaming/deploy`, body);
      const data = await response.json();
      if (!response.ok) return toast(data.fields ? Object.values(data.fields)[0] : "تعذر نشر لوحة السكريم");
      toast("✅ نُشرت لوحة السكريم في Discord", "success", 3000);
      await refreshGaming();
    };
    const list = el("div", { class: "gaming-list" });
    if (!state.gaming.length) {
      list.append(el("div", { class: "empty studio-empty", text: "لا توجد لوحات سكريم محفوظة بعد" }));
    } else {
      state.gaming.forEach((scrim) => {
        const closed = !scrim.is_active;
        const registrations = scrim.registrations || [];
        const roster = registrations.length
          ? registrations.map((item) => `#${item.slot_number} ${item.team_name}${item.checked_in ? " ✅" : ""}`).join(" · ")
          : "لا توجد فرق مسجلة";
        const actions = [];
        if (!closed) {
          actions.push(el("button", {
            class: "btn danger",
            type: "button",
            text: "إغلاق التسجيل",
            onClick: async () => {
              if (!confirm(`إغلاق سكريم «${scrim.title}»؟`)) return;
              const response = await writeApi(`api/guild/${state.guild.id}/gaming/close`, { scrim_id: scrim.id });
              if (response.ok) { toast("تم إغلاق السكريم", "success", 2500); await refreshGaming(); }
              else toast("تعذر إغلاق السكريم");
            },
          }));
          actions.push(el("button", {
            class: "btn ghost",
            type: "button",
            text: "إرسال بيانات الغرفة",
            onClick: () => openCredentialPrompt(scrim.id),
          }));
        }
        list.append(el("article", { class: `overview-panel gaming-card ${closed ? "is-closed" : ""}` },
          el("div", { class: "gaming-card-head" },
            el("div", {}, el("span", { class: "eyebrow", text: `${scrim.game_type} / ${closed ? "CLOSED" : "LIVE"}` }), el("h3", { text: scrim.title })),
            el("strong", { text: `${scrim.occupied_slots || 0}/${scrim.max_slots}` }),
          ),
          el("p", { class: "muted", text: `حجم الفريق ${scrim.team_size} · ${roster}` }),
          el("div", { class: "gaming-card-actions" }, actions),
        ));
      });
    }
    return el("section", { id: "view-gaming", class: "gaming-view" },
      el("div", { class: "section-intro" }, el("div", { class: "eyebrow", text: `${state.guild.name} / GAMING OPS` }), el("h1", { text: "Gaming, Scrims & Esports" }), el("p", { text: "أنشئ لوحات سكريم تفاعلية، راقب الحجوزات، وأرسل بيانات الغرف من مكان واحد." })),
      card("نشر لوحة جديدة", form),
      el("div", { class: "section-intro compact-intro" }, el("h2", { text: "اللوحات المحفوظة" }), el("p", { text: "الحجوزات تُحفظ وتستمر بعد إعادة تشغيل البوت." })),
      list,
    );
  }
  async function refreshGaming() {
    if (!state.guild?.id) return;
    try {
      const response = await api(`api/guild/${state.guild.id}/gaming`);
      if (response.ok) {
        state.gaming = (await response.json()).scrims || [];
        if (state.activeView === "gaming") renderPage();
      }
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر تحديث مركز السكريمات");
    }
  }
  async function openCredentialPrompt(scrimId) {
    const credentials = prompt("أدخل بيانات غرفة اللعب (الرابط/الكود):", "");
    if (!credentials?.trim()) return;
    const response = await writeApi(`api/guild/${state.guild.id}/gaming/credentials`, { scrim_id: scrimId, credentials: credentials.trim() });
    if (response.ok) toast("تم إرسال بيانات الغرفة إلى قناة السكريم", "success", 3000);
    else toast("تعذر إرسال بيانات الغرفة");
  }
  function economyView() {
    const snapshot = state.economy.settings || { settings: {} };
    const config = snapshot.settings || {};
    const channels = (state.meta?.channels || []).filter((channel) => channel.type === "text" || !channel.type);
    const roles = state.meta?.roles || [];
    const channelSelect = el(
      "select",
      { name: "leaderboard_channel_id", required: true },
      el("option", { value: "0", text: "لا توجد قناة مثبتة" }),
      channels.map((channel) => el("option", { value: channel.id, text: `#${channel.name}` })),
    );
    channelSelect.value = String(config.leaderboard_channel_id || "0");
    const supportSelect = el(
      "select",
      { name: "economy_support_role_ids", multiple: true, size: "4" },
      roles.map((role) => el("option", { value: role.id, text: role.name })),
    );
    const selectedSupportRoles = new Set((config.economy_support_role_ids || []).map(String));
    supportSelect.querySelectorAll("option").forEach((option) => {
      option.selected = selectedSupportRoles.has(String(option.value));
    });
    const form = el(
      "form",
      { class: "fields economy-config-form" },
      el("label", {}, el("span", { text: "قناة لوحة المتصدرين" }), channelSelect),
      el("label", {}, el("span", { text: "المكافأة اليومية الأساسية" }), el("input", { name: "daily_base_amount", type: "number", min: "0", max: "1000000", value: String(config.daily_base_amount ?? 200) })),
      el("label", {}, el("span", { text: "نسبة زيادة المستوى %" }), el("input", { name: "level_multiplier_pct", type: "range", min: "0", max: "500", value: String(config.level_multiplier_pct ?? 10), onInput: (event) => { pctValue.textContent = `${event.target.value}%`; } })),
      el("span", { class: "economy-slider-value", text: `${config.level_multiplier_pct ?? 10}%` }),
      el("div", { class: "economy-role-multipliers" },
        el("div", { class: "panel-heading" }, el("h3", { text: "مضاعفات الرتب" }), el("small", { text: "اترك القيمة فارغة لإلغاء المضاعف" })),
        ...roles.map((role) => {
          const input = el("input", { type: "number", min: "0.1", max: "10", step: "0.1", value: state.economy.multipliers[String(role.id)] ?? "", "data-role-multiplier": role.id, placeholder: "1.0×" });
          return el("label", { class: "economy-role-row" }, el("span", { text: role.name }), input);
        }),
      ),
      el("label", {}, el("span", { text: "أدوار دعم الاقتصاد" }), supportSelect),
      el("button", { class: "btn primary", type: "submit", text: "حفظ وتثبيت اللوحة 📌" }),
    );
    const pctValue = form.querySelector(".economy-slider-value");
    form.onsubmit = async (event) => {
      event.preventDefault();
      const multipliers = {};
      form.querySelectorAll("[data-role-multiplier]").forEach((input) => {
        if (input.value) multipliers[input.dataset.roleMultiplier] = Number(input.value);
      });
      const body = {
        leaderboard_channel_id: channelSelect.value,
        daily_base_amount: Number(form.elements.daily_base_amount.value),
        level_multiplier_pct: Number(form.elements.level_multiplier_pct.value),
        role_multipliers: multipliers,
        economy_support_role_ids: [...supportSelect.selectedOptions].map((option) => option.value),
      };
      const response = await writeApi(`api/guild/${state.guild.id}/economy/config`, body);
      const data = await response.json();
      if (!response.ok) return toast(data.fields ? Object.values(data.fields)[0] : "تعذر حفظ إعدادات الاقتصاد");
      toast("✅ تم حفظ إعدادات الاقتصاد وتثبيت اللوحة", "success", 3000);
      await refreshEconomy();
    };
    const openAdjust = (row) => {
      const back = el("div", { class: "modal-back", role: "dialog", "aria-modal": "true" });
      const wallet = el("input", { name: "wallet_delta", type: "number", placeholder: "مثال: 500 أو -250", value: "0" });
      const level = el("input", { name: "level_delta", type: "number", placeholder: "مثال: 1 أو -1", value: "0" });
      const edit = el("form", { class: "fields" },
        el("label", {}, el("span", { text: "إضافة/خصم رصيد" }), wallet),
        el("label", {}, el("span", { text: "تعديل المستوى" }), level),
        el("button", { class: "btn primary", type: "submit", text: "تنفيذ التعديل فوراً" }),
      );
      edit.onsubmit = async (event) => {
        event.preventDefault();
        const response = await writeApi(`api/guild/${state.guild.id}/economy/adjust`, {
          user_id: row.user_id,
          wallet_delta: Number(wallet.value || 0),
          level_delta: Number(level.value || 0),
        });
        const data = await response.json();
        if (!response.ok) return toast(data.fields ? Object.values(data.fields)[0] : "تعذر تعديل الحساب");
        back.remove();
        toast("✅ تم تحديث حساب العضو", "success", 2500);
        await refreshEconomy();
      };
      back.append(el("div", { class: "modal" },
        el("h2", { text: `تعديل حساب ${row.user_id}` }),
        el("p", { text: `الرصيد الحالي: ${(Number(row.balance) + Number(row.bank)).toLocaleString()} · المستوى: ${row.level}` }),
        edit,
        el("button", { class: "btn ghost", type: "button", text: "إلغاء", onClick: () => back.remove() }),
      ));
      document.body.append(back);
    };
    const rows = state.economy.wealth.length
      ? state.economy.wealth.map((row, index) => el("button", { class: "economy-user-row", type: "button", onClick: () => openAdjust(row) },
        el("span", { text: `#${index + 1}` }),
        el("strong", { text: `عضو ${row.user_id}` }),
        el("span", { text: `${Number(row.total).toLocaleString()} عملة · مستوى ${row.level}` }),
      ))
      : [el("div", { class: "empty-row", text: "لا توجد حسابات اقتصادية بعد" })];
    return el("section", { id: "view-economy", class: "economy-view" },
      el("div", { class: "section-intro" }, el("div", { class: "eyebrow", text: `${state.guild.name} / ECONOMY CONTROL` }), el("h1", { text: "الاقتصاد والمتصدرون" }), el("p", { text: "مكافآت يومية متدرجة، مضاعفات للرتب، ولوحة متصدرين حية لا تختفي عند التحديث." })),
      card("إعدادات الاقتصاد واللوحة الحية", form),
      el("section", { class: "overview-panel economy-leaderboard-panel" },
        el("div", { class: "panel-heading" }, el("div", { class: "eyebrow", text: "LIVE BALANCE MANAGER" }), el("h2", { text: "أغنى الأعضاء" }), el("small", { text: "اضغط على أي صف لفتح التعديل السريع" })),
        el("div", { class: "economy-user-list" }, rows),
      ),
    );
  }
  async function refreshEconomy() {
    if (!state.guild?.id) return;
    try {
      const response = await api(`api/guild/${state.guild.id}/economy`);
      if (response.ok) {
        const data = await response.json();
        state.economy = {
          wealth: data.wealth || [],
          levels: data.levels || [],
          settings: data.settings || { settings: {} },
          multipliers: data.multipliers || {},
        };
        if (state.activeView === "economy") renderPage();
      }
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر تحديث مركز الاقتصاد");
    }
  }
  function analyticsView() {
    const categories = [
      ["log_sanctions", "⚔️", "سجل العقوبات", "الباند والطرد والكتم", "#DC2626"],
      ["log_violations", "⚠️", "سجل المخالفات", "الإنذارات والإجراءات التصحيحية", "#EAB308"],
      ["log_automod", "🛡️", "سجل Auto-Mod", "الروابط والكلمات والسبام والمنشن", "#F97316"],
      ["log_ticket", "🎫", "سجل التذاكر", "الفتح والاستلام والإغلاق والتصعيد", "#14B8A6"],
      ["log_channel", "📁", "سجل القنوات", "إنشاء وتعديل وحذف القنوات", "#10B981"],
      ["log_server", "🏰", "سجل السيرفر", "تعديلات إعدادات السيرفر", "#3B82F6"],
      ["log_member", "👤", "سجل الأعضاء", "الدخول والمغادرة وتغييرات العضوية", "#22C55E"],
      ["log_message", "💬", "سجل الرسائل", "حذف وتعديل الرسائل", "#EF4444"],
      ["log_voice", "🎙️", "سجل النشاط الصوتي", "الدخول والخروج والتنقل", "#06B6D4"],
      ["log_react", "👍", "سجل التفاعلات", "إضافة التفاعلات على الرسائل", "#EC4899"],
      ["log_roles", "🎭", "سجل الرتب والصلاحيات", "إضافة الرتب وتعديلها", "#8B5CF6"],
    ];
    const channels = (state.meta?.channels || []).filter((item) => item.type === "text" || !item.type);
    const routeState = state.logRouting?.channels || {};
    const cards = categories.map(([key, icon, title, hint, accent]) => {
      const select = el(
        "select",
        { class: "analytics-channel-select", "aria-label": title },
        el("option", { value: "0" }, "✕ غير مفعّلة"),
        ...channels.map((channel) => el("option", { value: String(channel.id) }, `#${channel.name}`)),
      );
      select.value = String(routeState[key] || "0");
      select.onchange = () => { state.logRouting.channels[key] = select.value; };
      return el(
        "article",
        { class: "analytics-route-card", style: `--route-accent:${accent}` },
        el("div", { class: "analytics-route-head" },
          el("span", { class: "analytics-route-icon", text: icon }),
          el("div", {}, el("strong", { text: title }), el("small", { text: hint })),
          el("span", { class: "analytics-route-accent", text: "LIVE" }),
        ),
        select,
        el("div", { class: "analytics-route-actions" },
          el("button", {
            class: "btn analytics-test-button", type: "button", title: "إرسال رسالة اختبار إلى القناة المختارة",
            text: "🧪 إرسال اختبار",
            onClick: async (event) => {
              pulse();
              const button = event.currentTarget;
              button.disabled = true;
              try {
                const response = await writeApi(`api/guild/${state.guild.id}/logs/test/${key}`, {});
                const data = await response.json().catch(() => ({}));
                const message = {
                  category_unassigned: "عيّن قناة لهذا التصنيف أولاً ثم احفظ التوزيع",
                  missing_send_permission: "البوت لا يملك صلاحية إرسال الرسائل في هذه القناة",
                  discord_unavailable: "تعذر الوصول إلى Discord حالياً",
                }[data.error] || "تعذر إرسال التجربة";
                toast(response.ok ? "تم إرسال رسالة الاختبار إلى Discord" : message, response.ok ? "success" : "warn");
              } finally {
                button.disabled = false;
              }
            },
          }),
          el("button", {
            class: "btn analytics-disable-button", type: "button", title: "تعطيل هذا التصنيف",
            text: "✕ تعطيل",
            onClick: () => { select.value = "0"; state.logRouting.channels[key] = "0"; },
          }),
        ),
      );
    });
    return el("section", { id: "view-analytics", class: "analytics-view" },
      el("div", { class: "studio-hero analytics-hero" },
        el("div", { class: "eyebrow", text: `${state.guild.name} / ANALYTICS CONTROL` }),
        el("h2", { text: "موزع السجلات الاحترافي" }),
        el("p", { text: "وجّه كل فئة إلى قناتها الخاصة وراجع شكل الإمبد الحقيقي قبل تفعيل السجل." }),
        el("button", {
          class: "btn analytics-save-button", type: "button", text: "💾 حفظ توزيع قنوات السجلات",
          onClick: async (event) => {
            pulse();
            const button = event.currentTarget;
            button.disabled = true;
            try {
              const response = await writeApi(
                `api/guild/${state.guild.id}/logs/channels`,
                { channels: state.logRouting.channels },
              );
              const data = await response.json().catch(() => ({}));
              if (response.ok) {
                state.logRouting = data;
                toast("تم حفظ توزيع السجلات وتحديث الذاكرة مباشرة", "success");
                renderPage();
              } else {
                toast(Object.values(data.fields || {})[0] || "تعذر حفظ توزيع السجلات", "warn");
              }
            } finally {
              button.disabled = false;
            }
          },
        }),
      ),
       el("div", { class: "analytics-route-grid" }, ...cards),
    );
  }
  function renderPage() {
    const main = $("#main");
    main.replaceChildren();
    if (state.newer) {
      const n = el("div", {
        class: "notice",
        text: "توجد نسخة أحدث من الإعدادات. تعديلاتك ما زالت محفوظة محلياً. ",
      });
      n.append(
        el("button", {
          type: "button",
          text: "تحميل الإصدار الأحدث",
          onClick: () => {
            state.draft = clone(state.baseline);
            state.newer = false;
            renderPage();
          },
        }),
      );
      main.append(n);
    }
    const view = state.activeView;
    if (view === "overview") main.append(overviewView());
    else if (view === "tickets") main.append(ticketsView());
    else if (view === "commands") main.append(commandsView());
    else if (view === "gaming") main.append(gamingView());
    else if (view === "onboarding") main.append(onboardingView());
    else if (view === "security") main.append(securityView());
    else if (view === "analytics") main.append(analyticsView());
    else if (view === "economy") main.append(economyView());
    else if (["moderation", "community", "ai", "system"].includes(view)) main.append(operationsView(view));
    else main.append(settingsView());
    renderDock();
    renderDynamic();
    drawDashboardCharts();
  }
  function renderDynamic() {
    Object.keys(state.fields).forEach((k) => {
      const x = $(`#err-${k}`);
      if (x) x.textContent = state.fields[k];
    });
    const d = $(".dock");
    if (d) d.classList.toggle("show", dirty() || onboardingDirty());
    const onboardingSave = $(".onboarding-save");
    if (onboardingSave) onboardingSave.disabled = !onboardingDirty() || state.saving || !state.online;
    const onboardingTest = $(".onboarding-test");
    if (onboardingTest) onboardingTest.disabled = !state.online || state.saving;
    document.querySelectorAll("[data-role-matrix-key]").forEach((node) => {
      node.textContent = roleName(state.draft[node.dataset.roleMatrixKey]);
    });
    refreshEmbedPreview();
  }
  async function saveAll() {
    if (dirty()) await save();
    if (onboardingDirty()) await saveOnboarding();
  }
  function renderDock() {
    let d = $(".dock");
    if (d) d.remove();
    d = el(
      "div",
      { class: "dock" },
      el("div", { class: "dock-text", text: "⚠️ لديك تعديلات غير محفوظة" }),
      el("button", {
        class: "btn primary",
        type: "button",
        text: "حفظ التغييرات",
         onClick: saveAll,
      }),
      el("button", {
        class: "btn cancel",
        type: "button",
        text: "إلغاء",
        onClick: () => {
          state.draft = clone(state.baseline);
          state.fields = {};
          renderPage();
        },
      }),
    );
    document.body.append(d);
    renderDynamic();
  }
  // Saving and conflict handling
  async function save() {
    if (state.saving || !dirty() || !state.online) return;
    const guildId = state.guild.id,
      snap = changes(),
      sent = { ...clone(state.baseline), ...snap };
    state.saving = true;
    const b = $(".dock .primary");
    b.disabled = true;
    b.replaceChildren(el("span", { class: "spinner" }));
    try {
      const r = await writeApi(`api/guild/${guildId}/settings`, {
        revision: state.revision,
        changes: snap,
      });
      if (guildId !== state.guild.id) return;
      const data = await r.json();
      if (r.status === 200 && data.ok) {
        // تعديلات أُجريت أثناء الحفظ فقط هي التي تبقى غير محفوظة
        const later = Object.fromEntries(
          settingsKeys
            .filter((k) => !sameValue(state.draft[k], sent[k]))
            .map((k) => [k, state.draft[k]]),
        );
        if (data.revision >= state.revision) {
          state.baseline = clone(data.settings);
          state.revision = data.revision;
          state.updated = data.updated_at;
        }
        state.draft = { ...clone(state.baseline), ...later };
        state.newer = false;
        state.fields = {};
        navigator.vibrate?.([15, 30, 15]);
        toast("✅ تم تطبيق التحديثات فورياً على السيرفر", "success", 3500);
        renderPage();
      } else if (r.status === 400) {
        state.fields = data.fields || {};
        toast("يرجى مراجعة الحقول المعلّمة");
        renderDynamic();
      } else if (r.status === 403) {
        const reason = data.error === "csrf"
          ? "انتهت جلسة الحماية. أعد تحميل الصفحة ثم جرّب الحفظ."
          : "لا تملك صلاحية تعديل هذا السيرفر";
        toast(reason);
      }
      else if (r.status === 409) conflict(data);
      else if (r.status === 429)
        toast(`تم تجاوز الحد، حاول بعد ${data.retry_after} ثانية`, "warn", 5000);
      else toast("تعذر حفظ الإعدادات. حاول مجدداً");
    } catch (e) {
      if (e.message !== "unauth")
        toast("تعذر الاتصال بالخادم. احتفظنا بتعديلاتك");
    } finally {
      state.saving = false;
      if ($(".dock .primary")) {
        b.disabled = !state.online;
        b.textContent = "حفظ التغييرات";
      }
    }
  }
  async function saveOnboarding() {
    if (state.saving || !onboardingDirty() || !state.online) return false;
    const guildId = state.guild.id;
    const snap = onboardingChanges();
    const sent = { ...clone(state.baseline), ...snap };
    state.saving = true;
    const button = $(".onboarding-save");
    if (button) {
      button.disabled = true;
      button.replaceChildren(el("span", { class: "spinner" }), document.createTextNode(" جارٍ الحفظ…"));
    }
    try {
      const r = await writeApi(`api/guild/${guildId}/onboarding`, {
        revision: state.revision,
        changes: snap,
      });
      if (guildId !== state.guild.id) return false;
      const data = await r.json();
      if (r.ok && data.revision != null) {
        const later = Object.fromEntries(
          onboardingKeys
            .filter((key) => state.draft[key] !== sent[key])
            .map((key) => [key, state.draft[key]]),
        );
        state.baseline = { ...state.baseline, ...(data.settings || {}) };
        state.revision = data.revision;
        state.updated = data.updated_at;
        state.draft = { ...clone(state.baseline), ...later };
        state.onboarding = { ...state.onboarding, ...data, settings: data.settings || state.onboarding?.settings || {} };
        state.newer = false;
        state.fields = {};
        navigator.vibrate?.([15, 30, 15]);
        toast("✅ تم حفظ إعدادات الدخول وتطبيقها فورياً", "success", 3500);
        renderPage();
        return true;
      }
      if (r.status === 400) {
        state.fields = data.fields || {};
        toast("يرجى مراجعة حقول onboarding");
        renderDynamic();
      } else if (r.status === 403) {
        const reason = data.error === "csrf"
          ? "انتهت جلسة الحماية. أعد تحميل الصفحة ثم جرّب الحفظ."
          : "لا تملك صلاحية تعديل هذا السيرفر";
        toast(reason);
      }
      else if (r.status === 409) onboardingConflict(data);
      else if (r.status === 429) toast(`تم تجاوز الحد، حاول بعد ${data.retry_after || 5} ثانية`, "warn", 5000);
      else toast("تعذر حفظ إعدادات onboarding");
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم. احتفظنا بتعديلاتك");
    } finally {
      state.saving = false;
      renderDynamic();
    }
    return false;
  }
  function onboardingConflict(data) {
    const back = el("div", { class: "modal-back", role: "dialog", "aria-modal": "true" });
    const modal = el(
      "div",
      { class: "modal" },
      el("h2", { text: "تعارض في إعدادات الدخول" }),
      el("p", { text: "تم تعديل استوديو onboarding من جلسة أخرى. اختر النسخة التي تريد اعتمادها." }),
    );
    const actions = el("div", { class: "modal-actions" });
    const adoptOnboarding = (keepLocal) => {
      const local = keepLocal ? onboardingChanges() : {};
      state.baseline = { ...state.baseline, ...(data.settings || {}) };
      state.revision = data.revision;
      state.updated = data.updated_at;
      state.draft = { ...clone(state.baseline), ...local };
      state.onboarding = { ...state.onboarding, ...data };
      state.newer = keepLocal && Object.keys(local).length > 0;
      back.remove();
      renderPage();
    };
    actions.append(
      el("button", { type: "button", text: "تحميل الأحدث", onClick: () => adoptOnboarding(false) }),
      el("button", { type: "button", text: "مراجعة تعديلي", onClick: () => adoptOnboarding(true) }),
    );
    modal.append(actions);
    back.append(modal);
    document.body.append(back);
  }
  async function sendTestWelcome() {
    if (!state.online || state.saving) return;
    if (onboardingDirty()) {
      const saved = await saveOnboarding();
      if (!saved) {
        toast("احفظ إعدادات onboarding أولاً لإرسال تجربة مطابقة لها", "warn");
        return;
      }
    }
    const channelId = state.draft?.welcome_channel_id;
    if (!channelId) {
      toast("اختر قناة الترحيب أولاً", "warn");
      return;
    }
    const button = $(".onboarding-test");
    if (button) {
      button.disabled = true;
      button.replaceChildren(el("span", { class: "spinner" }), document.createTextNode(" جارٍ الإرسال…"));
    }
    try {
      const r = await api(`api/guild/${state.guild.id}/onboarding/test-welcome`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({
          target_channel_id: String(channelId),
          template_data: { username: "عضو تجريبي" },
        }),
      });
      const data = await r.json();
      if (r.ok && data.ok) toast("تم إرسال رسالة التجربة إلى Discord", "success", 3500);
      else toast(data.fields?.target_channel_id || "تعذر إرسال رسالة التجربة");
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال لإرسال رسالة التجربة");
    } finally {
      renderDynamic();
    }
  }
  async function deploySelfRoles() {
    const builder = ensureSelfRoleBuilder();
    if (!state.online || state.saving) return;
    if (!builder.target_channel_id) {
      toast("اختر قناة لوحة الرتب أولاً", "warn");
      return;
    }
    if (!builder.roles.length || builder.roles.length > 25) {
      toast("أضف من رتبة إلى 25 رتبة قابلة للإسناد", "warn");
      return;
    }
    const button = $(".builder-deploy");
    if (button) {
      button.disabled = true;
      button.replaceChildren(el("span", { class: "spinner" }), document.createTextNode(" جارٍ النشر…"));
    }
    try {
      const r = await api(`api/guild/${state.guild.id}/self-roles/deploy`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({
          channel_id: String(builder.target_channel_id),
          title: builder.title,
          description: builder.description,
          min_level: Number(builder.min_level || 0),
          color_hex: normalizePanelColor(builder.color),
          buttons: builder.roles.map((role) => ({
            role_id: String(role.id),
            label: String(role.label || roleName(role.id)).slice(0, 100),
            emoji: String(role.emoji || "").slice(0, 100),
            custom_min_level: Number(role.custom_min_level || 0),
          })),
        }),
      });
      const data = await r.json();
      if (r.ok && data.ok && data.panel) {
        state.onboarding = {
          ...state.onboarding,
          self_roles: [data.panel, ...(state.onboarding?.self_roles || [])],
        };
        navigator.vibrate?.([15, 30, 15]);
        toast("✅ نُشرت لوحة الرتب وحُفظت للاستعادة بعد إعادة التشغيل", "success", 4000);
        renderPage();
      } else toast(data.error === "role_not_assignable" ? "إحدى الرتب أعلى من رتبة البوت أو مُدارة" : "تعذر نشر لوحة الرتب");
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال لنشر لوحة الرتب");
    } finally {
      renderDynamic();
    }
  }
  function conflict(data) {
    const back = el("div", {
        class: "modal-back",
        role: "dialog",
        "aria-modal": "true",
      }),
      m = el(
        "div",
        { class: "modal" },
        el("h2", { text: "تعارض في الإعدادات" }),
        el("p", {
          text: "تم تعديل الإعدادات من جلسة أخرى. اختر كيف تريد المتابعة.",
        }),
      );
    const actions = el("div", { class: "modal-actions" });
    actions.append(
      el("button", {
        text: "تحميل الإصدار الأحدث",
        onClick: () => {
          adopt(data, false);
          back.remove();
          renderPage();
        },
      }),
      el("button", {
        text: "مراجعة",
        onClick: () => {
          adopt(data, true);
          back.remove();
          renderPage();
        },
      }),
    );
    m.append(actions);
    back.append(m);
    document.body.append(back);
  }
  // Guild loading and live events
  function stopIncidentRefresh() {
    if (state.incidentTimer) {
      clearInterval(state.incidentTimer);
      state.incidentTimer = null;
    }
  }
  async function refreshIncidents(id, redraw = false) {
    if (state.guild?.id !== id) return;
    try {
      const r = await api(`api/guild/${id}/security/incidents`);
      if (!r.ok) return;
      const data = await r.json();
      if (state.guild?.id !== id) return;
      const lockChanged = state.lockdown !== Boolean(data.locked);
      state.incidents = data.incidents || [];
      state.whitelist = data.whitelist || [];
      state.lockdown = Boolean(data.locked);
      if (redraw) {
        if (lockChanged) {
          const view = $("#view-security");
          if (view) view.replaceWith(securityView());
        } else {
          refreshIncidentBody();
        }
      }
    } catch (error) {
      if (error.message !== "unauth") updatePing("wait");
    }
  }
  async function refreshDashboardStats(id, redraw = false) {
    if (state.guild?.id !== id) return;
    try {
      const [statsResponse, actionsResponse] = await Promise.all([
        api(`api/guild/${id}/stats`),
        api(`api/guild/${id}/actions`),
      ]);
      if (state.guild?.id !== id) return;
      if (statsResponse.ok) state.stats = await statsResponse.json();
      if (actionsResponse.ok) state.actions = (await actionsResponse.json()).actions || [];
      if (redraw && state.activeView !== "settings") renderPage();
    } catch (error) {
      if (error.message !== "unauth") updatePing("wait");
    }
  }
  function startIncidentRefresh(id) {
    stopIncidentRefresh();
    state.incidentTimer = setInterval(() => refreshIncidents(id, true), 15000);
  }
  async function fetchGuildMeta(id) {
    const response = await api(`api/guild/${id}/meta`);
    if (!response.ok) throw new Error("meta_unavailable");
    const meta = await response.json();
    if (state.guild?.id !== id) return meta;
    state.meta = meta;
    state.commandStudio = {
      ...(state.commandStudio || {}),
      roles: meta.roles || [],
      channels: meta.channels || [],
    };
    state.autoResponderMeta = {
      roles: meta.roles || [],
      emojis: meta.emojis || [],
      members: meta.members || [],
    };
    return meta;
  }
  async function loadGuild(id) {
    const g = state.session.guilds.find((x) => x.id === id);
    if (!g) return;
    state.guild = g;
    sessionStorage.setItem("dashboard-guild", id);
    state.meta = state.baseline = state.draft = null;
    state.stats = null;
    state.actions = [];
    state.drawerOpen = false;
    state.onboarding = null;
    state.commandStudio = { commands: [], roles: [], channels: [], shortcuts: [] };
    state.commandRegistry = { categories: [], commands: [], policies: {}, byKey: {} };
    state.shortcutCommandId = "";
    state.shortcutInputText = null;
    state.autoResponses = [];
    state.commandSearch = "";
    state.tickets = { active: [], archive: [], kpis: [], canned: [] };
    state.gaming = [];
    state.economy = { wealth: [], levels: [], settings: null, multipliers: {} };
    state.ticketSearch = "";
    state.ticketStatusFilter = "all";
    state.selfRoleBuilder = null;
    state.fields = {};
    renderShell();
    closeSSE();
    stopIncidentRefresh();
    try {
      const [mr, sr, ir, or, cr, registryResponse, ar, ta, tv, tk, tc, str, acr, gr, er, lr] = await Promise.all([
        fetchGuildMeta(id),
        api(`api/guild/${id}/settings`),
        api(`api/guild/${id}/security/incidents`),
        api(`api/guild/${id}/onboarding`),
        api(`api/guild/${id}/commands`),
        api(`api/guild/${id}/commands/registry`),
        api(`api/guild/${id}/auto-responses`),
        api(`api/guild/${id}/tickets/active`),
        api(`api/guild/${id}/tickets/archive`),
        api(`api/guild/${id}/tickets/kpis`),
        api(`api/guild/${id}/tickets/canned`),
        api(`api/guild/${id}/stats`),
        api(`api/guild/${id}/actions`),
        api(`api/guild/${id}/gaming`),
        api(`api/guild/${id}/economy`),
        api(`api/guild/${id}/logs/channels`),
      ]);
      if (state.guild.id !== id) return;
      const [meta, settings, incidents, onboarding, commands, registry, autoResponses, activeTickets, archiveTickets, ticketKpis, canned, stats, actions, gaming, economy, logRouting] = await Promise.all([
        Promise.resolve(mr),
        sr.json(),
        ir.ok ? ir.json() : Promise.resolve({ incidents: [] }),
        or.json(),
        cr.ok ? cr.json() : Promise.resolve({ commands: [], roles: [], channels: [], shortcuts: [] }),
        registryResponse.ok ? registryResponse.json() : Promise.resolve({ categories: [], commands: [], policies: {} }),
        ar.ok ? ar.json() : Promise.resolve({ rules: [], channels: [] }),
        ta.ok ? ta.json() : Promise.resolve({ tickets: [] }),
        tv.ok ? tv.json() : Promise.resolve({ tickets: [] }),
        tk.ok ? tk.json() : Promise.resolve({ kpis: [] }),
        tc.ok ? tc.json() : Promise.resolve({ responses: [] }),
        str.ok ? str.json() : Promise.resolve({ counts: {}, series: [] }),
        acr.ok ? acr.json() : Promise.resolve({ actions: [] }),
        gr.ok ? gr.json() : Promise.resolve({ scrims: [] }),
        er.ok ? er.json() : Promise.resolve({ wealth: [], levels: [], settings: { settings: {} }, multipliers: {} }),
        lr.ok ? lr.json() : Promise.resolve({ channels: {} }),
      ]);
      if (state.guild.id !== id) return;
      state.meta = meta;
      state.commandStudio = {
        commands: commands.commands || [],
        roles: commands.roles || meta.roles || [],
        channels: commands.channels || meta.channels || [],
        shortcuts: commands.shortcuts || [],
      };
      state.commandRegistry = {
        categories: registry.categories || [],
        commands: registry.commands || [],
        policies: registry.policies || {},
        byKey: Object.fromEntries((registry.commands || []).map((item) => [String(item.key).toLowerCase(), item])),
      };
      state.selectedCommandIds = [];
      state.commandSearch = "";
      state.commandCogFilter = "all";
      state.commandStatusFilter = "all";
      state.commandRoleFilter = "all";
      state.commandDetail = null;
       state.autoResponses = autoResponses.rules || [];
      state.autoResponderMeta = {
        roles: autoResponses.roles || meta.roles || [],
        emojis: autoResponses.emojis || meta.emojis || [],
        members: autoResponses.members || meta.members || [],
      };
      state.tickets = {
        active: activeTickets.tickets || [],
        archive: archiveTickets.tickets || [],
        kpis: ticketKpis.kpis || [],
        canned: canned.responses || [],
      };
      state.incidents = incidents.incidents || [];
      state.whitelist = incidents.whitelist || [];
      state.lockdown = Boolean(incidents.locked);
      state.stats = stats;
      state.actions = actions.actions || [];
      state.gaming = gaming.scrims || [];
      state.economy = {
        wealth: economy.wealth || [],
        levels: economy.levels || [],
        settings: economy.settings || { settings: {} },
        multipliers: economy.multipliers || {},
      };
      state.logRouting = logRouting || { channels: {} };
      state.baseline = clone(settings.settings);
      state.onboarding = onboarding;
      state.baseline = { ...state.baseline, ...(onboarding.settings || {}) };
      state.draft = clone(state.baseline);
      state.revision = onboarding.revision ?? settings.revision;
      state.updated = onboarding.updated_at ?? settings.updated_at;
      renderPage();
      openSSE(id);
      startIncidentRefresh(id);
    } catch (e) {
      if (e.message !== "unauth" && state.guild.id === id) {
        $("#main").replaceChildren(
          el(
            "div",
            { class: "empty" },
            el("strong", { text: "تعذر تحميل الإعدادات" }),
            el("button", {
              class: "btn primary",
              text: "إعادة المحاولة",
              onClick: () => loadGuild(id),
            }),
          ),
        );
      }
    }
  }
  function chooseGuild(id) {
    if (id === state.guild.id) return;
    if (dirty()) {
      const back = el("div", {
          class: "modal-back",
          role: "dialog",
          "aria-modal": "true",
        }),
        m = el(
          "div",
          { class: "modal" },
          el("h2", { text: "لديك تعديلات غير محفوظة" }),
          el("p", { text: "ماذا تريد قبل الانتقال إلى سيرفر آخر؟" }),
        ),
        a = el("div", { class: "modal-actions" });
      a.append(
        el("button", {
          class: "save",
          text: "حفظ",
          onClick: async () => {
            await save();
            if (!dirty()) {
              back.remove();
              loadGuild(id);
            }
          },
        }),
        el("button", {
          text: "تجاهل",
          onClick: () => {
            back.remove();
            loadGuild(id);
          },
        }),
        el("button", { text: "البقاء", onClick: () => back.remove() }),
      );
      m.append(a);
      back.append(m);
      document.body.append(back);
    } else loadGuild(id);
  }
  function openSSE(id) {
    state.source = new EventSource(`api/guild/${id}/events`);
    state.source.addEventListener("settings", (e) => {
      if (state.guild?.id !== id) return;
      const d = JSON.parse(e.data);
      if (state.revision != null && d.revision <= state.revision) return;
      const wasDirty = dirty();
      adopt(d, true);
      renderPage();
      if (!wasDirty) toast("تم تحديث الإعدادات من جلسة أخرى", "info", 2600);
    });
    state.source.addEventListener("ping", (e) => {
      const d = JSON.parse(e.data);
      updatePing(d.online ? "online" : "offline", d.latency_ms);
    });
    state.source.addEventListener("expired", redirect);
    state.source.addEventListener("action", (e) => {
      if (state.guild?.id !== id) return;
      const payload = JSON.parse(e.data);
      state.actions = [{ ...payload, timestamp: new Date().toISOString() }, ...(state.actions || [])].slice(0, 100);
      if (state.activeView !== "settings") renderPage();
    });
    state.source.onerror = () => {
      updatePing("wait");
      setOffline(true);
    };
  }
  // Network and lifecycle events
  function closeSSE() {
    state.source?.close();
    state.source = null;
  }
  function setOffline(check = false) {
    if (!navigator.onLine || check) {
      state.online = false;
      let x = $(".net-banner");
      if (!x) {
        x = el("div", {
          class: "net-banner",
          text: "⚠️ انقطع الاتصال بالشبكة — الحفظ معطّل مؤقتاً",
        });
        document.body.append(x);
      }
      const b = $(".dock .primary");
      if (b) b.disabled = true;
    }
  }
  async function health() {
    if (!navigator.onLine) {
      setOffline(true);
      return;
    }
    try {
      const r = await api("api/health");
      if (!r.ok) throw Error();
      state.failures = 0;
      state.online = true;
      $(".net-banner")?.remove();
      const b = $(".dock .primary");
      if (b) b.disabled = false;
      await refreshDashboardStats(state.guild?.id, false);
    } catch (e) {
      state.failures++;
      if (state.failures >= 2) setOffline(true);
    }
  }
  async function start() {
    try {
      const r = await api("api/me"),
        me = await r.json();
      if (!me.auth) return redirect();
      state.session = me.session;
      if (!state.session.guilds?.length) {
        const inviteUrl = state.session.invite_url;
        app.replaceChildren(
          el(
            "main",
            { class: "page" },
            el(
              "div",
              { class: "empty access-empty" },
              el("strong", { text: "لا توجد سيرفرات مصرّح بها" }),
              el("span", {
                text: "البوت غير موجود حالياً في أي سيرفر تملك صلاحية إدارته.",
              }),
              inviteUrl
                ? el(
                    "div",
                    { class: "empty-actions" },
                    el(
                      "a",
                      {
                        class: "invite-button",
                        href: inviteUrl,
                        target: "_blank",
                        rel: "noopener noreferrer",
                      },
                      "دعوة البوت إلى سيرفر",
                    ),
                    el("small", {
                      class: "empty-hint",
                      text: "اختر السيرفر من صفحة Discord ثم وافق على الدعوة، وبعدها أعد تحميل الداشبورد.",
                    }),
                  )
                : el("span", {
                    class: "empty-hint",
                    text: "رابط دعوة البوت غير متاح حالياً. تحقق من إعداد CLIENT_ID ثم أعد المحاولة.",
                  }),
            ),
          ),
        );
        return;
      }
      const id = sessionStorage.getItem("dashboard-guild");
      loadGuild(
        state.session.guilds.some((g) => g.id === id)
          ? id
          : state.session.guilds[0].id,
      );
    } catch (e) {
      if (e.message !== "unauth")
        app.replaceChildren(
          el(
            "main",
            { class: "page" },
            el("div", {
              class: "empty",
              text: "تعذر التحقق من الجلسة. أعد تحميل الصفحة.",
            }),
          ),
        );
    }
  }
  addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      openCommandPalette();
      return;
    }
    if (e.key === "Escape") {
      $(".command-palette-back")?.remove();
      toggleDrawer(false);
    }
    if (e.key !== "Escape") return;
    document.querySelectorAll(".popover:not([hidden])").forEach((p) => {
      p.hidden = true;
      const trigger = p.parentElement?.querySelector("button");
      trigger?.setAttribute("aria-expanded", "false");
      trigger?.focus();
    });
  });
  addEventListener("pointerdown", (e) => {
    document.querySelectorAll(".popover:not([hidden])").forEach((p) => {
      if (!p.parentElement.contains(e.target)) {
        p.hidden = true;
        p.parentElement.querySelector("button")?.setAttribute("aria-expanded", "false");
      }
    });
  });
  addEventListener("online", health);
  addEventListener("offline", () => setOffline(true));
  addEventListener("beforeunload", (e) => {
    closeSSE();
    if (dirty()) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  setInterval(health, 15000);
  setupPwa();
  start();
})();
