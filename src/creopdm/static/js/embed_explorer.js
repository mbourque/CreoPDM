/**
 * Compact Creo navigator explorer.
 * Open / Checkout / Check In go through CreoPDM + creopdm-agent — never Toolkit from the browser.
 */
(function () {
  "use strict";

  var root = document.getElementById("embed-explorer");
  if (!root) return;

  var treeEl = document.getElementById("ex-tree");
  var searchEl = document.getElementById("ex-search");
  var bannerEl = document.getElementById("ex-banner");
  var msgEl = document.getElementById("ex-msg");
  var menuEl = document.getElementById("ex-context-menu");
  var refreshBtn = document.getElementById("ex-refresh");
  var listErrorEl = document.getElementById("ex-list-error");
  var listErrorText = document.getElementById("ex-list-error-text");
  var retryBtn = document.getElementById("ex-retry");
  var typeToggleRoot = document.getElementById("ex-type-toggles");
  /** None pressed → show all. Any pressed → OR of those filters. */
  var typeFilters = {
    part: false,
    assembly: false,
    drawing: false,
    top_level: false,
  };
  /** Paths expanded only to reveal type/search matches — cleared when filters go off. */
  var filterAutoExpanded = Object.create(null);
  var topLevelAssemblyIds = Object.create(null);
  /** Skip soft-refresh rebuilds that would replace the row mid double-click. */
  var interactGraceUntil = 0;
  var softRefreshTimer = null;
  var lastPaintFingerprint = "";

  var productId = (root.getAttribute("data-product-uuid") || "").trim();
  var vaultFolder = (root.getAttribute("data-vault-folder") || "").trim();
  var initialFolder = (root.getAttribute("data-initial-folder") || "").trim();
  var focusUuid = (root.getAttribute("data-focus-uuid") || "").trim();
  var followActive = root.getAttribute("data-follow-active") === "1";
  var queryProduct = (root.getAttribute("data-query-product") || "").trim();
  var queryFile = (root.getAttribute("data-query-file") || "").trim();
  var queryFolder = (root.getAttribute("data-query-folder") || "").trim();
  // Same product_ui flags as Files (role ∩ lifecycle). Do not use lifecycle-only
  // allows_checkout — that wrongly showed Checkout when the role cannot.
  var allowsContent = root.getAttribute("data-allows-content") === "1";
  var showOpen = root.getAttribute("data-show-open") === "1";
  var showCheckout = root.getAttribute("data-show-checkout") === "1";
  var showUndo = root.getAttribute("data-show-undo") === "1";
  var showCheckin = root.getAttribute("data-show-checkin") === "1";
  var showRevise = root.getAttribute("data-show-revise") === "1";
  var showExport =
    root.getAttribute("data-show-export") === "1" ||
    root.getAttribute("data-can-export") === "1";
  var productNameEl = document.getElementById("ex-product-name");
  var productStateEl = document.getElementById("ex-product-state");

  function filesCtx() {
    var api = window.CreoPdmFilesContextMenu;
    if (!api || typeof api.capabilities !== "function") {
      throw new Error("files_context_menu.js failed to load (CreoPdmFilesContextMenu missing).");
    }
    return api;
  }

  var objects = [];
  var selected = null;
  var expanded = Object.create(null);
  var toolkitOk = false;
  var toolkitReason = "Checking local Toolkit…";
  var agentOnline = false;
  var busy = false;
  /** Same signal Files uses (checkin-preview object_ids) — objects.modified_locally is often stale. */
  var pendingCheckinIds = Object.create(null);
  var pendingCheckinSeq = 0;
  /** loading | ok | error — never show "no files yet" until ok with length 0. */
  var listState = "loading";
  var listError = "";
  var listLoadSeq = 0;
  var contextSeq = 0;
  /**
   * True after the first context sync. Toolkit opens the pane with ?file=&folder= (the
   * active model) — that only seeds the first load. Later polls must follow Files'
   * last-used product; the server prefers a file's product over last-used, so sending
   * file/folder on every poll pinned the pane to the product of the active model.
   */
  var contextSeeded = false;
  var syncingContext = false;
  /** Creo CEF often never fires focus/visibility when the pane stays loaded. */
  var followPollTimer = null;
  var FOLLOW_POLL_MS = 2000;
  var postHandoffRefreshTimers = [];

  function agentBase() {
    return (root.getAttribute("data-agent-base") || "http://127.0.0.1:8766").replace(/\/$/, "");
  }

  function agentHeaders(extra) {
    var headers = Object.assign({}, extra || {});
    var token = (root.getAttribute("data-agent-token") || "").trim();
    if (token) headers.Authorization = "Bearer " + token;
    return headers;
  }

  function pdmOrigin() {
    return window.location.origin;
  }

  function setMsg(text, kind) {
    if (!msgEl) return;
    msgEl.textContent = text || "";
    msgEl.classList.toggle("is-ok", kind === "ok");
    msgEl.classList.toggle("is-err", kind === "err");
  }

  function setBanner(text, isError) {
    if (!bannerEl) return;
    if (!text) {
      bannerEl.hidden = true;
      bannerEl.textContent = "";
      return;
    }
    bannerEl.hidden = false;
    bannerEl.textContent = text;
    bannerEl.classList.toggle("is-error", Boolean(isError));
  }

  function readError(response) {
    return response
      .json()
      .then(function (body) {
        if (body && body.error && body.error.message) return body.error.message;
        if (body && body.detail) {
          return typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
        }
        return "HTTP " + response.status;
      })
      .catch(function () {
        return "HTTP " + response.status;
      });
  }

  function iconKind(obj) {
    var typ = String(obj.object_type || "").toUpperCase();
    var ext = String(obj.extension || "").toLowerCase().replace(/^\./, "");
    var name = String(obj.filename || "").toLowerCase();
    if (typ === "CREO_ASSEMBLY" || ext === "asm" || /\.asm(\.\d+)?$/.test(name)) {
      return { kind: "assembly", file: "assembly.png", label: "Assembly" };
    }
    if (typ === "CREO_DRAWING" || ext === "drw" || /\.drw(\.\d+)?$/.test(name)) {
      return { kind: "drawing", file: "drawing.png", label: "Drawing" };
    }
    if (typ === "CREO_PART" || ext === "prt" || /\.prt(\.\d+)?$/.test(name)) {
      return { kind: "part", file: "part.png", label: "Part" };
    }
    return { kind: "other", file: "file.svg", label: "File" };
  }

  function readTopLevelAssemblyIds(raw) {
    var next = Object.create(null);
    String(raw || "")
      .split(",")
      .forEach(function (item) {
        var id = String(item || "").trim();
        if (id) next[id] = true;
      });
    topLevelAssemblyIds = next;
  }

  function setTopLevelAssemblyIds(ids) {
    var next = Object.create(null);
    (ids || []).forEach(function (item) {
      var id = String(item || "").trim();
      if (id) next[id] = true;
    });
    topLevelAssemblyIds = next;
    root.setAttribute("data-top-level-assemblies", Object.keys(next).join(","));
  }

  function isTopLevelAssembly(obj) {
    if (!obj || !obj.uuid) return false;
    return Boolean(topLevelAssemblyIds[String(obj.uuid)]);
  }

  function anyTypeFilterOn() {
    return Boolean(
      typeFilters.top_level ||
        typeFilters.part ||
        typeFilters.assembly ||
        typeFilters.drawing
    );
  }

  function matchesTypeFilter(obj) {
    // Top Level wins alone — exclusive mode, ignore part/asm/drw.
    if (typeFilters.top_level) return isTopLevelAssembly(obj);
    if (!typeFilters.part && !typeFilters.assembly && !typeFilters.drawing) {
      return true;
    }
    return Boolean(typeFilters[iconKind(obj).kind]);
  }

  function syncTypeToggleButtons() {
    if (!typeToggleRoot) return;
    typeToggleRoot.querySelectorAll(".ex-type-toggle[data-type]").forEach(function (btn) {
      var key = String(btn.getAttribute("data-type") || "");
      var on = Boolean(typeFilters[key]);
      btn.setAttribute("aria-pressed", on ? "true" : "false");
      btn.classList.toggle("is-on", on);
    });
  }

  function ensureFilterExpandedPath(folderPath) {
    var parts = String(folderPath || "")
      .split("/")
      .filter(Boolean);
    var acc = [];
    parts.forEach(function (part) {
      acc.push(part);
      var path = acc.join("/");
      if (!expanded[path]) {
        expanded[path] = true;
        filterAutoExpanded[path] = true;
      }
    });
  }

  function clearFilterAutoExpanded() {
    Object.keys(filterAutoExpanded).forEach(function (path) {
      if (filterAutoExpanded[path]) delete expanded[path];
    });
    filterAutoExpanded = Object.create(null);
  }

  function toggleTypeFilter(key) {
    if (!Object.prototype.hasOwnProperty.call(typeFilters, key)) return;
    var wasOn = anyTypeFilterOn();
    if (key === "top_level") {
      // Exclusive: Top Level clears type filters and only shows WU roots.
      var next = !typeFilters.top_level;
      typeFilters.part = false;
      typeFilters.assembly = false;
      typeFilters.drawing = false;
      typeFilters.top_level = next;
    } else {
      // Type filters clear exclusive Top Level.
      typeFilters.top_level = false;
      typeFilters[key] = !typeFilters[key];
    }
    // Turning the last filter off: collapse paths we only opened for the filter
    // (left expanded, double-click Open kept missing the same row).
    if (wasOn && !anyTypeFilterOn()) clearFilterAutoExpanded();
    syncTypeToggleButtons();
    if (listState === "ok") renderTree();
  }

  function tipCanCheckin(obj) {
    // Files rows use data-can-checkin; owned + show_checkin is the same eligibility.
    return Boolean(obj && (obj.can_checkin || (obj.owned_by_me && showCheckin)));
  }

  function tipHasCheckinWork(obj) {
    // Match Files rowHasCheckinWork: eligible + (server Modified or pending set).
    if (!obj || !obj.uuid || !tipCanCheckin(obj)) return false;
    if (obj.modified_locally) return true;
    return Boolean(pendingCheckinIds[String(obj.uuid)]);
  }

  function localCachePendingApi() {
    var api = window.CreoPdmLocalCachePending;
    if (!api || typeof api.resolvePendingCheckinUuids !== "function") {
      throw new Error("local_cache_pending.js failed to load.");
    }
    return api;
  }

  function purgeableFromDom() {
    return (root.getAttribute("data-purgeable") || "").trim();
  }

  async function listAgentCacheFiles(vaultOverride) {
    // No short abort — large workspaces can take longer than Files' list (Files has none).
    var params = new URLSearchParams({ product_id: productId });
    var vault = String(vaultOverride || vaultFolder || "").trim();
    if (vault) params.set("vault_folder", vault);
    var response = await fetch(agentBase() + "/files?" + params.toString(), {
      headers: agentHeaders(),
    });
    if (!response.ok) return null;
    var body = await response.json();
    return body && Array.isArray(body.files) ? body.files : null;
  }

  async function listAgentCacheFilesPreferringVault() {
    var candidates = [];
    [vaultFolder, productId].forEach(function (item) {
      var key = String(item || "").trim();
      if (key && candidates.indexOf(key) < 0) candidates.push(key);
    });
    var lastEmpty = null;
    var i;
    for (i = 0; i < candidates.length; i += 1) {
      var files = await listAgentCacheFiles(candidates[i]);
      if (files == null) continue;
      if (files.length) return { files: files, vaultFolder: candidates[i] };
      lastEmpty = { files: files, vaultFolder: candidates[i] };
    }
    return lastEmpty || { files: [], vaultFolder: vaultFolder || "" };
  }

  async function hashAgentCachePaths(relativePaths, vaultOverride) {
    var paths = [];
    var seen = Object.create(null);
    (relativePaths || []).forEach(function (item) {
      var rel = String(item || "")
        .replace(/\\/g, "/")
        .replace(/^\/+/, "");
      if (!rel || seen[rel.toLowerCase()]) return;
      seen[rel.toLowerCase()] = true;
      paths.push(rel);
    });
    var byPath = Object.create(null);
    if (!productId || !paths.length) return byPath;
    var vault = String(vaultOverride || vaultFolder || "").trim();
    var response = await fetch(agentBase() + "/hash-paths", {
      method: "POST",
      headers: agentHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({
        product_id: productId,
        vault_folder: vault,
        relative_paths: paths,
      }),
    });
    if (!response.ok) return byPath;
    var body = await response.json();
    (body && Array.isArray(body.files) ? body.files : []).forEach(function (item) {
      if (!item || !item.ok) return;
      var rel = String(item.relative_path || "").replace(/\\/g, "/");
      var hash = String(item.content_hash || "").trim().toLowerCase();
      if (rel && hash) byPath[rel.toLowerCase()] = hash;
    });
    return byPath;
  }

  async function mergeAgentPendingCheckinIds(into) {
    // Same algorithm as Files (shared local_cache_pending.js) — no Files handoff.
    if (!productId || !into) return;
    agentOnline = await probeAgent();
    if (!agentOnline) return;
    try {
      var listed = await listAgentCacheFilesPreferringVault();
      if (!listed.files || !listed.files.length) return;
      var listedVault = listed.vaultFolder || vaultFolder || "";
      // Match Files eligibility: can_checkin, or owned + product show_checkin.
      var tips = (objects || []).map(function (obj) {
        if (!obj || Boolean(obj.can_checkin) === tipCanCheckin(obj)) return obj;
        return Object.assign({}, obj, { can_checkin: tipCanCheckin(obj) });
      });
      var uuids = await localCachePendingApi().resolvePendingCheckinUuids(
        listed.files,
        tips,
        function (paths) {
          return hashAgentCachePaths(paths, listedVault);
        },
        { purgeable: purgeableFromDom() }
      );
      (uuids || []).forEach(function (id) {
        var key = String(id || "").trim();
        if (key) into[key] = true;
      });
    } catch (err) {
      /* agent offline / old agent — keep server pending set */
    }
  }

  async function refreshPendingCheckinIds() {
    if (!productId) {
      pendingCheckinIds = Object.create(null);
      return;
    }
    var seq = ++pendingCheckinSeq;
    var next = Object.create(null);
    // Agent first — navigator must not depend on Files having opened.
    await mergeAgentPendingCheckinIds(next);
    if (seq !== pendingCheckinSeq) return;
    try {
      var response = await fetch(
        "/api/products/" +
          encodeURIComponent(productId) +
          "/checkin-preview?_=" +
          String(Date.now()),
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json" },
        }
      );
      if (seq !== pendingCheckinSeq) return;
      if (response.ok) {
        var data = await response.json();
        if (seq !== pendingCheckinSeq) return;
        (data.object_ids || []).forEach(function (id) {
          var key = String(id || "").trim();
          if (key) next[key] = true;
        });
      }
    } catch (err) {
      if (seq !== pendingCheckinSeq) return;
    }
    if (seq !== pendingCheckinSeq) return;
    pendingCheckinIds = next;
  }

  function rowStateFromObject(obj) {
    if (!obj) return null;
    return {
      uuid: String(obj.uuid || "").trim(),
      relativePath: String(obj.relative_path || "").trim(),
      canCheckout: Boolean(obj.can_checkout),
      owned: Boolean(obj.owned_by_me),
      canCheckin: tipCanCheckin(obj),
      localCache: false,
      isNewFile: false,
      hasDetails: Boolean(obj.uuid && productId),
      hasCheckinWork: tipHasCheckinWork(obj),
      isFolder: false,
      // Role and product state (show_revise), Released and not checked out (obj.can_revise).
      canRevise: showRevise && Boolean(obj.can_revise),
    };
  }

  function menuCapabilitiesFor(obj) {
    var row = rowStateFromObject(obj);
    return filesCtx().capabilities({
      rows: row ? [row] : [],
      showOpen: showOpen,
      showCheckout: showCheckout,
      showUndo: showUndo,
      showCheckin: showCheckin,
      showExportObjects: showExport,
      canViewObjects: true,
      allowsContent: allowsContent,
      canOfferAdd: false,
      canDiscardLocalControl: false,
      busy: busy,
    });
  }

  function canOfferOpen(obj) {
    // Same Open rule as Files RMB (shared files_context_menu.js).
    return menuCapabilitiesFor(obj).canOpen;
  }

  function folderOf(relative) {
    var path = String(relative || "").replace(/\\/g, "/");
    var idx = path.lastIndexOf("/");
    return idx < 0 ? "" : path.slice(0, idx);
  }

  function setListErrorVisible(show, message) {
    if (!listErrorEl) return;
    listErrorEl.hidden = !show;
    if (listErrorText && message) listErrorText.textContent = message;
    if (treeEl) treeEl.hidden = Boolean(show);
  }

  function abortAfter(ms) {
    var controller = new AbortController();
    window.setTimeout(function () {
      try {
        controller.abort();
      } catch (err) {
        /* ignore */
      }
    }, ms);
    return controller.signal;
  }

  function probeAgent() {
    return fetch(agentBase() + "/health", { signal: abortAfter(2500) })
      .then(function (res) {
        return res.ok;
      })
      .catch(function () {
        return false;
      });
  }

  function probeToolkit() {
    return fetch(agentBase() + "/toolkit/health", {
      headers: agentHeaders(),
      signal: abortAfter(4000),
    })
      .then(function (res) {
        if (!res.ok) {
          return readError(res).then(function (detail) {
            return { ok: false, reason: detail || "Toolkit health failed." };
          });
        }
        return res.json().then(function (body) {
          if (body && body.ok === false) {
            return { ok: false, reason: "Toolkit reported not ok." };
          }
          return { ok: true, reason: "" };
        });
      })
      .catch(function (err) {
        return {
          ok: false,
          reason:
            "Local Toolkit unreachable via creopdm-agent (" +
            String(err && err.message ? err.message : err) +
            ").",
        };
      });
  }

  async function refreshConnectivity() {
    agentOnline = await probeAgent();
    if (!agentOnline) {
      toolkitOk = false;
      toolkitReason = "Start creopdm-agent on this PC (Download / Check In and main-browser Open need it).";
      setBanner(toolkitReason, true);
      syncActionButtons();
      return;
    }
    var tk = await probeToolkit();
    toolkitOk = Boolean(tk.ok);
    toolkitReason = tk.reason || "Creo Toolkit Companion is not reachable on 127.0.0.1:8767.";
    if (!toolkitOk) {
      setBanner(
        "Toolkit offline: " +
          toolkitReason +
          " List/search still work; Open in the main browser may need Toolkit /url.",
        true
      );
    } else {
      setBanner("");
    }
    syncActionButtons();
  }

  function matchesQuery(obj, q) {
    // Same matcher as Files (files_search_match.js) — wildcards / ^ $ / type labels.
    var api = window.CreoPdmFilesSearchMatch;
    if (!api || typeof api.objectMatchesSearchQuery !== "function") {
      throw new Error("files_search_match.js failed to load.");
    }
    return api.objectMatchesSearchQuery(obj, q || "");
  }

  function buildTree(list) {
    var rootNode = { name: "", path: "", folders: Object.create(null), files: [] };
    list.forEach(function (obj) {
      var rel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      var parts = rel.split("/").filter(Boolean);
      if (!parts.length) return;
      var cursor = rootNode;
      var pathAcc = [];
      for (var i = 0; i < parts.length - 1; i += 1) {
        pathAcc.push(parts[i]);
        var key = parts[i];
        if (!cursor.folders[key]) {
          cursor.folders[key] = {
            name: key,
            path: pathAcc.join("/"),
            folders: Object.create(null),
            files: [],
          };
        }
        cursor = cursor.folders[key];
      }
      cursor.files.push(obj);
    });
    return rootNode;
  }

  function ensureExpandedPath(folderPath) {
    var parts = String(folderPath || "")
      .split("/")
      .filter(Boolean);
    var acc = [];
    parts.forEach(function (part) {
      acc.push(part);
      expanded[acc.join("/")] = true;
    });
  }

  function renderTree() {
    if (!treeEl || !productId) return;
    treeEl.setAttribute("data-list-state", listState);
    if (listState === "loading") {
      setListErrorVisible(false);
      treeEl.hidden = false;
      treeEl.innerHTML = '<p class="ex-loading" id="ex-loading">Loading files…</p>';
      return;
    }
    if (listState === "error") {
      setListErrorVisible(true, listError || "Could not load files.");
      return;
    }
    setListErrorVisible(false);
    treeEl.hidden = false;
    var q = (searchEl && searchEl.value ? searchEl.value : "").trim();
    var typeOn = anyTypeFilterOn();
    var filtered = objects.filter(function (obj) {
      return matchesQuery(obj, q) && matchesTypeFilter(obj);
    });
    // Search or type filter: expand ancestor folders so matches are visible.
    // Track auto-expands separately so clearing filters can collapse them again.
    if (q || typeOn) {
      filtered.forEach(function (obj) {
        ensureFilterExpandedPath(folderOf(obj.relative_path));
      });
    } else if (!q) {
      // Search cleared with no type filter — drop search-only auto-expands too.
      clearFilterAutoExpanded();
    }
    var tree = buildTree(filtered);
    treeEl.innerHTML = "";
    // Open from expanded{} only (ensureFilterExpandedPath already filled it).
    // Do not force-open with || typeOn — that left folders stuck open and made
    // click targets drift so double-click Open missed the file row.
    appendFolderKids(treeEl, tree, 0, false);
    // Empty copy only after a successful list response (listState === "ok").
    if (!filtered.length) {
      var empty = document.createElement("p");
      empty.className = "ex-empty";
      empty.textContent =
        q || typeOn ? "No matching files." : "This product has no files yet.";
      treeEl.appendChild(empty);
    }
  }

  function appendFolderKids(parent, node, depth, q) {
    var folderNames = Object.keys(node.folders).sort(function (a, b) {
      return a.localeCompare(b, undefined, { sensitivity: "base" });
    });
    folderNames.forEach(function (name) {
      var folder = node.folders[name];
      var open = Boolean(expanded[folder.path]) || Boolean(q);
      var row = document.createElement("button");
      row.type = "button";
      row.className = "ex-node";
      row.style.paddingLeft = 0.35 + depth * 0.75 + "rem";
      row.setAttribute("data-folder", folder.path);
      row.innerHTML =
        '<span class="ex-twist">' +
        (open ? "▼" : "▶") +
        '</span><span class="ex-folder-glyph" aria-hidden="true"></span><span class="ex-name"></span>';
      row.querySelector(".ex-name").textContent = folder.name;
      row.addEventListener("click", function () {
        expanded[folder.path] = !expanded[folder.path];
        renderTree();
      });
      parent.appendChild(row);
      var kids = document.createElement("div");
      kids.className = "ex-folder-kids";
      kids.hidden = !open;
      parent.appendChild(kids);
      if (open) appendFolderKids(kids, folder, depth + 1, q);
    });

    node.files
      .slice()
      .sort(function (a, b) {
        return String(a.filename || "").localeCompare(String(b.filename || ""), undefined, {
          sensitivity: "base",
        });
      })
      .forEach(function (obj) {
        var icon = iconKind(obj);
        var row = document.createElement("button");
        row.type = "button";
        row.className = "ex-node";
        row.style.paddingLeft = 0.35 + depth * 0.75 + "rem";
        row.setAttribute("data-uuid", obj.uuid || "");
        if (selected && selected.uuid === obj.uuid) row.classList.add("is-selected");
        if (focusUuid && focusUuid === obj.uuid) row.classList.add("is-focus");
        var badges = "";
        if (obj.owned_by_me || obj.checkout_user) {
          badges += '<span class="ex-badge co" title="Checked out">CO</span>';
        }
        if (tipHasCheckinWork(obj)) {
          badges += '<span class="ex-badge mod" title="Modified">MOD</span>';
        }
        row.innerHTML =
          '<span class="ex-twist is-leaf">•</span><img class="ex-icon" src="/static/icons/' +
          icon.file +
          '" alt="' +
          icon.label +
          '"><span class="ex-name"></span><span class="ex-badges">' +
          badges +
          "</span>";
        row.querySelector(".ex-name").textContent = obj.filename || obj.name || "file";
        row.title =
          (obj.relative_path || obj.filename || "") + " — double-click to Open";
        row.addEventListener("click", function () {
          noteUserInteract();
          // Soft-select only — never renderTree() here (that kills dblclick).
          selectObject(obj);
        });
        row.addEventListener("dblclick", function (ev) {
          ev.preventDefault();
          noteUserInteract();
          selected = obj;
          paintSelection();
          void onOpen();
        });
        row.addEventListener("contextmenu", function (ev) {
          noteUserInteract();
          onFileContextMenu(ev, obj);
        });
        parent.appendChild(row);
      });
  }

  function noteUserInteract() {
    // Hold off soft-refresh tree rebuilds while the user is clicking / opening.
    interactGraceUntil = Date.now() + 800;
  }

  function paintSelection() {
    if (!treeEl) return;
    var selId = selected && selected.uuid ? String(selected.uuid) : "";
    treeEl.querySelectorAll(".ex-node[data-uuid]").forEach(function (row) {
      var id = String(row.getAttribute("data-uuid") || "");
      row.classList.toggle("is-selected", Boolean(selId) && id === selId);
    });
  }

  function selectObject(obj) {
    selected = obj;
    paintSelection();
  }

  function objectsPaintFingerprint() {
    var pending = Object.keys(pendingCheckinIds)
      .sort()
      .join(",");
    var rows = (objects || [])
      .map(function (o) {
        if (!o) return "";
        return [
          o.uuid || "",
          o.filename || "",
          o.checkout_user || "",
          o.owned_by_me ? "1" : "0",
          tipHasCheckinWork(o) ? "1" : "0",
        ].join(":");
      })
      .join("|");
    return rows + "#" + pending;
  }

  function menuCapabilities() {
    // Shared with Files — files_context_menu.js (do not fork hide rules).
    return menuCapabilitiesFor(selected);
  }

  function ensureContextMenu() {
    if (!menuEl) return null;
    filesCtx().ensureItems(menuEl, { itemClass: "ex-menu-item", idPrefix: "" });
    menuEl.dataset.ready = "1";
    return menuEl;
  }

  function closeContextMenu() {
    if (menuEl) menuEl.hidden = true;
  }

  function positionContextMenu(menu, clientX, clientY) {
    menu.hidden = false;
    menu.style.left = "0px";
    menu.style.top = "0px";
    var rect = menu.getBoundingClientRect();
    var pad = 8;
    var left = clientX;
    var top = clientY;
    if (left + rect.width > window.innerWidth - pad) {
      left = Math.max(pad, window.innerWidth - rect.width - pad);
    }
    if (top + rect.height > window.innerHeight - pad) {
      top = Math.max(pad, window.innerHeight - rect.height - pad);
    }
    menu.style.left = left + "px";
    menu.style.top = top + "px";
  }

  function openContextMenu(clientX, clientY) {
    var api = filesCtx();
    var caps = menuCapabilities();
    if (!api.anyVisible(caps)) return false;
    var menu = ensureContextMenu();
    if (!menu) return false;
    api.applyVisibility(menu, caps);
    positionContextMenu(menu, clientX, clientY);
    return true;
  }

  function onFileContextMenu(ev, obj) {
    ev.preventDefault();
    ev.stopPropagation();
    selectObject(obj);
    var x = ev.clientX;
    var y = ev.clientY;
    // Refresh pending Modified set before hide rules (same signals as Files).
    void refreshPendingCheckinIds().then(function () {
      if (selected !== obj) return;
      // Paint MOD badge from the fresh pending set, then show matching RMB.
      renderTree();
      if (!openContextMenu(x, y)) closeContextMenu();
    });
  }

  function runContextAction(action) {
    closeContextMenu();
    var api = filesCtx();
    // Every Files RMB action needs the main embedded browser (dialogs / toolbar).
    if (api.needsEmbeddedBrowser(action)) {
      if (action === "details") {
        void onDetails();
        return;
      }
      void openInMainEmbeddedBrowser(filesDeepLink(action));
      return;
    }
  }

  function syncActionButtons() {
    /* Bottom Open/Checkout/Check In removed — actions live on RMB + double-click. */
  }

  function applyProductChrome(product, stateKey, stateLabel) {
    var name = product && product.name ? product.name : "No product";
    if (productNameEl) {
      productNameEl.textContent = name;
      productNameEl.title = name;
    }
    if (productStateEl) {
      if (stateLabel) {
        productStateEl.hidden = false;
        productStateEl.textContent = stateLabel;
        productStateEl.setAttribute("data-state", stateKey || "");
      } else {
        productStateEl.hidden = true;
        productStateEl.textContent = "";
      }
    }
    if (searchEl) searchEl.disabled = !product;
    document.title = name + " — Explorer";
  }

  function contextQuery() {
    var q = new URLSearchParams();
    // Follow Files' last-used product when Toolkit opened with no ?product=.
    if (!followActive) {
      if (queryProduct) q.set("product", queryProduct);
      else if (productId) q.set("product", productId);
    }
    // A pinned pane (?product=) keeps sending them; a following pane only seeds once.
    if (!(followActive && contextSeeded)) {
      if (queryFile) q.set("file", queryFile);
      if (queryFolder) q.set("folder", queryFolder);
    }
    q.set("_", String(Date.now()));
    return q;
  }

  async function syncActiveProduct(options) {
    var opts = options || {};
    var quiet = Boolean(opts.quiet);
    var onlyIfChanged = Boolean(opts.onlyIfChanged);
    var seq = ++contextSeq;
    syncingContext = true;
    try {
      var response = await fetch(
        "/api/embed/explorer/context?" + contextQuery().toString(),
        {
          credentials: "same-origin",
          cache: "no-store",
          headers: { Accept: "application/json", "Cache-Control": "no-cache" },
        }
      );
      if (seq !== contextSeq) return false;
      if (!response.ok) {
        listState = "error";
        listError = await readError(response);
        renderTree();
        setMsg(listError, "err");
        return false;
      }
      var body = await response.json();
      if (seq !== contextSeq) return false;
      var wasSeeded = contextSeeded;
      contextSeeded = true;
      var product = body && body.product ? body.product : null;
      var nextId = product && product.uuid ? String(product.uuid) : "";
      var switched = Boolean(nextId && nextId !== productId);
      if (onlyIfChanged && !switched && productId) {
        return false;
      }
      productId = nextId;
      vaultFolder = product
        ? String(product.vault_folder || product.uuid || "")
        : "";
      // After the first sync a following pane no longer sends file/folder, so an
      // unswitched refresh must keep the focus the first load seeded.
      if (!(followActive && wasSeeded) || switched) {
        focusUuid = String((body && body.focus_uuid) || "").trim();
        initialFolder = String((body && body.initial_folder) || "").trim();
      }
      if (initialFolder) ensureExpandedPath(initialFolder);
      root.setAttribute("data-product-uuid", productId);
      root.setAttribute("data-vault-folder", vaultFolder);
      root.setAttribute("data-product-name", product ? product.name || "" : "");
      root.setAttribute("data-focus-uuid", focusUuid);
      root.setAttribute("data-initial-folder", initialFolder);
      // Prefer server product_ui flags (role ∩ lifecycle) — same as Files chrome.
      if (body && typeof body.allows_content === "boolean") {
        allowsContent = body.allows_content;
      } else if (product) {
        allowsContent = product.allows_content !== false;
      }
      if (body && typeof body.show_open === "boolean") showOpen = body.show_open;
      if (body && typeof body.show_checkout === "boolean") {
        showCheckout = body.show_checkout;
      }
      if (body && typeof body.show_undo_checkout === "boolean") {
        showUndo = body.show_undo_checkout;
      }
      if (body && typeof body.show_checkin === "boolean") {
        showCheckin = body.show_checkin;
      }
      if (body && typeof body.show_revise === "boolean") {
        showRevise = body.show_revise;
      }
      if (body && typeof body.show_export_objects === "boolean") {
        showExport = body.show_export_objects;
      }
      root.setAttribute("data-allows-content", allowsContent ? "1" : "0");
      root.setAttribute("data-show-open", showOpen ? "1" : "0");
      root.setAttribute("data-show-checkout", showCheckout ? "1" : "0");
      root.setAttribute("data-show-undo", showUndo ? "1" : "0");
      root.setAttribute("data-show-checkin", showCheckin ? "1" : "0");
      root.setAttribute("data-show-revise", showRevise ? "1" : "0");
      root.setAttribute("data-show-export", showExport ? "1" : "0");
      setTopLevelAssemblyIds(
        body && Array.isArray(body.top_level_assembly_uuids)
          ? body.top_level_assembly_uuids
          : []
      );
      applyProductChrome(
        product,
        (body && body.product_state_key) || "",
        (body && body.product_state_label) || ""
      );
      if (switched) {
        selected = null;
        objects = [];
        expanded = Object.create(null);
        if (initialFolder) ensureExpandedPath(initialFolder);
        closeContextMenu();
        if (!quiet) setMsg("Switched to " + (product.name || "product") + ".", "ok");
      }
      if (!productId) {
        listState = "error";
        listError = "No product selected.";
        renderTree();
        return false;
      }
      await loadObjects({ quiet: quiet && !switched });
      return switched;
    } catch (err) {
      if (seq !== contextSeq) return false;
      listState = "error";
      listError = String(err && err.message ? err.message : err || "Network error");
      renderTree();
      setMsg(listError, "err");
      return false;
    } finally {
      if (seq === contextSeq) syncingContext = false;
    }
  }

  async function loadObjects(options) {
    var opts = options || {};
    var quiet = Boolean(opts.quiet);
    // keepPaint: background refresh after Files Check In — do not flash Loading.
    var keepPaint = Boolean(opts.keepPaint);
    if (!productId) return;
    var seq = ++listLoadSeq;
    if (!keepPaint) {
      listState = "loading";
      listError = "";
      renderTree();
    }
    if (!quiet) setMsg("Loading files…");
    try {
      // credentials + no-store: Creo CEF must send session cookies and not reuse
      // an empty cached list from the first navigator hit.
      var url =
        "/api/products/" +
        encodeURIComponent(productId) +
        "/objects?_=" +
        String(Date.now());
      var response = await fetch(url, {
        credentials: "same-origin",
        cache: "no-store",
        headers: { Accept: "application/json", "Cache-Control": "no-cache" },
      });
      if (seq !== listLoadSeq) return;
      if (!response.ok) {
        listState = "error";
        listError = await readError(response);
        objects = [];
        renderTree();
        setMsg(listError, "err");
        return;
      }
      var items = await response.json();
      if (seq !== listLoadSeq) return;
      objects = Array.isArray(items) ? items : [];
      listState = "ok";
      await refreshPendingCheckinIds();
      if (seq !== listLoadSeq) return;
      if (focusUuid && !selected) {
        selected =
          objects.find(function (row) {
            return row.uuid === focusUuid;
          }) || null;
        if (selected) ensureExpandedPath(folderOf(selected.relative_path));
      } else if (selected) {
        selected =
          objects.find(function (row) {
            return row.uuid === selected.uuid;
          }) || null;
      }
      var fp = objectsPaintFingerprint();
      // keepPaint soft-refresh: skip DOM rebuild when CO/MOD/list unchanged so a
      // mid-flight double-click still hits the same row (native dblclick).
      if (keepPaint && listState === "ok" && fp === lastPaintFingerprint) {
        if (selected) paintSelection();
        if (!quiet) setMsg(objects.length ? "Updated." : "", objects.length ? "ok" : "");
        return;
      }
      lastPaintFingerprint = fp;
      renderTree();
      if (selected) selectObject(selected);
      if (!quiet) setMsg(objects.length ? "Updated." : "", objects.length ? "ok" : "");
    } catch (err) {
      if (seq !== listLoadSeq) return;
      listState = "error";
      listError = String(err && err.message ? err.message : err || "Network error");
      objects = [];
      renderTree();
      setMsg(listError, "err");
    }
  }

  async function softRefreshList() {
    // Reload checkout / Modified badges without "Loading files…" flash.
    if (!productId || busy || syncingContext) return;
    if (Date.now() < interactGraceUntil) {
      scheduleSoftRefresh(300);
      return;
    }
    await loadObjects({ quiet: true, keepPaint: true });
  }

  function scheduleSoftRefresh(delayMs) {
    if (softRefreshTimer != null) window.clearTimeout(softRefreshTimer);
    softRefreshTimer = window.setTimeout(function () {
      softRefreshTimer = null;
      void softRefreshList();
    }, delayMs == null ? 400 : delayMs);
  }

  async function refreshObjects() {
    // Always re-resolve active product (Files last-used) then reload files.
    await syncActiveProduct({ quiet: false });
    await refreshConnectivity();
  }

  function schedulePostHandoffRefresh() {
    // After Check In / Checkout in Files, CO/MOD here must catch up without Refresh.
    postHandoffRefreshTimers.forEach(function (id) {
      window.clearTimeout(id);
    });
    postHandoffRefreshTimers = [];
    [1500, 4000, 9000].forEach(function (ms) {
      postHandoffRefreshTimers.push(
        window.setTimeout(function () {
          if (busy || syncingContext) return;
          scheduleSoftRefresh(0);
        }, ms)
      );
    });
  }

  function onPaneShown() {
    // Debounced — never refresh synchronously on the same gesture as a click
    // (pointerdown→refresh used to replace the row and kill native dblclick).
    if (syncingContext || busy) return;
    if (followActive) {
      void syncActiveProduct({ quiet: true, onlyIfChanged: true }).then(function (switched) {
        if (switched) return refreshConnectivity();
        scheduleSoftRefresh(400);
      });
      return;
    }
    scheduleSoftRefresh(400);
  }

  function startFollowActivePoll() {
    if (followPollTimer != null) return;
    // Poll product follow (when enabled) and always refresh CO/MOD while pane stays open.
    followPollTimer = window.setInterval(function () {
      if (syncingContext || busy) return;
      if (Date.now() < interactGraceUntil) return;
      if (followActive) {
        void syncActiveProduct({ quiet: true, onlyIfChanged: true }).then(function (switched) {
          if (!switched) scheduleSoftRefresh(0);
        });
      } else {
        scheduleSoftRefresh(0);
      }
    }, FOLLOW_POLL_MS);
  }

  async function openInMainEmbeddedBrowser(absoluteUrl) {
    // Full CreoPDM pages must load in Creo's main embedded browser — never
    // Creo.JS SetURL on this pane (would replace the explorer with Files).
    // Toolkit /url → ProWindowURLShow on the main browser.
    if (!absoluteUrl) {
      setMsg("Could not build Open link for this file.", "err");
      return false;
    }
    try {
      var response = await fetch(
        agentBase() +
          "/toolkit/url?" +
          new URLSearchParams({ url: absoluteUrl }).toString(),
        { headers: agentHeaders(), signal: abortAfter(15000) }
      );
      if (!response.ok) throw new Error(await readError(response));
      setMsg("Opened in CreoPDM browser.", "ok");
      schedulePostHandoffRefresh();
      return true;
    } catch (err) {
      setMsg(
        "Could not open the main CreoPDM browser (" +
          String(err && err.message ? err.message : err) +
          "). Keep this navigator pane and use Creo’s embedded browser for Details.",
        "err"
      );
      return false;
    }
  }

  async function onDetails() {
    if (!selected || !selected.uuid || !productId) return;
    var absolute = new URL(
      "/products/" +
        encodeURIComponent(productId) +
        "/objects/" +
        encodeURIComponent(selected.uuid),
      window.location.origin
    ).href;
    await openInMainEmbeddedBrowser(absolute);
  }

  function filesDeepLink(action) {
    if (!selected || !selected.uuid || !productId) return "";
    var folder = folderOf(selected.relative_path);
    var q = new URLSearchParams();
    q.set("product", productId);
    // Always send folder (even "") so Files does not redirect to a remembered
    // folder that does not contain this tip — that caused "Could not find that file".
    q.set("folder", folder);
    q.set("select", selected.uuid);
    if (action) q.set("action", action);
    // Bust CEF same-URL no-reload so Files reboots and consumes select/action.
    q.set("_nav", String(Date.now()));
    return new URL("/?" + q.toString(), window.location.origin).href;
  }

  async function onOpen() {
    if (!selected || busy) return;
    if (!canOfferOpen(selected)) {
      setMsg("Open is not available for this file.", "err");
      return;
    }
    // Open chooser lives in the main CreoPDM browser — not this pane.
    await openInMainEmbeddedBrowser(filesDeepLink("open"));
  }

  function boot() {
    if (initialFolder) ensureExpandedPath(initialFolder);
    readTopLevelAssemblyIds(root.getAttribute("data-top-level-assemblies") || "");
    syncTypeToggleButtons();
    if (typeToggleRoot) {
      typeToggleRoot.querySelectorAll(".ex-type-toggle[data-type]").forEach(function (btn) {
        btn.addEventListener("click", function (ev) {
          ev.preventDefault();
          ev.stopPropagation();
          toggleTypeFilter(String(btn.getAttribute("data-type") || ""));
        });
      });
    }
    if (searchEl) {
      searchEl.addEventListener("input", function () {
        if (listState === "ok") renderTree();
      });
    }
    if (refreshBtn) {
      refreshBtn.addEventListener("click", function () {
        void refreshObjects();
      });
    }
    if (retryBtn) {
      retryBtn.addEventListener("click", function () {
        void syncActiveProduct({ quiet: false });
      });
    }
    ensureContextMenu();
    if (menuEl) {
      menuEl.addEventListener("click", function (ev) {
        var item = ev.target && ev.target.closest ? ev.target.closest("[data-action]") : null;
        if (!item || !menuEl.contains(item)) return;
        ev.preventDefault();
        runContextAction(item.getAttribute("data-action") || "");
      });
    }
    document.addEventListener(
      "click",
      function (ev) {
        if (!menuEl || menuEl.hidden) return;
        var node = ev.target;
        if (node instanceof Element && menuEl.contains(node)) return;
        closeContextMenu();
      },
      true
    );
    document.addEventListener("keydown", function (ev) {
      if (ev.key === "Escape") closeContextMenu();
    });
    window.addEventListener("scroll", closeContextMenu, true);
    window.addEventListener("resize", closeContextMenu);
    // Never show the browser Refresh / Save as menu in this pane.
    document.addEventListener(
      "contextmenu",
      function (ev) {
        ev.preventDefault();
        var node = ev.target;
        if (node instanceof Element && node.closest && node.closest(".ex-node[data-uuid]")) {
          return; // file row bubble handler opens CreoPDM menu
        }
        closeContextMenu();
      },
      true
    );
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") onPaneShown();
    });
    window.addEventListener("pageshow", function () {
      onPaneShown();
    });
    window.addEventListener("focus", function () {
      onPaneShown();
    });
    // CEF often skips focus/visibility; mouse into the pane still syncs.
    // Do NOT soft-refresh on pointerdown — that rebuilt the tree mid double-click
    // so only an ultra-fast dblclick could open before the row was replaced.
    root.addEventListener("mouseenter", onPaneShown);
    startFollowActivePoll();
    // Re-resolve last-used product (Files may have switched) then load files.
    listState = "loading";
    renderTree();
    void syncActiveProduct({ quiet: true }).then(function () {
      return refreshConnectivity();
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
