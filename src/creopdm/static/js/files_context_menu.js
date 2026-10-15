/**
 * Shared Files / navigator RMB menu — single source for labels + hide rules.
 * Loaded by base.html (Files) and embed_explorer.html (Creo navigator).
 * Callers map their selection into a plain state object; do not fork item lists.
 */
(function (global) {
  "use strict";

  var ITEMS = [
    {
      action: "open",
      label: "Open selected",
      title: "Open the selected file in Creo or its Windows associated program.",
      // Navigator pane: hand off to main embedded Files (Open chooser).
      needsEmbedded: true,
    },
    {
      action: "details",
      label: "Details",
      title:
        "Open Details for the selected file (Overview and History). Same as double-clicking the row.",
      needsEmbedded: true,
    },
    {
      action: "checkout",
      label: "Checkout selected",
      title: "Check out the selected files and download them to the local workspace.",
      needsEmbedded: true,
    },
    {
      action: "undo",
      label: "Undo Checkout",
      title:
        "Release your checkout lock. Does not delete the vault file or record a new version. A Creo save still on disk can be checked in afterward.",
      needsEmbedded: true,
    },
    {
      action: "add-selected",
      label: "Add selected…",
      title: "Add selected new files to the product (uploads local workspace files first).",
      needsEmbedded: true,
    },
    {
      action: "checkin",
      label: "Check in selected…",
      title: "Check in selected files.",
      needsEmbedded: true,
    },
    {
      action: "download",
      label: "Download selected to workspace",
      title: "Download the selected files into this product’s local workspace on this PC.",
      needsEmbedded: true,
    },
    {
      action: "export",
      label: "Export selected…",
      title: "Download the selected vault files or folders as a zip.",
      needsEmbedded: true,
    },
    {
      action: "discard-local",
      label: "Remove from Workspace…",
      title:
        "Move selected files from the local workspace on this PC to the Recycle Bin. Does not affect the vault or product list.",
      needsEmbedded: true,
    },
  ];

  function itemForAction(action) {
    var key = String(action || "");
    for (var i = 0; i < ITEMS.length; i += 1) {
      if (ITEMS[i].action === key) return ITEMS[i];
    }
    return null;
  }

  function needsEmbeddedBrowser(action) {
    var item = itemForAction(action);
    return Boolean(item && item.needsEmbedded);
  }

  /** localStorage key so Files → navigator share the same Modified / Check In set. */
  function pendingCheckinStorageKey(productId) {
    var id = String(productId || "").trim();
    return id ? "creopdm:pending-checkin:" + id : "";
  }

  var PENDING_COOKIE = "creopdm_pending_checkin";

  function writePendingCheckinIds(productId, ids) {
    var pid = String(productId || "").trim();
    var list = [];
    var seen = Object.create(null);
    (ids || []).forEach(function (id) {
      var uid = String(id || "").trim();
      if (!uid || seen[uid]) return;
      seen[uid] = true;
      list.push(uid);
    });
    var payload = JSON.stringify({ productId: pid, at: Date.now(), ids: list });
    var key = pendingCheckinStorageKey(pid);
    if (key && typeof localStorage !== "undefined") {
      try {
        localStorage.setItem(key, payload);
      } catch (err) {
        /* private mode / quota */
      }
    }
    // Cookie shared across Creo CEF panes (navigator vs main) for same origin.
    if (pid && typeof document !== "undefined") {
      try {
        document.cookie =
          PENDING_COOKIE +
          "=" +
          encodeURIComponent(payload) +
          "; path=/; SameSite=Lax; max-age=7200";
      } catch (err) {
        /* ignore */
      }
    }
  }

  function readPendingCheckinIds(productId) {
    var pid = String(productId || "").trim();
    var bodies = [];
    var key = pendingCheckinStorageKey(pid);
    if (key && typeof localStorage !== "undefined") {
      try {
        var raw = localStorage.getItem(key);
        if (raw) bodies.push(raw);
      } catch (err) {
        /* ignore */
      }
    }
    if (typeof document !== "undefined" && document.cookie) {
      try {
        var parts = document.cookie.split(";");
        for (var i = 0; i < parts.length; i += 1) {
          var chunk = parts[i].trim();
          if (chunk.indexOf(PENDING_COOKIE + "=") !== 0) continue;
          bodies.push(decodeURIComponent(chunk.slice(PENDING_COOKIE.length + 1)));
          break;
        }
      } catch (err) {
        /* ignore */
      }
    }
    var out = [];
    var seen = Object.create(null);
    bodies.forEach(function (raw) {
      try {
        var body = JSON.parse(raw);
        if (!body) return;
        if (pid && body.productId && String(body.productId) !== pid) return;
        (Array.isArray(body.ids) ? body.ids : []).forEach(function (id) {
          var uid = String(id || "").trim();
          if (!uid || seen[uid]) return;
          seen[uid] = true;
          out.push(uid);
        });
      } catch (err) {
        /* ignore bad payload */
      }
    });
    return out;
  }

  /**
   * @param {object} state
   * @param {Array<object>} state.rows normalized selection rows:
   *   uuid, relativePath, canCheckout, owned, canCheckin, localCache,
   *   isNewFile, hasDetails, hasCheckinWork, isFolder
   * @param {boolean} [state.hasOpenSpec] when set, overrides row-derived Open tip
   * @param {boolean} state.showOpen product_ui / Open control present
   * @param {boolean} state.showCheckout role ∩ lifecycle Checkout
   * @param {boolean} state.showUndo role ∩ lifecycle Undo
   * @param {boolean} state.showCheckin role ∩ lifecycle Check In
   * @param {boolean} state.showExportObjects objects.export ∩ product_ui
   * @param {boolean} state.canViewObjects objects.view
   * @param {boolean} state.allowsContent lifecycle download/open
   * @param {boolean} state.canOfferAdd Add ▾ present
   * @param {boolean} state.canDiscardLocalControl Remove from Workspace control present
   * @param {boolean} [state.busy]
   */
  function capabilities(state) {
    state = state || {};
    var rows = Array.isArray(state.rows) ? state.rows : [];
    var busy = Boolean(state.busy);

    var openSpec;
    if (typeof state.hasOpenSpec === "boolean") {
      openSpec = state.hasOpenSpec;
    } else if (rows.length === 1) {
      var tip = rows[0] || {};
      openSpec = Boolean(tip.uuid || tip.relativePath);
    } else {
      openSpec = false;
    }
    var canOpen = Boolean(state.showOpen) && openSpec && !busy;

    var one = rows.length === 1 ? rows[0] : null;
    var canDetails = Boolean(one && one.hasDetails) && !busy;

    var canCheckout =
      Boolean(state.showCheckout) &&
      rows.length > 0 &&
      rows.every(function (row) {
        return Boolean(row && row.canCheckout);
      }) &&
      !busy;

    var canUndo =
      Boolean(state.showUndo) &&
      rows.length > 0 &&
      rows.every(function (row) {
        return Boolean(row && row.owned);
      }) &&
      !busy;

    var addOnly =
      rows.length > 0 &&
      rows.every(function (row) {
        return Boolean(row && row.isNewFile);
      });
    var canAddSelected = Boolean(state.canOfferAdd) && addOnly && !busy;

    var allEligibleCheckin =
      rows.length > 0 &&
      rows.every(function (row) {
        return Boolean(row && (row.canCheckin || row.isNewFile));
      });
    var someCheckinWork = rows.some(function (row) {
      return Boolean(row && (row.isNewFile || row.hasCheckinWork));
    });
    // New-files-only uses Add selected… — never Check in selected…
    var canCheckin =
      Boolean(state.showCheckin) &&
      !addOnly &&
      allEligibleCheckin &&
      someCheckinWork &&
      !busy;

    var alreadyLocal =
      rows.length > 0 &&
      rows.every(function (row) {
        return Boolean(row && row.localCache);
      });
    var downloadIds = 0;
    rows.forEach(function (row) {
      if (row && row.uuid) downloadIds += 1;
    });
    var canDownload =
      Boolean(state.canViewObjects) &&
      Boolean(state.allowsContent) &&
      downloadIds > 0 &&
      !alreadyLocal &&
      !busy;

    var exportHasSelection = rows.some(function (row) {
      return Boolean(row && (row.uuid || row.isFolder));
    });
    var canExport = Boolean(state.showExportObjects) && exportHasSelection && !busy;

    var canDiscardLocal =
      Boolean(state.canDiscardLocalControl) &&
      rows.some(function (row) {
        return Boolean(row && row.isNewFile && row.localCache);
      }) &&
      !busy;

    return {
      canOpen: canOpen,
      canDetails: canDetails,
      canCheckout: canCheckout,
      canUndo: canUndo,
      canAddSelected: canAddSelected,
      canCheckin: canCheckin,
      canDownload: canDownload,
      canExport: canExport,
      canDiscardLocal: canDiscardLocal,
    };
  }

  function anyVisible(caps) {
    caps = caps || {};
    return Boolean(
      caps.canOpen ||
        caps.canDetails ||
        caps.canCheckout ||
        caps.canUndo ||
        caps.canAddSelected ||
        caps.canCheckin ||
        caps.canDownload ||
        caps.canExport ||
        caps.canDiscardLocal
    );
  }

  /**
   * Ensure menu buttons exist (idempotent). options: { itemClass, idPrefix }
   */
  function ensureItems(menuEl, options) {
    if (!menuEl) return menuEl;
    options = options || {};
    var itemClass = options.itemClass || "toolbar-menu-item";
    var idPrefix = options.idPrefix || "";
    ITEMS.forEach(function (spec) {
      var id = idPrefix ? idPrefix + spec.action : "";
      if (id && menuEl.querySelector("#" + id)) return;
      if (!id && menuEl.querySelector('[data-action="' + spec.action + '"]')) return;
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = itemClass;
      if (id) btn.id = id;
      btn.dataset.action = spec.action;
      btn.setAttribute("role", "menuitem");
      btn.textContent = spec.label;
      btn.title = spec.title;
      menuEl.appendChild(btn);
    });
    return menuEl;
  }

  function applyVisibility(menuEl, caps) {
    if (!menuEl) return;
    caps = caps || {};
    var map = {
      open: caps.canOpen,
      details: caps.canDetails,
      checkout: caps.canCheckout,
      undo: caps.canUndo,
      "add-selected": caps.canAddSelected,
      checkin: caps.canCheckin,
      download: caps.canDownload,
      export: caps.canExport,
      "discard-local": caps.canDiscardLocal,
    };
    menuEl.querySelectorAll("[data-action]").forEach(function (btn) {
      var action = btn.getAttribute("data-action") || "";
      btn.hidden = !map[action];
      if (action === "checkin") {
        btn.textContent = "Check in selected…";
        btn.title = "Check in selected files.";
      }
    });
  }

  global.CreoPdmFilesContextMenu = {
    ITEMS: ITEMS,
    capabilities: capabilities,
    anyVisible: anyVisible,
    ensureItems: ensureItems,
    applyVisibility: applyVisibility,
    itemForAction: itemForAction,
    needsEmbeddedBrowser: needsEmbeddedBrowser,
    pendingCheckinStorageKey: pendingCheckinStorageKey,
    writePendingCheckinIds: writePendingCheckinIds,
    readPendingCheckinIds: readPendingCheckinIds,
  };
})(typeof window !== "undefined" ? window : globalThis);
