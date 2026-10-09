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
      // Brief grace for that inject, then load /creojs.js when the PTC bridge
      // is present so browser reopen is not stuck waiting ~4s for a no-show.
      let tries = 0;
      let scriptStarted = false;
      const hasBridge = () => {
        try {
          return !!(window.external && window.external.ptc);
        } catch {
          return false;
        }
      };
      const appendCreojsFallback = () => {
        if (scriptStarted || window.CreoJS || !hasBridge()) return;
        scriptStarted = true;
        const script = document.createElement("script");
        script.src = "/creojs.js";
        script.onload = () => {
          tryInit();
          done(Boolean(window.CreoJS));
        };
        script.onerror = () => done(Boolean(window.CreoJS));
        document.head.appendChild(script);
      };
      // ~500ms grace with bridge; outside Creo never load creojs.js.
      const graceTries = hasBridge() ? 10 : 40;
      const maxTries = hasBridge() ? 80 : 40;
      const poll = trackedInterval(() => {
        tries += 1;
        if (window.CreoJS) {
          window.clearInterval(poll);
          tryInit();
          done(true);
          return;
        }
        if (hasBridge() && tries >= graceTries) {
          appendCreojsFallback();
        }
        if (tries < maxTries) return;
        window.clearInterval(poll);
        // Outside Creo, skip loading creojs.js — it cannot talk to a session.
        if (!hasBridge()) {
          done(false);
          return;
        }
        appendCreojsFallback();
        // onload/onerror settle when the script tag was started.
        if (!scriptStarted) done(false);
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
  let busyCancelHandler = null;
  const heartbeat = { ids: [], timer: 0 };
  function busyOverlayEl() {
    return document.getElementById("busy-overlay");
  }
  // Bind once with native listener (not pageAbort) — soft boots must not drop Escape cancel.
  if (!window.__creopdmBusyCancelBound) {
    window.__creopdmBusyCancelBound = true;
    origAddEventListener.call(
      document,
      "cancel",
      (event) => {
        if (event.target?.id !== "busy-overlay") return;
        // Never let Escape dismiss the modal while work owns busyDepth — that hung the UI.
        event.preventDefault();
        const api = window.__creopdmSoftNavApi;
        if (api && typeof api.invokeBusyCancel === "function") {
          // No-op when the current job did not register a cancel handler (Add, Check In, …).
          api.invokeBusyCancel();
        }
      },
      true
    );
    // Safety net: if the dialog is closed while still "busy", unstick the shell.
    origAddEventListener.call(
      document,
      "close",
      (event) => {
        if (event.target?.id !== "busy-overlay") return;
        const api = window.__creopdmSoftNavApi;
        if (api && typeof api.recoverStuckBusyOverlay === "function") {
          api.recoverStuckBusyOverlay();
        }
      },
      true
    );
  }
  function showBusyOverlay() {
    const busyOverlay = busyOverlayEl();
    if (!(busyOverlay instanceof HTMLDialogElement)) return;
    if (!busyOverlay.open) busyOverlay.showModal();
  }
  function hideBusyOverlay() {
    const busyOverlay = busyOverlayEl();
    if (!(busyOverlay instanceof HTMLDialogElement)) return;
    if (busyOverlay.open) busyOverlay.close();
  }
  function setBusyMessage(message) {
    const text = document.getElementById("busy-message");
    if (text) text.textContent = message || "Working…";
  }
  function setBusyCancelHandler(handler) {
    // Opt-in only: Escape cancels only when the job registered a clean abort.
    busyCancelHandler = typeof handler === "function" ? handler : null;
    // Window slot so the once-bound Escape handler (survives soft boot) always hits
    // the active job's handler, not a stale closure's null.
    window.__creopdmBusyCancelHandler = busyCancelHandler;
  }
  function invokeBusyCancel() {
    const handler = window.__creopdmBusyCancelHandler || busyCancelHandler;
    if (typeof handler === "function") void handler();
  }
  function forceClearBusy() {
    busyDepth = 0;
    setBusyCancelHandler(null);
    hideBusyOverlay();
    document.body.classList.remove("is-busy");
    document.body.removeAttribute("aria-busy");
  }
  function recoverStuckBusyOverlay() {
    // Dialog closed while depth > 0 (stale listener / browser quirk). Unstick UI only.
    if (busyDepth <= 0) return;
    if (typeof busyCancelHandler === "function") {
      void busyCancelHandler();
      return;
    }
    forceClearBusy();
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
    setBusyCancelHandler(null);
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

  function preparedDependencyCount(prepared) {
    const deps = Array.isArray(prepared?.dependencies) ? prepared.dependencies.length : 0;
    return deps + (prepared?.object_id ? 1 : 0);
  }

  function creoOpenModelTimeoutMs(depCount) {
    // Large JD assemblies need many minutes in Creo after materialize — 90s was
    // too short and surfaced "session may be offline" while Retrieve was still running.
    const n = Math.max(0, Number(depCount) || 0);
    return Math.min(900_000, Math.max(90_000, 60_000 + n * 40));
  }

  function openWorkTimeoutMs(depCount) {
    // Outer budget must cover prepare + zip materialize + Creo openModel.
    const n = Math.max(0, Number(depCount) || 0);
    return Math.min(1_200_000, Math.max(180_000, 120_000 + n * 80));
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
      // Auth / API must hard-load. Every other signed-in shell page soft-navs so
      // Creo.JS stays Connected (Files, Details/History, Admin*, Settings, …).
      if (
        path === "/login" ||
        path === "/logout" ||
        path === "/setup" ||
        path === "/forgot-password" ||
        path === "/reset-password" ||
        path === "/help" ||
        path.startsWith("/api/") ||
        path.startsWith("/static/") ||
        path === "/creojs.js"
      ) {
        return false;
      }
      if (path === "/" || path === "") return true;
      if (path.startsWith("/admin")) return true;
      if (path.startsWith("/settings")) return true;
      if (path.startsWith("/account")) return true;
      if (path === "/no-access") return true;
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

  // Files search lives only in the DOM — soft-nav to Details / Back replaces the
  // shell and would wipe it. Persist across leave + restore on the next Files boot.
  const LIST_SEARCH_KEY = "creopdmListSearch";
  // Files list tab (Files / Checked out / Modified / New files) — same lifetime.
  // Must be declared early: tab clicks / leavePage run before the late boot block.
  const WATCH_KEY = "creopdmWatchRestore";
  const LIST_RESTORE_TABS = new Set(["files", "checked-out", "modified", "changes"]);

  function persistListSearchState() {
    try {
      const input = document.querySelector("#search-input");
      if (!input || !document.querySelector("#object-table")) return;
      const q = (input.value || "").trim();
      const productId = currentProductId();
      if (!productId || !q) {
        sessionStorage.removeItem(LIST_SEARCH_KEY);
        return;
      }
      const ids =
        typeof selectedIds === "function"
          ? selectedIds()
          : [...document.querySelectorAll("#object-table tr.object-row.is-selected")]
              .map((row) => row.dataset.uuid)
              .filter(Boolean);
      sessionStorage.setItem(
        LIST_SEARCH_KEY,
        JSON.stringify({ productId, q, ids })
      );
    } catch {
      /* private mode / blocked storage */
    }
  }

  function persistListTabState(tabName, ids) {
    try {
      if (!document.querySelector("#object-table")) return;
      const rawTab =
        tabName
        ?? document.querySelector(".tabs .tab.is-active")?.dataset.tab
        ?? "";
      const activeTab = LIST_RESTORE_TABS.has(String(rawTab)) ? String(rawTab) : "";
      if (!activeTab) return;
      const selected =
        ids
        ?? (typeof selectedIds === "function"
          ? selectedIds()
          : [...document.querySelectorAll(
              "#object-table tr.object-row.is-selected, #modified-table tr.is-selected, #changes-table tr.is-selected, #checked-out-table tr.is-selected"
            )]
              .map((row) => row.dataset.uuid)
              .filter(Boolean));
      sessionStorage.setItem(
        WATCH_KEY,
        JSON.stringify({ ids: selected, tab: activeTab })
      );
    } catch {
      /* private mode / blocked storage */
    }
  }

  function loadUpdatedAppJs(src) {
    // Soft-nav cannot replace <script> via innerHTML; fetch the new cache-bust URL
    // so __creopdmBoot updates without a hard reload that drops Creo.JS.
    // Keep __creopdmSkipAutoBoot true until the new file's bottom guard runs (it
    // clears the flag) — clearing here in onload races the sync script body.
    return new Promise((resolve, reject) => {
      window.__creopdmSkipAutoBoot = true;
      const script = document.createElement("script");
      script.src = src;
      script.onload = () => {
        window.__creopdmAppJsSrc = src;
        [...document.querySelectorAll('script[src*="/client/app.js"]')]
          .filter((el) => el !== script)
          .forEach((el) => el.remove());
        resolve();
      };
      script.onerror = () => {
        window.__creopdmSkipAutoBoot = false;
        reject(new Error("Could not load updated CreoPDM client script."));
      };
      (document.head || document.documentElement).appendChild(script);
    });
  }

  function softNavigate(url, historyMode = "push") {
    if (metadataCollectJob.running) {
      showOk("Finish Collect metadata (or wait for it) before leaving this page.");
      return Promise.resolve();
    }
    const absolute = new URL(url, window.location.href);
    if (!isSoftNavUrl(absolute.href)) {
      persistListSearchState();
      window.location.href = absolute.href;
      return Promise.resolve();
    }
    const href = absolute.href;
    const mode = historyMode;
    const run = async () => {
      softNavBusy = true;
      window.__creopdmSoftNavBusy = true;
      try {
        // Capture search (+ selection) and Files list tab before the shell swap.
        // Only while #object-table exists — leaving Details must not overwrite
        // a New files / Modified restore with Overview/History.
        persistListSearchState();
        persistListTabState();
        let response;
        try {
          response = await fetch(href, {
            headers: { Accept: "text/html", "X-CreoPDM-Soft": "1" },
            credentials: "same-origin",
            // After remove/add the prior GET is often still in the HTTP cache; without
            // this, soft reload paints the deleted folder/file until a hard refresh.
            cache: "no-store",
            // Hung Open / Where Used can block the only server worker — do not leave
            // Loading… forever; fall through to a hard navigation attempt.
            signal: abortSignalAfter(45_000),
          });
        } catch {
          window.location.href = href;
          return;
        }
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
          if (creo && placeholder) {
            // Keep the live Connected pill, but refresh open-mode from the new HTML
            // so Settings → Embedded is not stuck on a stale association attr.
            const openMode = placeholder.getAttribute("data-creo-open-mode");
            if (openMode != null) creo.setAttribute("data-creo-open-mode", openMode);
            placeholder.replaceWith(creo);
          }
        }
        const nextUrl = response.url || href;
        // fetch() drops the fragment; keep #where-used / #history so Details tabs restore.
        let historyUrl = nextUrl;
        if (absolute.hash) {
          try {
            const resolved = new URL(nextUrl, window.location.origin);
            resolved.hash = absolute.hash;
            historyUrl = `${resolved.pathname}${resolved.search}${resolved.hash}`;
          } catch {
            historyUrl = nextUrl;
          }
        }
        if (mode === "push") {
          history.pushState({ creopdmSoft: 1 }, "", historyUrl);
        } else if (mode === "replace") {
          history.replaceState({ creopdmSoft: 1 }, "", historyUrl);
        }
        // Soft-nav only swaps main.shell — <script app.js> stays in memory. After
        // deploy/pull-restart the HTML cache-bust changes; load that script so Open
        // (Modified/New local) is not stuck on the previous association path.
        const nextAppJs =
          doc.querySelector('script[src*="/client/app.js"]')?.getAttribute("src") || "";
        const curAppJs =
          window.__creopdmAppJsSrc
          || document.querySelector('script[src*="/client/app.js"]')?.getAttribute("src")
          || "";
        if (nextAppJs && curAppJs && nextAppJs !== curAppJs) {
          try {
            await loadUpdatedAppJs(nextAppJs);
          } catch {
            window.location.href = href;
            return;
          }
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
    persistListSearchState();
    persistListTabState();
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
      PRE_WORK: "Pre-Work",
      IN_WORK: "In Work",
      IN_REVIEW: "In Review",
      APPROVED: "Approved",
      RELEASED: "Released",
      UNDER_CHANGE: "Under Change",
      OBSOLETE: "Obsolete",
      ARCHIVED: "Archived",
      LOCKED: "Locked",
    };
    return labels[key] || key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()) || "Locked";
  }

  function productAllowsContent() {
    const el = $("#metric-filters");
    if (!el || el.dataset.allowsContent == null || el.dataset.allowsContent === "") {
      return true;
    }
    return el.dataset.allowsContent === "1";
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
  const CAD_MODEL_CHILD_FILTERS = new Set([
    "creo_parts",
    "assemblies",
    "top_level_assemblies",
    "drawings",
  ]);
  const METRIC_LABELS = {
    folders: "folders",
    files: "all files",
    cad_models: "Creo models",
    creo_parts: "parts",
    assemblies: "assemblies",
    top_level_assemblies: "top-level assemblies",
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

  function topLevelAssemblyIds() {
    const root = document.querySelector("#metric-filters");
    const raw = root?.getAttribute("data-top-level-assemblies") || root?.dataset?.topLevelAssemblies || "";
    return new Set(
      raw.split(/[\s,;]+/).map((item) => item.trim()).filter(Boolean)
    );
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
    if (key === "top_level_assemblies") {
      const uuid = String(row.dataset.uuid || "").trim();
      if (!uuid) return false;
      if (rowAttr(row, "data-top-level-assembly") === "1" || row.dataset.topLevelAssembly === "1") {
        return true;
      }
      return topLevelAssemblyIds().has(uuid);
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
    if (tab === "modified") {
      return document.getElementById("modified-table")
        || document.getElementById("panel-modified")
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
    if (
      root.id === "panel-changes"
      || root.id === "changes-table"
      || root.id === "panel-modified"
      || root.id === "modified-table"
    ) {
      return [...root.querySelectorAll(".queue-row")];
    }
    return [...root.querySelectorAll(".object-row")];
  }

  function listedFolderRows() {
    const root = fileListRoot();
    if (!root) return [];
    if (root.id === "panel-changes" || root.id === "changes-table") return [];
    if (root.id === "panel-modified" || root.id === "modified-table") return [];
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

  function productHasListedObjects() {
    const root = document.querySelector("#metric-filters");
    const raw = Number.parseInt(root?.getAttribute("data-product-objects") || "", 10);
    if (Number.isFinite(raw)) return raw > 0;
    return productHasVaultFilesForExport();
  }

  function isFirstProductCheckIn() {
    return !productHasListedObjects();
  }

  function defaultAddHistoryComment({ count = 0, singleName = "" } = {}) {
    /** Blank Add → History text; first vault content gets a "First check in:" prefix. */
    const n = Math.max(0, Number(count) || 0);
    const name = String(singleName || "").trim();
    let base = "Add files";
    if (n > 1) base = `Add ${n} files`;
    else if (n === 1) base = name ? `Add ${name}` : "Add files";
    return isFirstProductCheckIn() ? `First check in: ${base}` : base;
  }

  function refreshTabMetrics() {
    applyMetricVisibility();
    applyMetricSelection();
    updateMetricCounts();
    syncMetricFiltersVisibility();
    syncSearchFormVisibility();
    syncToolbar();
  }

  function syncMetricFiltersVisibility() {
    const root = document.querySelector("#metric-filters");
    if (!root) return;
    const hide = !productHasListedObjects();
    if (root.hidden === hide) return;
    root.hidden = hide;
    if (hide) {
      metricButtons().forEach((btn) => {
        if (metricMode(btn) !== "off") setMetricMode(btn, "off");
      });
      applyMetricVisibility();
      applyMetricSelection();
    }
  }

  function setProductObjectCount(count) {
    const root = document.querySelector("#metric-filters");
    if (!root) return;
    const n = Math.max(0, Number(count) || 0);
    root.setAttribute("data-product-objects", String(n));
    syncMetricFiltersVisibility();
    syncSearchFormVisibility();
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
    if (key === "top_level_assemblies") {
      btn.title = mode === "off"
        ? "Filter to top-level assemblies (not used by another assembly). Drawing references do not count. Click again to clear."
        : "Showing top-level assemblies (selected). Click to clear.";
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
    const outcome = await indexWhereUsedUnderBusy(productId);
    if (!outcome?.started) {
      showError($("#toolbar-error"), outcome?.error || "Could not start Where Used indexing.");
      return;
    }
    if (outcome.state === "cancelled") {
      showOk(
        "Where Used indexing cancelled. Run Rebuild Where Used again if Top Level looks incomplete."
      );
      return;
    }
    if (outcome.state === "error" || outcome.state === "timeout") {
      showError($("#toolbar-error"), outcome.error || "Where Used indexing failed.");
      return;
    }
    if (outcome.state === "done") {
      const missMsg = outcome.parentsMissing
        ? ` ${outcome.parentsMissing} parent file(s) missing from vault.`
        : "";
      try {
        sessionStorage.setItem(
          "creopdmNotice",
          `Where Used index ready: ${outcome.edgesAdded} new link(s), ${outcome.edgesExisting} already stored.${missMsg}`
        );
      } catch {
        /* private mode / blocked storage */
      }
      reloadPage();
    }
  });

  function sleepMs(ms, signal) {
    return new Promise((resolve) => {
      if (signal?.aborted) {
        resolve();
        return;
      }
      const timer = window.setTimeout(resolve, ms);
      if (!signal) return;
      const onAbort = () => {
        window.clearTimeout(timer);
        resolve();
      };
      signal.addEventListener("abort", onAbort, { once: true });
    });
  }

  function whereUsedBusyText(doneCount, total) {
    if (total > 0) return `Indexing Where Used… ${doneCount} of ${total}`;
    return "Indexing Where Used… preparing…";
  }

  function metadataBusyText(doneCount, total, filename) {
    const name = filename ? `: ${filename}` : "";
    if (total > 0) return `Collecting Creo metadata… ${doneCount} of ${total}${name}`;
    return "Collecting Creo metadata…";
  }

  function publishBusyMessage(message) {
    const api = window.__creopdmSoftNavApi;
    if (api && typeof api.setBusyMessage === "function") api.setBusyMessage(message);
    else setBusyMessage(message);
  }

  async function cancelWhereUsedIndex(productId) {
    if (!productId) return;
    try {
      await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`, {
        method: "DELETE",
      });
    } catch {
      /* still clear UI even if cancel request fails */
    }
  }

  async function runWhereUsedProgress(productId) {
    // Caller already owns the busy overlay — keep it up through N of M.
    setBusyMessage("Indexing Where Used… preparing…");
    return awaitWhereUsedIndex(productId, {
      onProgress: (doneCount, total) => {
        publishBusyMessage(whereUsedBusyText(doneCount, total));
      },
    });
  }

  async function indexWhereUsedUnderBusy(productId) {
    if (!productId) return null;
    // Nested under Add/Compressed busy: do not clearBusy between import and index
    // (that flashed the Files list before Where Used finished — false Top Level).
    if (busyDepth > 0) {
      return runWhereUsedProgress(productId);
    }
    try {
      return await withBusy("Indexing Where Used… preparing…", () =>
        runWhereUsedProgress(productId)
      );
    } finally {
      // Escape cancel must never leave the modal stuck over the app.
      if (busyDepth > 0) forceClearBusy();
    }
  }

  function utilitiesRepairNotice(form, { ok, error } = {}) {
    const article = form?.closest("article") || document.querySelector(".admin-utilities");
    if (!article) return;
    article.querySelectorAll("p.ok, p.error").forEach((el) => el.remove());
    const p = document.createElement("p");
    p.className = error ? "error" : "ok";
    p.textContent = error || ok || "";
    const h1 = article.querySelector("h1");
    if (h1) h1.after(p);
    else article.prepend(p);
  }

  async function runUtilitiesRebuildWithWhereUsed(form) {
    if (!(form instanceof HTMLFormElement)) return;
    const select = form.querySelector('select[name="product_id"]');
    const productId = (select?.value || "").trim();
    const label = select?.selectedOptions?.[0]?.textContent?.trim() || "product";
    const fd = new FormData(form);
    const action = String(fd.get("repair_action") || "");
    let initial = "Indexing Where Used… preparing…";
    if (action === "rebuild") initial = `Rebuilding product database for ${label}…`;
    else if (action === "clear_metadata") {
      initial = `Deleting Creo metadata for ${label}…`;
    }
    const btn = form.querySelector('button[type="submit"]');
    if (btn instanceof HTMLButtonElement) btn.disabled = true;
    try {
      await withBusy(initial, async () => {
        const response = await fetch(form.getAttribute("action") || form.action, {
          method: "POST",
          body: fd,
        });
        const html = await response.text();
        const parsed = new DOMParser().parseFromString(html, "text/html");
        if (!response.ok) {
          utilitiesRepairNotice(form, {
            error:
              parsed.querySelector("p.error")?.textContent?.trim()
              || "Could not start the selected action.",
          });
          return;
        }
        const priorOk = parsed.querySelector("p.ok")?.textContent?.trim() || "";
        publishBusyMessage("Indexing Where Used… preparing…");
        // Form POST schedules Start after the response (so the HTML fetch is not
        // blocked by the indexer write lock). POST Start here for N of M + Cancel
        // (no-op if the background task already started the same run).
        const outcome = await awaitWhereUsedIndex(productId, {
          start: true,
          onProgress: (doneCount, total) => {
            publishBusyMessage(whereUsedBusyText(doneCount, total));
          },
        });
        if (outcome?.state === "cancelled") {
          utilitiesRepairNotice(form, {
            ok:
              "Where Used indexing cancelled. Run Delete and rebuild Where Used again "
              + "if Top Level / dependencies look incomplete.",
          });
          return;
        }
        if (!outcome || outcome.state === "error" || outcome.state === "timeout") {
          utilitiesRepairNotice(form, {
            error: outcome?.error || "Where Used indexing failed.",
          });
          return;
        }
        if (outcome.state === "done") {
          const missMsg = outcome.parentsMissing
            ? ` ${outcome.parentsMissing} parent file(s) missing from vault.`
            : "";
          const wu =
            `Where Used index ready: ${outcome.edgesAdded} new link(s), `
            + `${outcome.edgesExisting} already stored.${missMsg}`;
          const msg = priorOk && !/where used/i.test(priorOk) ? `${priorOk} ${wu}` : wu;
          utilitiesRepairNotice(form, { ok: msg });
        }
      });
    } finally {
      forceClearBusy();
      if (btn instanceof HTMLButtonElement) btn.disabled = false;
    }
  }

  /**
   * Start Where Used indexing and wait until done/error/cancelled.
   * Used under the Add (and gear Rebuild) busy overlay — not fire-and-forget.
   * Escape stops the server job and clears the overlay.
   */
  async function awaitWhereUsedIndex(productId, { onProgress, start = true } = {}) {
    if (!productId) return { started: false };
    let expectStartedAt = 0;
    let sawActive = false;
    let userCancelled = false;
    let cancelInFlight = false;
    const ac = new AbortController();
    const requestCancel = async () => {
      if (userCancelled || cancelInFlight) return;
      cancelInFlight = true;
      userCancelled = true;
      publishBusyMessage("Cancelling Where Used indexing…");
      // Abort Start/poll fetches — otherwise a hung Start left Cancel looking dead.
      try {
        ac.abort();
      } catch {
        /* ignore */
      }
      await cancelWhereUsedIndex(productId);
    };
    setBusyCancelHandler(requestCancel);
    try {
      if (start) {
        let startResponse;
        try {
          startResponse = await fetch(
            `/api/products/${encodeURIComponent(productId)}/rebuild-where-used`,
            { method: "POST", signal: ac.signal }
          );
        } catch (exc) {
          if (userCancelled || ac.signal.aborted) {
            return { started: true, state: "cancelled" };
          }
          return { started: false, error: exc?.message || "Could not reach CreoPDM." };
        }
        if (userCancelled) return { started: true, state: "cancelled" };
        if (!startResponse.ok) {
          return { started: false, error: await readError(startResponse) };
        }
        try {
          const startBody = await startResponse.json();
          expectStartedAt = Number(startBody.started_at) || 0;
          const startState = String(startBody.state || "");
          if (startState === "queued" || startState === "running") sawActive = true;
          const startTotal = Number(startBody.parents_total) || 0;
          const startDone = Number(startBody.parents_done) || 0;
          onProgress?.(startDone, startTotal);
        } catch {
          /* status body optional */
        }
      }
      for (let tries = 0; tries < 1800; tries += 1) {
        if (userCancelled || ac.signal.aborted) {
          return { started: true, state: "cancelled" };
        }
        try {
          const response = await fetch(
            `/api/products/${encodeURIComponent(productId)}/rebuild-where-used`,
            { signal: ac.signal }
          );
          if (!response.ok) {
            await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
            continue;
          }
          const body = await response.json();
          const state = String(body.state || "");
          const startedAt = Number(body.started_at) || 0;
          const total = Number(body.parents_total) || 0;
          const doneCount = Number(body.parents_done) || 0;
          // Ignore a prior job's terminal status (utilities used to flash "done" instantly).
          if (
            expectStartedAt
            && startedAt
            && startedAt + 0.001 < expectStartedAt
            && state !== "queued"
            && state !== "running"
          ) {
            await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
            continue;
          }
          if (state === "queued" || state === "running") {
            sawActive = true;
            onProgress?.(doneCount, total);
            await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
            continue;
          }
          if (state === "done") {
            if (expectStartedAt && startedAt && startedAt + 0.001 < expectStartedAt) {
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            // Stale idle→done (no Start stamp) or unfinished progress — keep waiting.
            if (start && !sawActive) {
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            if (total > 0 && doneCount < total) {
              onProgress?.(doneCount, total);
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            onProgress?.(doneCount, total);
            return {
              started: true,
              state: "done",
              edgesAdded: Number(body.edges_added) || 0,
              edgesExisting: Number(body.edges_existing) || 0,
              parentsMissing: Number(body.parents_missing_vault) || 0,
              parentsTotal: total,
              parentsDone: doneCount,
            };
          }
          if (state === "cancelled") {
            return { started: true, state: "cancelled" };
          }
          if (state === "error") {
            return {
              started: true,
              state: "error",
              error: body.error || "Where Used indexing failed.",
            };
          }
          // idle while waiting for a job we started — keep polling
          if (expectStartedAt || start) {
            await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
            continue;
          }
          return { started: true, state: state || "idle" };
        } catch {
          if (userCancelled || ac.signal.aborted) {
            return { started: true, state: "cancelled" };
          }
          /* ignore transient poll errors */
        }
        await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
      }
      return {
        started: true,
        state: "timeout",
        error: "Where Used indexing timed out. Try Rebuild Where Used from the product gear.",
      };
    } finally {
      setBusyCancelHandler(null);
    }
  }

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
          try {
            sessionStorage.setItem(
              "creopdmNotice",
              `Where Used index ready: ${added} new link(s), ${existing} already stored.${missMsg}`
            );
          } catch {
            /* private mode / blocked storage */
          }
          // Refresh Files so Top level assemblies / Where Used gates appear.
          reloadPage();
          return;
        }
        if (state === "cancelled") {
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

  async function pushOneCreoMetadataTarget(target, options) {
    // No per-file JS timeout — large assemblies (e.g. 844j.asm) can take many
    // minutes in Creo. Skipping them loses the metadata we care about most.
    // Cancel still works between models; during a Creo retrieve the UI may pause.
    // Bulk Collect: tip-only prepare, no empty-session probe, defer Erase, skip
    // feature.name reads (Open session capture fills renamed Features later).
    const opts = options && typeof options === "object" ? options : {};
    try {
      let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
      if (!filePath) {
        filePath = (await prepareLocalPathForMetadata(target.uuid, target.filename)) || "";
      }
      if (!filePath) {
        return { ok: false, reason: "materialize_failed" };
      }
      let snapshot = await gatherCreoMetadataForFilename(target.filename, filePath, {
        deferErase: opts.deferErase !== false,
        // Default on — Details Features need tree names (RIGHT, DEFAULT_CS, …).
        featureNames: opts.featureNames !== false,
        pendingErase: opts.pendingErase,
      });
      if (snapshot && snapshot.__error) {
        return {
          ok: false,
          reason: String(snapshot.__error),
          detail: String(snapshot.__detail || ""),
        };
      }
      if (!snapshot) return { ok: false, reason: "gather_failed" };
      // Require a real identity filename so empty/failed snapshots are never "saved".
      const identityName = String(snapshot.identity?.file_name || snapshot.identity?.full_name || "").trim();
      if (!identityName) {
        return { ok: false, reason: "empty_identity" };
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
        structure: Array.isArray(snapshot.structure) ? snapshot.structure : null,
      };
      try {
        const response = await fetch(`/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        if (response.ok) {
          await postAiSnapshotFromGather(target.uuid, target.versionId || null, snapshot, {
            objectFilename: target.filename,
          });
        }
        return {
          ok: response.ok,
          reason: response.ok ? "" : "post_failed",
        };
      } catch {
        return { ok: false, reason: "post_failed" };
      }
    } catch {
      return { ok: false, reason: "exception" };
    }
  }

  async function attachCollectLocalPaths(productId, targets) {
    // Warm workspace: resolve tip paths once so Collect skips per-file open-prepare.
    if (!productId || !Array.isArray(targets) || !targets.length) return;
    try {
      const [workdir, cacheFiles] = await Promise.all([
        agentWorkdir(productId, currentVaultFolder()).catch(() => ""),
        listAgentCacheFiles(productId),
      ]);
      if (!workdir || !Array.isArray(cacheFiles) || !cacheFiles.length) return;
      const byRel = new Map();
      const byLogical = new Map();
      cacheFiles.forEach((item) => {
        const rel = String(item?.relative_path || item?.path || "")
          .replace(/\\/g, "/")
          .replace(/^\/+/, "");
        if (!rel) return;
        const full = joinLocalWorkspacePath(workdir, rel);
        if (!full || !looksLikeLocalWindowsPath(full)) return;
        byRel.set(rel.toLowerCase(), full);
        const base = PathBasename(rel);
        const logical = (logicalUploadName(base) || base).toLowerCase();
        if (logical && !byLogical.has(logical)) byLogical.set(logical, full);
      });
      targets.forEach((target) => {
        if (looksLikeLocalWindowsPath(target.path)) return;
        const rel = String(target.relativePath || "").replace(/\\/g, "/").replace(/^\/+/, "");
        if (rel && byRel.has(rel.toLowerCase())) {
          target.path = byRel.get(rel.toLowerCase());
          return;
        }
        const logical = (logicalUploadName(target.filename) || target.filename || "").toLowerCase();
        if (logical && byLogical.has(logical)) {
          target.path = byLogical.get(logical);
        }
      });
    } catch {
      /* prepare-per-file still works */
    }
  }

  async function flushPendingMetadataErase(pendingErase) {
    const list = Array.isArray(pendingErase) ? pendingErase.splice(0, pendingErase.length) : [];
    if (!list.length) return;
    if (typeof window.CreoJS?.eraseSessionModelsByNames !== "function") return;
    try {
      await window.CreoJS.eraseSessionModelsByNames(list, { allowUndisplayed: false });
    } catch {
      /* best-effort */
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
    // Same Escape cancel as Where Used — stops between models; clears overlay via finally.
    setBusyCancelHandler(() => {
      metadataCollectJob.cancel = true;
      publishBusyMessage("Cancelling metadata collection…");
      showOk("Cancelling metadata collection…");
    });
    let index = Math.max(0, Number(state.index) || 0);
    let captured = Number(state.captured) || 0;
    let failed = Number(state.failed) || 0;
    let lastReason = "";
    let shouldRefreshList = false;
    const pendingErase = [];
    try {
      // Fresh runs: parts/asms before drawings so companions land before .drw Retrieve.
      // Do not re-order mid-resume (index would point at the wrong file).
      if (index === 0 && targets.length > 1) {
        const sorted = sortMetadataCollectTargets(targets);
        targets.splice(0, targets.length, ...sorted);
        state.targets = targets;
      }
      if (state.productId) {
        setBusyMessage("Checking local workspace tips…");
        await attachCollectLocalPaths(state.productId, targets);
      }
      while (index < targets.length) {
        if (metadataCollectJob.cancel) break;
        const target = targets[index];
        const message =
          `Collecting Creo metadata… ${index + 1} of ${targets.length}: ${target.filename}` +
          ` (${captured} saved, ${failed} skipped` +
          (lastReason ? `, last: ${lastReason}` : "") +
          `)`;
        setBusyMessage(message);
        // Avoid showOk every file — toolbar churn; busy overlay carries progress.
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
        const result = await pushOneCreoMetadataTarget(target, {
          deferErase: true,
          featureNames: true,
          pendingErase,
        });
        if (result.ok) {
          captured += 1;
          // Keep mass/units/feature gap hints on success so we can watch Collect.
          lastReason = String(result.reason || "");
        } else {
          failed += 1;
          lastReason = String(result.reason || "skipped");
        }
        index += 1;
        if (pendingErase.length >= 25) {
          await flushPendingMetadataErase(pendingErase);
        }
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
      await flushPendingMetadataErase(pendingErase);
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
      setBusyCancelHandler(null);
      clearBusy();
      forceClearBusy();
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
    const targets = sortMetadataCollectTargets(
      (Array.isArray(rows) ? rows : [])
        .map((row) => ({
          uuid: String(row.uuid || "").trim(),
          filename: String(row.filename || "").trim(),
          path: "",
          relativePath: String(row.relative_path || "").trim(),
          versionId: String(row.current_version?.uuid || row.version_id || "").trim(),
        }))
        .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename))
    );
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
    if (!productId) return;
    const formData = new FormData(deleteProductForm);
    const password = String(formData.get("confirm_password") || "");
    if (!password) {
      showError($("#delete-product-error"), "Enter your password to confirm.");
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
                  // Product Delete: trash the folder too (Clear workspace keeps it).
                  remove_folder: true,
                }),
                signal: abortSignalAfter(60_000),
              });
              if (!localResponse.ok) {
                notices.push(await readError(localResponse));
              } else {
                try {
                  const localBody = await localResponse.json();
                  if (localBody?.message && localBody.deleted === false) {
                    notices.push(String(localBody.message));
                  } else if (
                    typeof localBody?.message === "string" &&
                    /could not be removed|still locked|still present/i.test(localBody.message)
                  ) {
                    notices.push(String(localBody.message));
                  }
                } catch {
                  /* ignore */
                }
              }
            } catch (exc) {
              notices.push(
                exc?.name === "AbortError"
                  ? "Timed out clearing the local workspace (Creo may still have files open). Server delete continues."
                  : exc?.message ||
                      "Could not reach creopdm-agent to delete the local workspace."
              );
            }
          }
        }
        const forgetResponse = await fetch(`/api/products/${productId}/forget`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ confirm_password: password }),
          signal: abortSignalAfter(120_000),
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
        exc?.name === "AbortError"
          ? "Delete timed out. Cancel any still-running Add, wait a few seconds, or restart CreoPDM, then try again (uncheck local workspace if Creo has that folder open)."
          : exc?.message || "Could not delete the product."
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

  function defaultPurgeableExtensionSet() {
    // Details / soft-nav without #metric-filters still must recognize Creo .ext.N
    // (base-plate.prt.2). Keep in sync with DEFAULT_PURGEABLE_EXTENSIONS.
    return new Set([
      ".asm", ".dat", ".drw", ".err", ".frm", ".gph", ".inf", ".lsl", ".lst",
      ".mat", ".mrd", ".ncl", ".neu", ".prt", ".sec", ".sym", ".tbl", ".tph",
      ".txt", ".xml",
    ]);
  }

  function purgeableExtensionSet() {
    /**
     * Prefer Files metric-filters, then body (Details / all pages via base.html).
     * Never return empty — creoSaveNumber / logicalUploadName would treat
     * base-plate.prt.2 as save 0 and Compare would miss Newer local save.
     */
    const raw =
      document.getElementById("metric-filters")?.dataset?.purgeable
      || document.body?.dataset?.purgeable
      || "";
    const fromDom = raw
      .split(/[\s,;]+/)
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean)
      .map((item) => (item.startsWith(".") ? item : `.${item}`));
    if (fromDom.length) return new Set(fromDom);
    return defaultPurgeableExtensionSet();
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
  async function pollZipImportJob(productId, jobId, { signal } = {}) {
    // Busy overlay text while agent streams the zip and the server imports.
    while (!signal?.aborted) {
      try {
        const response = await fetch(
          `/api/products/${encodeURIComponent(productId)}/zip-import/jobs/${encodeURIComponent(jobId)}`,
          { signal }
        );
        if (response.ok) {
          const body = await response.json();
          const message = String(body.message || "").trim();
          if (message) setBusyMessage(message);
          if (body.done) return body;
        }
      } catch (err) {
        if (signal?.aborted) return null;
        /* keep polling through transient errors */
      }
      await new Promise((resolve) => window.setTimeout(resolve, 500));
    }
    return null;
  }

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
    const pollAbort = new AbortController();
    try {
      // One busy session for upload/import AND Where Used — clearing between those
      // returned the Files list early with a sparse graph (~every asm as Top Level).
      const pack = await withBusy(
        "Starting compressed import…",
        async () => {
          const jobResponse = await fetch(
            `/api/products/${encodeURIComponent(productId)}/zip-import/jobs`,
            { method: "POST" }
          );
          if (!jobResponse.ok) {
            throw new Error(await readError(jobResponse));
          }
          const job = await jobResponse.json();
          const jobId = String(job.job_id || "").trim();
          if (!jobId) {
            throw new Error("Could not start zip import progress.");
          }
          if (job.message) setBusyMessage(job.message);
          let jobFinal = null;
          const pollPromise = pollZipImportJob(productId, jobId, {
            signal: pollAbort.signal,
          }).then((body) => {
            jobFinal = body;
            return body;
          });
          let result;
          try {
            const response = await fetch(`${agentBase()}/import-zip`, {
              method: "POST",
              headers: agentAuthHeaders({ "Content-Type": "application/json" }),
              body: JSON.stringify({
                pdm_url: window.location.origin,
                product_id: productId,
                zip_path: chosenZipPath,
                parent_folder: currentFolder() || "",
                job_id: jobId,
                ...agentPdmAuth(),
              }),
            });
            if (!response.ok) {
              throw new Error(await readError(response));
            }
            result = await response.json();
          } finally {
            pollAbort.abort();
            try {
              await pollPromise;
            } catch {
              /* aborted */
            }
          }
          // Huge zips may omit/truncate ok[] in the agent response — job totals still count.
          let jobFilesTotal =
            Number(jobFinal?.files_total) || Number(jobFinal?.files_done) || 0;
          if (!jobFilesTotal && jobId) {
            try {
              const statusResponse = await fetch(
                `/api/products/${encodeURIComponent(productId)}/zip-import/jobs/${encodeURIComponent(jobId)}`
              );
              if (statusResponse.ok) {
                const statusBody = await statusResponse.json();
                jobFilesTotal =
                  Number(statusBody.files_total) || Number(statusBody.files_done) || 0;
              }
            } catch {
              /* ignore */
            }
          }
          const okCount = (result?.ok?.length || 0) || jobFilesTotal;
          let indexOutcome = null;
          if (okCount) {
            indexOutcome = await indexWhereUsedUnderBusy(productId);
            if (canGatherCreoMetadata() && Array.isArray(result?.ok) && result.ok.length) {
              publishBusyMessage("Collecting Creo metadata…");
              await pushCreoMetadataForItems(metadataTargetsFromResult(result));
            }
            const failedInside = result?.failed || [];
            if (failedInside.length) {
              const sample = failedInside
                .slice(0, 3)
                .map((item) => item.filename || "file")
                .join(", ");
              try {
                sessionStorage.setItem(
                  "creopdmNotice",
                  `Imported ${okCount} file(s); ${failedInside.length} failed (${sample}${failedInside.length > 3 ? ", …" : ""}).`
                );
              } catch {
                /* private mode / blocked storage */
              }
            } else if (indexOutcome?.state === "cancelled") {
              try {
                sessionStorage.setItem(
                  "creopdmNotice",
                  "Where Used indexing cancelled. Run Rebuild Where Used if Top Level looks incomplete."
                );
              } catch {
                /* private mode / blocked storage */
              }
            } else if (
              !indexOutcome?.started
              || indexOutcome?.state === "error"
              || indexOutcome?.state === "timeout"
            ) {
              try {
                sessionStorage.setItem(
                  "creopdmNotice",
                  indexOutcome?.error
                    || "Where Used indexing did not finish. Run Rebuild Where Used from the product gear."
                );
              } catch {
                /* private mode / blocked storage */
              }
            }
            // Refresh while this withBusy is still open — no Files flash between index and reload.
            await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
          }
          return { result, indexOutcome, okCount };
        }
      );
      const result = pack?.result;
      const failed = result?.failed || [];
      const okCount = pack?.okCount || 0;
      if (failed.length && !okCount) {
        const first = failed[0]?.message || "Could not import the zip.";
        showError($("#toolbar-error"), first);
      }
    } catch (err) {
      pollAbort.abort();
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
    let indexOutcome = null;
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
      const out = await (async () => {
      async function addAgentPathChunks(paths, baseFolder, commentOnce, batchOpts) {
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
        const opts = batchOpts && typeof batchOpts === "object" ? batchOpts : {};
        // One Audit import_batch_id for the whole Add (all 25-path /add-paths calls).
        const importBatchId = String(opts.importBatchId || "").trim()
          || (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
            ? crypto.randomUUID()
            : `add-${Date.now()}-${Math.random().toString(16).slice(2)}`);
        const batchTotal = Math.max(1, Number(opts.batchTotal) || total);
        const basenameOf = (path) => {
          const text = String(path || "");
          const parts = text.split(/[/\\]/);
          return parts[parts.length - 1] || text;
        };
        // Stable History comment for every chunk (blank → "Add 935 files", not "Add 5 files").
        const effectiveComment =
          String(commentOnce || "").trim()
          || defaultAddHistoryComment({
            count: batchTotal,
            singleName: total === 1 ? basenameOf(list[0]) : "",
          });
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
                client_total: batchTotal,
                import_batch_id: importBatchId,
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
      // One batch id for the whole Add so Audit merges agent 25-path calls.
      const agentImportBatchId =
        typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
          ? crypto.randomUUID()
          : `add-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      if (chosenAgentFolderBatches.length) {
        const combined = { ok: [], failed: [] };
        const folderBatchTotal = Math.max(1, Number(bulkCount) || 0)
          || chosenAgentFolderBatches.reduce(
            (sum, batch) => sum + (batch.paths?.length || 0),
            0
          );
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
              || defaultAddHistoryComment({ count: folderBatchTotal }),
            { importBatchId: agentImportBatchId, batchTotal: folderBatchTotal }
          );
          if (!part) return combined.ok.length ? combined : null;
          combined.ok.push(...(part.ok || []));
          combined.failed.push(...(part.failed || []));
        }
        return combined;
      }
      if (chosenAgentPaths.length) {
        return addAgentPathChunks(
          chosenAgentPaths,
          chosenAgentBaseFolder,
          comment,
          {
            importBatchId: agentImportBatchId,
            batchTotal: chosenAgentPaths.length,
          }
        );
      }
      if (chosenUploads.length) {
        const combined = { ok: [], failed: [] };
        const total = chosenUploads.length;
        const parentFolder = currentFolder() || "";
        const importBatchId =
          typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
            ? crypto.randomUUID()
            : `add-${Date.now()}-${Math.random().toString(16).slice(2)}`;
        for (let offset = 0; offset < chosenUploads.length; offset += UPLOAD_CHUNK) {
          const chunk = chosenUploads.slice(offset, offset + UPLOAD_CHUNK);
          const done = Math.min(offset + chunk.length, total);
          setBusyMessage(`Adding files… ${done} of ${total}`);
          const data = new FormData();
          const uploadComment =
            comment
            || defaultAddHistoryComment({
              count: total,
              singleName: total === 1 ? (chunk[0]?.file?.name || "file") : "",
            });
          if (uploadComment) data.append("comment", uploadComment);
          data.append("batch_total", String(total));
          data.append("import_batch_id", importBatchId);
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
      })();
      // Keep the same busy overlay through Where Used then metadata (no Files flash).
      if (out?.ok?.length) {
        const okN = out.ok.length;
        indexOutcome = await indexWhereUsedUnderBusy(productId);
        if (canGatherCreoMetadata()) {
          publishBusyMessage("Collecting Creo metadata…");
          await pushCreoMetadataForItems(metadataTargetsFromResult(out));
        }
        const failedInside = out.failed || [];
        if (failedInside.length) {
          const codes = (() => {
            const counts = {};
            for (const item of failedInside) {
              const code = String(item?.code || "FAILED").trim() || "FAILED";
              counts[code] = (counts[code] || 0) + 1;
            }
            return Object.keys(counts)
              .sort()
              .map((code) => `${code}=${counts[code]}`)
              .join(", ");
          })();
          const sample = failedInside
            .slice(0, 3)
            .map((item) => item.filename || item.uuid || "file")
            .join(", ");
          try {
            sessionStorage.setItem(
              "creopdmNotice",
              `Added ${okN} file(s); ${failedInside.length} failed` +
                (codes ? ` [${codes}]` : "") +
                ` (${sample}${failedInside.length > 3 ? ", …" : ""}).` +
                " See creopdm-agent log for each file."
            );
          } catch {
            /* private mode / blocked storage */
          }
        } else if (indexOutcome?.state === "cancelled") {
          try {
            sessionStorage.setItem(
              "creopdmNotice",
              "Where Used indexing cancelled. Run Rebuild Where Used if Top Level looks incomplete."
            );
          } catch {
            /* private mode / blocked storage */
          }
        } else if (
          !indexOutcome?.started
          || indexOutcome?.state === "error"
          || indexOutcome?.state === "timeout"
        ) {
          try {
            sessionStorage.setItem(
              "creopdmNotice",
              indexOutcome?.error
                || "Where Used indexing did not finish. Run Rebuild Where Used from the product gear."
            );
          } catch {
            /* private mode / blocked storage */
          }
        }
        await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
      }
      return out;
    });
    if (!result) return;
    const failed = result.failed || [];
    const okCount = result.ok?.length || 0;
    if (failed.length && !okCount) {
      const first = failed[0]?.message || "Could not add files.";
      const counts = {};
      for (const item of failed) {
        const code = String(item?.code || "FAILED").trim() || "FAILED";
        counts[code] = (counts[code] || 0) + 1;
      }
      const codes = Object.keys(counts)
        .sort()
        .map((code) => `${code}=${counts[code]}`)
        .join(", ");
      const msg =
        first +
        ` (${failed.length} files failed` +
        (codes ? `: ${codes}` : "") +
        ").";
      showError($("#add-error"), msg);
      try {
        sessionStorage.setItem("creopdmNotice", msg);
      } catch {
        /* private mode / blocked storage */
      }
    }
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

  function formatBomQty(value) {
    // BOM counts are whole numbers — show 1 not 1.0.
    const n = Number(value);
    if (!Number.isFinite(n)) return String(value ?? 1);
    return String(Math.round(n));
  }

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

  function truncateMiddlePath(path, maxLen = 64) {
    // Search (and other product-wide lists) show vault-relative paths under the
    // filename. Keep the first folder and the leaf so deep trees stay readable.
    const s = String(path || "").replace(/\\/g, "/");
    if (s.length <= maxLen) return s;
    const parts = s.split("/").filter((part) => part.length);
    if (parts.length >= 2) {
      const first = parts[0];
      const last = parts[parts.length - 1];
      if (parts.length >= 3) {
        const withParent = `${first}/…/${parts.slice(-2).join("/")}`;
        if (withParent.length <= maxLen) return withParent;
      }
      const withFile = `${first}/…/${last}`;
      if (withFile.length <= maxLen) return withFile;
    }
    const ellip = "…";
    const budget = Math.max(12, maxLen - ellip.length);
    const head = Math.ceil(budget * 0.35);
    const tail = budget - head;
    return `${s.slice(0, head)}${ellip}${s.slice(-tail)}`;
  }

  function searchPathLineHtml(relative, filename) {
    const full = String(relative || "").replace(/\\/g, "/");
    const name = String(filename || "");
    if (!full || full === name) return "";
    const shown = truncateMiddlePath(full);
    return `<div class="muted small search-path" title="${escapeHtml(full)}">${escapeHtml(shown)}</div>`;
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
    const pathLine = searchPathLineHtml(relative, filename);
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
    const topLevel = topLevelAssemblyIds().has(String(obj.uuid || ""));
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
              data-top-level-assembly="${topLevel ? "1" : "0"}"
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
      persistListSearchState();
      showFolderView();
      applyMetricVisibility();
      applyMetricSelection();
      syncToolbar();
      return;
    }
    searchTimer = window.setTimeout(() => {
      persistListSearchState();
      void searchAllFolders(query);
    }, 200);
  }

  function syncSearchFormVisibility() {
    // Product search only applies to the Files list — hide on Checked out /
    // Modified / New files so the box is not left looking broken. Also hide
    // when the product has no objects yet (nothing to search).
    const form = $("#search-form");
    if (!form) return;
    form.hidden = activeListTab() !== "files" || !productHasListedObjects();
  }

  searchInput?.addEventListener("input", onSearchInput);
  $("#search-form")?.addEventListener("submit", (event) => {
    event.preventDefault();
    window.clearTimeout(searchTimer);
    const query = searchInput?.value.trim() || "";
    if (!query) {
      searchSeq += 1;
      persistListSearchState();
      showFolderView();
      applyMetricVisibility();
      applyMetricSelection();
      syncToolbar();
      return;
    }
    persistListSearchState();
    void searchAllFolders(query);
  });
  syncSearchFormVisibility();

  async function restoreListSearchState() {
    if (!searchInput || !objectTable || !isListPage) return;
    let raw = null;
    try {
      raw = sessionStorage.getItem(LIST_SEARCH_KEY);
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
    const productId = currentProductId();
    const query = String(saved?.q || "").trim();
    if (!query || !productId || saved.productId !== productId) return;
    searchInput.value = query;
    await searchAllFolders(query);
    const wanted = new Set(
      Array.isArray(saved.ids) ? saved.ids.map(String).filter(Boolean) : []
    );
    if (wanted.size) {
      rows().forEach((row) => markRowSelected(row, wanted.has(String(row.dataset.uuid || ""))));
      syncToolbar();
    }
    // Keep storage so Details → Back (or History again) can re-apply the same search.
  }

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

  function productHasVaultFilesForExport() {
    const filesMetric = metricButtons().find((btn) => metricKey(btn) === "files");
    const raw = (filesMetric?.querySelector("strong")?.textContent || "")
      .replace(/,/g, "")
      .trim();
    const fromMetric = Number.parseInt(raw, 10);
    if (Number.isFinite(fromMetric)) return fromMetric > 0;
    // Fallback when the Files metric is missing (detail-only / soft-nav edge).
    return [...document.querySelectorAll("tr.object-row")].some((row) => {
      const uuid = (row.dataset.uuid || "").trim();
      return Boolean(uuid) && row.dataset.localCache !== "1";
    });
  }

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
      return openSpecFromRow(selected[0], selected[0].querySelector(".object-open"));
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
      document
        .querySelectorAll(
          "#modified-table .queue-row.is-pending[data-uuid], #changes-table .queue-row.is-pending[data-uuid]"
        )
        .forEach((row) => {
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
    const addOnly = selectionIsAddOnly(selected);
    // Modified / owned check-in work only — New files use Add ▾ → Add selected…
    const canCheckin = roleCanCheckin && selectionCanCheckin(selected) && !addOnly;
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
    const productId =
      checkinBtn?.dataset.product ||
      checkinMenuBtn?.dataset.product ||
      openWorkspaceBtn?.dataset.product ||
      addForm?.dataset.product ||
      currentProductId() ||
      "";
    // Add menu is omitted from the DOM when the product is locked (Jinja product_ui).
    const canAdd = Boolean(productId) && Boolean($("#add-menu"));
    // Add selected… only for New files rows (vault or local) — never Modified / Files.
    const canAddSelected = canAdd && Boolean($("#add-selected-btn")) && addOnly;
    setToolbarActionVisible(addMenuBtn, canAdd);
    for (const id of ["create-folder-btn", "add-files-btn", "add-folder-btn", "add-folders-btn", "add-compressed-btn"]) {
      setToolbarActionVisible($("#" + id), canAdd);
    }
    // Stay visible in Add ▾ but greyed until a New files selection (hover title explains).
    const addSelectedBtn = $("#add-selected-btn");
    if (addSelectedBtn) {
      addSelectedBtn.hidden = false;
      addSelectedBtn.disabled = !canAddSelected;
      addSelectedBtn.title = canAddSelected
        ? "Add selected new files to the product (uploads local workspace files first)."
        : "Select New files (vault or local workspace), then add them to the product.";
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
    // Check In ▾ keeps "Check in selected…" for Modified work. New-files-only
    // selection uses Add ▾ → Add selected… (objects.add), not a Check In relabel.
    if (checkinBtn) {
      checkinBtn.textContent = "Check in selected…";
      checkinBtn.title = addOnly
        ? "Use Add ▾ → Add selected… for New files."
        : checkinSelectedHoverTitle(selected, canCheckin, false);
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
    // Copy/Export menus omitted from the DOM when product_ui hides them (Locked / not mutable).
    setToolbarActionVisible(
      workspaceBtn,
      Boolean(workspaceBtn) &&
        document.body?.dataset?.canCopyToVault === "1" &&
        selected.some((row) => row.dataset.inWorkspace !== "1")
    );
    const canExportProduct =
      Boolean(exportProductBtn) && document.body?.dataset?.canExportProduct === "1";
    const canExportObjects =
      Boolean(exportSelectedBtn) && document.body?.dataset?.canExportObjects === "1";
    // Visual selection only — do not treat checkout/open fallback ids as an export selection.
    const exportHasSelection =
      selectedRows().flatMap(rowObjectIds).length > 0 || selectedFolderPaths().length > 0;
    const exportHasVaultFiles = productHasVaultFilesForExport();
    const canExportWhole = Boolean(productId) && canExportProduct && exportHasVaultFiles;
    const canExportSelection =
      Boolean(productId) && canExportObjects && exportHasSelection;
    // Hide Export ▾ entirely when every menu item would be greyed.
    const canShowExportMenu = canExportWhole || canExportSelection;
    setToolbarActionVisible(exportMenuBtn, canShowExportMenu);
    if (!canShowExportMenu) closeExportMenu();
    // Export product stays visible but greyed when the product has no vault files
    // (only while Export selected… is still usable so the menu stays open).
    if (exportProductBtn) {
      exportProductBtn.hidden = false;
      exportProductBtn.disabled = !canExportWhole;
      exportProductBtn.title = canExportWhole
        ? "Download the entire product vault tip as a zip."
        : !canExportProduct
          ? "Your role cannot export a whole product (products.export)."
          : "Nothing to export — this product has no vault files yet.";
    }
    // Export selected stays visible but greyed until files/folders are selected
    // (only while Export product… is still usable so the menu stays open).
    if (exportSelectedBtn) {
      exportSelectedBtn.hidden = false;
      exportSelectedBtn.disabled = !canExportSelection;
      exportSelectedBtn.title = exportHasSelection
        ? "Download the selected vault files or folders as a zip."
        : "Download the selected vault files or folders as a zip. Greyed out until something is selected.";
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
    const modifiedTab = document.querySelector('.tab[data-tab="modified"]');
    if (modifiedTab) {
      const n = Number(pendingSaves || 0);
      modifiedTab.textContent = n ? `Modified · ${n}` : "Modified";
    }
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (tab) {
      const n = Number(newFiles || 0);
      tab.textContent = n ? `New files · ${n}` : "New files";
    }
    syncToolbar();
  }

  function setCheckedOutTabCount(count) {
    const tab = document.querySelector('.tab[data-tab="checked-out"]');
    if (!tab) return;
    const n = Number(count) || 0;
    tab.textContent = n ? `Checked out · ${n}` : "Checked out";
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
    const relativePath = openLink?.dataset?.relativePath || row.dataset.relativePath || "";
    const localCache = row.dataset.localCache === "1";
    // Newer local save / New file (local): open the agent-workspace tip first
    // (even when a product uuid exists — vault prepare is the wrong source).
    if (localCache && relativePath) {
      return {
        relativePath,
        productId: currentProductId(),
        localCache: true,
        objectId: uuid || undefined,
      };
    }
    if (uuid) return { objectId: uuid };
    if (relativePath) {
      return {
        relativePath,
        productId: currentProductId(),
        localCache: false,
      };
    }
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
    // Soft-nav Details — hard location.href SSR-paints Session offline and drops Creo.JS.
    leavePage(href);
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
  document.querySelector("#modified-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#modified-table")?.addEventListener("dblclick", onFileTableDblclick);
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
    // New files only + objects.add (Add menu present). Never for Modified / Files.
    const canAddSelected = canOfferAdd() && addOnly;
    // Check in selected for Modified/checkout work — not New-files-only (Add selected).
    const canCheckin =
      Boolean(checkinBtn) &&
      roleCanCheckin &&
      selectionCanCheckin(selected) &&
      !addOnly;
    // Modified "Newer local save" / New file (local) are already in the agent workspace.
    const alreadyLocal =
      selected.length > 0 && selected.every((row) => row.dataset.localCache === "1");
    // Download/export: role caps ∩ product_ui (data-allows-content / Export DOM).
    const canDownload =
      canViewObjects() &&
      productAllowsContent() &&
      selectedDownloadIds().length > 0 &&
      !alreadyLocal;
    const canExportObjects = document.body?.dataset?.canExportObjects === "1";
    const exportHasSelection =
      selected.flatMap(rowObjectIds).length > 0 || selectedFolderPaths().length > 0;
    const canExport =
      Boolean(exportSelectedBtn) &&
      canExportObjects &&
      exportHasSelection;
    // Same rule as Remove ▾ → Remove from Workspace (local New files only).
    const canDiscardLocal =
      Boolean(discardLocalBtn) &&
      selected.some((row) => isNewFileQueueRow(row) && row.dataset.localCache === "1");
    return {
      canOpen,
      canDetails,
      canCheckout,
      canUndo,
      canAddSelected,
      canCheckin,
      canDownload,
      canExport,
      canDiscardLocal,
    };
  }

  function ensureFilesContextMenu() {
    let menu = document.getElementById("files-context-menu");
    const items = [
      {
        id: "files-context-open",
        action: "open",
        label: "Open selected",
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
        id: "files-context-add-selected",
        action: "add-selected",
        label: "Add selected…",
        title: "Add selected new files to the product (uploads local workspace files first).",
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
      {
        id: "files-context-discard-local",
        action: "discard-local",
        label: "Remove from Workspace…",
        title:
          "Move selected files from the local workspace on this PC to the Recycle Bin. Does not affect the vault or product list.",
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
      && !caps.canAddSelected
      && !caps.canCheckin
      && !caps.canDownload
      && !caps.canExport
      && !caps.canDiscardLocal
    ) {
      return false;
    }
    closeAllToolbarMenus();
    const menu = ensureFilesContextMenu();
    const openItem = menu.querySelector("#files-context-open");
    const detailsItem = menu.querySelector("#files-context-details");
    const checkoutItem = menu.querySelector("#files-context-checkout");
    const undoItem = menu.querySelector("#files-context-undo");
    const addSelectedItem = menu.querySelector("#files-context-add-selected");
    const checkinItem = menu.querySelector("#files-context-checkin");
    const downloadItem = menu.querySelector("#files-context-download");
    const exportItem = menu.querySelector("#files-context-export");
    const discardLocalItem = menu.querySelector("#files-context-discard-local");
    if (openItem) openItem.hidden = !caps.canOpen;
    if (detailsItem) detailsItem.hidden = !caps.canDetails;
    if (checkoutItem) checkoutItem.hidden = !caps.canCheckout;
    if (undoItem) undoItem.hidden = !caps.canUndo;
    if (addSelectedItem) addSelectedItem.hidden = !caps.canAddSelected;
    if (checkinItem) {
      checkinItem.hidden = !caps.canCheckin;
      checkinItem.textContent = "Check in selected…";
      checkinItem.title = "Check in selected files.";
    }
    if (downloadItem) downloadItem.hidden = !caps.canDownload;
    if (exportItem) exportItem.hidden = !caps.canExport;
    if (discardLocalItem) discardLocalItem.hidden = !caps.canDiscardLocal;
    positionFilesContextMenu(menu, clientX, clientY);
    return true;
  }

  async function downloadSelectedToWorkspace() {
    closeFilesContextMenu();
    if (!canViewObjects() || !productAllowsContent()) return;
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
            setBusyMessage(`Checking local workspace for ${total} files…`);
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
    if (action === "add-selected") {
      $("#add-selected-btn")?.click();
      return;
    }
    if (action === "checkin") {
      checkinBtn?.click();
      return;
    }
    if (action === "export") {
      exportSelectedBtn?.click();
      return;
    }
    if (action === "discard-local") {
      discardLocalBtn?.click();
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
  document.querySelector("#modified-table")?.addEventListener("contextmenu", onFileTableContextMenu);
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
    // Top level assemblies is exclusive — no other pills stay on with it.
    if (key === "top_level_assemblies" && next !== "off") {
      metricButtons().forEach((item) => {
        if (item !== btn) setMetricMode(item, "off");
      });
    } else if (key !== "top_level_assemblies" && next !== "off") {
      clearMetricFilters(new Set(["top_level_assemblies"]));
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
    // Prefer getAttribute — Creo CEF dataset on the status pill is unreliable and
    // used to read as "" → association, so Modified/New local open went via Windows.
    const el = $("#creo-status");
    if (!el) return "";
    if (typeof el.getAttribute === "function") {
      return String(el.getAttribute("data-creo-open-mode") || "").trim().toLowerCase();
    }
    return String(el.dataset?.creoOpenMode || "").trim().toLowerCase();
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

  function looksLikeCreoEmbeddedBrowser() {
    // Strong signals we are inside Creo's CEF — never plain Chrome/Edge.
    if (creoExternalBridge()) return true;
    try {
      if (typeof pfcGetCurrentSession === "function") return true;
    } catch {
      /* ignore */
    }
    const ua = String(navigator.userAgent || "");
    return /creo|ptc|parametric/i.test(ua);
  }

  function showCreoConnectingOverlay() {
    const el = $("#creo-connecting-overlay");
    if (!el) return;
    el.hidden = false;
    document.body.classList.add("creo-connecting");
  }

  function hideCreoConnectingOverlay() {
    const el = $("#creo-connecting-overlay");
    if (el) el.hidden = true;
    document.body.classList.remove("creo-connecting");
    if (window.__creopdmCreoConnectingPoll) {
      window.clearInterval(window.__creopdmCreoConnectingPoll);
      window.__creopdmCreoConnectingPoll = 0;
    }
  }

  function isAuthShellPage() {
    // Logout hard-loads /login — never block username/password with Connecting…
    const path = String(window.location.pathname || "");
    if (
      path === "/login"
      || path === "/logout"
      || path === "/setup"
      || path === "/forgot-password"
      || path === "/reset-password"
    ) {
      return true;
    }
    return Boolean(document.getElementById("login-form"));
  }

  function startCreoConnectingOverlayGuard() {
    // Only in Creo's embedded browser while Creo.JS is still linking.
    // Soft boots keep the live bridge — never block after Soft-nav.
    // Auth pages (post-Logout sign-in): never show the overlay — Creo.JS can
    // re-link in the background; blocking ~15s made Logout feel stuck/offline.
    if (soft || hostedCreoJS() || isAuthShellPage()) {
      hideCreoConnectingOverlay();
      return;
    }
    if (!looksLikeCreoEmbeddedBrowser()) {
      hideCreoConnectingOverlay();
      return;
    }
    showCreoConnectingOverlay();
    let tries = 0;
    if (window.__creopdmCreoConnectingPoll) {
      window.clearInterval(window.__creopdmCreoConnectingPoll);
    }
    // 100ms poll — clear overlay as soon as the bridge is live (~15s cap).
    window.__creopdmCreoConnectingPoll = trackedInterval(() => {
      tries += 1;
      if (hostedCreoJS()) {
        hideCreoConnectingOverlay();
        syncCreoSessionControlsFromBridge();
        return;
      }
      // ~15s — leave Session offline; do not trap clicks forever.
      if (tries >= 150) hideCreoConnectingOverlay();
    }, 100);
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

  function metadataCollectLogicalName(filename) {
    return String(filename || "")
      .trim()
      .replace(/\.(\d+)$/i, "")
      .toLowerCase();
  }

  function metadataCollectRank(filename) {
    // Parts first, assemblies next, drawings last — Creo Retrieve of a .drw
    // needs referenced .prt/.asm already in the workspace folder (otherwise
    // "Model X.PRT is not in this directory").
    const logical = metadataCollectLogicalName(filename);
    if (logical.endsWith(".drw") || logical.endsWith(".frm")) return 2;
    if (logical.endsWith(".asm")) return 1;
    return 0;
  }

  function metadataNeedsOpenDependencies(filename) {
    const logical = metadataCollectLogicalName(filename);
    return logical.endsWith(".drw") || logical.endsWith(".frm");
  }

  function sortMetadataCollectTargets(targets) {
    const list = Array.isArray(targets) ? targets.slice() : [];
    list.sort((a, b) => {
      const rankDiff = metadataCollectRank(a?.filename) - metadataCollectRank(b?.filename);
      if (rankDiff !== 0) return rankDiff;
      return String(a?.filename || "").localeCompare(String(b?.filename || ""), undefined, {
        sensitivity: "base",
      });
    });
    return list;
  }

  function looksLikeLocalWindowsPath(path) {
    const text = String(path || "").trim();
    return /^[a-zA-Z]:[\\/]/.test(text) || text.startsWith("\\\\");
  }

  async function prepareLocalPathForMetadata(objectId, filename) {
    if (!objectId) return null;
    try {
      // Tip-only for parts/assemblies — Collect must not walk/materialize the
      // full Where Used tree for every file (that made 900+ Collects feel stuck).
      // Drawings still need referenced models beside them in the workspace.
      const includeDependencies = metadataNeedsOpenDependencies(filename);
      const response = await fetch("/api/creo/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          object_id: objectId,
          launch: false,
          include_dependencies: includeDependencies,
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
      const openSpec = await materializeViaAgent(
        {
          ...prepared,
          replace_newer: Boolean(prepared.replace_newer),
        },
        // Keep Collect's "N of M" busy text — do not flash workspace-up-to-date.
        { quietBusy: true }
      );
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

  async function gatherCreoMetadataForFilename(filename, filePath, options) {
    if (!canGatherCreoMetadata() || !filename) return null;
    const opts = options && typeof options === "object" ? options : {};
    const deferErase = Boolean(opts.deferErase);
    // Default on — Boolean(undefined) was false and wiped Collect/Open names.
    const featureNames = opts.featureNames !== false;
    const preferDisk = opts.preferDisk === true;
    const pendingErase = Array.isArray(opts.pendingErase) ? opts.pendingErase : null;
    try {
      await whenCreoJSReady();
      if (typeof window.CreoJS.gatherModelMetadata !== "function") return null;
      const snapshot = await window.CreoJS.gatherModelMetadata(filename, filePath || "", {
        featureNames,
        preferDisk: preferDisk && !!filePath,
      });
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
      // Collect batches erases (deferErase) so 935 models are not 935 Erase turns.
      if (eraseKeys.length) {
        if (deferErase && pendingErase) {
          eraseKeys.forEach((key) => pendingErase.push(key));
        } else if (typeof window.CreoJS.eraseSessionModelsByNames === "function") {
          try {
            await window.CreoJS.eraseSessionModelsByNames(eraseKeys, { allowUndisplayed: false });
          } catch {
            /* best-effort session cleanup */
          }
        }
      }
      return snapshot;
    } catch {
      return null;
    }
  }

  function aiSnapshotBodyFromGather(gatherSnapshot) {
    const ai = gatherSnapshot && typeof gatherSnapshot === "object"
      ? gatherSnapshot.ai_snapshot
      : null;
    if (!ai || typeof ai !== "object") return null;
    const capture = ai.capture && typeof ai.capture === "object" ? ai.capture : {};
    // Prefer snapshot.bom / structure (enriched); fall back to gather metadata.
    const bom = Array.isArray(ai.bom)
      ? ai.bom
      : (Array.isArray(gatherSnapshot?.bom) ? gatherSnapshot.bom : null);
    const structure = Array.isArray(ai.structure)
      ? ai.structure
      : (Array.isArray(gatherSnapshot?.structure) ? gatherSnapshot.structure : null);
    return {
      schema_version: Number(ai.schema_version) || 1,
      identity: ai.identity || null,
      features: Array.isArray(ai.features) ? ai.features : [],
      dimensions: Array.isArray(ai.dimensions) ? ai.dimensions : [],
      parameters: Array.isArray(ai.parameters) ? ai.parameters : [],
      materials: ai.materials && typeof ai.materials === "object" ? ai.materials : null,
      units: ai.units && typeof ai.units === "object" ? ai.units : null,
      family_table: ai.family_table && typeof ai.family_table === "object" ? ai.family_table : null,
      bom,
      structure,
      capture,
    };
  }

  function objectAiSnapshotTipIsStale(objectUuid) {
    /**
     * Modified local workspace must not overwrite the tip AI snapshot.
     * Otherwise delete-view → Collect → Check In stores the same gather on
     * A.1 and A.2 and Ask AI reports "no changes".
     */
    const id = String(objectUuid || "").trim();
    if (!id) return false;
    let row = null;
    try {
      row = document.querySelector(`tr.object-row[data-uuid="${CSS.escape(id)}"]`);
    } catch {
      row = document.querySelector(`tr.object-row[data-uuid="${id}"]`);
    }
    if (row) {
      if (row.getAttribute("data-modified-locally") === "1") return true;
      const st = String(
        row.querySelector(".state")?.getAttribute("data-state") || ""
      ).toUpperCase();
      if (st === "MODIFIED") return true;
    }
    const detail = document.querySelector(
      `[data-object-id="${id}"], [data-uuid="${id}"]`
    );
    if (detail?.getAttribute?.("data-modified-locally") === "1") return true;
    return false;
  }

  async function postAiSnapshotFromGather(objectUuid, versionId, gatherSnapshot, options) {
    // Soft-fail — AI snapshot must not block Creo metadata save.
    const opts = options && typeof options === "object" ? options : {};
    const snapshot = aiSnapshotBodyFromGather(gatherSnapshot);
    if (!objectUuid || !snapshot) return false;
    // Check In / forced tip match may pass force:true. Collect on Modified skips.
    if (!opts.force && objectAiSnapshotTipIsStale(objectUuid)) {
      return false;
    }
    // Never store PART solid JSON on a .drw object (session stem matched wedge.prt).
    try {
      const objectName = String(opts.objectFilename || "").toLowerCase();
      const idName = String(snapshot.identity?.filename || "").toLowerCase();
      const idType = String(snapshot.identity?.model_type || "").toUpperCase();
      if (
        objectName.endsWith(".drw")
        && (idType === "PART" || idType === "ASSEMBLY"
          || idName.endsWith(".prt") || idName.endsWith(".asm"))
      ) {
        return false;
      }
    } catch {
      /* continue — server also rejects */
    }
    const capture = snapshot.capture && typeof snapshot.capture === "object" ? snapshot.capture : {};
    const body = {
      version_id: versionId || null,
      schema_version: Number(snapshot.schema_version) || 1,
      capture_status: String(capture.status || "ok"),
      capture_errors: Array.isArray(capture.errors) ? capture.errors.map(String) : [],
      snapshot,
    };
    try {
      const response = await fetch(
        `/api/objects/${encodeURIComponent(objectUuid)}/ai-snapshot`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        }
      );
      if (response.ok) {
        clearAiSnapshotClientCache();
      }
      return response.ok;
    } catch {
      return false;
    }
  }

  async function pushCreoMetadataForItems(items, options) {
    const opts = options && typeof options === "object" ? options : {};
    const sessionOnly = Boolean(opts.sessionOnly);
    const sessionWaitRounds = Math.max(0, Number(opts.sessionWaitRounds) || 0);
    const sessionWaitMs = Math.max(50, Number(opts.sessionWaitMs) || 500);
    const featureNames = opts.featureNames !== false;
    const showProgress = opts.progress !== false;
    const targets = sortMetadataCollectTargets(
      (items || [])
        .map((item) => ({
          uuid: String(item?.uuid || item?.object_id || "").trim(),
          filename: String(item?.filename || "").trim(),
          path: String(item?.path || "").trim(),
          versionId: String(item?.version_id || item?.current_version?.uuid || "").trim(),
        }))
        .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename))
    );
    let saved = 0;
    if (!targets.length || !canGatherCreoMetadata()) return saved;
    for (let i = 0; i < targets.length; i += 1) {
      const target = targets[i];
      if (showProgress) {
        publishBusyMessage(metadataBusyText(i + 1, targets.length, target.filename));
      }
      // Session first (Open / Check In often already have the model) — avoids
      // re-Retrieve + erase of a model the user just opened.
      let snapshot = null;
      for (let round = 0; round <= sessionWaitRounds; round += 1) {
        snapshot = await gatherCreoMetadataForFilename(target.filename, "", {
          featureNames,
        });
        if (snapshot && snapshot.__error) snapshot = null;
        if (snapshot) break;
        if (round < sessionWaitRounds) {
          await new Promise((resolve) => window.setTimeout(resolve, sessionWaitMs));
        }
      }
      // After File > Open trail, do not Retrieve from disk — that re-floods the
      // Creo message log on large assemblies the trail already opened quietly.
      if (!snapshot && !sessionOnly) {
        let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
        if (!filePath) {
          filePath = (await prepareLocalPathForMetadata(target.uuid, target.filename)) || "";
        }
        if (!filePath) continue;
        snapshot = await gatherCreoMetadataForFilename(target.filename, filePath, {
          featureNames,
        });
        if (snapshot && snapshot.__error) snapshot = null;
      }
      if (!snapshot) continue;
      const identityName = String(
        snapshot.identity?.file_name || snapshot.identity?.full_name || ""
      ).trim();
      if (!identityName) continue;
      const body = {
        version_id: target.versionId || null,
        identity: snapshot.identity || null,
        parameters: Array.isArray(snapshot.parameters) ? snapshot.parameters : [],
        materials: snapshot.materials || null,
        dependencies: Array.isArray(snapshot.dependencies) ? snapshot.dependencies : [],
        bom: snapshot.bom || null,
        units: snapshot.units || null,
        // Mass unsupported without a displayed solid — omit so mass_json is preserved.
        family_table: snapshot.family_table || null,
        features: Array.isArray(snapshot.features) && snapshot.features.length
          ? snapshot.features
          : null,
        structure: Array.isArray(snapshot.structure) ? snapshot.structure : null,
      };
      try {
        const response = await fetch(
          `/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          }
        );
        if (response.ok) {
          saved += 1;
          // Check In / Open tip capture — force so Modified row paint cannot skip.
          await postAiSnapshotFromGather(target.uuid, target.versionId || null, snapshot, {
            force: true,
            objectFilename: target.filename,
          });
        }
      } catch {
        /* soft-fail — metadata is best-effort */
      }
    }
    return saved;
  }

  function metadataItemsFromOpenResult(result) {
    // Only after a Creo.JS session open (not Windows association / browser download).
    if (!result || !result.creo_object) return [];
    const uuid = String(result.object_id || "").trim();
    const filename = String(result.filename || "").trim();
    if (!uuid || !filename || !isCreoMetadataCandidate(filename)) return [];
    return [
      {
        uuid,
        filename,
        // Prefer session gather; local path only as fallback inside push.
        path: looksLikeLocalWindowsPath(result.path) ? result.path : "",
        version_id: String(result.version_id || "").trim(),
      },
    ];
  }

  async function captureCreoMetadataAfterOpen(result) {
    if (!canGatherCreoMetadata()) return 0;
    const items = metadataItemsFromOpenResult(result);
    if (!items.length) return 0;
    let saved = 0;
    await withBusy("Capturing Creo metadata…", async () => {
      // Embedded Open prefers File > Open trail (returns before retrieve finishes).
      // Wait for the model in session; never disk-Retrieve after Open.
      saved = await pushCreoMetadataForItems(items, {
        sessionOnly: true,
        sessionWaitRounds: 60,
        sessionWaitMs: 500,
        featureNames: true,
      });
    });
    return saved;
  }

  function metadataTargetsFromResult(result) {
    if (!result) return [];
    if (Array.isArray(result.ok)) {
      return result.ok
        .filter((item) => {
          if (!item || !item.uuid || !item.filename) return false;
          const status = String(item.status || "").trim().toLowerCase();
          // Add / zip → "added"; Check In → "checked_in". Skip undo-only rows.
          return !status || status === "checked_in" || status === "added";
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
                include_dependencies: false,
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
    // Set Working Directory + Collect metadata: only inside Creo with a live session.
    // Rebuild Where Used is server-side vault indexing — not creo-session-only.
    // Hidden outside Creo / when disconnected; Set WD always hidden on File Details.
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
    hideCreoConnectingOverlay();
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
    // Keep agent online flag fresh so Open workspace can hide when offline.
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
    // Hide the gear when every menu item is hidden (e.g. only Collect left and
    // Session offline). Rebuild Where Used stays visible without Creo.JS.
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

  function pollCreoBridgeUntilLive(onLive) {
    // Creo.JS often appears after first paint (Details / soft-nav / hard refresh).
    if (hostedCreoJS()) {
      onLive();
      return;
    }
    let bridgeTries = 0;
    const bridgePoll = trackedInterval(() => {
      bridgeTries += 1;
      // ~10s at 100ms — promote Connected as soon as the bridge is readable.
      if (hostedCreoJS() || bridgeTries >= 100) {
        window.clearInterval(bridgePoll);
        onLive();
      }
    }, 100);
  }

  // Soft folder/product switches keep the live Creo.JS bridge and header status
  // pill (both live outside main.shell). Never re-probe agent or reconnect.
  startCreoConnectingOverlayGuard();
  if (soft) {
    syncCreoSessionControlsFromBridge();
    // Soft boot into Details/Admin can land before the bridge is readable again.
    void creoJSReady.then(() => {
      pollCreoBridgeUntilLive(() => syncCreoSessionControlsFromBridge());
    });
  } else if (!isListPage) {
    // Admin / Settings / Details / login: no Open workspace toolbar — skip agent /health.
    // Still wait for Creo.JS so Details does not stay Session offline after hard refresh.
    syncCreoSessionControlsFromBridge();
    void creoJSReady.then(() => {
      pollCreoBridgeUntilLive(() => syncCreoSessionControlsFromBridge());
    });
  } else {
    // Files list: promote Connected as soon as Creo.JS is live — do not wait on
    // creopdm-agent /health (that only affects Open workspace / agent online).
    syncCreoSessionControlsFromBridge();
    void creoJSReady.then(() => {
      pollCreoBridgeUntilLive(() => syncCreoSessionControlsFromBridge());
      void (async () => {
        // CREOPDM_STATUS_POLL_V2: at most one /health on load; repeat only if agent says > 0.
        // Files list only — Open workspace visibility depends on agent online.
        const agent = await probeCreoAgent();
        await refreshCreoStatusPill(agent);
        syncToolbar();
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
      throw new Error("Local CreoPDM agent could not provide a workspace folder.");
    }
    const body = await response.json();
    if (!body || !body.path) {
      throw new Error("Local CreoPDM agent returned no workspace path.");
    }
    return String(body.path);
  }

  async function setCreoWorkingDirectory(options) {
    const quiet = Boolean(options && options.quiet);
    try {
      await creoJSReady;
      if (!hostedCreoJS()) {
        showError($("#toolbar-error"), "Open this page in Creo's built-in browser to set the working directory.");
        return false;
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
        return false;
      }
      const directory = await agentWorkdir(currentProductId(), currentVaultFolder());
      await whenCreoJSReady();
      const result = await window.CreoJS.setWorkingDirectory(directory);
      const text = result == null ? "" : String(result);
      if (text.indexOf("CREOPDM_ERROR:") === 0) {
        showError($("#toolbar-error"), text.slice("CREOPDM_ERROR:".length));
        return false;
      }
      if (!quiet) showOk("Creo working directory set to the local workspace.");
      return true;
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
      if (!message || message === "[object Object]" || message === "{}") {
        showError(
          $("#toolbar-error"),
          "Creo could not change the working directory. Check that creopdm-agent is running."
        );
        return false;
      }
      showError($("#toolbar-error"), message || "Creo could not change directory.");
      return false;
    }
  }
  setCreoDirBtn?.addEventListener("click", () => {
    void setCreoWorkingDirectory();
  });

  function openRequestBody(target, launch, includeDependencies) {
    const spec = typeof target === "string" ? { objectId: target } : target || {};
    const body = { launch: Boolean(launch) };
    if (includeDependencies !== undefined) body.include_dependencies = Boolean(includeDependencies);
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
    // permission from the toolbar. The Checkout fly-up can exist for Force Undo
    // alone; that used to make Checkout ▾ open empty for Viewer / no-checkout roles.
    const raw = document.body?.getAttribute("data-can-checkout");
    if (raw != null && String(raw).trim() !== "") return false;
    // Attribute missing (Creo CEF / soft-nav wipe) — recover only from real
    // checkout/undo items, never from the Checkout fly-up shell or Force Undo alone.
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
    const dependenciesWrap = $("#open-checkout-dependencies-wrap");
    const dependenciesNote = $("#open-checkout-dependencies-note");
    const wdWrap = $("#open-checkout-wd-wrap");
    const wdBox = $("#open-checkout-set-wd");
    const openRadio = $("#open-action-open");
    const cancelBtn = $("#open-checkout-cancel");
    const err = $("#open-checkout-error");
    // Object availability AND signed-in user objects.checkout capability.
    const allowCheckout = Boolean(canCheckout) && userCanCheckout();
    // Working directory only applies inside Creo's embedded browser.
    // Off by default — File > Open trail is enough; Set WD locks the workspace
    // folder (WinError 32 on Delete product / remove-folder). Opt-in via checkbox.
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
    if (dependenciesWrap) dependenciesWrap.hidden = false;
    if (dependenciesNote) dependenciesNote.hidden = false;
    if (wdWrap) wdWrap.hidden = !showWd;
    openRadio.checked = true;
    if (wdBox) {
      wdBox.disabled = !showWd;
      wdBox.checked = false;
    }
    const fileRadio = $("#open-action-checkout-file");
    const dependenciesRadio = $("#open-action-checkout-dependencies");
    if (fileRadio) fileRadio.disabled = false;
    if (dependenciesRadio) dependenciesRadio.disabled = false;

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

  async function checkoutBeforeOpen(target, withDependencies) {
    const objectId = openTargetObjectId(target);
    if (!objectId) return [];
    if (!withDependencies) {
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
      "Finding dependencies…"
    );
    if (!prepared) return null;
    const ids = [
      objectId,
      ...((prepared.dependencies || []).map((item) => item.object_id).filter(Boolean)),
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
    // with no modal. Do not Set WD on Open by default (locks workspace folder).
    if (objectId && kind === "mine") {
      return openPdmObject(target, { setWorkingDirectory: false });
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
    if (action === "checkout-file" || action === "checkout-dependencies") {
      const checkedOutIds = await checkoutBeforeOpen(
        target,
        action === "checkout-dependencies"
      );
      if (!checkedOutIds) return null;
      // Paint before openModel — Creo collapses the embedded browser on Display.
      applyCheckedOutOnRows(checkedOutIds);
    }
    // WD is applied inside openPdmObjectWork (before openModel) so skip-chooser
    // and chooser paths share one place; quiet during the Opening… overlay.
    return openPdmObject(target, { setWorkingDirectory: setWd });
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

  async function listAgentCacheFiles(productId, vaultFolderOverride) {
    /**
     * null = agent offline /files failed (do not treat as empty workspace).
     * [] = agent answered and the workspace folder has no listed tips.
     */
    if (!productId) return null;
    const agent = await probeCreoAgent();
    if (!agent) return null;
    const vaultFolder =
      String(vaultFolderOverride || "").trim() || currentVaultFolder();
    const params = new URLSearchParams({ product_id: productId });
    if (vaultFolder) params.set("vault_folder", vaultFolder);
    try {
      const response = await fetch(
        `${agentBase()}/files?${params}`,
        { method: "GET", headers: agentAuthHeaders() }
      );
      if (!response.ok) return null;
      const body = await response.json().catch(() => null);
      if (!body || !Array.isArray(body.files)) return null;
      return body.files;
    } catch {
      return null;
    }
  }

  async function listAgentCacheFilesPreferringVault(productId, vaultFolderOverride) {
    /** Try panel vault first, then page vault / product id — Details has no metric-filters. */
    const candidates = [
      String(vaultFolderOverride || "").trim(),
      currentVaultFolder(),
      String(productId || "").trim(),
    ].filter(Boolean);
    const seen = new Set();
    let lastEmpty = null;
    for (const vault of candidates) {
      const key = vault.toLowerCase();
      if (seen.has(key)) continue;
      seen.add(key);
      const files = await listAgentCacheFiles(productId, vault);
      if (files == null) continue;
      if (files.length) return { files, vaultFolder: vault, listed: true };
      lastEmpty = { files, vaultFolder: vault, listed: true };
    }
    if (lastEmpty) return lastEmpty;
    return { files: [], vaultFolder: String(vaultFolderOverride || "").trim(), listed: false };
  }

  /** SHA-256 selected local cache paths (for same-size content-replace detection). */
  async function hashAgentCachePaths(productId, relativePaths, vaultFolderOverride) {
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
    const vaultFolder =
      String(vaultFolderOverride || "").trim() || currentVaultFolder();
    const response = await fetch(`${agentBase()}/hash-paths`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
        vault_folder: vaultFolder,
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

  /**
   * Trash workspace tips for Remove-from-Product (incl. Hidden Creo ``.N`` siblings).
   * Must be awaited before soft-nav/reload — fire-and-forget was aborted mid-delete
   * and left Hidden numbered tips behind (Clear workspace waited, so it looked fine).
   */
  async function deleteLocalWorkspacePathsForRemove(productId, relativePaths) {
    const paths = [
      ...new Set(
        (relativePaths || [])
          .map((item) => String(item || "").replace(/\\/g, "/").replace(/^\/+/, ""))
          .filter(Boolean)
      ),
    ];
    if (!productId || !paths.length) return { ok: [], failed: [], skipped: true };
    const agent = await probeCreoAgent();
    if (!agent) {
      throw new Error(
        "creopdm-agent is not running — local workspace on this PC was not deleted."
      );
    }
    const chunkSize = 150;
    const combined = { ok: [], failed: [] };
    for (let i = 0; i < paths.length; i += chunkSize) {
      const slice = paths.slice(i, i + chunkSize);
      const done = Math.min(i + slice.length, paths.length);
      if (paths.length > chunkSize) {
        publishBusyMessage(`Cleaning local workspace… ${done} of ${paths.length}`);
      }
      const body = await deleteLocalWorkspacePaths(productId, slice);
      if (!body) {
        throw new Error(
          "creopdm-agent is not running — local workspace on this PC was not deleted."
        );
      }
      combined.ok.push(...(body.ok || []));
      combined.failed.push(...(body.failed || []));
    }
    return combined;
  }

  /** @deprecated Prefer deleteLocalWorkspacePathsForRemove (awaited). */
  function deleteLocalWorkspacePathsBackground(productId, relativePaths) {
    deleteLocalWorkspacePathsForRemove(productId, relativePaths).catch(() => {});
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
  let lastModifiedPending = null;
  let changesReloadBusy = false;
  let modifiedReloadBusy = false;
  // Warm row lists when the tab badge changes so opening Modified / New files
  // does not flash “Looking for…” after the count already moved.
  let checkinQueueCache = {
    productId: "",
    at: 0,
    saves: [],
    created: [],
    newerLocal: [],
  };
  let checkinQueuePrefetch = null;

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
    // Collapse Creo siblings to the highest .N (test-part.prt.2 over .prt.1).
    // First-wins used to leave a stale tip after Save created a newer version.
    const knownExact = new Set(known.exact || []);
    const knownLogical = new Set(known.logical || []);
    const knownBasenames = new Set(known.basenames || []);
    const bestByFamily = new Map();
    (cacheFiles || []).forEach((item) => {
      const rel = String(item.relative_path || "").replace(/\\/g, "/");
      if (!rel) return;
      const exactKey = rel.toLowerCase();
      const logicalKey = logicalRelativePath(rel).toLowerCase();
      const base = logicalUploadName(PathBasename(rel)).toLowerCase();
      const atRoot = !rel.includes("/");
      if (knownExact.has(exactKey) || knownLogical.has(logicalKey)) return;
      if (atRoot && knownBasenames.has(base)) return;
      const filename = item.filename || PathBasename(rel);
      const saveNumber = creoSaveNumber(filename);
      const familyKey = logicalKey || exactKey;
      const prev = bestByFamily.get(familyKey);
      if (!prev || saveNumber > prev.saveNumber) {
        bestByFamily.set(familyKey, {
          item,
          rel,
          filename,
          saveNumber,
          exactKey,
          logicalKey,
          base,
          atRoot,
        });
      }
    });
    const created = [];
    const seenExact = new Set();
    const seenLogical = new Set();
    const seenBasenames = new Set();
    bestByFamily.forEach((entry) => {
      if (seenExact.has(entry.exactKey) || seenLogical.has(entry.logicalKey)) return;
      if (entry.atRoot && seenBasenames.has(entry.base)) return;
      seenExact.add(entry.exactKey);
      seenLogical.add(entry.logicalKey);
      seenBasenames.add(entry.base);
      created.push({
        filename: entry.filename,
        relative_path: entry.rel,
        size: entry.item.size,
        saved_at: entry.item.saved_at || "",
        object_type: typeFromExtension(filenameExtension(entry.filename || entry.rel)),
        local_cache: true,
      });
    });
    return created;
  }

  function indexLocalCacheTipsByLogical(cacheFiles) {
    /** Highest Creo .N per logical path (and unique basename) from agent /files. */
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
    return { bestByLogical, bestByBasename };
  }

  function latestLocalCacheTipForObject(cacheFiles, objects, objectId) {
    /**
     * Highest on-disk Creo .N for this product object (base-plate.prt.6 over .prt.2).
     * Does not require a vault hash mismatch — used for live Compare / Ask AI gather path.
     */
    const id = String(objectId || "").trim();
    if (!id) return null;
    const obj = (Array.isArray(objects) ? objects : []).find(
      (row) => String(row?.uuid || "") === id
    );
    if (!obj) return null;
    const vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
    if (!vaultRel) return null;
    const { bestByLogical, bestByBasename } = indexLocalCacheTipsByLogical(cacheFiles);
    const key = logicalRelativePath(vaultRel).toLowerCase();
    const safeKey = logicalRelativePath(agentCacheSafeRelativePath(vaultRel)).toLowerCase();
    let local = bestByLogical.get(key) || bestByLogical.get(safeKey);
    if (!local) {
      const base = logicalUploadName(PathBasename(vaultRel)).toLowerCase();
      let basenameCount = 0;
      (Array.isArray(objects) ? objects : []).forEach((row) => {
        const rel = String(row.relative_path || row.filename || "").replace(/\\/g, "/");
        if (!rel) return;
        if (logicalUploadName(PathBasename(rel)).toLowerCase() === base) {
          basenameCount += 1;
        }
      });
      if (basenameCount === 1) local = bestByBasename.get(base);
    }
    if (!local) return null;
    return {
      uuid: obj.uuid,
      filename: local.filename,
      relative_path: local.rel,
      saveNumber: local.saveNumber,
      size: local.item?.size,
    };
  }

  function newerLocalCacheSaves(cacheFiles, objects) {
    // Prefer full vault-relative path. Older flat agent caches (basename only)
    // still match when that basename is unique in the product.
    const { bestByLogical, bestByBasename } = indexLocalCacheTipsByLogical(cacheFiles);
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
      // Prefer .creopdm_cache_index.json hash from GET /files (size-verified).
      const indexHash = String(local.item.content_hash || "").trim().toLowerCase();
      needsHash.push({ row, vaultHash, rel: local.rel, indexHash });
    });
    return { rows, needsHash };
  }

  async function resolveNewerLocalCacheSaves(
    cacheFiles,
    objects,
    productId,
    vaultFolderOverride
  ) {
    const planned = newerLocalCacheSaves(cacheFiles, objects);
    const rows = [...(planned.rows || [])];
    const pending = planned.needsHash || [];
    if (!pending.length) return rows;
    const needHashPaths = [];
    pending.forEach((item) => {
      const indexHash = String(item.indexHash || "").trim().toLowerCase();
      if (indexHash && indexHash !== item.vaultHash) {
        // .creopdm_cache_index.json + on-disk size match — file is real and differs.
        rows.push(item.row);
        return;
      }
      if (indexHash && indexHash === item.vaultHash && !item.row?.newer_save) {
        // Index agrees with vault tip; skip rehash.
        return;
      }
      // Missing index, size-stale index, or newer .N — verify via /hash-paths.
      needHashPaths.push(item);
    });
    if (!needHashPaths.length || !productId) return rows;
    try {
      const hashes = await hashAgentCachePaths(
        productId,
        needHashPaths.map((item) => item.rel),
        vaultFolderOverride
      );
      needHashPaths.forEach((item) => {
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

  function setOpenPrepareBusyMessage() {
    setBusyMessage("Finding dependencies…");
  }

  const BULK_AGENT_CACHE_ZIP_THRESHOLD = 50;

  function setOpenDownloadBusyMessage(prepared) {
    const dependencies = Array.isArray(prepared?.dependencies) ? prepared.dependencies : [];
    const total = 1 + dependencies.length;
    // N is the product dependency count — agent skips tips already on disk.
    if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD) {
      setBusyMessage(`Checking local index (${total} files)…`);
    } else if (total > 1) {
      setBusyMessage(`Updating local workspace… (${total} tips)`);
    } else {
      setBusyMessage("Updating local workspace…");
    }
  }

  async function materializeViaAgentPerFile(prepared, dependencies, { quietBusy = false } = {}) {
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
        content_hash: prepared.content_hash || null,
        file_size: prepared.file_size || 0,
        prefer_local: Boolean(prepared.prefer_local),
        replace_newer: Boolean(prepared.replace_newer),
        dependencies: (dependencies || []).map((item) => ({
          object_id: item.object_id || null,
          product_id: item.product_id || prepared.product_id || currentProductId() || null,
          relative_path: item.relative_path || null,
          filename: item.filename || null,
          disk_name: item.disk_name || item.filename || null,
          content_hash: item.content_hash || null,
          file_size: item.file_size || 0,
          prefer_local: Boolean(item.prefer_local),
        })),
      }),
    });
    if (!response.ok) {
      const message = await readError(response);
      throw new Error(message || "Local CreoPDM agent could not fetch the file.");
    }
    const body = await response.json();
    if (!quietBusy) {
      const skipped = Number(body.skipped_count) || 0;
      const downloaded = Number(body.dependencies_written) || 0;
      if (downloaded > 0) {
        setBusyMessage(
          `Updated local workspace (${downloaded} downloaded, ${skipped} already local)…`
        );
      } else if (skipped > 0) {
        setBusyMessage("Local workspace already up to date…");
      }
    }
    return body;
  }

  async function materializeViaAgent(prepared, { quietBusy = false } = {}) {
    const dependencies = Array.isArray(prepared.dependencies) ? prepared.dependencies : [];
    const ids = [];
    if (prepared.object_id) ids.push(String(prepared.object_id));
    dependencies.forEach((item) => {
      if (item?.object_id) ids.push(String(item.object_id));
    });
    const unique = [...new Set(ids)];
    // Empty / large trees: one zip from CreoPDM (same as bulk checkout), not 900 GETs.
    // Agent plans first — matching local tips are skipped (no re-download).
    if (unique.length >= BULK_AGENT_CACHE_ZIP_THRESHOLD) {
      try {
        if (!quietBusy) {
          setBusyMessage(`Checking local index (${unique.length} files)…`);
        }
        // Pass prepare identities so the agent skips a second 935-id manifest fetch
        // and only looks up `.creopdm_cache_index.json` + file size.
        const zipResult = await materializeCheckedOutToAgentCacheZip(unique, prepared);
        if (!quietBusy) {
          const downloaded = Number(zipResult?.download_count || 0);
          const skipped = Number(zipResult?.skipped_count || 0);
          if (downloaded > 0) {
            setBusyMessage(`Downloaded ${downloaded} missing file${downloaded === 1 ? "" : "s"}…`);
          } else if (skipped > 0) {
            setBusyMessage(`Local workspace up to date (${skipped} files)…`);
          } else {
            setBusyMessage("Local workspace already up to date…");
          }
        }
        // Resolve the primary open path only — deps are already on disk.
        return await materializeViaAgentPerFile(prepared, [], { quietBusy });
      } catch {
        /* fall back to per-file materialize */
        if (!quietBusy) setOpenDownloadBusyMessage(prepared);
      }
    }
    return materializeViaAgentPerFile(prepared, dependencies, { quietBusy });
  }

  function cachePlanItemsFromPrepared(prepared) {
    const items = [];
    const push = (item) => {
      const objectId = String(item?.object_id || "").trim();
      const contentHash = String(item?.content_hash || "").trim();
      if (!objectId || !contentHash) return;
      items.push({
        object_id: objectId,
        product_id: item?.product_id || prepared?.product_id || currentProductId() || "",
        relative_path: item?.relative_path || "",
        filename: item?.filename || item?.disk_name || "",
        disk_name: item?.disk_name || item?.filename || "",
        content_hash: contentHash,
        file_size: Number(item?.file_size) || 0,
      });
    };
    if (prepared) push(prepared);
    (Array.isArray(prepared?.dependencies) ? prepared.dependencies : []).forEach(push);
    return items;
  }

  async function materializeCheckedOutToAgentCacheZip(objectIds, prepared) {
    const planItems = cachePlanItemsFromPrepared(prepared);
    const response = await fetch(`${agentBase()}/materialize-zip`, {
      method: "POST",
      headers: agentAuthHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        pdm_url: window.location.origin,
        ...agentPdmAuth(),
        product_id: currentProductId() || null,
        vault_folder: currentVaultFolder(),
        object_ids: objectIds,
        items: planItems,
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
          { object_id: objectId, launch: false, include_dependencies: false },
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

  function joinLocalWorkspacePath(directory, relativePath) {
    const root = String(directory || "").replace(/[\\/]+$/, "");
    const rel = String(relativePath || "").replace(/\\/g, "/").replace(/^\/+/, "");
    if (!root || !rel) return "";
    const sep = root.includes("\\") ? "\\" : "/";
    return `${root}${sep}${rel.replace(/\//g, sep)}`;
  }

  async function openLocalCacheRelative(productId, relativePath, options) {
    // New file (local) / Modified newer local — open agent workspace tip.
    // Creo.JS needs the logical tip name (shaft.prt); disk may still be shaft.prt.1.
    const objectId = String(options?.objectId || "").trim();
    const wantSetWd = options?.setWorkingDirectory === true;
    const agent = await probeCreoAgent();
    if (!agent) {
      throw new Error(
        "Start creopdm-agent on this Creo PC to open files that exist only in the local workspace."
      );
    }
    const directory = await agentWorkdir(productId, currentVaultFolder());
    const fullPath = joinLocalWorkspacePath(directory, relativePath);
    if (!fullPath) {
      throw new Error("Could not resolve the local workspace path for that file.");
    }
    const diskName = PathBasename(relativePath) || "file";
    const logicalName = logicalUploadName(diskName) || diskName;
    const embeddedMode = creoOpenMode() === "embedded";
    // Same brief Creo.JS wait as vault Open — do not fall through to Windows
    // association from the embedded browser while the bridge is still linking.
    if (embeddedMode && !hostedCreoJS() && !likelyStandaloneBrowser()) {
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
    if (useCreoSession) {
      setBusyMessage("Opening in Creo…");
      await whenCreoJSReady();
      // Opt-in only — Set WD locks the workspace folder for later remove-folder.
      if (wantSetWd) {
        await setCreoWorkingDirectory({ quiet: true });
      }
      const opened = await withTimeout(
        window.CreoJS.openModel(directory, logicalName, "", diskName, fullPath),
        creoOpenModelTimeoutMs(1),
        "Creo did not finish opening the model (session may be offline)."
      );
      const openedText = opened == null ? "" : String(opened);
      if (openedText.indexOf("CREOPDM_ERROR:") === 0) {
        throw new Error(openedText.slice("CREOPDM_ERROR:".length));
      }
      return {
        path: fullPath,
        filename: logicalName,
        working_directory: directory,
        object_id: objectId || null,
        // Same flag as vault Creo.JS open — enables opportunistic metadata capture.
        creo_object: true,
      };
    }
    if (embeddedMode && !useCreoSession && !likelyStandaloneBrowser()) {
      throw new Error(
        "Creo.JS is not connected yet. Wait until the status shows Creo: Connected, then open the file again — do not open via Windows file association from the embedded browser."
      );
    }
    setBusyMessage("Opening with Windows…");
    await openViaAgent(fullPath, "association");
    return {
      path: fullPath,
      filename: logicalName,
      working_directory: directory,
      object_id: objectId || null,
      creo_object: false,
    };
  }

  function openTimeoutMessage() {
    if (creoOpenMode() === "embedded" && !likelyStandaloneBrowser()) {
      return "Open timed out. Check creopdm-agent and that Creo is Connected, then try again.";
    }
    return "Open timed out. Check that creopdm-agent is running, then try again.";
  }

  async function openPdmObject(target, options) {
    // Keep the busy overlay up through prepare + materialize until Creo/OS open starts.
    // Always clear on timeout/error so Session offline / hung agent cannot leave Opening… stuck.
    const openOpts = options && typeof options === "object" ? options : {};
    let result = null;
    await withBusy("Preparing…", async () => {
      try {
        result = await withTimeout(
          openPdmObjectWork(target, openOpts),
          openWorkTimeoutMs(5000),
          openTimeoutMessage()
        );
      } catch (err) {
        const message = err && err.message ? err.message : String(err);
        showError($("#toolbar-error"), message || "Could not open the file.");
        result = null;
      }
    });
    // Best-effort: fill Creo identity/type/deps while the model is in session.
    // Metadata POST updates Type / Features / Where Used — soft-refresh Files or
    // Details so SSR is not stale until the user navigates away and back.
    let metadataSaved = 0;
    try {
      metadataSaved = Number(await captureCreoMetadataAfterOpen(result)) || 0;
    } catch {
      /* soft-fail — open already succeeded */
    }
    const onDetail = Boolean($("article.detail"));
    if (metadataSaved > 0 && (isListPage || onDetail)) {
      try {
        if (onDetail) {
          // Keep Features (etc.) selected across the soft-refresh.
          const tab = document
            .querySelector(".tabs .tab.is-active")
            ?.getAttribute("data-tab");
          if (tab && tab !== "overview") {
            try {
              const url = new URL(window.location.href);
              url.hash = tab;
              window.history.replaceState(window.history.state, "", url.toString());
            } catch {
              /* ignore */
            }
          }
        }
        await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
      } catch {
        /* soft-fail — Open + metadata already succeeded */
      }
    }
    return result;
  }

  function likelyStandaloneBrowser() {
    // True for Chrome/Edge/Firefox outside Creo — Embedded setting may still fall
    // back to OS association. Do not treat a loaded creojs.js (window.CreoJS) as
    // being inside Creo; that script is served to every browser and used to make
    // Session-offline Chrome take the "open from built-in browser" dead end.
    if (hostedCreoJS() || looksLikeCreoEmbeddedBrowser()) return false;
    const ua = String(navigator.userAgent || "");
    return /Chrome|Edg|Firefox|Safari/i.test(ua);
  }

  async function openPdmObjectWork(target, options) {
    const spec = typeof target === "string" ? { objectId: target } : target || {};
    const openOpts = options && typeof options === "object" ? options : {};
    // Set WD only when the Open chooser checkbox was checked (or caller opted in).
    // Default off — File > Open trail resolves companions; WD locks the folder.
    const wantSetWd = Boolean(openOpts.setWorkingDirectory);
    // Local-workspace tips (New file local / Newer local save on Modified) must
    // open from the agent cache — not /api/creo/open (vault tip / missing file).
    if (spec.localCache && spec.relativePath) {
      const productId = spec.productId || currentProductId();
      if (!productId) {
        showError($("#toolbar-error"), "No product is selected.");
        return null;
      }
      return openLocalCacheRelative(productId, spec.relativePath, {
        objectId: spec.objectId || "",
        setWorkingDirectory: wantSetWd,
      });
    }
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
      setOpenPrepareBusyMessage();
      const prepared = await postAction(
        "/api/creo/open",
        openRequestBody(target, false),
        "POST",
        ""
      );
      if (!prepared) return null;

      // Every Creo-openable model must land in the local workspace before open.
      let openSpec = prepared;
      const needsCache =
        prepared.requires_agent_cache || prepared.creo_object || prepared.open_with_creo;
      if (needsCache) {
        const agent = await probeCreoAgent();
        if (!agent) {
          showError(
            $("#toolbar-error"),
            "Start creopdm-agent on this Creo PC so the file can download into the local workspace before open."
          );
          return null;
        }
        try {
          setOpenDownloadBusyMessage(prepared);
          openSpec = await materializeViaAgent(prepared);
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError(
            $("#toolbar-error"),
            message || "Local CreoPDM agent could not download the file into the workspace."
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
          // Opt-in Set WD only (checkbox); trail open does not need WD.
          if (wantSetWd) {
            await setCreoWorkingDirectory({ quiet: true });
          }
          const opened = await withTimeout(
            window.CreoJS.openModel(
              openSpec.working_directory,
              openSpec.filename || prepared.filename,
              prepared.creo_release || "",
              openSpec.disk_name || openSpec.filename || prepared.filename,
              openSpec.path || ""
            ),
            creoOpenModelTimeoutMs(preparedDependencyCount(prepared)),
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
            "Open SolidWorks / Multi-CAD files from Creo's built-in browser so the running session can use the local workspace."
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
            creoOpenModelTimeoutMs(preparedDependencyCount(prepared)),
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
              setOpenDownloadBusyMessage(prepared);
              openSpec = await materializeViaAgent(prepared);
            }
            setBusyMessage("Opening with Windows…");
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
    setOpenPrepareBusyMessage();
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
        setOpenDownloadBusyMessage(prepared);
        const openSpec = await materializeViaAgent(prepared);
        if (!openSpec?.path) {
          showError($("#toolbar-error"), "Local agent did not return a workspace path.");
          return null;
        }
        setBusyMessage("Opening with Windows…");
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
            setBusyMessage(`Checking local workspace for ${total} files…`);
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
    } else if (!productHasVaultFilesForExport()) {
      showError($("#toolbar-error"), "Nothing to export — this product has no vault files yet.");
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
        ? "Undo checkout of this file?\n\nYour lock is released. Unsaved vault changes for this file may be discarded. Local workspace files are kept."
        : `Undo checkout of ${count} files?\n\nYour locks are released. Unsaved vault changes for these files may be discarded. Local workspace files are kept.${slowNote}`;
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

  async function beginAddSelected() {
    const selected = selectedRows();
    if (!canOfferAdd() || !selectionIsAddOnly(selected)) {
      showError(
        $("#toolbar-error"),
        "Select New files (vault or local workspace) to add them to the product."
      );
      return;
    }
    await beginCheckin("selected");
  }

  async function beginCheckin(scope = "selected") {
    const productScope = scope === "product";
    const selected = productScope ? [] : selectedRows();
    const addOnlySelection = !productScope && selectionIsAddOnly(selected);
    if (
      !productScope
      && !selectionCanCheckin(selected)
      && !checkinBtn?.dataset.uuid
      && !addOnlySelection
    ) {
      showError(
        $("#toolbar-error"),
        "Nothing to check in for this selection. Save changes in Creo first, or use Undo Checkout."
      );
      return;
    }
    if (addOnlySelection && !canOfferAdd() && !userCanCheckin()) {
      showError(
        $("#toolbar-error"),
        "You do not have permission to add files."
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
      openWorkspaceBtn?.dataset.product ||
      addForm?.dataset.product ||
      currentProductId();
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
    const commentBoxEarly = $("#checkin-comment");
    if (commentBoxEarly) commentBoxEarly.value = "";
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
    // Add selected…: seed the required comment (first product content gets prefix).
    if (commentBox && canSubmit && addOnly && !String(commentBox.value || "").trim()) {
      const addList = [...selectedNew];
      const single =
        addList.length === 1
          ? String(addList[0] || "").split(/[/\\]/).pop() || ""
          : "";
      commentBox.value = defaultAddHistoryComment({
        count: addList.length,
        singleName: single,
      });
    }
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
    const queueIds = useQueue
      ? JSON.parse(checkinDialog?.dataset.objectIds || "[]")
      : objectId
        ? [objectId]
        : [];
    const pendingNamesForAi = data.pending_files || [];
    const pendingIdsForAi = data.object_ids || [];
    const aiCandidates = [];
    for (const id of queueIds) {
      const oid = String(id || "").trim();
      if (!oid) continue;
      const nameIdx = pendingIdsForAi.indexOf(oid);
      const tipName = tipNameForCheckin(
        oid,
        nameIdx >= 0 ? pendingNamesForAi[nameIdx] : ""
      );
      if (!isCreoMetadataCandidate(tipName)) continue;
      const rowEl = document.querySelector(`tr[data-uuid="${CSS.escape(oid)}"]`);
      const rel = String(
        rowEl?.dataset?.relativePath || rowEl?.dataset?.path || ""
      ).trim();
      aiCandidates.push({
        objectId: oid,
        filename: tipName,
        path: rel,
        nextDisplay: useQueue
          ? "pending"
          : String(data.next_display || "").trim() || "pending",
      });
    }
    syncCheckinAiAskRow({
      addOnly,
      canSubmit,
      candidates: aiCandidates,
    });
    checkinDialog.showModal();
  }

  function aiFeaturesEnabled() {
    return String(document.body?.dataset?.aiEnabled || "1") === "1";
  }

  function syncCheckinAiAskRow(opts) {
    const row = $("#checkin-ai-row");
    const btn = $("#checkin-ask-ai");
    if (!row || !btn || !checkinDialog) return;
    const addOnly = Boolean(opts?.addOnly);
    const canSubmit = Boolean(opts?.canSubmit);
    const candidates = Array.isArray(opts?.candidates)
      ? opts.candidates.filter(
          (item) =>
            item &&
            String(item.objectId || "").trim() &&
            String(item.filename || "").trim()
        )
      : [];
    const aiOn = aiFeaturesEnabled();
    const canAsk =
      aiOn && !addOnly && canSubmit && candidates.length > 0;
    row.hidden = !canAsk;
    btn.disabled = !canAsk || !canGatherCreoMetadata();
    const large = candidates.length > 8;
    btn.title = !aiOn
      ? "AI features are turned off under System Settings → AI"
      : !canAsk
        ? "Ask AI for comment needs at least one modified Creo model in this check-in"
        : !canGatherCreoMetadata()
          ? "Open this page in Creo’s embedded browser with Creo Connected to collect the modified model"
          : large
            ? `Summarize all ${candidates.length} modified Creo models into one check-in comment (may take several minutes)`
            : candidates.length === 1
              ? "Collect metadata on the modified model, compare to the tip snapshot, and fill the comment"
              : `Summarize all ${candidates.length} modified Creo models into one check-in comment`;
    checkinDialog.dataset.aiCandidates = canAsk ? JSON.stringify(candidates) : "[]";
    // Legacy single-id fields kept for resolvePendingCheckinLocalPath defaults.
    const first = canAsk ? candidates[0] : null;
    checkinDialog.dataset.aiObjectId = first ? String(first.objectId) : "";
    checkinDialog.dataset.aiFilename = first ? String(first.filename) : "";
    checkinDialog.dataset.aiNextDisplay = first
      ? String(first.nextDisplay || "pending")
      : "";
    checkinDialog.dataset.aiPath = first ? String(first.path || "") : "";
  }

  async function resolvePendingCheckinLocalPath(objectId, logicalFilename, options) {
    /**
     * Local modified tip for Ask AI (tip snapshot A.n vs file being checked in).
     * Never materialize the vault tip — that compared A.1 to A.1 again.
     */
    const opts = options && typeof options === "object" ? options : {};
    const id = String(objectId || "").trim();
    const productId =
      String(opts.productId || "").trim() || currentProductId();
    const vaultFolder =
      String(opts.vaultFolder || "").trim() || currentVaultFolder();
    if (!id || !productId) return { path: "", diskName: "", logicalName: "" };
    let tipFilename = String(logicalFilename || "").trim();
    let rel = String(
      opts.relativePath || checkinDialog?.dataset.aiPath || ""
    )
      .trim()
      .replace(/\\/g, "/");
    try {
      const items = JSON.parse(checkinDialog?.dataset.pushItems || "[]");
      const hit = (Array.isArray(items) ? items : []).find(
        (item) => String(item?.object_id || "") === id
      );
      if (hit?.filename) tipFilename = String(hit.filename).trim();
      if (hit?.relative_path) rel = String(hit.relative_path).trim().replace(/\\/g, "/");
    } catch {
      /* keep defaults */
    }
    try {
      const [cacheFiles, objects] = await Promise.all([
        listAgentCacheFiles(productId, vaultFolder),
        ensureProductObjects(productId),
      ]);
      // Always prefer the highest Creo .N on disk (e.g. .prt.6 over .prt.2).
      const latest = latestLocalCacheTipForObject(cacheFiles, objects, id);
      if (latest?.filename) tipFilename = String(latest.filename).trim();
      if (latest?.relative_path) {
        rel = String(latest.relative_path).trim().replace(/\\/g, "/");
      } else {
        const newer = (
          await resolveNewerLocalCacheSaves(cacheFiles, objects, productId)
        ).find((item) => String(item?.uuid || "") === id);
        if (newer?.filename) tipFilename = String(newer.filename).trim();
        if (newer?.relative_path) {
          rel = String(newer.relative_path).trim().replace(/\\/g, "/");
        }
      }
    } catch {
      /* agent offline — try pushItems / relative only */
    }
    const logicalName =
      logicalUploadName(tipFilename) || logicalUploadName(PathBasename(rel)) || tipFilename;
    const diskName = PathBasename(tipFilename) || PathBasename(rel) || logicalName;
    // Cache relative may be logical (wedge.drw); disk tip may be wedge.drw.2.
    let cacheRel = rel;
    if (cacheRel && diskName && PathBasename(cacheRel).toLowerCase() !== diskName.toLowerCase()) {
      const dir = cacheRel.includes("/")
        ? cacheRel.slice(0, cacheRel.lastIndexOf("/") + 1)
        : "";
      cacheRel = `${dir}${diskName}`;
    } else if (!cacheRel && diskName) {
      cacheRel = diskName;
    }
    const directory = await agentWorkdir(productId, vaultFolder).catch(() => "");
    const path = joinLocalWorkspacePath(directory, cacheRel);
    return {
      path: looksLikeLocalWindowsPath(path) ? path : "",
      diskName,
      logicalName: logicalName || diskName,
      relative_path: String(cacheRel || "").replace(/\\/g, "/"),
      saveNumber: creoSaveNumber(diskName),
    };
  }

  async function askAiCheckinCommentForOne(candidate, index, total) {
    /**
     * Tip snapshot (A.n) vs pending gather for one Creo model.
     * Prefer session — never Erase. Disk path only if not in session.
     */
    const objectId = String(candidate?.objectId || "").trim();
    const filename = String(candidate?.filename || "").trim();
    const nextDisplay = String(candidate?.nextDisplay || "pending").trim();
    if (!objectId || !filename) {
      throw new Error("Missing Creo model for Ask AI.");
    }
    // Per-candidate path for resolvePendingCheckinLocalPath.
    if (checkinDialog) {
      checkinDialog.dataset.aiObjectId = objectId;
      checkinDialog.dataset.aiFilename = filename;
      checkinDialog.dataset.aiPath = String(candidate?.path || "").trim();
      checkinDialog.dataset.aiNextDisplay = nextDisplay;
    }
    publishBusyMessage(
      total > 1
        ? `Collecting ${index} of ${total}: ${filename}…`
        : "Collecting modified model…"
    );
    const pending = await resolvePendingCheckinLocalPath(objectId, filename);
    const gatherName =
      pending.logicalName || logicalUploadName(filename) || filename;
    let snapshot = await gatherCreoMetadataForFilename(gatherName, "", {
      featureNames: true,
    });
    if (snapshot && snapshot.__error) snapshot = null;
    let gatherSource = snapshot ? "session" : "";
    if (!snapshot && pending.path) {
      snapshot = await gatherCreoMetadataForFilename(gatherName, pending.path, {
        featureNames: true,
        preferDisk: true,
      });
      if (snapshot && snapshot.__error) {
        throw new Error(
          String(
            snapshot.__detail
              || snapshot.__error
              || `Could not gather metadata from ${filename}.`
          )
        );
      }
      gatherSource = "disk";
    }
    if (!snapshot) {
      throw new Error(
        `Could not find ${filename} in Creo. Keep it open `
          + "(or Save so it is in the local workspace), then try again."
      );
    }
    // Same body as postAiSnapshotFromGather (what Modifications stores).
    const newerSnapshot = aiSnapshotBodyFromGather(snapshot);
    if (!newerSnapshot) {
      throw new Error(
        `Creo did not return an AI snapshot for ${filename}. `
          + "Collect metadata on the tip while it is clean, then try again."
      );
    }
    try {
      if (!newerSnapshot.capture || typeof newerSnapshot.capture !== "object") {
        newerSnapshot.capture = {};
      }
      newerSnapshot.capture.compare_source = gatherSource || "unknown";
    } catch {
      /* ignore */
    }
    publishBusyMessage(
      total > 1
        ? `Asking AI ${index} of ${total}: ${filename}…`
        : "Asking AI for check-in comment…"
    );
    let response;
    try {
      response = await fetch(
        `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/compare-pending`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          cache: "no-store",
          signal: abortSignalAfter(120_000),
          body: JSON.stringify({
            newer_snapshot: newerSnapshot,
            // Queue preview uses "—" for next_display — never send that to Ollama.
            newer_display_revision:
              nextDisplay && nextDisplay !== "—" ? nextDisplay : "pending",
          }),
        }
      );
    } catch (errFetch) {
      const aborted =
        errFetch?.name === "AbortError"
        || /aborted|timeout/i.test(String(errFetch?.message || errFetch || ""));
      throw new Error(
        aborted
          ? "Ollama timed out after 2 minutes. Is it running on the CreoPDM server and is the model loaded?"
          : String(errFetch?.message || errFetch || "Could not reach CreoPDM for AI compare.")
      );
    }
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    const text = String(payload?.summary || "").trim();
    if (!text) throw new Error(`Ollama returned an empty summary for ${filename}.`);
    return { filename, summary: text };
  }

  function formatCheckinBatchCommentFallback(notes) {
    const bullets = [];
    for (const note of notes || []) {
      const name = String(note?.filename || "").trim() || "(unnamed)";
      let one = String(note?.summary || "").trim().replace(/\s+/g, " ");
      if (!one) continue;
      if (one.length > 220) one = `${one.slice(0, 217).trim()}…`;
      bullets.push(`- ${name}: ${one}`);
    }
    return bullets.length ? `Check-in summary:\n${bullets.join("\n")}` : "";
  }

  async function synthesizeCheckinComment(notes) {
    const productId = currentProductId();
    if (!productId || !notes?.length) {
      return formatCheckinBatchCommentFallback(notes);
    }
    if (notes.length === 1) return String(notes[0].summary || "").trim();
    publishBusyMessage("Summarizing check-in comment…");
    try {
      const response = await fetch(
        `/api/products/${encodeURIComponent(productId)}/ai/checkin-comment-synthesize`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          cache: "no-store",
          signal: abortSignalAfter(120_000),
          body: JSON.stringify({ notes }),
        }
      );
      if (!response.ok) throw new Error(await readError(response));
      const payload = await response.json();
      const text = String(payload?.summary || "").trim();
      if (text) return text;
    } catch {
      /* fall through to bullets */
    }
    return formatCheckinBatchCommentFallback(notes);
  }

  async function askAiCheckinComment() {
    let candidates = [];
    try {
      candidates = JSON.parse(checkinDialog?.dataset.aiCandidates || "[]");
    } catch {
      candidates = [];
    }
    if (!Array.isArray(candidates) || !candidates.length) {
      const objectId = String(checkinDialog?.dataset.aiObjectId || "").trim();
      const filename = String(checkinDialog?.dataset.aiFilename || "").trim();
      if (objectId && filename) {
        candidates = [
          {
            objectId,
            filename,
            path: String(checkinDialog?.dataset.aiPath || "").trim(),
            nextDisplay: String(checkinDialog?.dataset.aiNextDisplay || "pending").trim(),
          },
        ];
      }
    }
    const commentBox = $("#checkin-comment");
    showError($("#checkin-error"), "");
    if (!aiFeaturesEnabled()) {
      showError(
        $("#checkin-error"),
        "AI features are turned off. Open System Settings → AI, check Enable AI features, and Save."
      );
      return;
    }
    if (!candidates.length) {
      showError(
        $("#checkin-error"),
        "Ask AI for comment needs at least one modified Creo model in this check-in."
      );
      return;
    }
    if (!canGatherCreoMetadata()) {
      showError(
        $("#checkin-error"),
        "Open this page in Creo’s embedded browser with Creo Connected to collect the modified model."
      );
      return;
    }
    try {
      const summary = await withBusy(
        candidates.length > 1
          ? `Collecting ${candidates.length} modified models…`
          : "Collecting modified model…",
        async () => {
          const notes = [];
          const failures = [];
          for (let i = 0; i < candidates.length; i++) {
            try {
              notes.push(
                await askAiCheckinCommentForOne(candidates[i], i + 1, candidates.length)
              );
            } catch (errOne) {
              failures.push(
                `${candidates[i]?.filename || "file"}: ${String(errOne?.message || errOne)}`
              );
            }
          }
          if (!notes.length) {
            throw new Error(
              failures[0]
                || "Could not gather any modified Creo models for Ask AI."
            );
          }
          const text = await synthesizeCheckinComment(notes);
          if (!text) throw new Error("Ollama returned an empty summary.");
          return { text, failures, used: notes.length };
        }
      );
      if (commentBox) {
        commentBox.value = summary.text;
        commentBox.focus();
      }
      if (summary.failures?.length) {
        showError(
          $("#checkin-error"),
          `Comment filled from ${summary.used} model(s). Skipped: ${summary.failures.join("; ")}`
        );
      }
    } catch (err) {
      showError(
        $("#checkin-error"),
        String(err?.message || err || "Could not ask AI for a check-in comment.")
      );
    }
  }

  checkinBtn?.addEventListener("click", () => {
    void beginCheckin("selected");
  });
  checkinProductBtn?.addEventListener("click", () => {
    void beginCheckin("product");
  });

  $("#checkin-ask-ai")?.addEventListener("click", () => {
    void askAiCheckinComment();
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
      const productId =
        checkinBtn?.dataset.product ||
        checkinDialog?.dataset.productId ||
        addForm?.dataset.product ||
        openWorkspaceBtn?.dataset.product ||
        currentProductId();
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
      // New files via Add selected… / check-in add paths: Where Used first, then metadata.
      const addedPaths = Array.isArray(added) ? added.length : 0;
      const addOnlyCheckin = checkinDialog?.dataset.addOnly === "1";
      if (succeeded && (addOnlyCheckin || addedPaths > 0)) {
        const productIdForIndex =
          checkinDialog?.dataset.productId ||
          checkinBtn?.dataset.product ||
          currentProductId();
        await indexWhereUsedUnderBusy(productIdForIndex);
      }
      if (canGatherCreoMetadata()) {
        await withBusy("Collecting Creo metadata…", async () => {
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
    // Soft-nav like folders — hard reload kills Creo.JS / paints Session offline.
    if (href) leavePage(href);
  });

  function confirmByPassword({
    title,
    lead,
    note,
    submitLabel,
    detailsHtml = "",
    workspaceOption = false,
    requirePassword = true,
  }) {
    const dialog = $("#danger-confirm-dialog");
    const form = $("#danger-confirm-form");
    if (!dialog || !form) {
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
    const passwordLabel =
      $("#danger-confirm-password-label")
      || form.querySelector('label[for="danger-confirm-input"]')
      || form.querySelector("label:has(#danger-confirm-input)");
    const passwordInput = $("#danger-confirm-input");
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
    if (passwordLabel) passwordLabel.hidden = !requirePassword;
    if (passwordInput) {
      passwordInput.required = Boolean(requirePassword);
      passwordInput.hidden = !requirePassword;
      passwordInput.value = "";
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
        if (passwordLabel) passwordLabel.hidden = false;
        if (passwordInput) {
          passwordInput.hidden = false;
          passwordInput.required = true;
          passwordInput.value = "";
        }
        const deleteWorkspaceFiles = Boolean(ok && workspaceOption && workspaceCheck?.checked);
        if (dialog.open) dialog.close();
        resolve({ ok: Boolean(ok), deleteWorkspaceFiles });
      };
      const onCancel = () => finish(false);
      const onClose = () => finish(false);
      const onSubmit = async (event) => {
        event.preventDefault();
        if (requirePassword) {
          const password = String(new FormData(form).get("confirm_password") || "");
          if (!password) {
            showError($("#danger-confirm-error"), "Enter your password to confirm.");
            return;
          }
          if (submitBtn) submitBtn.disabled = true;
          showError($("#danger-confirm-error"), "");
          try {
            const response = await fetch("/api/account/confirm-password", {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ password }),
            });
            if (!response.ok) {
              showError(
                $("#danger-confirm-error"),
                await readError(response) || "Incorrect password."
              );
              return;
            }
          } catch (exc) {
            showError(
              $("#danger-confirm-error"),
              exc?.message || "Could not verify password."
            );
            return;
          } finally {
            if (submitBtn) submitBtn.disabled = false;
          }
        }
        finish(true);
      };
      form.addEventListener("submit", onSubmit);
      $("#danger-confirm-cancel")?.addEventListener("click", onCancel);
      dialog.addEventListener("close", onClose);
      dialog.showModal();
      if (requirePassword) $("#danger-confirm-input")?.focus();
      else submitBtn?.focus();
    });
  }

  // Back-compat alias — callers used product-name typing before password re-auth.
  const confirmByProductName = confirmByPassword;

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
  $("#add-selected-btn")?.addEventListener("click", () => {
    closeAddMenu();
    void beginAddSelected();
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
          ? "This moves the file from the local workspace on this PC to the Recycle Bin. The vault and product list are unchanged."
          : "These files move from the local workspace on this PC to the Recycle Bin. The vault and product list are unchanged.",
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
    else if (activeListTab() === "modified") await loadModifiedTab();
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
      lead: `About to move ${wouldDelete} older local Creo model save(s) from the local workspace to the Recycle Bin on this PC. The vault revision and any newer local work stay. The vault is not changed.`,
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
    else if (activeListTab() === "modified") await loadModifiedTab();
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
          "Local creopdm-agent does not support Clear workspace yet. Restart the creopdm-agent tray (or reinstall from this repo), then try again."
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
    // Same danger-confirm overlay as Remove / Purge (no product-name typing).
    const confirmed = await confirmByProductName({
      title: "Clear workspace",
      lead:
        "This clears this product’s local workspace on this PC (everything inside the workspace folder — "
        + "CAD, folders, cache files, and any other file). "
        + "Local-only new files that were never added to the product are deleted. "
        + "The empty workspace folder stays so Creo’s working directory can remain set. "
        + "Vault copies and the product file list are not changed — open or rematerialize from the vault when you need files again.",
      note:
        "Close open models in Creo first (File → Erase) if files are locked. "
        + "This cannot be undone from CreoPDM. Restore from the Recycle Bin on this PC if needed.",
      submitLabel: "Clear workspace",
      requirePassword: false,
    });
    if (!confirmed.ok) return;
    showError($("#toolbar-error"), "");
    const result = await withBusy("Clearing local workspace…", async () => {
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
        "Start creopdm-agent on this Creo PC to clear the local workspace."
      );
      return;
    }
    knownWorkspacePaths.at = 0;
    cachedProductObjects.at = 0;
    if (result.deleted) {
      showOk(result.message || "Local workspace contents moved to the Recycle Bin.");
    } else {
      showOk(result.message || "Local workspace was already empty.");
    }
    if (activeListTab() === "changes") await loadChangesTab();
    else if (activeListTab() === "modified") await loadModifiedTab();
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
        try {
          await withBusy("Cleaning local workspace…", () =>
            deleteLocalWorkspacePathsForRemove(productId, workspacePaths)
          );
        } catch (errWs) {
          showError(
            $("#toolbar-error"),
            String(errWs?.message || errWs || "Local workspace cleanup failed.")
          );
        }
      }
      leavePage(productHome());
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
      let wsWarning = "";
      try {
        const ws = await withBusy("Cleaning local workspace…", () =>
          deleteLocalWorkspacePathsForRemove(productId, workspacePaths)
        );
        if (ws?.failed?.length) {
          wsWarning = `Local workspace: ${ws.failed.length} file(s) could not be deleted (often locked in Creo).`;
        }
      } catch (errWs) {
        wsWarning = String(
          errWs?.message || errWs || "Local workspace cleanup failed."
        );
      }
      if (wsWarning) {
        showError($("#toolbar-error"), warning ? `${warning} ${wsWarning}` : wsWarning);
      } else if (!warning) {
        showOk(`${result.ok.length} item(s) removed from the product.`);
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

  function rememberCheckinQueueParts(productId, parts) {
    checkinQueueCache = {
      productId: String(productId || ""),
      at: Date.now(),
      saves: Array.isArray(parts?.saves) ? parts.saves : [],
      created: Array.isArray(parts?.created) ? parts.created : [],
      newerLocal: Array.isArray(parts?.newerLocal) ? parts.newerLocal : [],
    };
  }

  function invalidateCheckinQueueCache() {
    checkinQueueCache = {
      productId: "",
      at: 0,
      saves: [],
      created: [],
      newerLocal: [],
    };
  }

  function checkinQueueCacheCounts(parts) {
    const saves = parts?.saves || [];
    const created = parts?.created || [];
    const newerLocal = parts?.newerLocal || [];
    return {
      modified: saves.length + newerLocal.length,
      created: created.length,
    };
  }

  function tabBadgeCount(tabName) {
    const tab = document.querySelector(`.tab[data-tab="${tabName}"]`);
    const match = String(tab?.textContent || "").match(/·\s*(\d+)\s*$/);
    return match ? Number(match[1]) : 0;
  }

  function cachedCheckinQueueParts(productId, { focus } = {}) {
    if (!productId || checkinQueueCache.productId !== String(productId)) return null;
    if (!checkinQueueCache.at) return null;
    // Reject stale empty/partial caches when the tab badge already moved.
    const counts = checkinQueueCacheCounts(checkinQueueCache);
    if (focus === "changes" && counts.created !== tabBadgeCount("changes")) return null;
    if (focus === "modified" && counts.modified !== tabBadgeCount("modified")) return null;
    if (
      focus !== "changes"
      && focus !== "modified"
      && (counts.created !== tabBadgeCount("changes")
        || counts.modified !== tabBadgeCount("modified"))
    ) {
      return null;
    }
    return checkinQueueCache;
  }

  async function loadCheckinQueueParts(productId, vaultFolderOverride) {
    const listed = await listAgentCacheFilesPreferringVault(
      productId,
      vaultFolderOverride
    );
    const cacheFiles = Array.isArray(listed.files) ? listed.files : [];
    const [queueResponse, objectsResponse] = await Promise.all([
      fetch(`/api/products/${productId}/checkin-queue`),
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
      await resolveNewerLocalCacheSaves(
        cacheFiles,
        objects,
        productId,
        listed.vaultFolder || vaultFolderOverride
      )
    ).filter((item) => !vaultSaveIds.has(String(item.uuid || "")));
    const parts = {
      saves,
      created,
      newerLocal,
      agentListed: Boolean(listed.listed),
    };
    rememberCheckinQueueParts(productId, parts);
    return parts;
  }

  function prefetchCheckinQueueParts(productId) {
    if (!productId) return Promise.resolve(null);
    if (checkinQueuePrefetch) return checkinQueuePrefetch;
    checkinQueuePrefetch = loadCheckinQueueParts(productId)
      .then((parts) => {
        const modifiedCount = parts.saves.length + parts.newerLocal.length;
        setCheckinQueueCounts(modifiedCount, parts.created.length);
        lastModifiedPending = modifiedCount;
        lastChangesPending = parts.created.length;
        return parts;
      })
      .catch(() => null)
      .finally(() => {
        checkinQueuePrefetch = null;
      });
    return checkinQueuePrefetch;
  }

  async function applyCheckinQueueParts(productId, parts, focus) {
    const saves = parts.saves || [];
    const created = parts.created || [];
    const newerLocal = parts.newerLocal || [];
    const modifiedCount = saves.length + newerLocal.length;
    setCheckinQueueCounts(modifiedCount, created.length);
    lastModifiedPending = modifiedCount;
    lastChangesPending = created.length;
    rememberPendingCheckinIds([
      ...saves.map((item) => item.uuid),
      ...newerLocal
        .filter((item) => item.can_checkin === "1")
        .map((item) => item.uuid),
    ]);
    if (focus === "modified") {
      const body = $("#modified-table tbody");
      if (!body) return modifiedCount;
      if (!modifiedCount) {
        showQueueEmpty(body, "No modified vault or local workspace files.");
        void refreshPendingCheckinIds(productId);
        return 0;
      }
      renderModifiedQueueRows(body, productId, saves, newerLocal);
      refreshTabMetrics();
      return modifiedCount;
    }
    const body = $("#changes-table tbody");
    if (!body) return created.length;
    if (!created.length) {
      showQueueEmpty(body, "No new vault or local workspace files.");
      void refreshPendingCheckinIds(productId);
      return 0;
    }
    renderNewFilesQueueRows(body, productId, created);
    refreshTabMetrics();
    return created.length;
  }

  function appendQueueRow(body, productId, values, className, meta = {}) {
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
  }

  function showQueueEmpty(body, message) {
    body.replaceChildren();
    const row = document.createElement("tr");
    row.className = "empty-row";
    const cell = document.createElement("td");
    cell.colSpan = 5;
    cell.textContent = message;
    row.appendChild(cell);
    body.appendChild(row);
    refreshTabMetrics();
  }

  function renderModifiedQueueRows(body, productId, saves, newerLocal) {
    body.replaceChildren();
    saves.forEach((item) => {
      appendQueueRow(
        body,
        productId,
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
      appendQueueRow(
        body,
        productId,
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
  }

  function renderNewFilesQueueRows(body, productId, created) {
    body.replaceChildren();
    created.forEach((item) => {
      const offerAdd = canOfferAdd();
      const newDetail = !offerAdd
        ? item.local_cache
          ? "Local workspace."
          : "Not in the product yet."
        : item.local_cache
          ? "Local workspace — select and Add."
          : "Not in the product yet. Select and click Add.";
      appendQueueRow(
        body,
        productId,
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
  }

  async function loadModifiedTab(options = {}) {
    const quiet = Boolean(options.quiet);
    const forceNetwork = Boolean(options.forceNetwork);
    const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
    const body = $("#modified-table tbody");
    if (!productId || !body) return 0;
    // Never flash “Looking for…” — badge/count already moved; keep prior rows until ready.
    try {
      if (!forceNetwork && checkinQueuePrefetch) {
        const parts = await checkinQueuePrefetch;
        const counts = checkinQueueCacheCounts(parts || {});
        // In-flight prefetch can still be the pre-count snapshot — ignore if badge disagrees.
        if (parts && counts.modified === tabBadgeCount("modified")) {
          return applyCheckinQueueParts(productId, parts, "modified");
        }
      }
      const cached = !forceNetwork
        ? cachedCheckinQueueParts(productId, { focus: "modified" })
        : null;
      if (cached) {
        const count = await applyCheckinQueueParts(productId, cached, "modified");
        if (!quiet) void loadModifiedTab({ quiet: true, forceNetwork: true });
        return count;
      }
      const parts = await loadCheckinQueueParts(productId);
      return await applyCheckinQueueParts(productId, parts, "modified");
    } catch {
      if (!quiet && !body.querySelector(".queue-row")) {
        showQueueEmpty(body, "Could not load modified files.");
      }
      return lastModifiedPending || 0;
    }
  }

  async function loadChangesTab(options = {}) {
    const quiet = Boolean(options.quiet);
    const forceNetwork = Boolean(options.forceNetwork);
    const productId = checkinBtn?.dataset.product || openWorkspaceBtn?.dataset.product;
    const body = $("#changes-table tbody");
    if (!productId || !body) return 0;
    // Never flash “Looking for…” — badge/count already moved; keep prior rows until ready.
    try {
      if (!forceNetwork && checkinQueuePrefetch) {
        const parts = await checkinQueuePrefetch;
        const counts = checkinQueueCacheCounts(parts || {});
        if (parts && counts.created === tabBadgeCount("changes")) {
          return applyCheckinQueueParts(productId, parts, "changes");
        }
      }
      const cached = !forceNetwork
        ? cachedCheckinQueueParts(productId, { focus: "changes" })
        : null;
      if (cached) {
        const count = await applyCheckinQueueParts(productId, cached, "changes");
        if (!quiet) void loadChangesTab({ quiet: true, forceNetwork: true });
        return count;
      }
      const parts = await loadCheckinQueueParts(productId);
      return await applyCheckinQueueParts(productId, parts, "changes");
    } catch {
      if (!quiet && !body.querySelector(".queue-row")) {
        showQueueEmpty(body, "Could not load new files.");
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
              dependencies: [],
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
      else if (name === "modified") void loadModifiedTab();
      else if (name === "checked-out") void loadCheckedOutTab();
      else if (name === "where-used") void loadWhereUsedTab();
      else if (name === "snapshot" || name === "compare-revisions") {
        void loadAiSnapshotTab();
      }
      else refreshTabMetrics();
      syncSearchFormVisibility();
      syncDetailToolbar();
      // Keep list tab ready for Details → Back (Details boot must not consume it).
      if (LIST_RESTORE_TABS.has(String(name || "")) && document.querySelector("#object-table")) {
        persistListTabState(name);
      }
    });
  });

  let aiSnapshotListCache = null;
  const aiSnapshotOutlineByVersion = new Map();
  /** Newest-first revisions that have snapshots (Modifications dropdowns). */
  let aiSnapshotCompareVersions = [];
  /** Live workspace gather for pending Compare → Ask AI (compare-pending). */
  let aiSnapshotPendingGather = null;
  /** Right NEW dropdown may list live Modified (Files Modified / newer local .N). */
  let aiSnapshotIncludeModified = false;
  /** selectB value for live workspace gather (API compare-pending still uses pending). */
  const AI_SNAPSHOT_MODIFIED_VALUE = "pending";

  function clearAiSnapshotClientCache() {
    aiSnapshotListCache = null;
    aiSnapshotOutlineByVersion.clear();
    aiSnapshotCompareVersions = [];
    aiSnapshotPendingGather = null;
    aiSnapshotIncludeModified = false;
  }

  function isAiSnapshotModifiedValue(value) {
    const v = String(value || "").trim().toLowerCase();
    return v === AI_SNAPSHOT_MODIFIED_VALUE || v === "modified";
  }

  function aiSnapshotCompareIndex(versionId) {
    const id = String(versionId || "").trim();
    if (!id) return -1;
    return aiSnapshotCompareVersions.findIndex(
      (item) => String(item.version_id || "") === id
    );
  }

  function fillAiSnapshotHistoryOptions(select, indexes, selectedIdx) {
    select.replaceChildren();
    indexes.forEach((idx) => {
      const item = aiSnapshotCompareVersions[idx];
      if (!item) return;
      const option = document.createElement("option");
      option.value = String(item.version_id || "");
      option.textContent = String(item.display_revision || option.value);
      select.appendChild(option);
    });
    const selected = aiSnapshotCompareVersions[selectedIdx];
    if (selected) select.value = String(selected.version_id || "");
  }

  function prependAiSnapshotModifiedOption(selectB, selected) {
    if (!selectB || !aiSnapshotIncludeModified) return;
    const option = document.createElement("option");
    option.value = AI_SNAPSHOT_MODIFIED_VALUE;
    option.textContent = "Modified";
    selectB.insertBefore(option, selectB.firstChild);
    if (selected) selectB.value = AI_SNAPSHOT_MODIFIED_VALUE;
  }

  function fillAiSnapshotOrderedSelects(preferOldId, preferNewId, changed) {
    /**
     * API list is newest-first, so smaller index = newer revision.
     * OLD may only pick indexes > NEW; NEW may only pick indexes < OLD.
     * When Files would show Modified, NEW also lists **Modified** (live gather)
     * and defaults to it — tip History snap stays selectable on OLD (e.g. A.2).
     * NEW History picks are only revisions newer than OLD (never older A.1).
     * Landing on Modified advances OLD to the tip so the tip A.n is not also on NEW.
     */
    const selectA = $("#ai-snapshot-rev-a");
    const selectB = $("#ai-snapshot-rev-b");
    const n = aiSnapshotCompareVersions.length;
    if (!selectA || !selectB || n < 1) return;
    const panel = aiSnapshotPanel();
    const tipId = String(panel?.dataset.tipVersion || "").trim();

    // One History snap + live Modified: tip on left, Modified on right.
    if (n === 1) {
      if (!aiSnapshotIncludeModified) return;
      const item = aiSnapshotCompareVersions[0];
      selectA.replaceChildren();
      const optionA = document.createElement("option");
      optionA.value = String(item?.version_id || "");
      optionA.textContent = String(item?.display_revision || optionA.value);
      selectA.appendChild(optionA);
      selectA.value = optionA.value;
      selectA.disabled = true;
      selectB.replaceChildren();
      prependAiSnapshotModifiedOption(selectB, true);
      selectB.disabled = true;
      return;
    }

    const newIsModified =
      aiSnapshotIncludeModified && isAiSnapshotModifiedValue(preferNewId);

    if (newIsModified) {
      // NEW = Modified: advance OLD to tip (last known, e.g. A.2) unless the
      // user just changed OLD. Right = Modified + History newer than OLD only
      // (tip on left ⇒ drop A.2 from right; only Modified remains).
      const tipIdx = aiSnapshotCompareIndex(tipId);
      let oldIdx = aiSnapshotCompareIndex(preferOldId);
      if (changed === "old" && oldIdx >= 0) {
        /* keep the user's OLD pick */
      } else if (tipIdx >= 0) {
        oldIdx = tipIdx;
      } else if (oldIdx < 0) {
        oldIdx = 0;
      }
      const allIdx = [];
      for (let i = 0; i < n; i += 1) allIdx.push(i);
      fillAiSnapshotHistoryOptions(selectA, allIdx, oldIdx);
      selectA.disabled = false;
      // Newest-first: indexes < oldIdx are strictly newer than OLD.
      const newerThanOld = [];
      for (let i = 0; i < oldIdx; i += 1) newerThanOld.push(i);
      selectB.replaceChildren();
      prependAiSnapshotModifiedOption(selectB, true);
      newerThanOld.forEach((idx) => {
        const item = aiSnapshotCompareVersions[idx];
        if (!item) return;
        const option = document.createElement("option");
        option.value = String(item.version_id || "");
        option.textContent = String(item.display_revision || option.value);
        selectB.appendChild(option);
      });
      selectB.value = AI_SNAPSHOT_MODIFIED_VALUE;
      selectB.disabled = false;
      return;
    }

    let newIdx = aiSnapshotCompareIndex(preferNewId);
    let oldIdx = aiSnapshotCompareIndex(preferOldId);
    if (newIdx < 0) newIdx = 0;
    if (oldIdx < 0) oldIdx = Math.min(1, n - 1);

    if (newIdx >= oldIdx) {
      if (changed === "new") {
        oldIdx = Math.min(newIdx + 1, n - 1);
      } else if (changed === "old") {
        newIdx = Math.max(oldIdx - 1, 0);
      } else {
        newIdx = 0;
        oldIdx = 1;
      }
    }
    if (newIdx >= oldIdx) {
      newIdx = 0;
      oldIdx = 1;
    }

    const oldAllowed = [];
    for (let i = newIdx + 1; i < n; i += 1) oldAllowed.push(i);
    const newAllowed = [];
    for (let i = 0; i < oldIdx; i += 1) newAllowed.push(i);

    fillAiSnapshotHistoryOptions(selectA, oldAllowed, oldIdx);
    fillAiSnapshotHistoryOptions(selectB, newAllowed, newIdx);
    selectA.disabled = false;
    selectB.disabled = false;
    // Keep Modified available so you can switch back from A.2 → live tip.
    prependAiSnapshotModifiedOption(selectB, false);
  }

  function aiSnapshotEmptyMessage(displayRevision) {
    const rev = String(displayRevision || "").trim() || "this revision";
    return (
      `No snapshot for ${rev}.\n\n`
      + "Open the model in Creo and Collect metadata (or Open / Check In with Creo Connected) "
      + "while this version is the tip to create one."
    );
  }

  function aiSnapshotPaneRole(pane) {
    return pane === "b" ? "NEW" : "OLD";
  }

  function formatAiSnapshotOutlineDisplay(role, displayRevision, outline) {
    const rev = String(displayRevision || "").trim() || "—";
    const text = String(outline || "").trim();
    if (!text) return "";
    const roleLabel = String(role || "").trim().toUpperCase() || "OLD";
    return `=== ${roleLabel} snapshot (${rev}) ===\n${text}`;
  }

  function aiSnapshotPanel() {
    return $("#panel-snapshot") || $("#panel-compare-revisions");
  }

  function syncAiSnapshotAskVisibility(livePendingReady) {
    const askRow = $("#ai-snapshot-ask-row");
    if (!askRow) return;
    const mode = String($("#ai-snapshot-compare")?.dataset.mode || "");
    const rightIsModified = isAiSnapshotModifiedValue(
      $("#ai-snapshot-rev-b")?.value
    );
    if (!aiFeaturesEnabled()) {
      askRow.hidden = true;
      return;
    }
    // Live Modified gather — Ask AI only after outline is ready.
    if (mode === "pending" || rightIsModified) {
      askRow.hidden = !livePendingReady;
      return;
    }
    if (mode === "compare") {
      askRow.hidden = false;
      return;
    }
    askRow.hidden = true;
  }

  function syncAiSnapshotTabChrome(mode) {
    /**
     * Always "Modifications":
     * compare = two History snaps (OLD/NEW) + Ask AI;
     * pending = Checked in tip vs Not checked in workspace (or boxed placeholder).
     */
    const resolved = mode === "compare" ? "compare" : "pending";
    const compare = $("#ai-snapshot-compare");
    if (compare) compare.dataset.mode = resolved;
    const tab =
      document.querySelector('.tabs .tab[data-tab="snapshot"]')
      || document.querySelector('.tabs .tab[data-tab="compare-revisions"]');
    if (tab) {
      tab.dataset.tab = "snapshot";
      tab.textContent = "Modifications";
    }
    if (resolved === "pending") {
      const answer = $("#ai-snapshot-ai-answer");
      if (answer) answer.hidden = true;
    }
    syncAiSnapshotAskVisibility(false);
    const labelA = $("#ai-snapshot-label-a");
    const labelB = $("#ai-snapshot-label-b");
    const selectA = $("#ai-snapshot-rev-a");
    const selectB = $("#ai-snapshot-rev-b");
    if (resolved === "compare") {
      if (labelA) labelA.textContent = "OLD";
      if (labelB) labelB.textContent = "NEW";
      if (selectA) {
        selectA.disabled = false;
        selectA.setAttribute("aria-label", "OLD snapshot revision");
      }
      if (selectB) {
        selectB.disabled = false;
        selectB.setAttribute("aria-label", "NEW snapshot revision");
      }
      const copyA = $("#ai-snapshot-copy-a");
      if (copyA) copyA.title = "Copy OLD snapshot outline to the clipboard";
      const copyB = $("#ai-snapshot-copy-b");
      if (copyB) copyB.title = "Copy NEW snapshot outline to the clipboard";
    } else {
      if (labelA) labelA.textContent = "Checked in";
      if (labelB) labelB.textContent = "Not checked in";
      if (selectA) {
        selectA.disabled = true;
        selectA.setAttribute("aria-label", "Checked-in tip revision");
      }
      if (selectB) {
        selectB.disabled = true;
        selectB.setAttribute("aria-label", "Modified (not checked in)");
      }
      const copyA = $("#ai-snapshot-copy-a");
      if (copyA) copyA.title = "Copy checked-in outline to the clipboard";
      const copyB = $("#ai-snapshot-copy-b");
      if (copyB) copyB.title = "Copy workspace outline to the clipboard";
    }
  }

  function splitAiSnapshotLines(text) {
    return String(text || "")
      .replace(/\r\n/g, "\n")
      .replace(/\r/g, "\n")
      .split("\n");
  }

  function aiSnapshotLineIdentity(line) {
    /**
     * Compare / highlight key — Creo id wins.
     * Dim lines use dN (never the owning feature id in parentheses).
     * Feature / structure lines use the trailing `(146)` Creo feature id.
     */
    const text = String(line || "").trim();
    if (!text) return "";
    const dim = text.match(/^-\s*(d\d+)\b/i);
    if (dim) return `dim:${String(dim[1]).toLowerCase()}`;
    const param = text.match(/^-\s*([A-Za-z_][\w.]*)\s*=/);
    if (param) return `param:${String(param[1]).toUpperCase()}`;
    const ids = text.match(/\((\d+)\)/g);
    if (ids && ids.length) {
      const last = ids[ids.length - 1].replace(/\D/g, "");
      if (last) return `feat:${last}`;
    }
    return "";
  }

  function aiSnapshotLinesAlign(left, right) {
    if (left === right) return true;
    const key = aiSnapshotLineIdentity(left);
    return Boolean(key) && key === aiSnapshotLineIdentity(right);
  }

  function aiSnapshotAlignedOp(left, right) {
    if (left === right) return { type: "same", oldText: left, newText: right };
    return { type: "changed", oldText: left, newText: right };
  }

  function buildAiSnapshotLineDiff(oldLines, newLines) {
    /**
     * Side-by-side line ops (GitHub-style), aligned by Creo id / dim / param:
     * same | removed | added | changed (same id, different text).
     */
    const a = Array.isArray(oldLines) ? oldLines : [];
    const b = Array.isArray(newLines) ? newLines : [];
    const m = a.length;
    const n = b.length;
    const ops = [];
    if (m * n > 250_000) {
      const limit = Math.max(m, n);
      for (let i = 0; i < limit; i += 1) {
        const left = i < m ? a[i] : null;
        const right = i < n ? b[i] : null;
        if (left !== null && right !== null) {
          if (aiSnapshotLinesAlign(left, right)) {
            ops.push(aiSnapshotAlignedOp(left, right));
          } else {
            ops.push({ type: "removed", oldText: left, newText: "" });
            ops.push({ type: "added", oldText: "", newText: right });
          }
        } else if (left !== null) {
          ops.push({ type: "removed", oldText: left, newText: "" });
        } else {
          ops.push({ type: "added", oldText: "", newText: right });
        }
      }
      return ops;
    }
    const dp = Array.from({ length: m + 1 }, () => new Uint32Array(n + 1));
    for (let i = m - 1; i >= 0; i -= 1) {
      for (let j = n - 1; j >= 0; j -= 1) {
        dp[i][j] = aiSnapshotLinesAlign(a[i], b[j])
          ? dp[i + 1][j + 1] + 1
          : Math.max(dp[i + 1][j], dp[i][j + 1]);
      }
    }
    let i = 0;
    let j = 0;
    while (i < m && j < n) {
      if (aiSnapshotLinesAlign(a[i], b[j])) {
        ops.push(aiSnapshotAlignedOp(a[i], b[j]));
        i += 1;
        j += 1;
      } else if (dp[i + 1][j] >= dp[i][j + 1]) {
        ops.push({ type: "removed", oldText: a[i], newText: "" });
        i += 1;
      } else {
        ops.push({ type: "added", oldText: "", newText: b[j] });
        j += 1;
      }
    }
    while (i < m) {
      ops.push({ type: "removed", oldText: a[i], newText: "" });
      i += 1;
    }
    while (j < n) {
      ops.push({ type: "added", oldText: "", newText: b[j] });
      j += 1;
    }
    // Safety: same Creo id / dim / param in a remove+add run → yellow changed.
    // CUT (95) vs ROUND (146) stay red/blue — different ids.
    const merged = [];
    let k = 0;
    while (k < ops.length) {
      if (ops[k].type === "removed") {
        const removed = [];
        while (k < ops.length && ops[k].type === "removed") {
          removed.push(ops[k]);
          k += 1;
        }
        const added = [];
        while (k < ops.length && ops[k].type === "added") {
          added.push(ops[k]);
          k += 1;
        }
        const usedAdded = new Set();
        for (let r = 0; r < removed.length; r += 1) {
          const key = aiSnapshotLineIdentity(removed[r].oldText);
          let match = -1;
          if (key) {
            for (let aIdx = 0; aIdx < added.length; aIdx += 1) {
              if (usedAdded.has(aIdx)) continue;
              if (aiSnapshotLineIdentity(added[aIdx].newText) === key) {
                match = aIdx;
                break;
              }
            }
          }
          if (match >= 0) {
            usedAdded.add(match);
            merged.push(
              aiSnapshotAlignedOp(removed[r].oldText, added[match].newText)
            );
          } else {
            merged.push(removed[r]);
          }
        }
        for (let aIdx = 0; aIdx < added.length; aIdx += 1) {
          if (!usedAdded.has(aIdx)) merged.push(added[aIdx]);
        }
        continue;
      }
      merged.push(ops[k]);
      k += 1;
    }
    return merged;
  }

  function formatAiSnapshotDiffLine(kind, text, side) {
    /**
     * Git unified-diff markers (not outline bullets):
     *   " " context/same · "-" removed/old · "+" added/new
     * Changed (same id, different text): "-" on OLD, "+" on NEW.
     */
    const raw = text == null ? "" : String(text);
    if (kind === "empty" || raw === "") return "\u00a0";
    let marker = " ";
    if (kind === "removed") marker = "-";
    else if (kind === "added") marker = "+";
    else if (kind === "changed") marker = side === "new" ? "+" : "-";
    // Outline list lines: "- body" / "  - └ body" → swap bullet for marker.
    const list = raw.match(/^(\s*)-\s(.*)$/);
    if (list) return `${list[1]}${marker} ${list[2]}`;
    // Already a diff marker (re-paint / copy round-trip).
    const prior = raw.match(/^(\s*)([+\-])\s(.*)$/);
    if (prior) return `${prior[1]}${marker} ${prior[3]}`;
    if (kind === "same" || kind === "plain") return raw;
    return `${marker} ${raw}`;
  }

  function paintAiSnapshotLine(el, kind, text, side) {
    el.className = `ai-snapshot-line ai-snapshot-line--${kind}`;
    el.textContent = formatAiSnapshotDiffLine(kind, text, side);
  }

  function renderAiSnapshotDiffBodies(textA, textB) {
    const bodyA = $("#ai-snapshot-body-a");
    const bodyB = $("#ai-snapshot-body-b");
    if (!bodyA || !bodyB) return;
    const rows = buildAiSnapshotLineDiff(
      splitAiSnapshotLines(textA),
      splitAiSnapshotLines(textB)
    );
    const fragA = document.createDocumentFragment();
    const fragB = document.createDocumentFragment();
    rows.forEach((row) => {
      const elA = document.createElement("div");
      const elB = document.createElement("div");
      if (row.type === "same") {
        paintAiSnapshotLine(elA, "same", row.oldText, "old");
        paintAiSnapshotLine(elB, "same", row.newText, "new");
      } else if (row.type === "removed") {
        paintAiSnapshotLine(elA, "removed", row.oldText, "old");
        paintAiSnapshotLine(elB, "empty", "", "new");
      } else if (row.type === "added") {
        paintAiSnapshotLine(elA, "empty", "", "old");
        paintAiSnapshotLine(elB, "added", row.newText, "new");
      } else {
        paintAiSnapshotLine(elA, "changed", row.oldText, "old");
        paintAiSnapshotLine(elB, "changed", row.newText, "new");
      }
      fragA.appendChild(elA);
      fragB.appendChild(elB);
    });
    bodyA.replaceChildren(fragA);
    bodyB.replaceChildren(fragB);
  }

  function syncAiSnapshotScrollLayout() {
    const rail = $("#ai-snapshot-scroll");
    const spacer = $("#ai-snapshot-scroll-spacer");
    const bodyA = $("#ai-snapshot-body-a");
    const bodyB = $("#ai-snapshot-body-b");
    const clipA = $("#ai-snapshot-clip-a");
    if (!rail || !spacer || !bodyA || !bodyB) return;
    const viewH = clipA?.clientHeight || rail.clientHeight || 0;
    const contentH = Math.max(
      bodyA.scrollHeight || 0,
      bodyB.scrollHeight || 0,
      viewH
    );
    spacer.style.height = `${contentH}px`;
    applyAiSnapshotScrollOffset(rail.scrollTop || 0);
  }

  function applyAiSnapshotScrollOffset(top) {
    const y = -Math.max(0, Number(top) || 0);
    const bodyA = $("#ai-snapshot-body-a");
    const bodyB = $("#ai-snapshot-body-b");
    if (bodyA) bodyA.style.transform = `translateY(${y}px)`;
    if (bodyB) bodyB.style.transform = `translateY(${y}px)`;
  }

  function resetAiSnapshotScroll() {
    const rail = $("#ai-snapshot-scroll");
    if (rail) rail.scrollTop = 0;
    applyAiSnapshotScrollOffset(0);
    // Layout after paint so clip heights are real.
    requestAnimationFrame(() => syncAiSnapshotScrollLayout());
  }

  async function fetchAiSnapshotOutline(objectId, versionId) {
    const key = String(versionId || "");
    if (aiSnapshotOutlineByVersion.has(key)) {
      return aiSnapshotOutlineByVersion.get(key);
    }
    const response = await fetch(
      `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot?version=${encodeURIComponent(key)}`,
      { credentials: "same-origin", cache: "no-store" }
    );
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    const body = await response.json();
    const payload = body?.has_snapshot
      ? {
          outline: String(body.outline || "").trim(),
          displayRevision: String(body.display_revision || "").trim(),
        }
      : null;
    aiSnapshotOutlineByVersion.set(key, payload);
    return payload;
  }

  function setAiSnapshotPlainBody(body, copyBtn, text, copyable) {
    if (!body) return;
    body.replaceChildren();
    const el = document.createElement("div");
    el.className = "ai-snapshot-line ai-snapshot-line--plain";
    el.textContent = text;
    body.appendChild(el);
    if (copyBtn) {
      copyBtn.disabled = !copyable;
      if (copyable) copyBtn.dataset.copyText = text;
      else delete copyBtn.dataset.copyText;
    }
  }

  function fillAiSnapshotPendingSelects() {
    /**
     * Left = current tip History snap only (data-tip-version / A.1).
     * Right = Modified (not a History A.n). Never pick a newer snap for OLD.
     */
    const selectA = $("#ai-snapshot-rev-a");
    const selectB = $("#ai-snapshot-rev-b");
    const panel = aiSnapshotPanel();
    if (!selectA || !selectB || !aiSnapshotCompareVersions.length) return;
    const tipId = String(panel?.dataset.tipVersion || "").trim();
    // Pin to tip version when it has a snap; else newest snap (pending = usually one).
    const item =
      (tipId
        && aiSnapshotCompareVersions.find(
          (row) => String(row?.version_id || "") === tipId
        ))
      || aiSnapshotCompareVersions[0];
    selectA.replaceChildren();
    const optionA = document.createElement("option");
    optionA.value = String(item.version_id || "");
    optionA.textContent = String(item.display_revision || optionA.value);
    selectA.appendChild(optionA);
    selectA.value = optionA.value;
    selectB.replaceChildren();
    const optionB = document.createElement("option");
    optionB.value = AI_SNAPSHOT_MODIFIED_VALUE;
    optionB.textContent = "Modified";
    selectB.appendChild(optionB);
    selectB.value = AI_SNAPSHOT_MODIFIED_VALUE;
  }

  function setAiSnapshotPendingPlaceholder(body, copyBtn, message) {
    if (!body) return;
    body.replaceChildren();
    const box = document.createElement("div");
    box.className = "ai-snapshot-placeholder";
    box.textContent = String(message || "");
    body.appendChild(box);
    if (copyBtn) {
      copyBtn.disabled = true;
      delete copyBtn.dataset.copyText;
    }
  }

  function aiSnapshotPendingCleanPlaceholder() {
    return "No modifications to compare.";
  }

  function aiSnapshotPendingGatherFailedPlaceholder() {
    return (
      "Could not gather a live workspace outline.\n\n"
      + "Keep the model open in Creo (Connected), or Save so a local tip "
      + "is in the workspace, then reopen this tab."
    );
  }

  async function gatherLiveCompareNewSnapshot(panel) {
    /**
     * Tip snap is OLD; fresh session / latest local .N gather is NEW.
     * Hard refresh often opens Compare before Creo.JS is Connected — wait first.
     * Always resolve the highest Creo .N (base-plate.prt.6) for the disk path
     * and stamp that leaf into Model: … so the right pane shows the tip name.
     */
    const objectId = String(panel?.dataset.objectId || "").trim();
    const filename = String(panel?.dataset.filename || "").trim();
    const relativePath = String(panel?.dataset.relativePath || "")
      .trim()
      .replace(/\\/g, "/");
    if (!objectId || !filename) return null;
    const productId = aiSnapshotPanelProductId(panel);
    const panelVault = aiSnapshotPanelVaultFolder(panel);
    const openWs = $("#open-workspace-btn");
    if (openWs && panelVault) openWs.dataset.vaultFolder = panelVault;
    // Soft-nav / hard refresh: tab click runs before the bridge is live.
    await waitForCreoMetadataBridge({ tries: 48, intervalMs: 250 });
    if (checkinDialog) {
      checkinDialog.dataset.aiObjectId = objectId;
      checkinDialog.dataset.aiFilename = filename;
      checkinDialog.dataset.aiPath = relativePath;
      checkinDialog.dataset.aiNextDisplay =
        String(panel?.dataset.nextDisplay || "").trim() || "pending";
    }
    const pending = await resolvePendingCheckinLocalPath(objectId, filename, {
      productId,
      vaultFolder: panelVault,
      relativePath,
    });
    // Label the tip leaf only — do not mark Modified (clean rematerialize also has a .N).
    if (pending.diskName) {
      const selectB = $("#ai-snapshot-rev-b");
      if (selectB?.options?.length && isAiSnapshotModifiedValue(selectB.value)) {
        selectB.options[0].textContent = `Modified · ${pending.diskName}`;
      }
      if (pending.relative_path) {
        panel.dataset.relativePath = pending.relative_path;
      }
      panel.dataset.filename = pending.diskName;
    }
    const gatherName =
      pending.logicalName || logicalUploadName(filename) || filename;
    // Session when open (unsaved edits); else Retrieve the latest .N path.
    let snapshot = await gatherCreoMetadataForFilename(
      gatherName,
      pending.path || "",
      {
        featureNames: true,
        preferDisk: Boolean(pending.path),
      }
    );
    if (snapshot && snapshot.__error) snapshot = null;
    let gatherSource = "unknown";
    if (snapshot) {
      gatherSource = pending.path ? "session_or_disk" : "session";
    }
    if (!snapshot && pending.path) {
      snapshot = await gatherCreoMetadataForFilename(gatherName, pending.path, {
        featureNames: true,
        preferDisk: true,
      });
      if (snapshot && snapshot.__error) snapshot = null;
      if (snapshot) gatherSource = "disk";
    }
    if (!snapshot) return null;
    const body = aiSnapshotBodyFromGather(snapshot);
    if (!body) return null;
    // Show Model: base-plate.prt.6 (PART) — Creo identity is usually logical tip.
    try {
      if (!body.identity || typeof body.identity !== "object") body.identity = {};
      if (pending.diskName) {
        body.identity.filename = pending.diskName;
      }
      if (!body.capture || typeof body.capture !== "object") body.capture = {};
      body.capture.compare_source = gatherSource || "unknown";
      if (pending.diskName) body.capture.workspace_tip = pending.diskName;
    } catch {
      /* ignore */
    }
    return body;
  }

  async function postAiSnapshotOutline(objectId, snapshot, displayRevision) {
    const response = await fetch(
      `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/outline`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        cache: "no-store",
        body: JSON.stringify({
          snapshot,
          display_revision: displayRevision || "pending",
        }),
      }
    );
    if (!response.ok) throw new Error(await readError(response));
    const payload = await response.json();
    return {
      outline: String(payload?.outline || "").trim(),
      displayRevision: String(payload?.display_revision || displayRevision || "").trim(),
    };
  }

  function aiSnapshotPanelProductId(panel) {
    return (
      String(panel?.dataset.productId || "").trim()
      || currentProductId()
      || ""
    );
  }

  function aiSnapshotPanelVaultFolder(panel) {
    return (
      String(panel?.dataset.vaultFolder || "").trim()
      || currentVaultFolder()
      || aiSnapshotPanelProductId(panel)
    );
  }

  function markAiSnapshotPanelModified(panel, extras) {
    if (!panel) return;
    panel.setAttribute("data-modified-locally", "1");
    const info = extras && typeof extras === "object" ? extras : {};
    if (info.filename) {
      panel.dataset.filename = String(info.filename).trim();
    }
    if (info.relative_path || info.relativePath) {
      panel.dataset.relativePath = String(
        info.relative_path || info.relativePath || ""
      )
        .trim()
        .replace(/\\/g, "/");
    }
    const selectB = $("#ai-snapshot-rev-b");
    if (selectB && selectB.options.length) {
      const tip = String(info.filename || panel.dataset.filename || "").trim();
      const leaf = tip ? PathBasename(tip) : "";
      const modOpt = [...selectB.options].find((opt) =>
        isAiSnapshotModifiedValue(opt.value)
      );
      if (modOpt) {
        modOpt.textContent = leaf ? `Modified · ${leaf}` : "Modified";
      } else if (isAiSnapshotModifiedValue(selectB.value) || selectB.options.length === 1) {
        selectB.options[0].textContent = leaf ? `Modified · ${leaf}` : "Modified";
      }
    }
  }

  function clearAiSnapshotPanelModified(panel) {
    if (!panel) return;
    panel.setAttribute("data-modified-locally", "0");
    panel.setAttribute("data-workspace-pending", "0");
    const selectB = $("#ai-snapshot-rev-b");
    const modOpt = selectB
      ? [...selectB.options].find((opt) => isAiSnapshotModifiedValue(opt.value))
      : null;
    if (modOpt) modOpt.textContent = "Modified";
  }

  async function waitForCreoAgentReady({ tries = 24, intervalMs = 250 } = {}) {
    for (let i = 0; i < tries; i += 1) {
      try {
        if (await probeCreoAgent()) return true;
      } catch {
        /* retry */
      }
      await new Promise((resolve) => window.setTimeout(resolve, intervalMs));
    }
    return false;
  }

  function checkinQueueHitForObject(productId, objectId) {
    /**
     * Soft-nav from Files → Modified often still has the queue cache; Details
     * has no Modified tab badge, so cachedCheckinQueueParts() would reject it.
     */
    const id = String(objectId || "").trim();
    const pid = String(productId || "").trim();
    if (!id || !pid) return null;
    if (
      String(checkinQueueCache.productId || "") !== pid
      || !checkinQueueCache.at
    ) {
      return null;
    }
    const rows = [
      ...(Array.isArray(checkinQueueCache.saves) ? checkinQueueCache.saves : []),
      ...(Array.isArray(checkinQueueCache.newerLocal)
        ? checkinQueueCache.newerLocal
        : []),
    ];
    return (
      rows.find((item) => String(item?.uuid || "") === id) || null
    );
  }

  function vaultTipSaveNumber(obj) {
    if (!obj) return 0;
    const vaultRel = String(obj.relative_path || obj.filename || "").replace(
      /\\/g,
      "/"
    );
    return Math.max(
      creoSaveNumber(obj.filename || PathBasename(vaultRel)),
      creoSaveNumber(obj.current_version?.filename || ""),
      creoSaveNumber(PathBasename(vaultRel))
    );
  }

  async function refreshAiSnapshotPanelModifiedFlag(panel) {
    /**
     * Detect the same tip Files → Modified shows as "Newer local save"
     * (e.g. base-plate.prt.2). Prefer a higher Creo .N on disk; also hash
     * mismatch and vault checkin-queue. null from listAgentCacheFiles is not clean.
     * Details relies on body data-purgeable / defaultPurgeableExtensionSet so
     * creoSaveNumber recognizes .prt.2 without #metric-filters.
     */
    if (!panel) return false;
    const objectId = String(panel.dataset.objectId || "").trim();
    if (!objectId) return false;
    const productId = aiSnapshotPanelProductId(panel);
    if (!productId) {
      clearAiSnapshotPanelModified(panel);
      return false;
    }
    const openWs = $("#open-workspace-btn");
    const panelVault = aiSnapshotPanelVaultFolder(panel);
    if (openWs && panelVault) openWs.dataset.vaultFolder = panelVault;
    const wasPending = pendingCheckinIds.has(objectId);
    const stickyPending =
      wasPending || panel.getAttribute("data-workspace-pending") === "1";
    const cachedHit = checkinQueueHitForObject(productId, objectId);
    if (cachedHit) {
      markAiSnapshotPanelModified(panel, cachedHit);
      rememberPendingCheckinIds([objectId], { merge: true });
      return true;
    }
    await waitForCreoAgentReady();

    // Direct agent tip probe first — same leaf Modified tab lists.
    let agentListed = false;
    let workingVault = panelVault;
    try {
      const listed = await listAgentCacheFilesPreferringVault(
        productId,
        panelVault
      );
      agentListed = Boolean(listed.listed);
      workingVault = listed.vaultFolder || panelVault;
      const cacheFiles = Array.isArray(listed.files) ? listed.files : [];
      const objects = await ensureProductObjects(productId, { force: true });
      const obj = (objects || []).find(
        (row) => String(row?.uuid || "") === objectId
      );
      const latest = latestLocalCacheTipForObject(
        cacheFiles,
        objects,
        objectId
      );
      if (latest) {
        const vaultNumber = vaultTipSaveNumber(obj);
        // Higher on-disk .N than the checked-in tip (base-plate.prt.2) → live NEW.
        if (latest.saveNumber > vaultNumber) {
          markAiSnapshotPanelModified(panel, latest);
          rememberPendingCheckinIds([objectId], { merge: true });
          return true;
        }
      }
      const newer = (
        await resolveNewerLocalCacheSaves(
          cacheFiles,
          objects,
          productId,
          workingVault
        )
      ).find((item) => String(item?.uuid || "") === objectId);
      if (newer) {
        markAiSnapshotPanelModified(panel, newer);
        rememberPendingCheckinIds([objectId], { merge: true });
        return true;
      }
    } catch {
      /* agent optional */
    }

    try {
      const parts = await loadCheckinQueueParts(productId, workingVault);
      const hit = [...(parts.saves || []), ...(parts.newerLocal || [])].find(
        (item) => String(item?.uuid || "") === objectId
      );
      if (hit) {
        markAiSnapshotPanelModified(panel, hit);
        rememberPendingCheckinIds([objectId], { merge: true });
        return true;
      }
      if (parts.agentListed || agentListed) {
        clearAiSnapshotPanelModified(panel);
        return false;
      }
    } catch {
      /* queue optional */
    }

    if (agentListed) {
      clearAiSnapshotPanelModified(panel);
      return false;
    }
    if (stickyPending) {
      markAiSnapshotPanelModified(panel);
      return true;
    }
    clearAiSnapshotPanelModified(panel);
    return false;
  }

  async function renderAiSnapshotPending(objectId) {
    /**
     * Left = selected History snap (tip by default) — never a live gather.
     * Right = live workspace gather when Files would show Modified;
     * clean workspace → boxed placeholder (Creo session alone is not enough).
     */
    const panel = aiSnapshotPanel();
    const selectA = $("#ai-snapshot-rev-a");
    const bodyA = $("#ai-snapshot-body-a");
    const bodyB = $("#ai-snapshot-body-b");
    const copyA = $("#ai-snapshot-copy-a");
    const copyB = $("#ai-snapshot-copy-b");
    if (!selectA || !bodyA || !bodyB) return;

    const tipVersion = String(panel?.dataset.tipVersion || "").trim();
    const versionA = String(selectA.value || tipVersion || "").trim();
    const labelA = selectA.selectedOptions?.[0]?.textContent || versionA;
    aiSnapshotPendingGather = null;
    syncAiSnapshotAskVisibility(false);

    setAiSnapshotPlainBody(bodyA, copyA, "Loading…", false);
    setAiSnapshotPlainBody(bodyB, copyB, "Loading…", false);

    let textA = "";
    try {
      if (!versionA) {
        setAiSnapshotPlainBody(bodyA, copyA, "No snapshot yet.", false);
      } else {
        const rowA = await fetchAiSnapshotOutline(objectId, versionA);
        if (!rowA?.outline) {
          setAiSnapshotPlainBody(bodyA, copyA, aiSnapshotEmptyMessage(labelA), false);
        } else {
          textA = formatAiSnapshotOutlineDisplay(
            "OLD",
            rowA.displayRevision || labelA,
            rowA.outline
          );
        }
      }
    } catch (err) {
      setAiSnapshotPlainBody(
        bodyA,
        copyA,
        `Could not load snapshot (${err?.message || "error"}).`,
        false
      );
      setAiSnapshotPendingPlaceholder(
        bodyB,
        copyB,
        aiSnapshotPendingGatherFailedPlaceholder()
      );
      return;
    }

    // Re-probe Modified every open — sticky SSR / session gather must not fake dirtiness.
    let isModified = false;
    try {
      isModified = await refreshAiSnapshotPanelModifiedFlag(panel);
    } catch {
      isModified = false;
    }
    aiSnapshotIncludeModified = Boolean(isModified);

    if (!isModified) {
      if (textA) setAiSnapshotPlainBody(bodyA, copyA, textA, true);
      setAiSnapshotPendingPlaceholder(
        bodyB,
        copyB,
        aiSnapshotPendingCleanPlaceholder()
      );
      return;
    }

    try {
      const newer = await gatherLiveCompareNewSnapshot(panel);
      if (newer) {
        const rowB = await postAiSnapshotOutline(objectId, newer, "pending");
        if (rowB?.outline) {
          const textB = formatAiSnapshotOutlineDisplay(
            "NEW",
            "Modified",
            rowB.outline
          );
          if (!textA) {
            setAiSnapshotPlainBody(bodyB, copyB, textB, true);
            return;
          }
          renderAiSnapshotDiffBodies(textA, textB);
          if (copyA) {
            copyA.disabled = false;
            copyA.dataset.copyText = textA;
          }
          if (copyB) {
            copyB.disabled = false;
            copyB.dataset.copyText = textB;
          }
          aiSnapshotPendingGather = {
            snapshot: newer,
            displayRevision: "pending",
          };
          syncAiSnapshotAskVisibility(true);
          return;
        }
      }
    } catch (err) {
      if (textA) setAiSnapshotPlainBody(bodyA, copyA, textA, true);
      setAiSnapshotPendingPlaceholder(
        bodyB,
        copyB,
        `Could not build live workspace outline (${err?.message || "error"}).\n\n`
          + "Keep the model open in Creo (Connected), or Save a local tip, then retry."
      );
      return;
    }

    if (textA) setAiSnapshotPlainBody(bodyA, copyA, textA, true);
    setAiSnapshotPendingPlaceholder(
      bodyB,
      copyB,
      aiSnapshotPendingGatherFailedPlaceholder()
    );
  }

  async function renderAiSnapshotCompare(objectId) {
    /**
     * NEW = Modified → live gather; else History vs History.
     * Mode pending (one snap, clean/dirty) also uses the live path when B is Modified.
     */
    const selectB = $("#ai-snapshot-rev-b");
    const compare = $("#ai-snapshot-compare");
    const mode =
      String(compare?.dataset.mode || "compare") === "pending" ? "pending" : "compare";
    if (mode === "pending" || isAiSnapshotModifiedValue(selectB?.value)) {
      await renderAiSnapshotPending(objectId);
      return;
    }

    const selectA = $("#ai-snapshot-rev-a");
    const bodyA = $("#ai-snapshot-body-a");
    const bodyB = $("#ai-snapshot-body-b");
    const copyA = $("#ai-snapshot-copy-a");
    const copyB = $("#ai-snapshot-copy-b");
    if (!selectA || !selectB || !bodyA || !bodyB) return;

    const versionA = String(selectA.value || "").trim();
    const versionB = String(selectB.value || "").trim();
    const labelA = selectA.selectedOptions?.[0]?.textContent || versionA;
    const labelB = selectB.selectedOptions?.[0]?.textContent || versionB;

    if (!versionA || !versionB) {
      setAiSnapshotPlainBody(bodyA, copyA, versionA ? "Loading…" : "No revisions yet.", false);
      setAiSnapshotPlainBody(bodyB, copyB, versionB ? "Loading…" : "No revisions yet.", false);
      return;
    }

    setAiSnapshotPlainBody(bodyA, copyA, "Loading…", false);
    setAiSnapshotPlainBody(bodyB, copyB, "Loading…", false);

    const [resA, resB] = await Promise.allSettled([
      fetchAiSnapshotOutline(objectId, versionA),
      fetchAiSnapshotOutline(objectId, versionB),
    ]);
    const rowA = resA.status === "fulfilled" ? resA.value : null;
    const rowB = resB.status === "fulfilled" ? resB.value : null;
    const errA = resA.status === "rejected" ? resA.reason : null;
    const errB = resB.status === "rejected" ? resB.reason : null;

    if (errA) {
      setAiSnapshotPlainBody(
        bodyA,
        copyA,
        `Could not load snapshot (${errA?.message || "error"}).`,
        false
      );
    }
    if (errB) {
      setAiSnapshotPlainBody(
        bodyB,
        copyB,
        `Could not load snapshot (${errB?.message || "error"}).`,
        false
      );
    }
    if (errA || errB) return;

    if (!rowA || !rowA.outline) {
      setAiSnapshotPlainBody(bodyA, copyA, aiSnapshotEmptyMessage(labelA), false);
    }
    if (!rowB || !rowB.outline) {
      setAiSnapshotPlainBody(bodyB, copyB, aiSnapshotEmptyMessage(labelB), false);
    }
    if (!rowA?.outline || !rowB?.outline) return;

    const textA = formatAiSnapshotOutlineDisplay(
      "OLD",
      rowA.displayRevision || labelA,
      rowA.outline
    );
    const textB = formatAiSnapshotOutlineDisplay(
      "NEW",
      rowB.displayRevision || labelB,
      rowB.outline
    );
    renderAiSnapshotDiffBodies(textA, textB);
    if (copyA) {
      copyA.disabled = false;
      copyA.dataset.copyText = textA;
    }
    if (copyB) {
      copyB.disabled = false;
      copyB.dataset.copyText = textB;
    }
  }

  async function loadAiSnapshotTab() {
    const panel = aiSnapshotPanel();
    if (!panel) return;
    const objectId = String(panel.dataset.objectId || "").trim();
    if (!objectId) return;
    const selectA = $("#ai-snapshot-rev-a");
    const selectB = $("#ai-snapshot-rev-b");
    if (!selectA || !selectB) return;
    try {
      // Always refresh list + outlines when opening Modifications.
      clearAiSnapshotClientCache();
      {
        const response = await fetch(
          `/api/objects/${encodeURIComponent(objectId)}/ai-snapshots`
        );
        if (!response.ok) throw new Error(await readError(response));
        aiSnapshotListCache = await response.json();
      }
      const items = Array.isArray(aiSnapshotListCache?.items)
        ? aiSnapshotListCache.items
        : [];
      // API lists newest-first. Defaults: NEW = latest snap, OLD = one prior.
      // OLD dropdown never lists a revision newer than NEW (and vice versa).
      aiSnapshotCompareVersions = items.filter((item) => item && item.has_snapshot);
      let isModified = false;
      try {
        isModified = await refreshAiSnapshotPanelModifiedFlag(panel);
      } catch {
        isModified = false;
      }
      aiSnapshotIncludeModified = Boolean(isModified);
      const n = aiSnapshotCompareVersions.length;
      // Two+ History snaps, or one snap with live Modified → enabled OLD/NEW chrome.
      const mode =
        n >= 2 || (n >= 1 && isModified) ? "compare" : "pending";
      syncAiSnapshotTabChrome(mode);
      if (!n) {
        setAiSnapshotPlainBody(
          $("#ai-snapshot-body-a"),
          $("#ai-snapshot-copy-a"),
          "No snapshot yet. Collect metadata (or Check In / Open with Creo Connected) while this tip is current.",
          false
        );
        setAiSnapshotPendingPlaceholder(
          $("#ai-snapshot-body-b"),
          $("#ai-snapshot-copy-b"),
          aiSnapshotPendingCleanPlaceholder()
        );
        return;
      }
      const tipId = String(panel.dataset.tipVersion || "").trim();
      if (n >= 2) {
        if (isModified) {
          // Default NEW = Modified; OLD = tip History snap (e.g. A.2).
          fillAiSnapshotOrderedSelects(tipId, AI_SNAPSHOT_MODIFIED_VALUE, null);
        } else {
          fillAiSnapshotOrderedSelects(
            aiSnapshotCompareVersions[1]?.version_id,
            aiSnapshotCompareVersions[0]?.version_id,
            null
          );
        }
      } else if (isModified) {
        fillAiSnapshotOrderedSelects(tipId, AI_SNAPSHOT_MODIFIED_VALUE, null);
      } else {
        fillAiSnapshotPendingSelects();
      }
      await renderAiSnapshotCompare(objectId);
      resetAiSnapshotScroll();
    } catch (err) {
      const body = $("#ai-snapshot-body-a");
      if (body) {
        body.textContent = `Could not load snapshot list (${err?.message || "error"}).`;
      }
    }
  }

  async function copyTextToClipboard(text) {
    // Creo's embedded browser often lacks navigator.clipboard (or blocks it).
    // Prefer the Clipboard API, then execCommand('copy') via a temporary textarea.
    const value = String(text || "");
    if (!value) return false;
    if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
      try {
        await navigator.clipboard.writeText(value);
        return true;
      } catch {
        /* fall through to execCommand */
      }
    }
    try {
      const ta = document.createElement("textarea");
      ta.value = value;
      ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0;";
      document.body.appendChild(ta);
      ta.focus();
      ta.select();
      ta.setSelectionRange(0, value.length);
      const ok = document.execCommand("copy");
      document.body.removeChild(ta);
      return Boolean(ok);
    } catch {
      return false;
    }
  }

  async function askAiSnapshotCompare() {
    const panel = aiSnapshotPanel();
    const objectId = String(panel?.dataset.objectId || "").trim();
    const compare = $("#ai-snapshot-compare");
    const answerBox = $("#ai-snapshot-ai-answer");
    const answerBody = $("#ai-snapshot-ai-answer-body");
    const answerMeta = $("#ai-snapshot-ai-answer-meta");
    const mode = String(compare?.dataset.mode || "");
    if (!aiFeaturesEnabled()) {
      showError(
        $("#toolbar-error"),
        "AI features are turned off. Open System Settings → AI, check Enable AI features, and Save."
      );
      return;
    }
    if (!objectId || !compare) {
      showError($("#toolbar-error"), "Open Modifications first.");
      return;
    }
    showError($("#toolbar-error"), "");

    const postCompare = async (url, body) => {
      let response;
      try {
        response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          cache: "no-store",
          signal: abortSignalAfter(120_000),
          body: JSON.stringify(body),
        });
      } catch (errFetch) {
        const aborted =
          errFetch?.name === "AbortError"
          || /aborted|timeout/i.test(String(errFetch?.message || errFetch || ""));
        throw new Error(
          aborted
            ? "Ollama timed out after 2 minutes. Is it running on the CreoPDM server and is the model loaded?"
            : String(errFetch?.message || errFetch || "Could not reach CreoPDM for AI compare.")
        );
      }
      if (!response.ok) throw new Error(await readError(response));
      return response.json();
    };

    try {
      const payload = await withBusy("Asking AI what changed…", async () => {
        const olderId = String($("#ai-snapshot-rev-a")?.value || "").trim();
        const newerId = String($("#ai-snapshot-rev-b")?.value || "").trim();
        if (mode === "pending" || isAiSnapshotModifiedValue(newerId)) {
          const gather = aiSnapshotPendingGather;
          if (!gather?.snapshot) {
            throw new Error(
              "Gather a live workspace outline first (open the model in Creo or Save a local tip)."
            );
          }
          return postCompare(
            `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/compare-pending`,
            {
              newer_snapshot: gather.snapshot,
              newer_display_revision: gather.displayRevision || "Modified",
              older_version_id: olderId || null,
            }
          );
        }
        if (mode !== "compare") {
          throw new Error("Need two revisions with snapshots before asking AI what changed.");
        }
        if (!olderId || !newerId) {
          throw new Error("Choose older and newer snapshot revisions.");
        }
        if (olderId === newerId) {
          throw new Error("Pick two different revisions to compare.");
        }
        return postCompare(
          `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/compare`,
          {
            older_version_id: olderId,
            newer_version_id: newerId,
          }
        );
      });
      const summary = String(payload?.summary || "").trim();
      if (!summary) {
        showError($("#toolbar-error"), "Ollama returned an empty summary.");
        return;
      }
      if (answerBody) answerBody.textContent = summary;
      if (answerMeta) {
        const olderRev = String(payload?.older_display_revision || "").trim();
        const newerRev = String(payload?.newer_display_revision || "").trim();
        const model = String(payload?.model || "").trim();
        const parts = [];
        if (olderRev && newerRev) parts.push(`${olderRev} → ${newerRev}`);
        if (model) parts.push(model);
        answerMeta.textContent = parts.join(" · ");
      }
      if (answerBox) {
        answerBox.hidden = false;
        answerBox.scrollIntoView({ block: "nearest", behavior: "smooth" });
      }
    } catch (err) {
      showError(
        $("#toolbar-error"),
        String(err?.message || err || "Could not ask AI what changed.")
      );
    }
  }

  function bindAiSnapshotControls() {
    const panel = aiSnapshotPanel();
    if (!panel || panel.dataset.aiSnapshotBound === "1") return;
    panel.dataset.aiSnapshotBound = "1";
    const objectId = String(panel.dataset.objectId || "").trim();
    ["a", "b"].forEach((pane) => {
      $(`#ai-snapshot-rev-${pane}`)?.addEventListener("change", () => {
        const selectA = $("#ai-snapshot-rev-a");
        const selectB = $("#ai-snapshot-rev-b");
        fillAiSnapshotOrderedSelects(
          selectA?.value,
          selectB?.value,
          pane === "a" ? "old" : "new"
        );
        void renderAiSnapshotCompare(objectId).then(() => resetAiSnapshotScroll());
      });
      $(`#ai-snapshot-copy-${pane}`)?.addEventListener("click", async () => {
        const btn = $(`#ai-snapshot-copy-${pane}`);
        const body = $(`#ai-snapshot-body-${pane}`);
        let text = String(btn?.dataset.copyText || "").trim();
        if (!text && body) {
          text = String(body.textContent || "").trim();
        }
        if (!text) {
          showError($("#toolbar-error"), "Nothing to copy yet.");
          return;
        }
        const ok = await copyTextToClipboard(text);
        if (!ok) {
          showError(
            $("#toolbar-error"),
            "Could not copy outline. Select the text and use Ctrl+C."
          );
          return;
        }
        const label = pane === "a" ? "OLD outline" : "NEW outline";
        showOk(`Copied ${label}.`);
      });
    });
    const rail = $("#ai-snapshot-scroll");
    const compare = $("#ai-snapshot-compare");
    rail?.addEventListener("scroll", () => {
      applyAiSnapshotScrollOffset(rail.scrollTop || 0);
    });
    // Wheel over either text pane drives the center scrollbar only.
    const diffRow = $("#ai-snapshot-diff-row");
    diffRow?.addEventListener(
      "wheel",
      (event) => {
        if (!rail) return;
        if (Math.abs(event.deltaY) < Math.abs(event.deltaX)) return;
        event.preventDefault();
        rail.scrollTop += event.deltaY;
      },
      { passive: false }
    );
    window.addEventListener("resize", () => {
      syncAiSnapshotScrollLayout();
    });
    $("#ai-snapshot-ask-ai")?.addEventListener("click", () => {
      void askAiSnapshotCompare();
    });
  }

  bindAiSnapshotControls();

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
        // Top Level means no assembly parents — do not urge "open parents to capture".
        if (panel.dataset.topLevelAssembly === "1") {
          host.innerHTML =
            '<p class="muted">No parent assemblies (Top Level).</p>';
        } else {
          host.innerHTML =
            '<p class="muted">Not listed in any captured assembly/drawing BOM in this product yet. Open parent assemblies in Creo and Add or Check In to capture Where Used. (Vault byte-scan is skipped when the product has many assemblies, so the server stays responsive.)</p>';
        }
        return;
      }
      const rows = items
        .map((row) => {
          const href = productId
            ? `/products/${encodeURIComponent(productId)}/objects/${encodeURIComponent(row.object_id || "")}#where-used`
            : "#";
          const sub =
            row.relative_path && row.relative_path !== row.filename
              ? `<div class="muted small">${escapeHtml(row.relative_path)}</div>`
              : "";
          return `<tr>
            <td class="filename-cell"><a href="${href}">${escapeHtml(row.filename || "")}</a>${sub}</td>
            <td>${escapeHtml(row.type_label || "")}</td>
            <td>${escapeHtml(row.display_revision || "")}</td>
            <td>${escapeHtml(formatBomQty(row.quantity ?? 1))}</td>
            <td>${escapeHtml(row.dependency_type || "")}</td>
          </tr>`;
        })
        .join("");
      host.innerHTML = `<div class="table-wrap"><table class="grid inventory-table" id="where-used-table">
        <thead><tr><th>Filename</th><th>Type</th><th>Rev</th><th>Qty</th><th>Relation</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
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
  } else if (
    window.location.hash === "#snapshot"
    || window.location.hash === "#compare-revisions"
  ) {
    document.querySelector('.tab[data-tab="snapshot"]')?.click();
  } else if (window.location.hash === "#changes") {
    document.querySelector('.tab[data-tab="changes"]')?.click();
  } else if (window.location.hash === "#modified") {
    document.querySelector('.tab[data-tab="modified"]')?.click();
  } else if (window.location.hash === "#checked-out") {
    document.querySelector('.tab[data-tab="checked-out"]')?.click();
  } else {
    // Details tabs after Open metadata soft-refresh (#features, #parameters, …).
    const detailHash = String(window.location.hash || "").replace(/^#/, "").trim();
    if (
      detailHash
      && $("article.detail")
      && document.querySelector(`.tabs .tab[data-tab="${detailHash}"]`)
    ) {
      document.querySelector(`.tabs .tab[data-tab="${detailHash}"]`)?.click();
    }
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

  function syncAiSettingsOptions() {
    if (!settingsForm) return;
    const card = settingsForm.querySelector("#ai-ollama-settings");
    if (!card) return;
    const aiOn = Boolean(settingsForm.querySelector('[name="ai_enabled"]')?.checked);
    card.classList.toggle("is-disabled", !aiOn);
    if (aiOn) card.removeAttribute("aria-disabled");
    else card.setAttribute("aria-disabled", "true");
    card.querySelectorAll("input, textarea, select, button").forEach((el) => {
      el.disabled = !aiOn;
    });
  }

  settingsForm?.querySelector('[name="ai_enabled"]')?.addEventListener(
    "change",
    syncAiSettingsOptions
  );
  syncAiSettingsOptions();

  function prettyUnavailableSince(date = new Date()) {
    // Match format_local_pretty: Monday, July 23, 2026 at 5:30pm
    const days = [
      "Sunday",
      "Monday",
      "Tuesday",
      "Wednesday",
      "Thursday",
      "Friday",
      "Saturday",
    ];
    const months = [
      "January",
      "February",
      "March",
      "April",
      "May",
      "June",
      "July",
      "August",
      "September",
      "October",
      "November",
      "December",
    ];
    const hour = date.getHours();
    const minute = date.getMinutes();
    const hour12 = hour % 12 || 12;
    const ampm = hour < 12 ? "am" : "pm";
    return (
      `${days[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()} `
      + `at ${hour12}:${String(minute).padStart(2, "0")}${ampm}`
    );
  }

  function isStockUnavailableMessage(text, base) {
    const value = String(text || "").trim();
    const stock = String(base || "").trim();
    if (!value || !stock) return !value;
    if (value === stock) return true;
    return value.startsWith(`${stock}\n\nSince `);
  }

  function syncSiteAvailabilityOptions() {
    if (!settingsForm) return;
    const unavailableOn = Boolean(
      settingsForm.querySelector('input[name="site_availability"][value="unavailable"]')?.checked
    );
    const wrap = settingsForm.querySelector("#site-unavailable-message-wrap");
    const message = settingsForm.querySelector('[name="site_unavailable_message"]');
    if (wrap) {
      wrap.classList.toggle("is-disabled", !unavailableOn);
      if (unavailableOn) wrap.removeAttribute("aria-disabled");
      else wrap.setAttribute("aria-disabled", "true");
    }
    if (message) {
      message.disabled = !unavailableOn;
      // Fill the stock message with a pretty Since stamp when turning unavailable on.
      if (unavailableOn) {
        const base = message.getAttribute("data-default-base") || "";
        if (isStockUnavailableMessage(message.value, base)) {
          message.value = `${base}\n\nSince ${prettyUnavailableSince()}.`;
        }
      }
    }
  }

  function syncUnavailableAdminPill(unavailable) {
    // Settings save stays on this page — show/hide the top-bar pill without navigating.
    const pill = $("#site-unavailable-pill");
    if (!pill) return;
    pill.hidden = !unavailable;
  }

  settingsForm?.querySelectorAll('input[name="site_availability"]').forEach((radio) => {
    radio.addEventListener("change", syncSiteAvailabilityOptions);
  });
  syncSiteAvailabilityOptions();

  function splitExtensionList(raw) {
    return String(raw || "")
      .split(/[\s,;]+/)
      .map((item) => item.trim())
      .filter(Boolean);
  }

  function parseOptionalInt(raw, fallback) {
    const text = String(raw || "").trim();
    if (!text) return fallback;
    const parsed = Number.parseInt(text, 10);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  settingsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError($("#settings-error"), "");
    const ok = $("#settings-ok");
    if (ok) ok.hidden = true;
    // Hub section pages only send fields present on this form (partial PUT).
    const data = new FormData(settingsForm);
    const body = {};
    if (settingsForm.querySelector('[name="site_availability"]')) {
      body.site_availability = String(data.get("site_availability") || "available");
      const unavailableMessageEl = settingsForm.querySelector('[name="site_unavailable_message"]');
      // Read even when the message field is disabled for “available”.
      body.site_unavailable_message = String(unavailableMessageEl?.value || "").trim();
    }
    if (settingsForm.querySelector('[name="creo_open_mode"]')) {
      body.creo_open_mode = String(data.get("creo_open_mode") || "association");
      const jsLibraryInput = settingsForm.querySelector('[name="creo_js_library"]');
      // Read even when the nested Embedded fields are disabled for association mode.
      body.creo_js_library = jsLibraryInput
        ? String(jsLibraryInput.value || "").trim() || null
        : null;
    }
    if (settingsForm.querySelector('[name="workspace_root"]')) {
      body.workspace_root = String(data.get("workspace_root") || "").trim() || null;
    }
    if (settingsForm.querySelector('[name="cad_model_extensions"]')) {
      body.cad_model_extensions = splitExtensionList(data.get("cad_model_extensions"));
    }
    if (settingsForm.querySelector('[name="cad_models_extensions"]')) {
      body.cad_models_extensions = splitExtensionList(data.get("cad_models_extensions"));
    }
    if (settingsForm.querySelector('[name="document_extensions"]')) {
      body.document_extensions = splitExtensionList(data.get("document_extensions"));
    }
    if (settingsForm.querySelector('[name="cad_openable_extensions"]')) {
      body.cad_openable_extensions = splitExtensionList(data.get("cad_openable_extensions"));
    }
    if (settingsForm.querySelector('[name="cad_extensions"]')) {
      body.cad_extensions = splitExtensionList(data.get("cad_extensions"));
    }
    if (settingsForm.querySelector('[name="purgeable_extensions"]')) {
      body.purgeable_extensions = splitExtensionList(data.get("purgeable_extensions"));
    }
    if (settingsForm.querySelector('[name="ignore_patterns"]')) {
      body.ignore_patterns = splitExtensionList(data.get("ignore_patterns"));
    }
    if (settingsForm.querySelector('[name="database_url"]')) {
      body.database_url = String(data.get("database_url") || "").trim();
    }
    if (settingsForm.querySelector('[name="port"]')) {
      body.port = parseOptionalInt(data.get("port"), 0);
    }
    if (settingsForm.querySelector('[name="agent_base_url"]')) {
      body.agent_base_url = String(data.get("agent_base_url") || "").trim();
    }
    if (settingsForm.querySelector('[name="workspace_poll_interval_ms"]')) {
      body.workspace_poll_interval_ms = parseOptionalInt(
        data.get("workspace_poll_interval_ms"),
        5000
      );
    }
    if (settingsForm.querySelector('[name="workspace_poll_idle_minutes"]')) {
      body.workspace_poll_idle_minutes = parseOptionalInt(
        data.get("workspace_poll_idle_minutes"),
        10
      );
    }
    if (settingsForm.querySelector('[name="ai_enabled"]')) {
      // Checkbox omitted from FormData when unchecked — read .checked explicitly.
      body.ai_enabled = Boolean(
        settingsForm.querySelector('[name="ai_enabled"]')?.checked
      );
    }
    // Read .value (not FormData) so disabled Ollama fields still persist on Save.
    const ollamaUrl = settingsForm.querySelector('[name="ollama_base_url"]');
    if (ollamaUrl) {
      body.ollama_base_url = String(ollamaUrl.value || "").trim();
      body.ollama_model = String(
        settingsForm.querySelector('[name="ollama_model"]')?.value || ""
      ).trim();
    }
    const promptEl = settingsForm.querySelector('[name="snapshot_compare_prompt"]');
    if (promptEl) {
      body.snapshot_compare_prompt = String(promptEl.value || "");
    }
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
    const messageInput = settingsForm.querySelector('[name="site_unavailable_message"]');
    if (messageInput && saved?.site_unavailable_message) {
      messageInput.value = saved.site_unavailable_message;
    }
    if (Object.prototype.hasOwnProperty.call(body, "site_availability")) {
      syncUnavailableAdminPill(
        String(saved?.site_availability || body.site_availability || "") === "unavailable"
      );
    }
    if (Object.prototype.hasOwnProperty.call(body, "ai_enabled")) {
      const on = Boolean(
        saved && Object.prototype.hasOwnProperty.call(saved, "ai_enabled")
          ? saved.ai_enabled
          : body.ai_enabled
      );
      document.body.dataset.aiEnabled = on ? "1" : "0";
    }
    if (body.creo_open_mode) {
      syncCreoStatusPill(body.creo_open_mode);
    }
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
    const body = { type_labels };
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
  });

  const ollamaSettings = $("#ai-ollama-settings");
  function normalizeOllamaRoot(raw) {
    let text = String(raw || "").trim().replace(/\/+$/, "");
    if (!text) text = "http://127.0.0.1:11434";
    if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(text)) text = `http://${text}`;
    return text;
  }
  function applyOllamaModelOptions(select, models, previous, statusEl, note) {
    select.replaceChildren();
    if (!models.length) {
      const empty = document.createElement("option");
      empty.value = "";
      empty.textContent = "No models found — pull one in Ollama first";
      select.appendChild(empty);
      if (statusEl) statusEl.textContent = note || "Reached Ollama, but no models are installed.";
      return;
    }
    for (const name of models) {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name === previous ? `${name} (current)` : name;
      if (name === previous) option.selected = true;
      select.appendChild(option);
    }
    if (previous && !models.includes(previous)) {
      const keep = document.createElement("option");
      keep.value = previous;
      keep.textContent = `${previous} (saved — not on server)`;
      keep.selected = true;
      select.insertBefore(keep, select.firstChild);
    }
    if (statusEl) {
      statusEl.textContent =
        note ||
        `Connected — ${models.length} model${models.length === 1 ? "" : "s"}.`;
    }
  }
  async function listOllamaModelsFromBrowser(baseUrl) {
    // Ollama on the Creo PC is often reachable from this browser even when the
    // CreoPDM Linux host cannot resolve/route to that hostname.
    const root = normalizeOllamaRoot(baseUrl);
    const response = await fetch(`${root}/api/tags`, {
      cache: "no-store",
      mode: "cors",
    });
    if (!response.ok) {
      throw new Error(`Ollama returned HTTP ${response.status} for ${root}/api/tags`);
    }
    const payload = await response.json();
    const models = Array.isArray(payload?.models) ? payload.models : [];
    const names = [];
    const seen = new Set();
    for (const item of models) {
      const name = String(item?.name || item?.model || "").trim();
      if (!name || seen.has(name)) continue;
      seen.add(name);
      names.push(name);
    }
    names.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
    return { base_url: root, models: names };
  }
  async function refreshOllamaModels() {
    const urlInput = $("#ollama-base-url");
    const modelSelect = $("#ollama-model");
    const statusEl = $("#ollama-status");
    const refreshBtn = $("#ollama-refresh-models");
    if (!modelSelect || !urlInput) return;
    const baseUrl = String(urlInput.value || "").trim();
    const saved = String(modelSelect.dataset.savedModel || "").trim();
    const previous = String(modelSelect.value || "").trim() || saved;
    showError($("#settings-error"), "");
    if (statusEl) {
      statusEl.textContent = "Contacting Ollama via CreoPDM server…";
      statusEl.classList.remove("error");
    }
    if (refreshBtn) refreshBtn.disabled = true;
    let serverMessage = "";
    try {
      const qs = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
      const response = await fetch(`/api/settings/ai/ollama/models${qs}`, {
        credentials: "same-origin",
        cache: "no-store",
      });
      if (response.ok) {
        const payload = await response.json();
        const models = Array.isArray(payload?.models) ? payload.models.map(String) : [];
        applyOllamaModelOptions(
          modelSelect,
          models,
          previous,
          statusEl,
          `Server reached ${payload?.base_url || baseUrl} — ${models.length} model${models.length === 1 ? "" : "s"}.`
        );
        return;
      }
      serverMessage = (await readError(response)) || `Server probe failed (HTTP ${response.status}).`;
    } catch (err) {
      serverMessage = String(err?.message || err || "Server probe failed.");
    }
    if (statusEl) {
      statusEl.textContent = `${serverMessage} Trying this browser…`;
      statusEl.classList.remove("error");
    }
    try {
      const payload = await listOllamaModelsFromBrowser(baseUrl);
      applyOllamaModelOptions(
        modelSelect,
        payload.models,
        previous,
        statusEl,
        `Browser reached ${payload.base_url} — ${payload.models.length} model${payload.models.length === 1 ? "" : "s"} (CreoPDM server could not). Save still stores the URL for later server-side use.`
      );
    } catch (err) {
      const browserMessage = String(err?.message || err || "Browser could not reach Ollama.");
      const combined =
        `${serverMessage} Browser fallback also failed: ${browserMessage}. ` +
        "On the CreoPDM host, test: curl -sS -m 5 http://michael-desktop:11434/api/tags — " +
        "and on this PC: curl.exe -sS http://127.0.0.1:11434/api/tags";
      if (statusEl) {
        statusEl.textContent = combined;
        statusEl.classList.add("error");
      }
      showError($("#settings-error"), combined);
    } finally {
      if (refreshBtn) refreshBtn.disabled = false;
    }
  }
  $("#ollama-refresh-models")?.addEventListener("click", () => {
    void refreshOllamaModels();
  });
  if (ollamaSettings) {
    void refreshOllamaModels();
  }

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

  function rememberWatchView(overrides = {}) {
    // Soft reload / undo paths — only Files-page tabs; never overwrite from Details.
    if (overrides.tab != null) {
      persistListTabState(overrides.tab, overrides.ids);
    } else {
      persistListTabState(undefined, overrides.ids);
    }
    persistListSearchState();
  }
  function restoreWatchView() {
    // Details / Admin also boot after soft-nav — do not consume WATCH_KEY there
    // or Back to Files loses the Modified / New files tab.
    if (!document.querySelector("#object-table") || !isListPage) return;
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
    const tab = LIST_RESTORE_TABS.has(String(saved.tab || "")) ? String(saved.tab) : "";
    if (tab && tab !== "files") {
      document.querySelector(`.tabs .tab[data-tab="${tab}"]`)?.click();
    }
    // Search restore rewrites the Files tbody — skip folder-row selection when
    // a saved search will re-select after results load.
    let pendingSearch = null;
    try {
      pendingSearch = sessionStorage.getItem(LIST_SEARCH_KEY);
    } catch {
      pendingSearch = null;
    }
    if (pendingSearch) return;
    const wanted = new Set(saved.ids || []);
    if (wanted.size) {
      rows().forEach((row) => markRowSelected(row, wanted.has(row.dataset.uuid)));
      syncToolbar();
    }
  }
  restoreWatchView();
  void restoreListSearchState();

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
      // Never paint Modified / New files badges from poll estimates — a brief false
      // local/vault hit used to flash "· 1" then clear. Confirmed queue loads only.
      if (lastPendingCheckinCount === null || lastPendingCheckinCount !== pending) {
        lastPendingCheckinCount = pending;
        void refreshPendingCheckinIds(watchProductId);
      }
      // Local agent-cache saves do not change the vault stamp — refresh the open tab in place.
      const modCount =
        Number(data.pending_saves || 0) + Number(localPending.newerLocal || 0);
      const newCount =
        Number(data.new_files || 0) + Number(localPending.localNew || 0);
      const activeTab = activeListTab();
      if (activeTab === "changes") {
        const changesNeedsLoad =
          (lastChangesPending === null && newCount > 0)
          || (lastChangesPending !== null && newCount !== lastChangesPending);
        lastChangesPending = newCount;
        if (changesNeedsLoad && !changesReloadBusy) {
          changesReloadBusy = true;
          knownWorkspacePaths.at = 0;
          cachedProductObjects.at = 0;
          invalidateCheckinQueueCache();
          try {
            // Must hit the network — quiet cache reuse left "· 1" with an empty table.
            await loadChangesTab({ quiet: true, forceNetwork: true });
          } finally {
            changesReloadBusy = false;
          }
        }
      } else if (activeTab === "modified") {
        const modifiedNeedsLoad =
          (lastModifiedPending === null && modCount > 0)
          || (lastModifiedPending !== null && modCount !== lastModifiedPending);
        lastModifiedPending = modCount;
        if (modifiedNeedsLoad && !modifiedReloadBusy) {
          modifiedReloadBusy = true;
          knownWorkspacePaths.at = 0;
          cachedProductObjects.at = 0;
          invalidateCheckinQueueCache();
          try {
            await loadModifiedTab({ quiet: true, forceNetwork: true });
          } finally {
            modifiedReloadBusy = false;
          }
        }
      } else {
        const countsMoved =
          lastChangesPending !== newCount || lastModifiedPending !== modCount;
        lastChangesPending = newCount;
        lastModifiedPending = modCount;
        // Poll estimate moved — confirm with the full queue before touching badges.
        if (countsMoved) {
          knownWorkspacePaths.at = 0;
          cachedProductObjects.at = 0;
          invalidateCheckinQueueCache();
          void prefetchCheckinQueueParts(watchProductId);
        }
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
    // SSR may already show Modified · N / New files · N — warm lists before first click.
    const ssrMod = Number(checkinBtn?.dataset?.pendingSaves || 0);
    const ssrNew = Number(checkinBtn?.dataset?.newFiles || 0);
    if (ssrMod || ssrNew) void prefetchCheckinQueueParts(watchProductId);
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
    setBusy,
    setBusyMessage,
    forceClearBusy,
    invokeBusyCancel,
    recoverStuckBusyOverlay,
    awaitWhereUsedIndex,
    runUtilitiesRebuildWithWhereUsed,
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
  // Compact / Delete products are sync form POSTs (can take a while). Busy until navigate.
  if (!window.__creopdmUtilitiesBusyBound) {
    window.__creopdmUtilitiesBusyBound = true;
    origAddEventListener.call(
      document,
      "submit",
      (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement)) return;
        const select = form.querySelector('select[name="product_id"]');
        const label = select?.selectedOptions?.[0]?.textContent?.trim() || "product";
        let message = "";
        if (form.id === "utilities-compact-vault-form") {
          message = `Compacting vault history for ${label}…`;
        } else if (form.id === "utilities-rebuild-product-form") {
          // FormData reflects the selected radio at submit.
          const fd = new FormData(form);
          const action = String(fd.get("repair_action") || "");
          if (action === "rebuild_where_used") {
            // Never preventDefault without a runner — that made Run look like a no-op.
            const api = window.__creopdmSoftNavApi;
            const runner = api?.runUtilitiesRebuildWithWhereUsed;
            if (typeof runner === "function") {
              event.preventDefault();
              void runner(form);
              return;
            }
            // Fallback: let the normal POST run (server starts Where Used; no N of M overlay).
          }
          if (action === "rebuild") {
            message = `Rebuilding product database for ${label}…`;
          } else if (action === "clear_metadata") {
            message = `Deleting Creo metadata for ${label}…`;
          } else {
            message = `Repairing product database for ${label}…`;
          }
        } else if (form.id === "utilities-delete-products-form") {
          message = `Deleting product ${label}…`;
        } else {
          return;
        }
        const api = window.__creopdmSoftNavApi;
        if (api && typeof api.setBusy === "function") api.setBusy(message);
        else {
          const text = document.getElementById("busy-message");
          if (text) text.textContent = message;
          const overlay = document.getElementById("busy-overlay");
          if (overlay instanceof HTMLDialogElement && !overlay.open) overlay.showModal();
          document.body.classList.add("is-busy");
          document.body.setAttribute("aria-busy", "true");
        }
        const btn = form.querySelector('button[type="submit"]');
        if (btn instanceof HTMLButtonElement) btn.disabled = true;
      },
      true
    );
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

// Soft-nav may inject a newer /client/app.js after deploy — skip the auto hard
// boot so the caller can soft-boot and keep Creo.JS Connected.
if (!window.__creopdmSkipAutoBoot) {
  const tag = document.querySelector('script[src*="/client/app.js"]');
  if (tag?.getAttribute("src")) window.__creopdmAppJsSrc = tag.getAttribute("src");
  window.__creopdmBoot({ soft: false });
} else {
  window.__creopdmSkipAutoBoot = false;
}
