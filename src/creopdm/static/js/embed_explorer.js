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
  var actionsEl = document.getElementById("ex-actions");
  var selNameEl = document.getElementById("ex-sel-name");
  var openBtn = document.getElementById("ex-open");
  var checkoutBtn = document.getElementById("ex-checkout");
  var checkinBtn = document.getElementById("ex-checkin");
  var refreshBtn = document.getElementById("ex-refresh");
  var listErrorEl = document.getElementById("ex-list-error");
  var listErrorText = document.getElementById("ex-list-error-text");
  var retryBtn = document.getElementById("ex-retry");

  var productId = (root.getAttribute("data-product-uuid") || "").trim();
  var vaultFolder = (root.getAttribute("data-vault-folder") || "").trim();
  var initialFolder = (root.getAttribute("data-initial-folder") || "").trim();
  var focusUuid = (root.getAttribute("data-focus-uuid") || "").trim();
  var followActive = root.getAttribute("data-follow-active") === "1";
  var queryProduct = (root.getAttribute("data-query-product") || "").trim();
  var queryFile = (root.getAttribute("data-query-file") || "").trim();
  var queryFolder = (root.getAttribute("data-query-folder") || "").trim();
  var allowsContent = root.getAttribute("data-allows-content") === "1";
  var showOpen = root.getAttribute("data-show-open") === "1";
  var showCheckout = root.getAttribute("data-show-checkout") === "1";
  var showCheckin = root.getAttribute("data-show-checkin") === "1";
  var canCheckoutRole = root.getAttribute("data-can-checkout") === "1";
  var canCheckinRole = root.getAttribute("data-can-checkin") === "1";
  var productNameEl = document.getElementById("ex-product-name");
  var productStateEl = document.getElementById("ex-product-state");

  var objects = [];
  var selected = null;
  var expanded = Object.create(null);
  var toolkitOk = false;
  var toolkitReason = "Checking local Toolkit…";
  var agentOnline = false;
  var busy = false;
  /** loading | ok | error — never show "no files yet" until ok with length 0. */
  var listState = "loading";
  var listError = "";
  var listLoadSeq = 0;
  var contextSeq = 0;
  var syncingContext = false;
  /** Creo CEF often never fires focus/visibility when the pane stays loaded. */
  var followPollTimer = null;
  var FOLLOW_POLL_MS = 2000;

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
      return { file: "assembly.png", label: "Assembly" };
    }
    if (typ === "CREO_DRAWING" || ext === "drw" || /\.drw(\.\d+)?$/.test(name)) {
      return { file: "drawing.png", label: "Drawing" };
    }
    if (typ === "CREO_PART" || ext === "prt" || /\.prt(\.\d+)?$/.test(name)) {
      return { file: "part.png", label: "Part" };
    }
    return { file: "file.svg", label: "File" };
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
      toolkitReason = "Start creopdm-agent on this PC (Open needs the agent to reach Toolkit).";
      setBanner(toolkitReason, true);
      syncActionButtons();
      return;
    }
    var tk = await probeToolkit();
    toolkitOk = Boolean(tk.ok);
    toolkitReason = tk.reason || "Creo Toolkit Companion is not reachable on 127.0.0.1:8767.";
    if (!toolkitOk) {
      setBanner(
        "Open disabled: " + toolkitReason + " List/search still work.",
        true
      );
    } else {
      setBanner("");
    }
    syncActionButtons();
  }

  function matchesQuery(obj, q) {
    if (!q) return true;
    var hay = [
      obj.filename,
      obj.relative_path,
      obj.type_label,
      obj.revision,
      obj.lifecycle_state,
      obj.checkout_status,
    ]
      .join(" ")
      .toLowerCase();
    return hay.indexOf(q) !== -1;
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
    var q = (searchEl && searchEl.value ? searchEl.value : "").trim().toLowerCase();
    var filtered = objects.filter(function (obj) {
      return matchesQuery(obj, q);
    });
    if (q) {
      filtered.forEach(function (obj) {
        ensureExpandedPath(folderOf(obj.relative_path));
      });
    }
    var tree = buildTree(filtered);
    treeEl.innerHTML = "";
    appendFolderKids(treeEl, tree, 0, q);
    // Empty copy only after a successful list response (listState === "ok").
    if (!filtered.length) {
      var empty = document.createElement("p");
      empty.className = "ex-empty";
      empty.textContent = q ? "No matching files." : "This product has no files yet.";
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
        if (obj.modified_locally && (obj.owned_by_me || obj.can_checkin)) {
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
          selectObject(obj);
        });
        row.addEventListener("dblclick", function (ev) {
          ev.preventDefault();
          selectObject(obj);
          void onOpen();
        });
        parent.appendChild(row);
      });
  }

  function selectObject(obj) {
    selected = obj;
    if (actionsEl) actionsEl.hidden = !obj;
    if (selNameEl) selNameEl.textContent = obj ? obj.filename || obj.name || "" : "";
    syncActionButtons();
    renderTree();
  }

  function syncActionButtons() {
    if (!selected) {
      if (openBtn) openBtn.disabled = true;
      if (checkoutBtn) checkoutBtn.disabled = true;
      if (checkinBtn) checkinBtn.disabled = true;
      return;
    }
    var openEnabled =
      showOpen && allowsContent && toolkitOk && agentOnline && !busy;
    if (openBtn) {
      openBtn.disabled = !openEnabled;
      openBtn.classList.toggle("is-primary", openEnabled);
      openBtn.title = openEnabled
        ? "Download via creopdm-agent, then open with Creo Toolkit"
        : toolkitOk
          ? "Open unavailable"
          : toolkitReason;
    }
    if (checkoutBtn) {
      checkoutBtn.disabled = !(
        showCheckout &&
        canCheckoutRole &&
        selected.can_checkout &&
        !busy
      );
      checkoutBtn.hidden = !showCheckout;
    }
    if (checkinBtn) {
      checkinBtn.disabled = !(
        showCheckin &&
        canCheckinRole &&
        selected.can_checkin &&
        !busy
      );
      checkinBtn.hidden = !showCheckin;
    }
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
    if (queryFile) q.set("file", queryFile);
    if (queryFolder) q.set("folder", queryFolder);
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
      focusUuid = String((body && body.focus_uuid) || "").trim();
      initialFolder = String((body && body.initial_folder) || "").trim();
      if (initialFolder) ensureExpandedPath(initialFolder);
      root.setAttribute("data-product-uuid", productId);
      root.setAttribute("data-vault-folder", vaultFolder);
      root.setAttribute("data-product-name", product ? product.name || "" : "");
      root.setAttribute("data-focus-uuid", focusUuid);
      root.setAttribute("data-initial-folder", initialFolder);
      if (product) {
        allowsContent = product.allows_content !== false;
        root.setAttribute("data-allows-content", allowsContent ? "1" : "0");
      }
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
        if (actionsEl) actionsEl.hidden = true;
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
    if (!productId) return;
    var seq = ++listLoadSeq;
    listState = "loading";
    listError = "";
    renderTree();
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

  async function refreshObjects() {
    // Always re-resolve active product (Files last-used) then reload files.
    await syncActiveProduct({ quiet: false });
    await refreshConnectivity();
  }

  function onPaneShown() {
    if (syncingContext || busy) return;
    if (!followActive) return;
    void syncActiveProduct({ quiet: true, onlyIfChanged: true }).then(function (switched) {
      if (switched) return refreshConnectivity();
    });
  }

  function startFollowActivePoll() {
    if (!followActive || followPollTimer != null) return;
    // Navigator pane stays loaded while you use Files — poll last-used product.
    followPollTimer = window.setInterval(function () {
      if (syncingContext || busy) return;
      void syncActiveProduct({ quiet: true, onlyIfChanged: true });
    }, FOLLOW_POLL_MS);
  }

  async function materializePrepared(prepared) {
    var deps = Array.isArray(prepared.dependencies) ? prepared.dependencies : [];
    var body = {
      pdm_url: pdmOrigin(),
      object_id: prepared.object_id || selected.uuid,
      product_id: prepared.product_id || productId,
      vault_folder: vaultFolder,
      relative_path: prepared.relative_path || selected.relative_path,
      filename: prepared.filename || selected.filename,
      disk_name: prepared.disk_name || prepared.filename || selected.filename,
      content_hash: prepared.content_hash || "",
      file_size: prepared.file_size || 0,
      prefer_local: Boolean(prepared.prefer_local),
      token: (root.getAttribute("data-agent-token") || "").trim(),
      dependencies: deps.map(function (dep) {
        return {
          object_id: dep.object_id || null,
          product_id: dep.product_id || productId,
          relative_path: dep.relative_path || null,
          filename: dep.filename || null,
          disk_name: dep.disk_name || dep.filename || null,
          content_hash: dep.content_hash || "",
          file_size: dep.file_size || 0,
          prefer_local: Boolean(dep.prefer_local),
        };
      }),
    };
    var response = await fetch(agentBase() + "/materialize", {
      method: "POST",
      headers: agentHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    return response.json();
  }

  async function toolkitOpen(fileName, path) {
    var query = new URLSearchParams();
    if (fileName) query.set("fileName", fileName);
    if (path) query.set("path", path);
    var response = await fetch(agentBase() + "/toolkit/open?" + query.toString(), {
      headers: agentHeaders(),
    });
    if (!response.ok) {
      throw new Error(await readError(response));
    }
    var body = await response.json();
    if (body && body.ok === false) {
      throw new Error(String(body.error || body.detail || "Toolkit open failed."));
    }
    return body;
  }

  async function onOpen() {
    if (!selected || busy) return;
    busy = true;
    syncActionButtons();
    setMsg("Preparing…");
    try {
      await refreshConnectivity();
      if (!agentOnline || !toolkitOk) {
        throw new Error(toolkitReason);
      }
      var prepare = await fetch("/api/creo/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          object_id: selected.uuid,
          launch: false,
          include_dependencies: true,
        }),
      });
      if (!prepare.ok) throw new Error(await readError(prepare));
      var prepared = await prepare.json();
      setMsg("Updating local workspace…");
      var local = await materializePrepared(prepared);
      var tipName = prepared.filename || selected.filename;
      var tipPath = local.path || "";
      setMsg("Opening in Creo (Toolkit)…");
      await toolkitOpen(tipName, tipPath);
      setMsg("Opened " + tipName + " in Creo.", "ok");
    } catch (err) {
      setMsg(String(err && err.message ? err.message : err), "err");
    } finally {
      busy = false;
      syncActionButtons();
    }
  }

  async function onCheckout() {
    if (!selected || busy) return;
    busy = true;
    syncActionButtons();
    setMsg("Checking out…");
    try {
      var response = await fetch(
        "/api/objects/" + encodeURIComponent(selected.uuid) + "/checkout",
        { method: "POST" }
      );
      if (!response.ok) throw new Error(await readError(response));
      var updated = await response.json();
      selected = updated;
      objects = objects.map(function (row) {
        return row.uuid === updated.uuid ? updated : row;
      });
      if (agentOnline) {
        setMsg("Downloading to workspace…");
        var prepare = await fetch("/api/creo/open", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            object_id: selected.uuid,
            launch: false,
            include_dependencies: true,
          }),
        });
        if (prepare.ok) {
          await materializePrepared(await prepare.json());
        }
      }
      renderTree();
      selectObject(selected);
      setMsg("Checked out " + (selected.filename || "") + ".", "ok");
    } catch (err) {
      setMsg(String(err && err.message ? err.message : err), "err");
    } finally {
      busy = false;
      syncActionButtons();
    }
  }

  async function onCheckin() {
    if (!selected || busy) return;
    var comment = window.prompt("Check-in comment", "Check in from explorer");
    if (comment == null) return;
    comment = String(comment).trim();
    if (!comment) {
      setMsg("A check-in comment is required.", "err");
      return;
    }
    busy = true;
    syncActionButtons();
    setMsg("Checking in…");
    try {
      if (agentOnline) {
        var push = await fetch(agentBase() + "/push", {
          method: "POST",
          headers: agentHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            pdm_url: pdmOrigin(),
            product_id: productId,
            vault_folder: vaultFolder,
            token: (root.getAttribute("data-agent-token") || "").trim(),
            items: [
              {
                object_id: selected.uuid,
                filename: selected.filename,
                relative_path: selected.relative_path,
              },
            ],
          }),
        });
        if (!push.ok) {
          // Local tip may already match vault — continue to server check-in.
          var pushDetail = await readError(push);
          setMsg("Workspace push note: " + pushDetail);
        }
      }
      var response = await fetch(
        "/api/objects/" + encodeURIComponent(selected.uuid) + "/checkin",
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ comment: comment, add_relative_paths: [] }),
        }
      );
      if (!response.ok) throw new Error(await readError(response));
      var updated = await response.json();
      selected = updated;
      objects = objects.map(function (row) {
        return row.uuid === updated.uuid ? updated : row;
      });
      renderTree();
      selectObject(selected);
      setMsg("Checked in " + (selected.filename || "") + ".", "ok");
    } catch (err) {
      setMsg(String(err && err.message ? err.message : err), "err");
    } finally {
      busy = false;
      syncActionButtons();
    }
  }

  function boot() {
    if (initialFolder) ensureExpandedPath(initialFolder);
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
    if (openBtn) openBtn.addEventListener("click", function () {
      void onOpen();
    });
    if (checkoutBtn) checkoutBtn.addEventListener("click", function () {
      void onCheckout();
    });
    if (checkinBtn) checkinBtn.addEventListener("click", function () {
      void onCheckin();
    });
    document.addEventListener("visibilitychange", function () {
      if (document.visibilityState === "visible") onPaneShown();
    });
    window.addEventListener("pageshow", function () {
      onPaneShown();
    });
    window.addEventListener("focus", function () {
      onPaneShown();
    });
    // CEF often skips focus/visibility; mouse into the pane still syncs immediately.
    root.addEventListener("mouseenter", onPaneShown);
    root.addEventListener("pointerdown", onPaneShown, true);
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
