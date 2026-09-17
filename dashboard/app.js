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
    baseline: null,
    draft: null,
    revision: null,
    updated: null,
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
    "welcome_channel_id",
    "welcome_message",
    "log_channel_id",
    "anti_spam_enabled",
    "anti_link_enabled",
    "economy_tax",
    "daily_amount",
  ];
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const changes = () =>
    !state.baseline || !state.draft
      ? {}
      : Object.fromEntries(
          keys
            .filter((k) => state.baseline[k] !== state.draft[k])
            .map((k) => [k, state.draft[k]]),
        );
  const dirty = () => Object.keys(changes()).length > 0;
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
  function preview() {
    let t = state.draft.welcome_message || "";
    const guild = state.guild;
    t = t
      .replace(/\{user\}/g, "@عضو_جديد")
      .replace(/\{server\}/g, guild.name)
      .replace(
        /\{count\}/g,
        guild.members == null ? "1000" : String(guild.members),
      );
    return el(
      "div",
      { id: "preview" },
      el("div", { class: "preview-title", text: "معاينة مباشرة" }),
      el(
        "div",
        { class: "discord" },
        el(
          "div",
          { class: "msg-head" },
          el("span", { class: "bot-face", text: "ب" }),
          el("b", { text: "البوت" }),
          el("span", { class: "bot-tag", text: "BOT" }),
        ),
        el("div", {
          class: "embed",
          text: t || "اكتب رسالة الترحيب لرؤية المعاينة.",
        }),
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
  function incidentsCard() {
    const body = el("div", { class: "incident-list" });
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
    return card("سجل الحوادث الأمنية", body);
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
      toggle("anti_spam_enabled", "تفعيل مكافحة السبام"),
      toggle("anti_link_enabled", "تفعيل مكافحة الروابط"),
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
    const welcome = el("div", { class: "fields" });
    welcome.append(
      selector("welcome_channel_id", "قناة الترحيب", "channel"),
      selector("auto_role_id", "الرتبة التلقائية", "role"),
    );
    const ta = el("textarea", {
      id: "in-welcome_message",
      maxlength: "1000",
      placeholder: "مرحباً {user} في {server}",
    });
    ta.value = state.draft.welcome_message || "";
    const count = el("div", {
      class: "counter",
      text: `${ta.value.length} / 1000`,
    });
    ta.oninput = () => {
      state.draft.welcome_message = ta.value;
      count.textContent = `${ta.value.length} / 1000`;
      renderDynamic();
      const pv = $("#preview");
      if (pv) pv.replaceWith(preview().cloneNode(true));
    };
    const wfield = field("رسالة الترحيب", ta, "welcome_message");
    wfield.classList.add("wide");
    wfield.append(count, el("div", { id: "preview" }));
    wfield.lastChild.replaceWith(preview());
    welcome.append(wfield);
    main.append(card("الترحيب", welcome));
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
      incidentsCard(),
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
  async function loadGuild(id) {
    const g = state.session.guilds.find((x) => x.id === id);
    if (!g) return;
    state.guild = g;
    sessionStorage.setItem("dashboard-guild", id);
    state.meta = state.baseline = state.draft = null;
    renderShell();
    closeSSE();
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
      state.baseline = clone(settings.settings);
      state.draft = clone(settings.settings);
      state.revision = settings.revision;
      state.updated = settings.updated_at;
      renderPage();
      openSSE(id);
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
