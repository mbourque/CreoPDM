window.__creopdmBoot = function creopdmBoot(options = {}) {
  const soft = Boolean(options.soft);
  window.__creopdmAbort?.abort();
  const pageAbort = new AbortController();
  window.__creopdmAbort = pageAbort;
  const pageSignal = pageAbort.signal;
  const pageIntervals = [];
  const origAddEventListener = EventTarget.prototype.addEventListener;
  origAddEventListener.call(pageSignal, "abort", () => {
    pageIntervals.forEach((id) => {
      try {
        window.clearInterval(id);
      } catch {
        /* ignore */
      }
    });
    pageIntervals.length = 0;
  });
  function trackedInterval(fn, ms) {
    const id = window.setInterval(fn, ms);
    pageIntervals.push(id);
    return id;
  }
  // Soft project switches re-run this boot; abort prior listeners via signal.
  EventTarget.prototype.addEventListener = function creopdmAddEventListener(type, listener, options) {
    let opts;
    if (options === true) opts = { capture: true, signal: pageSignal };
    else if (options === false || options == null) opts = { signal: pageSignal };
    else opts = { ...options, signal: options.signal || pageSignal };
    return origAddEventListener.call(this, type, listener, opts);
  };

  try {

  const $ = (sel, root = document) => root.querySelector(sel);

  function formatByteSize(value) {
    const size = Number(value);
    if (!Number.isFinite(size) || size < 0) return "—";
    if (size < 1024) return `${Math.round(size)} B`;
    if (size < 1024 * 1024) {
      const kb = size / 1024;
      const text = kb >= 10 ? String(Math.round(kb)) : String(Math.round(kb * 10) / 10);
      return `${text} KB`;
    }
    const mb = size / (1024 * 1024);
    const text = mb >= 10 ? String(Math.round(mb)) : String(Math.round(mb * 10) / 10);
    return `${text} MB`;
  }

  function eventEl(event) {
    const node = event?.target;
    if (!node) return null;
    return node.nodeType === 1 ? node : node.parentElement;
  }

  function inCreoBrowser() {
    try {
      if (window.external && window.external.ptc) return true;
    } catch {
      /* Chromium / Linux Creo may not expose window.external.ptc */
    }
    try {
      if (window.CreoJS && typeof window.CreoJS.isAvailable === "function" && window.CreoJS.isAvailable()) {
        return true;
      }
    } catch {
      /* ignore */
    }
    // Chromium Creo often omits external.ptc / isAvailable while the session is live.
    try {
      if (typeof pfcGetCurrentSession === "function" && pfcGetCurrentSession()) {
        return true;
      }
    } catch {
      /* not in a Creo session */
    }
    return Boolean(window.CreoJS);
  }

  const creoJSReady =
    soft && window.CreoJS
      ? Promise.resolve(true)
      : window.__creopdmCreoJSReady ||
        (window.__creopdmCreoJSReady = (function loadHostedCreoJS() {
    if (window.CreoJS) return Promise.resolve(true);
    return new Promise((resolve) => {
      let settled = false;
      const done = (ok) => {
        if (settled) return;
        settled = true;
        resolve(Boolean(ok));
      };
      const tryInit = () => {
        try {
          if (
            document.readyState === "complete" &&
            window.CreoJS &&
            typeof window.CreoJS.$INITIALIZE === "function"
          ) {
            window.CreoJS.$INITIALIZE();
          }
        } catch {
          /* keep going; Creo may still expose CreoJS */
        }
      };
      // Creo may inject CreoJS after scanning text/creojs scripts.
      // Wait longer when the PTC bridge is present so we don't load a second copy.
      let tries = 0;
      const hasBridge = () => {
        try {
          return !!(window.external && window.external.ptc);
        } catch {
          return false;
        }
      };
      const maxTries = hasBridge() ? 80 : 40;
      const poll = trackedInterval(() => {
        tries += 1;
        if (window.CreoJS) {
          window.clearInterval(poll);
          tryInit();
          done(true);
          return;
        }
        if (tries < maxTries) return;
        window.clearInterval(poll);
        // Outside Creo, skip loading creojs.js — it cannot talk to a session.
        if (!hasBridge()) {
          done(false);
          return;
        }
        const script = document.createElement("script");
        script.src = "/creojs.js";
        script.onload = () => {
          tryInit();
          done(Boolean(window.CreoJS));
        };
        script.onerror = () => done(Boolean(window.CreoJS));
        document.head.appendChild(script);
      }, 50);
    });
  })());

  function userFacingError(message) {
    let text = String(message || "").replace(/^\s*Uncaught Error:\s*/i, "").trim();
    const detail = text.search(/\s+\d+\)\s*(SCRIPT|Object\.execute)/i);
    if (detail >= 0) text = text.slice(0, detail).trim();
    const newline = text.search(/\r?\n/);
    if (newline >= 0) text = text.slice(0, newline).trim();
    return text;
  }

  function showError(el, message) {
    if (!el) return;
    const text = userFacingError(message);
    el.hidden = !text;
    el.textContent = text;
  }

  function showOk(message) {
    showError($("#toolbar-error"), "");
    const el = $("#toolbar-ok");
    const row = $("#toolbar-ok-row");
    if (!el) return;
    const text = message || "";
    el.textContent = text;
    if (row) {
      row.hidden = !text;
    } else {
      el.hidden = !text;
    }
  }

  try {
    const storedNotice = sessionStorage.getItem("creopdmNotice");
    if (storedNotice) {
      sessionStorage.removeItem("creopdmNotice");
      showError($("#toolbar-error"), storedNotice);
    }
  } catch {
    /* private mode / blocked storage */
  }

  let busyDepth = 0;
  const heartbeat = { ids: [], timer: 0 };
  const busyOverlay = $("#busy-overlay");
  busyOverlay?.addEventListener("cancel", (event) => event.preventDefault());
  function showBusyOverlay() {
    if (!(busyOverlay instanceof HTMLDialogElement)) return;
    if (!busyOverlay.open) busyOverlay.showModal();
  }
  function hideBusyOverlay() {
    if (!(busyOverlay instanceof HTMLDialogElement)) return;
    if (busyOverlay.open) busyOverlay.close();
  }
  function setBusyMessage(message) {
    const text = $("#busy-message");
    if (text) text.textContent = message || "Working…";
  }
  function setBusy(message) {
    busyDepth += 1;
    setBusyMessage(message);
    showBusyOverlay();
    document.body.classList.add("is-busy");
    document.body.setAttribute("aria-busy", "true");
  }
  function clearBusy() {
    busyDepth = Math.max(0, busyDepth - 1);
    if (busyDepth > 0) return;
    hideBusyOverlay();
    document.body.classList.remove("is-busy");
    document.body.removeAttribute("aria-busy");
  }
  async function withBusy(message, work) {
    setBusy(message);
    try {
      return await work();
    } finally {
      clearBusy();
    }
  }

  function closeOpenDialogs({ keepBusy = false } = {}) {
    document.querySelectorAll("dialog[open]").forEach((dialog) => {
      if (keepBusy && dialog.id === "busy-overlay") return;
      try {
        dialog.close();
      } catch {
        /* ignore */
      }
    });
  }

  /** Same-origin pages that share base.html + main.shell — soft-nav keeps Creo.JS. */
  function isSoftNavUrl(url) {
    try {
      const parsed = new URL(url, window.location.href);
      if (parsed.origin !== window.location.origin) return false;
      const path = parsed.pathname || "/";
      if (path === "/" || path === "") return true;
      if (path === "/settings" || path === "/settings/types") return true;
      if (/^\/projects\/[^/]+\/objects\/[^/]+\/?$/.test(path)) return true;
      return false;
    } catch {
      return false;
    }
  }

  let softNavBusy = false;
  // Serialize soft navigations so a refresh after Remove is never dropped, and
  // callers can await the real shell swap (the old queue resolved too early).
  let softNavTail = Promise.resolve();

  function softNavigate(url, historyMode = "push") {
    const absolute = new URL(url, window.location.href);
    if (!isSoftNavUrl(absolute.href)) {
      window.location.href = absolute.href;
      return Promise.resolve();
    }
    const href = absolute.href;
    const mode = historyMode;
    const run = async () => {
      softNavBusy = true;
      window.__creopdmSoftNavBusy = true;
      try {
        const response = await fetch(href, {
          headers: { Accept: "text/html", "X-CreoPDM-Soft": "1" },
          credentials: "same-origin",
          // After remove/add the prior GET is often still in the HTTP cache; without
          // this, soft reload paints the deleted folder/file until a hard refresh.
          cache: "no-store",
        });
        if (!response.ok) {
          window.location.href = href;
          return;
        }
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, "text/html");
        const nextShell = doc.querySelector("main.shell");
        const curShell = document.querySelector("main.shell");
        if (!nextShell || !curShell) {
          window.location.href = href;
          return;
        }
        curShell.innerHTML = nextShell.innerHTML;
        if (doc.title) document.title = doc.title;
        const nextUrl = response.url || href;
        if (mode === "push") {
          history.pushState({ creopdmSoft: 1 }, "", nextUrl);
        } else if (mode === "replace") {
          history.replaceState({ creopdmSoft: 1 }, "", nextUrl);
        }
        // Keep the live Creo.JS bridge — rebind UI only.
        EventTarget.prototype.addEventListener = origAddEventListener;
        window.__creopdmBoot({ soft: true });
      } catch {
        window.location.href = href;
      } finally {
        softNavBusy = false;
        window.__creopdmSoftNavBusy = false;
      }
    };
    const done = softNavTail.then(run, run);
    softNavTail = done.catch(() => {});
    return done;
  }

  function leavePage(url) {
    closeOpenDialogs();
    // Always soft-nav shell pages — hard reload SSR-paints Not Connected and kills Creo.JS.
    if (isSoftNavUrl(url)) {
      void withBusy("Loading…", () => softNavigate(url, "push"));
      return;
    }
    window.location.href = url;
  }

  function reloadPage(options = {}) {
    const keepBusy = Boolean(options.keepBusy);
    const busyMessage = options.busyMessage || "Refreshing…";
    closeOpenDialogs({ keepBusy });
    // Keep the busy overlay up through navigation so the stale table is not shown.
    // Do not bump busyDepth — that would pause workspace-watch if navigation stalls.
    if (keepBusy) {
      setBusyMessage(busyMessage);
      showBusyOverlay();
      document.body.classList.add("is-busy");
      document.body.setAttribute("aria-busy", "true");
    }
    let pathname = window.location.pathname || "/";
    let hash = window.location.hash || "";
    const params = new URLSearchParams();
    try {
      const url = new URL(window.location.href);
      pathname = url.pathname || "/";
      hash = url.hash || "";
      url.searchParams.forEach((value, key) => {
        if (key !== "r") params.append(key, value);
      });
    } catch {
      /* keep defaults */
    }
    params.set("r", String(Date.now()));
    const query = params.toString();
    const next = `${pathname}${query ? `?${query}` : ""}${hash}`;
    // Soft-nav pages: fetch+swap (cache-busted, no-store) so Creo actually refreshes
    // and Creo.JS stays alive. Hard assign/form is often ignored there, which left a
    // stale Files table after Remove until the user hard-refreshed.
    if (isSoftNavUrl(next)) {
      return withBusy(busyMessage, () => softNavigate(next, "replace"));
    }
    // Non-shell pages: normal browsers assign; Creo needs a GET form submit.
    if (!inCreoBrowser()) {
      window.location.assign(next);
      return Promise.resolve();
    }
    const form = document.createElement("form");
    form.method = "GET";
    form.action = pathname;
    form.style.display = "none";
    params.forEach((value, key) => {
      const input = document.createElement("input");
      input.type = "hidden";
      input.name = key;
      input.value = value;
      form.appendChild(input);
    });
    document.body.appendChild(form);
    form.submit();
    return Promise.resolve();
  }

  function reloadPageAfterDialog() {
    // Submitting a navigation form from inside another form's submit handler
    // (Check In dialog) is ignored by Creo; checkout works because it is a button click.
    window.setTimeout(() => reloadPage({ keepBusy: true }), 50);
  }

  const BULK_SLOW_WARN_THRESHOLD = 100;

  function confirmLargeBulk(actionLabel, count) {
    if (count <= BULK_SLOW_WARN_THRESHOLD) return true;
    return window.confirm(
      `${actionLabel} ${count} files?\n\nThis can take several minutes. Keep this window open until it finishes.`
    );
  }

  function stopHeartbeats(clearIds) {
    const wanted = clearIds?.length ? new Set(clearIds.map(String)) : null;
    if (wanted) {
      heartbeat.ids = heartbeat.ids.filter((id) => !wanted.has(String(id)));
    } else {
      heartbeat.ids = [];
    }
    if (!heartbeat.ids.length && heartbeat.timer) {
      window.clearInterval(heartbeat.timer);
      heartbeat.timer = 0;
    }
  }

  function applyCheckedInResult(result) {
    /** Update rows immediately when Creo ignores post-check-in navigation. */
    const byId = new Map();
    if (Array.isArray(result?.ok)) {
      result.ok.forEach((item) => {
        if (item?.uuid) byId.set(String(item.uuid), item);
      });
    } else if (result?.uuid) {
      byId.set(String(result.uuid), result);
    }
    if (!byId.size) return;
    stopHeartbeats([...byId.keys()]);
    rows().forEach((row) => {
      const id = row.dataset.uuid;
      if (!id || !byId.has(id)) return;
      const item = byId.get(id);
      row.dataset.owned = "0";
      row.dataset.checkedOut = "0";
      row.dataset.canCheckin = "0";
      row.dataset.canCheckout = "1";
      if (item.filename) {
        row.dataset.filename = item.filename;
        const openBtn = row.querySelector(".object-open");
        if (openBtn) {
          openBtn.textContent = item.filename;
          openBtn.title = item.filename;
        }
      }
      if (item.display_revision) {
        const revTd = row.children[1];
        if (revTd) {
          revTd.textContent = item.display_revision;
          revTd.title = item.display_revision;
        }
      }
      const state = row.querySelector(".checkout-state");
      if (state) {
        const label = item.checkout_status || "Available";
        state.dataset.state = "available";
        state.textContent = label;
        const td = state.closest("td");
        if (td) td.title = label;
      }
    });
    try {
      syncToolbar();
      updateMetricCounts();
    } catch {
      /* metrics helpers may not be ready on detail-only pages */
    }
  }

  function applyCheckedOutOnRows(uuids, { label = "Checked out by me" } = {}) {
    /** Paint Checkout column immediately — Creo often ignores post-checkout reload in folders. */
    const ids = new Set(
      (uuids || []).map((id) => String(id || "").trim()).filter(Boolean)
    );
    if (!ids.size) return;
    const text = String(label || "Checked out by me");
    rows().forEach((row) => {
      const id = row.dataset.uuid;
      if (!id || !ids.has(id)) return;
      row.dataset.owned = "1";
      row.dataset.checkedOut = "1";
      row.dataset.canCheckin = "1";
      row.dataset.canCheckout = "0";
      const state = row.querySelector(".checkout-state");
      if (state) {
        state.dataset.state = "mine";
        state.textContent = text;
        const td = state.closest("td");
        if (td) td.title = text;
      }
      const tree = row.dataset.tree || "";
      if (row.dataset.sortCheckout != null) {
        row.dataset.sortCheckout = `${tree}/${text}`;
      }
    });
    document.querySelectorAll(".detail-meta .checkout-state").forEach((state) => {
      state.dataset.state = "mine";
      state.textContent = text;
    });
    try {
      syncToolbar();
      updateMetricCounts();
      reapplyActiveTableSorts();
    } catch {
      /* list helpers may not be ready on detail-only pages */
    }
  }

  function applyUndoCheckoutOnRows(uuids) {
    /** Paint Available immediately when reload is slow or ignored. */
    const ids = new Set(
      (uuids || []).map((id) => String(id || "").trim()).filter(Boolean)
    );
    if (!ids.size) return;
    stopHeartbeats([...ids]);
    const text = "Available";
    rows().forEach((row) => {
      const id = row.dataset.uuid;
      if (!id || !ids.has(id)) return;
      row.dataset.owned = "0";
      row.dataset.checkedOut = "0";
      row.dataset.canCheckin = "0";
      row.dataset.canCheckout = "1";
      row.dataset.modifiedLocally = "0";
      const state = row.querySelector(".checkout-state");
      if (state) {
        state.dataset.state = "available";
        state.textContent = text;
        const td = state.closest("td");
        if (td) td.title = text;
      }
      const tree = row.dataset.tree || "";
      if (row.dataset.sortCheckout != null) {
        row.dataset.sortCheckout = `${tree}/${text}`;
      }
    });
    document.querySelectorAll(".detail-meta .checkout-state").forEach((state) => {
      state.dataset.state = "available";
      state.textContent = text;
    });
    try {
      syncModifiedStateLabels();
      syncToolbar();
      updateMetricCounts();
      reapplyActiveTableSorts();
    } catch {
      /* list helpers may not be ready on detail-only pages */
    }
  }

  async function withHtmlDialogClosed(dialog, work) {
    const wasOpen = Boolean(dialog?.open);
    if (wasOpen) dialog.close();
    try {
      return await work();
    } finally {
      if (wasOpen && dialog && !dialog.open) dialog.showModal();
    }
  }

  async function readError(response) {
    try {
      const payload = await response.json();
      const err = payload?.error;
      if (err) {
        const extra = err.details?.user
          ? ` ${err.details.user} on ${err.details.machine || "unknown machine"} since ${err.details.since || "unknown"}.`
          : "";
        return `${err.message}${extra}`;
      }
      if (typeof payload?.detail === "string" && payload.detail.trim()) {
        return payload.detail.trim();
      }
      return response.statusText;
    } catch {
      return response.statusText;
    }
  }

  const FILTERS = {
    files: null,
    creo_parts: ["CREO_PART"],
    assemblies: ["CREO_ASSEMBLY"],
    drawings: ["CREO_DRAWING"],
    documents: ["PDF", "DOCUMENT", "SPREADSHEET", "TEXT", "IMAGE"],
    other: ["PDF", "DOCUMENT", "SPREADSHEET", "TEXT", "IMAGE", "OTHER"],
  };
  const CAD_MODEL_CHILD_FILTERS = new Set(["creo_parts", "assemblies", "drawings"]);
  const METRIC_LABELS = {
    files: "all files",
    cad_models: "Creo models",
    creo_parts: "parts",
    assemblies: "assemblies",
    drawings: "drawings",
    documents: "documents",
    other: "files that are not Creo models",
    checked_out: "checked out files",
  };

  function metricButtons() {
    return [...document.querySelectorAll(".metric")];
  }

  function metricKey(btn) {
    return String(btn?.getAttribute("data-filter") || btn?.dataset.filter || "").trim();
  }

  function metricMode(btn) {
    return String(btn?.getAttribute("data-mode") || btn?.dataset.mode || "off").trim() || "off";
  }

  function isParentMetric(key) {
    return key === "files" || key === "cad_models";
  }

  function clearMetricFilters(keys) {
    metricButtons().forEach((item) => {
      if (keys.has(metricKey(item)) && metricMode(item) !== "off") setMetricMode(item, "off");
    });
  }

  function cadModelsExtensions() {
    return listedExtensions("cadModels");
  }

  function documentExtensions() {
    return listedExtensions("documents");
  }

  function listedExtensions(datasetKey) {
    const root = document.querySelector("#metric-filters");
    const attr = String(datasetKey || "").replace(/[A-Z]/g, (ch) => `-${ch.toLowerCase()}`);
    const raw = root?.getAttribute(`data-${attr}`) || root?.dataset[datasetKey] || "";
    return raw.split(/[\s,;]+/).map((item) => {
      const ext = item.trim().toLowerCase();
      if (!ext) return "";
      return ext.startsWith(".") ? ext : `.${ext}`;
    }).filter(Boolean);
  }

  function rowAttr(row, name) {
    return String(row?.getAttribute(name) || "").trim();
  }

  function rowFilename(row) {
    const named = rowAttr(row, "data-filename") || rowAttr(row, "data-sort-name");
    if (named) return named.replace(/\\/g, "/").split("/").pop() || named;
    return row?.querySelector(".object-open")?.textContent || "";
  }

  function rowExtension(row) {
    const fromName = filenameExtension(rowFilename(row));
    if (fromName) return fromName;
    const ext = rowAttr(row, "data-extension").toLowerCase();
    if (!ext || /^\.\d+$/.test(ext.startsWith(".") ? ext : `.${ext}`)) return "";
    return ext.startsWith(".") ? ext : `.${ext}`;
  }

  function rowObjectType(row) {
    return rowAttr(row, "data-object-type").toUpperCase();
  }

  function rowMatchesMetric(row, key) {
    if (key === "checked_out") {
      return rowAttr(row, "data-checked-out") === "1" || row.dataset.checkedOut === "1";
    }
    if (key === "cad_models") return cadModelsExtensions().includes(rowExtension(row));
    if (key === "documents") return documentExtensions().includes(rowExtension(row));
    if (key === "other") return !cadModelsExtensions().includes(rowExtension(row));
    const types = FILTERS[key];
    if (types === null) return true;
    if (!types) return false;
    return types.includes(rowObjectType(row));
  }

  function rememberMetricCounts() {
    metricButtons().forEach((btn) => {
      const strong = btn.querySelector("strong");
      if (!strong || btn.dataset.folderCount != null) return;
      btn.dataset.folderCount = strong.textContent.trim();
    });
  }

  function activeListTab() {
    return document.querySelector(".tabs .tab.is-active")?.getAttribute("data-tab") || "files";
  }

  function fileListRoot() {
    const tab = activeListTab();
    if (tab === "changes") {
      return document.getElementById("changes-table")
        || document.getElementById("panel-changes")
        || document;
    }
    if (tab === "checked-out") {
      return document.getElementById("checked-out-table")
        || document.getElementById("panel-checked-out")
        || document;
    }
    return document.getElementById("object-table")
      || document.getElementById("panel-files")
      || document;
  }

  function rows() {
    return [...fileListRoot().querySelectorAll(".object-row, .folder-row, .queue-row")];
  }

  function markRowSelected(row, on) {
    if (on) {
      row.classList.add("is-selected");
      row.setAttribute("data-selected", "1");
    } else {
      row.classList.remove("is-selected");
      row.removeAttribute("data-selected");
    }
  }

  function filenameExtension(filename) {
    const name = String(filename || "").toLowerCase();
    const match = name.match(/(\.[a-z0-9_+]+)(?:\.\d+)?$/i);
    return match ? match[1] : "";
  }

  function typeFromExtension(ext) {
    const key = String(ext || "").toLowerCase();
    if (key === ".prt") return "CREO_PART";
    if (key === ".asm") return "CREO_ASSEMBLY";
    if (key === ".drw") return "CREO_DRAWING";
    if (key === ".mfg") return "CREO_MANUFACTURING";
    if (key === ".pdf") return "PDF";
    if ([".doc", ".docx", ".odt", ".rtf", ".txt", ".md"].includes(key)) return "DOCUMENT";
    if ([".xls", ".xlsx", ".xlsm", ".csv"].includes(key)) return "SPREADSHEET";
    if ([".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".svg"].includes(key)) return "IMAGE";
    if ([".log", ".xml", ".ncl", ".lst"].includes(key)) return "TEXT";
    return "CAD";
  }

  function listedMetricRows() {
    const root = fileListRoot();
    if (!root) return [];
    if (root.id === "panel-changes" || root.id === "changes-table") {
      return [...root.querySelectorAll(".queue-row")];
    }
    return [...root.querySelectorAll(".object-row")];
  }

  function updateMetricCounts() {
    rememberMetricCounts();
    const root = fileListRoot();
    const filesTab = !root || root.id === "panel-files" || root.id === "object-table";
    const searching = $("#object-table")?.dataset.searching === "1";
    if (filesTab && !searching) {
      metricButtons().forEach((btn) => {
        const strong = btn.querySelector("strong");
        if (strong) strong.textContent = btn.dataset.folderCount || "0";
      });
      return;
    }
    const files = listedMetricRows();
    metricButtons().forEach((btn) => {
      const strong = btn.querySelector("strong");
      if (!strong) return;
      const key = metricKey(btn);
      const count = key === "files"
        ? files.length
        : files.filter((row) => rowMatchesMetric(row, key)).length;
      strong.textContent = String(count);
    });
  }

  function refreshTabMetrics() {
    applyMetricVisibility();
    applyMetricSelection();
    updateMetricCounts();
    syncToolbar();
  }

  function setMetricMode(btn, mode) {
    btn.dataset.mode = mode;
    btn.setAttribute("data-mode", mode);
    // Use add/remove — Creo's embedded browser mishandles classList.toggle(name, force).
    if (mode === "select") {
      // Legacy stored mode — treat like filter visually until migrated.
      btn.classList.remove("is-selected");
      btn.classList.add("is-filtered");
    } else if (mode === "filter") {
      btn.classList.remove("is-selected");
      btn.classList.add("is-filtered");
    } else {
      btn.classList.remove("is-selected");
      btn.classList.remove("is-filtered");
    }
    const key = metricKey(btn);
    const label = METRIC_LABELS[key] || key;
    if (key === "files") {
      btn.title = mode === "off"
        ? "Show and select all files. Clears type chips. Click again to clear."
        : "Showing all files (selected). Click to clear.";
      return;
    }
    if (key === "checked_out") {
      btn.title = mode === "off"
        ? "Filter to checked out files in the current group and select them. Click again to clear."
        : "Showing checked out files (selected). Click to clear.";
      return;
    }
    btn.title = mode === "off"
      ? `Filter to ${label} and select them. Click again to clear.`
      : `Filtering to ${label} (selected). Click to clear.`;
  }

  function isCheckoutMetric(key) {
    return key === "checked_out";
  }

  function setRowHidden(row, hide) {
    row.classList.toggle("is-row-hidden", hide);
    if (hide) row.setAttribute("hidden", "");
    else row.removeAttribute("hidden");
  }

  function rowIsHidden(row) {
    return row.classList.contains("is-row-hidden");
  }

  function applyMetricVisibility() {
    const metrics = metricButtons();
    const typeFilterBtns = metrics.filter((btn) => {
      return !isCheckoutMetric(metricKey(btn)) && metricMode(btn) === "filter";
    });
    const checkoutFiltering = metrics.some((btn) => {
      return isCheckoutMetric(metricKey(btn)) && metricMode(btn) === "filter";
    });
    const typeRestricts = typeFilterBtns.length > 0 || checkoutFiltering;
    const viewBtns = metrics.filter((btn) => {
      const key = metricKey(btn);
      if (isCheckoutMetric(key)) return false;
      const mode = metricMode(btn);
      if (mode === "off" || !typeRestricts) return false;
      if (mode === "select" && isParentMetric(key) && typeFilterBtns.length) return false;
      return true;
    });
    const q = ($("#search-input")?.value || "").trim().toLowerCase();
    const searchingAll = $("#object-table")?.dataset.searching === "1";
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        const matchesSearch = searchingAll ? false : (!q || row.textContent.toLowerCase().includes(q));
        setRowHidden(row, Boolean(q) && !matchesSearch);
        return;
      }
      const matchesSearch = searchingAll || !q || row.textContent.toLowerCase().includes(q);
      const matchesView = !viewBtns.length || viewBtns.some((btn) => rowMatchesMetric(row, metricKey(btn)));
      const matchesCheckout = !checkoutFiltering || rowMatchesMetric(row, "checked_out");
      setRowHidden(row, !(matchesSearch && matchesView && matchesCheckout));
    });
  }

  function applyMetricSelection() {
    // Select and filter both keep matching rows selected (sticky while the pill is on).
    const selecting = metricButtons().filter((btn) => {
      const mode = metricMode(btn);
      return mode === "select" || mode === "filter";
    });
    if (!selecting.length) return;
    const typeActive = selecting.filter((btn) => !isCheckoutMetric(metricKey(btn)));
    const checkoutOn = selecting.some((btn) => isCheckoutMetric(metricKey(btn)));
    rows().forEach((row) => {
      // Folder rows are selected by click for Remove — do not clear them here.
      if (row.classList.contains("folder-row")) return;
      const matchesType = !typeActive.length || typeActive.some((btn) => rowMatchesMetric(row, metricKey(btn)));
      const matchesCheckout = !checkoutOn || rowMatchesMetric(row, "checked_out");
      markRowSelected(row, matchesType && matchesCheckout && !rowIsHidden(row));
    });
  }

  function metricSelectionActive() {
    return metricButtons().some((btn) => {
      const mode = metricMode(btn);
      return mode === "select" || mode === "filter";
    });
  }

  const projectDialog = $("#project-dialog");
  const projectForm = $("#project-form");
  const addDialog = $("#add-dialog");
  const addForm = $("#add-form");
  const checkinDialog = $("#checkin-dialog");
  const checkinForm = $("#checkin-form");
  const settingsForm = $("#settings-form");

  const workspaceEl = document.querySelector(".workspace");
  const projectSidebar = document.querySelector(".sidebar");
  const projectMenuBtn = $("#project-menu-btn");
  const sidebarCollapseBtn = $("#sidebar-collapse-btn");
  function closeProjectMenu() {
    projectSidebar?.classList.remove("is-open");
    projectMenuBtn?.setAttribute("aria-expanded", "false");
  }
  function sidebarCollapsed() {
    return Boolean(workspaceEl?.classList.contains("is-sidebar-collapsed"));
  }
  function syncSidebarCollapse() {
    const collapsed = sidebarCollapsed();
    const label = collapsed ? "Show project list" : "Collapse project list";
    if (!sidebarCollapseBtn) return;
    sidebarCollapseBtn.title = label;
    sidebarCollapseBtn.setAttribute("aria-label", label);
    sidebarCollapseBtn.setAttribute("aria-pressed", collapsed ? "true" : "false");
  }
  function rememberSidebarCollapse(collapsed) {
    document.cookie = "creopdm_sidebar=" + (collapsed ? "1" : "0")
      + "; Path=/; Max-Age=31536000; SameSite=Lax";
  }
  sidebarCollapseBtn?.addEventListener("click", (event) => {
    event.stopPropagation();
    workspaceEl?.classList.toggle("is-sidebar-collapsed");
    closeProjectMenu();
    syncSidebarCollapse();
    rememberSidebarCollapse(sidebarCollapsed());
  });
  function toggleProjectMenu(event) {
    event.stopPropagation();
    const open = projectSidebar?.classList.toggle("is-open");
    projectMenuBtn?.setAttribute("aria-expanded", open ? "true" : "false");
  }
  projectMenuBtn?.addEventListener("click", toggleProjectMenu);
  document.addEventListener("click", (event) => {
    if (!projectSidebar?.classList.contains("is-open")) return;
    if (projectSidebar.contains(event.target)) return;
    closeProjectMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProjectMenu();
  });

  $("#new-project-btn")?.addEventListener("click", () => {
    closeProjectMenu();
    showProjectDialog("create");
  });
  const projectSettings = $("#project-settings");
  const projectSettingsBtn = $("#project-settings-btn");
  const projectSettingsMenu = $("#project-settings-menu");
  function closeProjectSettings() {
    projectSettings?.classList.remove("is-open");
    if (projectSettingsMenu) projectSettingsMenu.hidden = true;
    projectSettingsBtn?.setAttribute("aria-expanded", "false");
  }
  function toggleProjectSettings(event) {
    event.stopPropagation();
    const open = !projectSettings?.classList.contains("is-open");
    if (open) {
      projectSettings?.classList.add("is-open");
      if (projectSettingsMenu) projectSettingsMenu.hidden = false;
      projectSettingsBtn?.setAttribute("aria-expanded", "true");
    } else {
      closeProjectSettings();
    }
  }
  projectSettingsBtn?.addEventListener("click", toggleProjectSettings);
  document.addEventListener("click", (event) => {
    if (!projectSettings?.classList.contains("is-open")) return;
    if (projectSettings.contains(event.target)) return;
    closeProjectSettings();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProjectSettings();
  });
  $("#rename-project-btn")?.addEventListener("click", () => {
    closeProjectSettings();
    showProjectDialog("rename");
  });
  $("#rebuild-where-used-btn")?.addEventListener("click", async () => {
    closeProjectSettings();
    const projectId = $("#rebuild-where-used-btn")?.dataset.project || currentProjectId();
    if (!projectId) return;
    showError($("#toolbar-error"), "");
    const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/rebuild-where-used`, {
      method: "POST",
    });
    if (!response.ok) {
      showError($("#toolbar-error"), await readError(response));
      return;
    }
    showOk("Where Used indexing started in the background.");
    watchWhereUsedIndex(projectId);
  });

  function watchWhereUsedIndex(projectId) {
    if (!projectId) return;
    let tries = 0;
    const tick = async () => {
      tries += 1;
      try {
        const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/rebuild-where-used`);
        if (!response.ok) return;
        const body = await response.json();
        const state = String(body.state || "");
        if (state === "queued" || state === "running") {
          const total = Number(body.parents_total) || 0;
          const doneCount = Number(body.parents_done) || 0;
          if (total > 0) {
            showOk(`Indexing Where Used in background… ${doneCount} of ${total} assemblies/drawings`);
          }
          if (tries < 600) window.setTimeout(tick, 2000);
          return;
        }
        if (state === "done") {
          const added = Number(body.edges_added) || 0;
          const existing = Number(body.edges_existing) || 0;
          const miss = Number(body.parents_missing_vault) || 0;
          const missMsg = miss ? ` ${miss} parent file(s) missing from vault.` : "";
          showOk(`Where Used index ready: ${added} new link(s), ${existing} already stored.${missMsg}`);
          return;
        }
        if (state === "error") {
          showError($("#toolbar-error"), body.error || "Where Used indexing failed.");
        }
      } catch {
        /* ignore transient poll errors */
      }
    };
    window.setTimeout(tick, 800);
  }

  async function resumeWhereUsedIndexWatch() {
    const projectId = currentProjectId();
    if (!projectId) return;
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/rebuild-where-used`);
      if (!response.ok) return;
      const body = await response.json();
      const state = String(body.state || "");
      if (state === "queued" || state === "running") {
        watchWhereUsedIndex(projectId);
      }
    } catch {
      /* ignore */
    }
  }

  resumeWhereUsedIndexWatch();

  const METADATA_COLLECT_WARN_THRESHOLD = 50;
  const METADATA_COLLECT_KEY = "creopdmMetadataCollect";
  const metadataCollectJob = { running: false, cancel: false };
  const cancelMetadataBtn = $("#cancel-metadata-collect-btn");
  const resumeMetadataBtn = $("#resume-metadata-collect-btn");

  function setMetadataCollectControls({ cancel = false, resume = false } = {}) {
    if (cancelMetadataBtn) cancelMetadataBtn.hidden = !cancel;
    if (resumeMetadataBtn) resumeMetadataBtn.hidden = !resume;
  }

  function syncMetadataCollectControls() {
    const stored = loadMetadataCollectState();
    if (!stored || stored.status !== "running") {
      setMetadataCollectControls({ cancel: false, resume: false });
      return;
    }
    if (metadataCollectJob.running) {
      setMetadataCollectControls({ cancel: true, resume: false });
    } else {
      setMetadataCollectControls({ cancel: true, resume: true });
    }
  }

  function saveMetadataCollectState(state) {
    try {
      if (!state) sessionStorage.removeItem(METADATA_COLLECT_KEY);
      else sessionStorage.setItem(METADATA_COLLECT_KEY, JSON.stringify(state));
    } catch {
      /* private mode / quota */
    }
    syncMetadataCollectControls();
  }

  function loadMetadataCollectState() {
    try {
      const raw = sessionStorage.getItem(METADATA_COLLECT_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== "object") return null;
      return parsed;
    } catch {
      return null;
    }
  }

  cancelMetadataBtn?.addEventListener("click", () => {
    const stored = loadMetadataCollectState();
    if (metadataCollectJob.running) {
      metadataCollectJob.cancel = true;
      showOk("Cancelling metadata collection…");
      return;
    }
    if (stored && stored.status === "running") {
      saveMetadataCollectState(null);
      showOk("Metadata collection cancelled.");
    }
  });

  resumeMetadataBtn?.addEventListener("click", () => {
    if (metadataCollectJob.running) return;
    void resumeMetadataCollectIfNeeded({ fromButton: true });
  });

  function confirmCollectMetadata(total) {
    const dialog = $("#collect-metadata-dialog");
    const form = $("#collect-metadata-form");
    const lead = $("#collect-metadata-lead");
    const warn = $("#collect-metadata-warn");
    if (!(dialog instanceof HTMLDialogElement) || !form || !lead) {
      return Promise.resolve(window.confirm(`Collect Creo metadata for ${total} model(s)?`));
    }
    lead.textContent =
      `Capture parameters, materials, units, features, and BOM/structure for ${total} Creo model(s) in this project. ` +
      "Each model is retrieved in the Creo session when needed. Mass properties are not collected (unsupported in silent Collect).";
    if (warn) {
      if (total > METADATA_COLLECT_WARN_THRESHOLD) {
        warn.hidden = false;
        warn.textContent =
          `This is ${total} models (over ${METADATA_COLLECT_WARN_THRESHOLD}). It can take a long time and may make Creo sluggish. Cancel or Resume from the toolbar. Progress survives navigation within CreoPDM.`;
      } else {
        warn.hidden = true;
        warn.textContent = "";
      }
    }
    return new Promise((resolve) => {
      const onCancel = () => {
        cleanup();
        dialog.close();
        resolve(false);
      };
      const onSubmit = (event) => {
        event.preventDefault();
        cleanup();
        dialog.close();
        resolve(true);
      };
      function cleanup() {
        form.removeEventListener("submit", onSubmit);
        $("#collect-metadata-cancel")?.removeEventListener("click", onCancel);
      }
      form.addEventListener("submit", onSubmit);
      $("#collect-metadata-cancel")?.addEventListener("click", onCancel);
      if (!dialog.open) dialog.showModal();
    });
  }

  async function pushOneCreoMetadataTarget(target) {
    const METADATA_ITEM_TIMEOUT_MS = 90000;
    let settled = false;
    const work = async () => {
      let snapshot = await gatherCreoMetadataForFilename(target.filename, "");
      let reason = "";
      if (snapshot && snapshot.__error) {
        reason = snapshot.__error;
        snapshot = null;
      }
      if (!snapshot) {
        let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
        if (!filePath) {
          filePath = (await prepareLocalPathForMetadata(target.uuid)) || "";
        }
        if (!filePath) {
          return { ok: false, timedOut: false, reason: reason || "materialize_failed" };
        }
        snapshot = await gatherCreoMetadataForFilename(target.filename, filePath);
        if (snapshot && snapshot.__error) {
          return {
            ok: false,
            timedOut: false,
            reason: String(snapshot.__error),
            detail: String(snapshot.__detail || ""),
          };
        }
      }
      if (!snapshot) return { ok: false, timedOut: false, reason: reason || "gather_failed" };
      // Require a real identity filename so empty/failed snapshots are never "saved".
      const identityName = String(snapshot.identity?.file_name || snapshot.identity?.full_name || "").trim();
      if (!identityName) {
        return { ok: false, timedOut: false, reason: "empty_identity" };
      }
      const body = {
        version_id: target.versionId || null,
        identity: snapshot.identity || null,
        parameters: Array.isArray(snapshot.parameters) ? snapshot.parameters : [],
        materials: snapshot.materials || null,
        dependencies: Array.isArray(snapshot.dependencies) ? snapshot.dependencies : [],
        bom: snapshot.bom || null,
        units: snapshot.units || null,
        // Mass unsupported in silent Collect — omit so existing mass_json is preserved.
        family_table: snapshot.family_table || null,
        features: Array.isArray(snapshot.features) && snapshot.features.length
          ? snapshot.features
          : null,
      };
      try {
        const response = await fetch(`/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        return {
          ok: response.ok,
          timedOut: false,
          reason: response.ok ? "" : "post_failed",
        };
      } catch {
        return { ok: false, timedOut: false, reason: "post_failed" };
      }
    };
    try {
      const result = await Promise.race([
        work().then((value) => {
          settled = true;
          return value;
        }),
        new Promise((resolve) => {
          window.setTimeout(() => {
            if (!settled) resolve({ ok: false, timedOut: true, reason: "timeout" });
          }, METADATA_ITEM_TIMEOUT_MS);
        }),
      ]);
      return result;
    } catch {
      return { ok: false, timedOut: false, reason: "exception" };
    }
  }

  async function runMetadataCollectLoop(state) {
    if (metadataCollectJob.running) return;
    const targets = Array.isArray(state.targets) ? state.targets : [];
    if (!targets.length) {
      saveMetadataCollectState(null);
      return;
    }
    metadataCollectJob.running = true;
    metadataCollectJob.cancel = false;
    syncMetadataCollectControls();
    showError($("#toolbar-error"), "");
    let index = Math.max(0, Number(state.index) || 0);
    let captured = Number(state.captured) || 0;
    let failed = Number(state.failed) || 0;
    let lastReason = "";
    try {
      while (index < targets.length) {
        if (metadataCollectJob.cancel) break;
        const target = targets[index];
        const message =
          `Collecting Creo metadata… ${index + 1} of ${targets.length}: ${target.filename}` +
          ` (${captured} saved, ${failed} skipped` +
          (lastReason ? `, last: ${lastReason}` : "") +
          `)`;
        showOk(message);
        saveMetadataCollectState({
          ...state,
          status: "running",
          index,
          captured,
          failed,
          message,
          lastReason,
          updatedAt: Date.now(),
        });
        const result = await pushOneCreoMetadataTarget(target);
        if (result.timedOut) {
          failed += 1;
          lastReason = "timeout";
          index += 1;
          const waitSec = 8;
          const pauseMsg =
            `Creo busy / timeout on ${target.filename} — waiting ${waitSec}s then continuing ` +
            `(${index} of ${targets.length}; ${captured} saved, ${failed} skipped).`;
          showOk(pauseMsg);
          saveMetadataCollectState({
            ...state,
            status: "running",
            index,
            captured,
            failed,
            message: pauseMsg,
            lastReason,
            updatedAt: Date.now(),
          });
          // Let Creo recover; Cancel still works during the wait.
          for (let w = 0; w < waitSec * 4 && !metadataCollectJob.cancel; w += 1) {
            await new Promise((resolve) => window.setTimeout(resolve, 250));
          }
          continue;
        }
        if (result.ok) {
          captured += 1;
          // Keep mass/units/feature gap hints on success so we can watch Collect.
          lastReason = String(result.reason || "");
        } else {
          failed += 1;
          lastReason = String(result.reason || "skipped");
        }
        index += 1;
        saveMetadataCollectState({
          ...state,
          status: "running",
          index,
          captured,
          failed,
          lastReason,
          message:
            `Collecting Creo metadata… ${index} of ${targets.length}` +
            ` (${captured} saved, ${failed} skipped` +
            (lastReason ? `, last: ${lastReason}` : "") +
            `)`,
          updatedAt: Date.now(),
        });
        await new Promise((resolve) => window.setTimeout(resolve, 0));
      }
      if (typeof window.CreoJS?.eraseUndisplayedModelsQuiet === "function") {
        try {
          await window.CreoJS.eraseUndisplayedModelsQuiet();
        } catch {
          /* final sweep is best-effort */
        }
      }
      if (metadataCollectJob.cancel) {
        const msg =
          `Metadata collection cancelled after ${captured + failed} of ${targets.length} ` +
          `(${captured} saved, ${failed} skipped).`;
        showOk(msg);
        saveMetadataCollectState(null);
      } else {
        const msg =
          `Metadata collection finished: ${captured} saved` +
          (failed ? `, ${failed} skipped` : "") +
          `.`;
        showOk(msg);
        saveMetadataCollectState(null);
      }
    } finally {
      metadataCollectJob.running = false;
      metadataCollectJob.cancel = false;
      syncMetadataCollectControls();
    }
  }

  async function runCollectAllMetadata(projectId) {
    if (metadataCollectJob.running) {
      showOk("Metadata collection is already running.");
      return;
    }
    // Bridge often arrives after first paint — same wait as Resume.
    showOk("Waiting for Creo.JS…");
    const ready = await waitForCreoMetadataBridge();
    if (!ready) {
      showError(
        $("#toolbar-error"),
        "Collect metadata needs Creo’s embedded browser with Creo.JS available."
      );
      return;
    }
    showOk("");
    const existing = loadMetadataCollectState();
    if (
      existing &&
      existing.status === "running" &&
      existing.projectId === projectId &&
      Array.isArray(existing.targets) &&
      existing.targets.length
    ) {
      await runMetadataCollectLoop(existing);
      return;
    }
    const rows = await ensureProjectObjects(projectId, { force: true });
    const targets = (Array.isArray(rows) ? rows : [])
      .map((row) => ({
        uuid: String(row.uuid || "").trim(),
        filename: String(row.filename || "").trim(),
        path: "",
        versionId: String(row.current_version?.uuid || row.version_id || "").trim(),
      }))
      .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename));
    if (!targets.length) {
      showOk("No Creo parts, assemblies, or drawings to capture.");
      return;
    }
    const okToStart = await confirmCollectMetadata(targets.length);
    if (!okToStart) return;

    const state = {
      projectId,
      status: "running",
      index: 0,
      captured: 0,
      failed: 0,
      targets,
      message: `Collecting Creo metadata… 0 of ${targets.length}`,
      updatedAt: Date.now(),
    };
    saveMetadataCollectState(state);
    await runMetadataCollectLoop(state);
  }

  async function resumeMetadataCollectIfNeeded(opts = {}) {
    const fromButton = Boolean(opts && opts.fromButton);
    const state = loadMetadataCollectState();
    if (!state || state.status !== "running") return;
    if (!Array.isArray(state.targets) || !state.targets.length) {
      saveMetadataCollectState(null);
      return;
    }
    if (metadataCollectJob.running) {
      if (state.message) showOk(state.message);
      syncMetadataCollectControls();
      return;
    }
    const projectId = currentProjectId();
    if (projectId && state.projectId && projectId !== state.projectId) {
      showOk(
        `Metadata collection paused for another project (${state.index || 0} of ${state.targets.length}).`
      );
      syncMetadataCollectControls();
      return;
    }
    if (state.message) showOk(state.message);
    syncMetadataCollectControls();
    // Bridge often appears after first paint (same race as the status pill).
    if (!(await waitForCreoMetadataBridge())) {
      showOk(
        `Metadata collection paused at ${state.index || 0} of ${state.targets.length}. ` +
          (fromButton
            ? "Creo.JS still unavailable — open CreoPDM inside Creo, then click Resume."
            : "Click Resume when Creo.JS is connected, or re-open CreoPDM inside Creo.")
      );
      syncMetadataCollectControls();
      return;
    }
    await runMetadataCollectLoop(state);
  }

  $("#collect-metadata-btn")?.addEventListener("click", async () => {
    closeProjectSettings();
    const projectId = $("#collect-metadata-btn")?.dataset.project || currentProjectId();
    if (!projectId) return;
    await runCollectAllMetadata(projectId);
  });

  resumeMetadataCollectIfNeeded();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) resumeMetadataCollectIfNeeded();
  });
  window.addEventListener("pageshow", () => {
    resumeMetadataCollectIfNeeded();
  });

  $("#project-cancel")?.addEventListener("click", () => projectDialog?.close());

  const deleteProjectDialog = $("#delete-project-dialog");
  const deleteProjectForm = $("#delete-project-form");
  $("#delete-project-btn")?.addEventListener("click", () => {
    closeProjectSettings();
    const btn = $("#delete-project-btn");
    showError($("#delete-project-error"), "");
    if (deleteProjectForm) deleteProjectForm.reset();
    const deleteLocal = $("#delete-local-workspace");
    if (deleteLocal) deleteLocal.checked = true;
    deleteProjectDialog?.showModal();
  });
  $("#delete-project-cancel")?.addEventListener("click", () => deleteProjectDialog?.close());
  deleteProjectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("#delete-project-btn");
    const projectId = btn?.dataset.project;
    const expected = (btn?.dataset.name || "").trim();
    if (!projectId) return;
    const formData = new FormData(deleteProjectForm);
    const typed = String(formData.get("confirm_name") || "").trim();
    if (typed !== expected) {
      showError($("#delete-project-error"), "Type the project name exactly to delete it.");
      return;
    }
    const deleteLocal = Boolean($("#delete-local-workspace")?.checked);
    const vaultFolder = currentVaultFolder();
    let result;
    try {
      result = await withBusy("Deleting project…", async () => {
        const notices = [];
        if (deleteLocal) {
          const agent = await probeCreoAgent();
          if (!agent) {
            notices.push(
              "creopdm-agent is not running — local workspace on this PC was not deleted."
            );
          } else {
            try {
              const localResponse = await fetch(`${agentBase()}/delete-project-cache`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  project_id: projectId,
                  vault_folder: vaultFolder,
                }),
              });
              if (!localResponse.ok) {
                notices.push(await readError(localResponse));
              }
            } catch (exc) {
              notices.push(
                exc?.message ||
                  "Could not reach creopdm-agent to delete the local workspace."
              );
            }
          }
        }
        const forgetResponse = await fetch(`/api/projects/${projectId}/forget`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm_name: typed }),
        });
        if (!forgetResponse.ok) {
          throw new Error(await readError(forgetResponse));
        }
        const body = await forgetResponse.json().catch(() => ({}));
        if (body.warning) notices.push(String(body.warning));
        body.warning = notices.filter(Boolean).join(" ");
        return body;
      });
    } catch (exc) {
      showError(
        $("#delete-project-error"),
        exc?.message || "Could not delete the project."
      );
      return;
    }
    if (result?.warning) sessionStorage.setItem("creopdmNotice", result.warning);
    clearProjectViewStorage(projectId);
    leavePage("/");
  });

  function showProjectDialog(mode) {
    if (!projectForm || !projectDialog) return;
    showError($("#project-error"), "");
    const title = $("#project-dialog-title");
    const submit = $("#project-submit");
    const vaultFields = $("#project-vault-fields");
    projectForm.dataset.mode = mode;
    if (mode === "rename") {
      const btn = $("#rename-project-btn");
      if (title) title.textContent = "Rename project";
      projectForm.elements.name.value = btn?.dataset.name || "";
      projectForm.elements.number.value = btn?.dataset.number || "";
      projectForm.elements.description.value = btn?.dataset.description || "";
      if (vaultFields) vaultFields.hidden = true;
      if (submit) submit.textContent = "Save";
    } else {
      projectForm.reset();
      if (title) title.textContent = "New project";
      if (submit) submit.textContent = "Create";
      if (vaultFields) vaultFields.hidden = false;
      projectVaultCustom = "";
      projectVaultCustomTouched = false;
      projectVaultHash = "";
      const useHash = $("#project-use-hash");
      if (useHash) useHash.checked = true;
      syncProjectVaultFolderField(true);
    }
    projectDialog.showModal();
  }

  let projectVaultHash = "";
  let projectVaultCustom = "";
  let projectVaultCustomTouched = false;

  function newProjectVaultHash() {
    // Prefer platform UUID; CEF often lacks randomUUID but has getRandomValues.
    if (window.crypto?.randomUUID) return window.crypto.randomUUID();
    if (window.crypto?.getRandomValues) {
      const bytes = new Uint8Array(16);
      window.crypto.getRandomValues(bytes);
      bytes[6] = (bytes[6] & 0x0f) | 0x40;
      bytes[8] = (bytes[8] & 0x3f) | 0x80;
      const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
    }
    // Last resort: still UUID-shaped (not proj-…).
    let hex = "";
    for (let i = 0; i < 32; i += 1) hex += Math.floor(Math.random() * 16).toString(16);
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20)}`;
  }

  function slugifyVaultFolder(name) {
    const slug = String(name || "")
      .trim()
      .toLowerCase()
      .replace(/\s+/g, "-")
      .replace(/[^a-z0-9._-]+/g, "-")
      .replace(/-+/g, "-")
      .replace(/^[-.]+|[-.]+$/g, "");
    return slug.slice(0, 200);
  }

  function fillVaultFolderFromName() {
    const input = $("#project-vault-folder");
    const useHash = $("#project-use-hash");
    if (!input || useHash?.checked || projectVaultCustomTouched) return;
    const slug = slugifyVaultFolder(projectForm?.elements?.name?.value || "");
    input.value = slug;
    projectVaultCustom = slug;
  }

  function syncProjectVaultFolderField(resetHash) {
    const input = $("#project-vault-folder");
    const useHash = $("#project-use-hash");
    if (!input || !useHash) return;
    if (resetHash || !projectVaultHash) projectVaultHash = newProjectVaultHash();
    if (useHash.checked) {
      input.value = projectVaultHash;
      input.disabled = true;
      input.readOnly = true;
    } else {
      input.disabled = false;
      input.readOnly = false;
      if (!projectVaultCustomTouched) {
        fillVaultFolderFromName();
      } else {
        input.value = projectVaultCustom || "";
      }
    }
  }

  $("#project-use-hash")?.addEventListener("change", () => {
    const useHash = $("#project-use-hash");
    if (useHash?.checked) {
      projectVaultCustomTouched = false;
      syncProjectVaultFolderField(true);
    } else {
      syncProjectVaultFolderField(false);
      $("#project-vault-folder")?.focus();
      $("#project-vault-folder")?.select();
    }
  });

  projectForm?.elements?.name?.addEventListener("input", () => {
    fillVaultFolderFromName();
  });

  $("#project-vault-folder")?.addEventListener("input", () => {
    const useHash = $("#project-use-hash");
    if (useHash?.checked) return;
    projectVaultCustomTouched = true;
    projectVaultCustom = String($("#project-vault-folder")?.value || "").trim();
  });

  projectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(projectForm);
    const renaming = projectForm.dataset.mode === "rename";
    const body = {
      name: String(data.get("name") || "").trim(),
      number: String(data.get("number") || "").trim() || null,
      description: String(data.get("description") || "").trim() || null,
    };
    if (!renaming) {
      const useHash = Boolean($("#project-use-hash")?.checked);
      let vaultFolder = String(data.get("vault_folder") || "").trim();
      if (useHash) {
        body.vault_folder = projectVaultHash || newProjectVaultHash();
      } else {
        // Custom vault name must be provided (not blank).
        if (!vaultFolder) {
          showError($("#project-error"), "Enter a vault/workspace name, or check Use hash.");
          $("#project-vault-folder")?.focus();
          return;
        }
        if (/\s/.test(vaultFolder)) {
          showError($("#project-error"), "Vault/workspace name cannot contain spaces.");
          return;
        }
        body.vault_folder = vaultFolder;
      }
    }
    if (!body.name) {
      showError($("#project-error"), "A project name is required.");
      return;
    }
    const projectId = $("#rename-project-btn")?.dataset.project;
    const url = renaming ? `/api/projects/${projectId}` : "/api/projects";
    const response = await withBusy(renaming ? "Saving project…" : "Creating project…", () =>
      fetch(url, {
        method: renaming ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    );
    if (!response.ok) {
      showError($("#project-error"), await readError(response));
      return;
    }
    const project = await response.json();
    leavePage(`/?project=${encodeURIComponent(project.uuid)}`);
  });

  let chosenPaths = [];
  let chosenBaseFolder = null;
  let chosenFolders = [];
  let chosenUploads = [];
  let chosenAgentPaths = [];
  let chosenAgentBaseFolder = null;
  let chosenAgentFolderBatches = [];
  let importIgnorePatterns = [];
  let importExtensions = [];
  let addInitialDirectory = "";
  const UPLOAD_CHUNK = 400;

  function addMode() {
    return String(addForm?.dataset.addMode || "files").trim() || "files";
  }

  function isFolderAddMode() {
    const mode = addMode();
    return mode === "folders" || mode === "folder";
  }

  function isRecursiveAddMode() {
    return addMode() !== "folder";
  }

  function clearAddSelection() {
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenFolders = [];
    chosenUploads = [];
    chosenAgentPaths = [];
    chosenAgentBaseFolder = null;
    chosenAgentFolderBatches = [];
    const summary = $("#chosen-file-summary");
    if (summary) summary.textContent = "";
  }

  function configureAddDialog(mode) {
    const resolved = ["files", "folders", "folder"].includes(mode) ? mode : "files";
    if (addForm) addForm.dataset.addMode = resolved;
    const title = $("#add-dialog-title");
    const lead = $("#add-dialog-lead");
    const hint = $("#add-drop-hint");
    const filesBtn = $("#choose-workspace-files");
    const folderBtn = $("#choose-workspace-folder");
    if (resolved === "files") {
      if (title) title.textContent = "Add files";
      if (lead) {
        lead.innerHTML =
          "Files are copied into the vault. Numbered names such as <code>shaft.prt.3</code> keep only the latest save.";
      }
      if (hint) {
        hint.textContent = "Drop files here, or choose them. Copies go into the vault.";
      }
      if (filesBtn) filesBtn.hidden = false;
      if (folderBtn) folderBtn.hidden = true;
    } else if (resolved === "folders") {
      if (title) title.textContent = "Add folders";
      if (lead) {
        lead.textContent =
          "Choose one or more folders. Every nested file is imported. Choose Folder again to add another.";
      }
      if (hint) {
        hint.textContent =
          "Drop folders here, or choose them. Nested subfolders are included. On a LAN http:// address, drop folders instead of Choose Folder to avoid Chrome’s upload warning.";
      }
      if (filesBtn) filesBtn.hidden = true;
      if (folderBtn) {
        folderBtn.hidden = false;
        folderBtn.textContent = "Choose Folder";
      }
    } else {
      if (title) title.textContent = "Add Folder";
      if (lead) {
        lead.textContent =
          "Choose a folder. Only files directly inside it are imported — subfolders are skipped.";
      }
      if (hint) {
        hint.textContent =
          "Drop a folder here, or choose one. Only top-level files are added. On a LAN http:// address, drop the folder instead of Choose Folder to avoid Chrome’s upload warning.";
      }
      if (filesBtn) filesBtn.hidden = true;
      if (folderBtn) {
        folderBtn.hidden = false;
        folderBtn.textContent = "Choose Folder";
      }
    }
  }

  function openAddDialog(mode) {
    showError($("#add-error"), "");
    clearAddSelection();
    configureAddDialog(mode);
    loadAddFolder();
    addDialog?.showModal();
  }

  async function loadAddFolder() {
    const projectId = addForm?.dataset.project;
    const label = $("#add-folder-label");
    if (!projectId || !label) return;
    const response = await fetch(`/api/projects/${projectId}/workspace/add-folder`);
    if (!response.ok) return;
    const data = await response.json();
    if (addForm && data.native_picker !== undefined) {
      addForm.dataset.nativePicker = data.native_picker ? "1" : "0";
    }
    addInitialDirectory = String(data.initial_directory || "").trim();
    importIgnorePatterns = Array.isArray(data.ignore_patterns) ? data.ignore_patterns : [];
    importExtensions = Array.isArray(data.import_extensions)
      ? data.import_extensions.map((item) => String(item || "").toLowerCase())
      : [];
    if (!data.native_picker) {
      label.textContent = "Choose files or a folder in this browser. Copies go into the vault.";
      return;
    }
    label.textContent = `Opens in: ${data.initial_directory}`;
  }

  function fileCountLabel(count) {
    return count === 1 ? "1 file" : `${count} files`;
  }

  function importExtensionSet() {
    // Older .ext.N saves are omitted using Settings → Purgeable extensions.
    const fromApi = (importExtensions || [])
      .map((item) => String(item || "").trim().toLowerCase())
      .filter(Boolean)
      .map((item) => (item.startsWith(".") ? item : `.${item}`));
    if (fromApi.length) return new Set(fromApi);
    return purgeableExtensionSet();
  }

  function isImportVersionedExtension(extension) {
    const key = String(extension || "").trim().toLowerCase();
    if (!key) return false;
    const dotted = key.startsWith(".") ? key : `.${key}`;
    return importExtensionSet().has(dotted);
  }

  function importSaveNumber(filename) {
    const name = PathBasename(filename);
    const parts = name.split(".");
    if (parts.length < 3 || !parts[0]) return 0;
    const last = parts[parts.length - 1];
    const prev = parts[parts.length - 2];
    if (/^\d+$/.test(last) && isImportVersionedExtension(`.${prev}`)) {
      return Number.parseInt(last, 10) || 0;
    }
    if (/^\d+$/.test(prev) && isImportVersionedExtension(`.${last}`)) {
      return Number.parseInt(prev, 10) || 0;
    }
    return 0;
  }

  function countLatestImportNames(names) {
    const best = new Map();
    (names || []).forEach((raw) => {
      const rel = String(raw || "").replace(/\\/g, "/");
      if (!rel) return;
      const key = logicalRelativePath(rel).toLowerCase();
      const number = importSaveNumber(PathBasename(rel));
      const prev = best.get(key);
      if (prev == null || number > prev) best.set(key, number);
    });
    return best.size;
  }

  function formatReadyToAddSummary(selectedCount, willAddCount, skippedIgnored) {
    const omittedIgnored = skippedIgnored
      ? ` ${skippedIgnored} ignored ${skippedIgnored === 1 ? "file" : "files"} skipped.`
      : "";
    if (!willAddCount) {
      return skippedIgnored ? `No files to add.${omittedIgnored}` : "";
    }
    const older = Math.max(0, selectedCount - willAddCount);
    const omittedOlder = older
      ? ` ${older} older numbered ${older === 1 ? "save" : "saves"} omitted.`
      : "";
    return `${fileCountLabel(willAddCount)} ready to add.${omittedOlder}${omittedIgnored}`;
  }

  function logicalUploadName(name) {
    // Strip .ext.N / .N.ext only for Settings → Purgeable (import) extensions.
    const text = PathBasename(name);
    const parts = text.split(".");
    if (parts.length >= 3 && parts[0]) {
      const last = parts[parts.length - 1];
      const prev = parts[parts.length - 2];
      if (/^\d+$/.test(last) && isImportVersionedExtension(`.${prev}`)) {
        return parts.slice(0, -1).join(".");
      }
      if (/^\d+$/.test(prev) && isImportVersionedExtension(`.${last}`)) {
        return [...parts.slice(0, -2), last].join(".");
      }
    }
    return text;
  }

  function purgeableExtensionSet() {
    const raw = document.getElementById("metric-filters")?.dataset?.purgeable || "";
    return new Set(
      raw
        .split(/[\s,;]+/)
        .map((item) => item.trim().toLowerCase())
        .filter(Boolean)
        .map((item) => (item.startsWith(".") ? item : `.${item}`))
    );
  }

  function isPurgeableVersionedExtension(extension) {
    const key = String(extension || "").trim().toLowerCase();
    if (!key) return false;
    const dotted = key.startsWith(".") ? key : `.${key}`;
    return purgeableExtensionSet().has(dotted);
  }

  function creoSaveNumber(filename) {
    const name = PathBasename(filename);
    const parts = name.split(".");
    if (parts.length < 3 || !parts[0]) return 0;
    const last = parts[parts.length - 1];
    const prev = parts[parts.length - 2];
    if (/^\d+$/.test(last) && isPurgeableVersionedExtension(`.${prev}`)) {
      return Number.parseInt(last, 10) || 0;
    }
    if (/^\d+$/.test(prev) && isPurgeableVersionedExtension(`.${last}`)) {
      return Number.parseInt(prev, 10) || 0;
    }
    return 0;
  }

  function uploadExtension(name) {
    const logical = logicalUploadName(PathBasename(name)).toLowerCase();
    const dot = logical.lastIndexOf(".");
    return dot >= 0 ? logical.slice(dot) : "";
  }

  function PathBasename(value) {
    const text = String(value || "").replace(/\\/g, "/");
    const parts = text.split("/");
    return parts[parts.length - 1] || text;
  }

  function matchesIgnorePattern(name, pattern) {
    const target = PathBasename(name).toLowerCase();
    const logical = logicalUploadName(target).toLowerCase();
    const pat = String(pattern || "").toLowerCase();
    if (!pat) return false;
    const toRegex = (glob) =>
      new RegExp(
        `^${glob.replace(/[.+^${}()|[\]\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".")}$`,
        "i"
      );
    const re = toRegex(pat);
    return re.test(target) || re.test(logical);
  }

  function isIgnoredUploadName(name) {
    return importIgnorePatterns.some((pattern) => matchesIgnorePattern(name, pattern));
  }

  function isImportableUploadName(name) {
    // Skip configured ignore patterns only — allow CAD, documents, HTML, etc.
    return !isIgnoredUploadName(name);
  }

  function filterUploadItems(items) {
    const kept = [];
    let skipped = 0;
    for (const item of items || []) {
      const name = item?.relativePath || item?.file?.name || "";
      if (!item?.file || !isImportableUploadName(name)) {
        skipped += 1;
        continue;
      }
      kept.push(item);
    }
    return { kept, skipped };
  }

  function applyChosenPaths(paths, labelText, baseFolder, ignoredCount) {
    chosenUploads = [];
    chosenAgentPaths = [];
    chosenAgentBaseFolder = null;
    chosenAgentFolderBatches = [];
    if (addMode() === "folders" && baseFolder) {
      chosenPaths = [];
      chosenBaseFolder = null;
      const key = String(baseFolder);
      if (!chosenFolders.includes(key)) chosenFolders.push(key);
      const label = $("#add-folder-label");
      if (label && labelText) label.textContent = labelText;
      const summary = $("#chosen-file-summary");
      if (summary) {
        summary.textContent =
          chosenFolders.length === 1
            ? `Folder: ${chosenFolders[0]}`
            : `${chosenFolders.length} folders ready to add.`;
      }
      return;
    }
    chosenFolders = [];
    chosenPaths = paths || [];
    chosenBaseFolder = baseFolder || null;
    const label = $("#add-folder-label");
    if (label && labelText) label.textContent = labelText;
    const summary = $("#chosen-file-summary");
    if (!summary) return;
    const ignored = Number(ignoredCount) || 0;
    const omitted = ignored
      ? ` ${ignored} ignored ${ignored === 1 ? "file" : "files"} omitted.`
      : "";
    if (chosenBaseFolder) {
      summary.textContent = `Folder: ${chosenBaseFolder}.${omitted}`;
    } else if (chosenPaths.length) {
      const willAdd = countLatestImportNames(chosenPaths);
      summary.textContent = formatReadyToAddSummary(chosenPaths.length, willAdd, ignored);
    } else if (ignored) {
      summary.textContent = `No files to add.${omitted}`;
    } else {
      summary.textContent = "";
    }
  }

  function applyAgentPickedPaths(paths, baseFolder) {
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenUploads = [];
    const folder = baseFolder ? String(baseFolder) : "";
    const picked = [...new Set((paths || []).map((item) => String(item || "").trim()).filter(Boolean))];
    if (addMode() === "folders" && folder) {
      chosenAgentPaths = [];
      chosenAgentBaseFolder = null;
      chosenFolders = [];
      const existing = chosenAgentFolderBatches.find((item) => item.folder === folder);
      if (existing) existing.paths = picked;
      else chosenAgentFolderBatches.push({ folder, paths: picked });
      showError($("#add-error"), "");
      const summary = $("#chosen-file-summary");
      if (!summary) return;
      const total = chosenAgentFolderBatches.reduce((sum, item) => sum + item.paths.length, 0);
      summary.textContent =
        chosenAgentFolderBatches.length === 1
          ? `Folder: ${folder}. ${formatReadyToAddSummary(picked.length, countLatestImportNames(picked), 0)}`
          : `${chosenAgentFolderBatches.length} folders (${fileCountLabel(total)}) ready to add.`;
      return;
    }
    chosenFolders = [];
    chosenAgentFolderBatches = [];
    chosenAgentPaths = picked;
    chosenAgentBaseFolder = folder || null;
    showError($("#add-error"), "");
    const summary = $("#chosen-file-summary");
    if (!summary) return;
    if (!chosenAgentPaths.length) {
      summary.textContent = chosenAgentBaseFolder
        ? `Folder: ${chosenAgentBaseFolder} (no importable files).`
        : "";
      return;
    }
    const willAdd = countLatestImportNames(chosenAgentPaths);
    const ready = formatReadyToAddSummary(chosenAgentPaths.length, willAdd, 0);
    summary.textContent = chosenAgentBaseFolder
      ? `Folder: ${chosenAgentBaseFolder}. ${ready}`
      : ready;
  }

  function fileDiskPath(file) {
    return String(file.path || file.mozFullPath || "").trim();
  }

  function fileUrlToPath(value) {
    let text = String(value || "").trim().replace(/^["']|["']$/g, "");
    if (!text || text.startsWith("#")) return "";
    if (/^https?:/i.test(text)) {
      try {
        if (new URL(text).origin === window.location.origin) return "";
      } catch {
        return "";
      }
      return "";
    }
    if (/^file:/i.test(text)) {
      let path = text.replace(/^file:\/\//i, "");
      try {
        path = decodeURIComponent(path);
      } catch {
        /* keep raw */
      }
      path = path.replace(/^\/+/, "");
      if (/^[A-Za-z]:/.test(path)) return path.replace(/\//g, "\\");
      return `\\\\${path.replace(/\//g, "\\")}`;
    }
    if (/^[A-Za-z]:[\\/]/.test(text) || text.startsWith("\\\\")) {
      return text.replace(/\//g, "\\");
    }
    return "";
  }

  function pathsFromDrop(dataTransfer) {
    const chunks = [
      dataTransfer.getData("text/uri-list"),
      dataTransfer.getData("text/plain"),
      dataTransfer.getData("text/html"),
      dataTransfer.getData("URL"),
      dataTransfer.getData("text/x-moz-url"),
    ];
    const html = dataTransfer.getData("text/html") || "";
    for (const match of html.matchAll(/href\s*=\s*["']([^"']+)["']/gi)) {
      chunks.push(match[1]);
    }
    const found = [];
    const seen = new Set();
    for (const chunk of chunks) {
      for (const line of String(chunk || "").split(/\r?\n/)) {
        const path = fileUrlToPath(line);
        if (!path) continue;
        const key = path.toLowerCase();
        if (seen.has(key)) continue;
        seen.add(key);
        found.push(path);
      }
    }
    return found;
  }

  function transferCanDrop(dataTransfer) {
    if (!dataTransfer) return false;
    const types = [...(dataTransfer.types || [])];
    if (types.includes("Files") || (dataTransfer.files && dataTransfer.files.length)) return true;
    return types.some((type) =>
      ["text/uri-list", "text/plain", "text/html", "URL", "text/x-moz-url"].includes(type)
    );
  }

  function readAllDirectoryEntries(reader) {
    const entries = [];
    return new Promise((resolve, reject) => {
      const next = () => {
        reader.readEntries((batch) => {
          if (!batch.length) {
            resolve(entries);
            return;
          }
          entries.push(...batch);
          next();
        }, reject);
      };
      next();
    });
  }

  async function walkDropEntry(entry, prefix) {
    if (!entry) return [];
    if (entry.isFile) {
      const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
      const relativePath = prefix ? `${prefix}/${file.name}` : file.name;
      return [{ file, relativePath, path: fileDiskPath(file) }];
    }
    if (!entry.isDirectory) return [];
    const children = await readAllDirectoryEntries(entry.createReader());
    const next = prefix ? `${prefix}/${entry.name}` : entry.name;
    const found = [];
    for (const child of children) {
      found.push(...(await walkDropEntry(child, next)));
    }
    return found;
  }

  async function droppedItems(dataTransfer) {
    const items = [...(dataTransfer.items || [])];
    const entries = items.map((item) => item.webkitGetAsEntry?.()).filter(Boolean);
    if (entries.length) {
      const found = [];
      for (const entry of entries) {
        found.push(...(await walkDropEntry(entry, "")));
      }
      if (found.length) return found;
    }
    return [...(dataTransfer.files || [])].map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
      path: fileDiskPath(file),
    }));
  }

  function commonParentDir(paths) {
    const dirs = [...new Set(
      (paths || [])
        .map((item) => String(item || "").trim().replace(/\\/g, "/"))
        .filter(Boolean)
        .map((item) => {
          const cut = item.replace(/\/+$/, "");
          const idx = cut.lastIndexOf("/");
          return idx > 0 ? cut.slice(0, idx) : "";
        })
        .filter(Boolean)
    )];
    if (!dirs.length) return "";
    let parts = dirs[0].split("/");
    for (const dir of dirs.slice(1)) {
      const other = dir.split("/");
      let i = 0;
      while (i < parts.length && i < other.length && parts[i].toLowerCase() === other[i].toLowerCase()) {
        i += 1;
      }
      parts = parts.slice(0, i);
    }
    if (!parts.length) return "";
    // Need a real folder (not "C:" alone on Windows).
    if (parts.length === 1 && /^[A-Za-z]:$/.test(parts[0])) return "";
    return parts.join("/");
  }

  function filterTopLevelUploads(items) {
    /** Keep only files whose relative path has a single path segment after the root folder name. */
    const kept = [];
    let skipped = 0;
    for (const item of items || []) {
      const rel = String(item?.relativePath || item?.file?.name || "").replace(/\\/g, "/");
      if (!rel || !item?.file) {
        skipped += 1;
        continue;
      }
      const parts = rel.split("/").filter(Boolean);
      // webkitRelativePath / walk: FolderName/file.ext → 2 parts (keep); FolderName/sub/file → 3+ (skip)
      if (parts.length > 2) {
        skipped += 1;
        continue;
      }
      kept.push(item);
    }
    return { kept, skipped };
  }

  function applyDroppedFiles(items, uriPaths) {
    let uploads = (items || []).filter((item) => item?.file);
    if (addMode() === "files") {
      // Files mode: reject nested folder trees so Add files stays file-only.
      const nested = uploads.some((item) => String(item.relativePath || "").includes("/"));
      if (nested) {
        showError($("#add-error"), "Use Add folders or Add Folder to import a folder tree.");
        return;
      }
    } else if (addMode() === "folder") {
      const filtered = filterTopLevelUploads(uploads);
      uploads = filtered.kept;
      if (!uploads.length && filtered.skipped) {
        showError(
          $("#add-error"),
          "No top-level files found in that folder. Subfolder files are skipped for Add Folder."
        );
        return;
      }
    }
    const nestedUploads = uploads.some((item) => String(item.relativePath || "").includes("/"));
    // Keep browser-relative paths whenever a folder tree was walked — disk paths
    // alone would flatten nested subfolders (Creo / some Chromium builds set .path).
    if (nestedUploads) {
      const { kept, skipped } = filterUploadItems(uploads);
      chosenPaths = [];
      chosenBaseFolder = null;
      chosenFolders = [];
      chosenAgentPaths = [];
      chosenAgentBaseFolder = null;
      chosenAgentFolderBatches = [];
      chosenUploads = kept;
      const summary = $("#chosen-file-summary");
      if (summary) {
        const willAdd = countLatestImportNames(
          kept.map((item) => item.relativePath || item.file?.name || "")
        );
        summary.textContent = formatReadyToAddSummary(kept.length, willAdd, skipped);
      }
      return;
    }
    const diskPaths = [
      ...(uriPaths || []),
      ...uploads.map((item) => item.path).filter(Boolean),
    ];
    const uniquePaths = [...new Set(diskPaths)];
    if (uniquePaths.length && uniquePaths.length >= uploads.length) {
      const base = commonParentDir(uniquePaths);
      applyChosenPaths(
        uniquePaths,
        base ? `Folder: ${base}` : "",
        base || null,
        0
      );
      return;
    }
    const { kept, skipped } = filterUploadItems(uploads);
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenFolders = [];
    chosenAgentPaths = [];
    chosenAgentBaseFolder = null;
    chosenAgentFolderBatches = [];
    chosenUploads = kept;
    const summary = $("#chosen-file-summary");
    if (summary) {
      const willAdd = countLatestImportNames(
        kept.map((item) => item.relativePath || item.file?.name || "")
      );
      summary.textContent = formatReadyToAddSummary(kept.length, willAdd, skipped);
    }
  }

  function applyBrowserPickedFiles(fileList) {
    const uploads = [...(fileList || [])].map((file) => ({
      file,
      relativePath: file.webkitRelativePath || file.name,
      path: fileDiskPath(file),
    }));
    applyDroppedFiles(uploads, []);
  }

  async function walkDirectoryHandle(dirHandle, prefix, recursive = true) {
    const found = [];
    for await (const [name, handle] of dirHandle.entries()) {
      const relativePath = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "directory") {
        if (recursive) found.push(...(await walkDirectoryHandle(handle, relativePath, true)));
      } else if (handle.kind === "file") {
        const file = await handle.getFile();
        found.push({ file, relativePath, path: "" });
      }
    }
    return found;
  }

  function canUseDirectoryPicker() {
    return (
      typeof window.showDirectoryPicker === "function" &&
      window.isSecureContext === true
    );
  }

  async function browseLocalFolder() {
    if (canUseDirectoryPicker()) {
      try {
        const handle = await window.showDirectoryPicker({ mode: "read" });
        const items = await withBusy("Reading folder…", () =>
          walkDirectoryHandle(handle, handle.name || "", isRecursiveAddMode())
        );
        applyDroppedFiles(items, []);
        if (addDialog && !addDialog.open) addDialog.showModal();
        return;
      } catch (err) {
        if (err && (err.name === "AbortError" || err.name === "NotAllowedError")) return;
        showError(
          $("#add-error"),
          "Could not open the folder picker. Drag the folder onto the drop zone instead."
        );
        return;
      }
    }
    // webkitdirectory always triggers Chrome's "Upload N files to this site?" prompt.
    // Prefer drag-and-drop on http://LAN addresses (not a secure context).
    showError(
      $("#add-error"),
      "Folder pick needs https:// or http://127.0.0.1. Drag the folder onto the drop zone instead — that skips Chrome's upload warning."
    );
  }

  function bindDropTarget(node, onFiles) {
    if (!node) return;
    let depth = 0;
    const mark = (active) => node.classList.toggle("is-dragover", active);
    node.addEventListener("dragenter", (event) => {
      event.preventDefault();
      depth += 1;
      mark(true);
    });
    node.addEventListener("dragover", (event) => {
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    });
    node.addEventListener("dragleave", () => {
      depth -= 1;
      if (depth <= 0) {
        depth = 0;
        mark(false);
      }
    });
    node.addEventListener("drop", (event) => {
      event.preventDefault();
      depth = 0;
      mark(false);
      onFiles(event.dataTransfer);
    });
  }

  $("#add-files-btn")?.addEventListener("click", () => {
    closeAddMenu();
    openAddDialog("files");
  });
  $("#add-folders-btn")?.addEventListener("click", () => {
    closeAddMenu();
    openAddDialog("folders");
  });
  $("#add-folder-btn")?.addEventListener("click", () => {
    closeAddMenu();
    openAddDialog("folder");
  });
  $("#add-cancel")?.addEventListener("click", () => addDialog?.close());

  function useNativePicker() {
    return addForm?.dataset.nativePicker !== "0";
  }

  function browseLocalFiles(input) {
    if (!input) return;
    let settled = false;
    const finish = (files) => {
      if (settled) return;
      settled = true;
      window.removeEventListener("focus", onFocus);
      if (files && files.length) applyBrowserPickedFiles(files);
      if (addDialog && !addDialog.open) addDialog.showModal();
    };
    const onFocus = () => window.setTimeout(() => finish(input.files), 400);
    input.addEventListener("change", () => finish(input.files), { once: true });
    input.addEventListener("cancel", () => finish([]), { once: true });
    window.addEventListener("focus", onFocus);
    addDialog?.close();
    input.value = "";
    input.click();
  }

  async function browseViaAgentPicker() {
    const agent = await probeCreoAgent();
    if (!agent) return false;
    const pickResponse = await fetch(`${agentBase()}/pick-files`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_directory: addInitialDirectory || "",
        title: "Add files to the project",
        purgeable_extensions: [...purgeableExtensionSet()],
      }),
    });
    if (!pickResponse.ok) {
      showError($("#add-error"), await readError(pickResponse));
      return true;
    }
    const picked = await pickResponse.json();
    const paths = Array.isArray(picked.selected) ? picked.selected : [];
    if (!paths.length) return true;
    // Keep absolute paths on the agent — do not pull thousands of bodies into the browser.
    applyAgentPickedPaths(paths);
    return true;
  }

  async function browseViaAgentFolderPicker() {
    const agent = await probeCreoAgent();
    if (!agent) return false;
    const recursive = isRecursiveAddMode();
    const pickResponse = await fetch(`${agentBase()}/pick-folder`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        initial_directory: addInitialDirectory || "",
        title: recursive ? "Add folders to the project" : "Add a folder to the project",
        purgeable_extensions: [...purgeableExtensionSet()],
        recursive,
      }),
    });
    if (!pickResponse.ok) {
      showError($("#add-error"), await readError(pickResponse));
      return true;
    }
    const picked = await pickResponse.json();
    if (picked.cancelled) return true;
    const paths = Array.isArray(picked.selected) ? picked.selected : [];
    const folder = String(picked.folder || "").trim();
    if (!paths.length) {
      showError(
        $("#add-error"),
        folder
          ? `No importable files found in ${folder}.`
          : "No folder was selected."
      );
      return true;
    }
    applyAgentPickedPaths(paths, folder);
    return true;
  }

  $("#choose-workspace-files")?.addEventListener("click", async () => {
    const projectId = addForm?.dataset.project;
    if (!projectId) return;
    showError($("#add-error"), "");
    if (!useNativePicker()) {
      const usedAgent = await withHtmlDialogClosed(addDialog, () => browseViaAgentPicker());
      if (usedAgent) return;
      browseLocalFiles($("#add-file-input"));
      return;
    }
    await withHtmlDialogClosed(addDialog, async () => {
      const response = await fetch(`/api/projects/${projectId}/workspace/choose-files`, { method: "POST" });
      if (!response.ok) {
        showError($("#add-error"), await readError(response));
        return;
      }
      const data = await response.json();
      applyChosenPaths(
        data.selected || [],
        data.initial_directory ? `Opens in: ${data.initial_directory}` : "",
        null,
        data.ignored_count || 0
      );
      if (data.warning) showError($("#add-error"), data.warning);
    });
  });

  $("#choose-workspace-folder")?.addEventListener("click", async () => {
    const projectId = addForm?.dataset.project;
    if (!projectId) return;
    showError($("#add-error"), "");
    if (!useNativePicker()) {
      const usedAgent = await withHtmlDialogClosed(addDialog, () => browseViaAgentFolderPicker());
      if (usedAgent) return;
      await browseLocalFolder();
      return;
    }
    await withHtmlDialogClosed(addDialog, async () => {
      const response = await withBusy("Choosing folder…", () =>
        fetch(`/api/projects/${projectId}/workspace/choose-folder`, { method: "POST" })
      );
      if (!response.ok) {
        showError($("#add-error"), await readError(response));
        return;
      }
      const data = await response.json();
      if (data.cancelled) return;
      const folder = data.folder || "";
      if (!folder) {
        showError($("#add-error"), "No folder was selected.");
        return;
      }
      applyChosenPaths([], `Folder: ${folder}`, folder);
    });
  });

  async function handleDroppedTransfer(dataTransfer) {
    showError($("#add-error"), "");
    const uriPaths = pathsFromDrop(dataTransfer);
    const items = await droppedItems(dataTransfer);
    if (!items.length && !uriPaths.length) {
      showError($("#add-error"), "Drop a file, folder, or a link to a local file.");
      return;
    }
    applyDroppedFiles(items, uriPaths);
  }

  function showPageDrop(active) {
    document.body.classList.toggle("is-file-drag", active);
    const overlay = $("#file-drop-overlay");
    if (overlay) overlay.hidden = !active;
  }

  function canAcceptDrops() {
    const btn = $("#add-menu-btn") || $("#add-files-btn");
    return Boolean(btn && !btn.disabled && addForm?.dataset.project);
  }

  async function acceptPageDrop(dataTransfer) {
    if (!canAcceptDrops()) return;
    if (!addDialog?.open) {
      // Default page-drop to Add folders when dropping trees; files otherwise.
      openAddDialog("folders");
    }
    await handleDroppedTransfer(dataTransfer);
  }

  let hidePageDropTimer = 0;
  window.addEventListener("dragenter", (event) => {
    if (!transferCanDrop(event.dataTransfer) || !canAcceptDrops()) return;
    event.preventDefault();
    window.clearTimeout(hidePageDropTimer);
    showPageDrop(true);
  }, true);
  window.addEventListener("dragover", (event) => {
    if (!transferCanDrop(event.dataTransfer) || !canAcceptDrops()) return;
    event.preventDefault();
    if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    window.clearTimeout(hidePageDropTimer);
    showPageDrop(true);
  }, true);
  window.addEventListener("dragleave", () => {
    window.clearTimeout(hidePageDropTimer);
    hidePageDropTimer = window.setTimeout(() => showPageDrop(false), 80);
  }, true);
  window.addEventListener("drop", (event) => {
    window.clearTimeout(hidePageDropTimer);
    showPageDrop(false);
    if (!transferCanDrop(event.dataTransfer)) return;
    event.preventDefault();
    event.stopPropagation();
    if (!canAcceptDrops()) return;
    acceptPageDrop(event.dataTransfer);
  }, true);

  bindDropTarget($("#dropzone"), (transfer) => {
    handleDroppedTransfer(transfer);
  });

  let addInFlight = false;
  addForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (addInFlight) {
      showError($("#add-error"), "Add is already running — wait for it to finish.");
      return;
    }
    const projectId = addForm.dataset.project;
    if (!projectId) return;
    if (
      !chosenPaths.length
      && !chosenBaseFolder
      && !chosenFolders.length
      && !chosenUploads.length
      && !chosenAgentPaths.length
      && !chosenAgentFolderBatches.length
    ) {
      showError(
        $("#add-error"),
        isFolderAddMode() ? "Choose a folder first." : "Choose files or a folder first."
      );
      return;
    }
    const comment = String(new FormData(addForm).get("comment") || "").trim();
    const recursive = isRecursiveAddMode();
    addInFlight = true;
    let result;
    try {
    result = await withBusy(
      chosenFolders.length || chosenBaseFolder || chosenAgentFolderBatches.length
        ? chosenFolders.length > 1 || chosenAgentFolderBatches.length > 1
          ? "Adding folders…"
          : "Adding folder…"
        : chosenAgentPaths.length > 100
          ? `Adding ${chosenAgentPaths.length} files…`
          : "Adding files…",
      async () => {
      async function addAgentPathChunks(paths, baseFolder, commentOnce) {
        const agent = await probeCreoAgent();
        if (!agent) {
          showError(
            $("#add-error"),
            "Start creopdm-agent on this Creo PC to add the selected files."
          );
          return null;
        }
        const list = [...paths];
        const total = list.length;
        const chunkSize = 25;
        const combined = { ok: [], failed: [] };
        const parentFolder = currentFolder() || "";
        const basenameOf = (path) => {
          const text = String(path || "");
          const parts = text.split(/[/\\]/);
          return parts[parts.length - 1] || text;
        };
        for (let offset = 0; offset < list.length; offset += chunkSize) {
          const chunk = list.slice(offset, offset + chunkSize);
          const done = Math.min(offset + chunk.length, total);
          setBusyMessage(`Adding files… ${done} of ${total}`);
          let response;
          try {
            response = await fetch(`${agentBase()}/add-paths`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                pdm_url: window.location.origin,
                project_id: projectId,
                absolute_paths: chunk,
                base_folder: baseFolder || "",
                parent_folder: parentFolder,
                comment: offset === 0 ? commentOnce || null : null,
                client_offset: offset,
                client_total: total,
                purgeable_extensions: [...purgeableExtensionSet()],
              }),
            });
          } catch (exc) {
            const message = exc?.message || "Could not reach creopdm-agent.";
            chunk.forEach((path) => {
              combined.failed.push({
                filename: basenameOf(path),
                code: "NETWORK",
                message,
              });
            });
            continue;
          }
          if (!response.ok) {
            let message = `creopdm-agent returned ${response.status}`;
            try {
              message = await readError(response);
            } catch {
              /* keep status message */
            }
            chunk.forEach((path) => {
              combined.failed.push({
                filename: basenameOf(path),
                code: "HTTP_ERROR",
                message,
              });
            });
            continue;
          }
          let body = {};
          try {
            body = await response.json();
          } catch (exc) {
            const message = exc?.message || "Invalid JSON from creopdm-agent.";
            chunk.forEach((path) => {
              combined.failed.push({
                filename: basenameOf(path),
                code: "BAD_RESPONSE",
                message,
              });
            });
            continue;
          }
          combined.ok.push(...(body.ok || []));
          combined.failed.push(...(body.failed || []));
        }
        return combined;
      }
      if (chosenAgentFolderBatches.length) {
        const combined = { ok: [], failed: [] };
        for (let i = 0; i < chosenAgentFolderBatches.length; i += 1) {
          const batch = chosenAgentFolderBatches[i];
          setBusyMessage(
            `Adding folder ${i + 1} of ${chosenAgentFolderBatches.length}…`
          );
          const part = await addAgentPathChunks(
            batch.paths,
            batch.folder,
            i === 0 ? comment : null
          );
          if (!part) return combined.ok.length ? combined : null;
          combined.ok.push(...(part.ok || []));
          combined.failed.push(...(part.failed || []));
        }
        return combined;
      }
      if (chosenAgentPaths.length) {
        return addAgentPathChunks(chosenAgentPaths, chosenAgentBaseFolder, comment);
      }
      if (chosenUploads.length) {
        const combined = { ok: [], failed: [] };
        const total = chosenUploads.length;
        const parentFolder = currentFolder() || "";
        for (let offset = 0; offset < chosenUploads.length; offset += UPLOAD_CHUNK) {
          const chunk = chosenUploads.slice(offset, offset + UPLOAD_CHUNK);
          const done = Math.min(offset + chunk.length, total);
          setBusyMessage(`Adding files… ${done} of ${total}`);
          const data = new FormData();
          if (comment && offset === 0) data.append("comment", comment);
          if (parentFolder) data.append("parent_folder", parentFolder);
          chunk.forEach((item) => {
            data.append("files", item.file, item.file.name);
            data.append("relative_paths", item.relativePath || item.file.name);
          });
          const response = await fetch(`/api/projects/${projectId}/objects/from-uploads`, {
            method: "POST",
            body: data,
          });
          if (!response.ok) {
            showError($("#add-error"), await readError(response));
            return combined.ok.length ? combined : null;
          }
          const body = await response.json();
          combined.ok.push(...(body.ok || []));
          combined.failed.push(...(body.failed || []));
        }
        return combined;
      }
      const parentFolder = currentFolder() || "";
      let payload;
      if (chosenFolders.length) {
        payload = {
          folders: chosenFolders,
          recursive,
          parent_folder: parentFolder || "",
          comment: comment || null,
        };
      } else if (chosenBaseFolder) {
        payload = {
          folder: chosenBaseFolder,
          base_folder: chosenBaseFolder,
          recursive,
          parent_folder: parentFolder || "",
          comment: comment || null,
        };
      } else {
        payload = {
          paths: chosenPaths,
          parent_folder: parentFolder || "",
          comment: comment || null,
        };
      }
      const response = await fetch(`/api/projects/${projectId}/objects/from-disk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        showError($("#add-error"), await readError(response));
        return null;
      }
      return response.json();
    });
    if (!result) return;
    const failed = result.failed || [];
    const okCount = result.ok?.length || 0;
    const summarizeAddFailures = (items) => {
      const counts = {};
      for (const item of items || []) {
        const code = String(item?.code || "FAILED").trim() || "FAILED";
        counts[code] = (counts[code] || 0) + 1;
      }
      return Object.keys(counts)
        .sort()
        .map((code) => `${code}=${counts[code]}`)
        .join(", ");
    };
    const rememberNotice = (message) => {
      const text = String(message || "").trim();
      if (!text) return;
      try {
        sessionStorage.setItem("creopdmNotice", text);
      } catch {
        /* private mode / blocked storage */
      }
    };
    if (failed.length && !okCount) {
      const first = failed[0]?.message || "Could not add files.";
      const codes = summarizeAddFailures(failed);
      const msg =
        first +
        ` (${failed.length} files failed` +
        (codes ? `: ${codes}` : "") +
        ").";
      showError($("#add-error"), msg);
      rememberNotice(msg);
      return;
    }
    if (failed.length && okCount) {
      const codes = summarizeAddFailures(failed);
      const sample = failed
        .slice(0, 3)
        .map((item) => item.filename || item.uuid || "file")
        .join(", ");
      const msg =
        `Added ${okCount} file(s); ${failed.length} failed` +
        (codes ? ` [${codes}]` : "") +
        ` (${sample}${failed.length > 3 ? ", …" : ""}).` +
        " See creopdm-agent log for each file.";
      showError($("#add-error"), msg);
      rememberNotice(msg);
    }
    if (canGatherCreoMetadata() && okCount > 0 && okCount <= 50) {
      await withBusy("Capturing Creo metadata…", async () => {
        await pushCreoMetadataForItems(metadataTargetsFromResult(result));
      });
    } else if (okCount > 50) {
      const indexNote =
        result.where_used_index === "started"
          ? " Where Used indexing started in the background."
          : "";
      showOk(
        `${okCount} file(s) added. Creo metadata was skipped for this large add — open a model in Creo and Check In to capture it.${indexNote}`
      );
    }
    if (okCount) reloadPage();
    } finally {
      addInFlight = false;
    }
  });

  const searchInput = $("#search-input");
  const isListPage = Boolean(document.querySelector("#object-table"));
  const objectTable = $("#object-table");
  const objectTbody = objectTable?.querySelector("tbody");
  const searchScope = $("#search-scope");
  const folderCrumb = document.querySelector(".folder-crumb");
  let folderTbodyHtml = objectTbody?.innerHTML ?? "";
  let searchTimer = 0;
  let searchSeq = 0;

  function escapeHtml(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function folderOfPath(relative) {
    const posix = String(relative || "").replace(/\\/g, "/");
    const index = posix.lastIndexOf("/");
    return index < 0 ? "" : posix.slice(0, index);
  }

  function titleCaseWords(value) {
    return String(value || "")
      .replace(/_/g, " ")
      .toLowerCase()
      .replace(/\b[a-z]/g, (ch) => ch.toUpperCase());
  }

  function formatStamp(iso) {
    if (!iso) return "";
    let raw = String(iso).trim();
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(raw) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)) {
      raw += "Z";
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return "";
    const pad = (n) => String(n).padStart(2, "0");
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
  }

  function padIteration(value) {
    return String(Number(value) || 0).padStart(6, "0");
  }

  function typeIconMaps() {
    const raw = $("#metric-filters")?.dataset?.typeIcons || "";
    if (!raw) return { by_ext: {}, by_label: {}, by_object_type: {} };
    try {
      const parsed = JSON.parse(raw);
      return {
        by_ext: parsed.by_ext || {},
        by_label: parsed.by_label || {},
        by_object_type: parsed.by_object_type || {},
      };
    } catch {
      return { by_ext: {}, by_label: {}, by_object_type: {} };
    }
  }

  function resolveTypeIcon(spec = {}) {
    const maps = typeIconMaps();
    const label = String(spec.typeLabel || spec.type_label || "").trim();
    if (label && maps.by_label[label]) return { file: maps.by_label[label], label };
    const ext = String(spec.extension || filenameExtension(spec.filename || "")).toLowerCase();
    if (ext && maps.by_ext[ext]) {
      return { file: maps.by_ext[ext], label: label || ext };
    }
    const objectType = String(spec.objectType || spec.object_type || "").toUpperCase();
    if (objectType && maps.by_object_type[objectType]) {
      const fallback =
        objectType === "CREO_PART"
          ? "Part"
          : objectType === "CREO_ASSEMBLY"
            ? "Assembly"
            : objectType === "CREO_DRAWING"
              ? "Drawing"
              : label || objectType;
      return { file: maps.by_object_type[objectType], label: label || fallback };
    }
    if (label || ext || objectType) {
      return { file: maps.by_label._default || "file.svg", label: label || ext || "File" };
    }
    return { file: "", label: "" };
  }

  function typeIconHtml(spec) {
    // Legacy: typeIconHtml("CREO_PART") still works.
    const info =
      typeof spec === "string"
        ? resolveTypeIcon({ objectType: spec })
        : resolveTypeIcon(spec || {});
    if (!info.file) return "";
    const label = escapeHtml(info.label || "File");
    return `<img class="type-icon" src="/static/icons/${escapeHtml(info.file)}" alt="${label}" title="${label}" width="14" height="14" decoding="async">`;
  }

  function searchRowHtml(obj, projectId) {
    const relative = String(obj.relative_path || obj.filename || "");
    const folder = folderOfPath(relative);
    const filename = String(obj.filename || "");
    const stamp = formatStamp(obj.updated_at);
    const state = String(obj.lifecycle_state || "");
    const stateLabel = titleCaseWords(state);
    const typeLabel = String(obj.type_label || "");
    const objectType = String(obj.object_type || "");
    const creo = String(obj.creo_release || "");
    const checkout = String(obj.checkout_status || "Available");
    const checkoutKind = obj.owned_by_me ? "mine" : obj.checkout_user ? "other" : "available";
    const rev = String(obj.display_revision || obj.revision || "");
    const pathLine = relative && relative !== filename
      ? `<div class="muted small">${escapeHtml(relative)}</div>`
      : "";
    const icon = typeIconHtml({
      objectType,
      typeLabel,
      extension: obj.extension || filenameExtension(filename),
      filename,
    });
    const modifiedLocally = Boolean(obj.modified_locally);
    const showModified =
      modifiedLocally && (obj.owned_by_me || obj.can_checkin);
    const stateDisplay = showModified ? "MODIFIED" : state;
    const stateDisplayLabel = showModified ? "Modified" : stateLabel;
    const stateSort = stateSortToken(stateDisplay);
    return `<tr data-uuid="${escapeHtml(obj.uuid)}"
              data-object-type="${escapeHtml(objectType)}"
              data-extension="${escapeHtml(obj.extension || "")}"
              data-filename="${escapeHtml(obj.filename || "")}"
              data-relative-path="${escapeHtml(relative)}"
              data-can-checkout="${obj.can_checkout ? "1" : "0"}"
              data-can-checkin="${obj.can_checkin ? "1" : "0"}"
              data-owned="${obj.owned_by_me ? "1" : "0"}"
              data-checked-out="${obj.owned_by_me || obj.checkout_user ? "1" : "0"}"
              data-modified-locally="${modifiedLocally ? "1" : "0"}"
              data-in-workspace="${obj.in_workspace ? "1" : "0"}"
              data-tree="${escapeHtml(folder)}"
              data-sort-name="${escapeHtml(relative)}"
              data-sort-rev="${escapeHtml(folder)}/${escapeHtml(obj.revision || "")}-${padIteration(obj.iteration)}"
              data-sort-state="${escapeHtml(folder)}/${escapeHtml(stateSort)}"
              data-sort-type="${escapeHtml(folder)}/${escapeHtml(typeLabel)}"
              data-sort-creo="${escapeHtml(folder)}/${escapeHtml(creo)}"
              data-sort-modified="${stamp.replace(/[-: ]/g, "")}"
              data-sort-checkout="${escapeHtml(folder)}/${escapeHtml(checkout)}"
              data-detail="/projects/${escapeHtml(projectId)}/objects/${escapeHtml(obj.uuid)}#history"
              class="object-row"
              style="--depth: 0">
            <td title="${escapeHtml(filename)}">
              <span class="name-with-icon">${icon}<button type="button" class="object-open" data-uuid="${escapeHtml(obj.uuid)}" title="Open this file">${escapeHtml(filename)}</button></span>
              ${pathLine}
            </td>
            <td title="${escapeHtml(rev)}">${escapeHtml(rev)}</td>
            <td title="${escapeHtml(stateDisplayLabel)}"><span class="state" data-state="${escapeHtml(stateDisplay)}" data-lifecycle-state="${escapeHtml(state)}">${escapeHtml(stateDisplayLabel)}</span></td>
            <td title="${escapeHtml(typeLabel)}">${escapeHtml(typeLabel)}</td>
            <td title="${escapeHtml(creo)}">${escapeHtml(creo)}</td>
            <td title="${escapeHtml(stamp || "—")}">${escapeHtml(stamp || "—")}</td>
            <td title="${escapeHtml(checkout)}">
              <span class="checkout-state" data-state="${checkoutKind}">${escapeHtml(checkout)}</span>
            </td>
          </tr>`;
  }

  function showFolderView() {
    if (!objectTable || !objectTbody) return;
    objectTable.dataset.searching = "";
    objectTbody.innerHTML = folderTbodyHtml;
    if (searchScope) searchScope.hidden = true;
    if (folderCrumb) folderCrumb.hidden = false;
    updateMetricCounts();
  }

  function showSearchMatches(items, projectId) {
    if (!objectTable || !objectTbody) return;
    objectTable.dataset.searching = "1";
    if (searchScope) searchScope.hidden = false;
    if (folderCrumb) folderCrumb.hidden = true;
    if (!items.length) {
      objectTbody.innerHTML = `<tr class="empty-row"><td colspan="7">No matching files in this project.</td></tr>`;
      updateMetricCounts();
      return;
    }
    objectTbody.innerHTML = items.map((item) => searchRowHtml(item, projectId)).join("");
    updateMetricCounts();
    syncModifiedStateLabels();
  }

  async function searchAllFolders(query) {
    const projectId = $("#rename-project-btn")?.dataset.project;
    if (!objectTbody || !projectId) {
      applyMetricVisibility();
      syncToolbar();
      return;
    }
    const seq = ++searchSeq;
    const response = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/objects?q=${encodeURIComponent(query)}`
    );
    if (seq !== searchSeq) return;
    if (!response.ok) {
      showFolderView();
      applyMetricVisibility();
      syncToolbar();
      return;
    }
    const items = await response.json();
    if (seq !== searchSeq) return;
    showSearchMatches(Array.isArray(items) ? items : [], projectId);
    applyMetricVisibility();
    applyMetricSelection();
    syncToolbar();
  }

  function onSearchInput() {
    const query = searchInput?.value.trim() || "";
    window.clearTimeout(searchTimer);
    if (!query) {
      searchSeq += 1;
      showFolderView();
      applyMetricVisibility();
      applyMetricSelection();
      syncToolbar();
      return;
    }
    searchTimer = window.setTimeout(() => {
      void searchAllFolders(query);
    }, 200);
  }

  searchInput?.addEventListener("input", onSearchInput);
  $("#search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    window.clearTimeout(searchTimer);
    const query = searchInput?.value.trim() || "";
    if (!query) {
      searchSeq += 1;
      showFolderView();
      applyMetricVisibility();
      applyMetricSelection();
      syncToolbar();
      return;
    }
    void searchAllFolders(query);
  });

  const historyBtn = $("#history-btn");
  const openBtn = $("#open-btn");
  const openMenu = $("#open-menu");
  const openMenuBtn = $("#open-menu-btn");
  const openMenuPanel = openMenu?.querySelector(".toolbar-menu-panel");
  const checkoutBtn = $("#checkout-btn");
  const checkoutProjectBtn = $("#checkout-project-btn");
  const checkoutMenu = $("#checkout-menu");
  const checkoutMenuBtn = $("#checkout-menu-btn");
  const checkoutMenuPanel = checkoutMenu?.querySelector(".toolbar-menu-panel");
  const checkinBtn = $("#checkin-btn");
  const checkinProjectBtn = $("#checkin-project-btn");
  const checkinMenu = $("#checkin-menu");
  const checkinMenuBtn = $("#checkin-menu-btn");
  const checkinMenuPanel = checkinMenu?.querySelector(".toolbar-menu-panel");
  const undoBtn = $("#undo-btn");
  const workspaceBtn = $("#workspace-btn");
  const openWorkspaceBtn = $("#open-workspace-btn");
  const setCreoDirBtn = $("#set-creo-dir-btn");
  const purgeBtn = $("#purge-workspace-btn");
  const purgeVersionsBtn = $("#purge-versions-btn");
  const removeBtn = $("#remove-project-btn");
  const discardLocalBtn = $("#discard-local-btn");
  const removeMenu = $("#remove-menu");
  const removeMenuBtn = $("#remove-menu-btn");
  const removeMenuPanel = removeMenu?.querySelector(".toolbar-menu-panel");
  const addMenu = $("#add-menu");
  const addMenuBtn = $("#add-menu-btn");
  const addMenuPanel = addMenu?.querySelector(".toolbar-menu-panel");
  const createFolderDialog = $("#create-folder-dialog");
  const createFolderForm = $("#create-folder-form");

  function closeToolbarMenu(menu, btn, panel) {
    if (!menu || !btn || !panel) return;
    menu.classList.remove("is-open");
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
  }

  function openToolbarMenu(menu, btn, panel) {
    if (!menu || !btn || !panel || btn.disabled || btn.hidden || menu.hidden) return;
    menu.classList.add("is-open");
    panel.hidden = false;
    btn.setAttribute("aria-expanded", "true");
  }

  function toggleToolbarMenu(menu, btn, panel) {
    if (menu?.classList.contains("is-open")) closeToolbarMenu(menu, btn, panel);
    else openToolbarMenu(menu, btn, panel);
  }

  function closeRemoveMenu() {
    closeToolbarMenu(removeMenu, removeMenuBtn, removeMenuPanel);
  }

  function closeCheckoutMenu() {
    closeToolbarMenu(checkoutMenu, checkoutMenuBtn, checkoutMenuPanel);
  }

  function closeCheckinMenu() {
    closeToolbarMenu(checkinMenu, checkinMenuBtn, checkinMenuPanel);
  }

  function closeAddMenu() {
    closeToolbarMenu(addMenu, addMenuBtn, addMenuPanel);
  }

  function closeOpenMenu() {
    closeToolbarMenu(openMenu, openMenuBtn, openMenuPanel);
  }

  function closeAllToolbarMenus() {
    closeRemoveMenu();
    closeCheckoutMenu();
    closeCheckinMenu();
    closeAddMenu();
    closeOpenMenu();
  }

  function openRemoveMenu() {
    closeCheckoutMenu();
    closeCheckinMenu();
    closeAddMenu();
    closeOpenMenu();
    openToolbarMenu(removeMenu, removeMenuBtn, removeMenuPanel);
  }

  function toggleRemoveMenu() {
    if (removeMenu?.classList.contains("is-open")) closeRemoveMenu();
    else openRemoveMenu();
  }

  function toggleCheckoutMenu() {
    if (checkoutMenu?.classList.contains("is-open")) closeCheckoutMenu();
    else {
      closeRemoveMenu();
      closeCheckinMenu();
      closeAddMenu();
      closeOpenMenu();
      openToolbarMenu(checkoutMenu, checkoutMenuBtn, checkoutMenuPanel);
    }
  }

  function toggleCheckinMenu() {
    if (checkinMenu?.classList.contains("is-open")) closeCheckinMenu();
    else {
      closeRemoveMenu();
      closeCheckoutMenu();
      closeAddMenu();
      closeOpenMenu();
      openToolbarMenu(checkinMenu, checkinMenuBtn, checkinMenuPanel);
    }
  }

  function toggleAddMenu() {
    if (addMenu?.classList.contains("is-open")) closeAddMenu();
    else {
      closeRemoveMenu();
      closeCheckoutMenu();
      closeCheckinMenu();
      closeOpenMenu();
      openToolbarMenu(addMenu, addMenuBtn, addMenuPanel);
    }
  }

  function toggleOpenMenu() {
    if (openMenu?.classList.contains("is-open")) closeOpenMenu();
    else {
      closeRemoveMenu();
      closeCheckoutMenu();
      closeCheckinMenu();
      closeAddMenu();
      openToolbarMenu(openMenu, openMenuBtn, openMenuPanel);
    }
  }
  function rowObjectIds(row) {
    if (row.classList.contains("folder-row")) {
      return (row.dataset.objectIds || "").split(",").map((item) => item.trim()).filter(Boolean);
    }
    return row.dataset.uuid ? [row.dataset.uuid] : [];
  }

  function selectedFolderPaths() {
    return [
      ...new Set(
        selectedRows()
          .filter((row) => row.classList.contains("folder-row"))
          .map((row) => String(row.dataset.folder || "").trim())
          .filter(Boolean)
      ),
    ];
  }

  function selectedRows() {
    const picked = rows().filter((row) => row.classList.contains("is-selected") && !rowIsHidden(row));
    if (picked.length) return picked;
    if (checkoutBtn?.dataset.uuid) return [];
    return [];
  }

  function selectedIds() {
    const ids = selectedRows().flatMap(rowObjectIds);
    if (ids.length) return ids;
    const fallback = checkoutBtn?.dataset.uuid || openBtn?.dataset.uuid;
    return fallback ? [fallback] : [];
  }

  function selectedOpenSpec() {
    const selected = selectedRows();
    if (selected.length === 1) {
      const row = selected[0];
      if (!row.classList.contains("folder-row")) {
        if (row.dataset.uuid) return { objectId: row.dataset.uuid };
        if (row.dataset.relativePath) {
          return { relativePath: row.dataset.relativePath, projectId: currentProjectId() };
        }
      }
    }
    const ids = selectedIds();
    if (ids.length === 1) return { objectId: ids[0] };
    return null;
  }

  function setToolbarActionVisible(button, visible) {
    if (!button) return;
    // Hide inactive toolbar actions and fly-up items so the bar stays compact.
    button.hidden = !visible;
    button.disabled = !visible;
    const tip = button.closest(".toolbar-tip");
    if (tip) tip.hidden = !visible;
    if (button.classList.contains("toolbar-menu-toggle")) {
      const menu = button.closest(".toolbar-menu");
      if (menu) {
        menu.hidden = !visible;
        if (!visible) {
          menu.classList.remove("is-open");
          const panel = menu.querySelector(".toolbar-menu-panel");
          if (panel) panel.hidden = true;
          button.setAttribute("aria-expanded", "false");
        }
      }
    }
  }

  function isNewFileQueueRow(row) {
    return (
      row.classList.contains("queue-row")
      && Boolean(row.dataset.relativePath)
      && !row.dataset.uuid
    );
  }

  function selectionIsAddOnly(rows) {
    return rows.length > 0 && rows.every(isNewFileQueueRow);
  }

  // UUIDs with vault/local saves waiting to check in (not merely checked out).
  let pendingCheckinIds = new Set();
  let pendingCheckinIdsReady = false;
  let pendingCheckinFetch = 0;

  function rememberPendingCheckinIds(ids, { merge = false } = {}) {
    const next = new Set(
      (merge ? [...pendingCheckinIds] : [])
        .concat(ids || [])
        .map((id) => String(id || "").trim())
        .filter(Boolean)
    );
    pendingCheckinIds = next;
    pendingCheckinIdsReady = true;
    syncModifiedStateLabels();
  }

  function syncModifiedStateLabels() {
    document.querySelectorAll(".object-row, .queue-row").forEach((row) => {
      const stateEl = row.querySelector(".state[data-lifecycle-state], .state[data-state]");
      if (!stateEl) return;
      // Prefer the real lifecycle; never treat display "MODIFIED" as the restore base.
      let base = String(stateEl.dataset.lifecycleState || "").toUpperCase();
      if (!base || base === "MODIFIED") {
        const attr = String(stateEl.getAttribute("data-lifecycle-state") || "").toUpperCase();
        base = attr && attr !== "MODIFIED" ? attr : "IN_WORK";
        stateEl.dataset.lifecycleState = base;
      }
      const uuid = row.dataset.uuid || "";
      const owned = row.dataset.owned === "1" || row.dataset.canCheckin === "1";
      const dirty = Boolean(
        row.dataset.modifiedLocally === "1"
          || (uuid && pendingCheckinIds.has(String(uuid)))
      );
      const td = stateEl.closest("td");
      if (owned && dirty) {
        stateEl.dataset.state = "MODIFIED";
        stateEl.textContent = "Modified";
        if (td) td.title = "Modified";
        writeRowSortState(row, "MODIFIED");
        return;
      }
      stateEl.dataset.state = base;
      const label = titleCaseWords(base);
      stateEl.textContent = label;
      if (td) td.title = label;
      writeRowSortState(row, base);
    });
    reapplyActiveTableSorts();
  }

  async function refreshPendingCheckinIds(projectId) {
    if (!projectId) return;
    const seq = ++pendingCheckinFetch;
    try {
      const ids = [];
      document.querySelectorAll(".object-row[data-modified-locally='1'][data-uuid]").forEach((row) => {
        ids.push(row.dataset.uuid);
      });
      // Paint Modified from SSR flags immediately; agent/vault merge follows.
      if (ids.length) rememberPendingCheckinIds(ids, { merge: true });
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/checkin-preview`);
      if (seq !== pendingCheckinFetch) return;
      if (response.ok) {
        const data = await response.json();
        if (seq !== pendingCheckinFetch) return;
        (data.object_ids || []).forEach((id) => ids.push(id));
      }
      // Same local-cache signal as the New files tab (Creo often saves there first).
      try {
        const [cacheFiles, objects] = await Promise.all([
          listAgentCacheFiles(projectId),
          ensureProjectObjects(projectId),
        ]);
        if (seq !== pendingCheckinFetch) return;
        newerLocalCacheSaves(cacheFiles, objects).forEach((item) => {
          if (item.uuid && item.can_checkin === "1") ids.push(item.uuid);
        });
      } catch {
        /* agent offline — vault/preview ids still apply */
      }
      document.querySelectorAll("#changes-table .queue-row.is-pending[data-uuid]").forEach((row) => {
        if (row.dataset.canCheckin === "0") return;
        ids.push(row.dataset.uuid);
      });
      if (seq !== pendingCheckinFetch) return;
      rememberPendingCheckinIds(ids);
      document.querySelectorAll(".object-row[data-uuid]").forEach((row) => {
        const id = row.dataset.uuid;
        if (!id) return;
        if (pendingCheckinIds.has(String(id))) {
          row.dataset.modifiedLocally = "1";
        }
      });
      syncModifiedStateLabels();
      syncToolbar();
    } catch {
      if (seq !== pendingCheckinFetch) return;
      pendingCheckinIdsReady = true;
      syncModifiedStateLabels();
      syncToolbar();
    }
  }

  function rowHasCheckinWork(row) {
    if (!row) return false;
    if (isNewFileQueueRow(row)) return true;
    if (row.classList.contains("queue-row") && row.dataset.uuid && row.dataset.canCheckin === "1") {
      return true;
    }
    if (row.dataset.canCheckin === "1" && row.dataset.uuid) {
      return (
        row.dataset.modifiedLocally === "1"
        || pendingCheckinIds.has(String(row.dataset.uuid))
      );
    }
    return false;
  }

  function selectionCanCheckin(selected) {
    if (!selected.length) return false;
    if (selectionIsAddOnly(selected)) return true;
    // Every selected row must be something we could check in / add; at least one
    // must actually have work (dirty save or new file) — not just a clean checkout.
    const allEligible = selected.every(
      (row) => row.dataset.canCheckin === "1" || isNewFileQueueRow(row)
    );
    if (!allEligible) return false;
    return selected.some(rowHasCheckinWork);
  }

  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.flatMap(rowObjectIds);
    const canOpenFile = Boolean(selectedOpenSpec());
    const canOpenWorkspace = Boolean(openWorkspaceBtn?.dataset.project);
    const canOpenMenu = canOpenFile || canOpenWorkspace;
    setToolbarActionVisible(openBtn, canOpenFile);
    setToolbarActionVisible(openWorkspaceBtn, canOpenWorkspace);
    setToolbarActionVisible(openMenuBtn, canOpenMenu);
    if (!canOpenMenu) closeOpenMenu();
    const one = selected.length === 1 ? selected[0] : null;
    setToolbarActionVisible(historyBtn, Boolean(rowHistoryHref(one)));
    const canCheckout = selected.length > 0 && selected.every((row) => row.dataset.canCheckout === "1");
    const canCheckin = selectionCanCheckin(selected);
    const canUndo = selected.length > 0 && selected.every((row) => row.dataset.owned === "1");
    const addOnly = selectionIsAddOnly(selected);
    const projectId =
      checkinBtn?.dataset.project ||
      checkinMenuBtn?.dataset.project ||
      openWorkspaceBtn?.dataset.project ||
      currentProjectId() ||
      "";
    const canAdd = Boolean(projectId);
    setToolbarActionVisible(addMenuBtn, canAdd);
    for (const id of ["create-folder-btn", "add-files-btn", "add-folder-btn", "add-folders-btn"]) {
      setToolbarActionVisible($("#" + id), canAdd);
    }
    if (!canAdd) closeAddMenu();
    const canCheckoutProject =
      Boolean(projectId) &&
      Number(checkoutProjectBtn?.dataset.checkoutable || 0) > 0;
    const pendingProjectSaves = Number(
      checkinBtn?.dataset.pendingSaves || checkinMenuBtn?.dataset.pendingSaves || 0
    );
    const pendingProjectNew = Number(
      checkinBtn?.dataset.newFiles || checkinMenuBtn?.dataset.newFiles || 0
    );
    const projectCheckoutCount = Number(
      checkinProjectBtn?.dataset.checkoutCount || checkinMenuBtn?.dataset.checkoutCount || 0
    );
    // Project check-in when there is queue work and/or active checkouts to release.
    const canCheckinProject =
      Boolean(projectId) &&
      (pendingProjectSaves > 0 || pendingProjectNew > 0 || projectCheckoutCount > 0);
    const canCheckoutMenu = canCheckout || canCheckoutProject || canUndo;
    setToolbarActionVisible(checkoutBtn, canCheckout);
    setToolbarActionVisible(checkoutProjectBtn, canCheckoutProject);
    if (checkoutProjectBtn) {
      checkoutProjectBtn.title = canCheckoutProject
        ? "Check out every file in this project that is available (not locked by someone else)."
        : "Nothing left to check out in this project.";
    }
    setToolbarActionVisible(undoBtn, canUndo);
    setToolbarActionVisible(checkoutMenuBtn, canCheckoutMenu);
    if (!canCheckoutMenu) closeCheckoutMenu();
    if (checkinBtn) {
      checkinBtn.textContent = addOnly ? "Add selected…" : "Check in selected…";
      checkinBtn.title = addOnly
        ? "Add selected new files to the project (uploads local workspace files first)."
        : canCheckin
          ? "Check in selected files."
          : selected.some((row) => row.dataset.canCheckin === "1")
            ? "Nothing to check in for this selection. Save changes in Creo first, or use Undo Checkout to release locks."
            : "Check in selected files.";
    }
    setToolbarActionVisible(checkinBtn, canCheckin);
    setToolbarActionVisible(checkinProjectBtn, canCheckinProject);
    if (checkinProjectBtn) {
      checkinProjectBtn.title = canCheckinProject
        ? "Check in modified files and new files, and release unchanged checkouts so the project looks fully checked in."
        : "Nothing to check in for this project. Check out and save changes, or add new files first.";
    }
    const canCheckinMenu = canCheckin || canCheckinProject;
    setToolbarActionVisible(checkinMenuBtn, canCheckinMenu);
    if (!canCheckinMenu) closeCheckinMenu();
    setToolbarActionVisible(
      workspaceBtn,
      selected.some((row) => row.dataset.inWorkspace !== "1")
    );
    const localNewSelected = selected.filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache === "1"
    );
    const vaultNewSelected = selected.filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache !== "1"
    );
    const canDiscardLocal = localNewSelected.length > 0;
    const canPurge =
      vaultNewSelected.length > 0 ||
      selected.some((row) => row.dataset.uuid && row.dataset.inWorkspace !== "0");
    const folderPaths = selectedFolderPaths();
    const canRemoveProject = ids.length > 0 || folderPaths.length > 0;
    const canPurgeVersions = Boolean(
      purgeVersionsBtn?.dataset.project || openWorkspaceBtn?.dataset.project || checkinBtn?.dataset.project
    );
    const canRemoveMenu = canDiscardLocal || canPurge || canRemoveProject || canPurgeVersions;
    setToolbarActionVisible(discardLocalBtn, canDiscardLocal);
    setToolbarActionVisible(purgeBtn, canPurge);
    setToolbarActionVisible(purgeVersionsBtn, canPurgeVersions);
    setToolbarActionVisible(removeBtn, canRemoveProject);
    setToolbarActionVisible(removeMenuBtn, canRemoveMenu);
    if (!canRemoveMenu) closeRemoveMenu();
    const filtering = metricButtons().some((btn) => metricMode(btn) === "filter");
    const summary = $("#selection-summary");
    if (summary) {
      const count = selected.length || ids.length;
      if (count) {
        summary.classList.add("is-active");
        summary.textContent = `${count} selected${filtering ? ". The list is filtered" : ""}.`;
      } else {
        summary.classList.remove("is-active");
        // Keep a non-breaking space so the reserved line height stays stable.
        summary.textContent = "\u00a0";
      }
    }
  }

  function setCheckinQueueCounts(pendingSaves, newFiles) {
    for (const el of [checkinBtn, checkinMenuBtn]) {
      if (!el) continue;
      el.dataset.pendingSaves = String(pendingSaves || 0);
      el.dataset.newFiles = String(newFiles || 0);
    }
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (tab) {
      const pending = Number(pendingSaves || 0) + Number(newFiles || 0);
      tab.textContent = pending ? `New files · ${pending}` : "New files";
    }
    syncToolbar();
  }

  function setCheckedOutTabCount(count) {
    const tab = document.querySelector('.tab[data-tab="checked-out"]');
    if (!tab) return;
    const n = Number(count) || 0;
    tab.textContent = n ? `Files checked out · ${n}` : "Files checked out";
    if (checkinProjectBtn) checkinProjectBtn.dataset.checkoutCount = String(n);
    if (checkinMenuBtn) checkinMenuBtn.dataset.checkoutCount = String(n);
  }

  function setCheckoutableCount(count) {
    if (checkoutProjectBtn) checkoutProjectBtn.dataset.checkoutable = String(Number(count) || 0);
    syncToolbar();
  }

  function snapshotMetricModes() {
    return metricButtons().map((btn) => ({ btn, mode: metricMode(btn) }));
  }

  function restoreMetricModes(snapshot) {
    let changed = false;
    (snapshot || []).forEach(({ btn, mode }) => {
      if (!btn || metricMode(btn) === mode) return;
      setMetricMode(btn, mode);
      changed = true;
    });
    return changed;
  }

  function afterRowSelectionChange(snapshot) {
    // Row clicks must never clear an active pill.
    restoreMetricModes(snapshot);
    if (metricSelectionActive()) {
      applyMetricVisibility();
      applyMetricSelection();
    }
    syncToolbar();
  }

  function toggleRow(row) {
    const snapshot = snapshotMetricModes();
    if (row.classList.contains("folder-row")) {
      markRowSelected(row, !row.classList.contains("is-selected"));
      lastSelectRow = row;
      syncToolbar();
      return;
    }
    // While a pill is sticky, ignore ctrl-toggle so the group stays selected.
    if (metricSelectionActive()) {
      lastSelectRow = row;
      afterRowSelectionChange(snapshot);
      return;
    }
    markRowSelected(row, !row.classList.contains("is-selected"));
    lastSelectRow = row;
    afterRowSelectionChange(snapshot);
  }

  function selectOnly(row) {
    const snapshot = snapshotMetricModes();
    lastSelectRow = row;
    // Folder click always selects that folder (Remove / Checkout); metrics apply to files only.
    if (row.classList.contains("folder-row")) {
      rows().forEach((item) => markRowSelected(item, item === row));
      syncToolbar();
      return;
    }
    // Sticky pill: keep filtered/selected group; do not collapse to one row.
    if (metricSelectionActive()) {
      afterRowSelectionChange(snapshot);
      return;
    }
    rows().forEach((item) => markRowSelected(item, item === row));
    afterRowSelectionChange(snapshot);
  }

  function selectRange(toRow, additive = false) {
    const snapshot = snapshotMetricModes();
    // Sticky pill: range clicks keep the metric group, not a custom range.
    // Folder rows still use normal range selection (Remove / bulk).
    if (
      metricSelectionActive()
      && !toRow.classList.contains("folder-row")
      && !(lastSelectRow && lastSelectRow.classList.contains("folder-row"))
    ) {
      lastSelectRow = toRow;
      afterRowSelectionChange(snapshot);
      return;
    }
    const visible = rows().filter((row) => !rowIsHidden(row));
    const end = visible.indexOf(toRow);
    const start = lastSelectRow ? visible.indexOf(lastSelectRow) : end;
    if (end < 0) return;
    const from = start < 0 ? end : Math.min(start, end);
    const until = start < 0 ? end : Math.max(start, end);
    if (!additive) {
      visible.forEach((row) => markRowSelected(row, false));
    }
    visible.slice(from, until + 1).forEach((row) => markRowSelected(row, true));
    lastSelectRow = toRow;
    if (metricSelectionActive() && !toRow.classList.contains("folder-row")) {
      afterRowSelectionChange(snapshot);
      return;
    }
    syncToolbar();
  }

  let lastSelectRow = null;
  let pendingOpen = 0;

  function cancelPendingOpen() {
    if (pendingOpen) {
      window.clearTimeout(pendingOpen);
      pendingOpen = 0;
    }
  }

  function openSpecFromRow(row, openLink) {
    if (!row || row.classList.contains("folder-row")) return null;
    const uuid = openLink?.dataset?.uuid || row.dataset.uuid || "";
    if (uuid) return { objectId: uuid };
    const relativePath = openLink?.dataset?.relativePath || row.dataset.relativePath || "";
    if (relativePath) return { relativePath, projectId: currentProjectId() };
    return null;
  }

  function stateSortToken(state) {
    const s = String(state || "")
      .toUpperCase()
      .replace(/\s+/g, "_")
      .replace(/^\d+-/, "");
    if (!s) return "9-";
    // First ascending click should put dirty work at the top.
    if (s === "MODIFIED") return "0-MODIFIED";
    if (s === "IN_WORK") return "1-IN_WORK";
    return `2-${s}`;
  }

  function rowDisplayState(row) {
    const stateEl = row.querySelector(".state[data-state]");
    const live = String(stateEl?.getAttribute("data-state") || "").toUpperCase();
    if (live) return live.replace(/^\d+-/, "");
    const raw = String(row.dataset.sortState || "");
    const leaf = raw.includes("/") ? raw.slice(raw.lastIndexOf("/") + 1) : raw;
    return leaf.toUpperCase().replace(/^\d+-/, "");
  }

  function writeRowSortState(row, state) {
    if (!row || row.classList.contains("folder-row")) return;
    const tree = row.dataset.tree || "";
    const token = stateSortToken(state);
    row.dataset.sortState = tree ? `${tree}/${token}` : token;
  }

  function sortValue(row, key, columnIndex) {
    if (key === "state") {
      if (row.classList.contains("folder-row")) {
        const folder = row.dataset.folder || "";
        return folder ? `${folder}/` : String(row.dataset.sortState || "");
      }
      const state = rowDisplayState(row);
      const tree = row.dataset.tree || "";
      const token = stateSortToken(state);
      return tree ? `${tree}/${token}` : token;
    }
    const dataKey = `sort${key.charAt(0).toUpperCase()}${key.slice(1)}`;
    const fromData = row.dataset[dataKey];
    if (fromData !== undefined && fromData !== "") return fromData;
    const cell = row.children[columnIndex];
    return cell ? cell.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function reapplyActiveTableSorts() {
    document.querySelectorAll("table.grid").forEach((table) => {
      const th = table.querySelector(
        'th[data-sort][aria-sort="ascending"], th[data-sort][aria-sort="descending"]'
      );
      if (!th) return;
      const dir = th.getAttribute("aria-sort") === "descending" ? "desc" : "asc";
      applyTableSort(table, th.dataset.sort, dir);
    });
  }

  function currentProjectId() {
    const fromPath = String(window.location.pathname || "").match(
      /\/projects\/([0-9a-f-]{36})\//i
    );
    return (
      $("#rename-project-btn")?.dataset.project ||
      $("#delete-project-btn")?.dataset.project ||
      $("#collect-metadata-btn")?.dataset.project ||
      $("#rebuild-where-used-btn")?.dataset.project ||
      $("#open-workspace-btn")?.dataset.project ||
      $("#checkin-btn")?.dataset.project ||
      document.getElementById("metric-filters")?.dataset?.project ||
      (fromPath && fromPath[1]) ||
      new URLSearchParams(window.location.search).get("project") ||
      ""
    );
  }

  function currentVaultFolder() {
    const raw =
      document.getElementById("metric-filters")?.dataset?.vaultFolder ||
      $("#open-workspace-btn")?.dataset?.vaultFolder ||
      "";
    return String(raw || "").trim() || currentProjectId();
  }

  function agentProjectFields() {
    return {
      project_id: currentProjectId() || null,
      vault_folder: currentVaultFolder() || "",
    };
  }

  function sortStoreKey(table) {
    const project = currentProjectId();
    const tableId = table.id || "";
    if (!project || !tableId) return "";
    return `creopdm.sort.${project}.${tableId}`;
  }

  function readStoredSort(table) {
    const key = sortStoreKey(table);
    if (!key) return null;
    try {
      const parsed = JSON.parse(localStorage.getItem(key) || "null");
      if (!parsed || typeof parsed.key !== "string") return null;
      return { key: parsed.key, dir: parsed.dir === "desc" ? "desc" : "asc" };
    } catch {
      return null;
    }
  }

  function currentFolder() {
    return document.querySelector("#panel-files")?.dataset.folder || "";
  }

  function filterStoreKey(folder) {
    const project = currentProjectId();
    if (!project) return "";
    return `creopdm.filters.${project}.${folder}`;
  }

  function readStoredFilters() {
    const project = currentProjectId();
    if (!project) return null;
    const keys = [filterStoreKey(currentFolder()), filterStoreKey("_last")];
    for (const key of keys) {
      if (!key) continue;
      try {
        const parsed = JSON.parse(localStorage.getItem(key) || "null");
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) return parsed;
      } catch {
        /* ignore */
      }
    }
    return null;
  }

  function writeStoredFilters() {
    const project = currentProjectId();
    if (!project) return;
    const modes = {};
    metricButtons().forEach((btn) => {
      const name = metricKey(btn);
      const mode = metricMode(btn);
      if (name) modes[name] = mode;
    });
    const payload = JSON.stringify(modes);
    try {
      localStorage.setItem(filterStoreKey(currentFolder()), payload);
      localStorage.setItem(filterStoreKey("_last"), payload);
    } catch {
      /* quota / private mode */
    }
  }

  function restoreStoredFilters() {
    const saved = readStoredFilters();
    if (!saved) return;
    let applied = false;
    metricButtons().forEach((btn) => {
      let mode = saved[metricKey(btn)];
      // Old three-click "select" mode → sticky filter.
      if (mode === "select") mode = "filter";
      if (mode !== "filter" && mode !== "off") return;
      setMetricMode(btn, mode);
      applied = true;
    });
    const files = metricButtons().find((btn) => metricKey(btn) === "files");
    if (files && metricMode(files) !== "off") {
      metricButtons().forEach((item) => {
        if (item !== files && !isCheckoutMetric(metricKey(item))) setMetricMode(item, "off");
      });
    }
    const cadModels = metricButtons().find((btn) => metricKey(btn) === "cad_models");
    if (cadModels && metricMode(cadModels) !== "off") clearMetricFilters(CAD_MODEL_CHILD_FILTERS);
    if (!applied) return;
    applyMetricVisibility();
    applyMetricSelection();
  }

  function clearProjectViewStorage(projectId) {
    if (!projectId) return;
    const prefixes = [`creopdm.filters.${projectId}.`, `creopdm.sort.${projectId}.`];
    const remove = [];
    try {
      for (let index = 0; index < localStorage.length; index += 1) {
        const key = localStorage.key(index);
        if (key && prefixes.some((prefix) => key.startsWith(prefix))) remove.push(key);
      }
      remove.forEach((key) => localStorage.removeItem(key));
    } catch {
      /* private mode */
    }
  }

  function writeStoredSort(table, key, dir) {
    const storeKey = sortStoreKey(table);
    if (!storeKey) return;
    try {
      localStorage.setItem(storeKey, JSON.stringify({ key, dir }));
    } catch {
      /* quota / private mode */
    }
  }

  function applyTableSort(table, key, dir) {
    const heads = [...table.querySelectorAll("th[data-sort]")];
    const th = heads.find((item) => item.dataset.sort === key);
    if (!th) return;
    heads.forEach((item) => {
      const active = item === th;
      item.setAttribute("aria-sort", active ? (dir === "asc" ? "ascending" : "descending") : "none");
    });
    const tbody = table.tBodies[0];
    if (!tbody) return;
    const columnIndex = [...th.parentElement.children].indexOf(th);
    const pending = [...tbody.querySelectorAll("tr.is-pending")];
    const empty = [...tbody.querySelectorAll("tr.empty-row")];
    const sortable = [...tbody.rows].filter(
      (row) => !row.classList.contains("is-pending") && !row.classList.contains("empty-row")
    );
    sortable.sort((a, b) => {
      const left = sortValue(a, key, columnIndex);
      const right = sortValue(b, key, columnIndex);
      let cmp = 0;
      try {
        cmp = left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
      } catch {
        cmp = left.localeCompare(right);
      }
      return dir === "asc" ? cmp : -cmp;
    });
    [...pending, ...sortable, ...empty].forEach((row) => tbody.appendChild(row));
  }

  function enableTableSort(table) {
    const heads = [...table.querySelectorAll("th[data-sort]")];
    if (!heads.length) return;
    table.tHead?.addEventListener("click", (event) => {
      const th = eventEl(event)?.closest("th[data-sort]");
      if (!th || !table.contains(th)) return;
      event.preventDefault();
      const key = th.dataset.sort;
      const next = th.getAttribute("aria-sort") === "ascending" ? "desc" : "asc";
      applyTableSort(table, key, next);
      writeStoredSort(table, key, next);
    });
    const saved = readStoredSort(table);
    if (saved) applyTableSort(table, saved.key, saved.dir);
  }

  document.querySelectorAll("table.grid").forEach(enableTableSort);

  function openFolderRow(folder) {
    if (!folder) return;
    const link = folder.matches?.("a.folder-open")
      ? folder
      : folder.querySelector?.("a.folder-open");
    const href = link?.getAttribute?.("href") || "";
    if (href) {
      leavePage(href);
      return;
    }
    const projectId = currentProjectId();
    const path =
      folder.dataset?.folder
      || folder.querySelector?.(".folder-open")?.dataset?.folder
      || "";
    if (projectId && path) {
      leavePage(`/?project=${encodeURIComponent(projectId)}&folder=${encodeURIComponent(path)}`);
    }
  }

  function onFileTableClick(event) {
    const target = eventEl(event);
    const folderRow = target?.closest?.(".folder-row") || null;
    // Folder name link always opens; click elsewhere on the row selects (Remove, etc.).
    if (folderRow) {
      const folderLink = target?.closest?.("a.folder-open");
      if (folderLink && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
        event.preventDefault();
        event.stopPropagation();
        cancelPendingOpen();
        openFolderRow(folderRow);
        return;
      }
      // Stop soft-nav / default so a non-link click keeps the row selected.
      event.preventDefault();
      event.stopPropagation();
      cancelPendingOpen();
      if (event.shiftKey) {
        selectRange(folderRow, event.ctrlKey || event.metaKey);
        return;
      }
      if (event.ctrlKey || event.metaKey) {
        toggleRow(folderRow);
        return;
      }
      selectOnly(folderRow);
      return;
    }
    const row = target?.closest(".object-row, .queue-row");
    if (!row) return;
    const openLink = target?.closest(".object-open");
    if (openLink) event.preventDefault();
    if (event.shiftKey) {
      event.preventDefault();
      cancelPendingOpen();
      selectRange(row, event.ctrlKey || event.metaKey);
      return;
    }
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      cancelPendingOpen();
      toggleRow(row);
      return;
    }
    selectOnly(row);
    if (!openLink) {
      cancelPendingOpen();
      return;
    }
    const spec = openSpecFromRow(row, openLink);
    if (!spec) return;
    cancelPendingOpen();
    // Delay so a double-click can cancel and open History instead.
    pendingOpen = window.setTimeout(() => {
      pendingOpen = 0;
      void openPdmObjectFromUi(spec, row);
    }, 280);
  }

  function onFileTableDblclick(event) {
    cancelPendingOpen();
    const target = eventEl(event);
    // Double-click opens the folder (name or anywhere on the row).
    const folder = target?.closest?.(".folder-row");
    if (folder) {
      event.preventDefault();
      openFolderRow(folder);
      return;
    }
    const row = target?.closest(".object-row, .queue-row");
    const href = rowHistoryHref(row);
    if (!href) return;
    event.preventDefault();
    if (target?.closest(".object-open")) event.preventDefault();
    window.location.href = href;
  }

  function rowHistoryHref(row) {
    if (!row) return "";
    if (row.dataset.detail) return row.dataset.detail;
    const uuid = row.dataset.uuid;
    if (!uuid) return "";
    const projectId = currentProjectId();
    if (!projectId) return "";
    return `/projects/${projectId}/objects/${uuid}#history`;
  }

  document.querySelector("#object-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#object-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#checked-out-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#checked-out-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#changes-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#changes-table")?.addEventListener("dblclick", onFileTableDblclick);

  function onMetricChip(event) {
    const btn = eventEl(event)?.closest(".metric");
    if (!btn || btn.disabled) return;
    event.preventDefault();
    event.stopPropagation();
    if (typeof event.stopImmediatePropagation === "function") event.stopImmediatePropagation();
    const current = metricMode(btn);
    const key = metricKey(btn);
    // One click = sticky filter (list filtered + matching rows selected). Click again clears.
    const next = current === "filter" || current === "select" ? "off" : "filter";
    setMetricMode(btn, next);
    if (key === "files" && next !== "off") {
      metricButtons().forEach((item) => {
        if (item !== btn && !isCheckoutMetric(metricKey(item))) setMetricMode(item, "off");
      });
    }
    if (key !== "files" && !isCheckoutMetric(key) && next !== "off") {
      clearMetricFilters(new Set(["files"]));
    }
    if (key === "cad_models" && next !== "off") {
      clearMetricFilters(CAD_MODEL_CHILD_FILTERS);
    }
    if (next !== "off" && CAD_MODEL_CHILD_FILTERS.has(key)) {
      clearMetricFilters(new Set(["cad_models"]));
    }
    if (next === "off") {
      rows().forEach((row) => markRowSelected(row, false));
      lastSelectRow = null;
    }
    applyMetricVisibility();
    applyMetricSelection();
    writeStoredFilters();
    updateMetricCounts();
    syncToolbar();
  }

  document.querySelector("#metric-filters")?.addEventListener("click", onMetricChip, true);
  document.querySelector("#metric-filters")?.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const btn = eventEl(event)?.closest(".metric");
    if (!btn) return;
    event.preventDefault();
    onMetricChip(event);
  });

  async function postAction(url, body, method = "POST", busyMessage = "Working…") {
    showError($("#toolbar-error"), "");
    showOk("");
    const run = async () => {
      const response = await fetch(url, {
        method,
        headers: body ? { "Content-Type": "application/json" } : undefined,
        body: body ? JSON.stringify(body) : undefined,
      });
      if (!response.ok) {
        showError($("#toolbar-error"), await readError(response));
        return null;
      }
      if (response.status === 204) return {};
      return response.json();
    };
    if (!busyMessage) return run();
    return withBusy(busyMessage, run);
  }

  function formatBatch(result) {
    const failed = result?.failed || [];
    if (!failed.length) return "";
    return failed.map((item) => `${item.filename || item.uuid}: ${item.message}`).join(" ");
  }

  function creoOpenMode() {
    const el = $("#creo-status");
    return String(el?.dataset?.creoOpenMode || "").trim().toLowerCase();
  }

  function creoExternalBridge() {
    try {
      return !!(window.external && window.external.ptc);
    } catch {
      return false;
    }
  }

  function hostedCreoJS() {
    try {
      if (!window.CreoJS) return false;
      // Live PTC bridge — preferred over creojs.js's one-shot isAvailable flag.
      if (creoExternalBridge()) return true;
      if (typeof window.CreoJS.isAvailable === "function") {
        if (Boolean(window.CreoJS.isAvailable())) return true;
      }
      // Chromium Creo often omits external.ptc / isAvailable while the session is live.
      try {
        if (typeof pfcGetCurrentSession === "function" && pfcGetCurrentSession()) {
          return true;
        }
      } catch {
        /* not in a Creo session */
      }
      return false;
    } catch {
      return false;
    }
  }

  function canGatherCreoMetadata() {
    try {
      if (!window.CreoJS) return false;
      if (typeof window.CreoJS.gatherModelMetadata !== "function") return false;
      // Require a real Creo.JS bridge — Embedded mode alone is not enough
      // (Chrome with settings=Embedded must not pretend to gather).
      return hostedCreoJS();
    } catch {
      return false;
    }
  }

  async function waitForCreoMetadataBridge({ tries = 40, intervalMs = 250 } = {}) {
    await creoJSReady;
    if (canGatherCreoMetadata()) return true;
    for (let i = 0; i < tries && !canGatherCreoMetadata(); i += 1) {
      await new Promise((r) => window.setTimeout(r, intervalMs));
    }
    return canGatherCreoMetadata();
  }

  function isCreoMetadataCandidate(filename) {
    const base = String(filename || "");
    const logical = base.replace(/\.(\d+)$/i, "");
    return /\.(prt|asm|drw|frm|mfg|lay|sec|dgm|rep)$/i.test(logical);
  }

  function looksLikeLocalWindowsPath(path) {
    const text = String(path || "").trim();
    return /^[a-zA-Z]:[\\/]/.test(text) || text.startsWith("\\\\");
  }

  async function prepareLocalPathForMetadata(objectId) {
    if (!objectId) return null;
    try {
      const response = await fetch("/api/creo/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          object_id: objectId,
          launch: false,
          include_companions: true,
        }),
      });
      if (!response.ok) return null;
      const prepared = await response.json();
      const agent = await probeCreoAgent();
      if (!agent) {
        const dir = String(prepared.working_directory || prepared.directory || "").trim();
        const name = String(prepared.disk_name || prepared.filename || "").trim();
        if (dir && name && looksLikeLocalWindowsPath(dir)) {
          return `${dir.replace(/[\\/]+$/, "")}\\${name}`;
        }
        return null;
      }
      const openSpec = await materializeViaAgent(prepared);
      const workdir = String(openSpec.working_directory || "").trim();
      const diskName = String(openSpec.disk_name || openSpec.filename || "").trim();
      if (workdir && diskName) {
        return `${workdir.replace(/[\\/]+$/, "")}\\${diskName}`;
      }
      return null;
    } catch {
      return null;
    }
  }

  async function gatherCreoMetadataForFilename(filename, filePath) {
    if (!canGatherCreoMetadata() || !filename) return null;
    try {
      await whenCreoJSReady();
      if (typeof window.CreoJS.gatherModelMetadata !== "function") return null;
      const snapshot = await window.CreoJS.gatherModelMetadata(filename, filePath || "");
      if (!snapshot || typeof snapshot !== "object") return null;
      if (typeof snapshot === "string" && snapshot.startsWith("CREOPDM_ERROR:")) return null;
      if (snapshot.__error) {
        return {
          __error: String(snapshot.__error || "gather_failed"),
          __detail: String(snapshot.__detail || ""),
        };
      }
      const eraseKeys = Array.isArray(snapshot._pdm_erase_keys)
        ? snapshot._pdm_erase_keys.filter((name) => typeof name === "string" && name.trim())
        : [];
      delete snapshot._pdm_erase_keys;
      // PTC defers Erase until Creo regains control — must be a separate Creo.JS turn.
      if (eraseKeys.length && typeof window.CreoJS.eraseSessionModelsByNames === "function") {
        try {
          // Named Erase only — EraseUndisplayedModels spams the Creo message area
          // during bulk Collect metadata.
          await window.CreoJS.eraseSessionModelsByNames(eraseKeys, { allowUndisplayed: false });
        } catch {
          /* best-effort session cleanup */
        }
      }
      return snapshot;
    } catch {
      return null;
    }
  }

  async function pushCreoMetadataForItems(items) {
    const targets = (items || [])
      .map((item) => ({
        uuid: String(item?.uuid || item?.object_id || "").trim(),
        filename: String(item?.filename || "").trim(),
        path: String(item?.path || "").trim(),
        versionId: String(item?.version_id || item?.current_version?.uuid || "").trim(),
      }))
      .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename));
    if (!targets.length || !canGatherCreoMetadata()) return;
    for (const target of targets) {
      let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
      if (!filePath) {
        filePath = (await prepareLocalPathForMetadata(target.uuid)) || "";
      }
      const snapshot = await gatherCreoMetadataForFilename(target.filename, filePath);
      if (!snapshot) continue;
      const body = {
        version_id: target.versionId || null,
        identity: snapshot.identity || null,
        parameters: Array.isArray(snapshot.parameters) ? snapshot.parameters : [],
        materials: snapshot.materials || null,
        dependencies: Array.isArray(snapshot.dependencies) ? snapshot.dependencies : [],
        bom: snapshot.bom || null,
        units: snapshot.units || null,
        family_table: snapshot.family_table || null,
        features: Array.isArray(snapshot.features) && snapshot.features.length
          ? snapshot.features
          : null,
      };
      try {
        await fetch(`/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
      } catch {
        /* soft-fail — metadata is best-effort */
      }
    }
  }

  function metadataTargetsFromResult(result) {
    if (!result) return [];
    if (Array.isArray(result.ok)) {
      return result.ok
        .filter((item) => item && item.uuid && item.filename)
        .map((item) => ({
          uuid: item.uuid,
          filename: item.filename,
          path: item.path || "",
          version_id: item.version_id || "",
          current_version: item.current_version || null,
        }));
    }
    if (result.uuid && result.filename) {
      return [
        {
          uuid: result.uuid,
          filename: result.filename,
          path: result.path || "",
          version_id: result.current_version?.uuid || "",
          current_version: result.current_version || null,
        },
      ];
    }
    return [];
  }

  function whenCreoJSReady() {
    return new Promise((resolve, reject) => {
      try {
        if (typeof window.CreoJS.$ADD_ON_LOAD === "function") {
          window.CreoJS.$ADD_ON_LOAD(resolve);
          return;
        }
        resolve();
      } catch (err) {
        reject(err);
      }
    });
  }

  async function refreshCreoStatusPill(prefetchedAgent) {
    // Soft folder/project swap — never flash Session offline / Not Connected.
    if (window.__creopdmSoftNavBusy || softNavBusy) return null;
    const inSession = hostedCreoJS();
    document.querySelectorAll(".creo-session-only").forEach((el) => {
      // Keep Set Working Directory in the toolbar (greyed when unusable) so it
      // stays discoverable; other inactive toolbar actions stay hidden.
      el.hidden = false;
      const btn = el.tagName === "BUTTON" ? el : el.querySelector("button");
      if (!btn) return;
      btn.hidden = false;
      if (!inSession) {
        btn.disabled = true;
        return;
      }
      if (btn.id === "set-creo-dir-btn") {
        btn.disabled = !btn.dataset.workspace;
      } else {
        btn.disabled = false;
      }
    });
    const pill = $("#creo-status");
    if (!pill) return null;
    const modeKey = creoOpenMode() || "association";
    const modeName = modeKey === "embedded" ? "Embedded" : modeKey === "association" ? "OS" : modeKey;
    if (modeKey === "embedded") {
      const agent =
        prefetchedAgent !== undefined ? prefetchedAgent : await probeCreoAgent();
      // Transient bridge flake during nav — keep Connected while CreoJS is still present.
      if (
        !inSession &&
        pill.dataset.state === "ok" &&
        window.CreoJS &&
        agent
      ) {
        return agent;
      }
      if (inSession && agent) {
        pill.textContent = `Creo: Connected · ${modeName}`;
        pill.dataset.state = "ok";
        pill.title = "Creo.JS session linked. Local creopdm-agent is running.";
      } else if (inSession && !agent) {
        pill.textContent = `Creo: Agent offline · ${modeName}`;
        pill.dataset.state = "idle";
        pill.title =
          "Creo.JS session is linked, but creopdm-agent is not running on this PC. Start creopdm-agent-tray for Embedded open.";
      } else if (!inSession && agent) {
        // Agent health ≠ Creo.JS. SSR often says Not Connected from the Linux host.
        pill.textContent = `Creo: Session offline · ${modeName}`;
        pill.dataset.state = "idle";
        pill.title =
          "creopdm-agent is running, but this page has no Creo.JS bridge (window.external.ptc). Open CreoPDM inside Creo's embedded browser — not Chrome/Edge — then hard-refresh.";
      } else {
        pill.textContent = `Creo: Not Connected · ${modeName}`;
        pill.dataset.state = "idle";
        pill.title =
          "No Creo.JS bridge and creopdm-agent is offline. Open CreoPDM in Creo's embedded browser and start the agent tray.";
      }
      return agent;
    }
    if (inSession) {
      pill.textContent = `Creo: Connected · ${modeName}`;
      pill.dataset.state = "ok";
      pill.title = "Creo.JS session linked (OS open mode).";
    } else {
      pill.textContent = `Creo: Not Connected · ${modeName}`;
      pill.dataset.state = "idle";
      pill.title = "Opens Creo models as a browser download for the OS association";
    }
    return null;
  }

  function showCreoSessionControls() {
    void refreshCreoStatusPill();
  }

  function syncCreoSessionControlsFromBridge() {
    /** Soft nav only: re-enable toolbar Creo buttons. Do not probe or touch the pill. */
    const inSession = hostedCreoJS();
    document.querySelectorAll(".creo-session-only").forEach((el) => {
      el.hidden = false;
      const btn = el.tagName === "BUTTON" ? el : el.querySelector("button");
      if (!btn) return;
      btn.hidden = false;
      if (!inSession) {
        btn.disabled = true;
        return;
      }
      if (btn.id === "set-creo-dir-btn") {
        btn.disabled = !btn.dataset.workspace;
      } else {
        btn.disabled = false;
      }
    });
  }

  // Soft folder/project switches keep the live Creo.JS bridge and header status
  // pill (both live outside main.shell). Never re-probe agent or reconnect.
  if (soft) {
    syncCreoSessionControlsFromBridge();
  } else {
  void creoJSReady.then(() => {
    void (async () => {
      // CREOPDM_STATUS_POLL_V2: at most one /health on load; repeat only if agent says > 0.
      const modeKey = creoOpenMode() || "association";
      let agent = null;
      if (modeKey === "embedded") {
        agent = await probeCreoAgent();
        await refreshCreoStatusPill(agent);
      } else {
        await refreshCreoStatusPill(null);
      }
      // First load: Creo.JS bridge can appear after first paint — re-check a few times.
      if (!hostedCreoJS()) {
        let bridgeTries = 0;
        const bridgePoll = trackedInterval(() => {
          bridgeTries += 1;
          if (hostedCreoJS() || bridgeTries >= 40) {
            window.clearInterval(bridgePoll);
            void refreshCreoStatusPill(agent);
          }
        }, 250);
      }
      let seconds = 0;
      if (agent && Object.prototype.hasOwnProperty.call(agent, "status_poll_interval_seconds")) {
        const parsed = Number(agent.status_poll_interval_seconds);
        seconds = Number.isFinite(parsed) ? parsed : 0;
      }
      if (modeKey === "embedded" && seconds > 0 && !window.__creopdmStatusPollId) {
        const interval = Math.min(120000, Math.max(1000, Math.round(seconds * 1000)));
        // Survive soft folder/project boots (those abort pageIntervals).
        window.__creopdmStatusPollId = window.setInterval(() => {
          if (window.__creopdmSoftNavBusy) return;
          void refreshCreoStatusPill();
        }, interval);
      }
    })();
  });
  }

  async function agentWorkdir(projectId, vaultFolder) {
    const params = new URLSearchParams();
    if (projectId) params.set("project_id", projectId);
    const folder = vaultFolder || currentVaultFolder();
    if (folder) params.set("vault_folder", folder);
    const query = params.toString() ? `?${params}` : "";
    const response = await fetch(`${agentBase()}/workdir${query}`, { method: "GET" });
    if (!response.ok) {
      throw new Error("Local CreoPDM agent could not provide a cache folder.");
    }
    const body = await response.json();
    if (!body || !body.path) {
      throw new Error("Local CreoPDM agent returned no cache path.");
    }
    return String(body.path);
  }

  async function setCreoWorkingDirectory() {
    try {
      await creoJSReady;
      if (!hostedCreoJS()) {
        showError($("#toolbar-error"), "Open this page in Creo's built-in browser to set the working directory.");
        return;
      }
      if (window.CreoJS && typeof window.CreoJS === "object") {
        window.CreoJS.$ONEXCEPTION = function (exc) {
          const raw = exc && exc.message ? String(exc.message) : "";
          const text =
            raw && raw !== "{}" && raw !== "[object Object]"
              ? raw
              : "Creo could not complete that command.";
          showError($("#toolbar-error"), text);
        };
      }
      const agent = await probeCreoAgent();
      if (!agent) {
        showError(
          $("#toolbar-error"),
          "Start creopdm-agent on this Creo PC, then try Set Working Directory again."
        );
        return;
      }
      const directory = await agentWorkdir(currentProjectId(), currentVaultFolder());
      await whenCreoJSReady();
      const result = await window.CreoJS.setWorkingDirectory(directory);
      const text = result == null ? "" : String(result);
      if (text.indexOf("CREOPDM_ERROR:") === 0) {
        showError($("#toolbar-error"), text.slice("CREOPDM_ERROR:".length));
        return;
      }
      showOk("Creo working directory set to the local agent cache.");
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      if (!message || message === "[object Object]" || message === "{}") {
        showError(
          $("#toolbar-error"),
          "Creo could not change the working directory. Check that creopdm-agent is running."
        );
        return;
      }
      showError($("#toolbar-error"), message || "Creo could not change directory.");
    }
  }
  setCreoDirBtn?.addEventListener("click", () => {
    void setCreoWorkingDirectory();
  });

  function openRequestBody(target, launch, includeCompanions) {
    const spec = typeof target === "string" ? { objectId: target } : target || {};
    const body = { launch: Boolean(launch) };
    if (includeCompanions !== undefined) body.include_companions = Boolean(includeCompanions);
    if (spec.objectId) {
      body.object_id = spec.objectId;
      return body;
    }
    body.project_id = spec.projectId || currentProjectId();
    body.relative_path = spec.relativePath;
    return body;
  }

  function openTargetObjectId(target) {
    if (typeof target === "string") return target;
    return target?.objectId || "";
  }

  function openTargetFilename(target, row) {
    if (row?.dataset?.filename) return row.dataset.filename;
    if (typeof target === "string") {
      const match = rows().find((item) => item.dataset.uuid === target);
      if (match?.dataset?.filename) return match.dataset.filename;
      return target;
    }
    if (target?.relativePath) return String(target.relativePath).split("/").pop() || "file";
    return "file";
  }

  function promptOpenCheckout({ filename, canCheckout }) {
    const dialog = $("#open-checkout-dialog");
    const form = $("#open-checkout-form");
    const lead = $("#open-checkout-lead");
    const fileWrap = $("#open-checkout-file-wrap");
    const companionsWrap = $("#open-checkout-companions-wrap");
    const companionsNote = $("#open-checkout-companions-note");
    const wdBox = $("#open-checkout-set-wd");
    const openRadio = $("#open-action-open");
    const cancelBtn = $("#open-checkout-cancel");
    const err = $("#open-checkout-error");
    if (!(dialog instanceof HTMLDialogElement) || !form || !openRadio) {
      return Promise.resolve({ action: "open", setWorkingDirectory: false });
    }
    if (lead) {
      lead.textContent = `How do you want to open ${filename}?`;
    }
    showError(err, "");
    const allowCheckout = Boolean(canCheckout);
    if (fileWrap) fileWrap.hidden = !allowCheckout;
    if (companionsWrap) companionsWrap.hidden = !allowCheckout;
    if (companionsNote) companionsNote.hidden = !allowCheckout;
    openRadio.checked = true;
    if (wdBox) wdBox.checked = true;
    const fileRadio = $("#open-action-checkout-file");
    const companionsRadio = $("#open-action-checkout-companions");
    if (fileRadio) fileRadio.disabled = !allowCheckout;
    if (companionsRadio) companionsRadio.disabled = !allowCheckout;

    return new Promise((resolve) => {
      const finish = (action) => {
        form.removeEventListener("submit", onSubmit);
        cancelBtn?.removeEventListener("click", onCancel);
        dialog.removeEventListener("cancel", onCancel);
        try {
          if (dialog.open) dialog.close();
        } catch {
          /* ignore */
        }
        resolve({
          action,
          setWorkingDirectory: Boolean(wdBox?.checked),
        });
      };
      const onCancel = (event) => {
        event?.preventDefault?.();
        finish("cancel");
      };
      const onSubmit = (event) => {
        event.preventDefault();
        const selected = form.querySelector('input[name="open_action"]:checked');
        finish(selected?.value || "open");
      };
      form.addEventListener("submit", onSubmit);
      cancelBtn?.addEventListener("click", onCancel);
      dialog.addEventListener("cancel", onCancel);
      if (!dialog.open) dialog.showModal();
    });
  }

  async function checkoutBeforeOpen(target, withCompanions) {
    const objectId = openTargetObjectId(target);
    if (!objectId) return [];
    if (!withCompanions) {
      const result = await postAction(
        `/api/objects/${objectId}/checkout`,
        undefined,
        "POST",
        "Checking out…"
      );
      return result ? [objectId] : null;
    }
    const prepared = await postAction(
      "/api/creo/open",
      openRequestBody(target, false, true),
      "POST",
      "Finding companions…"
    );
    if (!prepared) return null;
    const ids = [
      objectId,
      ...((prepared.companions || []).map((item) => item.object_id).filter(Boolean)),
    ];
    const unique = [...new Set(ids)];
    if (unique.length === 1) {
      const result = await postAction(
        `/api/objects/${unique[0]}/checkout`,
        undefined,
        "POST",
        "Checking out…"
      );
      return result ? unique : null;
    }
    const result = await postAction(
      "/api/objects/batch/checkout",
      { object_ids: unique },
      "POST",
      `Checking out ${unique.length} files…`
    );
    if (!result) return null;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (!result.ok?.length) return null;
    return result.ok.map((item) => item.uuid).filter(Boolean);
  }

  async function openPdmObjectFromUi(target, row) {
    const objectId = openTargetObjectId(target);
    const filename = openTargetFilename(target, row);
    const canCheckout = row ? row.dataset.canCheckout === "1" : false;
    const owned = row ? row.dataset.owned === "1" : false;
    // Already mine — no checkout choice needed; open immediately.
    if (objectId && owned) {
      return openPdmObject(target);
    }
    const choice = await promptOpenCheckout({
      filename,
      canCheckout: Boolean(objectId) && canCheckout,
      owned: false,
    });
    const action = typeof choice === "string" ? choice : choice?.action;
    const setWd = Boolean(choice && typeof choice === "object" && choice.setWorkingDirectory);
    if (action === "cancel") return null;
    if (action === "checkout-file" || action === "checkout-companions") {
      const checkedOutIds = await checkoutBeforeOpen(
        target,
        action === "checkout-companions"
      );
      if (!checkedOutIds) return null;
      // Paint before openModel — Creo collapses the embedded browser on Display.
      applyCheckedOutOnRows(checkedOutIds);
    }
    if (setWd && hostedCreoJS()) {
      await setCreoWorkingDirectory();
    }
    return openPdmObject(target);
  }

  function agentBase() {
    const fromBody = (document.body?.dataset?.agentBase || "").trim();
    return fromBody || "http://127.0.0.1:8766";
  }

  async function probeCreoAgent() {
    try {
      const response = await fetch(`${agentBase()}/health`, { method: "GET" });
      if (!response.ok) return null;
      const body = await response.json().catch(() => null);
      return body && body.ok ? body : null;
    } catch {
      return null;
    }
  }

  async function pushLocalWorkspaceToVault(projectId, items) {
    const list = (items || []).filter((item) => item && item.object_id);
    if (!projectId || !list.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/push`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdm_url: window.location.origin,
        project_id: projectId,
        vault_folder: currentVaultFolder(),
        items: list.map((item) => ({
          object_id: String(item.object_id),
          filename: String(item.filename || ""),
        })),
      }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  async function listAgentCacheFiles(projectId) {
    if (!projectId) return [];
    const agent = await probeCreoAgent();
    if (!agent) return [];
    const vaultFolder = currentVaultFolder();
    const params = new URLSearchParams({ project_id: projectId });
    if (vaultFolder) params.set("vault_folder", vaultFolder);
    const response = await fetch(
      `${agentBase()}/files?${params}`,
      { method: "GET" }
    );
    if (!response.ok) return [];
    const body = await response.json().catch(() => null);
    return Array.isArray(body?.files) ? body.files : [];
  }

  async function pushLocalNewPathsToVault(projectId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!projectId || !paths.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/push-paths`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdm_url: window.location.origin,
        project_id: projectId,
        vault_folder: currentVaultFolder(),
        relative_paths: paths,
      }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  async function deleteLocalWorkspacePaths(projectId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!projectId || !paths.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/delete-paths`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        vault_folder: currentVaultFolder(),
        relative_paths: paths,
      }),
    });
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          "Local creopdm-agent does not support Remove from Workspace yet. Restart the creopdm-agent tray (or reinstall from this repo), then try again."
        );
      }
      throw new Error(await readError(response));
    }
    return response.json();
  }

  /** Fire-and-forget trash so Remove can refresh without waiting on thousands of files. */
  function deleteLocalWorkspacePathsBackground(projectId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!projectId || !paths.length) return;
    const url = `${agentBase()}/delete-paths`;
    const chunkSize = 150;
    for (let i = 0; i < paths.length; i += chunkSize) {
      const slice = paths.slice(i, i + chunkSize);
      try {
        fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            vault_folder: currentVaultFolder(),
            relative_paths: slice,
          }),
          keepalive: true,
        });
      } catch {
        /* best-effort; page is about to refresh */
      }
    }
  }

  async function purgeLocalVersionsOlderThanVault(projectId, { dryRun = false } = {}) {
    if (!projectId) return { ok: [], failed: [], deleted: 0, skipped: true };
    const floorsResponse = await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/workspace/purge-floors`
    );
    if (!floorsResponse.ok) {
      throw new Error(await readError(floorsResponse));
    }
    const floorsBody = await floorsResponse.json();
    const floors = Array.isArray(floorsBody?.floors) ? floorsBody.floors : [];
    const modelExtensions = Array.isArray(floorsBody?.model_extensions)
      ? floorsBody.model_extensions
      : [];
    if (!floors.length) {
      return { ok: [], failed: [], deleted: 0, empty: true, floors: [] };
    }
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/purge-versions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        project_id: projectId,
        vault_folder: currentVaultFolder(),
        model_extensions: modelExtensions,
        dry_run: Boolean(dryRun),
        floors: floors.map((item) => ({
          logical_path: item.logical_path,
          min_keep: item.min_keep,
        })),
      }),
    });
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          "Local creopdm-agent does not support Purge workspace yet. Restart the creopdm-agent tray (or reinstall from this repo), then try again."
        );
      }
      throw new Error(await readError(response));
    }
    const body = await response.json();
    body.floors = floors;
    return body;
  }

  function logicalRelativePath(rel) {
    const norm = String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
    const parts = norm.split("/").filter(Boolean);
    const name = parts.pop() || "";
    const logical = logicalUploadName(name);
    return parts.length ? `${parts.join("/")}/${logical}` : logical;
  }

  function rememberKnownWorkspacePaths(exact, logical, basenames) {
    knownWorkspacePaths = {
      exact: new Set(exact || []),
      logical: new Set(logical || []),
      basenames: new Set(basenames || []),
      at: Date.now(),
    };
  }

  let knownWorkspacePaths = { exact: new Set(), logical: new Set(), basenames: new Set(), at: 0 };
  let lastChangesPending = null;
  let changesReloadBusy = false;

  function markKnownPath(rel, exact, logical, basenames) {
    const path = String(rel || "").replace(/\\/g, "/");
    if (!path) return;
    exact.add(path.toLowerCase());
    logical.add(logicalRelativePath(path).toLowerCase());
    basenames.add(logicalUploadName(PathBasename(path)).toLowerCase());
  }

  async function loadKnownWorkspacePaths(projectId, extraRels = []) {
    const exact = new Set();
    const logical = new Set();
    const basenames = new Set();
    (extraRels || []).forEach((rel) => markKnownPath(rel, exact, logical, basenames));
    try {
      const [objectsResponse, queueResponse] = await Promise.all([
        fetch(`/api/projects/${encodeURIComponent(projectId)}/objects`),
        fetch(`/api/projects/${encodeURIComponent(projectId)}/checkin-queue`),
      ]);
      if (objectsResponse.ok) {
        const objects = await objectsResponse.json().catch(() => []);
        (Array.isArray(objects) ? objects : []).forEach((item) => {
          markKnownPath(item.relative_path || item.filename || "", exact, logical, basenames);
        });
      }
      if (queueResponse.ok) {
        const queue = await queueResponse.json().catch(() => null);
        (queue?.new_files || []).forEach((item) => {
          markKnownPath(item.relative_path || "", exact, logical, basenames);
        });
      }
    } catch {
      /* keep whatever we collected */
    }
    rememberKnownWorkspacePaths(exact, logical, basenames);
    return knownWorkspacePaths;
  }

  async function ensureKnownWorkspacePaths(projectId, { force = false } = {}) {
    if (
      !force &&
      knownWorkspacePaths.at &&
      Date.now() - knownWorkspacePaths.at < 15000 &&
      knownWorkspacePaths.exact.size + knownWorkspacePaths.logical.size > 0
    ) {
      return knownWorkspacePaths;
    }
    return loadKnownWorkspacePaths(projectId);
  }

  function localOnlyCacheFiles(cacheFiles, known) {
    const exact = new Set(known.exact || []);
    const logical = new Set(known.logical || []);
    const basenames = new Set(known.basenames || []);
    const created = [];
    (cacheFiles || []).forEach((item) => {
      const rel = String(item.relative_path || "").replace(/\\/g, "/");
      if (!rel) return;
      const exactKey = rel.toLowerCase();
      const logicalKey = logicalRelativePath(rel).toLowerCase();
      const base = logicalUploadName(PathBasename(rel)).toLowerCase();
      const atRoot = !rel.includes("/");
      if (exact.has(exactKey) || logical.has(logicalKey)) return;
      if (atRoot && basenames.has(base)) return;
      exact.add(exactKey);
      logical.add(logicalKey);
      basenames.add(base);
      created.push({
        filename: item.filename || PathBasename(rel),
        relative_path: rel,
        size: item.size,
        saved_at: item.saved_at || "",
        object_type: typeFromExtension(filenameExtension(item.filename || rel)),
        local_cache: true,
      });
    });
    return created;
  }

    function newerLocalCacheSaves(cacheFiles, objects) {
    // Prefer full vault-relative path. Older flat agent caches (basename only)
    // still match when that basename is unique in the project.
    const bestByLogical = new Map();
    const bestByBasename = new Map();
    (cacheFiles || []).forEach((item) => {
      const rel = String(item.relative_path || "").replace(/\\/g, "/");
      if (!rel) return;
      const key = logicalRelativePath(rel).toLowerCase();
      const filename = item.filename || PathBasename(rel);
      const saveNumber = creoSaveNumber(filename);
      const base = logicalUploadName(filename).toLowerCase();
      const entry = { item, rel, filename, saveNumber };
      const prev = bestByLogical.get(key);
      if (!prev || saveNumber > prev.saveNumber) {
        bestByLogical.set(key, entry);
      }
      const prevBase = bestByBasename.get(base);
      const flatter =
        prevBase
        && saveNumber === prevBase.saveNumber
        && rel.split("/").length < prevBase.rel.split("/").length;
      if (!prevBase || saveNumber > prevBase.saveNumber || flatter) {
        bestByBasename.set(base, entry);
      }
    });
    const vaultBasenameCounts = new Map();
    (Array.isArray(objects) ? objects : []).forEach((obj) => {
      const vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      if (!vaultRel) return;
      const base = logicalUploadName(PathBasename(vaultRel)).toLowerCase();
      vaultBasenameCounts.set(base, (vaultBasenameCounts.get(base) || 0) + 1);
    });
    const rows = [];
    (Array.isArray(objects) ? objects : []).forEach((obj) => {
      const vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      if (!vaultRel) return;
      const key = logicalRelativePath(vaultRel).toLowerCase();
      let local = bestByLogical.get(key);
      if (!local) {
        const base = logicalUploadName(PathBasename(vaultRel)).toLowerCase();
        if ((vaultBasenameCounts.get(base) || 0) === 1) {
          local = bestByBasename.get(base);
        }
      }
      if (!local) return;
      const vaultNumber = creoSaveNumber(obj.filename || PathBasename(vaultRel));
      if (local.saveNumber <= vaultNumber) return;
      rows.push({
        uuid: obj.uuid,
        filename: local.filename,
        recorded_filename: obj.filename || PathBasename(vaultRel),
        object_type: obj.object_type,
        relative_path: local.rel,
        size: local.item.size,
        saved_at: local.item.saved_at || "",
        local_cache: true,
        newer_save: true,
        checked_out: obj.owned_by_me ? "1" : "0",
        can_checkin: obj.can_checkin ? "1" : "0",
        can_checkout: obj.can_checkout ? "1" : "0",
      });
    });
    return rows;
  }

  async function countLocalNewWorkspaceFiles(projectId) {
    if (!projectId) return 0;
    const pending = await countLocalWorkspacePending(projectId);
    return pending.localNew;
  }

  let cachedProjectObjects = { id: "", at: 0, rows: [] };

  async function ensureProjectObjects(projectId, { force = false } = {}) {
    if (
      !force &&
      cachedProjectObjects.id === projectId &&
      cachedProjectObjects.at &&
      Date.now() - cachedProjectObjects.at < 15000
    ) {
      return cachedProjectObjects.rows;
    }
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/objects`);
      const rows = response.ok ? await response.json().catch(() => []) : [];
      cachedProjectObjects = {
        id: projectId,
        at: Date.now(),
        rows: Array.isArray(rows) ? rows : [],
      };
    } catch {
      cachedProjectObjects = { id: projectId, at: Date.now(), rows: [] };
    }
    return cachedProjectObjects.rows;
  }

  async function countLocalWorkspacePending(projectId) {
    if (!projectId) return { localNew: 0, newerLocal: 0 };
    const [cacheFiles, known, objects] = await Promise.all([
      listAgentCacheFiles(projectId),
      ensureKnownWorkspacePaths(projectId),
      ensureProjectObjects(projectId),
    ]);
    return {
      localNew: localOnlyCacheFiles(cacheFiles, known).length,
      newerLocal: newerLocalCacheSaves(cacheFiles, objects).length,
    };
  }

  async function materializeViaAgent(prepared) {
    const companions = Array.isArray(prepared.companions) ? prepared.companions : [];
    const response = await fetch(`${agentBase()}/materialize`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdm_url: window.location.origin,
        object_id: prepared.object_id || null,
        project_id: prepared.project_id || currentProjectId() || null,
        vault_folder: currentVaultFolder(),
        relative_path: prepared.relative_path || null,
        filename: prepared.filename || null,
        disk_name: prepared.disk_name || prepared.filename || null,
        companions: companions.map((item) => ({
          object_id: item.object_id || null,
          project_id: item.project_id || prepared.project_id || currentProjectId() || null,
          relative_path: item.relative_path || null,
          filename: item.filename || null,
          disk_name: item.disk_name || item.filename || null,
        })),
      }),
    });
    if (!response.ok) {
      const message = await readError(response);
      throw new Error(message || "Local CreoPDM agent could not fetch the file.");
    }
    return response.json();
  }

  const BULK_AGENT_CACHE_ZIP_THRESHOLD = 50;

  async function materializeCheckedOutToAgentCacheZip(objectIds) {
    const response = await fetch(`${agentBase()}/materialize-zip`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        pdm_url: window.location.origin,
        project_id: currentProjectId() || null,
        vault_folder: currentVaultFolder(),
        object_ids: objectIds,
      }),
    });
    if (!response.ok) {
      const message = await readError(response);
      throw new Error(message || "Local CreoPDM agent could not download the archive.");
    }
    return response.json();
  }

  async function materializeCheckedOutToAgentCache(objectIds, onProgress) {
    const ids = [...new Set((objectIds || []).filter(Boolean))];
    if (!ids.length) return { agentOffline: false, ok: 0, failed: 0 };
    const agent = await probeCreoAgent();
    if (!agent) return { agentOffline: true, ok: 0, failed: 0 };
    const total = ids.length;
    if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD) {
      if (typeof onProgress === "function") onProgress(0, total);
      try {
        const zipResult = await materializeCheckedOutToAgentCacheZip(ids);
        const extracted = Number(zipResult?.extracted_count) || 0;
        const skipped = Number(zipResult?.skipped_count) || 0;
        const keptNewer = Number(zipResult?.kept_newer_count) || 0;
        const downloaded = Number(zipResult?.download_count) || extracted;
        if (typeof onProgress === "function") onProgress(total, total);
        const ok = extracted + skipped + keptNewer;
        return {
          agentOffline: false,
          ok,
          failed: Math.max(0, total - ok),
          skipped,
          keptNewer,
          downloaded,
        };
      } catch {
        /* fall back to per-file download */
      }
    }
    let ok = 0;
    let failed = 0;
    for (let i = 0; i < ids.length; i += 1) {
      const objectId = ids[i];
      if (typeof onProgress === "function") onProgress(i + 1, total);
      try {
        const prepared = await postAction(
          "/api/creo/open",
          { object_id: objectId, launch: false, include_companions: false },
          "POST",
          ""
        );
        if (!prepared) {
          failed += 1;
          continue;
        }
        await materializeViaAgent(prepared);
        ok += 1;
      } catch {
        failed += 1;
      }
    }
    return { agentOffline: false, ok, failed };
  }

  async function openViaAgent(localPath, mode) {
    const response = await fetch(`${agentBase()}/open`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: localPath, mode: mode || "association" }),
    });
    if (!response.ok) {
      const message = await readError(response);
      throw new Error(message || "Local CreoPDM agent could not open the file.");
    }
    return response.json();
  }

  async function openPdmObject(target) {
    await creoJSReady;
    const useCreoSession = hostedCreoJS() || creoOpenMode() === "embedded";
    if (useCreoSession) {
      const prepared = await postAction(
        "/api/creo/open",
        openRequestBody(target, false),
        "POST",
        ""
      );
      if (!prepared) return null;

      // Every Creo-openable model must land in the local agent cache before open.
      let openSpec = prepared;
      const needsCache =
        prepared.requires_agent_cache || prepared.creo_object || prepared.open_with_creo;
      if (needsCache) {
        const agent = await probeCreoAgent();
        if (!agent) {
          showError(
            $("#toolbar-error"),
            "Start creopdm-agent on this Creo PC so the file can download into the local cache before open."
          );
          return null;
        }
        try {
          openSpec = await materializeViaAgent(prepared);
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError(
            $("#toolbar-error"),
            message || "Local CreoPDM agent could not download the file into the cache."
          );
          return null;
        }
      }

      if (prepared.creo_object) {
        if (!hostedCreoJS()) {
          showError(
            $("#toolbar-error"),
            "Creo.JS is not available in this browser session. Reload the page inside Creo's embedded browser after confirming /creojs.js loads."
          );
          return null;
        }
        try {
          await whenCreoJSReady();
          const opened = await window.CreoJS.openModel(
            openSpec.working_directory,
            openSpec.filename || prepared.filename,
            prepared.creo_release || "",
            openSpec.disk_name || openSpec.filename || prepared.filename,
            openSpec.path || ""
          );
          const openedText = opened == null ? "" : String(opened);
          if (openedText.indexOf("CREOPDM_ERROR:") === 0) {
            showError(
              $("#toolbar-error"),
              openedText.slice("CREOPDM_ERROR:".length)
            );
            return null;
          }
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError(
            $("#toolbar-error"),
            message || "Creo could not open the model in this session."
          );
          return null;
        }
      } else if (prepared.open_with_creo) {
        if (!hostedCreoJS()) {
          showError(
            $("#toolbar-error"),
            "Open SolidWorks / Multi-CAD files from Creo's built-in browser so the running session can use the local cache."
          );
          return null;
        }
        try {
          await whenCreoJSReady();
          const directory = openSpec.working_directory || "";
          const diskName = openSpec.disk_name || openSpec.filename || prepared.filename;
          // Do not set Creo session WD — the File > Open trail navigates to the
          // agent cache folder via opt_EMBED_BROWSER_TB_SAB_LAYOUT.
          const opened = await window.CreoJS.openModel(
            directory,
            openSpec.filename || prepared.filename,
            "",
            diskName,
            openSpec.path || ""
          );
          const openedText = opened == null ? "" : String(opened);
          if (openedText.indexOf("CREOPDM_ERROR:") === 0) {
            showError(
              $("#toolbar-error"),
              (diskName || "File")
                + " is in the Creo working directory, but File > Open could not be driven automatically. Use File > Open and select "
                + (diskName || "the file")
                + "."
            );
            return null;
          }
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError(
            $("#toolbar-error"),
            message || "Could not prepare the Multi-CAD file in this Creo session."
          );
          return null;
        }
      } else {
        // Documents / images / Windows-openable CAD: association (or browser download).
        try {
          const agent = await probeCreoAgent();
          if (agent) {
            if (!needsCache) {
              openSpec = await materializeViaAgent(prepared);
            }
            await openViaAgent(openSpec.path, "association");
            return prepared;
          }
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError(
            $("#toolbar-error"),
            message || "Could not open the file with the local agent."
          );
          return null;
        }
        return openPdmLaunchResult(
          await postAction("/api/creo/open", openRequestBody(target, true), "POST", "")
        );
      }
      return prepared;
    }
    return openPdmLaunchResult(
      await postAction("/api/creo/open", openRequestBody(target, true), "POST", "")
    );
  }

  function openPdmLaunchResult(result) {
    if (!result) return null;
    if (result.method === "browser" && result.url) {
      const link = document.createElement("a");
      link.href = result.url;
      link.download = result.filename || "";
      link.rel = "noopener";
      document.body.appendChild(link);
      link.click();
      link.remove();
    }
    return result;
  }

  openBtn?.addEventListener("click", async () => {
    const spec = selectedOpenSpec();
    if (!spec) {
      showError($("#toolbar-error"), "Select one file to open.");
      return;
    }
    const selected = selectedRows();
    const row = selected.length === 1 ? selected[0] : null;
    await openPdmObjectFromUi(spec, row);
  });

  async function runCheckoutObjects(objectIds) {
    const ids = [...new Set((objectIds || []).filter(Boolean))];
    if (!ids.length) return false;
    if (!confirmLargeBulk("Check out", ids.length)) return false;
    showError($("#toolbar-error"), "");
    let checkoutResult = null;
    if (ids.length === 1 && !selectedRows().length) {
      checkoutResult = await postAction(
        `/api/objects/${ids[0]}/checkout`,
        undefined,
        "POST",
        "Checking out…"
      );
      if (!checkoutResult) return false;
    } else {
      const CHECKOUT_CHUNK = 50;
      const total = ids.length;
      checkoutResult = await withBusy(`Checking out… 0 of ${total}`, async () => {
        const merged = { ok: [], failed: [] };
        for (let start = 0; start < ids.length; start += CHECKOUT_CHUNK) {
          const chunk = ids.slice(start, start + CHECKOUT_CHUNK);
          setBusyMessage(`Checking out… ${Math.min(start + chunk.length, total)} of ${total}`);
          const part = await postAction(
            "/api/objects/batch/checkout",
            { object_ids: chunk },
            "POST",
            ""
          );
          if (!part) return null;
          if (Array.isArray(part.ok)) merged.ok.push(...part.ok);
          if (Array.isArray(part.failed)) merged.failed.push(...part.failed);
        }
        return merged;
      });
      if (!checkoutResult) return false;
      const warning = formatBatch(checkoutResult);
      if (warning) showError($("#toolbar-error"), warning);
      if (!checkoutResult.ok?.length) return false;
    }
    const syncedIds =
      Array.isArray(checkoutResult.ok) && checkoutResult.ok.length
        ? checkoutResult.ok.map((item) => item.uuid).filter(Boolean)
        : ids;
    const sync = await withBusy("Downloading checked-out files to local workspace…", async () => {
      try {
        return await materializeCheckedOutToAgentCache(syncedIds, (done, total) => {
          if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD && done === 0) {
            setBusyMessage(`Checking local cache for ${total} files…`);
          } else {
            setBusyMessage(`Downloading checked-out files… ${done} of ${total}`);
          }
        });
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return null;
      }
    });
    if (sync?.agentOffline) {
      showError(
        $("#toolbar-error"),
        "Checked out on the server, but creopdm-agent is not running — local workspace was not updated. Start the agent and open the files, or check out again."
      );
    } else if (sync && sync.failed && !sync.ok) {
      showError(
        $("#toolbar-error"),
        "Checked out, but could not download files into the local workspace."
      );
    } else if (sync?.ok) {
      const note = sync.failed
        ? `${sync.ok} file(s) in local workspace (${sync.failed} failed).`
        : sync.downloaded != null && (sync.skipped || sync.keptNewer)
          ? `${sync.ok} file(s) ready (${sync.downloaded} downloaded, ${sync.skipped || 0} already local` +
            (sync.keptNewer ? `, ${sync.keptNewer} kept newer local` : "") +
            `).`
          : `${sync.ok} file(s) downloaded to the local workspace.`;
      showOk(note);
    }
    // Paint before reload — Creo often collapses the browser on open and may
    // ignore form navigation while a folder view is showing.
    applyCheckedOutOnRows(syncedIds);
    const remaining = Math.max(
      0,
      Number(checkoutProjectBtn?.dataset.checkoutable || 0) - syncedIds.length
    );
    setCheckoutableCount(remaining);
    reloadPage({ keepBusy: true });
    return true;
  }

  checkoutBtn?.addEventListener("click", async () => {
    const ids = selectedRows().filter((row) => row.dataset.canCheckout === "1").flatMap(rowObjectIds);
    const fallback = selectedIds();
    const objectIds = [...new Set((ids.length ? ids : fallback).filter(Boolean))];
    await runCheckoutObjects(objectIds);
  });

  checkoutProjectBtn?.addEventListener("click", async () => {
    const projectId =
      checkoutProjectBtn.dataset.project ||
      openWorkspaceBtn?.dataset.project ||
      currentProjectId() ||
      "";
    if (!projectId) {
      showError($("#toolbar-error"), "Select a project first.");
      return;
    }
    showError($("#toolbar-error"), "");
    const listed = await withBusy("Listing project files…", async () => {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/objects`);
      if (!response.ok) {
        showError($("#toolbar-error"), await readError(response));
        return null;
      }
      return response.json();
    });
    if (!listed) return;
    const objectIds = (Array.isArray(listed) ? listed : [])
      .filter((item) => item && item.can_checkout && item.uuid)
      .map((item) => String(item.uuid));
    if (!objectIds.length) {
      showError($("#toolbar-error"), "No files available to check out in this project.");
      setCheckoutableCount(0);
      return;
    }
    await runCheckoutObjects(objectIds);
  });

  workspaceBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) return;
    const result = await postAction("/api/objects/batch/workspace", { object_ids: ids }, "POST", "Copying to vault…");
    if (!result) return;
    const warning = formatBatch(result);
    const copied = result.ok?.length || 0;
    if (warning) showError($("#toolbar-error"), warning);
    else showOk(`${copied} file(s) copied to the vault.`);
  });

  openWorkspaceBtn?.addEventListener("click", async () => {
    const projectId = openWorkspaceBtn.dataset.project;
    if (!projectId) return;
    const folder = openWorkspaceBtn.dataset.folder || currentFolder() || "";
    showError($("#toolbar-error"), "");
    showOk("");
    const agent = await probeCreoAgent();
    if (agent) {
      const opened = await withBusy("Opening local workspace…", async () => {
        const response = await fetch(`${agentBase()}/open-folder`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            project_id: projectId,
            vault_folder: openWorkspaceBtn.dataset.vaultFolder || currentVaultFolder(),
            folder,
          }),
        });
        if (!response.ok) {
          showError($("#toolbar-error"), await readError(response));
          return null;
        }
        return response.json();
      });
      if (opened) showOk("Opened the local workspace folder.");
      return;
    }
    const query = folder ? `?folder=${encodeURIComponent(folder)}` : "";
    const result = await postAction(
      `/api/projects/${projectId}/workspace/open${query}`,
      undefined,
      "POST",
      "Opening vault…"
    );
    if (result) showOk("Opened the vault folder on the CreoPDM host.");
  });

  undoBtn?.addEventListener("click", async () => {
    const ids = selectedRows().filter((row) => row.dataset.owned === "1").flatMap(rowObjectIds);
    const fallback = selectedIds();
    const objectIds = [...new Set((ids.length ? ids : fallback).filter(Boolean))];
    if (!objectIds.length) return;
    const count = objectIds.length;
    const slowNote =
      count > BULK_SLOW_WARN_THRESHOLD
        ? "\n\nThis can take several minutes. Keep this window open until it finishes."
        : "";
    const confirmMsg =
      count === 1
        ? "Undo checkout of this file?\n\nYour lock is released. Unsaved vault changes for this file may be discarded. Local agent cache files are kept."
        : `Undo checkout of ${count} files?\n\nYour locks are released. Unsaved vault changes for these files may be discarded. Local agent cache files are kept.${slowNote}`;
    if (!window.confirm(confirmMsg)) return;
    showError($("#toolbar-error"), "");
    if (count === 1 && !selectedRows().length) {
      const result = await postAction(
        `/api/objects/${objectIds[0]}/undo-checkout`,
        undefined,
        "POST",
        "Cancelling checkout…"
      );
      if (result) {
        rememberWatchView();
        applyUndoCheckoutOnRows(objectIds);
        reloadPage({ keepBusy: true });
      }
      return;
    }
    const UNDO_CHUNK = 50;
    const undoResult = await withBusy(`Cancelling checkout… 0 of ${count}`, async () => {
      const merged = { ok: [], failed: [] };
      for (let start = 0; start < objectIds.length; start += UNDO_CHUNK) {
        const chunk = objectIds.slice(start, start + UNDO_CHUNK);
        setBusyMessage(`Cancelling checkout… ${Math.min(start + chunk.length, count)} of ${count}`);
        const part = await postAction(
          "/api/objects/batch/undo-checkout",
          { object_ids: chunk },
          "POST",
          ""
        );
        if (!part) return null;
        if (Array.isArray(part.ok)) merged.ok.push(...part.ok);
        if (Array.isArray(part.failed)) merged.failed.push(...part.failed);
      }
      return merged;
    });
    if (!undoResult) return;
    const warning = formatBatch(undoResult);
    if (warning) showError($("#toolbar-error"), warning);
    if (undoResult.ok?.length) {
      const undone = undoResult.ok.map((item) => item.uuid).filter(Boolean);
      applyUndoCheckoutOnRows(undone.length ? undone : objectIds);
      reloadPage({ keepBusy: true });
    }
  });

  async function beginCheckin(scope = "selected") {
    const projectScope = scope === "project";
    const selected = projectScope ? [] : selectedRows();
    if (!projectScope && !selectionCanCheckin(selected) && !checkinBtn?.dataset.uuid) {
      showError(
        $("#toolbar-error"),
        "Nothing to check in for this selection. Save changes in Creo first, or use Undo Checkout."
      );
      return;
    }
    if (projectScope) {
      const pending = Number(
        checkinBtn?.dataset.pendingSaves || checkinMenuBtn?.dataset.pendingSaves || 0
      );
      const news = Number(checkinBtn?.dataset.newFiles || checkinMenuBtn?.dataset.newFiles || 0);
      const checkouts = Number(
        checkinProjectBtn?.dataset.checkoutCount || checkinMenuBtn?.dataset.checkoutCount || 0
      );
      if (pending <= 0 && news <= 0 && checkouts <= 0) {
        showError(
          $("#toolbar-error"),
          "Nothing to check in for this project. Modified checkouts and new files appear under New files."
        );
        return;
      }
    }
    const queued = selected.filter((row) => row.classList.contains("queue-row"));
    const owned = selected.filter((row) => {
      return row.dataset.canCheckin === "1" && !row.classList.contains("queue-row");
    });
    const addOnly = projectScope ? false : selectionIsAddOnly(selected);
    const projectId =
      checkinBtn?.dataset.project ||
      checkinMenuBtn?.dataset.project ||
      checkinProjectBtn?.dataset.project ||
      openWorkspaceBtn?.dataset.project;
    if (!checkinDialog) return;
    const fallbackId = checkinBtn?.dataset.uuid || "";
    let objectId = "";
    if (!projectScope) {
      if (!queued.length && owned.length === 1) {
        objectId = owned[0].dataset.uuid;
      } else if (!queued.length && !owned.length && fallbackId) {
        objectId = fallbackId;
      }
    }
    const useQueue = projectScope || !objectId;
    if (useQueue && !projectId) return;
    if (!projectScope) {
      const bulkCount = useQueue ? owned.length + queued.length : 1;
      if (!confirmLargeBulk(addOnly ? "Add" : "Check in", bulkCount)) return;
    }
    showError($("#checkin-error"), "");
    showError($("#toolbar-error"), "");
    const pushItems = [];
    let projectLocalNewPaths = [];
    if (!addOnly) {
      if (objectId) {
        const name =
          owned[0]?.dataset.filename ||
          document.querySelector(".detail-head .object-open")?.textContent?.trim() ||
          "";
        pushItems.push({ object_id: objectId, filename: name });
      } else if (!projectScope) {
        owned.forEach((row) => {
          if (row.dataset.uuid) {
            pushItems.push({
              object_id: row.dataset.uuid,
              filename: row.dataset.filename || "",
            });
          }
        });
        queued.forEach((row) => {
          if (row.dataset.uuid && row.dataset.localCache === "1") {
            pushItems.push({
              object_id: row.dataset.uuid,
              filename: row.dataset.filename || "",
            });
          }
        });
      } else if (projectId) {
        // Match New files tab: vault queue + local agent-cache new/newer saves.
        // Preview is vault-only — push local work first or the dialog shows "0 vault files".
        try {
          const [queueResp, cacheFiles, objects] = await Promise.all([
            fetch(`/api/projects/${encodeURIComponent(projectId)}/checkin-queue`),
            listAgentCacheFiles(projectId),
            ensureProjectObjects(projectId, { force: true }),
          ]);
          let vaultNew = [];
          if (queueResp.ok) {
            const queueBody = await queueResp.json();
            (queueBody.saves || []).forEach((item) => {
              if (item?.uuid) {
                pushItems.push({
                  object_id: String(item.uuid),
                  filename: String(item.filename || ""),
                });
              }
            });
            vaultNew = Array.isArray(queueBody.new_files) ? queueBody.new_files : [];
          }
          const known = await loadKnownWorkspacePaths(
            projectId,
            vaultNew.map((item) => item.relative_path || "")
          );
          const localNew = localOnlyCacheFiles(cacheFiles, known);
          projectLocalNewPaths = localNew
            .map((item) => String(item.relative_path || item.path || "").replace(/\\/g, "/"))
            .filter(Boolean);
          const vaultSaveIds = new Set(pushItems.map((item) => item.object_id));
          newerLocalCacheSaves(cacheFiles, objects)
            .filter((item) => item?.uuid && !vaultSaveIds.has(String(item.uuid)))
            .forEach((item) => {
              pushItems.push({
                object_id: String(item.uuid),
                filename: String(item.filename || ""),
              });
            });
        } catch {
          /* preview still runs */
        }
        const bulkHint = Math.max(pushItems.length + projectLocalNewPaths.length, 1);
        if (!confirmLargeBulk("Check in project", bulkHint)) return;
      }
    }
    let agentOffline = false;
    const preview = await withBusy(addOnly ? "Preparing…" : "Preparing check-in…", async () => {
      if (!addOnly && projectId && pushItems.length) {
        try {
          const pushed = await pushLocalWorkspaceToVault(projectId, pushItems);
          if (pushed === null) {
            agentOffline = true;
          } else if (pushed.failed?.length && !pushed.ok?.length) {
            const first = pushed.failed[0]?.message || "Could not sync local files to the vault.";
            showError($("#toolbar-error"), first);
          }
        } catch (err) {
          showError($("#toolbar-error"), err?.message || String(err));
        }
      }
      if (!addOnly && projectId && projectLocalNewPaths.length) {
        try {
          const pushedNew = await pushLocalNewPathsToVault(projectId, projectLocalNewPaths);
          if (pushedNew === null) {
            agentOffline = true;
          } else if (pushedNew.failed?.length && !pushedNew.ok?.length) {
            const first = pushedNew.failed[0]?.message || "Could not sync new local files to the vault.";
            showError($("#toolbar-error"), first);
          }
        } catch (err) {
          showError($("#toolbar-error"), err?.message || String(err));
        }
      }
      return fetch(
        useQueue
          ? `/api/projects/${projectId}/checkin-preview`
          : `/api/objects/${objectId}/checkin-preview`
      );
    });
    if (!preview.ok) {
      showError($("#toolbar-error"), await readError(preview));
      return;
    }
    const data = await preview.json();
    if (
      !addOnly &&
      agentOffline &&
      (pushItems.length || projectLocalNewPaths.length) &&
      !(data.object_ids || []).length &&
      !(data.new_files || []).length &&
      !data.can_checkin
    ) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to sync local workspace saves into the vault before check-in."
      );
    }
    const title = $("#checkin-dialog-title");
    if (title) {
      title.textContent = addOnly ? "Add files" : projectScope ? "Check in project" : "Check In";
    }
    $("#checkin-filename").textContent = addOnly
      ? (queued.length === 1 ? queued[0].dataset.filename || data.filename : `${queued.length || (data.new_files || []).length} files`)
      : data.filename;
    $("#checkin-current").textContent = data.current_display;
    $("#checkin-next").textContent = data.next_display;
    ["checkin-current", "checkin-next", "checkin-current-label", "checkin-next-label"].forEach((itemId) => {
      const el = $("#" + itemId);
      if (el) el.hidden = useQueue;
    });
    const objectLabel = [...document.querySelectorAll("#checkin-dialog .kv dt")].find(
      (el) => el.textContent.trim() === "Object"
    );
    if (objectLabel) {
      objectLabel.hidden = Boolean(addOnly);
      const objectValue = objectLabel.nextElementSibling;
      if (objectValue) objectValue.hidden = Boolean(addOnly);
    }
    $("#checkin-comment").value = "";
    let projectUndoIds = [];
    if (projectScope && projectId) {
      try {
        const checkoutResp = await fetch(`/api/projects/${encodeURIComponent(projectId)}/checkouts`);
        if (checkoutResp.ok) {
          const listed = await checkoutResp.json();
          const pendingSet = new Set(data.object_ids || []);
          projectUndoIds = (Array.isArray(listed) ? listed : [])
            .filter((item) => item && item.owned_by_me && item.uuid && !pendingSet.has(String(item.uuid)))
            .map((item) => String(item.uuid));
        }
      } catch {
        projectUndoIds = [];
      }
    }
    if (checkinDialog) {
      checkinDialog.dataset.force = data.force_checkin ? "1" : "";
      checkinDialog.dataset.queue = useQueue ? "1" : "";
      checkinDialog.dataset.addOnly = addOnly ? "1" : "";
      checkinDialog.dataset.objectId = useQueue ? "" : objectId;
      checkinDialog.dataset.projectId = projectId || "";
      checkinDialog.dataset.pushItems = JSON.stringify(pushItems);
      const selectedIdsForQueue = queued
        .map((row) => row.dataset.uuid)
        .filter(Boolean);
      const ownedIds = owned.map((row) => row.dataset.uuid).filter(Boolean);
      const pendingIds = data.object_ids || [];
      const pendingSet = new Set(pendingIds);
      // Only vault-dirty files — not every owned checkout (avoids empty revisions).
      let checkinIds = [];
      if (!addOnly) {
        if (projectScope) {
          checkinIds = pendingIds.slice();
        } else if (selectedIdsForQueue.length) {
          checkinIds = selectedIdsForQueue.filter((id) => pendingSet.has(id));
        } else if (ownedIds.length) {
          checkinIds = ownedIds.filter((id) => pendingSet.has(id));
        } else {
          checkinIds = pendingIds.slice();
        }
      }
      checkinDialog.dataset.objectIds = JSON.stringify(checkinIds);
      checkinDialog.dataset.projectScope = projectScope ? "1" : "";
      checkinDialog.dataset.undoIds = JSON.stringify(projectUndoIds);
    }
    const forceWarn = $("#checkin-force-warn");
    if (forceWarn) {
      forceWarn.hidden = !data.warning || addOnly;
      forceWarn.textContent = data.warning || "";
    }
    const submitBtn = checkinForm?.querySelector("button[type='submit']");
    const list = $("#checkin-changes");
    list.innerHTML = "";
    let canSubmit = true;
    if (useQueue) {
      const wantedIds = new Set(queued.map((row) => row.dataset.uuid).filter(Boolean));
      const pendingNames = data.pending_files || [];
      const pendingIds = data.object_ids || [];
      const names = addOnly
        ? []
        : projectScope || !queued.length
          ? pendingNames
          : pendingIds.map((id, index) => (wantedIds.has(id) ? pendingNames[index] : "")).filter(Boolean);
      names.forEach((name) => {
        const item = document.createElement("li");
        item.textContent = `✓ Check in ${name}`;
        list.appendChild(item);
      });
      const newCount = projectScope
        ? (data.new_files || []).length
        : queued.length
          ? queued.filter((row) => row.dataset.relativePath).length
          : (data.new_files || []).length;
      if (addOnly) {
        const selectedPaths = queued
          .map((row) => row.dataset.relativePath)
          .filter(Boolean);
        selectedPaths.forEach((path) => {
          const item = document.createElement("li");
          const name = path.includes("/") ? path.slice(path.lastIndexOf("/") + 1) : path;
          item.textContent = `✓ Add ${name}`;
          list.appendChild(item);
        });
        if (!selectedPaths.length) {
          const item = document.createElement("li");
          item.textContent = "– No files selected";
          list.appendChild(item);
          canSubmit = false;
        }
      } else if (!names.length && !newCount && !projectUndoIds.length) {
        const item = document.createElement("li");
        item.textContent = projectScope
          ? "– Nothing to check in. Local workspace files need creopdm-agent to sync into the vault first."
          : "– Nothing to check in. Use Undo Checkout to release locks without a new version.";
        list.appendChild(item);
        canSubmit = false;
      } else {
        if (projectScope && newCount && !names.length) {
          (data.new_files || []).forEach((file) => {
            const item = document.createElement("li");
            item.textContent = `✓ Add ${file.filename || file.relative_path || "file"}`;
            list.appendChild(item);
          });
        }
        if (projectUndoIds.length) {
          const item = document.createElement("li");
          item.textContent =
            projectUndoIds.length === 1
              ? "✓ Undo checkout on 1 unchanged file (no new version)"
              : `✓ Undo checkout on ${projectUndoIds.length} unchanged files (no new version)`;
          list.appendChild(item);
        }
      }
    } else {
      [
        [data.file_modified, "File modified"],
        [data.parameters_changed, "Parameters changed"],
        [data.dependencies_unchanged, "Dependencies unchanged"],
      ].forEach(([flag, label]) => {
        const item = document.createElement("li");
        item.textContent = `${flag ? "✓" : "–"} ${label}`;
        list.appendChild(item);
      });
      if (!addOnly && !data.file_modified && !data.force_checkin) {
        canSubmit = false;
        const item = document.createElement("li");
        item.textContent = "– No changes. Use Undo Checkout to release the lock without a new version.";
        list.appendChild(item);
      }
    }
    if (submitBtn) {
      submitBtn.textContent = addOnly
        ? "Add"
        : projectScope && !((data.object_ids || []).length) && !((data.new_files || []).length) && projectUndoIds.length
          ? "Release checkouts"
          : data.force_checkin
            ? "Check In anyway"
            : "Check In";
      submitBtn.disabled = !canSubmit;
    }
    const commentBox = $("#checkin-comment");
    const needsComment =
      canSubmit &&
      (addOnly ||
        Boolean((data.object_ids || []).length) ||
        Boolean((data.new_files || []).length) ||
        !projectScope);
    if (commentBox) {
      commentBox.disabled = !canSubmit;
      commentBox.required = needsComment;
      if (!canSubmit) commentBox.value = "";
      if (canSubmit && !needsComment) {
        commentBox.value = commentBox.value || "Release unchanged checkouts";
      }
    }
    if (checkinDialog) {
      checkinDialog.dataset.canSubmit = canSubmit ? "1" : "0";
    }
    const wrap = $("#checkin-new-wrap");
    const box = $("#checkin-new-files");
    const help = $("#checkin-new-help");
    const pick = $("#checkin-new-pick");
    if (help) {
      help.textContent = useQueue
        ? "New files in the vault. They are not added unless you check them."
        : "New files Creo saved next to this model. They are not added unless you check them.";
    }
    function syncNewFilePick() {
      if (!box || !pick) return;
      const boxes = [...box.querySelectorAll('input[type="checkbox"]')];
      if (!boxes.length) return;
      const checked = boxes.filter((item) => item.checked).length;
      const none = pick.querySelector('input[value="none"]');
      const all = pick.querySelector('input[value="all"]');
      if (checked === 0 && none) none.checked = true;
      else if (checked === boxes.length && all) all.checked = true;
      else {
        if (none) none.checked = false;
        if (all) all.checked = false;
      }
    }
    function applyNewFilePick(mode) {
      if (!box) return;
      const on = mode === "all";
      box.querySelectorAll('input[type="checkbox"]').forEach((item) => {
        item.checked = on;
      });
    }
    const selectedNew = new Set(
      projectScope
        ? (data.new_files || []).map((item) => item.relative_path).filter(Boolean)
        : queued.map((row) => row.dataset.relativePath).filter(Boolean)
    );
    if (checkinDialog) {
      checkinDialog.dataset.addPaths = JSON.stringify(
        addOnly ? [...selectedNew] : []
      );
      const localSelected = addOnly
        ? queued
            .filter((row) => row.dataset.localCache === "1" && row.dataset.relativePath)
            .map((row) => row.dataset.relativePath)
        : [];
      checkinDialog.dataset.localPaths = JSON.stringify(localSelected);
    }
    if (wrap && box) {
      box.innerHTML = "";
      if (addOnly) {
        wrap.hidden = true;
        if (pick) pick.hidden = true;
      } else {
        const news = data.new_files || [];
        wrap.hidden = news.length === 0;
        if (pick) pick.hidden = news.length === 0;
        news.forEach((item) => {
          const label = document.createElement("label");
          label.className = "choice";
          const input = document.createElement("input");
          input.type = "checkbox";
          input.value = item.relative_path;
          input.checked = selectedNew.has(item.relative_path);
          input.addEventListener("change", syncNewFilePick);
          label.appendChild(input);
          label.append(` ${item.filename}`);
          const hint = document.createElement("span");
          hint.className = "muted small";
          hint.textContent = ` ${item.relative_path}`;
          label.appendChild(hint);
          box.appendChild(label);
        });
        if (pick) {
          const none = pick.querySelector('input[value="none"]');
          const all = pick.querySelector('input[value="all"]');
          if (none) none.checked = selectedNew.size === 0;
          if (all) all.checked = news.length > 0 && selectedNew.size === news.length;
          if (!pick.dataset.bound) {
            pick.dataset.bound = "1";
            pick.addEventListener("change", (event) => {
              const radio = eventEl(event)?.closest('input[type="radio"]');
              if (!radio || radio.name !== "checkin-new-pick") return;
              applyNewFilePick(radio.value);
            });
          }
        }
        syncNewFilePick();
      }
    }
    checkinDialog.showModal();
  }

  checkinBtn?.addEventListener("click", () => {
    void beginCheckin("selected");
  });
  checkinProjectBtn?.addEventListener("click", () => {
    void beginCheckin("project");
  });

  $("#checkin-cancel")?.addEventListener("click", () => checkinDialog?.close());
  checkinForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = checkinDialog?.dataset.objectId || "";
    const comment = String($("#checkin-comment")?.value || "").trim();
    if (!comment) {
      showError(
        $("#checkin-error"),
        checkinDialog?.dataset.addOnly === "1" ? "A comment is required." : "A check-in comment is required."
      );
      return;
    }
    if (checkinDialog?.dataset.addOnly !== "1" && checkinDialog?.dataset.canSubmit === "0") {
      showError(
        $("#checkin-error"),
        "Nothing to check in. Use Undo Checkout to release locks without a new version."
      );
      return;
    }
    if (checkinDialog?.dataset.force === "1") {
      const name = $("#checkin-filename")?.textContent || "This file";
      if (!window.confirm(`${name} is not checked out. Check in the vault save anyway?`)) return;
    }
    let added = [...document.querySelectorAll("#checkin-new-files input:checked")].map(
      (input) => input.value
    );
    if (checkinDialog?.dataset.addOnly === "1") {
      try {
        added = JSON.parse(checkinDialog.dataset.addPaths || "[]");
      } catch {
        added = [];
      }
      if (!added.length) {
        showError($("#checkin-error"), "Select at least one file to add.");
        return;
      }
      let localPaths = [];
      try {
        localPaths = JSON.parse(checkinDialog.dataset.localPaths || "[]");
      } catch {
        localPaths = [];
      }
      localPaths = localPaths.filter((path) => added.includes(path));
      if (localPaths.length) {
        const projectId =
          checkinDialog?.dataset.projectId ||
          checkinBtn?.dataset.project ||
          openWorkspaceBtn?.dataset.project ||
          "";
        const synced = await withBusy("Uploading local workspace files to vault…", async () => {
          try {
            return await pushLocalNewPathsToVault(projectId, localPaths);
          } catch (err) {
            showError($("#checkin-error"), err?.message || String(err));
            return false;
          }
        });
        if (synced === false) return;
        if (!synced) {
          showError(
            $("#checkin-error"),
            "Start creopdm-agent on this Creo PC to upload local workspace files into the vault."
          );
          return;
        }
        if (synced.failed?.length && !synced.ok?.length) {
          showError(
            $("#checkin-error"),
            synced.failed[0]?.message || "Could not upload local files to the vault."
          );
          return;
        }
      }
    }
    let result;
    const busyLabel = checkinDialog?.dataset.addOnly === "1" ? "Adding…" : "Checking in…";
    if (checkinDialog?.dataset.addOnly !== "1") {
      let pushItems = [];
      try {
        pushItems = JSON.parse(checkinDialog?.dataset.pushItems || "[]");
      } catch {
        pushItems = [];
      }
      const projectId =
        checkinDialog?.dataset.projectId ||
        checkinBtn?.dataset.project ||
        openWorkspaceBtn?.dataset.project ||
        "";
      if (projectId && pushItems.length) {
        const synced = await withBusy("Syncing local workspace to vault…", async () => {
          try {
            return await pushLocalWorkspaceToVault(projectId, pushItems);
          } catch (err) {
            showError($("#checkin-error"), err?.message || String(err));
            return false;
          }
        });
        if (synced === false) return;
        if (synced?.failed?.length && !synced.ok?.length) {
          showError(
            $("#checkin-error"),
            synced.failed[0]?.message || "Could not sync local files to the vault."
          );
          return;
        }
      }
    }
    if (checkinDialog?.dataset.queue === "1") {
      const projectId = checkinBtn?.dataset.project || checkinDialog?.dataset.projectId;
      if (!projectId) return;
      let objectIds = [];
      try {
        objectIds = JSON.parse(checkinDialog.dataset.objectIds || "[]");
      } catch {
        objectIds = [];
      }
      let undoIds = [];
      try {
        undoIds = JSON.parse(checkinDialog.dataset.undoIds || "[]");
      } catch {
        undoIds = [];
      }
      const projectScopeSubmit = checkinDialog.dataset.projectScope === "1";
      if (!objectIds.length && !added.length && !(projectScopeSubmit && undoIds.length)) {
        showError(
          $("#checkin-error"),
          "Nothing to check in. Use Undo Checkout to release locks without a new version."
        );
        return;
      }
      if (objectIds.length || added.length) {
        result = await postAction(`/api/projects/${projectId}/checkin-queue`, {
          comment,
          object_ids: objectIds,
          add_relative_paths: added,
        }, "POST", busyLabel);
        if (!result) return;
      } else {
        result = { ok: [], failed: [] };
      }
      if (projectScopeSubmit && undoIds.length) {
        const UNDO_CHUNK = 50;
        const undoResult = await withBusy(
          `Releasing unchanged checkouts… 0 of ${undoIds.length}`,
          async () => {
            const merged = { ok: [], failed: [] };
            for (let start = 0; start < undoIds.length; start += UNDO_CHUNK) {
              const chunk = undoIds.slice(start, start + UNDO_CHUNK);
              setBusyMessage(
                `Releasing unchanged checkouts… ${Math.min(start + chunk.length, undoIds.length)} of ${undoIds.length}`
              );
              const part = await postAction(
                "/api/objects/batch/undo-checkout",
                { object_ids: chunk },
                "POST",
                ""
              );
              if (!part) return null;
              if (Array.isArray(part.ok)) merged.ok.push(...part.ok);
              if (Array.isArray(part.failed)) merged.failed.push(...part.failed);
            }
            return merged;
          }
        );
        if (!undoResult) return;
        result = {
          ok: [...(result.ok || []), ...(undoResult.ok || [])],
          failed: [...(result.failed || []), ...(undoResult.failed || [])],
        };
        applyUndoCheckoutOnRows(undoResult.ok.map((item) => item.uuid).filter(Boolean));
      }
    } else {
      if (!id) return;
      result = await postAction(`/api/objects/${id}/checkin`, {
        comment,
        add_relative_paths: added,
      }, "POST", busyLabel);
    }
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    const batchOk = Array.isArray(result.ok) ? result.ok.length > 0 : null;
    const succeeded = batchOk === null ? true : batchOk;
    if (succeeded) {
      try {
        checkinDialog?.close();
      } catch {
        /* ignore */
      }
      // Always patch the table first — Creo often skips navigation from this dialog.
      applyCheckedInResult(result);
      if (canGatherCreoMetadata()) {
        await withBusy("Capturing Creo metadata…", async () => {
          await pushCreoMetadataForItems(metadataTargetsFromResult(result));
        });
      }
      rememberWatchView({ tab: "files", ids: [] });
      reloadPageAfterDialog();
    }
  });

  historyBtn?.addEventListener("click", () => {
    const href = rowHistoryHref(selectedRows()[0]);
    if (href) window.location.href = href;
  });

  function expectedProjectName() {
    return (
      $("#delete-project-btn")?.dataset.name
      || purgeVersionsBtn?.dataset.projectName
      || purgeBtn?.dataset.projectName
      || removeBtn?.dataset.projectName
      || discardLocalBtn?.dataset.projectName
      || ""
    ).trim();
  }

  function confirmByProjectName({
    title,
    lead,
    note,
    submitLabel,
    detailsHtml = "",
    workspaceOption = false,
  }) {
    const dialog = $("#danger-confirm-dialog");
    const form = $("#danger-confirm-form");
    const expected = expectedProjectName();
    if (!dialog || !form || !expected) {
      return Promise.resolve({ ok: false, deleteWorkspaceFiles: false });
    }
    const titleEl = $("#danger-confirm-title");
    const leadEl = $("#danger-confirm-lead");
    const noteEl = $("#danger-confirm-note");
    const noteStrong = noteEl?.querySelector("strong");
    const detailsEl = $("#danger-confirm-details");
    const submitBtn = $("#danger-confirm-submit");
    const workspaceWrap = $("#danger-confirm-workspace-wrap");
    const workspaceHint = $("#danger-confirm-workspace-hint");
    const workspaceCheck = $("#danger-confirm-workspace");
    if (titleEl) titleEl.textContent = title;
    if (leadEl) leadEl.textContent = lead;
    if (noteStrong) noteStrong.textContent = note || "";
    if (noteEl) noteEl.hidden = !note;
    if (detailsEl) {
      const html = String(detailsHtml || "").trim();
      detailsEl.innerHTML = html;
      detailsEl.hidden = !html;
    }
    if (submitBtn) submitBtn.textContent = submitLabel;
    showError($("#danger-confirm-error"), "");
    form.reset();
    if (workspaceWrap) workspaceWrap.hidden = !workspaceOption;
    if (workspaceHint) workspaceHint.hidden = !workspaceOption;
    if (workspaceCheck) {
      workspaceCheck.disabled = !workspaceOption;
      workspaceCheck.checked = Boolean(workspaceOption);
    }
    return new Promise((resolve) => {
      let settled = false;
      const finish = (ok) => {
        if (settled) return;
        settled = true;
        form.removeEventListener("submit", onSubmit);
        $("#danger-confirm-cancel")?.removeEventListener("click", onCancel);
        dialog.removeEventListener("close", onClose);
        if (detailsEl) {
          detailsEl.innerHTML = "";
          detailsEl.hidden = true;
        }
        if (workspaceWrap) workspaceWrap.hidden = true;
        if (workspaceHint) workspaceHint.hidden = true;
        const deleteWorkspaceFiles = Boolean(ok && workspaceOption && workspaceCheck?.checked);
        if (dialog.open) dialog.close();
        resolve({ ok: Boolean(ok), deleteWorkspaceFiles });
      };
      const onCancel = () => finish(false);
      const onClose = () => finish(false);
      const onSubmit = (event) => {
        event.preventDefault();
        const typed = String(new FormData(form).get("confirm_name") || "").trim();
        if (typed !== expected) {
          showError($("#danger-confirm-error"), "Type the project name exactly to confirm.");
          return;
        }
        finish(true);
      };
      form.addEventListener("submit", onSubmit);
      $("#danger-confirm-cancel")?.addEventListener("click", onCancel);
      dialog.addEventListener("close", onClose);
      dialog.showModal();
      $("#danger-confirm-input")?.focus();
    });
  }

  function workspacePathsForRemovedObjects(projectId, selected) {
    // Sync only — do not list the whole agent cache (that stalled Remove for
    // thousands of files). Agent /delete-paths expands Creo numbered siblings.
    const seeds = new Set();
    const addSeed = (raw) => {
      const rel = String(raw || "").replace(/\\/g, "/").replace(/^\/+/, "").trim();
      if (!rel) return;
      seeds.add(rel);
      const base = PathBasename(rel);
      if (base) seeds.add(base);
    };
    (selected || []).forEach((row) => {
      addSeed(row?.dataset?.relativePath);
      addSeed(row?.dataset?.sortName);
      addSeed(row?.dataset?.filename);
      if (row?.classList?.contains("folder-row")) {
        addSeed(row.dataset.folder);
      }
    });
    if (!seeds.size && removeBtn) {
      addSeed(removeBtn.dataset.relativePath);
      addSeed(removeBtn.dataset.filename);
    }
    return [...seeds];
  }

  function removeSelectedRowsFromDom(rows) {
    (rows || []).forEach((row) => {
      try {
        row.remove();
      } catch {
        /* ignore */
      }
    });
    // Keep the folder-view snapshot in sync. Clearing search calls showFolderView()
    // which restores folderTbodyHtml — without this, a removed folder reappears.
    if (objectTbody && objectTable?.dataset?.searching !== "1") {
      folderTbodyHtml = objectTbody.innerHTML;
    }
    refreshTabMetrics();
    syncToolbar();
  }

  function stripRemovedListRows(objectIds, folderPaths) {
    /** Re-drop rows after soft reload in case SSR briefly lagged the DB commit. */
    const idSet = new Set((objectIds || []).map(String).filter(Boolean));
    const folderSet = new Set(
      (folderPaths || []).map((path) => String(path || "").replace(/\\/g, "/")).filter(Boolean)
    );
    if (!idSet.size && !folderSet.size) return;
    const rowsToStrip = rows().filter((row) => {
      if (idSet.has(String(row.dataset.uuid || ""))) return true;
      if (!row.classList.contains("folder-row")) return false;
      return folderSet.has(String(row.dataset.folder || "").replace(/\\/g, "/"));
    });
    if (rowsToStrip.length) removeSelectedRowsFromDom(rowsToStrip);
  }
  // Soft boot replaces closures — Remove awaits reload then calls this global.
  window.__creopdmStripRemovedListRows = stripRemovedListRows;

  function formatPurgeConfirmDetails(preview) {
    const deleted = [...(Array.isArray(preview?.ok) ? preview.ok : [])].sort((a, b) => {
      const left = String(a.message || a.filename || a.path || "");
      const right = String(b.message || b.filename || b.path || "");
      try {
        return left.localeCompare(right, undefined, { numeric: true, sensitivity: "base" });
      } catch {
        return left.localeCompare(right);
      }
    });
    const floors = Array.isArray(preview?.floors) ? preview.floors : [];
    const parts = [];
    if (deleted.length) {
      parts.push(
        `<p><strong>${deleted.length}</strong> local save(s) would move to the Recycle Bin:</p>`
      );
      const shown = deleted.slice(0, 20);
      const items = shown
        .map((item) => {
          const name = escapeHtml(item.message || item.filename || item.path || "");
          return `<li><code>${name}</code></li>`;
        })
        .join("");
      const more =
        deleted.length > shown.length
          ? `<li class="muted">…and ${deleted.length - shown.length} more</li>`
          : "";
      parts.push(`<ul class="confirm-file-list">${items}${more}</ul>`);
    } else {
      parts.push("<p>No older local saves match the vault floors right now.</p>");
    }
    if (floors.length) {
      parts.push(
        "<p>Kept for each vault model: the revision matching the vault and any newer local numbered saves. Examples:</p>"
      );
      const floorShown = floors.slice(0, 8);
      const floorItems = floorShown
        .map((item) => {
          const path = escapeHtml(item.logical_path || "");
          const keep = Number(item.min_keep) || 0;
          const keepLabel = keep <= 0 ? "unnumbered / .1+" : `.${keep} and newer`;
          return `<li><code>${path}</code> — keep ${escapeHtml(keepLabel)}</li>`;
        })
        .join("");
      const floorMore =
        floors.length > floorShown.length
          ? `<li class="muted">…and ${floors.length - floorShown.length} more model(s)</li>`
          : "";
      parts.push(`<ul class="confirm-file-list">${floorItems}${floorMore}</ul>`);
    }
    parts.push(
      "<p>Unrelated local files, the vault revision, newer local saves, and everything in the vault stay. On Windows, purged files go to the Recycle Bin.</p>"
    );
    return parts.join("");
  }

  function projectHome() {
    return document.querySelector(".crumb a")?.href || "/";
  }

  removeMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleRemoveMenu();
  });
  removeMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeRemoveMenu();
  });
  openMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleOpenMenu();
  });
  openMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeOpenMenu();
  });
  addMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleAddMenu();
  });
  addMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeAddMenu();
  });
  checkoutMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleCheckoutMenu();
  });
  checkoutMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeCheckoutMenu();
  });
  checkinMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleCheckinMenu();
  });
  checkinMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeCheckinMenu();
  });
  document.addEventListener("click", (event) => {
    const node = eventEl(event);
    if (removeMenu?.classList.contains("is-open") && !removeMenu.contains(node)) closeRemoveMenu();
    if (addMenu?.classList.contains("is-open") && !addMenu.contains(node)) closeAddMenu();
    if (openMenu?.classList.contains("is-open") && !openMenu.contains(node)) closeOpenMenu();
    if (checkoutMenu?.classList.contains("is-open") && !checkoutMenu.contains(node)) closeCheckoutMenu();
    if (checkinMenu?.classList.contains("is-open") && !checkinMenu.contains(node)) closeCheckinMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeAllToolbarMenus();
  });

  function openCreateFolderDialog() {
    showError($("#create-folder-error"), "");
    const nameInput = $("#create-folder-name");
    if (nameInput) nameInput.value = "";
    const location = $("#create-folder-location");
    const folder = currentFolder();
    if (location) {
      location.textContent = folder
        ? `Creates a folder under ${folder}.`
        : "Creates a folder at the project root.";
    }
    createFolderDialog?.showModal();
    nameInput?.focus();
  }

  $("#create-folder-btn")?.addEventListener("click", () => {
    closeAddMenu();
    openCreateFolderDialog();
  });
  $("#create-folder-cancel")?.addEventListener("click", () => createFolderDialog?.close());
  createFolderForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectId = createFolderForm.dataset.project || addForm?.dataset.project;
    if (!projectId) return;
    const name = String(new FormData(createFolderForm).get("name") || "").trim();
    if (!name) {
      showError($("#create-folder-error"), "Enter a folder name.");
      return;
    }
    showError($("#create-folder-error"), "");
    const response = await withBusy("Creating folder…", () =>
      fetch(`/api/projects/${projectId}/folders`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name,
          parent_folder: currentFolder() || "",
        }),
      })
    );
    if (!response.ok) {
      showError($("#create-folder-error"), await readError(response));
      return;
    }
    createFolderDialog?.close();
    reloadPage();
  });

  purgeBtn?.addEventListener("click", async () => {
    const selected = selectedRows();
    const pathRows = selected.filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache !== "1"
    );
    const objectRows = selected.filter((row) => !isNewFileQueueRow(row));
    let ids = objectRows.flatMap(rowObjectIds);
    if (!ids.length && !pathRows.length) ids = selectedIds();
    const paths = [
      ...new Set(pathRows.map((row) => row.dataset.relativePath).filter(Boolean)),
    ];
    const total = ids.length + paths.length;
    if (!total) return;
    const confirmed = await confirmByProjectName({
      title: total === 1 ? "Remove from vault" : `Remove ${total} files from vault`,
      lead:
        total === 1
          ? "Only the CreoPDM vault copy is deleted. The original in your project folder stays. If you have it checked out, that checkout is cancelled."
          : "Only CreoPDM vault copies are deleted. Originals in your project folder stay. Your checkouts on those files are cancelled.",
      note: "This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Vault",
    });
    if (!confirmed.ok) return;

    let okCount = 0;
    let warning = "";
    if (paths.length) {
      const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
      if (!projectId) return;
      const result = await postAction(
        `/api/projects/${projectId}/workspace/purge-paths`,
        { relative_paths: paths },
        "POST",
        "Removing from vault…"
      );
      if (!result) return;
      okCount += result.ok?.length || 0;
      warning = formatBatch(result) || warning;
    }
    if (ids.length) {
      if (ids.length === 1 && !isListPage && !paths.length) {
        const result = await postAction(
          `/api/objects/${ids[0]}/purge-workspace`,
          undefined,
          "POST",
          "Removing from vault…"
        );
        if (result) reloadPage();
        return;
      }
      const result = await postAction(
        "/api/objects/batch/purge-workspace",
        { object_ids: ids },
        "POST",
        "Removing from vault…"
      );
      if (!result) return;
      okCount += result.ok?.length || 0;
      warning = formatBatch(result) || warning;
    }
    if (warning) showError($("#toolbar-error"), warning);
    else if (okCount) showOk(`${okCount} file(s) removed from the vault.`);
    if (okCount) reloadPage();
  });

  discardLocalBtn?.addEventListener("click", async () => {
    const selected = selectedRows().filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache === "1"
    );
    const paths = [
      ...new Set(selected.map((row) => row.dataset.relativePath).filter(Boolean)),
    ];
    if (!paths.length) return;
    const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
    if (!projectId) return;
    const confirmed = await confirmByProjectName({
      title: paths.length === 1 ? "Remove from workspace" : `Remove ${paths.length} files from workspace`,
      lead:
        paths.length === 1
          ? "This moves the file from the local workspace on this PC (creopdm-agent cache) to the Recycle Bin. The vault and project list are unchanged."
          : "These files move from the local workspace on this PC (creopdm-agent cache) to the Recycle Bin. The vault and project list are unchanged.",
      note: "This cannot be undone from CreoPDM. Restore from the Recycle Bin on this PC if needed.",
      submitLabel: "Remove from Workspace",
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    const result = await withBusy("Removing from local workspace…", async () => {
      try {
        return await deleteLocalWorkspacePaths(projectId, paths);
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return false;
      }
    });
    if (result === false) return;
    if (!result) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to delete local workspace files."
      );
      return;
    }
    if (result.failed?.length && !result.ok?.length) {
      showError(
        $("#toolbar-error"),
        result.failed[0]?.message || "Could not delete local workspace files."
      );
      return;
    }
    knownWorkspacePaths.at = 0;
    const removed = result.ok?.length || 0;
    if (removed) showOk(`${removed} file(s) removed from the local workspace.`);
    if (activeListTab() === "changes") await loadChangesTab();
    else reloadPage();
    pollWorkspaceWatch();
  });

  purgeVersionsBtn?.addEventListener("click", async () => {
    const projectId =
      purgeVersionsBtn.dataset.project
      || checkinBtn?.dataset.project
      || openWorkspaceBtn?.dataset.project;
    if (!projectId) return;
    showError($("#toolbar-error"), "");
    const preview = await withBusy("Checking what Purge workspace would delete…", async () => {
      try {
        return await purgeLocalVersionsOlderThanVault(projectId, { dryRun: true });
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return false;
      }
    });
    if (preview === false) return;
    if (!preview) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to purge older local workspace saves."
      );
      return;
    }
    if (preview.empty) {
      showOk("Nothing to purge — no vault Creo models with numbered saves.");
      return;
    }
    const wouldDelete = preview.deleted || preview.ok?.length || 0;
    if (!wouldDelete) {
      showOk(
        "Nothing to purge — no older local saves below the vault revision (vault copy and newer local work are kept)."
      );
      return;
    }
    const confirmed = await confirmByProjectName({
      title: "Purge workspace",
      lead: `About to move ${wouldDelete} older local Creo model save(s) from the agent cache to the Recycle Bin on this PC. The vault revision and any newer local work stay. The vault is not changed.`,
      detailsHtml: formatPurgeConfirmDetails(preview),
      note: "This cannot be undone from CreoPDM. Restore from the Recycle Bin on this PC if needed.",
      submitLabel: `Purge ${wouldDelete} save(s)`,
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    const result = await withBusy("Purging older local saves…", async () => {
      try {
        return await purgeLocalVersionsOlderThanVault(projectId);
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return false;
      }
    });
    if (result === false) return;
    if (!result) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to purge older local workspace saves."
      );
      return;
    }
    if (result.empty) {
      showOk("Nothing to purge — no vault Creo models with numbered saves.");
      return;
    }
    if (result.failed?.length && !result.ok?.length) {
      showError(
        $("#toolbar-error"),
        result.failed[0]?.message || "Could not purge older local workspace saves."
      );
      return;
    }
    knownWorkspacePaths.at = 0;
    const removed = result.deleted || result.ok?.length || 0;
    if (removed) showOk(`${removed} older local save(s) purged.`);
    else showOk("No older local saves to purge.");
    if (activeListTab() === "changes") await loadChangesTab();
    else pollWorkspaceWatch();
  });

  removeBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    const folderPaths = selectedFolderPaths();
    if (!ids.length && !folderPaths.length) return;
    const removeCount = Math.max(ids.length, folderPaths.length);
    if (!confirmLargeBulk("Remove", removeCount)) return;
    const selected = selectedRows();
    const projectId =
      removeBtn.dataset.project
      || checkinBtn?.dataset.project
      || openWorkspaceBtn?.dataset.project
      || currentProjectId();
    const confirmed = await confirmByProjectName({
      title:
        folderPaths.length && !ids.length
          ? folderPaths.length === 1
            ? "Remove folder from project"
            : `Remove ${folderPaths.length} folders from project`
          : ids.length === 1
            ? "Remove from project"
            : `Remove ${ids.length} files from project`,
      lead:
        folderPaths.length
          ? "CreoPDM vault copies under the selected folder(s) are deleted. Originals in your project folder are not deleted."
          : ids.length === 1
            ? "CreoPDM vault copies are deleted. The original in your project folder is not deleted."
            : "CreoPDM vault copies are deleted. Originals in your project folder are not deleted.",
      note: "Removed from this project list. This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Project",
      workspaceOption: true,
    });
    if (!confirmed.ok) return;
    const deleteWorkspaceFiles = Boolean(confirmed.deleteWorkspaceFiles);
    const workspacePaths = deleteWorkspaceFiles
      ? workspacePathsForRemovedObjects(projectId, selected)
      : [];
    removeSelectedRowsFromDom(selected);
    if (ids.length === 1 && !folderPaths.length && !isListPage) {
      const result = await postAction(`/api/objects/${ids[0]}`, null, "DELETE", "Removing from project…");
      if (!result) {
        reloadPage({ keepBusy: true });
        return;
      }
      if (deleteWorkspaceFiles && projectId && workspacePaths.length) {
        deleteLocalWorkspacePathsBackground(projectId, workspacePaths);
      }
      window.location.href = projectHome();
      return;
    }
    const result = await postAction(
      "/api/objects/batch/remove",
      {
        object_ids: ids,
        folder_paths: folderPaths,
        project_id: projectId || null,
      },
      "POST",
      removeCount > 100
        ? `Removing ${removeCount} items from project…`
        : "Removing from project…"
    );
    if (!result) {
      reloadPage({ keepBusy: true });
      return;
    }
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length && deleteWorkspaceFiles && projectId && workspacePaths.length) {
      deleteLocalWorkspacePathsBackground(projectId, workspacePaths);
      if (!warning) {
        showOk(
          `${result.ok.length} item(s) removed from the project. Local workspace cleanup continues in the background.`
        );
      }
    } else if (result.ok?.length && !warning) {
      const files = (result.ok || []).filter((item) => item.status === "removed").length;
      const folders = (result.ok || []).filter((item) => item.status === "folder_removed").length;
      if (folders && !files) {
        showOk(folders === 1 ? "Folder removed from the project." : `${folders} folders removed.`);
      } else if (folders) {
        showOk(`${files} file(s) and ${folders} folder(s) removed from the project.`);
      } else {
        showOk(`${files} file(s) removed from the project.`);
      }
    }
    if (result.ok?.length) {
      await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
      // Soft SSR can still briefly include deleted rows; keep the list honest.
      // Use the post-boot global — this handler's closure is from the prior boot.
      window.__creopdmStripRemovedListRows?.(ids, folderPaths);
    }
  });

  async function loadChangesTab(options = {}) {
    const quiet = Boolean(options.quiet);
    const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
    const body = $("#changes-table tbody");
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (!projectId || !body) return 0;
    if (!quiet) {
      body.replaceChildren();
      const loading = document.createElement("tr");
      loading.className = "empty-row";
      const loadingCell = document.createElement("td");
      loadingCell.colSpan = 5;
      loadingCell.textContent = "Looking for vault and local workspace changes…";
      loading.appendChild(loadingCell);
      body.appendChild(loading);
      refreshTabMetrics();
    }
    try {
      const [queueResponse, cacheFiles, objectsResponse] = await Promise.all([
        fetch(`/api/projects/${projectId}/checkin-queue`),
        listAgentCacheFiles(projectId),
        fetch(`/api/projects/${encodeURIComponent(projectId)}/objects`),
      ]);
      if (!queueResponse.ok) throw new Error("queue");
      const data = await queueResponse.json();
      const objects = objectsResponse.ok
        ? await objectsResponse.json().catch(() => [])
        : [];
      cachedProjectObjects = {
        id: projectId,
        at: Date.now(),
        rows: Array.isArray(objects) ? objects : [],
      };
      const saves = data.saves || [];
      const vaultNew = data.new_files || [];
      const known = await loadKnownWorkspacePaths(
        projectId,
        vaultNew.map((item) => item.relative_path || "")
      );
      const created = [...vaultNew, ...localOnlyCacheFiles(cacheFiles, known)];
      const vaultSaveIds = new Set(
        saves.map((item) => String(item.uuid || "")).filter(Boolean)
      );
      const newerLocal = newerLocalCacheSaves(cacheFiles, objects).filter(
        (item) => !vaultSaveIds.has(String(item.uuid || ""))
      );
      const pending = saves.length + created.length + newerLocal.length;
      if (tab) tab.textContent = pending ? `New files · ${pending}` : "New files";
      setCheckinQueueCounts(saves.length + newerLocal.length, created.length);
      lastChangesPending = pending;
      body.replaceChildren();
      if (!pending) {
        const row = document.createElement("tr");
        row.className = "empty-row";
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "No new or changed vault or local workspace files.";
        row.appendChild(cell);
        body.appendChild(row);
        refreshTabMetrics();
        // Still merge vault/agent pending so list State stays accurate without this tab.
        void refreshPendingCheckinIds(projectId);
        return pending;
      }
      const addRow = (values, className, meta = {}) => {
        const row = document.createElement("tr");
        if (className) row.className = className;
        row.classList.add("queue-row");
        const filename = meta.filename || values[1] || "";
        const ext = filenameExtension(filename);
        row.dataset.filename = filename;
        row.dataset.extension = ext;
        row.dataset.objectType = meta.objectType || typeFromExtension(ext);
        row.dataset.checkedOut = meta.checkedOut || "0";
        row.dataset.canCheckin = meta.canCheckin || "1";
        row.dataset.canCheckout = meta.canCheckout || "0";
        row.dataset.inWorkspace = "1";
        if (meta.uuid) row.dataset.uuid = meta.uuid;
        if (meta.relativePath) row.dataset.relativePath = meta.relativePath;
        if (meta.localCache) row.dataset.localCache = "1";
        if (meta.uuid && projectId) {
          row.dataset.detail = `/projects/${projectId}/objects/${meta.uuid}#history`;
        }
        values.forEach((text, index) => {
          const cell = document.createElement("td");
          if (index === 1) {
            cell.className = "filename-cell";
            const wrap = document.createElement("span");
            wrap.className = "name-with-icon";
            const objectType = row.dataset.objectType || "";
            const typeLabel = meta.typeLabel || "";
            const iconInfo = resolveTypeIcon({
              objectType,
              typeLabel,
              extension: ext,
              filename,
            });
            if (iconInfo.file) {
              const icon = document.createElement("img");
              icon.className = "type-icon";
              icon.src = `/static/icons/${iconInfo.file}`;
              icon.alt = iconInfo.label || "File";
              icon.title = iconInfo.label || "File";
              icon.width = 14;
              icon.height = 14;
              icon.decoding = "async";
              wrap.appendChild(icon);
            }
            // Use a span — Creo/CEF paints an opaque fill on <button> that shows as a white band.
            const link = document.createElement("span");
            link.className = "object-open";
            link.setAttribute("role", "link");
            link.tabIndex = 0;
            link.textContent = filename;
            link.title = "Open this file";
            if (meta.uuid) link.dataset.uuid = meta.uuid;
            if (meta.relativePath) link.dataset.relativePath = meta.relativePath;
            wrap.appendChild(link);
            cell.appendChild(wrap);
            const noteText = meta.recordedFilename
              ? `from ${meta.recordedFilename}`
              : meta.relativePath && meta.relativePath !== filename
                ? meta.relativePath
                : "";
            if (noteText) {
              const note = document.createElement("div");
              note.className = "muted small";
              note.textContent = noteText;
              cell.appendChild(note);
            }
          } else {
            cell.textContent = text;
          }
          row.appendChild(cell);
        });
        body.appendChild(row);
      };
      saves.forEach((item) => {
        addRow(
          [
            item.newer_save ? "Newer Creo save" : "Modified",
            item.filename || "",
            `${item.next_display || "—"} · not checked in`,
            item.file_size != null ? formatByteSize(item.file_size) : "",
            item.saved_at || "",
          ],
          "is-pending",
          {
            filename: item.filename,
            uuid: item.uuid,
            objectType: item.object_type,
            checkedOut: "1",
            recordedFilename: item.newer_save ? item.recorded_filename : "",
          }
        );
      });
      newerLocal.forEach((item) => {
        addRow(
          [
            "Newer local save",
            item.filename || "",
            item.can_checkin === "1"
              ? "Local workspace — select and Check In."
              : "Local workspace — check out to Check In.",
            item.size != null ? formatByteSize(item.size) : "",
            item.saved_at || "—",
          ],
          "is-pending",
          {
            filename: item.filename,
            uuid: item.uuid,
            objectType: item.object_type,
            relativePath: item.relative_path,
            localCache: true,
            checkedOut: item.checked_out || "0",
            canCheckin: item.can_checkin || "0",
            canCheckout: item.can_checkout || "0",
            recordedFilename: item.recorded_filename || "",
          }
        );
      });
      created.forEach((item) => {
        addRow(
          [
            item.local_cache ? "New file (local)" : "New file",
            item.filename || "",
            item.local_cache
              ? "Local workspace — select and Add."
              : "Not in the project yet. Select and click Add.",
            item.size != null ? formatByteSize(item.size) : "",
            item.saved_at || "—",
          ],
          "",
          {
            filename: item.filename,
            objectType: item.object_type,
            relativePath: item.relative_path,
            localCache: Boolean(item.local_cache),
          }
        );
      });
      rememberPendingCheckinIds([
        ...saves.map((item) => item.uuid),
        ...newerLocal
          .filter((item) => item.can_checkin === "1")
          .map((item) => item.uuid),
      ]);
      refreshTabMetrics();
      return pending;
    } catch {
      if (!quiet) {
        body.replaceChildren();
        const row = document.createElement("tr");
        row.className = "empty-row";
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "Could not load vault changes.";
        row.appendChild(cell);
        body.appendChild(row);
        refreshTabMetrics();
      }
      return lastChangesPending || 0;
    }
  }

  async function loadCheckedOutTab() {
    const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
    const body = $("#checked-out-table tbody");
    if (!projectId || !body) return;
    body.replaceChildren();
    const loading = document.createElement("tr");
    loading.className = "empty-row";
    const loadingCell = document.createElement("td");
    loadingCell.colSpan = 7;
    loadingCell.textContent = "Looking for checked-out files…";
    loading.appendChild(loadingCell);
    body.appendChild(loading);
    refreshTabMetrics();
    try {
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/checkouts`);
      if (!response.ok) throw new Error("checkouts");
      const items = await response.json();
      const list = Array.isArray(items) ? items : [];
      setCheckedOutTabCount(list.length);
      if (!list.length) {
        body.innerHTML = `<tr class="empty-row"><td colspan="7">No files are checked out.</td></tr>`;
        refreshTabMetrics();
        return;
      }
      body.innerHTML = list.map((item) => searchRowHtml(item, projectId)).join("");
      refreshTabMetrics();
      syncModifiedStateLabels();
    } catch {
      body.replaceChildren();
      const row = document.createElement("tr");
      row.className = "empty-row";
      const cell = document.createElement("td");
      cell.colSpan = 7;
      cell.textContent = "Could not load checked-out files.";
      row.appendChild(cell);
      body.appendChild(row);
      refreshTabMetrics();
    }
  }

  function showHistorySubtab(name) {
    document.querySelectorAll(".subtab").forEach((item) => {
      item.classList.toggle("is-active", item.dataset.subtab === name);
    });
    document.querySelectorAll(".subtab-panel").forEach((panel) => {
      panel.hidden = panel.id !== `subpanel-${name}`;
    });
  }

  document.querySelectorAll(".tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      if (tab.disabled) return;
      const name = tab.dataset.tab;
      document.querySelectorAll(".tabs .tab").forEach((item) => item.classList.toggle("is-active", item === tab));
      document.querySelectorAll(".tab-panel").forEach((panel) => {
        panel.hidden = panel.id !== `panel-${name}`;
      });
      if (name === "changes") loadChangesTab();
      else if (name === "checked-out") void loadCheckedOutTab();
      else if (name === "where-used") void loadWhereUsedTab();
      else refreshTabMetrics();
    });
  });

  let whereUsedLoaded = false;
  async function loadWhereUsedTab() {
    const panel = $("#panel-where-used");
    if (!panel || panel.dataset.lazyWhereUsed !== "1" || whereUsedLoaded) return;
    const objectId = panel.dataset.objectId || "";
    const projectId = panel.dataset.projectId || "";
    if (!objectId) return;
    whereUsedLoaded = true;
    const host = $("#where-used-host");
    try {
      // Fast path first (deps + BOM). Full vault byte-scan is capped server-side
      // on large projects so this request cannot hang the service.
      const response = await fetch(
        `/api/objects/${encodeURIComponent(objectId)}/where-used`
      );
      if (!response.ok) {
        if (host) {
          host.innerHTML = `<p class="muted">Could not load Where Used (${await readError(response)}).</p>`;
        }
        return;
      }
      const body = await response.json();
      const items = Array.isArray(body.items) ? body.items : [];
      if (!host) return;
      if (!items.length) {
        host.innerHTML =
          '<p class="muted">Not listed in any captured assembly/drawing BOM in this project yet. Open parent assemblies in Creo and Add or Check In to capture Where Used. (Vault byte-scan is skipped when the project has many assemblies, so the server stays responsive.)</p>';
        return;
      }
      const rows = items
        .map((row) => {
          const href = projectId
            ? `/projects/${encodeURIComponent(projectId)}/objects/${encodeURIComponent(row.object_id || "")}`
            : "#";
          const sub =
            row.relative_path && row.relative_path !== row.filename
              ? `<div class="muted small">${escapeHtml(row.relative_path)}</div>`
              : "";
          return `<tr>
            <td class="filename-cell"><a href="${href}">${escapeHtml(row.filename || "")}</a>${sub}</td>
            <td>${escapeHtml(row.type_label || "")}</td>
            <td>${escapeHtml(row.display_revision || "")}</td>
            <td>${escapeHtml(String(row.quantity ?? 1))}</td>
            <td>${escapeHtml(row.dependency_type || "")}</td>
          </tr>`;
        })
        .join("");
      host.innerHTML = `<table class="grid" id="where-used-table">
        <thead><tr><th>Filename</th><th>Type</th><th>Rev</th><th>Qty</th><th>Relation</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
    } catch (err) {
      if (host) {
        host.innerHTML = `<p class="muted">Could not load Where Used (${escapeHtml(err?.message || "error")}).</p>`;
      }
    }
  }

  document.querySelectorAll(".subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      showHistorySubtab(tab.dataset.subtab);
    });
  });

  if (window.location.hash === "#history" || window.location.hash === "#file-history") {
    document.querySelector('.tab[data-tab="history"]')?.click();
    showHistorySubtab("files");
  } else if (window.location.hash === "#versions") {
    document.querySelector('.tab[data-tab="history"]')?.click();
    showHistorySubtab("versions");
  } else if (window.location.hash === "#changes") {
    document.querySelector('.tab[data-tab="changes"]')?.click();
  } else if (window.location.hash === "#checked-out") {
    document.querySelector('.tab[data-tab="checked-out"]')?.click();
  }

  function syncCreoStatusPill(mode, parametricPath, viewPath) {
    const pill = $("#creo-status");
    if (!pill) return;
    const key = String(mode || "association");
    pill.dataset.creoOpenMode = key;
    void refreshCreoStatusPill();
  }

  settingsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError($("#settings-error"), "");
    const ok = $("#settings-ok");
    if (ok) ok.hidden = true;
    const data = new FormData(settingsForm);
    const body = {
      creo_open_mode: String(data.get("creo_open_mode") || "association"),
      creo_executable: null,
      creo_view_executable: null,
      creo_js_library: String(data.get("creo_js_library") || "").trim() || null,
      workspace_root: String(data.get("workspace_root") || "").trim() || null,
      cad_model_extensions: String(data.get("cad_model_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      cad_models_extensions: String(data.get("cad_models_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      document_extensions: String(data.get("document_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      cad_openable_extensions: String(data.get("cad_openable_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      cad_extensions: String(data.get("cad_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      purgeable_extensions: String(data.get("purgeable_extensions") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      ignore_patterns: String(data.get("ignore_patterns") || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean),
      database_url: String(data.get("database_url") || "").trim(),
      port: (() => {
        const raw = String(data.get("port") || "").trim();
        if (!raw) return 0;
        const parsed = Number.parseInt(raw, 10);
        return Number.isFinite(parsed) ? parsed : 0;
      })(),
      agent_base_url: String(data.get("agent_base_url") || "").trim(),
      workspace_poll_interval_ms: (() => {
        const raw = String(data.get("workspace_poll_interval_ms") || "").trim();
        if (!raw) return 2000;
        const parsed = Number.parseInt(raw, 10);
        return Number.isFinite(parsed) ? parsed : 2000;
      })(),
    };
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      showError($("#settings-error"), await readError(response));
      return;
    }
    if (ok) ok.hidden = false;
    const saved = await response.json().catch(() => null);
    const workspaceInput = settingsForm.querySelector('[name="workspace_root"]');
    if (workspaceInput && saved?.workspace_root) {
      workspaceInput.value = saved.workspace_root;
    }
    syncCreoStatusPill(
      body.creo_open_mode,
      body.creo_executable,
      body.creo_view_executable
    );
  });

  const typeLabelsForm = $("#type-labels-form");
  const typeLabelRows = $("#type-label-rows");
  function typeLabelRow(extension = "", label = "") {
    const tr = document.createElement("tr");
    const extTd = document.createElement("td");
    const extInput = document.createElement("input");
    extInput.name = "extension";
    extInput.type = "text";
    extInput.value = extension;
    extInput.placeholder = ".stp, .step";
    extInput.autocomplete = "off";
    extTd.appendChild(extInput);
    const labelTd = document.createElement("td");
    const labelInput = document.createElement("input");
    labelInput.name = "label";
    labelInput.type = "text";
    labelInput.value = label;
    labelInput.placeholder = "STEP Model";
    labelInput.autocomplete = "off";
    labelTd.appendChild(labelInput);
    const actionTd = document.createElement("td");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "btn btn-small type-label-remove";
    remove.textContent = "Remove";
    actionTd.appendChild(remove);
    tr.append(extTd, labelTd, actionTd);
    return tr;
  }
  $("#type-label-add")?.addEventListener("click", () => {
    typeLabelRows?.appendChild(typeLabelRow());
  });
  typeLabelRows?.addEventListener("click", (event) => {
    const button = eventEl(event)?.closest(".type-label-remove");
    if (!button) return;
    button.closest("tr")?.remove();
    if (typeLabelRows && !typeLabelRows.querySelector("tr")) {
      typeLabelRows.appendChild(typeLabelRow());
    }
  });
  typeLabelsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError($("#settings-error"), "");
    const ok = $("#settings-ok");
    if (ok) ok.hidden = true;
    const type_labels = [...(typeLabelRows?.querySelectorAll("tr") || [])]
      .map((row) => ({
        extension: String(row.querySelector("[name=extension]")?.value || "").trim(),
        label: String(row.querySelector("[name=label]")?.value || "").trim(),
      }))
      .filter((item) => item.extension || item.label);
    const body = {
      creo_open_mode: String(new FormData(typeLabelsForm).get("creo_open_mode") || "association"),
      type_labels,
    };
    const response = await fetch("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      showError($("#settings-error"), await readError(response));
      return;
    }
    if (ok) ok.hidden = false;
    syncCreoStatusPill(body.creo_open_mode);
  });

  heartbeat.ids = rows()
    .filter((row) => row.dataset.owned === "1")
    .map((row) => row.dataset.uuid)
    .filter(Boolean);
  if (undoBtn?.dataset.uuid && !undoBtn.disabled) {
    heartbeat.ids.push(undoBtn.dataset.uuid);
  }
  if (heartbeat.ids.length) {
    // One write for all of my checkouts — avoid N concurrent POSTs during bulk ops.
    heartbeat.timer = trackedInterval(() => {
      fetch("/api/objects/batch/heartbeat", { method: "POST" });
    }, 60000);
  }

  const WATCH_KEY = "creopdmWatchRestore";
  function rememberWatchView(overrides = {}) {
    try {
      const activeTab =
        overrides.tab ??
        document.querySelector(".tabs .tab.is-active")?.dataset.tab ??
        "";
      const ids = overrides.ids ?? selectedIds();
      sessionStorage.setItem(
        WATCH_KEY,
        JSON.stringify({
          ids,
          tab: activeTab,
        })
      );
    } catch {
      /* private mode / blocked storage */
    }
  }
  function restoreWatchView() {
    let raw = null;
    try {
      raw = sessionStorage.getItem(WATCH_KEY);
      if (raw) sessionStorage.removeItem(WATCH_KEY);
    } catch {
      return;
    }
    if (!raw) return;
    let saved;
    try {
      saved = JSON.parse(raw);
    } catch {
      return;
    }
    if (saved.tab) {
      document.querySelector(`.tabs .tab[data-tab="${saved.tab}"]`)?.click();
      if (saved.tab === "history") {
        window.history.replaceState(null, "", "#history");
      }
    }
    const wanted = new Set(saved.ids || []);
    if (wanted.size) {
      rows().forEach((row) => markRowSelected(row, wanted.has(row.dataset.uuid)));
      syncToolbar();
    }
  }
  restoreWatchView();

  function watchPaused() {
    if (document.hidden || busyDepth > 0) return true;
    // Ignore the busy overlay — it is also a <dialog>, and keepBusy reload leaves it open.
    return [...document.querySelectorAll("dialog[open]")].some((dialog) => dialog.id !== "busy-overlay");
  }

  const watchProjectId = openWorkspaceBtn?.dataset.project || addForm?.dataset.project;
  let watchStamp = null;
  let watchReloadTimer = 0;
  let lastPendingCheckinCount = null;

  async function pollWorkspaceWatch() {
    if (!watchProjectId || watchPaused()) return;
    try {
      const [response, localPending] = await Promise.all([
        fetch(`/api/projects/${watchProjectId}/workspace-watch`),
        countLocalWorkspacePending(watchProjectId),
      ]);
      if (!response.ok) return;
      const data = await response.json();
      const localTotal = Number(localPending.localNew || 0) + Number(localPending.newerLocal || 0);
      const pending =
        Number(data.pending_saves || 0) + Number(data.new_files || 0) + localTotal;
      setCheckinQueueCounts(
        Number(data.pending_saves || 0) + Number(localPending.newerLocal || 0),
        Number(data.new_files || 0) + Number(localPending.localNew || 0)
      );
      if (lastPendingCheckinCount === null || lastPendingCheckinCount !== pending) {
        lastPendingCheckinCount = pending;
        void refreshPendingCheckinIds(watchProjectId);
      }
      // Local agent-cache saves do not change the vault stamp — refresh the open tab in place.
      if (activeListTab() === "changes") {
        if (lastChangesPending === null) {
          lastChangesPending = pending;
        } else if (pending !== lastChangesPending && !changesReloadBusy) {
          changesReloadBusy = true;
          knownWorkspacePaths.at = 0;
          cachedProjectObjects.at = 0;
          try {
            await loadChangesTab({ quiet: true });
          } finally {
            changesReloadBusy = false;
          }
        }
      } else {
        lastChangesPending = pending;
      }
      const next = data.stamp || "";
      if (watchStamp === null) {
        watchStamp = next;
        return;
      }
      if (next === watchStamp) return;
      watchStamp = next;
      knownWorkspacePaths.at = 0; // vault changed — refresh known paths on next count
      cachedProjectObjects.at = 0;
      window.clearTimeout(watchReloadTimer);
      watchReloadTimer = window.setTimeout(() => {
        if (watchPaused()) return;
        rememberWatchView();
        reloadPage();
      }, 400);
    } catch {
      /* ignore a missed poll */
    }
  }

  if (watchProjectId) {
    const pollMsRaw = Number.parseInt(document.body?.dataset?.workspacePollMs || "5000", 10);
    const pollMs = Number.isFinite(pollMsRaw) ? Math.min(120000, Math.max(500, pollMsRaw)) : 5000;
    trackedInterval(pollWorkspaceWatch, pollMs);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) pollWorkspaceWatch();
    });
    pollWorkspaceWatch();
  }

  document.querySelector(".detail-head .object-open")?.addEventListener("click", async (event) => {
    event.preventDefault();
    const link = event.currentTarget;
    const id = link?.dataset?.uuid;
    if (!id) return;
    const owned = Boolean(undoBtn && !undoBtn.disabled);
    const canCheckout = Boolean(checkoutBtn && !checkoutBtn.disabled);
    await openPdmObjectFromUi(id, {
      dataset: {
        filename: link.textContent?.trim() || id,
        canCheckout: canCheckout ? "1" : "0",
        owned: owned ? "1" : "0",
      },
    });
  });

  document.addEventListener("click", (event) => {
    const link = eventEl(event)?.closest("#panel-structure .object-open, #panel-bom .object-open");
    if (!link) return;
    event.preventDefault();
    const id = link.dataset.uuid;
    if (!id) return;
    void openPdmObjectFromUi(id, {
      dataset: {
        filename: link.textContent?.trim() || id,
        canCheckout: "1",
        owned: "0",
      },
    });
  });

  // Keep Creo.JS connected: soft-navigate shell pages (projects, folders, settings, detail).
  // Do not gate on inCreoBrowser — a false negative caused hard reloads that SSR-paint
  // "Not Connected" and drop the live Creo.JS bridge.
  document.addEventListener(
    "click",
    (event) => {
      const link = eventEl(event)?.closest("a[href]");
      if (!link || event.defaultPrevented) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      if (event.button != null && event.button !== 0) return;
      if (link.target && link.target !== "_self") return;
      // Folder name opens via onFileTableClick → leavePage; skip soft-nav here so
      // row chrome clicks still select without navigating.
      if (link.classList.contains("folder-open") || link.closest("tr.folder-row")) return;
      const href = link.getAttribute("href");
      if (!href || !isSoftNavUrl(href)) return;
      event.preventDefault();
      event.stopPropagation();
      void withBusy("Loading…", () => softNavigate(href, "push"));
    },
    true
  );

  window.addEventListener("popstate", () => {
    if (!isSoftNavUrl(window.location.href)) return;
    void withBusy("Loading…", () => softNavigate(window.location.href, "none"));
  });

  restoreStoredFilters();
  syncToolbar();
  const pendingProjectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
  if (pendingProjectId) void refreshPendingCheckinIds(pendingProjectId);

  } finally {
    EventTarget.prototype.addEventListener = origAddEventListener;
  }
};

window.__creopdmBoot({ soft: false });
