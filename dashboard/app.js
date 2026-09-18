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
    whitelist: [],
    lockdown: false,
    incidentTimer: null,
    baseline: null,
    draft: null,
    revision: null,
    updated: null,
    onboarding: null,
    commandStudio: { commands: [], roles: [], channels: [] },
    autoResponses: [],
    commandSearch: "",
    tickets: {
      active: [],
      archive: [],
      kpis: [],
      canned: [],
    },
    ticketSearch: "",
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
  };
  const keys = [
    "prefix",
    "anti_nuke",
    "anti_alt_days",
    "captcha_enabled",
    "captcha_role_id",
    "auto_role_id",
    "member_auto_role_id",
    "bot_auto_role_id",
    "verified_role_id",
    "unverified_role_id",
    "rules_channel_id",
    "welcome_dm_enabled",
    "welcome_channel_id",
    "welcome_message",
    "leave_message",
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
    "auto_role_id",
    "member_auto_role_id",
    "bot_auto_role_id",
    "verified_role_id",
    "unverified_role_id",
    "rules_channel_id",
  ];
  const settingsKeys = keys.filter((key) => !onboardingKeys.includes(key));
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const changes = () =>
    !state.baseline || !state.draft
      ? {}
      : Object.fromEntries(
          settingsKeys
            .filter((k) => state.baseline[k] !== state.draft[k])
            .map((k) => [k, state.draft[k]]),
        );
  const onboardingChanges = () =>
    !state.baseline || !state.draft
      ? {}
      : Object.fromEntries(
          onboardingKeys
            .filter((k) => state.baseline[k] !== state.draft[k])
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
        "div",
        { class: "brand", text: "لوحة القيادة " },
        el("i", { text: "المركزية" }),
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
    commands: { label: "الأوامر والأتمتة", icon: "⌘", hint: "Commands" },
    onboarding: { label: "الترحيب والأدوار", icon: "✦", hint: "Onboarding" },
    security: { label: "الحماية", icon: "◈", hint: "Security" },
    settings: { label: "الإعدادات", icon: "⚙", hint: "Configuration" },
  };
  function navigateView(view) {
    if (!viewLabels[view]) return;
    state.activeView = view;
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
      { class: "workspace-nav", "aria-label": "التنقل الرئيسي" },
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
      navButton("security"),
      navButton("settings"),
    );
    const moreButton = el(
      "button",
      {
        class: `nav-item ${["onboarding", "security", "settings"].includes(state.activeView) ? "active" : ""}`,
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
      renderDynamic();
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
    let choices = type === "channel" ? state.meta.channels : state.meta.roles,
      active = 0;
    const value = () => state.draft[key];
    const nameFor = (id) => choices.find((x) => x.id === id);
    function display() {
      const found = nameFor(value());
      let current;
      if (found)
        current = el(
          "span",
          { class: "choice" },
          type === "channel"
            ? el("span", { text: "#" })
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
      choices = type === "channel" ? state.meta.channels : state.meta.roles;
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
  function preview() {
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
      color: normalizePanelColor(saved?.color),
      emoji: saved?.emoji || "🏷️",
      roles: (saved?.role_specs || []).map((role) => ({
        id: String(role.id),
        label: String(role.label || role.name || role.id),
        emoji: String(role.emoji || "🏷️"),
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
        value: role.emoji || "🏷️",
        "aria-label": `إيموجي الرتبة ${index + 1}`,
      });
      label.oninput = () => (role.label = label.value);
      emoji.oninput = () => (role.emoji = emoji.value);
      roleRows.append(
        el(
          "div",
          { class: "builder-role-row" },
          el("span", { class: "role-dot", style: `background:${roles.find((r) => String(r.id) === String(role.id))?.color || "#64748b"}` }),
          emoji,
          label,
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
            el("small", { text: `${panel.role_specs?.length || 0} رتب · رسالة ${panel.message_id}` }),
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
  function commandRows() {
    const query = state.commandSearch.trim().toLowerCase();
    const commands = (state.commandStudio.commands || []).filter((command) =>
      !query ||
      command.command_name.toLowerCase().includes(query) ||
      String(command.cog || "").toLowerCase().includes(query),
    );
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
      const group = el("section", { class: "command-group" });
      group.append(el("div", { class: "command-group-title" }, el("span", { text: cog }), el("small", { text: `${items.length} أمر` })));
      items.forEach((command) => {
        const roles = commandRoles(command);
        const roleWrap = el("div", { class: "command-role-tags" });
        (state.commandStudio.roles || []).forEach((role) => {
          const active = roles.has(String(role.id));
          const tag = el("button", {
            class: `role-tag${active ? " active" : ""}`,
            type: "button",
            title: active ? "إزالة الرتبة" : "السماح للرتبة",
            text: `@${role.name}`,
          });
          tag.onclick = () => {
            pulse();
            const next = new Set(roles);
            if (next.has(String(role.id))) next.delete(String(role.id));
            else next.add(String(role.id));
            updateCommand(command, command.enabled, [...next]);
          };
          roleWrap.append(tag);
        });
        const toggleButton = el("button", {
          class: `studio-switch${command.enabled ? " on" : ""}`,
          type: "button",
          role: "switch",
          "aria-checked": String(!!command.enabled),
          "aria-label": `تفعيل ${command.command_name}`,
        }, el("i"));
        toggleButton.onclick = () => {
          pulse();
          updateCommand(command, !command.enabled, [...roles]);
        };
        group.append(el("article", { class: "command-row" },
          el("div", { class: "command-name" },
            el("strong", { text: `/${command.command_name}` }),
            el("small", { text: command.configured ? "سياسة مخصصة" : "إعداد افتراضي" }),
          ),
          el("div", { class: "command-role-picker" },
            el("span", { class: "command-role-label", text: "الرتب المسموحة — اتركها فارغة للجميع" }),
            roleWrap,
          ),
          toggleButton,
        ));
      });
      root.append(group);
    });
    return root;
  }
  async function updateCommand(command, enabled, allowedRoles) {
    try {
      const r = await api(`api/guild/${state.guild.id}/commands/toggle`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({
          command_name: command.command_name,
          enabled,
          allowed_roles: allowedRoles,
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
    form.querySelectorAll("[data-match-type]").forEach((button) => {
      button.classList.toggle("active", button.dataset.matchType === (rule?.match_type || "exact"));
    });
    const title = $("#auto-form-title");
    if (title) title.textContent = rule ? "تعديل قاعدة الرد" : "إنشاء رد تلقائي";
    form.scrollIntoView({ behavior: "smooth", block: "center" });
  }
  async function saveAutoResponder(form) {
    const selected = form.querySelector(".match-badge.active")?.dataset.matchType || "exact";
    const body = {
      trigger: form.elements.trigger.value.trim(),
      match_type: selected,
      response: form.elements.response.value,
      cooldown_seconds: Number(form.elements.cooldown_seconds.value),
      channel_id: form.elements.channel_id.value || null,
    };
    if (!body.trigger || !body.response.trim()) {
      toast("أدخل المشغل ونص الرد");
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
  async function ticketAction(ticket, action) {
    let staffId = null;
    if (action === "reassign") {
      staffId = prompt("أدخل Discord ID للموظف الجديد:", ticket.claimed_by || "");
      if (!staffId) return;
    }
    if (action === "close" && !confirm(`إغلاق التذكرة #${ticket.id} وأرشفتها؟`)) return;
    try {
      const r = await api(`api/guild/${state.guild.id}/tickets/action`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": state.session.csrf },
        body: JSON.stringify({
          ticket_id: ticket.id,
          action,
          staff_id: staffId,
          reason: "أُغلقت من لوحة الإدارة",
        }),
      });
      const data = await r.json();
      if (!r.ok) {
        toast(data.fields ? Object.values(data.fields)[0] : "تعذر تنفيذ الإجراء");
        return;
      }
      pulse();
      toast(action === "close" ? "تم إغلاق التذكرة وأرشفتها" : "تمت إعادة إسناد التذكرة", "success", 2400);
      await refreshTickets();
    } catch (error) {
      if (error.message !== "unauth") toast("تعذر الاتصال بالخادم");
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
      const roles = el("select", { class: "ticket-role-select", multiple: "multiple", "aria-label": `رتب دعم ${category.label}` });
      (state.commandStudio.roles || []).forEach((role) => {
        const option = el("option", { value: role.id }, role.name);
        option.selected = (category.support_role_ids || []).map(String).includes(String(role.id));
        roles.append(option);
      });
      roles.onchange = () => {
        state.ticketCategories[index].support_role_ids = [...roles.selectedOptions].map((option) => option.value);
      };
      wrap.append(el("div", { class: "ticket-category-row" },
        el("span", { class: "ticket-category-emoji", text: category.emoji }),
        label,
        roles,
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
        el("div", {}, el("h4", { text: "تصنيفات التذاكر" }), el("small", { text: "يمكن اختيار رتب الدعم لكل تصنيف" })),
        el("span", { class: "live-dot", text: `${state.ticketCategories.length} تصنيفات` }),
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
    if (!state.tickets.active.length) active.append(el("div", { class: "empty studio-empty", text: "لا توجد تذاكر نشطة الآن" }));
    state.tickets.active.forEach((ticket) => {
      const priority = ticket.priority || "normal";
      const label = { normal: "Normal", high: "Urgent", management: "Escalated" }[priority] || priority;
      active.append(el("article", { class: `ticket-radar-card ${priority}` },
        el("div", { class: "ticket-radar-top" }, el("span", { class: `priority-tag ${priority}`, text: label }), el("small", { text: `#${ticket.id}` })),
        el("h4", { text: ticket.subject }),
        el("p", { text: `${ticket.category_label} · ${ticket.claimed_by ? `مستلمة بواسطة ${ticket.claimed_by}` : "بانتظار الاستلام"}` }),
        el("div", { class: "ticket-radar-actions" },
          el("a", { class: "icon-action", href: `https://discord.com/channels/${state.guild.id}/${ticket.channel_id}`, target: "_blank", text: "↗", title: "فتح القناة" }),
          el("button", { class: "icon-action", type: "button", text: "⇄", title: "إعادة إسناد", onClick: () => ticketAction(ticket, "reassign") }),
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
      el("button", { class: "btn ghost", type: "button", text: "عرض السجل", onClick: () => openTicketTranscript(ticket) }),
    )));
     const cannedForm = el("form", { class: "canned-form" },
      el("input", { name: "title", class: "studio-input", placeholder: "عنوان سريع: سياسة الاسترداد" }),
      el("input", { name: "category", class: "studio-input", placeholder: "التصنيف", value: "عام" }),
      el("textarea", { name: "content", class: "studio-textarea", placeholder: "نص الرد الجاهز…" }),
       el("button", { class: "btn primary canned-submit", type: "submit", text: "حفظ الرد الجاهز" }),
    );
    cannedForm.onsubmit = (event) => { event.preventDefault(); saveCannedResponse(cannedForm); };
    const cannedList = el("div", { class: "canned-list" });
     state.tickets.canned.forEach((item) => cannedList.append(el("div", { class: "canned-row" },
       el("div", {}, el("strong", { text: item.title }), el("p", { text: item.content })),
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
      card("Ticket Launcher Studio", launchForm),
      el("section", { class: "ticket-kpi-section" }, el("div", { class: "section-heading" }, el("div", {}, el("div", { class: "eyebrow", text: "STAFF VELOCITY" }), el("h3", { text: "مؤشرات فريق الدعم" })), el("span", { class: "live-dot", text: `${kpis.length} موظفين` })), kpiCards),
      el("section", { class: "ticket-radar-section" }, el("div", { class: "section-heading" }, el("div", {}, el("div", { class: "eyebrow", text: "ACTIVE RADAR" }), el("h3", { text: "التذاكر النشطة" })), el("span", { class: "live-dot", text: `${state.tickets.active.length} مفتوحة` })), active),
      card("Searchable Transcript Vault", el("div", { class: "ticket-vault" }, archiveSearch, archiveRows)),
      card("Canned Responses Drawer", el("div", { class: "canned-drawer" }, cannedForm, cannedList)),
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
    const commandPanel = card("مصفوفة صلاحيات الأوامر",
      el("div", { class: "command-panel" },
        el("div", { class: "panel-intro" },
          el("p", { text: "تحكم في الأوامر حسب الـ Cog واربط كل أمر بالرتب المسموحة. اترك الرتب فارغة للسماح للجميع." }),
          search,
        ),
        commandRows(),
      ),
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
      el("div", { class: "auto-form-actions" },
        el("button", { class: "btn primary", type: "submit", text: "حفظ القاعدة" }),
        el("button", { class: "btn ghost", type: "button", text: "مسح", onClick: () => setRuleForm() }),
      ),
    );
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
    return el("section", { id: "view-commands", class: "commands-view" },
      el("div", { class: "studio-hero commands-hero" },
        el("div", { class: "eyebrow", text: `${state.guild.name} / COMMANDS` }),
        el("h2", { text: "استوديو الأوامر والاختصارات" }),
        el("p", { text: "اضبط الوصول، بدّل prefix فورياً، وابنِ ردوداً تلقائية بواجهة AMOLED سريعة وواضحة." }),
      ),
      prefixForm,
      commandPanel,
      card("Visual Auto-Responder Studio", form),
      el("section", { class: "active-trigger-section" },
        el("div", { class: "section-heading" },
          el("div", {}, el("div", { class: "eyebrow", text: "LIVE REGISTRY" }), el("h3", { text: "Active Triggers" })),
          el("span", { class: "live-dot", text: `${state.autoResponses.length} مفعّل` }),
        ),
        cards,
      ),
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
    else if (view === "onboarding") main.append(onboardingView());
    else if (view === "security") main.append(securityView());
    else main.append(settingsView());
    renderDock();
    renderDynamic();
  }
  function renderDynamic() {
    Object.keys(state.fields).forEach((k) => {
      const x = $(`#err-${k}`);
      if (x) x.textContent = state.fields[k];
    });
    const d = $(".dock");
    if (d) d.classList.toggle("show", dirty());
    const onboardingSave = $(".onboarding-save");
    if (onboardingSave) onboardingSave.disabled = !onboardingDirty() || state.saving || !state.online;
    const onboardingTest = $(".onboarding-test");
    if (onboardingTest) onboardingTest.disabled = !state.online || state.saving;
    document.querySelectorAll("[data-role-matrix-key]").forEach((node) => {
      node.textContent = roleName(state.draft[node.dataset.roleMatrixKey]);
    });
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
        onClick: save,
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
            .filter((k) => state.draft[k] !== sent[k])
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
      const r = await api(`api/guild/${state.guild.id}/onboarding/self-roles`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({
          target_channel_id: String(builder.target_channel_id),
          title: builder.title,
          description: builder.description,
          color: normalizePanelColor(builder.color),
          emoji: builder.emoji,
          roles: builder.roles.map((role) => ({
            id: String(role.id),
            label: String(role.label || roleName(role.id)).slice(0, 100),
            emoji: String(role.emoji || "🏷️").slice(0, 32),
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
  function startIncidentRefresh(id) {
    stopIncidentRefresh();
    state.incidentTimer = setInterval(() => refreshIncidents(id, true), 15000);
  }
  async function loadGuild(id) {
    const g = state.session.guilds.find((x) => x.id === id);
    if (!g) return;
    state.guild = g;
    sessionStorage.setItem("dashboard-guild", id);
    state.meta = state.baseline = state.draft = null;
    state.onboarding = null;
    state.commandStudio = { commands: [], roles: [], channels: [] };
    state.autoResponses = [];
    state.commandSearch = "";
    state.tickets = { active: [], archive: [], kpis: [], canned: [] };
    state.ticketSearch = "";
    state.selfRoleBuilder = null;
    state.fields = {};
    renderShell();
    closeSSE();
    stopIncidentRefresh();
    try {
      const [mr, sr, ir, or, cr, ar, ta, tv, tk, tc] = await Promise.all([
        api(`api/guild/${id}/meta`),
        api(`api/guild/${id}/settings`),
        api(`api/guild/${id}/security/incidents`),
        api(`api/guild/${id}/onboarding`),
        api(`api/guild/${id}/commands`),
        api(`api/guild/${id}/auto-responses`),
        api(`api/guild/${id}/tickets/active`),
        api(`api/guild/${id}/tickets/archive`),
        api(`api/guild/${id}/tickets/kpis`),
        api(`api/guild/${id}/tickets/canned`),
      ]);
      if (state.guild.id !== id) return;
      const [meta, settings, incidents, onboarding, commands, autoResponses, activeTickets, archiveTickets, ticketKpis, canned] = await Promise.all([
        mr.json(),
        sr.json(),
        ir.ok ? ir.json() : Promise.resolve({ incidents: [] }),
        or.json(),
        cr.ok ? cr.json() : Promise.resolve({ commands: [], roles: [], channels: [] }),
        ar.ok ? ar.json() : Promise.resolve({ rules: [], channels: [] }),
        ta.ok ? ta.json() : Promise.resolve({ tickets: [] }),
        tv.ok ? tv.json() : Promise.resolve({ tickets: [] }),
        tk.ok ? tk.json() : Promise.resolve({ kpis: [] }),
        tc.ok ? tc.json() : Promise.resolve({ responses: [] }),
      ]);
      if (state.guild.id !== id) return;
      state.meta = meta;
      state.commandStudio = {
        commands: commands.commands || [],
        roles: commands.roles || meta.roles || [],
        channels: commands.channels || meta.channels || [],
      };
      state.autoResponses = autoResponses.rules || [];
      state.tickets = {
        active: activeTickets.tickets || [],
        archive: archiveTickets.tickets || [],
        kpis: ticketKpis.kpis || [],
        canned: canned.responses || [],
      };
      state.incidents = incidents.incidents || [];
      state.whitelist = incidents.whitelist || [];
      state.lockdown = Boolean(incidents.locked);
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
        app.replaceChildren(
          el(
            "main",
            { class: "page" },
            el(
              "div",
              { class: "empty" },
              el("strong", { text: "لا توجد سيرفرات مصرّح بها" }),
              el("span", {
                text: "اطلب صلاحية الوصول إلى سيرفر Discord ثم أعد المحاولة.",
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
  start();
})();
