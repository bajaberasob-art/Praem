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
    selfRoleBuilder: null,
    onboardingPreviewTimer: null,
    fields: {},
    saving: false,
    online: navigator.onLine,
    failures: 0,
    source: null,
    newer: false,
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
    const local = keepLocal ? changes() : {};
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
    app.replaceChildren(
      header(),
      el(
        "main",
        { class: "page", id: "main" },
        el(
          "div",
          { class: "loading" },
          el("div", { class: "skeleton" }),
          el("p", { text: "جارٍ تحميل إعدادات السيرفر…" }),
        ),
      ),
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
        const tag = token.startsWith("`") ? "code" : token.startsWith("*") || token.startsWith("_") ? "strong" : "em";
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
          el("div", { class: "role-matrix-card human" }, el("span", { class: "matrix-icon", text: "◉" }), el("div", { class: "matrix-copy" }, el("strong", { text: "الأعضاء البشر" }), el("small", { text: roleName(state.draft.member_auto_role_id) })), selector("member_auto_role_id", "رتبة الأعضاء", "role")),
          el("div", { class: "role-matrix-card bot" }, el("span", { class: "matrix-icon", text: "⌘" }), el("div", { class: "matrix-copy" }, el("strong", { text: "البوتات" }), el("small", { text: roleName(state.draft.bot_auto_role_id) })), selector("bot_auto_role_id", "رتبة البوتات", "role")),
          el("div", { class: "role-matrix-card all" }, el("span", { class: "matrix-icon", text: "✦" }), el("div", { class: "matrix-copy" }, el("strong", { text: "رتبة افتراضية للجميع" }), el("small", { text: roleName(state.draft.auto_role_id) })), selector("auto_role_id", "رتبة عامة", "role")),
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
    main.append(
      el(
        "div",
        { class: "intro" },
        el("div", { class: "eyebrow", text: `${state.guild.name} / SETTINGS` }),
        el("h1", { text: "إعدادات السيرفر" }),
        el("p", {
          text: "اضبط سلوك البوت ثم احفظ التغييرات عندما تكون جاهزاً.",
        }),
      ),
    );
    main.append(onboardingView(), securityView());
    const general = el("div", { class: "fields" });
    general.append(
      input("prefix", "بادئة الأوامر", "text", {
        minlength: "1",
        maxlength: "5",
        required: true,
      }),
    );
    main.append(card("عام", general));
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
      input("anti_alt_days", "عمر الحساب الأدنى (أيام)", "number", {
        min: "0",
        max: "365",
      }),
      selector("captcha_role_id", "رتبة اجتياز الكابتشا", "role"),
      selector("log_channel_id", "قناة السجل", "channel"),
    );
    main.append(card("الحماية", protect));
    const econ = el("div", { class: "fields" }),
      tax = input("economy_tax", "ضريبة الاقتصاد", "number", {
        min: "0",
        max: "100",
        step: "0.5",
      });
    tax.classList.add("suffix");
    tax.append(el("span", { text: "%" }));
    econ.append(
      tax,
      input("daily_amount", "المبلغ اليومي", "number", {
        min: "0",
        max: "1000000",
        step: "1",
      }),
    );
    main.append(
      card("الاقتصاد", econ),
      el("footer", {
        class: "footer",
        text: "الإعدادات تُحفظ في قاعدة بيانات البوت وتُطبّق على الميزات المرتبطة بها",
      }),
    );
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
      const r = await api(`api/guild/${guildId}/settings`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRF-Token": state.session.csrf,
        },
        body: JSON.stringify({ revision: state.revision, changes: snap }),
      });
      if (guildId !== state.guild.id) return;
      const data = await r.json();
      if (r.status === 200 && data.ok) {
        // تعديلات أُجريت أثناء الحفظ فقط هي التي تبقى غير محفوظة
        const later = Object.fromEntries(
          keys
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
      } else if (r.status === 403) toast("لا تملك صلاحية تعديل هذا السيرفر");
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
    renderShell();
    closeSSE();
    stopIncidentRefresh();
    try {
      const [mr, sr, ir] = await Promise.all([
        api(`api/guild/${id}/meta`),
        api(`api/guild/${id}/settings`),
        api(`api/guild/${id}/security/incidents`),
      ]);
      if (state.guild.id !== id) return;
      const [meta, settings, incidents] = await Promise.all([
        mr.json(),
        sr.json(),
        ir.ok ? ir.json() : Promise.resolve({ incidents: [] }),
      ]);
      if (state.guild.id !== id) return;
      state.meta = meta;
      state.incidents = incidents.incidents || [];
      state.whitelist = incidents.whitelist || [];
      state.lockdown = Boolean(incidents.locked);
      state.baseline = clone(settings.settings);
      state.draft = clone(settings.settings);
      state.revision = settings.revision;
      state.updated = settings.updated_at;
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
