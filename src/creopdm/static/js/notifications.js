window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.notifications = {
  /**
   * The bell, the toast popups and the "(2) CreoPDM" tab title.
   *
   * Always on for a signed-in user who may view comments. The topbar (bell, toast stack) lives
   * outside <main>, so it survives soft navigation; only the listeners are rebound at each boot.
   * Delivery is a light poll of GET /api/notifications?after=<id> (~15 s). `seen_at` is stored on
   * the server, so a reload or a second tab never toasts the same message twice. The poll stops
   * for good after the server refuses it (403) or reports that notifications are not available.
   */
  init(shell) {
    const $ = shell.$;
    const bell = $("#notif-bell");
    const stack = $("#toast-stack");
    if (!bell || !stack) return;

    // State outlives page boots: one timer and one cursor for the whole browser tab.
    const state = (window.__creopdmNotif = window.__creopdmNotif || {
      lastId: null,
      unread: 0,
      stopped: false,
      timer: 0,
      toasts: [],
      polling: false,
    });
    const POLL_MS = 15000;
    const MAX_TOASTS = 3;
    const STICKY = new Set(["MENTION", "RESOLVED", "REOPENED"]);

    function esc(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    /** Where a notification leads: the exact place its thread is shown. */
    function linkFor(item) {
      const p = encodeURIComponent(item.product_uuid || "");
      const o = encodeURIComponent(item.object_uuid || "");
      const v = encodeURIComponent(item.version_uuid || "");
      const t = item.thread_uuid ? `&thread=${encodeURIComponent(item.thread_uuid)}` : "";
      const type = item.target_type;
      // Activity on a watched product (not a comment): the file's Details, or the product's Files.
      if (item.kind === "WATCH") {
        return type === "OBJECT" && o ? `/products/${p}/objects/${o}` : `/?product=${p}`;
      }
      if (type === "OBJECT" && o) return `/products/${p}/objects/${o}?tab=discussion${t}`;
      if (type === "VERSION" && o && v) return `/products/${p}/objects/${o}/versions/${v}?tab=discussion${t}`;
      if (type === "BASELINE") {
        return `/?product=${p}&tab=baselines&baseline=${encodeURIComponent(item.target_uuid)}&discussion=1${t}`;
      }
      if (type === "BASELINE_MEMBER" && o && v) {
        const baseline = encodeURIComponent(String(item.target_uuid || "").split("/")[0]);
        return `/products/${p}/objects/${o}/versions/${v}?baseline=${baseline}&tab=discussion${t}`;
      }
      return `/?product=${p}&tab=discussion${t}`;
    }

    async function api(path, options) {
      const response = await fetch(path, options);
      if (response.status === 403 || response.status === 401) {
        stop();
        return null;
      }
      if (!response.ok) return null;
      if (response.status === 204) return {};
      return response.json();
    }

    function stop() {
      state.stopped = true;
      if (state.timer) window.clearInterval(state.timer);
      state.timer = 0;
      bell.hidden = true;
    }

    /** "(2) CreoPDM": a background tab shows that something is waiting. */
    function paintTitle() {
      const base = document.title.replace(/^\(\d+\)\s+/, "");
      document.title = state.unread > 0 ? `(${state.unread}) ${base}` : base;
    }

    function paintBell() {
      bell.hidden = false;
      const count = bell.querySelector("#notif-count");
      if (count) {
        count.textContent = state.unread > 99 ? "99+" : String(state.unread);
        count.hidden = state.unread <= 0;
      }
      bell.title = state.unread ? `${state.unread} unread notification${state.unread === 1 ? "" : "s"}` : "Notifications";
      paintTitle();
    }

    function markSeen(ids) {
      if (!ids.length) return;
      void api("/api/notifications/seen", {
        method: "POST",
        keepalive: true, // a click that navigates away must still record it
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids }),
      });
    }

    function markRead(ids) {
      return api("/api/notifications/read", {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(ids ? { ids } : {}),
      });
    }

    function openItem(item) {
      void markRead([item.id]).then(() => poll());
      closePanel();
      void shell.softNavigate(linkFor(item));
    }

    // ---------------------------------------------------------------- toasts
    function dismissToast(entry) {
      if (entry.timer) window.clearTimeout(entry.timer);
      state.toasts = state.toasts.filter((item) => item !== entry);
      paintToasts();
    }

    function paintToasts() {
      stack.textContent = "";
      const visible = state.toasts.slice(-MAX_TOASTS);
      const hidden = state.toasts.length - visible.length;
      if (hidden > 0) {
        const more = document.createElement("div");
        more.className = "toast toast-more";
        more.textContent = `+${hidden} more — open the bell`;
        more.addEventListener("click", () => openPanel());
        stack.appendChild(more);
      }
      for (const entry of visible) {
        const el = document.createElement("div");
        el.className = `toast toast-${String(entry.item.kind || "").toLowerCase()}`;
        el.setAttribute("role", "status");
        el.innerHTML =
          `<button type="button" class="toast-close" aria-label="Dismiss">×</button>` +
          `<div class="toast-title">${esc(entry.item.title)}</div>` +
          `<div class="toast-excerpt">${esc(entry.item.excerpt)}</div>` +
          `<div class="toast-product muted small">${esc(entry.item.product_name)}</div>`;
        el.addEventListener("click", (event) => {
          if (event.target.closest(".toast-close")) {
            dismissToast(entry);
            return;
          }
          dismissToast(entry);
          openItem(entry.item);
        });
        stack.appendChild(el);
      }
    }

    function showToast(item) {
      if (state.toasts.some((entry) => entry.item.id === item.id)) return;
      const entry = { item, timer: 0 };
      // Mentions and the resolve loop stay until dismissed; the rest fades after a few seconds.
      if (!STICKY.has(item.kind)) {
        entry.timer = window.setTimeout(() => dismissToast(entry), 8000);
      }
      state.toasts.push(entry);
      paintToasts();
    }

    // ---------------------------------------------------------------- polling
    async function poll() {
      if (state.stopped || state.polling) return;
      state.polling = true;
      try {
        const first = state.lastId === null;
        const body = await api(first ? "/api/notifications?limit=20" : `/api/notifications?after=${state.lastId}&limit=50`);
        if (!body) return;
        if (body.enabled === false) {
          stop();
          return;
        }
        state.unread = Number(body.unread) || 0;
        const fresh = (body.items || []).filter((item) => !item.seen);
        // Oldest first so the newest toast ends up on top.
        fresh.sort((a, b) => a.id - b.id).forEach(showToast);
        markSeen(fresh.map((item) => item.id));
        state.lastId = Number(body.latest_id) || state.lastId || 0;
        paintBell();
        // New comments change the counts and glyphs too.
        if (fresh.length) void window.__creopdmModules.notifications?.refreshCounts?.();
        if (!$("#notif-panel")?.hidden) void renderPanel();
      } finally {
        state.polling = false;
      }
    }

    // ---------------------------------------------------------------- bell panel
    const panel = $("#notif-panel");

    function closePanel() {
      if (panel) panel.hidden = true;
      bell.setAttribute("aria-expanded", "false");
    }

    function openPanel() {
      if (!panel) return;
      panel.hidden = false;
      bell.setAttribute("aria-expanded", "true");
      void renderPanel();
    }

    async function renderPanel() {
      const body = await api("/api/notifications?limit=20");
      if (!body || !panel) return;
      const list = panel.querySelector("#notif-list");
      const items = body.items || [];
      state.unread = Number(body.unread) || 0;
      paintBell();
      // Clear is offered only after Mark all read: nothing unread, something to clear.
      // Mark all read only while something is unread (hidden on an empty list and once all is read).
      const readAll = $("#notif-read-all");
      if (readAll) readAll.hidden = !items.length || state.unread <= 0;
      const clear = $("#notif-clear");
      if (clear) {
        clear.hidden = state.unread > 0 || !items.length;
      }
      if (!items.length) {
        list.innerHTML = `<p class="muted small notif-empty">Nothing yet. Mentions, replies and resolved comments show up here.</p>`;
        return;
      }
      list.innerHTML = items
        .map(
          (item) =>
            `<button type="button" class="notif-item${item.read ? "" : " is-unread"}" data-notif="${item.id}">` +
            `<span class="notif-title">${esc(item.title)}</span>` +
            `<span class="notif-excerpt">${esc(item.excerpt)}</span>` +
            `<span class="notif-meta muted small" title="${esc(shell.formatStampPretty(item.created_at))}">` +
            `${esc(item.product_name)} · ${esc(shell.formatStamp(item.created_at))}</span></button>`
        )
        .join("");
      list.querySelectorAll("[data-notif]").forEach((button) => {
        button.addEventListener("click", () => {
          const item = items.find((entry) => String(entry.id) === button.getAttribute("data-notif"));
          if (item) openItem(item);
        });
      });
    }

    bell.addEventListener("click", (event) => {
      event.stopPropagation();
      if (panel?.hidden === false) closePanel();
      else openPanel();
    });
    $("#notif-read-all")?.addEventListener("click", () => {
      void markRead(null).then(() => {
        void poll();
        void renderPanel();
      });
    });
    $("#notif-clear")?.addEventListener("click", () => {
      void api("/api/notifications/clear", { method: "POST", keepalive: true }).then(() => {
        state.toasts.forEach((entry) => entry.timer && window.clearTimeout(entry.timer));
        state.toasts = [];
        paintToasts();
        void poll();
        void renderPanel();
      });
    });
    document.addEventListener("click", (event) => {
      if (panel && !panel.hidden && !panel.contains(event.target) && !bell.contains(event.target)) closePanel();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && panel && !panel.hidden) closePanel();
    });
    window.addEventListener("focus", () => void poll());

    // ---------------------------------------------------------------- counts and glyphs
    // One summary call per page: the Discussion tab / pill counts and the speech-bubble glyphs
    // (open threads; accent colour when one mentions you). Never one request per row.
    let lastSummary = null;

    function productUuid() {
      return (
        $("#panel-discussion")?.dataset.product ||
        $("#metric-filters")?.dataset.product ||
        $("#discussion-config")?.dataset.product ||
        ""
      );
    }

    function slot(type, uuid) {
      return lastSummary?.targets?.[type]?.[uuid] || null;
    }

    function glyphHtml(info, href) {
      const mine = info.mentions_me > 0;
      const tip =
        `${info.open} open comment${info.open === 1 ? "" : "s"}` +
        (mine ? `, ${info.mentions_me} mention${info.mentions_me === 1 ? "s" : ""} you` : "");
      return (
        `<a class="discuss-glyph${mine ? " is-mine" : ""}" href="${href}" title="${esc(tip)}" aria-label="${esc(tip)}">` +
        `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3h11A2.5 2.5 0 0 1 20 5.5v8a2.5 2.5 0 0 1-2.5 2.5H11l-4.2 3.6a.6.6 0 0 1-1-.46V16h-.3A2.5 2.5 0 0 1 3 13.5Z"/></svg>` +
        `<span>${info.open}</span></a>`
      );
    }

    function paintTabAndPill() {
      const open = lastSummary?.open || 0;
      const tab = $('.tabs .tab[data-tab="discussion"]');
      if (tab) {
        const mine = lastSummary?.mentions_me || 0;
        tab.textContent = open ? `Discussion · ${open}` : "Discussion";
        tab.classList.toggle("has-mention", mine > 0);
      }
      const pill = $("#discussion-pill-item");
      if (pill) pill.hidden = open === 0;
      const strong = $("#discussion-pill-count");
      if (strong) strong.textContent = String(open);
    }

    function paintGlyphs() {
      document.querySelectorAll(".discuss-glyph").forEach((el) => el.remove());
      const product = productUuid();
      if (!product || !lastSummary) return;
      const p = encodeURIComponent(product);
      // Files list: after the file name; opens that file's Discussion tab.
      document.querySelectorAll("#object-table tr.object-row[data-uuid]").forEach((row) => {
        const uuid = row.getAttribute("data-uuid");
        const info = slot("OBJECT", uuid);
        const name = row.querySelector(".name-with-icon");
        if (info && name) {
          name.insertAdjacentHTML("beforeend", glyphHtml(info, `/products/${p}/objects/${encodeURIComponent(uuid)}?tab=discussion`));
        }
      });
      // Baselines list: after the baseline name; opens the baseline with its discussion.
      document.querySelectorAll("#baselines-table tr.baseline-row[data-baseline]").forEach((row) => {
        const uuid = row.getAttribute("data-baseline");
        const info = slot("BASELINE", uuid);
        const cell = row.querySelector(".baseline-name-cell");
        if (info && cell) {
          cell.insertAdjacentHTML("beforeend", glyphHtml(info, `/?product=${p}&tab=baselines&baseline=${encodeURIComponent(uuid)}&discussion=1`));
        }
      });
      // A baseline's own files: comments on that exact baseline file (its Details page, as in the baseline).
      const open = $("#baseline-browse")?.hidden === false ? $("#baseline-browse")?.dataset.baseline : "";
      if (open) {
        document.querySelectorAll("#baseline-browse-table tr.object-row[data-uuid]").forEach((row) => {
          const uuid = row.getAttribute("data-uuid");
          const info = slot("BASELINE_MEMBER", `${open}/${uuid}`);
          const name = row.querySelector(".name-with-icon");
          const detail = row.getAttribute("data-detail");
          if (info && name && detail) {
            name.insertAdjacentHTML("beforeend", glyphHtml(info, `${detail}&tab=discussion`));
          }
        });
      }
    }

    async function refreshCounts() {
      const product = productUuid();
      if (!product) return;
      // Plain fetch: a refused product must not stop the notification poll (api() does on 403).
      let body = null;
      try {
        const response = await fetch(`/api/products/${encodeURIComponent(product)}/comments/summary`);
        if (response.ok) body = await response.json();
      } catch {
        body = null;
      }
      if (!body) return;
      lastSummary = body;
      paintTabAndPill();
      paintGlyphs();
    }

    // A glyph click opens that Discussion; it must not select the row or start a double-click open.
    document.addEventListener(
      "click",
      (event) => {
        const glyph = event.target.closest?.(".discuss-glyph");
        if (!glyph) return;
        event.preventDefault();
        event.stopPropagation();
        void shell.softNavigate(glyph.getAttribute("href"));
      },
      true
    );

    // Rows are rebuilt by sorting, searching and tab loads: repaint the glyphs when they change.
    let repaintTimer = 0;
    const repaint = () => {
      window.clearTimeout(repaintTimer);
      repaintTimer = window.setTimeout(paintGlyphs, 60);
    };
    ["#object-table tbody", "#baselines-table tbody", "#baseline-browse-table tbody"].forEach((sel) => {
      const body = $(sel);
      if (body) new MutationObserver(repaint).observe(body, { childList: true });
    });
    const browsePane = $("#baseline-browse");
    if (browsePane) new MutationObserver(repaint).observe(browsePane, { attributes: true, attributeFilter: ["hidden"] });

    const mod = window.__creopdmModules.notifications;
    mod.refreshCounts = refreshCounts;
    mod.paintGlyphs = paintGlyphs;
    void refreshCounts();

    if (!state.stopped) {
      paintBell();
      if (!state.timer) state.timer = window.setInterval(() => void poll(), POLL_MS);
      void poll();
    }
  },
};
