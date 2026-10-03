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
  // Soft product switches re-run this boot; abort prior listeners via signal.
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

  function agentBase() {
    const fromBody = (document.body?.dataset?.agentBase || "").trim();
    return fromBody || "http://127.0.0.1:8766";
  }

  function agentPdmToken() {
    return String(document.body?.dataset?.agentToken || "").trim();
  }

  /** Fields the local agent forwards to CreoPDM (Bearer = signed-in user). */
  function agentPdmAuth() {
    const token = agentPdmToken();
    return token ? { token } : {};
  }

  /** Browser → localhost agent: Authorization required when Origin is present. */
  function agentAuthHeaders(extra = {}) {
    const headers = { ...extra };
    const token = agentPdmToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    return headers;
  }

  function eventEl(event) {
    const node = event?.target;
    if (!node) return null;
    return node.nodeType === 1 ? node : node.parentElement;
  }

  /** Admin user form: All products checkbox enables/disables the multi-select. */
  function syncProductAccessUi(root = document) {
    const all = root.querySelector("#access-all-products");
    const list = root.querySelector("#product-access-list");
    if (!all || !list || String(list.tagName || "").toUpperCase() !== "SELECT") return;
    const locked = Boolean(all.checked);
    list.disabled = locked;
    list.classList.toggle("is-disabled", locked);
    if (locked) list.setAttribute("aria-disabled", "true");
    else list.removeAttribute("aria-disabled");
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

  function withTimeout(promise, ms, message) {
    let timer = 0;
    return Promise.race([
      Promise.resolve(promise).finally(() => {
        if (timer) window.clearTimeout(timer);
      }),
      new Promise((_, reject) => {
        timer = window.setTimeout(() => {
          reject(new Error(message || "Timed out."));
        }, ms);
      }),
    ]);
  }

  function abortSignalAfter(ms) {
    if (typeof AbortSignal !== "undefined" && typeof AbortSignal.timeout === "function") {
      return AbortSignal.timeout(ms);
    }
    const controller = new AbortController();
    window.setTimeout(() => controller.abort(), ms);
    return controller.signal;
  }

  function closeOpenDialogs({ keepBusy = false } = {}) {
    document.querySelectorAll("dialog[open]").forEach((dialog) => {
      // Never dismiss the busy overlay while setBusy depth is open (Collect, Add, …).
      if (dialog.id === "busy-overlay" && (keepBusy || busyDepth > 0)) return;
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
      if (path === "/admin" || path === "/admin/users" || path === "/admin/roles") return true;
      if (path === "/admin/roles/new" || /^\/admin\/roles\/[^/]+\/?$/.test(path)) return true;
      if (path === "/admin/users/new" || /^\/admin\/users\/[^/]+\/?$/.test(path)) return true;
      if (path === "/settings" || path === "/settings/types") return true;
      if (/^\/products\/[^/]+\/objects\/[^/]+\/?$/.test(path)) return true;
      return false;
    } catch {
      return false;
    }
  }

  let softNavBusy = false;
  // Serialize soft navigations so a refresh after Remove is never dropped, and
  // callers can await the real shell swap (the old queue resolved too early).
  let softNavTail = Promise.resolve();
  // Declared early so softNavigate / leavePage / reloadPage can block mid-Collect.
  const metadataCollectJob = { running: false, cancel: false };

  function softNavigate(url, historyMode = "push") {
    if (metadataCollectJob.running) {
      showOk("Finish Collect metadata (or wait for it) before leaving this page.");
      return Promise.resolve();
    }
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
        // Keep signed-in identity + caps in sync with the session that served this HTML.
        // Soft-nav only swaps main.shell; without this, a stale header/watch state can linger.
        const nextBody = doc.body;
        if (nextBody) {
          [
            "data-agent-token",
            "data-can-checkout",
            "data-can-checkin",
            "data-can-force-undo-checkout",
            "data-can-view",
            "data-can-copy-to-vault",
            "data-agent-base",
            "data-workspace-poll-ms",
          ].forEach((attr) => {
            if (nextBody.hasAttribute(attr)) {
              document.body.setAttribute(attr, nextBody.getAttribute(attr) || "");
            }
          });
        }
        const nextCluster = doc.querySelector(".status-cluster");
        const curCluster = document.querySelector(".status-cluster");
        if (nextCluster && curCluster) {
          const creo = curCluster.querySelector("#creo-status");
          curCluster.innerHTML = nextCluster.innerHTML;
          const placeholder = curCluster.querySelector("#creo-status");
          if (creo && placeholder) placeholder.replaceWith(creo);
        }
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
    if (metadataCollectJob.running) {
      showOk("Finish Collect metadata (or wait for it) before leaving this page.");
      return;
    }
    closeOpenDialogs();
    // Always soft-nav shell pages — hard reload SSR-paints Not Connected and kills Creo.JS.
    if (isSoftNavUrl(url)) {
      void withBusy("Loading…", () => softNavigate(url, "push"));
      return;
    }
    window.location.href = url;
  }

  function reloadPage(options = {}) {
    if (metadataCollectJob.running) {
      showOk("Finish Collect metadata (or wait for it) before refreshing.");
      return;
    }
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
      row.dataset.canCheckout = item.can_checkout ? "1" : "0";
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
        const label = item.checkout_status || (item.can_checkout ? "Available" : "Locked");
        state.dataset.state = item.can_checkout ? "available" : "locked";
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

  function productLockedCheckoutLabel() {
    // Server-painted product lock on #metric-filters — keep undo paint truthful.
    const el = $("#metric-filters");
    if (!el || el.dataset.allowsMutation == null || el.dataset.allowsMutation === "") {
      return null;
    }
    if (el.dataset.allowsMutation === "1") return null;
    if (el.dataset.readOnly === "1") return "Read only";
    const key = String(el.dataset.productState || "").trim().toUpperCase();
    const labels = {
      IN_WORK: "In work",
      ON_HOLD: "On hold",
      RELEASED: "Released",
      CLOSED: "Closed",
      ARCHIVED: "Archived",
    };
    return labels[key] || "Locked";
  }

  function applyUndoCheckoutOnRows(uuids) {
    /** Paint checkout column immediately when reload is slow or ignored. */
    const ids = new Set(
      (uuids || []).map((id) => String(id || "").trim()).filter(Boolean)
    );
    if (!ids.size) return;
    stopHeartbeats([...ids]);
    const lockedLabel = productLockedCheckoutLabel();
    const text = lockedLabel || "Available";
    const kind = lockedLabel ? "locked" : "available";
    const canCheckout = lockedLabel ? "0" : "1";
    rows().forEach((row) => {
      const id = row.dataset.uuid;
      if (!id || !ids.has(id)) return;
      row.dataset.owned = "0";
      row.dataset.checkedOut = "0";
      row.dataset.canCheckin = "0";
      row.dataset.canCheckout = canCheckout;
      row.dataset.modifiedLocally = "0";
      const state = row.querySelector(".checkout-state");
      if (state) {
        state.dataset.state = kind;
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
      state.dataset.state = kind;
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
    folders: null,
    creo_parts: ["CREO_PART"],
    assemblies: ["CREO_ASSEMBLY"],
    drawings: ["CREO_DRAWING"],
    documents: ["PDF", "DOCUMENT", "SPREADSHEET", "TEXT", "IMAGE"],
    other: ["PDF", "DOCUMENT", "SPREADSHEET", "TEXT", "IMAGE", "OTHER"],
  };
  const CAD_MODEL_CHILD_FILTERS = new Set(["creo_parts", "assemblies", "drawings"]);
  const METRIC_LABELS = {
    folders: "folders",
    files: "all files",
    cad_models: "Creo models",
    creo_parts: "parts",
    assemblies: "assemblies",
    drawings: "drawings",
    documents: "documents",
    other: "files that are not Creo models",
    modified: "modified files",
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
    if (key === "folders") {
      return row.classList.contains("folder-row");
    }
    if (key === "checked_out") {
      return rowAttr(row, "data-checked-out") === "1" || row.dataset.checkedOut === "1";
    }
    if (key === "modified") {
      const uuid = String(row.dataset.uuid || "").trim();
      const owned = row.dataset.owned === "1" || row.dataset.canCheckin === "1";
      const dirty = Boolean(
        rowAttr(row, "data-modified-locally") === "1"
          || row.dataset.modifiedLocally === "1"
          || (uuid && pendingCheckinIds.has(uuid))
      );
      return owned && dirty;
    }
    if (row.classList.contains("folder-row")) return false;
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
    if ([".xml", ".ncl", ".lst"].includes(key)) return "TEXT";
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

  function listedFolderRows() {
    const root = fileListRoot();
    if (!root) return [];
    if (root.id === "panel-changes" || root.id === "changes-table") return [];
    if (root.id === "panel-checked-out" || root.id === "checked-out-table") return [];
    return [...root.querySelectorAll(".folder-row")];
  }

  function updateMetricCounts() {
    rememberMetricCounts();
    const root = fileListRoot();
    const filesTab = !root || root.id === "panel-files" || root.id === "object-table";
    const searching = $("#object-table")?.dataset.searching === "1";
    const files = listedMetricRows();
    const folderRows = listedFolderRows();
    if (filesTab && !searching) {
      metricButtons().forEach((btn) => {
        const strong = btn.querySelector("strong");
        if (!strong) return;
        const key = metricKey(btn);
        if (key === "folders") {
          strong.textContent = String(folderRows.length);
          return;
        }
        // Type chips stay on the SSR folder snapshot. Checkout/modified update
        // after agent + check-in probes paint dirty rows — recount those.
        if (isStateMetric(key)) {
          strong.textContent = String(
            files.filter((row) => rowMatchesMetric(row, key)).length
          );
          return;
        }
        strong.textContent = btn.dataset.folderCount || "0";
      });
      return;
    }
    metricButtons().forEach((btn) => {
      const strong = btn.querySelector("strong");
      if (!strong) return;
      const key = metricKey(btn);
      if (key === "folders") {
        strong.textContent = String(folderRows.length);
        return;
      }
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
    if (key === "folders") {
      btn.title = mode === "off"
        ? "Filter to folders and select them. Click again to clear."
        : "Showing folders (selected). Click to clear.";
      return;
    }
    if (key === "checked_out") {
      btn.title = mode === "off"
        ? "Filter to checked out files in the current group and select them. Click again to clear."
        : "Showing checked out files (selected). Click to clear.";
      return;
    }
    if (key === "modified") {
      btn.title = mode === "off"
        ? "Filter to modified files in the current group and select them. Click again to clear."
        : "Showing modified files (selected). Click to clear.";
      return;
    }
    btn.title = mode === "off"
      ? `Filter to ${label} and select them. Click again to clear.`
      : `Filtering to ${label} (selected). Click to clear.`;
  }

  function isStateMetric(key) {
    return key === "checked_out" || key === "modified";
  }

  function activeStateMetricKeys(metrics) {
    return metrics
      .filter((btn) => isStateMetric(metricKey(btn)) && metricMode(btn) === "filter")
      .map((btn) => metricKey(btn));
  }

  function setRowHidden(row, hide) {
    row.classList.toggle("is-row-hidden", hide);
    if (hide) row.setAttribute("hidden", "");
    else row.removeAttribute("hidden");
  }

  function rowIsHidden(row) {
    return row.classList.contains("is-row-hidden");
  }

  function parseSearchAnchors(query) {
    let q = String(query || "").trim();
    const anchoredStart = q.startsWith("^");
    if (anchoredStart) q = q.slice(1);
    const anchoredEnd = q.endsWith("$");
    if (anchoredEnd) q = q.slice(0, -1);
    return { body: q, anchoredStart, anchoredEnd };
  }

  function globToRegExp(pattern) {
    const body = String(pattern || "")
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*/g, ".*")
      .replace(/\?/g, ".");
    return new RegExp(`^${body}$`, "i");
  }

  function rowMatchesSearchQuery(row, query) {
    const raw = String(query || "").trim();
    if (!raw) return true;
    const { body, anchoredStart, anchoredEnd } = parseSearchAnchors(raw);
    if (!body) return true;
    const name = rowFilename(row) || "";
    const path = String(row.dataset.relativePath || row.dataset.folder || "").replace(/\\/g, "/");
    const base = path.split("/").pop() || "";
    // Type column label (data-sort-type is "folder/TYPE").
    const typeLabel = String(row.dataset.sortType || "").includes("/")
      ? String(row.dataset.sortType || "").split("/").pop() || ""
      : String(row.dataset.sortType || "");
    const objectType = String(row.dataset.objectType || "");
    if (body.includes("*") || body.includes("?")) {
      let re;
      try {
        re = globToRegExp(body);
      } catch {
        return false;
      }
      return (
        re.test(name)
        || re.test(path)
        || (base && re.test(base))
        || (typeLabel && re.test(typeLabel))
        || (objectType && re.test(objectType))
      );
    }
    const needle = body.toLowerCase();
    const fields = [name, path, base, typeLabel, objectType]
      .filter(Boolean)
      .map((item) => item.toLowerCase());
    if (anchoredStart || anchoredEnd) {
      return fields.some((text) => {
        if (anchoredStart && anchoredEnd) return text === needle;
        if (anchoredStart) return text.startsWith(needle);
        return text.endsWith(needle);
      });
    }
    if (fields.some((text) => text.includes(needle))) return true;
    return (row.textContent || "").toLowerCase().includes(needle);
  }

  function applyMetricVisibility() {
    const metrics = metricButtons();
    const typeFilterBtns = metrics.filter((btn) => {
      return !isStateMetric(metricKey(btn)) && metricMode(btn) === "filter";
    });
    const stateKeys = activeStateMetricKeys(metrics);
    const typeRestricts = typeFilterBtns.length > 0 || stateKeys.length > 0;
    const viewBtns = metrics.filter((btn) => {
      const key = metricKey(btn);
      if (isStateMetric(key)) return false;
      const mode = metricMode(btn);
      if (mode === "off" || !typeRestricts) return false;
      if (mode === "select" && isParentMetric(key) && typeFilterBtns.length) return false;
      return true;
    });
    const foldersOnly =
      viewBtns.length > 0 && viewBtns.every((btn) => metricKey(btn) === "folders");
    const foldersFilterOn = viewBtns.some((btn) => metricKey(btn) === "folders");
    const fileTypeFilterOn = viewBtns.some((btn) => {
      const key = metricKey(btn);
      return key !== "folders" && key !== "files";
    });
    const q = ($("#search-input")?.value || "").trim();
    const searchingAll = $("#object-table")?.dataset.searching === "1";
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        const matchesSearch = searchingAll ? false : rowMatchesSearchQuery(row, q);
        if (Boolean(q) && !matchesSearch) {
          setRowHidden(row, true);
          return;
        }
        // Creo Models / Parts / … without Folders: hide folder rows.
        // Files alone (Folders off) still shows folders, unselected.
        if (fileTypeFilterOn && !foldersFilterOn) {
          setRowHidden(row, true);
          return;
        }
        setRowHidden(row, false);
        return;
      }
      if (foldersOnly) {
        setRowHidden(row, true);
        return;
      }
      const matchesSearch = searchingAll || rowMatchesSearchQuery(row, q);
      const matchesView = !viewBtns.length || viewBtns.some((btn) => rowMatchesMetric(row, metricKey(btn)));
      const matchesState = !stateKeys.length || stateKeys.every((key) => rowMatchesMetric(row, key));
      setRowHidden(row, !(matchesSearch && matchesView && matchesState));
    });
  }

  function applyMetricSelection() {
    // Select and filter both keep matching rows selected (sticky while the pill is on).
    const selecting = metricButtons().filter((btn) => {
      const mode = metricMode(btn);
      return mode === "select" || mode === "filter";
    });
    if (!selecting.length) return;
    const typeActive = selecting.filter((btn) => !isStateMetric(metricKey(btn)));
    const stateKeys = selecting.filter((btn) => isStateMetric(metricKey(btn))).map((btn) => metricKey(btn));
    const foldersSelecting = typeActive.some((btn) => metricKey(btn) === "folders");
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        // Folder selection follows the Folders pill only — never stick after it turns off.
        markRowSelected(row, foldersSelecting && !rowIsHidden(row));
        return;
      }
      const matchesType = !typeActive.length || typeActive.some((btn) => rowMatchesMetric(row, metricKey(btn)));
      const matchesState = !stateKeys.length || stateKeys.every((key) => rowMatchesMetric(row, key));
      markRowSelected(row, matchesType && matchesState && !rowIsHidden(row));
    });
  }

  function metricSelectionActive() {
    return metricButtons().some((btn) => {
      const mode = metricMode(btn);
      return mode === "select" || mode === "filter";
    });
  }

  const productDialog = $("#product-dialog");
  const productForm = $("#product-form");
  const addDialog = $("#add-dialog");
  const addForm = $("#add-form");
  const checkinDialog = $("#checkin-dialog");
  const checkinForm = $("#checkin-form");
  const settingsForm = $("#settings-form");

  const workspaceEl = document.querySelector(".workspace");
  const productSidebar = document.querySelector(".sidebar");
  const productMenuBtn = $("#product-menu-btn");
  const sidebarCollapseBtn = $("#sidebar-collapse-btn");
  function closeProductMenu() {
    productSidebar?.classList.remove("is-open");
    productMenuBtn?.setAttribute("aria-expanded", "false");
  }
  function sidebarCollapsed() {
    return Boolean(workspaceEl?.classList.contains("is-sidebar-collapsed"));
  }
  function syncSidebarCollapse() {
    const collapsed = sidebarCollapsed();
    const label = collapsed ? "Show product list" : "Collapse product list";
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
    closeProductMenu();
    syncSidebarCollapse();
    rememberSidebarCollapse(sidebarCollapsed());
  });
  function toggleProductMenu(event) {
    event.stopPropagation();
    const open = productSidebar?.classList.toggle("is-open");
    productMenuBtn?.setAttribute("aria-expanded", open ? "true" : "false");
  }
  productMenuBtn?.addEventListener("click", toggleProductMenu);
  document.addEventListener("click", (event) => {
    if (!productSidebar?.classList.contains("is-open")) return;
    if (productSidebar.contains(event.target)) return;
    closeProductMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProductMenu();
  });

  $("#new-product-btn")?.addEventListener("click", () => {
    closeProductMenu();
    showProductDialog("create");
  });
  const productSettings = $("#product-settings");
  const productSettingsBtn = $("#product-settings-btn");
  const productSettingsMenu = $("#product-settings-menu");
  function closeProductSettings() {
    productSettings?.classList.remove("is-open");
    if (productSettingsMenu) productSettingsMenu.hidden = true;
    productSettingsBtn?.setAttribute("aria-expanded", "false");
  }
  function toggleProductSettings(event) {
    event.stopPropagation();
    const open = !productSettings?.classList.contains("is-open");
    if (open) {
      productSettings?.classList.add("is-open");
      if (productSettingsMenu) productSettingsMenu.hidden = false;
      productSettingsBtn?.setAttribute("aria-expanded", "true");
    } else {
      closeProductSettings();
    }
  }
  productSettingsBtn?.addEventListener("click", toggleProductSettings);
  document.addEventListener("click", (event) => {
    if (!productSettings?.classList.contains("is-open")) return;
    if (productSettings.contains(event.target)) return;
    closeProductSettings();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeProductSettings();
  });

  function applyProductWatchState(btn, watching) {
    if (!btn) return;
    const on = Boolean(watching);
    btn.dataset.watching = on ? "1" : "0";
    btn.classList.toggle("is-watching", on);
    btn.setAttribute("aria-pressed", on ? "true" : "false");
    btn.setAttribute("aria-label", on ? "Stop watching product" : "Watch product");
    if (btn.dataset.canWatch === "1") {
      btn.title = on ? "Watching — click to stop" : "Watch this product";
    }
  }

  function applyProductWatchPayload(btn, body) {
    if (!btn || !body) return;
    const can = Boolean(body.can_watch);
    btn.dataset.canWatch = can ? "1" : "0";
    btn.dataset.reason = body.reason || "";
    btn.disabled = !can;
    if (!can) {
      btn.title = (body.reason || "").trim() || "Watching unavailable";
    }
    applyProductWatchState(btn, Boolean(body.watching));
  }

  async function syncProductWatchFromServer() {
    const btn = $("#product-watch-btn");
    if (!btn) return;
    const productId = btn.dataset.product || "";
    if (!productId) return;
    try {
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/watch`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (!response.ok) return;
      const body = await response.json().catch(() => null);
      if (body) applyProductWatchPayload(btn, body);
    } catch {
      /* best-effort — SSR attributes remain */
    }
  }

  function confirmProductWatch(watching) {
    const dialog = $("#product-watch-dialog");
    const form = $("#product-watch-form");
    const titleEl = $("#product-watch-title");
    const leadEl = $("#product-watch-lead");
    const confirmBtn = $("#product-watch-confirm");
    const cancelBtn = $("#product-watch-cancel");
    if (!dialog || !form || !titleEl || !leadEl || !confirmBtn) {
      return Promise.resolve(
        window.confirm(watching ? "Stop watching this product?" : "Watch this product for email updates?")
      );
    }
    const name = $("#product-watch-btn")?.dataset.productName || "this product";
    titleEl.textContent = watching ? "Stop watching" : "Watch product";
    leadEl.textContent = watching
      ? `Stop email notifications for activity in ${name}?`
      : `Get email when files change in ${name}?`;
    confirmBtn.textContent = watching ? "Stop watching" : "Watch";
    return new Promise((resolve) => {
      const finish = (ok) => {
        form.removeEventListener("submit", onSubmit);
        cancelBtn?.removeEventListener("click", onCancel);
        dialog.removeEventListener("cancel", onDialogCancel);
        if (dialog.open) dialog.close();
        resolve(ok);
      };
      const onSubmit = (event) => {
        event.preventDefault();
        finish(true);
      };
      const onCancel = () => finish(false);
      const onDialogCancel = (event) => {
        event.preventDefault();
        finish(false);
      };
      form.addEventListener("submit", onSubmit);
      cancelBtn?.addEventListener("click", onCancel);
      dialog.addEventListener("cancel", onDialogCancel);
      dialog.showModal();
    });
  }

  $("#product-watch-btn")?.addEventListener("click", async () => {
    const btn = $("#product-watch-btn");
    if (!btn) return;
    if (btn.dataset.canWatch !== "1") {
      const reason = (btn.dataset.reason || "").trim() || "Watching is unavailable.";
      showError($("#toolbar-error"), reason);
      return;
    }
    const productId = btn.dataset.product || currentProductId();
    if (!productId) return;
    const watching = btn.dataset.watching === "1";
    const ok = await confirmProductWatch(watching);
    if (!ok) return;
    showError($("#toolbar-error"), "");
    const response = await fetch(`/api/products/${encodeURIComponent(productId)}/watch`, {
      method: watching ? "DELETE" : "POST",
    });
    if (!response.ok) {
      showError($("#toolbar-error"), await readError(response));
      return;
    }
    const body = await response.json().catch(() => ({}));
    applyProductWatchPayload(btn, body);
    showOk(body.watching ? "Watching this product." : "Stopped watching this product.");
  });

  // Authoritative per-session watch state (avoids stale SSR/cache across logins).
  void syncProductWatchFromServer();

  $("#rename-product-btn")?.addEventListener("click", () => {
    closeProductSettings();
    showProductDialog("rename");
  });
  $("#rebuild-where-used-btn")?.addEventListener("click", async () => {
    closeProductSettings();
    const productId = $("#rebuild-where-used-btn")?.dataset.product || currentProductId();
    if (!productId) return;
    showError($("#toolbar-error"), "");
    const response = await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`, {
      method: "POST",
    });
    if (!response.ok) {
      showError($("#toolbar-error"), await readError(response));
      return;
    }
    showOk("Where Used indexing started in the background.");
    watchWhereUsedIndex(productId);
  });

  function watchWhereUsedIndex(productId) {
    if (!productId) return;
    let tries = 0;
    const tick = async () => {
      tries += 1;
      try {
        const response = await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`);
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
    const productId = currentProductId();
    if (!productId) return;
    try {
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`);
      if (!response.ok) return;
      const body = await response.json();
      const state = String(body.state || "");
      if (state === "queued" || state === "running") {
        watchWhereUsedIndex(productId);
      }
    } catch {
      /* ignore */
    }
  }

  resumeWhereUsedIndexWatch();

  const METADATA_COLLECT_WARN_THRESHOLD = 50;
  const METADATA_COLLECT_KEY = "creopdmMetadataCollect";
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
      `Capture parameters, materials, units, features, and BOM/structure for ${total} Creo model(s) in this product. ` +
      "Each model is retrieved in the Creo session when needed. Mass properties are not collected (unsupported in silent Collect).";
    if (warn) {
      if (total > METADATA_COLLECT_WARN_THRESHOLD) {
        warn.hidden = false;
        warn.textContent =
          `This is ${total} models (over ${METADATA_COLLECT_WARN_THRESHOLD}). It can take a long time and may make Creo sluggish. A busy overlay stays up until Collect finishes — keep this CreoPDM window open.`;
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

  function confirmExportZip({ title, lead }) {
    const dialog = $("#export-confirm-dialog");
    const form = $("#export-confirm-form");
    const titleEl = $("#export-confirm-title");
    const leadEl = $("#export-confirm-lead");
    const cancelBtn = $("#export-confirm-cancel");
    if (!(dialog instanceof HTMLDialogElement) || !form || !titleEl || !leadEl) {
      return Promise.resolve(window.confirm(`${title}\n\n${lead}`));
    }
    titleEl.textContent = title || "Export…";
    leadEl.textContent = lead || "";
    return new Promise((resolve) => {
      const finish = (ok) => {
        form.removeEventListener("submit", onSubmit);
        cancelBtn?.removeEventListener("click", onCancel);
        dialog.removeEventListener("cancel", onDialogCancel);
        if (dialog.open) dialog.close();
        resolve(ok);
      };
      const onSubmit = (event) => {
        event.preventDefault();
        finish(true);
      };
      const onCancel = () => finish(false);
      const onDialogCancel = (event) => {
        event.preventDefault();
        finish(false);
      };
      form.addEventListener("submit", onSubmit);
      cancelBtn?.addEventListener("click", onCancel);
      dialog.addEventListener("cancel", onDialogCancel);
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
    setBusy("Collecting Creo metadata…");
    let index = Math.max(0, Number(state.index) || 0);
    let captured = Number(state.captured) || 0;
    let failed = Number(state.failed) || 0;
    let lastReason = "";
    let shouldRefreshList = false;
    try {
      while (index < targets.length) {
        if (metadataCollectJob.cancel) break;
        const target = targets[index];
        const message =
          `Collecting Creo metadata… ${index + 1} of ${targets.length}: ${target.filename}` +
          ` (${captured} saved, ${failed} skipped` +
          (lastReason ? `, last: ${lastReason}` : "") +
          `)`;
        setBusyMessage(message);
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
          setBusyMessage(pauseMsg);
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
      // Type column (SHEETMETAL / MFG / …) comes from SSR — refresh Files after saves.
      shouldRefreshList = captured > 0;
    } finally {
      clearBusy();
      metadataCollectJob.running = false;
      metadataCollectJob.cancel = false;
      syncMetadataCollectControls();
    }
    if (shouldRefreshList) {
      await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
    }
  }

  async function runCollectAllMetadata(productId) {
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
      existing.productId === productId &&
      Array.isArray(existing.targets) &&
      existing.targets.length
    ) {
      await runMetadataCollectLoop(existing);
      return;
    }
    const rows = await ensureProductObjects(productId, { force: true });
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
      productId,
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
    const productId = currentProductId();
    if (productId && state.productId && productId !== state.productId) {
      showOk(
        `Metadata collection paused for another product (${state.index || 0} of ${state.targets.length}).`
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
    closeProductSettings();
    const productId = $("#collect-metadata-btn")?.dataset.product || currentProductId();
    if (!productId) return;
    await runCollectAllMetadata(productId);
  });

  resumeMetadataCollectIfNeeded();
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) resumeMetadataCollectIfNeeded();
  });
  window.addEventListener("pageshow", () => {
    resumeMetadataCollectIfNeeded();
  });
  window.addEventListener("beforeunload", (event) => {
    if (!metadataCollectJob.running) return;
    event.preventDefault();
    event.returnValue = "";
  });

  $("#product-cancel")?.addEventListener("click", () => productDialog?.close());

  const deleteProductDialog = $("#delete-product-dialog");
  const deleteProductForm = $("#delete-product-form");
  $("#delete-product-btn")?.addEventListener("click", () => {
    closeProductSettings();
    if (metadataCollectJob.running) {
      showOk("Finish Collect metadata (or cancel it) before deleting this product.");
      return;
    }
    const btn = $("#delete-product-btn");
    showError($("#delete-product-error"), "");
    if (deleteProductForm) deleteProductForm.reset();
    const deleteLocal = $("#delete-local-workspace");
    if (deleteLocal) deleteLocal.checked = true;
    deleteProductDialog?.showModal();
  });
  $("#delete-product-cancel")?.addEventListener("click", () => deleteProductDialog?.close());
  deleteProductForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("#delete-product-btn");
    const productId = btn?.dataset.product;
    const expected = (btn?.dataset.name || "").trim();
    if (!productId) return;
    const formData = new FormData(deleteProductForm);
    const typed = String(formData.get("confirm_name") || "").trim();
    if (typed !== expected) {
      showError($("#delete-product-error"), "Type the product name exactly to delete it.");
      return;
    }
    const deleteLocal = Boolean($("#delete-local-workspace")?.checked);
    const vaultFolder = currentVaultFolder();
    let result;
    try {
      result = await withBusy("Deleting product…", async () => {
        const notices = [];
        if (deleteLocal) {
          const agent = await probeCreoAgent();
          if (!agent) {
            notices.push(
              "creopdm-agent is not running — local workspace on this PC was not deleted."
            );
          } else {
            try {
              const localResponse = await fetch(`${agentBase()}/delete-product-cache`, {
                method: "POST",
                headers: agentAuthHeaders({ "Content-Type": "application/json" }),
                body: JSON.stringify({
                  product_id: productId,
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
        const forgetResponse = await fetch(`/api/products/${productId}/forget`, {
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
        $("#delete-product-error"),
        exc?.message || "Could not delete the product."
      );
      return;
    }
    if (result?.warning) sessionStorage.setItem("creopdmNotice", result.warning);
    clearProductViewStorage(productId);
    leavePage("/");
  });

  function showProductDialog(mode) {
    if (!productForm || !productDialog) return;
    showError($("#product-error"), "");
    const title = $("#product-dialog-title");
    const submit = $("#product-submit");
    const vaultFields = $("#product-vault-fields");
    productForm.dataset.mode = mode;
    if (mode === "rename") {
      const btn = $("#rename-product-btn");
      if (title) title.textContent = "Rename product";
      productForm.elements.name.value = btn?.dataset.name || "";
      productForm.elements.number.value = btn?.dataset.number || "";
      productForm.elements.description.value = btn?.dataset.description || "";
      if (vaultFields) vaultFields.hidden = true;
      if (submit) submit.textContent = "Save";
    } else {
      productForm.reset();
      if (title) title.textContent = "New product";
      if (submit) submit.textContent = "Create";
      if (vaultFields) vaultFields.hidden = false;
      productVaultCustom = "";
      productVaultCustomTouched = false;
      productVaultHash = "";
      const useHash = $("#product-use-hash");
      if (useHash) useHash.checked = true;
      syncProductVaultFolderField(true);
    }
    productDialog.showModal();
  }

  let productVaultHash = "";
  let productVaultCustom = "";
  let productVaultCustomTouched = false;

  function newProductVaultHash() {
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
    const input = $("#product-vault-folder");
    const useHash = $("#product-use-hash");
    if (!input || useHash?.checked || productVaultCustomTouched) return;
    const slug = slugifyVaultFolder(productForm?.elements?.name?.value || "");
    input.value = slug;
    productVaultCustom = slug;
  }

  function syncProductVaultFolderField(resetHash) {
    const input = $("#product-vault-folder");
    const useHash = $("#product-use-hash");
    if (!input || !useHash) return;
    if (resetHash || !productVaultHash) productVaultHash = newProductVaultHash();
    if (useHash.checked) {
      input.value = productVaultHash;
      input.disabled = true;
      input.readOnly = true;
    } else {
      input.disabled = false;
      input.readOnly = false;
      if (!productVaultCustomTouched) {
        fillVaultFolderFromName();
      } else {
        input.value = productVaultCustom || "";
      }
    }
  }

  $("#product-use-hash")?.addEventListener("change", () => {
    const useHash = $("#product-use-hash");
    if (useHash?.checked) {
      productVaultCustomTouched = false;
      syncProductVaultFolderField(true);
    } else {
      syncProductVaultFolderField(false);
      $("#product-vault-folder")?.focus();
      $("#product-vault-folder")?.select();
    }
  });

  productForm?.elements?.name?.addEventListener("input", () => {
    fillVaultFolderFromName();
  });

  $("#product-vault-folder")?.addEventListener("input", () => {
    const useHash = $("#product-use-hash");
    if (useHash?.checked) return;
    productVaultCustomTouched = true;
    productVaultCustom = String($("#product-vault-folder")?.value || "").trim();
  });

  productForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(productForm);
    const renaming = productForm.dataset.mode === "rename";
    const body = {
      name: String(data.get("name") || "").trim(),
      number: String(data.get("number") || "").trim() || null,
      description: String(data.get("description") || "").trim() || null,
    };
    if (!renaming) {
      const useHash = Boolean($("#product-use-hash")?.checked);
      let vaultFolder = String(data.get("vault_folder") || "").trim();
      if (useHash) {
        body.vault_folder = productVaultHash || newProductVaultHash();
      } else {
        // Custom vault name must be provided (not blank).
        if (!vaultFolder) {
          showError($("#product-error"), "Enter a vault/workspace name, or check Use hash.");
          $("#product-vault-folder")?.focus();
          return;
        }
        if (/\s/.test(vaultFolder)) {
          showError($("#product-error"), "Vault/workspace name cannot contain spaces.");
          return;
        }
        body.vault_folder = vaultFolder;
      }
    }
    if (!body.name) {
      showError($("#product-error"), "A product name is required.");
      return;
    }
    const productId = $("#rename-product-btn")?.dataset.product;
    const url = renaming ? `/api/products/${productId}` : "/api/products";
    const response = await withBusy(renaming ? "Saving product…" : "Creating product…", () =>
      fetch(url, {
        method: renaming ? "PATCH" : "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      })
    );
    if (!response.ok) {
      showError($("#product-error"), await readError(response));
      return;
    }
    const product = await response.json();
    leavePage(`/?product=${encodeURIComponent(product.uuid)}`);
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
    const keepRootRow = $("#add-keep-root-row");
    const keepRootHint = $("#add-keep-root-hint");
    const keepRoot = $("#add-keep-root-folder");
    const showKeepRoot = resolved === "folders" || resolved === "folder";
    if (keepRootRow) keepRootRow.hidden = !showKeepRoot;
    if (keepRootHint) keepRootHint.hidden = !showKeepRoot;
    if (keepRoot && showKeepRoot) keepRoot.checked = true;
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

  function keepRootFolder() {
    const el = $("#add-keep-root-folder");
    const row = $("#add-keep-root-row");
    if (!el || row?.hidden) return true;
    return Boolean(el.checked);
  }

  function openAddDialog(mode) {
    showError($("#add-error"), "");
    clearAddSelection();
    configureAddDialog(mode);
    loadAddFolder();
    addDialog?.showModal();
  }

  async function loadAddFolder() {
    const productId = addForm?.dataset.product;
    const label = $("#add-folder-label");
    if (!productId || !label) return;
    const response = await fetch(`/api/products/${productId}/workspace/add-folder`);
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
  $("#add-compressed-btn")?.addEventListener("click", () => {
    closeAddMenu();
    openCompressedDialog();
  });
  $("#add-cancel")?.addEventListener("click", () => addDialog?.close());

  // Shared with form Add and Compressed data… (declared before both handlers use it).
  let addInFlight = false;
  const compressedDialog = $("#compressed-dialog");
  const compressedForm = $("#compressed-form");
  const compressedSummary = $("#compressed-file-summary");
  const compressedSubmit = $("#compressed-submit");
  let chosenZipPath = "";

  function setCompressedSummary(path) {
    chosenZipPath = String(path || "").trim();
    if (compressedSummary) {
      compressedSummary.textContent = chosenZipPath
        ? `Chosen: ${chosenZipPath}`
        : "No zip chosen yet.";
    }
    if (compressedSubmit instanceof HTMLButtonElement) {
      compressedSubmit.disabled = !chosenZipPath;
    }
  }

  function openCompressedDialog() {
    const productId = currentProductId();
    if (!productId) {
      showError($("#toolbar-error"), "Open a product first.");
      return;
    }
    showError($("#compressed-error"), "");
    setCompressedSummary("");
    const loc = $("#compressed-location");
    if (loc) {
      const name =
        document.querySelector(".product-title")?.textContent?.trim() ||
        document.body?.dataset?.productName ||
        "";
      loc.textContent = name ? `Product: ${name}` : "";
    }
    if (compressedForm) compressedForm.dataset.product = productId;
    compressedDialog?.showModal();
  }

  async function chooseCompressedZip() {
    showError($("#compressed-error"), "");
    const agent = await probeCreoAgent();
    if (!agent) {
      showError(
        $("#compressed-error"),
        "Start creopdm-agent on this Creo PC to add compressed data."
      );
      return;
    }
    compressedDialog?.close();
    setBusy("Waiting for file picker…");
    let pickResponse;
    try {
      pickResponse = await fetch(`${agentBase()}/pick-files`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          initial_directory: addInitialDirectory || "",
          title: "Choose a compressed zip file",
          filter_mode: "archive",
        }),
      });
    } finally {
      clearBusy();
    }
    if (!pickResponse.ok) {
      showError($("#compressed-error"), await readError(pickResponse));
      compressedDialog?.showModal();
      return;
    }
    let picked;
    try {
      picked = await pickResponse.json();
    } catch {
      showError($("#compressed-error"), "File picker returned invalid JSON.");
      compressedDialog?.showModal();
      return;
    }
    const selected = Array.isArray(picked?.selected) ? picked.selected : [];
    if (picked?.cancelled || !selected.length) {
      compressedDialog?.showModal();
      return;
    }
    const zipPath = String(selected[0] || "").trim();
    if (!/\.zip$/i.test(zipPath)) {
      showError($("#compressed-error"), "Choose a .zip file.");
      setCompressedSummary("");
      compressedDialog?.showModal();
      return;
    }
    setCompressedSummary(zipPath);
    compressedDialog?.showModal();
  }

  $("#compressed-choose-btn")?.addEventListener("click", () => {
    void chooseCompressedZip();
  });
  $("#compressed-cancel")?.addEventListener("click", () => compressedDialog?.close());
  compressedForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (addInFlight) {
      showError($("#compressed-error"), "Add is already running — wait for it to finish.");
      return;
    }
    const productId = compressedForm.dataset.product || currentProductId();
    if (!productId) {
      showError($("#compressed-error"), "Open a product first.");
      return;
    }
    if (!chosenZipPath) {
      showError($("#compressed-error"), "Choose a .zip file first.");
      return;
    }
    const agent = await probeCreoAgent();
    if (!agent) {
      showError(
        $("#compressed-error"),
        "Start creopdm-agent on this Creo PC to add compressed data."
      );
      return;
    }
    addInFlight = true;
    compressedDialog?.close();
    try {
      const result = await withBusy(
        "Uploading and importing compressed data…",
        async () => {
          const response = await fetch(`${agentBase()}/import-zip`, {
            method: "POST",
            headers: agentAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({
              pdm_url: window.location.origin,
              product_id: productId,
              zip_path: chosenZipPath,
              parent_folder: currentFolder() || "",
              ...agentPdmAuth(),
            }),
          });
          if (!response.ok) {
            throw new Error(await readError(response));
          }
          return response.json();
        }
      );
      const failed = result?.failed || [];
      const okCount = result?.ok?.length || 0;
      if (failed.length && !okCount) {
        const first = failed[0]?.message || "Could not import the zip.";
        showError($("#toolbar-error"), first);
        return;
      }
      if (failed.length && okCount) {
        const sample = failed
          .slice(0, 3)
          .map((item) => item.filename || "file")
          .join(", ");
        showError(
          $("#toolbar-error"),
          `Imported ${okCount} file(s); ${failed.length} failed (${sample}${failed.length > 3 ? ", …" : ""}).`
        );
      } else if (okCount) {
        showOk(`Imported ${okCount} file(s) from the zip.`);
      }
      if (okCount) reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
    } catch (err) {
      showError(
        $("#toolbar-error"),
        err?.message || "Could not import the compressed zip."
      );
    } finally {
      addInFlight = false;
      setCompressedSummary("");
    }
  });

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
    // Busy stays up after the OS dialog closes while the agent resolves latest
    // numbered saves (can take a while for thousands of files).
    setBusy("Waiting for file picker…");
    let pickResponse;
    try {
      pickResponse = await fetch(`${agentBase()}/pick-files`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          initial_directory: addInitialDirectory || "",
          title: "Add files to the product",
          purgeable_extensions: [...purgeableExtensionSet()],
        }),
      });
    } finally {
      clearBusy();
    }
    if (!pickResponse.ok) {
      showError($("#add-error"), await readError(pickResponse));
      return true;
    }
    setBusy("Preparing selection…");
    let picked;
    try {
      picked = await pickResponse.json();
    } finally {
      clearBusy();
    }
    const paths = Array.isArray(picked.selected) ? picked.selected : [];
    if (!paths.length) {
      if (!picked.cancelled) {
        showError(
          $("#add-error"),
          "No importable files in that selection. For large libraries, use Add folders… instead of Add files…"
        );
      }
      return true;
    }
    // Keep absolute paths on the agent — do not pull thousands of bodies into the browser.
    applyAgentPickedPaths(paths);
    return true;
  }

  async function browseViaAgentFolderPicker() {
    const agent = await probeCreoAgent();
    if (!agent) return false;
    const recursive = isRecursiveAddMode();
    setBusy("Waiting for folder picker…");
    let pickResponse;
    try {
      pickResponse = await fetch(`${agentBase()}/pick-folder`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          initial_directory: addInitialDirectory || "",
          title: recursive ? "Add folders to the product" : "Add a folder to the product",
          purgeable_extensions: [...purgeableExtensionSet()],
          recursive,
        }),
      });
    } finally {
      clearBusy();
    }
    if (!pickResponse.ok) {
      showError($("#add-error"), await readError(pickResponse));
      return true;
    }
    setBusy("Reading folder…");
    let picked;
    try {
      picked = await pickResponse.json();
    } finally {
      clearBusy();
    }
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
    const productId = addForm?.dataset.product;
    if (!productId) return;
    showError($("#add-error"), "");
    if (!useNativePicker()) {
      const usedAgent = await withHtmlDialogClosed(addDialog, () => browseViaAgentPicker());
      if (usedAgent) return;
      browseLocalFiles($("#add-file-input"));
      return;
    }
    await withHtmlDialogClosed(addDialog, async () => {
      const response = await fetch(`/api/products/${productId}/workspace/choose-files`, { method: "POST" });
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
    const productId = addForm?.dataset.product;
    if (!productId) return;
    showError($("#add-error"), "");
    if (!useNativePicker()) {
      const usedAgent = await withHtmlDialogClosed(addDialog, () => browseViaAgentFolderPicker());
      if (usedAgent) return;
      await browseLocalFolder();
      return;
    }
    await withHtmlDialogClosed(addDialog, async () => {
      const response = await withBusy("Choosing folder…", () =>
        fetch(`/api/products/${productId}/workspace/choose-folder`, { method: "POST" })
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
    return Boolean(btn && !btn.disabled && addForm?.dataset.product);
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

  addForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (addInFlight) {
      showError($("#add-error"), "Add is already running — wait for it to finish.");
      return;
    }
    const productId = addForm.dataset.product;
    if (!productId) return;
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
    const bulkCount =
      chosenAgentFolderBatches.reduce((sum, item) => sum + (item.paths?.length || 0), 0) ||
      chosenAgentPaths.length ||
      chosenPaths.length ||
      chosenUploads.length ||
      0;
    if (bulkCount && !confirmLargeBulk("Add", bulkCount)) return;
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
        // Stable History comment for every chunk (blank → "Add 935 files", not "Add 5 files").
        const effectiveComment =
          String(commentOnce || "").trim()
          || (total > 1 ? `Add ${total} files` : total === 1 ? `Add ${basenameOf(list[0])}` : "");
        for (let offset = 0; offset < list.length; offset += chunkSize) {
          const chunk = list.slice(offset, offset + chunkSize);
          const done = Math.min(offset + chunk.length, total);
          setBusyMessage(`Adding files… ${done} of ${total}`);
          let response;
          try {
            response = await fetch(`${agentBase()}/add-paths`, {
              method: "POST",
              headers: agentAuthHeaders({ "Content-Type": "application/json" }),
              body: JSON.stringify({
                pdm_url: window.location.origin,
                ...agentPdmAuth(),
                product_id: productId,
                absolute_paths: chunk,
                base_folder: baseFolder || "",
                keep_root_folder: keepRootFolder(),
                parent_folder: parentFolder,
                comment: effectiveComment || null,
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
            // Prefer typed comment; else full multi-folder pick count (not this folder alone).
            comment
              || (bulkCount > 1 ? `Add ${bulkCount} files` : "")
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
          const uploadComment =
            comment
            || (total > 1 ? `Add ${total} files` : total === 1 ? `Add ${chunk[0]?.file?.name || "file"}` : "");
          if (uploadComment) data.append("comment", uploadComment);
          data.append("batch_total", String(total));
          if (parentFolder) data.append("parent_folder", parentFolder);
          chunk.forEach((item) => {
            data.append("files", item.file, item.file.name);
            data.append("relative_paths", item.relativePath || item.file.name);
          });
          const response = await fetch(`/api/products/${productId}/objects/from-uploads`, {
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
          keep_root_folder: keepRootFolder(),
          comment: comment || null,
        };
      } else if (chosenBaseFolder) {
        payload = {
          folder: chosenBaseFolder,
          base_folder: chosenBaseFolder,
          recursive,
          parent_folder: parentFolder || "",
          keep_root_folder: keepRootFolder(),
          comment: comment || null,
        };
      } else {
        payload = {
          paths: chosenPaths,
          parent_folder: parentFolder || "",
          comment: comment || null,
        };
      }
      const response = await fetch(`/api/products/${productId}/objects/from-disk`, {
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

  function formatStampPretty(iso) {
    if (!iso) return "";
    let raw = String(iso).trim();
    // Already a short local stamp from the server (YYYY-MM-DD HH:MM).
    if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}$/.test(raw)) {
      const [ymd, hm] = raw.split(" ");
      const [y, mo, d] = ymd.split("-").map((n) => Number(n));
      const [hh, mm] = hm.split(":").map((n) => Number(n));
      const date = new Date(y, mo - 1, d, hh, mm);
      if (Number.isNaN(date.getTime())) return "";
      return formatLocalPrettyDate(date);
    }
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(raw) && !/[zZ]|[+-]\d{2}:?\d{2}$/.test(raw)) {
      raw += "Z";
    }
    const date = new Date(raw);
    if (Number.isNaN(date.getTime())) return "";
    return formatLocalPrettyDate(date);
  }

  function formatLocalPrettyDate(date) {
    const weekdays = [
      "Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    ];
    const months = [
      "January", "February", "March", "April", "May", "June",
      "July", "August", "September", "October", "November", "December",
    ];
    const hour24 = date.getHours();
    const hour12 = hour24 % 12 || 12;
    const ampm = hour24 < 12 ? "am" : "pm";
    const minute = String(date.getMinutes()).padStart(2, "0");
    return (
      `${weekdays[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()} `
      + `at ${hour12}:${minute}${ampm}`
    );
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

  function searchRowHtml(obj, productId) {
    const relative = String(obj.relative_path || obj.filename || "");
    const folder = folderOfPath(relative);
    const filename = String(obj.filename || "");
    const stamp = formatStamp(obj.updated_at);
    const stampPretty = formatStampPretty(obj.updated_at);
    const state = String(obj.lifecycle_state || "");
    const stateLabel = titleCaseWords(state);
    const typeLabel = String(obj.type_label || "");
    const objectType = String(obj.object_type || "");
    const creo = String(obj.creo_release || "");
    const checkout = String(obj.checkout_status || "Available");
    const checkoutKind = obj.owned_by_me
      ? "mine"
      : obj.checkout_user
        ? "other"
        : obj.can_checkout
          ? "available"
          : "locked";
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
              data-detail="/products/${escapeHtml(productId)}/objects/${escapeHtml(obj.uuid)}"
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
            <td title="${escapeHtml(stampPretty || stamp || "")}">${escapeHtml(stamp || "—")}</td>
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

  function showSearchMatches(items, productId) {
    if (!objectTable || !objectTbody) return;
    objectTable.dataset.searching = "1";
    if (searchScope) searchScope.hidden = false;
    if (folderCrumb) folderCrumb.hidden = true;
    if (!items.length) {
      objectTbody.innerHTML = `<tr class="empty-row"><td colspan="7">No matching files in this product.</td></tr>`;
      updateMetricCounts();
      return;
    }
    objectTbody.innerHTML = items.map((item) => searchRowHtml(item, productId)).join("");
    updateMetricCounts();
    syncModifiedStateLabels();
  }

  async function searchAllFolders(query) {
    // Prefer currentProductId() — rename/delete gear items are absent when those
    // caps are off; metric-filters / URL still carry the product for search.
    const productId = currentProductId();
    if (!objectTbody || !productId) {
      applyMetricVisibility();
      syncToolbar();
      return;
    }
    const seq = ++searchSeq;
    const response = await fetch(
      `/api/products/${encodeURIComponent(productId)}/objects?q=${encodeURIComponent(query)}`
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
    showSearchMatches(Array.isArray(items) ? items : [], productId);
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
  const checkoutProductBtn = $("#checkout-product-btn");
  const checkoutMenu = $("#checkout-menu");
  const checkoutMenuBtn = $("#checkout-menu-btn");
  const checkoutMenuPanel = checkoutMenu?.querySelector(".toolbar-menu-panel");
  const checkinBtn = $("#checkin-btn");
  const checkinProductBtn = $("#checkin-product-btn");
  const checkinMenu = $("#checkin-menu");
  const checkinMenuBtn = $("#checkin-menu-btn");
  const checkinMenuPanel = checkinMenu?.querySelector(".toolbar-menu-panel");
  const undoBtn = $("#undo-btn");
  const forceUndoBtn = $("#force-undo-btn");
  const workspaceBtn = $("#workspace-btn");
  const exportMenu = $("#export-menu");
  const exportMenuBtn = $("#export-menu-btn");
  const exportMenuPanel = exportMenu?.querySelector(".toolbar-menu-panel");
  const exportProductBtn = $("#export-product-btn");
  const exportSelectedBtn = $("#export-selected-btn");
  const openWorkspaceBtn = $("#open-workspace-btn");
  const setCreoDirBtn = $("#set-creo-dir-btn");
  const purgeBtn = $("#purge-workspace-btn");
  const purgeVersionsBtn = $("#purge-versions-btn");
  const deleteWorkspaceBtn = $("#delete-workspace-btn");
  const removeBtn = $("#remove-product-btn");
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

  function closeExportMenu() {
    closeToolbarMenu(exportMenu, exportMenuBtn, exportMenuPanel);
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
    closeExportMenu();
    closeAddMenu();
    closeOpenMenu();
  }

  function openRemoveMenu() {
    closeCheckoutMenu();
    closeCheckinMenu();
    closeExportMenu();
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
      closeExportMenu();
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
      closeExportMenu();
      closeAddMenu();
      closeOpenMenu();
      openToolbarMenu(checkinMenu, checkinMenuBtn, checkinMenuPanel);
    }
  }

  function toggleExportMenu() {
    if (exportMenu?.classList.contains("is-open")) closeExportMenu();
    else {
      closeRemoveMenu();
      closeCheckoutMenu();
      closeCheckinMenu();
      closeAddMenu();
      closeOpenMenu();
      openToolbarMenu(exportMenu, exportMenuBtn, exportMenuPanel);
    }
  }

  function toggleAddMenu() {
    if (addMenu?.classList.contains("is-open")) closeAddMenu();
    else {
      closeRemoveMenu();
      closeCheckoutMenu();
      closeCheckinMenu();
      closeExportMenu();
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
      closeExportMenu();
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
          return { relativePath: row.dataset.relativePath, productId: currentProductId() };
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
    updateMetricCounts();
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

  async function refreshPendingCheckinIds(productId) {
    if (!productId) return;
    const seq = ++pendingCheckinFetch;
    try {
      // Interim paint from SSR only — do not seed the final pending set from
      // data-modified-locally (that attribute used to stick forever and kept
      // rematerialized matching tips painted Modified after a clean hash check).
      const ssrIds = [];
      document.querySelectorAll(".object-row[data-modified-locally='1'][data-uuid]").forEach((row) => {
        ssrIds.push(row.dataset.uuid);
      });
      if (ssrIds.length) rememberPendingCheckinIds(ssrIds, { merge: true });
      const ids = [];
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/checkin-preview`);
      if (seq !== pendingCheckinFetch) return;
      if (response.ok) {
        const data = await response.json();
        if (seq !== pendingCheckinFetch) return;
        (data.object_ids || []).forEach((id) => ids.push(id));
      }
      // Same local-cache signal as the New files tab (Creo often saves there first).
      try {
        const [cacheFiles, objects] = await Promise.all([
          listAgentCacheFiles(productId),
          ensureProductObjects(productId),
        ]);
        if (seq !== pendingCheckinFetch) return;
        const newerLocal = await resolveNewerLocalCacheSaves(cacheFiles, objects, productId);
        newerLocal.forEach((item) => {
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
        // Authoritative clear: matching rematerialize must drop Modified.
        row.dataset.modifiedLocally = pendingCheckinIds.has(String(id)) ? "1" : "0";
      });
      syncModifiedStateLabels();
      updateMetricCounts();
      syncToolbar();
    } catch {
      if (seq !== pendingCheckinFetch) return;
      pendingCheckinIdsReady = true;
      syncModifiedStateLabels();
      updateMetricCounts();
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

  function checkinSelectedHoverTitle(selected, canCheckin, addOnly) {
    if (addOnly) {
      return "Add selected new files to the product (uploads local workspace files first).";
    }
    if (canCheckin) return "Check in selected files.";
    if (!selected.length) {
      return "Select Modified files or new files to check in. Clean checkouts alone are not enough — use Check in product… to release them.";
    }
    const anyEligible = selected.some(
      (row) => row.dataset.canCheckin === "1" || isNewFileQueueRow(row)
    );
    const allEligible = selected.every(
      (row) => row.dataset.canCheckin === "1" || isNewFileQueueRow(row)
    );
    if (!anyEligible) {
      return "None of the selected files can be checked in (not checked out to you, or not eligible).";
    }
    if (!allEligible) {
      return "Every selected file must be eligible to check in. Remove files you do not own from the selection.";
    }
    return "Nothing to check in for this selection — content matches the vault tip (no Modified save). Use Check in product… to release unchanged checkouts, or Undo Checkout.";
  }

  // Product lock: Add/Check In/vault Remove omitted in Jinja via product_ui;
  // row can_checkout/can_checkin are false when locked. syncToolbar is selection-only.
  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.flatMap(rowObjectIds);
    const canOpenFile = Boolean(selectedOpenSpec());
    // Local Explorer open needs creopdm-agent on this PC — hide when offline
    // (server vault fallback is useless for remote Linux hosts / unsupported paths).
    const canOpenWorkspace =
      Boolean(openWorkspaceBtn?.dataset.product) && agentIsOnline();
    const canOpenMenu = canOpenFile || canOpenWorkspace;
    setToolbarActionVisible(openBtn, canOpenFile);
    setToolbarActionVisible(openWorkspaceBtn, canOpenWorkspace);
    setToolbarActionVisible(openMenuBtn, canOpenMenu);
    if (!canOpenMenu) closeOpenMenu();
    const one = selected.length === 1 ? selected[0] : null;
    setToolbarActionVisible(historyBtn, Boolean(rowHistoryHref(one)));
    const roleCanCheckout = userCanCheckout();
    const roleCanCheckin = userCanCheckin();
    const canCheckout =
      roleCanCheckout &&
      selected.length > 0 &&
      selected.every((row) => rowOffersCheckout(row));
    const canCheckin = roleCanCheckin && selectionCanCheckin(selected);
    const canUndo =
      roleCanCheckout &&
      selected.length > 0 &&
      selected.every((row) => rowCheckoutKind(row) === "mine" || dataFlag(row, "owned"));
    const canForceUndo =
      dataFlag(document.body, "can-force-undo-checkout") &&
      selected.length > 0 &&
      selected.every((row) => {
        const kind = rowCheckoutKind(row);
        if (kind === "other") return true;
        if (kind === "mine" || kind === "available" || kind === "locked") return false;
        return dataFlag(row, "checked-out") && !dataFlag(row, "owned");
      });
    const addOnly = selectionIsAddOnly(selected);
    const productId =
      checkinBtn?.dataset.product ||
      checkinMenuBtn?.dataset.product ||
      openWorkspaceBtn?.dataset.product ||
      currentProductId() ||
      "";
    // Add menu is omitted from the DOM when the product is locked (Jinja product_ui).
    const canAdd = Boolean(productId);
    setToolbarActionVisible(addMenuBtn, canAdd);
    for (const id of ["create-folder-btn", "add-files-btn", "add-folder-btn", "add-folders-btn", "add-compressed-btn"]) {
      setToolbarActionVisible($("#" + id), canAdd);
    }
    if (!canAdd) closeAddMenu();
    const canCheckoutProduct =
      roleCanCheckout &&
      Boolean(productId) &&
      Number(checkoutProductBtn?.dataset.checkoutable || 0) > 0;
    const pendingProductSaves = Number(
      checkinBtn?.dataset.pendingSaves || checkinMenuBtn?.dataset.pendingSaves || 0
    );
    const pendingProductNew = Number(
      checkinBtn?.dataset.newFiles || checkinMenuBtn?.dataset.newFiles || 0
    );
    const productCheckoutCount = Number(
      checkinProductBtn?.dataset.checkoutCount || checkinMenuBtn?.dataset.checkoutCount || 0
    );
    // Product check-in when there is queue work and/or active checkouts to release.
    // Check In menu is omitted from the DOM when the product is locked (Jinja product_ui).
    const canCheckinProduct =
      roleCanCheckin &&
      Boolean(productId) &&
      (pendingProductSaves > 0 || pendingProductNew > 0 || productCheckoutCount > 0);
    // Require a matching DOM item so Force-Undo-only / no-checkout roles never
    // get a hollow Checkout ▾ (menu open, every item omitted by product_ui).
    const canCheckoutMenu = Boolean(
      (canCheckout && checkoutBtn) ||
        (canCheckoutProduct && checkoutProductBtn) ||
        (canUndo && undoBtn) ||
        (canForceUndo && forceUndoBtn)
    );
    setToolbarActionVisible(checkoutBtn, canCheckout);
    setToolbarActionVisible(checkoutProductBtn, canCheckoutProduct);
    if (checkoutProductBtn) {
      checkoutProductBtn.title = canCheckoutProduct
        ? "Check out every file in this product that is available (not locked by someone else)."
        : "Nothing left to check out in this product.";
    }
    setToolbarActionVisible(undoBtn, canUndo);
    setToolbarActionVisible(forceUndoBtn, canForceUndo);
    setToolbarActionVisible(checkoutMenuBtn, canCheckoutMenu);
    if (!canCheckoutMenu) closeCheckoutMenu();
    if (checkinBtn) {
      checkinBtn.textContent = addOnly ? "Add selected…" : "Check in selected…";
      checkinBtn.title = checkinSelectedHoverTitle(selected, canCheckin, addOnly);
    }
    // Check in selected stays visible in the menu but greyed when the selection
    // has no pending work (clean checkout / rematerialized match) — hover title explains why.
    if (checkinBtn) {
      checkinBtn.hidden = false;
      checkinBtn.disabled = !canCheckin;
    }
    setToolbarActionVisible(checkinProductBtn, canCheckinProduct);
    if (checkinProductBtn) {
      checkinProductBtn.title = canCheckinProduct
        ? "Check in modified files and new files, and release unchanged checkouts so the product looks fully checked in."
        : "Nothing to check in for this product. Check out and save changes, or add new files first.";
    }
    const canCheckinMenu = canCheckin || canCheckinProduct;
    setToolbarActionVisible(checkinMenuBtn, canCheckinMenu);
    if (!canCheckinMenu) closeCheckinMenu();
    setToolbarActionVisible(
      workspaceBtn,
      document.body?.dataset?.canCopyToVault === "1" &&
        selected.some((row) => row.dataset.inWorkspace !== "1")
    );
    const canExportProduct = document.body?.dataset?.canExportProduct === "1";
    const canExportObjects = document.body?.dataset?.canExportObjects === "1";
    // Visual selection only — do not treat checkout/open fallback ids as an export selection.
    const exportHasSelection =
      selectedRows().flatMap(rowObjectIds).length > 0 || selectedFolderPaths().length > 0;
    const canShowExportMenu =
      Boolean(productId) && (canExportProduct || canExportObjects);
    setToolbarActionVisible(exportMenuBtn, canShowExportMenu);
    if (!canShowExportMenu) closeExportMenu();
    // Export product stays enabled whenever the menu is shown and the role allows it.
    if (exportProductBtn) {
      exportProductBtn.hidden = false;
      exportProductBtn.disabled = !canShowExportMenu || !canExportProduct;
    }
    // Export selected stays visible but greyed until files/folders are selected.
    if (exportSelectedBtn) {
      exportSelectedBtn.hidden = false;
      exportSelectedBtn.disabled =
        !canShowExportMenu || !canExportObjects || !exportHasSelection;
    }
    const localNewSelected = selected.filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache === "1"
    );
    const vaultNewSelected = selected.filter(
      (row) => isNewFileQueueRow(row) && row.dataset.localCache !== "1"
    );
    const canDiscardLocal = localNewSelected.length > 0;
    // Remove from Vault omitted from DOM when locked (product_ui.show_remove_vault).
    const canPurge =
      Boolean(purgeBtn) &&
      (vaultNewSelected.length > 0 ||
        selected.some((row) => row.dataset.uuid && row.dataset.inWorkspace !== "0"));
    const folderPaths = selectedFolderPaths();
    // Remove from Product omitted from DOM when locked (product_ui.show_remove_product).
    const canRemoveProduct =
      Boolean(removeBtn) && (ids.length > 0 || folderPaths.length > 0);
    // Local cache cleanup only — allowed on locked products.
    const canPurgeVersions = Boolean(
      purgeVersionsBtn?.dataset.product || openWorkspaceBtn?.dataset.product || checkinBtn?.dataset.product
    );
    const canDeleteWorkspace = Boolean(
      deleteWorkspaceBtn?.dataset.product
      || openWorkspaceBtn?.dataset.product
      || checkinBtn?.dataset.product
      || currentProductId()
    );
    const canRemoveMenu =
      canDiscardLocal || canPurge || canRemoveProduct || canPurgeVersions || canDeleteWorkspace;
    setToolbarActionVisible(discardLocalBtn, canDiscardLocal);
    setToolbarActionVisible(purgeBtn, canPurge);
    setToolbarActionVisible(purgeVersionsBtn, canPurgeVersions);
    setToolbarActionVisible(deleteWorkspaceBtn, canDeleteWorkspace);
    setToolbarActionVisible(removeBtn, canRemoveProduct);
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
    if (checkinProductBtn) checkinProductBtn.dataset.checkoutCount = String(n);
    if (checkinMenuBtn) checkinMenuBtn.dataset.checkoutCount = String(n);
  }

  function setCheckoutableCount(count) {
    if (checkoutProductBtn) checkoutProductBtn.dataset.checkoutable = String(Number(count) || 0);
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
    if (relativePath) return { relativePath, productId: currentProductId() };
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

  function currentProductId() {
    const fromPath = String(window.location.pathname || "").match(
      /\/products\/([0-9a-f-]{36})\//i
    );
    return (
      $("#rename-product-btn")?.dataset.product ||
      $("#delete-product-btn")?.dataset.product ||
      $("#collect-metadata-btn")?.dataset.product ||
      $("#rebuild-where-used-btn")?.dataset.product ||
      $("#open-workspace-btn")?.dataset.product ||
      $("#checkin-btn")?.dataset.product ||
      document.getElementById("metric-filters")?.dataset?.product ||
      (fromPath && fromPath[1]) ||
      new URLSearchParams(window.location.search).get("product") ||
      ""
    );
  }

  function currentVaultFolder() {
    const raw =
      document.getElementById("metric-filters")?.dataset?.vaultFolder ||
      $("#open-workspace-btn")?.dataset?.vaultFolder ||
      "";
    return String(raw || "").trim() || currentProductId();
  }

  function agentProductFields() {
    return {
      product_id: currentProductId() || null,
      vault_folder: currentVaultFolder() || "",
    };
  }

  function sortStoreKey(table) {
    const product = currentProductId();
    const tableId = table.id || "";
    if (!product || !tableId) return "";
    return `creopdm.sort.${product}.${tableId}`;
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
    const product = currentProductId();
    if (!product) return "";
    return `creopdm.filters.${product}.${folder}`;
  }

  function readStoredFilters() {
    const product = currentProductId();
    if (!product) return null;
    // Prefer _last (most recent pill clicks) so turning Files/Folders off
    // survives navigating into another folder that still has an older snapshot.
    const keys = [filterStoreKey("_last"), filterStoreKey(currentFolder())];
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
    const product = currentProductId();
    if (!product) return;
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
        const other = metricKey(item);
        // Files keeps Folders as stored (on or off) — do not force Folders back on.
        if (item !== files && !isStateMetric(other) && other !== "folders") {
          setMetricMode(item, "off");
        }
      });
    }
    const cadModels = metricButtons().find((btn) => metricKey(btn) === "cad_models");
    if (cadModels && metricMode(cadModels) !== "off") clearMetricFilters(CAD_MODEL_CHILD_FILTERS);
    if (!applied) return;
    applyMetricVisibility();
    applyMetricSelection();
  }

  function clearProductViewStorage(productId) {
    if (!productId) return;
    const prefixes = [`creopdm.filters.${productId}.`, `creopdm.sort.${productId}.`];
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
    const productId = currentProductId();
    const path =
      folder.dataset?.folder
      || folder.querySelector?.(".folder-open")?.dataset?.folder
      || "";
    if (productId && path) {
      leavePage(`/?product=${encodeURIComponent(productId)}&folder=${encodeURIComponent(path)}`);
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
    // Delay so a double-click can cancel and open Details instead.
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
    const productId = currentProductId();
    if (!productId) return "";
    // Details page defaults to Overview (first tab); use #history to deep-link History.
    return `/products/${productId}/objects/${uuid}`;
  }

  document.querySelector("#object-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#object-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#checked-out-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#checked-out-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#changes-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#changes-table")?.addEventListener("dblclick", onFileTableDblclick);

  function canViewObjects() {
    return document.body?.dataset?.canView === "1";
  }

  function selectedDownloadIds() {
    return [
      ...new Set(selectedRows().flatMap(rowObjectIds).map((id) => String(id || "").trim()).filter(Boolean)),
    ];
  }

  function filesContextMenuCapabilities() {
    const selected = selectedRows();
    const roleCanCheckout = userCanCheckout();
    const roleCanCheckin = userCanCheckin();
    const canOpen = Boolean(openBtn) && Boolean(selectedOpenSpec());
    const one = selected.length === 1 ? selected[0] : null;
    const canDetails = Boolean(historyBtn) && Boolean(rowHistoryHref(one));
    const canCheckout =
      Boolean(checkoutBtn) &&
      roleCanCheckout &&
      selected.length > 0 &&
      selected.every((row) => row.dataset.canCheckout === "1");
    const canUndo =
      Boolean(undoBtn) &&
      roleCanCheckout &&
      selected.length > 0 &&
      selected.every((row) => row.dataset.owned === "1");
    const addOnly = selectionIsAddOnly(selected);
    // Match toolbar: Check in selected stays in the DOM when the menu exists; enable only when work is pending.
    // Context menu hides when not possible (no greyed items).
    const canCheckin =
      Boolean(checkinBtn) &&
      roleCanCheckin &&
      selectionCanCheckin(selected);
    const canDownload = canViewObjects() && selectedDownloadIds().length > 0;
    const canExportObjects = document.body?.dataset?.canExportObjects === "1";
    const exportHasSelection =
      selected.flatMap(rowObjectIds).length > 0 || selectedFolderPaths().length > 0;
    const canExport =
      Boolean(exportSelectedBtn) &&
      canExportObjects &&
      exportHasSelection;
    return {
      canOpen,
      canDetails,
      canCheckout,
      canUndo,
      canCheckin,
      canDownload,
      canExport,
      checkinLabel: addOnly ? "Add selected…" : "Check in selected…",
    };
  }

  function ensureFilesContextMenu() {
    let menu = document.getElementById("files-context-menu");
    const items = [
      {
        id: "files-context-open",
        action: "open",
        label: "Open selected…",
        title: "Open the selected file in Creo or its Windows associated program.",
      },
      {
        id: "files-context-details",
        action: "details",
        label: "Details",
        title: "Open Details for the selected file (Overview and History). Same as double-clicking the row.",
      },
      {
        id: "files-context-checkout",
        action: "checkout",
        label: "Checkout selected",
        title: "Check out the selected files and download them to the local workspace.",
      },
      {
        id: "files-context-undo",
        action: "undo",
        label: "Undo Checkout",
        title: "Release your checkout lock. Does not delete the vault file or record a new version. A Creo save still on disk can be checked in afterward.",
      },
      {
        id: "files-context-checkin",
        action: "checkin",
        label: "Check in selected…",
        title: "Check in selected files.",
      },
      {
        id: "files-context-download",
        action: "download",
        label: "Download selected to workspace",
        title: "Download the selected files into this product’s local workspace on this PC.",
      },
      {
        id: "files-context-export",
        action: "export",
        label: "Export selected…",
        title: "Download the selected vault files or folders as a zip.",
      },
    ];
    if (!menu) {
      menu = document.createElement("div");
      menu.id = "files-context-menu";
      menu.className = "files-context-menu";
      menu.setAttribute("role", "menu");
      menu.hidden = true;
      document.body.appendChild(menu);
    }
    items.forEach((spec) => {
      if (menu.querySelector(`#${spec.id}`)) return;
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "toolbar-menu-item";
      btn.id = spec.id;
      btn.dataset.action = spec.action;
      btn.setAttribute("role", "menuitem");
      btn.textContent = spec.label;
      btn.title = spec.title;
      // Keep toolbar-like order when inserting into an older menu node.
      const order = items.map((item) => item.id);
      const index = order.indexOf(spec.id);
      let inserted = false;
      for (let i = index + 1; i < order.length; i += 1) {
        const next = menu.querySelector(`#${order[i]}`);
        if (next) {
          menu.insertBefore(btn, next);
          inserted = true;
          break;
        }
      }
      if (!inserted) menu.appendChild(btn);
    });
    return menu;
  }

  function closeFilesContextMenu() {
    const menu = document.getElementById("files-context-menu");
    if (menu) menu.hidden = true;
  }

  function positionFilesContextMenu(menu, clientX, clientY) {
    menu.hidden = false;
    menu.style.left = "0px";
    menu.style.top = "0px";
    const rect = menu.getBoundingClientRect();
    const pad = 8;
    let left = clientX;
    let top = clientY;
    if (left + rect.width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - rect.width - pad);
    }
    if (top + rect.height > window.innerHeight - pad) {
      top = Math.max(pad, window.innerHeight - rect.height - pad);
    }
    menu.style.left = `${left}px`;
    menu.style.top = `${top}px`;
  }

  function openFilesContextMenu(clientX, clientY) {
    syncToolbar();
    const caps = filesContextMenuCapabilities();
    if (
      !caps.canOpen
      && !caps.canDetails
      && !caps.canCheckout
      && !caps.canUndo
      && !caps.canCheckin
      && !caps.canDownload
      && !caps.canExport
    ) {
      return false;
    }
    closeAllToolbarMenus();
    const menu = ensureFilesContextMenu();
    const openItem = menu.querySelector("#files-context-open");
    const detailsItem = menu.querySelector("#files-context-details");
    const checkoutItem = menu.querySelector("#files-context-checkout");
    const undoItem = menu.querySelector("#files-context-undo");
    const checkinItem = menu.querySelector("#files-context-checkin");
    const downloadItem = menu.querySelector("#files-context-download");
    const exportItem = menu.querySelector("#files-context-export");
    if (openItem) openItem.hidden = !caps.canOpen;
    if (detailsItem) detailsItem.hidden = !caps.canDetails;
    if (checkoutItem) checkoutItem.hidden = !caps.canCheckout;
    if (undoItem) undoItem.hidden = !caps.canUndo;
    if (checkinItem) {
      checkinItem.hidden = !caps.canCheckin;
      checkinItem.textContent = caps.checkinLabel;
      checkinItem.title = caps.checkinLabel === "Add selected…"
        ? "Add selected new files to the product (uploads local workspace files first)."
        : "Check in selected files.";
    }
    if (downloadItem) downloadItem.hidden = !caps.canDownload;
    if (exportItem) exportItem.hidden = !caps.canExport;
    positionFilesContextMenu(menu, clientX, clientY);
    return true;
  }

  async function downloadSelectedToWorkspace() {
    closeFilesContextMenu();
    if (!canViewObjects()) return;
    const ids = selectedDownloadIds();
    if (!ids.length) {
      showError($("#toolbar-error"), "Select one or more files to download.");
      return;
    }
    if (!confirmLargeBulk("Download selected to workspace", ids.length)) return;
    showError($("#toolbar-error"), "");
    const sync = await withBusy("Downloading to local workspace…", async () => {
      try {
        return await materializeCheckedOutToAgentCache(ids, (done, total) => {
          if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD && done === 0) {
            setBusyMessage(`Checking local cache for ${total} files…`);
          } else {
            setBusyMessage(`Downloading to local workspace… ${done} of ${total}`);
          }
        });
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return null;
      }
    });
    if (!sync) return;
    if (sync.agentOffline) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to download files into the local workspace."
      );
      return;
    }
    if (sync.failed && !sync.ok) {
      showError($("#toolbar-error"), "Could not download the selected files into the local workspace.");
      return;
    }
    if (sync.ok) {
      const note = sync.failed
        ? `${sync.ok} file(s) in local workspace (${sync.failed} failed).`
        : sync.downloaded != null && (sync.skipped || sync.keptNewer)
          ? `${sync.ok} file(s) ready (${sync.downloaded} downloaded, ${sync.skipped || 0} already local` +
            (sync.keptNewer ? `, ${sync.keptNewer} kept newer local` : "") +
            `).`
          : `${sync.ok} file(s) downloaded to the local workspace.`;
      showOk(note);
    }
  }

  function runFilesContextMenuAction(action) {
    closeFilesContextMenu();
    if (action === "open") {
      openBtn?.click();
      return;
    }
    if (action === "details") {
      historyBtn?.click();
      return;
    }
    if (action === "download") {
      void downloadSelectedToWorkspace();
      return;
    }
    if (action === "checkout") {
      checkoutBtn?.click();
      return;
    }
    if (action === "undo") {
      undoBtn?.click();
      return;
    }
    if (action === "checkin") {
      checkinBtn?.click();
      return;
    }
    if (action === "export") {
      exportSelectedBtn?.click();
    }
  }

  function onFileTableContextMenu(event) {
    const target = eventEl(event);
    const row = target?.closest?.(".object-row, .queue-row, .folder-row");
    if (!row || rowIsHidden(row)) return;
    if (!row.classList.contains("is-selected")) {
      selectOnly(row);
    }
    if (!openFilesContextMenu(event.clientX, event.clientY)) return;
    event.preventDefault();
    event.stopPropagation();
  }

  document.querySelector("#object-table")?.addEventListener("contextmenu", onFileTableContextMenu);
  document.querySelector("#checked-out-table")?.addEventListener("contextmenu", onFileTableContextMenu);
  document.querySelector("#changes-table")?.addEventListener("contextmenu", onFileTableContextMenu);

  // Menu lives on document.body (survives soft-nav). Rebind actions each boot;
  // document listeners are registered once with the native addEventListener so
  // soft-nav abort does not remove them.
  window.__creopdmCloseFilesContextMenu = closeFilesContextMenu;
  window.__creopdmRunFilesContextMenuAction = runFilesContextMenuAction;
  if (!window.__creopdmFilesContextMenuBound) {
    window.__creopdmFilesContextMenuBound = true;
    origAddEventListener.call(
      document,
      "click",
      (event) => {
        const menu = document.getElementById("files-context-menu");
        if (!menu || menu.hidden) return;
        const node = event.target;
        if (node instanceof Element) {
          const item = node.closest("#files-context-menu [data-action]");
          if (item && menu.contains(item)) {
            event.preventDefault();
            window.__creopdmRunFilesContextMenuAction?.(item.getAttribute("data-action") || "");
            return;
          }
        }
        if (!(node instanceof Element) || !node.closest("#files-context-menu")) {
          window.__creopdmCloseFilesContextMenu?.();
        }
      },
      true
    );
    origAddEventListener.call(document, "keydown", (event) => {
      if (event.key === "Escape") window.__creopdmCloseFilesContextMenu?.();
    });
    origAddEventListener.call(window, "scroll", () => window.__creopdmCloseFilesContextMenu?.(), true);
    origAddEventListener.call(window, "resize", () => window.__creopdmCloseFilesContextMenu?.());
  }

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
        const other = metricKey(item);
        // Files does not clear Folders — leave Folders as the user left it (on or off).
        if (item !== btn && !isStateMetric(other) && other !== "folders") {
          setMetricMode(item, "off");
        }
      });
    }
    if (key === "folders" && next !== "off") {
      metricButtons().forEach((item) => {
        const other = metricKey(item);
        // Folders may stay with Files; clear other type chips only.
        if (item !== btn && !isStateMetric(other) && other !== "files") {
          setMetricMode(item, "off");
        }
      });
    }
    if (key !== "files" && key !== "folders" && !isStateMetric(key) && next !== "off") {
      clearMetricFilters(new Set(["files"]));
    }
    if (key !== "folders" && key !== "files" && !isStateMetric(key) && next !== "off") {
      clearMetricFilters(new Set(["folders"]));
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
      // Require a real Creo.JS bridge — same rule as Set Working Directory
      // (Chrome/Edge must not pretend to gather).
      return hostedCreoJS();
    } catch {
      return false;
    }
  }

  /**
   * Best-effort Creo.JS Erase() by logical name (Collect / revert / check-in).
   * Fails quietly when the model is displayed in a window. PTC defers Erase
   * until Creo regains control — callers should await creoYieldForDeferredErase
   * before deleting those files on disk.
   */
  async function tryEraseModelsFromCreoSession(names) {
    const list = (Array.isArray(names) ? names : [names])
      .map((name) => String(name || "").trim())
      .filter(Boolean);
    if (!list.length) return { erased: 0, attempted: false };
    if (!canGatherCreoMetadata()) return { erased: 0, attempted: false };
    if (typeof window.CreoJS?.eraseSessionModelsByNames !== "function") {
      return { erased: 0, attempted: false };
    }
    try {
      await whenCreoJSReady(4000);
      const result = await window.CreoJS.eraseSessionModelsByNames(list, {
        allowUndisplayed: false,
      });
      const erased = Number(result && result.erased) || 0;
      return { erased, attempted: true };
    } catch {
      return { erased: 0, attempted: true };
    }
  }

  /** Let Creo process deferred Erase before Windows can unlock/delete files. */
  async function creoYieldForDeferredErase(ms = 700) {
    await new Promise((resolve) => window.setTimeout(resolve, ms));
  }

  // Prefer tryEraseModelsFromCreoSession; keep alias for older call sites / tests.
  async function tryEraseRevertedModelFromCreo(filename) {
    return tryEraseModelsFromCreoSession(filename);
  }

  const CREO_SESSION_DISK_HINT =
    "If this model is still open in Creo, close the window or use File → Erase, "
    + "then Open again from CreoPDM.";
  const CREO_REVERT_SESSION_HINT = CREO_SESSION_DISK_HINT;

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
      const openSpec = await materializeViaAgent({
        ...prepared,
        replace_newer: Boolean(prepared.replace_newer),
      });
      const materialized = String(openSpec.path || "").trim();
      if (materialized && looksLikeLocalWindowsPath(materialized)) {
        return materialized;
      }
      const workdir = String(openSpec.working_directory || "").trim();
      const diskName = String(openSpec.disk_name || openSpec.filename || "").trim();
      if (workdir && diskName) {
        const rel = String(diskName).replace(/\//g, "\\");
        if (rel.includes("\\")) {
          return `${workdir.replace(/[\\/]+$/, "")}\\${rel}`;
        }
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
        .filter((item) => {
          if (!item || !item.uuid || !item.filename) return false;
          const status = String(item.status || "").trim().toLowerCase();
          // Same filter as checkedInItemsFromResult — skip undo-checkout rows.
          return !status || status === "checked_in";
        })
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

  function checkedInItemsFromResult(result) {
    const items = [];
    const seen = new Set();
    const push = (uuid, filename) => {
      const id = String(uuid || "").trim();
      if (!id || seen.has(id)) return;
      seen.add(id);
      items.push({
        uuid: id,
        filename: String(filename || "").trim(),
      });
    };
    if (Array.isArray(result?.ok)) {
      result.ok.forEach((item) => {
        if (!item || !item.uuid) return;
        // Product check-in merges undo-checkout rows into result.ok — those must
        // not rematerialize/erase (that closed every open Creo model).
        const status = String(item.status || "").trim().toLowerCase();
        if (status && status !== "checked_in") return;
        push(item.uuid, item.filename);
      });
    } else if (result?.uuid) {
      push(result.uuid, result.filename);
    }
    return items;
  }

  function checkedInObjectIdsFromResult(result) {
    return checkedInItemsFromResult(result).map((item) => item.uuid);
  }

  /**
   * After a clean check-in the vault tip is logical (shaft.prt), but Creo may
   * still leave shaft.prt.2 in the agent cache. Rematerialize with replace_newer
   * so higher .N siblings are trashed.
   *
   * Do NOT Erase from the Creo session here — check-in leaves models open for
   * continued work (and product check-in must not wipe unrelated open files).
   * History revert still erases; if .N stays locked, the toast hints File → Erase.
   */
  async function rematerializeCheckedInLocalTips(result) {
    const items = checkedInItemsFromResult(result);
    if (!items.length) return { agentOffline: false, ok: 0, failed: 0, erased: 0 };
    const agent = await probeCreoAgent();
    if (!agent) return { agentOffline: true, ok: 0, failed: 0, erased: 0 };

    let ok = 0;
    let failed = 0;
    const total = items.length;
    let purgedTotal = 0;
    await withBusy(
      total === 1
        ? "Updating local workspace…"
        : `Updating local workspace… 0 of ${total}`,
      async () => {
        for (let i = 0; i < items.length; i += 1) {
          if (total > 1) {
            setBusyMessage(`Updating local workspace… ${i + 1} of ${total}`);
          }
          const item = items[i];
          try {
            // Avoid postAction here — it paints toolbar errors and clears OK toasts.
            const response = await fetch("/api/creo/open", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                object_id: item.uuid,
                launch: false,
                include_companions: false,
              }),
            });
            if (!response.ok) {
              failed += 1;
              continue;
            }
            const prepared = await response.json();
            const openSpec = await materializeViaAgent({
              ...prepared,
              replace_newer: true,
            });
            purgedTotal += Array.isArray(openSpec?.purged_newer)
              ? openSpec.purged_newer.length
              : 0;
            ok += 1;
          } catch {
            failed += 1;
          }
        }
      }
    );

    return {
      agentOffline: false,
      ok,
      failed,
      erased: 0,
      purged: purgedTotal,
    };
  }

  function whenCreoJSReady(timeoutMs = 20000) {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (ok, err) => {
        if (settled) return;
        settled = true;
        window.clearTimeout(timer);
        if (ok) resolve();
        else reject(err || new Error("Creo.JS did not become ready."));
      };
      const timer = window.setTimeout(() => {
        finish(
          false,
          new Error("Creo.JS did not become ready (session may be offline). Try Open again or use OS association.")
        );
      }, timeoutMs);
      try {
        if (typeof window.CreoJS?.$ADD_ON_LOAD === "function") {
          window.CreoJS.$ADD_ON_LOAD(() => finish(true));
          return;
        }
        finish(true);
      } catch (err) {
        finish(false, err);
      }
    });
  }

  function applyCreoSessionOnlyVisibility(inSession) {
    // Set Working Directory: only when inside Creo with a live session (Files page).
    // Hidden outside Creo / when disconnected; always hidden on File Details.
    // Collect / Rebuild Where Used use the same rule (product gear).
    document.querySelectorAll(".creo-session-only").forEach((el) => {
      const btn = el.tagName === "BUTTON" ? el : el.querySelector("button");
      const onDetail = Boolean($("article.detail"));
      if (onDetail && btn?.id === "set-creo-dir-btn") {
        el.hidden = true;
        if (btn) btn.hidden = true;
        return;
      }
      el.hidden = !inSession;
      if (!btn) return;
      btn.hidden = !inSession;
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

  function promoteCreoPillWhenSessionLive() {
    // Soft-nav / late bridge: Set WD can appear from hostedCreoJS while the SSR
    // pill still says Session offline — promote without probing agent.
    const pill = $("#creo-status");
    if (!pill || !hostedCreoJS()) return;
    if (pill.dataset.state === "ok") return;
    const text = String(pill.textContent || "");
    if (text.includes("Agent offline")) return;
    pill.textContent = "Creo: Connected";
    pill.dataset.state = "ok";
    pill.title = "Creo.JS session linked.";
  }

  async function refreshCreoStatusPill(prefetchedAgent) {
    // Soft folder/product swap — never flash Session offline while Connected.
    if (window.__creopdmSoftNavBusy || softNavBusy) return null;
    const pill = $("#creo-status");
    if (!pill) {
      applyCreoSessionOnlyVisibility(hostedCreoJS());
      syncProductSettingsVisibility();
      return null;
    }
    const modeKey = creoOpenMode() || "association";
    const wasConnected = pill.dataset.state === "ok";
    let inSession = hostedCreoJS();
    let agent = null;
    if (modeKey === "embedded") {
      agent =
        prefetchedAgent !== undefined ? prefetchedAgent : await probeCreoAgent();
      // Agent probe can finish after a soft-nav started — don't paint over Connected.
      if (window.__creopdmSoftNavBusy || softNavBusy) return agent;
      inSession = hostedCreoJS();
      // Transient bridge / agent flake — keep Connected while CreoJS is still present.
      // Do not require a healthy agent probe (that used to flash Not Connected).
      if (!inSession && wasConnected && window.CreoJS) {
        applyCreoSessionOnlyVisibility(true);
        syncProductSettingsVisibility();
        return agent;
      }
      if (inSession && agent) {
        pill.textContent = "Creo: Connected";
        pill.dataset.state = "ok";
        pill.title = "Creo.JS session linked. Local creopdm-agent is running.";
      } else if (inSession && !agent) {
        pill.textContent = "Creo: Agent offline";
        pill.dataset.state = "idle";
        pill.title =
          "Creo.JS session is linked, but creopdm-agent is not running on this PC. Start creopdm-agent-tray for Embedded open.";
      } else if (!inSession && agent) {
        // Agent health ≠ Creo.JS. SSR often says Session offline from the Linux host.
        pill.textContent = "Creo: Session offline";
        pill.dataset.state = "idle";
        pill.title =
          "creopdm-agent is running, but this page has no Creo.JS bridge (window.external.ptc). Open CreoPDM inside Creo's embedded browser — not Chrome/Edge — then hard-refresh.";
      } else {
        pill.textContent = "Creo: Session offline";
        pill.dataset.state = "idle";
        pill.title =
          "No Creo.JS bridge and creopdm-agent is offline. Open CreoPDM in Creo's embedded browser and start the agent tray.";
      }
      // Re-apply after agent await — first-pass visibility used to disagree with the pill.
      applyCreoSessionOnlyVisibility(inSession);
      syncProductSettingsVisibility();
      return agent;
    }
    if (window.__creopdmSoftNavBusy || softNavBusy) return null;
    inSession = hostedCreoJS();
    if (!inSession && wasConnected && window.CreoJS) {
      applyCreoSessionOnlyVisibility(true);
      syncProductSettingsVisibility();
      return null;
    }
    // Keep agent online flag fresh so Open workspace… can hide when offline.
    // Prefer the caller's probe — association mode used to /health twice on every load.
    agent =
      prefetchedAgent !== undefined ? prefetchedAgent : await probeCreoAgent();
    if (window.__creopdmSoftNavBusy || softNavBusy) return agent;
    inSession = hostedCreoJS();
    if (inSession) {
      pill.textContent = "Creo: Connected";
      pill.dataset.state = "ok";
      pill.title = "Creo.JS session linked (OS open mode).";
    } else {
      pill.textContent = "Creo: Session offline";
      pill.dataset.state = "idle";
      pill.title = "Opens Creo models as a browser download for the OS association";
    }
    applyCreoSessionOnlyVisibility(inSession);
    syncProductSettingsVisibility();
    return agent;
  }

  function showCreoSessionControls() {
    void refreshCreoStatusPill();
  }

  function syncProductSettingsVisibility() {
    // Hide the gear when every menu item is session-only and Creo is offline.
    const gear = $("#product-settings");
    const menu = $("#product-settings-menu");
    if (!gear || !menu) return;
    const anyVisible = [...menu.querySelectorAll(".product-settings-item")].some((el) => !el.hidden);
    gear.hidden = !anyVisible;
  }

  function syncCreoSessionControlsFromBridge() {
    // Soft nav: re-enable toolbar Creo buttons from the live bridge. Do not probe
    // agent — but do promote a stale Session offline pill when Creo.JS is linked
    // (Set Working Directory must not disagree with the status pill).
    const inSession = hostedCreoJS();
    applyCreoSessionOnlyVisibility(inSession);
    if (inSession) promoteCreoPillWhenSessionLive();
    syncProductSettingsVisibility();
  }

  // Soft folder/product switches keep the live Creo.JS bridge and header status
  // pill (both live outside main.shell). Never re-probe agent or reconnect.
  if (soft) {
    syncCreoSessionControlsFromBridge();
  } else if (!isListPage) {
    // Admin / Settings / Details / login: no Open workspace toolbar — skip agent /health.
    syncCreoSessionControlsFromBridge();
  } else {
  void creoJSReady.then(() => {
    void (async () => {
      // CREOPDM_STATUS_POLL_V2: at most one /health on load; repeat only if agent says > 0.
      // Files list only — Open workspace… visibility depends on agent online.
      const agent = await probeCreoAgent();
      await refreshCreoStatusPill(agent);
      syncToolbar();
      // First load: Creo.JS bridge can appear after first paint — re-check a few times.
      if (!hostedCreoJS()) {
        let bridgeTries = 0;
        const bridgePoll = trackedInterval(() => {
          bridgeTries += 1;
          if (hostedCreoJS() || bridgeTries >= 40) {
            window.clearInterval(bridgePoll);
            void refreshCreoStatusPill(agent).then(() => syncToolbar());
          }
        }, 250);
      }
      let seconds = 0;
      if (agent && Object.prototype.hasOwnProperty.call(agent, "status_poll_interval_seconds")) {
        const parsed = Number(agent.status_poll_interval_seconds);
        seconds = Number.isFinite(parsed) ? parsed : 0;
      }
      // Poll agent for Open workspace + Embedded status (any open mode).
      if (seconds > 0 && !window.__creopdmStatusPollId) {
        const interval = Math.min(120000, Math.max(1000, Math.round(seconds * 1000)));
        // Survive soft folder/product boots (those abort pageIntervals).
        window.__creopdmStatusPollId = window.setInterval(() => {
          if (window.__creopdmSoftNavBusy) return;
          // Stop probing after soft-nav away from the Files list.
          if (!document.querySelector("#object-table")) return;
          void refreshCreoStatusPill().then(() => syncToolbar());
        }, interval);
      }
    })();
  });
  }

  async function agentWorkdir(productId, vaultFolder) {
    const params = new URLSearchParams();
    if (productId) params.set("product_id", productId);
    const folder = vaultFolder || currentVaultFolder();
    if (folder) params.set("vault_folder", folder);
    const query = params.toString() ? `?${params}` : "";
    const response = await fetch(`${agentBase()}/workdir${query}`, {
      method: "GET",
      headers: agentAuthHeaders(),
    });
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
      const directory = await agentWorkdir(currentProductId(), currentVaultFolder());
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
    body.product_id = spec.productId || currentProductId();
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

  function dataFlag(el, name) {
    // name like "can-checkout". Prefer getAttribute — Creo CEF dataset on <body>/<tr>
    // is unreliable and was skipping the Open chooser (allowCheckout always false).
    if (!el) return false;
    const attr = `data-${name}`;
    if (typeof el.getAttribute === "function") {
      const raw = el.getAttribute(attr);
      if (raw != null && String(raw).trim() !== "") {
        return String(raw).trim() === "1";
      }
    }
    const camel = name.replace(/-([a-z])/g, (_, ch) => ch.toUpperCase());
    return String(el.dataset?.[camel] || "").trim() === "1";
  }

  function userCanCheckout() {
    if (dataFlag(document.body, "can-checkout")) return true;
    // Explicit "0" (or other non-1) means no objects.checkout — do not invent
    // permission from the toolbar. #checkout-menu can exist for Force Undo alone;
    // that used to make Checkout ▾ open empty for Viewer / no-checkout roles.
    const raw = document.body?.getAttribute("data-can-checkout");
    if (raw != null && String(raw).trim() !== "") return false;
    // Attribute missing (Creo CEF / soft-nav wipe) — recover only from real
    // checkout/undo items, never from #checkout-menu or Force Undo alone.
    return Boolean(
      document.querySelector("#checkout-btn, #checkout-product-btn, #undo-btn")
    );
  }

  function userCanCheckin() {
    return dataFlag(document.body, "can-checkin");
  }

  function rowCheckoutKind(row) {
    // Prefer the Checkout column chrome — it stays correct when data-* attrs drift.
    if (row && typeof row.querySelector === "function") {
      const kind = String(
        row.querySelector(".checkout-state")?.getAttribute("data-state") || ""
      ).trim();
      if (kind) return kind;
    }
    if (dataFlag(row, "owned")) return "mine";
    if (dataFlag(row, "can-checkout")) return "available";
    if (String(row?.dataset?.owned || "").trim() === "1") return "mine";
    if (String(row?.dataset?.canCheckout || "").trim() === "1") return "available";
    return "";
  }

  function rowOffersCheckout(row) {
    const kind = rowCheckoutKind(row);
    if (kind === "available") return true;
    if (kind === "mine" || kind === "other" || kind === "locked") return false;
    // Unknown chrome — fall back to data-can-checkout.
    return dataFlag(row, "can-checkout");
  }

  function isModalDialog(el) {
    // Prefer duck-typing: Creo's embedded browser has historically failed
    // `instanceof HTMLDialogElement` even when <dialog>.showModal works — that
    // skipped the Open/checkout chooser and opened immediately.
    return Boolean(el && typeof el.showModal === "function");
  }

  function promptOpenCheckout({ filename, canCheckout }) {
    const dialog = $("#open-checkout-dialog");
    const form = $("#open-checkout-form");
    const lead = $("#open-checkout-lead");
    const fileWrap = $("#open-checkout-file-wrap");
    const companionsWrap = $("#open-checkout-companions-wrap");
    const companionsNote = $("#open-checkout-companions-note");
    const wdWrap = $("#open-checkout-wd-wrap");
    const wdBox = $("#open-checkout-set-wd");
    const openRadio = $("#open-action-open");
    const cancelBtn = $("#open-checkout-cancel");
    const err = $("#open-checkout-error");
    // Object availability AND signed-in user objects.checkout capability.
    const allowCheckout = Boolean(canCheckout) && userCanCheckout();
    // Working directory only applies inside Creo's embedded browser.
    const showWd = hostedCreoJS();
    // Viewer (or any case with no checkout choice): skip a one-option dialog.
    if (!allowCheckout) {
      return Promise.resolve({ action: "open", setWorkingDirectory: false });
    }
    if (!dialog || !form || !openRadio) {
      // Do not silently open when checkout was an option — that hid the chooser.
      showError(
        $("#toolbar-error"),
        "Could not show the Open dialog. Hard-refresh (F5) and try again."
      );
      return Promise.resolve({ action: "cancel", setWorkingDirectory: false });
    }
    if (lead) {
      lead.textContent = `How do you want to open ${filename}?`;
    }
    showError(err, "");
    if (fileWrap) fileWrap.hidden = false;
    if (companionsWrap) companionsWrap.hidden = false;
    if (companionsNote) companionsNote.hidden = false;
    if (wdWrap) wdWrap.hidden = !showWd;
    openRadio.checked = true;
    if (wdBox) {
      wdBox.disabled = !showWd;
      wdBox.checked = showWd;
    }
    const fileRadio = $("#open-action-checkout-file");
    const companionsRadio = $("#open-action-checkout-companions");
    if (fileRadio) fileRadio.disabled = false;
    if (companionsRadio) companionsRadio.disabled = false;

    return new Promise((resolve) => {
      const finish = (action) => {
        form.removeEventListener("submit", onSubmit);
        cancelBtn?.removeEventListener("click", onCancel);
        dialog.removeEventListener("cancel", onCancel);
        try {
          if (dialog.open) dialog.close();
          else dialog.removeAttribute("open");
        } catch {
          try {
            dialog.removeAttribute("open");
          } catch {
            /* ignore */
          }
        }
        resolve({
          action,
          setWorkingDirectory: showWd && Boolean(wdBox?.checked),
        });
      };
      const onCancel = (event) => {
        event?.preventDefault?.();
        finish("cancel");
      };
      const onSubmit = (event) => {
        event.preventDefault();
        event.stopPropagation?.();
        const selected = form.querySelector('input[name="open_action"]:checked');
        finish(selected?.value || "open");
      };
      form.addEventListener("submit", onSubmit);
      cancelBtn?.addEventListener("click", onCancel);
      dialog.addEventListener("cancel", onCancel);
      try {
        if (isModalDialog(dialog)) {
          if (!dialog.open) dialog.showModal();
        } else {
          // Last resort when showModal is missing — still block behind a visible panel.
          dialog.setAttribute("open", "");
        }
      } catch {
        dialog.setAttribute("open", "");
      }
      if (!dialog.open && !dialog.hasAttribute("open")) {
        showError(
          $("#toolbar-error"),
          "Could not show the Open dialog. Hard-refresh (F5) and try again."
        );
        finish("cancel");
      }
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
    const kind = rowCheckoutKind(row);
    // Only skip the chooser when the Checkout column says it is already mine.
    // Do not trust data-owned alone — a stale "1" was opening Available files
    // with no modal.
    if (objectId && kind === "mine") {
      return openPdmObject(target);
    }
    const canCheckout =
      Boolean(objectId) &&
      userCanCheckout() &&
      kind !== "other" &&
      kind !== "locked" &&
      (kind === "available" || kind === "" || rowOffersCheckout(row));
    const choice = await promptOpenCheckout({
      filename,
      canCheckout,
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

  async function probeCreoAgent() {
    try {
      const response = await fetch(`${agentBase()}/health`, {
        method: "GET",
        signal: abortSignalAfter(5000),
      });
      if (!response.ok) {
        window.__creopdmAgentOnline = false;
        return null;
      }
      const body = await response.json().catch(() => null);
      const ok = body && body.ok ? body : null;
      window.__creopdmAgentOnline = Boolean(ok);
      return ok;
    } catch {
      window.__creopdmAgentOnline = false;
      return null;
    }
  }

  function agentIsOnline() {
    return window.__creopdmAgentOnline === true;
  }

  async function pushLocalWorkspaceToVault(productId, items) {
    const list = (items || []).filter((item) => item && item.object_id);
    if (!productId || !list.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/push`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        pdm_url: window.location.origin,
        ...agentPdmAuth(),
        product_id: productId,
        vault_folder: currentVaultFolder(),
        items: list.map((item) => ({
          object_id: String(item.object_id),
          filename: String(item.filename || ""),
          relative_path: String(item.relative_path || ""),
        })),
      }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  async function listAgentCacheFiles(productId) {
    if (!productId) return [];
    const agent = await probeCreoAgent();
    if (!agent) return [];
    const vaultFolder = currentVaultFolder();
    const params = new URLSearchParams({ product_id: productId });
    if (vaultFolder) params.set("vault_folder", vaultFolder);
    const response = await fetch(
      `${agentBase()}/files?${params}`,
      { method: "GET", headers: agentAuthHeaders() }
    );
    if (!response.ok) return [];
    const body = await response.json().catch(() => null);
    return Array.isArray(body?.files) ? body.files : [];
  }

  /** SHA-256 selected local cache paths (for same-size content-replace detection). */
  async function hashAgentCachePaths(productId, relativePaths) {
    const paths = [
      ...new Set(
        (relativePaths || [])
          .map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, ""))
          .filter(Boolean)
      ),
    ];
    const byPath = new Map();
    if (!productId || !paths.length) return byPath;
    const agent = await probeCreoAgent();
    if (!agent) return byPath;
    const response = await fetch(`${agentBase()}/hash-paths`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
        vault_folder: currentVaultFolder(),
        relative_paths: paths,
      }),
    });
    if (!response.ok) return byPath;
    const body = await response.json().catch(() => null);
    (Array.isArray(body?.files) ? body.files : []).forEach((item) => {
      if (!item?.ok) return;
      const rel = String(item.relative_path || "").replace(/\\/g, "/");
      const hash = String(item.content_hash || "").trim().toLowerCase();
      if (rel && hash) byPath.set(rel.toLowerCase(), hash);
    });
    return byPath;
  }

  async function pushLocalNewPathsToVault(productId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!productId || !paths.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/push-paths`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        pdm_url: window.location.origin,
        ...agentPdmAuth(),
        product_id: productId,
        vault_folder: currentVaultFolder(),
        relative_paths: paths,
      }),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  async function deleteLocalWorkspacePaths(productId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!productId || !paths.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/delete-paths`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
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
  function deleteLocalWorkspacePathsBackground(productId, relativePaths) {
    const paths = [...new Set((relativePaths || []).map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, "")).filter(Boolean))];
    if (!productId || !paths.length) return;
    const url = `${agentBase()}/delete-paths`;
    const chunkSize = 150;
    for (let i = 0; i < paths.length; i += chunkSize) {
      const slice = paths.slice(i, i + chunkSize);
      try {
        fetch(url, {
          method: "POST",
          headers: agentAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            product_id: productId,
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

  async function purgeLocalVersionsOlderThanVault(productId, { dryRun = false } = {}) {
    if (!productId) return { ok: [], failed: [], deleted: 0, skipped: true };
    const floorsResponse = await fetch(
      `/api/products/${encodeURIComponent(productId)}/workspace/purge-floors`
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
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
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

  /** Match historical agent path sanitizer (spaces → _). New agent keeps spaces. */
  function agentCacheSafeSegment(value) {
    const text = String(value || "").trim().replace(/[^A-Za-z0-9._\-]+/g, "_");
    return (text || "x").slice(0, 180);
  }

  function agentCacheSafeRelativePath(rel) {
    const norm = String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
    const parts = norm.split("/").filter((part) => part && part !== "." && part !== "..");
    if (!parts.length) return "";
    return parts.map((part) => agentCacheSafeSegment(part)).join("/");
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
    // Vault "from ptc/…" must also match older agent-cache "from_ptc/…".
    const safe = agentCacheSafeRelativePath(path);
    if (safe && safe.toLowerCase() !== path.toLowerCase()) {
      exact.add(safe.toLowerCase());
      logical.add(logicalRelativePath(safe).toLowerCase());
    }
  }

  async function loadKnownWorkspacePaths(productId, extraRels = []) {
    const exact = new Set();
    const logical = new Set();
    const basenames = new Set();
    (extraRels || []).forEach((rel) => markKnownPath(rel, exact, logical, basenames));
    try {
      const [objectsResponse, queueResponse] = await Promise.all([
        fetch(`/api/products/${encodeURIComponent(productId)}/objects`),
        fetch(`/api/products/${encodeURIComponent(productId)}/checkin-queue`),
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

  async function ensureKnownWorkspacePaths(productId, { force = false } = {}) {
    if (
      !force &&
      knownWorkspacePaths.at &&
      Date.now() - knownWorkspacePaths.at < 15000 &&
      knownWorkspacePaths.exact.size + knownWorkspacePaths.logical.size > 0
    ) {
      return knownWorkspacePaths;
    }
    return loadKnownWorkspacePaths(productId);
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
    // still match when that basename is unique in the product.
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
      // Also index under legacy-safe key so vault "from ptc" finds cache "from_ptc".
      const safeKey = logicalRelativePath(agentCacheSafeRelativePath(rel)).toLowerCase();
      if (safeKey && safeKey !== key) {
        const prevSafe = bestByLogical.get(safeKey);
        if (!prevSafe || saveNumber > prevSafe.saveNumber) {
          bestByLogical.set(safeKey, entry);
        }
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
    const needsHash = [];
    (Array.isArray(objects) ? objects : []).forEach((obj) => {
      const vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      if (!vaultRel) return;
      const key = logicalRelativePath(vaultRel).toLowerCase();
      const safeKey = logicalRelativePath(agentCacheSafeRelativePath(vaultRel)).toLowerCase();
      let local = bestByLogical.get(key) || bestByLogical.get(safeKey);
      if (!local) {
        const base = logicalUploadName(PathBasename(vaultRel)).toLowerCase();
        if ((vaultBasenameCounts.get(base) || 0) === 1) {
          local = bestByBasename.get(base);
        }
      }
      if (!local) return;
      const vaultNumber = Math.max(
        creoSaveNumber(obj.filename || PathBasename(vaultRel)),
        creoSaveNumber(obj.current_version?.filename || ""),
        creoSaveNumber(PathBasename(vaultRel))
      );
      const newerSave = local.saveNumber > vaultNumber;
      // Content hash must differ — never trust .N / size / mtime alone
      // (materialize can rewrite the tip with matching bytes).
      const vaultHash = String(obj.current_version?.content_hash || "").trim().toLowerCase();
      if (!vaultHash) return;
      // Older local tip than vault is not pending check-in work.
      if (local.saveNumber < vaultNumber) return;
      const row = {
        uuid: obj.uuid,
        filename: local.filename,
        recorded_filename: obj.filename || PathBasename(vaultRel),
        object_type: obj.object_type,
        relative_path: local.rel,
        size: local.item.size,
        saved_at: local.item.saved_at || "",
        local_cache: true,
        newer_save: newerSave,
        checked_out: obj.owned_by_me ? "1" : "0",
        can_checkin: obj.can_checkin ? "1" : "0",
        can_checkout: obj.can_checkout ? "1" : "0",
      };
      needsHash.push({ row, vaultHash, rel: local.rel });
    });
    return { rows, needsHash };
  }

  async function resolveNewerLocalCacheSaves(cacheFiles, objects, productId) {
    const planned = newerLocalCacheSaves(cacheFiles, objects);
    const rows = [...(planned.rows || [])];
    const pending = planned.needsHash || [];
    if (!pending.length || !productId) return rows;
    try {
      const hashes = await hashAgentCachePaths(
        productId,
        pending.map((item) => item.rel)
      );
      pending.forEach((item) => {
        const localHash = hashes.get(String(item.rel || "").toLowerCase()) || "";
        if (localHash && localHash !== item.vaultHash) {
          rows.push(item.row);
        }
      });
    } catch {
      /* agent offline / old agent without /hash-paths — do not guess from size */
    }
    return rows;
  }

  async function countLocalNewWorkspaceFiles(productId) {
    if (!productId) return 0;
    const pending = await countLocalWorkspacePending(productId);
    return pending.localNew;
  }

  let cachedProductObjects = { id: "", at: 0, rows: [] };

  async function ensureProductObjects(productId, { force = false } = {}) {
    if (
      !force &&
      cachedProductObjects.id === productId &&
      cachedProductObjects.at &&
      Date.now() - cachedProductObjects.at < 15000
    ) {
      return cachedProductObjects.rows;
    }
    try {
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/objects`);
      const rows = response.ok ? await response.json().catch(() => []) : [];
      cachedProductObjects = {
        id: productId,
        at: Date.now(),
        rows: Array.isArray(rows) ? rows : [],
      };
    } catch {
      cachedProductObjects = { id: productId, at: Date.now(), rows: [] };
    }
    return cachedProductObjects.rows;
  }

  async function countLocalWorkspacePending(productId) {
    if (!productId) return { localNew: 0, newerLocal: 0 };
    const [cacheFiles, known, objects] = await Promise.all([
      listAgentCacheFiles(productId),
      ensureKnownWorkspacePaths(productId),
      ensureProductObjects(productId),
    ]);
    return {
      localNew: localOnlyCacheFiles(cacheFiles, known).length,
      newerLocal: (await resolveNewerLocalCacheSaves(cacheFiles, objects, productId)).length,
    };
  }

  async function materializeViaAgent(prepared) {
    const companions = Array.isArray(prepared.companions) ? prepared.companions : [];
    const response = await fetch(`${agentBase()}/materialize`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      signal: abortSignalAfter(180000),
      body: JSON.stringify({
        pdm_url: window.location.origin,
        ...agentPdmAuth(),
        object_id: prepared.object_id || null,
        product_id: prepared.product_id || currentProductId() || null,
        vault_folder: currentVaultFolder(),
        relative_path: prepared.relative_path || null,
        filename: prepared.filename || null,
        disk_name: prepared.disk_name || prepared.filename || null,
        replace_newer: Boolean(prepared.replace_newer),
        companions: companions.map((item) => ({
          object_id: item.object_id || null,
          product_id: item.product_id || prepared.product_id || currentProductId() || null,
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
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        pdm_url: window.location.origin,
        ...agentPdmAuth(),
        product_id: currentProductId() || null,
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
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      signal: abortSignalAfter(60000),
      body: JSON.stringify({ path: localPath, mode: mode || "association" }),
    });
    if (!response.ok) {
      const message = await readError(response);
      throw new Error(message || "Local CreoPDM agent could not open the file.");
    }
    return response.json();
  }

  async function openPdmObject(target) {
    // Keep the busy overlay up through prepare + materialize until Creo/OS open starts.
    // Always clear on timeout/error so Session offline / hung agent cannot leave Opening… stuck.
    return withBusy("Opening…", async () => {
      try {
        return await withTimeout(
          openPdmObjectWork(target),
          180000,
          "Open timed out. Check creopdm-agent and that Creo is Connected, then try again."
        );
      } catch (err) {
        const message = err && err.message ? err.message : String(err);
        showError($("#toolbar-error"), message || "Could not open the file.");
        return null;
      }
    });
  }

  function likelyStandaloneBrowser() {
    // True for Chrome/Edge/Firefox outside Creo — Embedded setting may still fall
    // back to OS association. False when we look like Creo's embedded browser.
    if (hostedCreoJS() || inCreoBrowser() || creoExternalBridge()) return false;
    if (window.CreoJS) return false;
    try {
      if (typeof pfcGetCurrentSession === "function") return false;
    } catch {
      /* ignore */
    }
    const ua = String(navigator.userAgent || "");
    if (/creo|ptc|parametric/i.test(ua)) return false;
    return /Chrome|Edg|Firefox|Safari/i.test(ua);
  }

  async function openPdmObjectWork(target) {
    // Only use Creo.JS when we are actually in Creo's embedded browser.
    // Outside Creo (Chrome/Edge), always materialize + Windows association.
    // Do not await creoJSReady first on the association path — Session offline
    // can stall that load forever while the Opening… overlay stays up.
    const embeddedMode = creoOpenMode() === "embedded";
    // Only wait inside Creo (or unknown hosts). Plain Chrome/Edge must not stall.
    if (embeddedMode && !hostedCreoJS() && !likelyStandaloneBrowser()) {
      // Brief wait — clicking Open before the bridge attaches used to fall through
      // to Windows file association and launch a second Creo.
      setBusyMessage("Waiting for Creo.JS…");
      try {
        await Promise.race([
          creoJSReady,
          new Promise((resolve) => window.setTimeout(resolve, 8000)),
        ]);
      } catch {
        /* ignore */
      }
      for (let i = 0; i < 12 && !hostedCreoJS(); i += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 250));
      }
    }
    const useCreoSession = hostedCreoJS() && embeddedMode;
    if (embeddedMode && !useCreoSession && !likelyStandaloneBrowser()) {
      showError(
        $("#toolbar-error"),
        "Creo.JS is not connected yet. Wait until the status shows Creo: Connected, then open the file again — do not open via Windows file association from the embedded browser."
      );
      return null;
    }
    if (useCreoSession) {
      await creoJSReady;
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
          setBusyMessage("Downloading to local cache…");
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
          setBusyMessage("Opening in Creo…");
          await whenCreoJSReady();
          const opened = await withTimeout(
            window.CreoJS.openModel(
              openSpec.working_directory,
              openSpec.filename || prepared.filename,
              prepared.creo_release || "",
              openSpec.disk_name || openSpec.filename || prepared.filename,
              openSpec.path || ""
            ),
            90000,
            "Creo did not finish opening the model (session may be offline)."
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
          setBusyMessage("Opening in Creo…");
          await whenCreoJSReady();
          const directory = openSpec.working_directory || "";
          const diskName = openSpec.disk_name || openSpec.filename || prepared.filename;
          // Do not set Creo session WD — the File > Open trail navigates to the
          // agent cache folder via opt_EMBED_BROWSER_TB_SAB_LAYOUT.
          const opened = await withTimeout(
            window.CreoJS.openModel(
              directory,
              openSpec.filename || prepared.filename,
              "",
              diskName,
              openSpec.path || ""
            ),
            90000,
            "Creo did not finish opening the Multi-CAD file (session may be offline)."
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
              setBusyMessage("Downloading to local cache…");
              openSpec = await materializeViaAgent(prepared);
            }
            setBusyMessage("Opening…");
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

    // Not in Creo embedded browser: download via agent and open with Windows association.
    const prepared = await postAction(
      "/api/creo/open",
      openRequestBody(target, false),
      "POST",
      ""
    );
    if (!prepared) return null;
    try {
      const agent = await probeCreoAgent();
      if (agent) {
        setBusyMessage("Downloading to local cache…");
        const openSpec = await materializeViaAgent(prepared);
        if (!openSpec?.path) {
          showError($("#toolbar-error"), "Local agent did not return a cache path.");
          return null;
        }
        setBusyMessage("Opening…");
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
    // No agent: browser download (OS association after save).
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
      Number(checkoutProductBtn?.dataset.checkoutable || 0) - syncedIds.length
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

  checkoutProductBtn?.addEventListener("click", async () => {
    const productId =
      checkoutProductBtn.dataset.product ||
      openWorkspaceBtn?.dataset.product ||
      currentProductId() ||
      "";
    if (!productId) {
      showError($("#toolbar-error"), "Select a product first.");
      return;
    }
    showError($("#toolbar-error"), "");
    const listed = await withBusy("Listing product files…", async () => {
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/objects`);
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
      showError($("#toolbar-error"), "No files available to check out in this product.");
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

  async function beginExport(mode) {
    const scopeSelected = mode === "selected";
    const productId =
      exportMenuBtn?.dataset.product ||
      exportProductBtn?.dataset.product ||
      exportSelectedBtn?.dataset.product ||
      checkinBtn?.dataset.product ||
      openWorkspaceBtn?.dataset.product ||
      currentProductId() ||
      "";
    if (!productId) return;
    const ids = scopeSelected
      ? selectedRows().flatMap(rowObjectIds)
      : [];
    const folderPaths = scopeSelected ? selectedFolderPaths() : [];
    const canExportProduct = document.body?.dataset?.canExportProduct === "1";
    const canExportObjects = document.body?.dataset?.canExportObjects === "1";
    if (scopeSelected) {
      if (!canExportObjects) {
        showError($("#toolbar-error"), "Your role cannot export a selection (objects.export).");
        return;
      }
      if (!ids.length && !folderPaths.length) {
        showError($("#toolbar-error"), "Select files or folders to export.");
        return;
      }
    } else if (!canExportProduct) {
      showError($("#toolbar-error"), "Your role cannot export a whole product (products.export).");
      return;
    }
    const productName =
      exportMenuBtn?.dataset.productName ||
      exportProductBtn?.dataset.productName ||
      exportSelectedBtn?.dataset.productName ||
      checkinBtn?.dataset.productName ||
      openWorkspaceBtn?.dataset.productName ||
      "this product";
    const title = scopeSelected ? "Export selection" : "Export product";
    const scopeBits = [
      ids.length ? `${ids.length} file(s)` : "",
      folderPaths.length ? `${folderPaths.length} folder(s)` : "",
    ]
      .filter(Boolean)
      .join(", ");
    const lead = scopeSelected
      ? `Export the selected files/folders from “${productName}” as a zip${scopeBits ? ` (${scopeBits})` : ""}?`
      : `Export the entire product “${productName}” as a zip?`;
    if (!(await confirmExportZip({ title, lead }))) return;
    showError($("#toolbar-error"), "");
    showOk("");
    const safeName = String(productName || "product")
      .replace(/[^\w.\-]+/g, "_")
      .replace(/^_+|_+$/g, "") || "product";
    const suggested = `${safeName}-${scopeSelected ? "selection" : "export"}.zip`;
    const payload = {
      object_ids: scopeSelected ? ids : [],
      folder_paths: scopeSelected ? folderPaths : [],
    };

    const browserDownload = async () => {
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        throw new Error(await readError(response));
      }
      const blob = await response.blob();
      const headerName = response.headers.get("X-CreoPDM-Export-Name");
      let filename = suggested;
      if (headerName) {
        try {
          filename = decodeURIComponent(headerName);
        } catch {
          filename = suggested;
        }
      }
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      const count = Number(response.headers.get("X-CreoPDM-File-Count") || 0);
      return count;
    };

    try {
      const count = await withBusy("Preparing export…", async () => {
        const agent = await probeCreoAgent();
        if (agent) {
          const response = await fetch(`${agentBase()}/export-zip`, {
            method: "POST",
            headers: agentAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({
              pdm_url: window.location.origin,
              ...agentPdmAuth(),
              product_id: productId,
              object_ids: payload.object_ids,
              folder_paths: payload.folder_paths,
              suggested_name: suggested,
            }),
          });
          if (!response.ok) {
            throw new Error(await readError(response));
          }
          const body = await response.json().catch(() => null);
          if (body?.cancelled) return null;
          if (!body?.ok) {
            throw new Error(body?.message || "Export failed.");
          }
          return Number(body.file_count || 0);
        }
        return browserDownload();
      });
      if (count == null) return;
      showOk(
        count
          ? `Exported ${count} file(s) to a zip.`
          : "Export zip saved."
      );
    } catch (err) {
      showError($("#toolbar-error"), err?.message || String(err));
    }
  }

  exportProductBtn?.addEventListener("click", async () => {
    closeExportMenu();
    await beginExport("product");
  });
  exportSelectedBtn?.addEventListener("click", async () => {
    closeExportMenu();
    await beginExport("selected");
  });

  openWorkspaceBtn?.addEventListener("click", async () => {
    const productId = openWorkspaceBtn.dataset.product;
    if (!productId) return;
    const folder = openWorkspaceBtn.dataset.folder || currentFolder() || "";
    showError($("#toolbar-error"), "");
    showOk("");
    const agent = await probeCreoAgent();
    if (!agent) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this PC to open the local workspace folder."
      );
      syncToolbar();
      return;
    }
    const opened = await withBusy("Opening local workspace…", async () => {
      const response = await fetch(`${agentBase()}/open-folder`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          product_id: productId,
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

  forceUndoBtn?.addEventListener("click", async () => {
    const ids = selectedRows()
      .filter((row) => row.dataset.checkedOut === "1" && row.dataset.owned !== "1")
      .flatMap(rowObjectIds);
    const detailId = forceUndoBtn.dataset.uuid;
    const objectIds = [...new Set((ids.length ? ids : detailId ? [detailId] : []).filter(Boolean))];
    if (!objectIds.length) return;
    const count = objectIds.length;
    const slowNote =
      count > BULK_SLOW_WARN_THRESHOLD
        ? "\n\nThis can take several minutes. Keep this window open until it finishes."
        : "";
    const confirmMsg =
      count === 1
        ? "Force Undo Checkout for this file?\n\nThe other user’s checkout lock is released. No new version is recorded. Unsaved vault changes for this file may be discarded."
        : `Force Undo Checkout for ${count} files?\n\nOther users’ checkout locks are released. No new version is recorded. Unsaved vault changes may be discarded.${slowNote}`;
    if (!window.confirm(confirmMsg)) return;
    showError($("#toolbar-error"), "");
    if (count === 1) {
      const result = await postAction(
        `/api/objects/${objectIds[0]}/force-undo-checkout`,
        undefined,
        "POST",
        "Force undoing checkout…"
      );
      if (result) {
        rememberWatchView();
        applyUndoCheckoutOnRows(objectIds);
        reloadPage({ keepBusy: true });
      }
      return;
    }
    const FORCE_CHUNK = 50;
    const forceResult = await withBusy(`Force undoing checkout… 0 of ${count}`, async () => {
      const merged = { ok: [], failed: [] };
      for (let start = 0; start < objectIds.length; start += FORCE_CHUNK) {
        const chunk = objectIds.slice(start, start + FORCE_CHUNK);
        setBusyMessage(
          `Force undoing checkout… ${Math.min(start + chunk.length, count)} of ${count}`
        );
        const part = await postAction(
          "/api/objects/batch/force-undo-checkout",
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
    if (!forceResult) return;
    const warning = formatBatch(forceResult);
    if (warning) showError($("#toolbar-error"), warning);
    if (forceResult.ok?.length) {
      const undone = forceResult.ok.map((item) => item.uuid).filter(Boolean);
      applyUndoCheckoutOnRows(undone.length ? undone : objectIds);
      reloadPage({ keepBusy: true });
    }
  });

  async function beginCheckin(scope = "selected") {
    const productScope = scope === "product";
    const selected = productScope ? [] : selectedRows();
    if (!productScope && !selectionCanCheckin(selected) && !checkinBtn?.dataset.uuid) {
      showError(
        $("#toolbar-error"),
        "Nothing to check in for this selection. Save changes in Creo first, or use Undo Checkout."
      );
      return;
    }
    if (productScope) {
      const pending = Number(
        checkinBtn?.dataset.pendingSaves || checkinMenuBtn?.dataset.pendingSaves || 0
      );
      const news = Number(checkinBtn?.dataset.newFiles || checkinMenuBtn?.dataset.newFiles || 0);
      const checkouts = Number(
        checkinProductBtn?.dataset.checkoutCount || checkinMenuBtn?.dataset.checkoutCount || 0
      );
      if (pending <= 0 && news <= 0 && checkouts <= 0) {
        showError(
          $("#toolbar-error"),
          "Nothing to check in for this product. Modified checkouts and new files appear under New files."
        );
        return;
      }
    }
    const queued = selected.filter((row) => row.classList.contains("queue-row"));
    const owned = selected.filter((row) => {
      return row.dataset.canCheckin === "1" && !row.classList.contains("queue-row");
    });
    const addOnly = productScope ? false : selectionIsAddOnly(selected);
    const productId =
      checkinBtn?.dataset.product ||
      checkinMenuBtn?.dataset.product ||
      checkinProductBtn?.dataset.product ||
      openWorkspaceBtn?.dataset.product;
    if (!checkinDialog) return;
    const fallbackId = checkinBtn?.dataset.uuid || "";
    let objectId = "";
    if (!productScope) {
      if (!queued.length && owned.length === 1) {
        objectId = owned[0].dataset.uuid;
      } else if (!queued.length && !owned.length && fallbackId) {
        objectId = fallbackId;
      }
    }
    const useQueue = productScope || !objectId;
    if (useQueue && !productId) return;
    if (!productScope) {
      const bulkCount = useQueue ? owned.length + queued.length : 1;
      if (!confirmLargeBulk(addOnly ? "Add" : "Check in", bulkCount)) return;
    }
    showError($("#checkin-error"), "");
    showError($("#toolbar-error"), "");
    const pushItems = [];
    let productLocalNewPaths = [];
    if (!addOnly) {
      if (objectId) {
        const name =
          owned[0]?.dataset.filename ||
          $("#detail-open-btn")?.dataset?.filename ||
          document.querySelector(".detail-filename")?.textContent?.trim() ||
          "";
        pushItems.push({
          object_id: objectId,
          filename: name,
          relative_path: owned[0]?.dataset.relativePath || "",
        });
      } else if (!productScope) {
        owned.forEach((row) => {
          if (row.dataset.uuid) {
            pushItems.push({
              object_id: row.dataset.uuid,
              filename: row.dataset.filename || "",
              relative_path: row.dataset.relativePath || "",
            });
          }
        });
        queued.forEach((row) => {
          if (row.dataset.uuid && row.dataset.localCache === "1") {
            pushItems.push({
              object_id: row.dataset.uuid,
              filename: row.dataset.filename || "",
              relative_path: row.dataset.relativePath || "",
            });
          }
        });
      } else if (productId) {
        // Match New files tab: vault queue + local agent-cache new/newer saves.
        // Preview is vault-only — push local work first or the dialog shows "0 vault files".
        try {
          const [queueResp, cacheFiles, objects] = await Promise.all([
            fetch(`/api/products/${encodeURIComponent(productId)}/checkin-queue`),
            listAgentCacheFiles(productId),
            ensureProductObjects(productId, { force: true }),
          ]);
          let vaultNew = [];
          if (queueResp.ok) {
            const queueBody = await queueResp.json();
            (queueBody.saves || []).forEach((item) => {
              if (item?.uuid) {
                pushItems.push({
                  object_id: String(item.uuid),
                  filename: String(item.filename || ""),
                  relative_path: String(item.relative_path || ""),
                });
              }
            });
            vaultNew = Array.isArray(queueBody.new_files) ? queueBody.new_files : [];
          }
          const known = await loadKnownWorkspacePaths(
            productId,
            vaultNew.map((item) => item.relative_path || "")
          );
          const localNew = localOnlyCacheFiles(cacheFiles, known);
          productLocalNewPaths = localNew
            .map((item) => String(item.relative_path || item.path || "").replace(/\\/g, "/"))
            .filter(Boolean);
          const vaultSaveIds = new Set(pushItems.map((item) => item.object_id));
          (await resolveNewerLocalCacheSaves(cacheFiles, objects, productId))
            .filter((item) => item?.uuid && !vaultSaveIds.has(String(item.uuid)))
            .forEach((item) => {
              pushItems.push({
                object_id: String(item.uuid),
                filename: String(item.filename || ""),
                relative_path: String(item.relative_path || ""),
              });
            });
        } catch {
          /* preview still runs */
        }
        const bulkHint = Math.max(pushItems.length + productLocalNewPaths.length, 1);
        if (!confirmLargeBulk("Check in product", bulkHint)) return;
      }
    }
    // Prefer the local Creo tip (.prt.2) over the vault logical row name before push,
    // so the dialog can show which save is being recorded.
    if (!addOnly && productId && pushItems.length) {
      try {
        const [cacheFiles, objects, queueResp] = await Promise.all([
          listAgentCacheFiles(productId),
          ensureProductObjects(productId),
          fetch(`/api/products/${encodeURIComponent(productId)}/checkin-queue`),
        ]);
        const tipById = new Map();
        if (queueResp.ok) {
          const queueBody = await queueResp.json();
          (queueBody.saves || []).forEach((item) => {
            if (item?.uuid && item.filename) {
              tipById.set(String(item.uuid), String(item.filename));
            }
          });
        }
        (await resolveNewerLocalCacheSaves(cacheFiles, objects, productId)).forEach((item) => {
          if (item?.uuid && item.filename) {
            tipById.set(String(item.uuid), String(item.filename));
          }
        });
        pushItems.forEach((item) => {
          const tip = tipById.get(String(item.object_id));
          if (tip) item.filename = tip;
        });
      } catch {
        /* keep row filenames */
      }
    }
    let agentOffline = false;
    const preview = await withBusy(addOnly ? "Preparing…" : "Preparing check-in…", async () => {
      if (!addOnly && productId && pushItems.length) {
        try {
          const pushed = await pushLocalWorkspaceToVault(productId, pushItems);
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
      if (!addOnly && productId && productLocalNewPaths.length) {
        try {
          const pushedNew = await pushLocalNewPathsToVault(productId, productLocalNewPaths);
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
          ? `/api/products/${productId}/checkin-preview`
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
      (pushItems.length || productLocalNewPaths.length) &&
      !(data.object_ids || []).length &&
      !(data.new_files || []).length &&
      !data.can_checkin
    ) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to sync local workspace saves into the vault before check-in."
      );
    }
    // Prefer the on-disk tip the user saw (shaft.prt.2), not the logical vault name
    // after push (shaft.prt) — so the dialog matches the New files / Files list.
    const tipNameForCheckin = (objectId, fallback) => {
      const id = String(objectId || "");
      const fromPush = pushItems.find((item) => String(item.object_id) === id);
      if (fromPush?.filename) return String(fromPush.filename);
      const fromQueued = queued.find((row) => row.dataset.uuid === id);
      if (fromQueued?.dataset?.filename) return fromQueued.dataset.filename;
      const fromOwned = owned.find((row) => row.dataset.uuid === id);
      if (fromOwned?.dataset?.filename) return fromOwned.dataset.filename;
      if (id) {
        const row = document.querySelector(
          `tr.queue-row[data-uuid="${CSS.escape(id)}"], tr[data-uuid="${CSS.escape(id)}"]`
        );
        if (row?.dataset?.filename) return row.dataset.filename;
      }
      return fallback || "";
    };
    const title = $("#checkin-dialog-title");
    if (title) {
      title.textContent = addOnly ? "Add files" : productScope ? "Check in product" : "Check In";
    }
    let objectLabelText = data.filename;
    if (!addOnly) {
      if (!useQueue) {
        objectLabelText = tipNameForCheckin(objectId, data.filename);
      } else {
        const pendingIdsForLabel = data.object_ids || [];
        if (pendingIdsForLabel.length === 1) {
          objectLabelText = tipNameForCheckin(pendingIdsForLabel[0], data.filename);
        }
      }
    } else if (queued.length === 1) {
      objectLabelText = queued[0].dataset.filename || data.filename;
    } else {
      objectLabelText = `${queued.length || (data.new_files || []).length} files`;
    }
    $("#checkin-filename").textContent = objectLabelText;
    const vaultTipNote = $("#checkin-vault-tip");
    if (vaultTipNote) {
      const tipLeaf = PathBasename(objectLabelText || "");
      const vaultLeaf = logicalUploadName(tipLeaf);
      if (
        !addOnly &&
        tipLeaf &&
        vaultLeaf &&
        tipLeaf.toLowerCase() !== vaultLeaf.toLowerCase()
      ) {
        vaultTipNote.hidden = false;
        vaultTipNote.textContent = `Checking in local save ${tipLeaf}; vault tip will be ${vaultLeaf} (Creo .N stripped).`;
      } else {
        vaultTipNote.hidden = true;
        vaultTipNote.textContent = "";
      }
    }
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
    let productUndoIds = [];
    if (productScope && productId) {
      try {
        const checkoutResp = await fetch(`/api/products/${encodeURIComponent(productId)}/checkouts`);
        if (checkoutResp.ok) {
          const listed = await checkoutResp.json();
          const pendingSet = new Set(data.object_ids || []);
          productUndoIds = (Array.isArray(listed) ? listed : [])
            .filter((item) => item && item.owned_by_me && item.uuid && !pendingSet.has(String(item.uuid)))
            .map((item) => String(item.uuid));
        }
      } catch {
        productUndoIds = [];
      }
    }
    if (checkinDialog) {
      checkinDialog.dataset.force = data.force_checkin ? "1" : "";
      checkinDialog.dataset.queue = useQueue ? "1" : "";
      checkinDialog.dataset.addOnly = addOnly ? "1" : "";
      checkinDialog.dataset.objectId = useQueue ? "" : objectId;
      checkinDialog.dataset.productId = productId || "";
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
        if (productScope) {
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
      checkinDialog.dataset.productScope = productScope ? "1" : "";
      checkinDialog.dataset.undoIds = JSON.stringify(productUndoIds);
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
        : productScope || !queued.length
          ? pendingIds.map((id, index) => tipNameForCheckin(id, pendingNames[index]))
          : pendingIds
              .map((id, index) => (wantedIds.has(id) ? tipNameForCheckin(id, pendingNames[index]) : ""))
              .filter(Boolean);
      names.forEach((name) => {
        const item = document.createElement("li");
        item.textContent = `✓ Check in ${name}`;
        list.appendChild(item);
      });
      const newCount = productScope
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
      } else if (!names.length && !newCount && !productUndoIds.length) {
        const item = document.createElement("li");
        item.textContent = productScope
          ? "– Nothing to check in. Local workspace files need creopdm-agent to sync into the vault first."
          : "– Nothing to check in. Use Undo Checkout to release locks without a new version.";
        list.appendChild(item);
        canSubmit = false;
      } else {
        if (productScope && newCount && !names.length) {
          (data.new_files || []).forEach((file) => {
            const item = document.createElement("li");
            item.textContent = `✓ Add ${file.filename || file.relative_path || "file"}`;
            list.appendChild(item);
          });
        }
        if (productUndoIds.length) {
          const item = document.createElement("li");
          item.textContent =
            productUndoIds.length === 1
              ? "✓ Undo checkout on 1 unchanged file (no new version)"
              : `✓ Undo checkout on ${productUndoIds.length} unchanged files (no new version)`;
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
        : productScope && !((data.object_ids || []).length) && !((data.new_files || []).length) && productUndoIds.length
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
        !productScope);
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
      productScope
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
  checkinProductBtn?.addEventListener("click", () => {
    void beginCheckin("product");
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
        const productId =
          checkinDialog?.dataset.productId ||
          checkinBtn?.dataset.product ||
          openWorkspaceBtn?.dataset.product ||
          "";
        const synced = await withBusy("Uploading local workspace files to vault…", async () => {
          try {
            return await pushLocalNewPathsToVault(productId, localPaths);
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
      const productId =
        checkinDialog?.dataset.productId ||
        checkinBtn?.dataset.product ||
        openWorkspaceBtn?.dataset.product ||
        "";
      if (productId && pushItems.length) {
        const synced = await withBusy("Syncing local workspace to vault…", async () => {
          try {
            return await pushLocalWorkspaceToVault(productId, pushItems);
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
      const productId = checkinBtn?.dataset.product || checkinDialog?.dataset.productId;
      if (!productId) return;
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
      const productScopeSubmit = checkinDialog.dataset.productScope === "1";
      if (!objectIds.length && !added.length && !(productScopeSubmit && undoIds.length)) {
        showError(
          $("#checkin-error"),
          "Nothing to check in. Use Undo Checkout to release locks without a new version."
        );
        return;
      }
      if (objectIds.length || added.length) {
        result = await postAction(`/api/products/${productId}/checkin-queue`, {
          comment,
          object_ids: objectIds,
          add_relative_paths: added,
        }, "POST", busyLabel);
        if (!result) return;
      } else {
        result = { ok: [], failed: [] };
      }
      if (productScopeSubmit && undoIds.length) {
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
      // Drop local .N leftovers and rematerialize logical tip — do not Erase Creo session
      // (keeps open models; product check-in must not wipe unrelated windows).
      const localSync = await rematerializeCheckedInLocalTips(result);
      if (canGatherCreoMetadata()) {
        await withBusy("Capturing Creo metadata…", async () => {
          await pushCreoMetadataForItems(metadataTargetsFromResult(result));
        });
      }
      if (localSync?.agentOffline) {
        showOk(
          "Checked in. Start creopdm-agent, then Open the file to refresh the local workspace."
        );
      } else if ((Number(localSync?.purged) || 0) > 0) {
        showOk("Checked in. Local workspace updated (removed leftover Creo .N saves).");
      } else {
        showOk(
          "Checked in. Local workspace updated. "
          + "If a higher .N file remains on disk while the model is still open in Creo, "
          + "close that window or use File → Erase, then Open again from CreoPDM."
        );
      }
      rememberWatchView({ tab: "files", ids: [] });
      reloadPageAfterDialog();
    }
  });

  historyBtn?.addEventListener("click", () => {
    const href = rowHistoryHref(selectedRows()[0]);
    if (href) window.location.href = href;
  });

  function expectedProductName() {
    return (
      $("#delete-product-btn")?.dataset.name
      || $("#revert-version-btn")?.dataset.productName
      || deleteWorkspaceBtn?.dataset.productName
      || purgeVersionsBtn?.dataset.productName
      || purgeBtn?.dataset.productName
      || removeBtn?.dataset.productName
      || discardLocalBtn?.dataset.productName
      || ""
    ).trim();
  }

  function confirmByProductName({
    title,
    lead,
    note,
    submitLabel,
    detailsHtml = "",
    workspaceOption = false,
    requireProductName = true,
  }) {
    const dialog = $("#danger-confirm-dialog");
    const form = $("#danger-confirm-form");
    const expected = expectedProductName();
    if (!dialog || !form || (requireProductName && !expected)) {
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
    const nameLabel = $("#danger-confirm-name-label") || form.querySelector('label[for="danger-confirm-input"]') || form.querySelector("label:has(#danger-confirm-input)");
    const nameInput = $("#danger-confirm-input");
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
    if (nameLabel) nameLabel.hidden = !requireProductName;
    if (nameInput) {
      nameInput.required = Boolean(requireProductName);
      nameInput.hidden = !requireProductName;
      if (!requireProductName) nameInput.value = "";
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
        if (nameLabel) nameLabel.hidden = false;
        if (nameInput) {
          nameInput.hidden = false;
          nameInput.required = true;
        }
        const deleteWorkspaceFiles = Boolean(ok && workspaceOption && workspaceCheck?.checked);
        if (dialog.open) dialog.close();
        resolve({ ok: Boolean(ok), deleteWorkspaceFiles });
      };
      const onCancel = () => finish(false);
      const onClose = () => finish(false);
      const onSubmit = (event) => {
        event.preventDefault();
        if (requireProductName) {
          const typed = String(new FormData(form).get("confirm_name") || "").trim();
          if (typed !== expected) {
            showError($("#danger-confirm-error"), "Type the product name exactly to confirm.");
            return;
          }
        }
        finish(true);
      };
      form.addEventListener("submit", onSubmit);
      $("#danger-confirm-cancel")?.addEventListener("click", onCancel);
      dialog.addEventListener("close", onClose);
      dialog.showModal();
      if (requireProductName) $("#danger-confirm-input")?.focus();
      else submitBtn?.focus();
    });
  }

  function workspacePathsForRemovedObjects(productId, selected) {
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

  function productHome() {
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
  exportMenuBtn?.addEventListener("click", (event) => {
    event.preventDefault();
    event.stopPropagation();
    toggleExportMenu();
  });
  exportMenuPanel?.addEventListener("click", (event) => {
    const item = eventEl(event)?.closest(".toolbar-menu-item");
    if (item && !item.disabled) closeExportMenu();
  });
  document.addEventListener("click", (event) => {
    const node = eventEl(event);
    if (removeMenu?.classList.contains("is-open") && !removeMenu.contains(node)) closeRemoveMenu();
    if (addMenu?.classList.contains("is-open") && !addMenu.contains(node)) closeAddMenu();
    if (openMenu?.classList.contains("is-open") && !openMenu.contains(node)) closeOpenMenu();
    if (checkoutMenu?.classList.contains("is-open") && !checkoutMenu.contains(node)) closeCheckoutMenu();
    if (checkinMenu?.classList.contains("is-open") && !checkinMenu.contains(node)) closeCheckinMenu();
    if (exportMenu?.classList.contains("is-open") && !exportMenu.contains(node)) closeExportMenu();
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
        : "Creates a folder at the product root.";
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
    const productId = createFolderForm.dataset.product || addForm?.dataset.product;
    if (!productId) return;
    const name = String(new FormData(createFolderForm).get("name") || "").trim();
    if (!name) {
      showError($("#create-folder-error"), "Enter a folder name.");
      return;
    }
    showError($("#create-folder-error"), "");
    const response = await withBusy("Creating folder…", () =>
      fetch(`/api/products/${productId}/folders`, {
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
    const confirmed = await confirmByProductName({
      title: total === 1 ? "Remove from vault" : `Remove ${total} files from vault`,
      lead:
        total === 1
          ? "Only the CreoPDM vault copy is deleted. The original in your product folder stays. If you have it checked out, that checkout is cancelled."
          : "Only CreoPDM vault copies are deleted. Originals in your product folder stay. Your checkouts on those files are cancelled.",
      note: "This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Vault",
    });
    if (!confirmed.ok) return;

    let okCount = 0;
    let warning = "";
    if (paths.length) {
      const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
      if (!productId) return;
      const result = await postAction(
        `/api/products/${productId}/workspace/purge-paths`,
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
    const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
    if (!productId) return;
    const confirmed = await confirmByProductName({
      title: paths.length === 1 ? "Remove from workspace" : `Remove ${paths.length} files from workspace`,
      lead:
        paths.length === 1
          ? "This moves the file from the local workspace on this PC (creopdm-agent cache) to the Recycle Bin. The vault and product list are unchanged."
          : "These files move from the local workspace on this PC (creopdm-agent cache) to the Recycle Bin. The vault and product list are unchanged.",
      note: "This cannot be undone from CreoPDM. Restore from the Recycle Bin on this PC if needed.",
      submitLabel: "Remove from Workspace",
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    const result = await withBusy("Removing from local workspace…", async () => {
      try {
        return await deleteLocalWorkspacePaths(productId, paths);
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
    const productId =
      purgeVersionsBtn.dataset.product
      || checkinBtn?.dataset.product
      || openWorkspaceBtn?.dataset.product;
    if (!productId) return;
    showError($("#toolbar-error"), "");
    const preview = await withBusy("Checking what Purge workspace would delete…", async () => {
      try {
        return await purgeLocalVersionsOlderThanVault(productId, { dryRun: true });
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
    const confirmed = await confirmByProductName({
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
        return await purgeLocalVersionsOlderThanVault(productId);
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

  async function deleteLocalProductWorkspace(productId) {
    if (!productId) return null;
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const response = await fetch(`${agentBase()}/delete-product-cache`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
        vault_folder: currentVaultFolder(),
      }),
    });
    if (!response.ok) {
      if (response.status === 404) {
        throw new Error(
          "Local creopdm-agent does not support Delete workspace yet. Restart the creopdm-agent tray (or reinstall from this repo), then try again."
        );
      }
      throw new Error(await readError(response));
    }
    return response.json();
  }

  deleteWorkspaceBtn?.addEventListener("click", async () => {
    const productId =
      deleteWorkspaceBtn.dataset.product
      || checkinBtn?.dataset.product
      || openWorkspaceBtn?.dataset.product
      || currentProductId();
    if (!productId) return;
    showError($("#toolbar-error"), "");
    const confirmed = await confirmByProductName({
      title: "Delete workspace",
      lead:
        "This deletes this product’s entire local workspace on this PC (the creopdm-agent cache folder). "
        + "Local-only new files that were never added to the product are deleted. "
        + "Vault copies and the product file list are not changed — open or rematerialize from the vault when you need files again.",
      note:
        "Close open models in Creo first if Creo’s working directory is this workspace. "
        + "This cannot be undone from CreoPDM. Restore from the Recycle Bin on this PC if needed.",
      submitLabel: "Delete workspace",
      requireProductName: false,
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    const result = await withBusy("Deleting local workspace…", async () => {
      try {
        return await deleteLocalProductWorkspace(productId);
      } catch (err) {
        showError($("#toolbar-error"), err?.message || String(err));
        return false;
      }
    });
    if (result === false) return;
    if (!result) {
      showError(
        $("#toolbar-error"),
        "Start creopdm-agent on this Creo PC to delete the local workspace."
      );
      return;
    }
    knownWorkspacePaths.at = 0;
    cachedProductObjects.at = 0;
    if (result.deleted) {
      showOk(result.message || "Local workspace moved to the Recycle Bin.");
    } else {
      showOk(result.message || "Local workspace folder was already gone.");
    }
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
    const productId =
      removeBtn.dataset.product
      || checkinBtn?.dataset.product
      || openWorkspaceBtn?.dataset.product
      || currentProductId();
    const confirmed = await confirmByProductName({
      title:
        folderPaths.length && !ids.length
          ? folderPaths.length === 1
            ? "Remove folder from product"
            : `Remove ${folderPaths.length} folders from product`
          : ids.length === 1
            ? "Remove from product"
            : `Remove ${ids.length} files from product`,
      lead:
        folderPaths.length
          ? "CreoPDM vault copies under the selected folder(s) are deleted. Originals in your product folder are not deleted."
          : ids.length === 1
            ? "CreoPDM vault copies are deleted. The original in your product folder is not deleted."
            : "CreoPDM vault copies are deleted. Originals in your product folder are not deleted.",
      note: "Removed from this product list. This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Product",
      workspaceOption: true,
    });
    if (!confirmed.ok) return;
    const deleteWorkspaceFiles = Boolean(confirmed.deleteWorkspaceFiles);
    const workspacePaths = deleteWorkspaceFiles
      ? workspacePathsForRemovedObjects(productId, selected)
      : [];
    removeSelectedRowsFromDom(selected);
    if (ids.length === 1 && !folderPaths.length && !isListPage) {
      const result = await postAction(`/api/objects/${ids[0]}`, null, "DELETE", "Removing from product…");
      if (!result) {
        reloadPage({ keepBusy: true });
        return;
      }
      if (deleteWorkspaceFiles && productId && workspacePaths.length) {
        deleteLocalWorkspacePathsBackground(productId, workspacePaths);
      }
      window.location.href = productHome();
      return;
    }
    const result = await postAction(
      "/api/objects/batch/remove",
      {
        object_ids: ids,
        folder_paths: folderPaths,
        product_id: productId || null,
      },
      "POST",
      removeCount > 100
        ? `Removing ${removeCount} items from product…`
        : "Removing from product…"
    );
    if (!result) {
      reloadPage({ keepBusy: true });
      return;
    }
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length && deleteWorkspaceFiles && productId && workspacePaths.length) {
      deleteLocalWorkspacePathsBackground(productId, workspacePaths);
      if (!warning) {
        showOk(
          `${result.ok.length} item(s) removed from the product. Local workspace cleanup continues in the background.`
        );
      }
    } else if (result.ok?.length && !warning) {
      const files = (result.ok || []).filter((item) => item.status === "removed").length;
      const folders = (result.ok || []).filter((item) => item.status === "folder_removed").length;
      if (folders && !files) {
        showOk(folders === 1 ? "Folder removed from the product." : `${folders} folders removed.`);
      } else if (folders) {
        showOk(`${files} file(s) and ${folders} folder(s) removed from the product.`);
      } else {
        showOk(`${files} file(s) removed from the product.`);
      }
    }
    if (result.ok?.length) {
      await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
      // Soft SSR can still briefly include deleted rows; keep the list honest.
      // Use the post-boot global — this handler's closure is from the prior boot.
      window.__creopdmStripRemovedListRows?.(ids, folderPaths);
    }
  });

  function canOfferAdd() {
    return Boolean($("#add-menu"));
  }

  function canOfferCheckin() {
    return Boolean($("#checkin-menu"));
  }

  async function loadChangesTab(options = {}) {
    const quiet = Boolean(options.quiet);
    const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
    const body = $("#changes-table tbody");
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (!productId || !body) return 0;
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
        fetch(`/api/products/${productId}/checkin-queue`),
        listAgentCacheFiles(productId),
        fetch(`/api/products/${encodeURIComponent(productId)}/objects`),
      ]);
      if (!queueResponse.ok) throw new Error("queue");
      const data = await queueResponse.json();
      const objects = objectsResponse.ok
        ? await objectsResponse.json().catch(() => [])
        : [];
      cachedProductObjects = {
        id: productId,
        at: Date.now(),
        rows: Array.isArray(objects) ? objects : [],
      };
      const saves = data.saves || [];
      const vaultNew = data.new_files || [];
      const known = await loadKnownWorkspacePaths(
        productId,
        vaultNew.map((item) => item.relative_path || "")
      );
      const created = [...vaultNew, ...localOnlyCacheFiles(cacheFiles, known)];
      const vaultSaveIds = new Set(
        saves.map((item) => String(item.uuid || "")).filter(Boolean)
      );
      const newerLocal = (
        await resolveNewerLocalCacheSaves(cacheFiles, objects, productId)
      ).filter((item) => !vaultSaveIds.has(String(item.uuid || "")));
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
        void refreshPendingCheckinIds(productId);
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
        if (meta.uuid && productId) {
          row.dataset.detail = `/products/${productId}/objects/${meta.uuid}`;
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
            // Date column (last) — pretty hover when the stamp is parseable.
            if (index === values.length - 1 && text) {
              const pretty = formatStampPretty(text);
              if (pretty) cell.title = pretty;
            }
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
        const offerCheckin = canOfferCheckin();
        const localDetail = !offerCheckin
          ? "Local workspace."
          : item.can_checkin === "1"
            ? "Local workspace — select and Check In."
            : "Local workspace — check out to Check In.";
        addRow(
          [
            "Newer local save",
            item.filename || "",
            localDetail,
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
            canCheckin: offerCheckin ? item.can_checkin || "0" : "0",
            canCheckout: offerCheckin ? item.can_checkout || "0" : "0",
            recordedFilename: item.recorded_filename || "",
          }
        );
      });
      created.forEach((item) => {
        const offerAdd = canOfferAdd();
        const newDetail = !offerAdd
          ? item.local_cache
            ? "Local workspace."
            : "Not in the product yet."
          : item.local_cache
            ? "Local workspace — select and Add."
            : "Not in the product yet. Select and click Add.";
        addRow(
          [
            item.local_cache ? "New file (local)" : "New file",
            item.filename || "",
            newDetail,
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
    const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
    const body = $("#checked-out-table tbody");
    if (!productId || !body) return;
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
      const response = await fetch(`/api/products/${encodeURIComponent(productId)}/checkouts`);
      if (!response.ok) throw new Error("checkouts");
      const items = await response.json();
      const list = Array.isArray(items) ? items : [];
      setCheckedOutTabCount(list.length);
      if (!list.length) {
        body.innerHTML = `<tr class="empty-row"><td colspan="7">No files are checked out.</td></tr>`;
        refreshTabMetrics();
        return;
      }
      body.innerHTML = list.map((item) => searchRowHtml(item, productId)).join("");
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

  function selectedHistoryVersionRow() {
    return document.querySelector("#panel-history tr.version-row.is-selected");
  }

  function syncRevertVersionButton() {
    const btn = $("#revert-version-btn");
    const tip = $("#revert-version-tip");
    if (!btn) return;
    const historyPanel = $("#panel-history");
    const historyVisible = Boolean(historyPanel && !historyPanel.hidden);
    const row = selectedHistoryVersionRow();
    const canRevert = Boolean(
      historyVisible && row && row.dataset.canRevert === "1" && row.dataset.versionUuid
    );
    setToolbarActionVisible(btn, canRevert);
    if (tip) tip.hidden = !canRevert;
  }

  function syncDetailToolbar() {
    if (isListPage || !$("article.detail")) return;
    // Details page (all tabs): Revert on History only. Check In / Open / Checkout /
    // Remove / Set WD live on the Files page — do not show a stale Check In here
    // when this file is Available but other product checkouts keep the menu “alive”.
    if (setCreoDirBtn) {
      const tip = setCreoDirBtn.closest(".toolbar-tip");
      setCreoDirBtn.hidden = true;
      if (tip) tip.hidden = true;
    }
    setToolbarActionVisible(openBtn, false);
    setToolbarActionVisible(openWorkspaceBtn, false);
    setToolbarActionVisible(openMenuBtn, false);
    setToolbarActionVisible(checkoutBtn, false);
    setToolbarActionVisible(checkoutProductBtn, false);
    setToolbarActionVisible(undoBtn, false);
    setToolbarActionVisible(forceUndoBtn, false);
    setToolbarActionVisible(checkoutMenuBtn, false);
    setToolbarActionVisible(removeMenuBtn, false);
    setToolbarActionVisible(checkinBtn, false);
    setToolbarActionVisible(checkinProductBtn, false);
    setToolbarActionVisible(checkinMenuBtn, false);
    syncRevertVersionButton();
  }

  function selectHistoryVersionRow(row) {
    document.querySelectorAll("#panel-history tr.version-row.is-selected").forEach((item) => {
      item.classList.remove("is-selected");
      item.removeAttribute("data-selected");
    });
    if (row) {
      row.classList.add("is-selected");
      row.dataset.selected = "1";
    }
    syncDetailToolbar();
  }

  $("#panel-history")?.addEventListener("click", (event) => {
    const row = eventEl(event)?.closest("tr.version-row");
    if (!row || !row.closest("#panel-history")) return;
    event.preventDefault();
    selectHistoryVersionRow(row);
  });

  $("#revert-version-btn")?.addEventListener("click", async () => {
    const btn = $("#revert-version-btn");
    const row = selectedHistoryVersionRow();
    const objectId = btn?.dataset.object || "";
    const versionId = row?.dataset.versionUuid || "";
    const display = row?.dataset.versionDisplay || "this version";
    if (!btn || btn.disabled || !objectId || !versionId || row?.dataset.canRevert !== "1") return;
    const confirmed = await confirmByProductName({
      title: `Revert to ${display}`,
      lead:
        "This restores that version’s content to the vault tip and local workspace now "
        + "(logical name like shaft.prt). You do not need to Check In afterward. "
        + "Newer numbered siblings are removed so Open does not prefer a leftover .N. "
        + "The current tip stays in History as an older row.",
      note:
        "Records a new version automatically. This cannot be undone by Cancel after you confirm. "
        + "If the model is already open in Creo, Creo may keep old geometry in memory until you "
        + "close the window or use File → Erase. When Creo is connected, CreoPDM will try to "
        + "remove it from session automatically.",
      submitLabel: "Revert",
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    try {
      const result = await withBusy(`Reverting to ${display}…`, async () => {
        const response = await fetch(
          `/api/objects/${encodeURIComponent(objectId)}/versions/${encodeURIComponent(versionId)}/revert`,
          { method: "POST" }
        );
        if (!response.ok) {
          throw new Error(await readError(response));
        }
        const body = await response.json().catch(() => ({}));
        let localSynced = false;
        let localWarning = "";
        // Erase before rematerialize so Windows can trash locked .N leftovers.
        const erase = await tryEraseModelsFromCreoSession(
          body.filename || body.disk_name || row?.dataset?.filename || ""
        );
        if (erase.attempted) {
          await creoYieldForDeferredErase();
        }
        try {
          const agent = await probeCreoAgent();
          if (agent) {
            await materializeViaAgent({
              object_id: objectId,
              product_id: body.product_uuid || currentProductId() || null,
              relative_path: body.relative_path || null,
              filename: body.filename || null,
              disk_name: body.filename || null,
              replace_newer: true,
              companions: [],
            });
            localSynced = true;
          } else {
            localWarning =
              "Vault restored. Start creopdm-agent on this PC, then Open the file to refresh the local workspace.";
          }
        } catch (localErr) {
          const detail =
            localErr && localErr.message ? String(localErr.message) : "local sync failed";
          localWarning =
            `Vault restored, but the local workspace still has a newer Creo save (${detail}). `
            + "Open the file again or use Purge workspace after the agent is running.";
        }
        // Second erase pass after disk replace.
        const eraseAfter = await tryEraseModelsFromCreoSession(
          body.filename || body.disk_name || row?.dataset?.filename || ""
        );
        return {
          localSynced,
          localWarning,
          erase: {
            erased: Math.max(Number(erase?.erased) || 0, Number(eraseAfter?.erased) || 0),
            attempted: Boolean(erase?.attempted || eraseAfter?.attempted),
          },
        };
      });
      const erased = Number(result?.erase?.erased) || 0;
      if (result?.localWarning) {
        showError(
          $("#toolbar-error"),
          `${result.localWarning} ${CREO_REVERT_SESSION_HINT}`
        );
      } else if (erased > 0) {
        showOk(
          `Reverted to ${display}. Vault and local workspace updated. `
          + "Removed from Creo session — Open again to load the restored file."
        );
      } else {
        showOk(
          (result?.localSynced
            ? `Reverted to ${display}. Vault and local workspace updated. `
            : `Reverted to ${display}. `)
          + CREO_REVERT_SESSION_HINT
        );
      }
      reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      showError($("#toolbar-error"), message || "Could not revert to that version.");
    }
  });

  syncRevertVersionButton();
  syncDetailToolbar();

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
      syncDetailToolbar();
    });
  });

  let whereUsedLoaded = false;
  async function loadWhereUsedTab() {
    const panel = $("#panel-where-used");
    if (!panel || panel.dataset.lazyWhereUsed !== "1" || whereUsedLoaded) return;
    const objectId = panel.dataset.objectId || "";
    const productId = panel.dataset.productId || "";
    if (!objectId) return;
    whereUsedLoaded = true;
    const host = $("#where-used-host");
    try {
      // Fast path first (deps + BOM). Full vault byte-scan is capped server-side
      // on large products so this request cannot hang the service.
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
          '<p class="muted">Not listed in any captured assembly/drawing BOM in this product yet. Open parent assemblies in Creo and Add or Check In to capture Where Used. (Vault byte-scan is skipped when the product has many assemblies, so the server stays responsive.)</p>';
        return;
      }
      const rows = items
        .map((row) => {
          const href = productId
            ? `/products/${encodeURIComponent(productId)}/objects/${encodeURIComponent(row.object_id || "")}`
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

  if (window.location.hash === "#history" || window.location.hash === "#file-history" || window.location.hash === "#versions") {
    document.querySelector('.tab[data-tab="history"]')?.click();
  } else if (window.location.hash === "#overview" || window.location.hash === "#details") {
    document.querySelector('.tab[data-tab="overview"]')?.click();
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

  function syncEmbeddedOpenOptions() {
    if (!settingsForm) return;
    const nested = settingsForm.querySelector("#embedded-open-options");
    if (!nested) return;
    const embeddedOn = Boolean(
      settingsForm.querySelector('input[name="creo_open_mode"][value="embedded"]')?.checked
    );
    nested.classList.toggle("is-disabled", !embeddedOn);
    if (embeddedOn) nested.removeAttribute("aria-disabled");
    else nested.setAttribute("aria-disabled", "true");
    nested.querySelectorAll("input, textarea, select").forEach((el) => {
      el.disabled = !embeddedOn;
    });
  }

  settingsForm?.querySelectorAll('input[name="creo_open_mode"]').forEach((radio) => {
    radio.addEventListener("change", syncEmbeddedOpenOptions);
  });
  syncEmbeddedOpenOptions();

  settingsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError($("#settings-error"), "");
    const ok = $("#settings-ok");
    if (ok) ok.hidden = true;
    const jsLibraryInput = settingsForm.querySelector('[name="creo_js_library"]');
    const jsLibraryValue = jsLibraryInput
      ? String(jsLibraryInput.value || "").trim() || null
      : null;
    const data = new FormData(settingsForm);
    const body = {
      creo_open_mode: String(data.get("creo_open_mode") || "association"),
      creo_executable: null,
      creo_view_executable: null,
      // Read even when the nested Embedded fields are disabled for association mode.
      creo_js_library: jsLibraryValue,
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
      workspace_poll_idle_minutes: (() => {
        const raw = String(data.get("workspace_poll_idle_minutes") || "").trim();
        if (!raw) return 10;
        const parsed = Number.parseInt(raw, 10);
        return Number.isFinite(parsed) ? parsed : 10;
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

  function watchIdleMinutes() {
    const idleMinutesRaw = Number.parseInt(
      document.body?.dataset?.workspacePollIdleMinutes || "10",
      10
    );
    return Number.isFinite(idleMinutesRaw)
      ? Math.min(24 * 60, Math.max(0, idleMinutesRaw))
      : 10;
  }

  function isWatchIdle() {
    const idleMinutes = watchIdleMinutes();
    return idleMinutes > 0 && Date.now() - lastUserActivityAt > idleMinutes * 60 * 1000;
  }

  function watchPaused() {
    if (document.hidden || busyDepth > 0) return true;
    // Ignore the busy overlay — it is also a <dialog>, and keepBusy reload leaves it open.
    if ([...document.querySelectorAll("dialog[open]")].some((dialog) => dialog.id !== "busy-overlay")) {
      return true;
    }
    return isWatchIdle();
  }

  // Files list only — Details / Admin / Settings may still expose a product id on the toolbar.
  const watchProductId = isListPage
    ? (openWorkspaceBtn?.dataset.product || addForm?.dataset.product || "")
    : "";
  let watchStamp = null;
  let watchReloadTimer = 0;
  let lastPendingCheckinCount = null;
  let lastUserActivityAt = Date.now();

  function noteUserActivity() {
    const wasIdle = isWatchIdle();
    lastUserActivityAt = Date.now();
    // Resume immediately when the user comes back after an idle pause.
    if (wasIdle && watchProductId && !document.hidden) {
      void pollWorkspaceWatch();
    }
  }

  async function pollWorkspaceWatch() {
    // Soft-nav can leave this closure briefly; never poll without the Files table.
    if (!watchProductId || !document.querySelector("#object-table") || watchPaused()) return;
    try {
      const [response, localPending] = await Promise.all([
        fetch(`/api/products/${watchProductId}/workspace-watch`),
        countLocalWorkspacePending(watchProductId),
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
        void refreshPendingCheckinIds(watchProductId);
      }
      // Local agent-cache saves do not change the vault stamp — refresh the open tab in place.
      if (activeListTab() === "changes") {
        if (lastChangesPending === null) {
          lastChangesPending = pending;
        } else if (pending !== lastChangesPending && !changesReloadBusy) {
          changesReloadBusy = true;
          knownWorkspacePaths.at = 0;
          cachedProductObjects.at = 0;
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
      cachedProductObjects.at = 0;
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

  if (watchProductId) {
    const pollMsRaw = Number.parseInt(document.body?.dataset?.workspacePollMs || "5000", 10);
    const pollMs = Number.isFinite(pollMsRaw) ? Math.min(120000, Math.max(500, pollMsRaw)) : 5000;
    trackedInterval(pollWorkspaceWatch, pollMs);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) {
        noteUserActivity();
        pollWorkspaceWatch();
      }
    });
    ["pointerdown", "mousemove", "keydown", "touchstart", "scroll", "wheel"].forEach((eventName) => {
      document.addEventListener(eventName, noteUserActivity, { passive: true, capture: true });
    });
    pollWorkspaceWatch();
  }

  document.querySelector("#detail-open-btn")?.addEventListener("click", async (event) => {
    event.preventDefault();
    const btn = event.currentTarget;
    const id = btn?.dataset?.uuid;
    if (!id) return;
    await openPdmObjectFromUi(id, {
      dataset: {
        filename: btn.getAttribute("data-filename") || btn.dataset.filename || id,
        canCheckout: dataFlag(btn, "can-checkout") ? "1" : "0",
        owned: dataFlag(btn, "owned") ? "1" : "0",
      },
      getAttribute: (name) => {
        if (name === "data-can-checkout") return dataFlag(btn, "can-checkout") ? "1" : "0";
        if (name === "data-owned") return dataFlag(btn, "owned") ? "1" : "0";
        if (name === "data-filename") {
          return btn.getAttribute("data-filename") || btn.dataset.filename || id;
        }
        return null;
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
        // Object may be free; userCap is enforced in promptOpenCheckout via body data-can-checkout.
        canCheckout: "1",
        owned: "0",
      },
    });
  });

  // Keep Creo.JS connected: soft-navigate shell pages (products, folders, settings, detail).
  // Do not gate on inCreoBrowser — a false negative caused hard reloads that SSR-paint
  // "Not Connected" and drop the live Creo.JS bridge.
  //
  // Bind once with the native addEventListener (no pageAbort signal). Soft boots
  // abort prior page listeners; if soft-nav lived there, a click mid-swap hard-reloaded
  // and painted Not Connected. Keep the latest handlers on window.__creopdmSoftNavApi.
  window.__creopdmSoftNavApi = {
    softNavigate,
    isSoftNavUrl,
    withBusy,
    eventEl,
    syncProductAccessUi,
    isMetadataCollectRunning: () => Boolean(metadataCollectJob.running),
    warnMetadataCollectBlockingNav: () => {
      showOk("Finish Collect metadata (or wait for it) before leaving this page.");
    },
  };
  if (!window.__creopdmSoftNavBound) {
    window.__creopdmSoftNavBound = true;
    origAddEventListener.call(
      document,
      "click",
      (event) => {
        const api = window.__creopdmSoftNavApi;
        if (!api) return;
        const link = api.eventEl(event)?.closest("a[href]");
        if (!link || event.defaultPrevented) return;
        if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        if (event.button != null && event.button !== 0) return;
        if (link.target && link.target !== "_self") return;
        // Folder name opens via onFileTableClick → leavePage; skip soft-nav here so
        // row chrome clicks still select without navigating.
        if (link.classList.contains("folder-open") || link.closest("tr.folder-row")) return;
        const href = link.getAttribute("href");
        if (!href || !api.isSoftNavUrl(href)) return;
        event.preventDefault();
        event.stopPropagation();
        // Collect already owns the busy overlay — do not nest a Loading busy on top
        // (that left Loading stuck until the next metadata tick).
        if (api.isMetadataCollectRunning()) {
          api.warnMetadataCollectBlockingNav();
          return;
        }
        void api.withBusy("Loading…", () => api.softNavigate(href, "push"));
      },
      true
    );
    origAddEventListener.call(window, "popstate", () => {
      const api = window.__creopdmSoftNavApi;
      if (!api || !api.isSoftNavUrl(window.location.href)) return;
      if (api.isMetadataCollectRunning()) {
        api.warnMetadataCollectBlockingNav();
        return;
      }
      void api.withBusy("Loading…", () => api.softNavigate(window.location.href, "none"));
    });
  }
  // Soft-nav replaces shell HTML without running inline <script>; keep product-access
  // toggle alive with a document-level listener (not aborted on soft boot).
  if (!window.__creopdmProductAccessBound) {
    window.__creopdmProductAccessBound = true;
    const onProductAccessToggle = (event) => {
      const api = window.__creopdmSoftNavApi;
      const t = event?.target;
      if (!t || t.id !== "access-all-products") return;
      if (api && typeof api.syncProductAccessUi === "function") api.syncProductAccessUi();
      else syncProductAccessUi();
    };
    origAddEventListener.call(document, "change", onProductAccessToggle, true);
    origAddEventListener.call(document, "input", onProductAccessToggle, true);
  }

  restoreStoredFilters();
  syncToolbar();
  syncProductAccessUi();
  const pendingProductId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
  if (isListPage && pendingProductId) void refreshPendingCheckinIds(pendingProductId);

  } finally {
    EventTarget.prototype.addEventListener = origAddEventListener;
  }
};

window.__creopdmBoot({ soft: false });
