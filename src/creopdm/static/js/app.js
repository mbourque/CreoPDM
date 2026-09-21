(() => {
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
      if (window.CreoJS) return true;
    } catch {
      /* ignore */
    }
    return false;
  }

  const creoJSReady = (function loadHostedCreoJS() {
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
      let tries = 0;
      const poll = setInterval(() => {
        tries += 1;
        if (window.CreoJS) {
          clearInterval(poll);
          tryInit();
          done(true);
          return;
        }
        if (tries < 40) return;
        clearInterval(poll);
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
  })();

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
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || "";
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
  function setBusy(message) {
    busyDepth += 1;
    const text = $("#busy-message");
    if (text) text.textContent = message || "Working…";
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

  function closeOpenDialogs() {
    document.querySelectorAll("dialog[open]").forEach((dialog) => {
      try {
        dialog.close();
      } catch {
        /* ignore */
      }
    });
  }

  function leavePage(url) {
    closeOpenDialogs();
    window.location.href = url;
  }

  function reloadPage() {
    closeOpenDialogs();
    // Creo's embedded browser often ignores location.reload/replace and
    // document.write. A real GET form submit reliably loads fresh HTML.
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
    const form = document.createElement("form");
    form.method = "GET";
    form.action = pathname + hash;
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
  }

  function reloadPageAfterDialog() {
    // Submitting a navigation form from inside another form's submit handler
    // (Check In dialog) is ignored by Creo; checkout works because it is a button click.
    window.setTimeout(() => reloadPage(), 50);
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
    btn.classList.toggle("is-selected", mode === "select");
    btn.classList.toggle("is-filtered", mode === "filter");
    const key = metricKey(btn);
    const label = METRIC_LABELS[key] || key;
    if (key === "files") {
      btn.title = mode === "off"
        ? "Select all files and clear type chips. Click again to clear."
        : "Showing all files. Click to clear.";
      return;
    }
    if (key === "checked_out") {
      if (mode === "off") {
        btn.title = "Select checked out files in the current group. Click again to hide the rest. Click a third time to clear.";
      } else if (mode === "select") {
        btn.title = "Selected checked out files in the current group. Click to hide files that are not checked out.";
      } else {
        btn.title = "Showing checked out files in the current group. Click to clear.";
      }
      return;
    }
    if (mode === "off") {
      btn.title = `Select ${label}. Click again to filter. Click a third time to clear.`;
    } else if (mode === "select") {
      btn.title = `Selected ${label}. Click to filter the list to this group.`;
    } else {
      btn.title = `Filtering to ${label}. Click to clear.`;
    }
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
    const active = metricButtons().filter((btn) => metricMode(btn) !== "off");
    const typeActive = active.filter((btn) => !isCheckoutMetric(metricKey(btn)));
    const checkoutOn = active.some((btn) => isCheckoutMetric(metricKey(btn)));
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        if (!active.length) markRowSelected(row, false);
        return;
      }
      if (!active.length) {
        markRowSelected(row, false);
        return;
      }
      const matchesType = !typeActive.length || typeActive.some((btn) => rowMatchesMetric(row, metricKey(btn)));
      const matchesCheckout = !checkoutOn || rowMatchesMetric(row, "checked_out");
      markRowSelected(row, matchesType && matchesCheckout && !rowIsHidden(row));
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
  $("#project-cancel")?.addEventListener("click", () => projectDialog?.close());

  const deleteProjectDialog = $("#delete-project-dialog");
  const deleteProjectForm = $("#delete-project-form");
  $("#delete-project-btn")?.addEventListener("click", () => {
    closeProjectSettings();
    const btn = $("#delete-project-btn");
    showError($("#delete-project-error"), "");
    if (deleteProjectForm) deleteProjectForm.reset();
    deleteProjectDialog?.showModal();
  });
  $("#delete-project-cancel")?.addEventListener("click", () => deleteProjectDialog?.close());
  deleteProjectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("#delete-project-btn");
    const projectId = btn?.dataset.project;
    const expected = (btn?.dataset.name || "").trim();
    if (!projectId) return;
    const typed = String(new FormData(deleteProjectForm).get("confirm_name") || "").trim();
    if (typed !== expected) {
      showError($("#delete-project-error"), "Type the project name exactly to delete it.");
      return;
    }
    const response = await withBusy("Deleting project…", () =>
      fetch(`/api/projects/${projectId}/forget`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_name: typed }),
      })
    );
    if (!response.ok) {
      showError($("#delete-project-error"), await readError(response));
      return;
    }
    const result = await response.json().catch(() => ({}));
    if (result.warning) sessionStorage.setItem("creopdmNotice", result.warning);
    clearProjectViewStorage(projectId);
    leavePage("/");
  });

  function showProjectDialog(mode) {
    if (!projectForm || !projectDialog) return;
    showError($("#project-error"), "");
    const title = $("#project-dialog-title");
    const submit = $("#project-submit");
    projectForm.dataset.mode = mode;
    if (mode === "rename") {
      const btn = $("#rename-project-btn");
      if (title) title.textContent = "Rename project";
      projectForm.elements.name.value = btn?.dataset.name || "";
      projectForm.elements.number.value = btn?.dataset.number || "";
      projectForm.elements.description.value = btn?.dataset.description || "";
      if (submit) submit.textContent = "Save";
    } else {
      projectForm.reset();
      if (title) title.textContent = "New project";
      if (submit) submit.textContent = "Create";
    }
    projectDialog.showModal();
  }

  projectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(projectForm);
    const renaming = projectForm.dataset.mode === "rename";
    const body = {
      name: String(data.get("name") || "").trim(),
      number: String(data.get("number") || "").trim() || null,
      description: String(data.get("description") || "").trim() || null,
    };
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
  let chosenUploads = [];
  let importIgnorePatterns = [];
  let importExtensions = [];
  const UPLOAD_CHUNK = 400;

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

  function logicalUploadName(name) {
    const text = String(name || "");
    const match = text.match(/^(.*?)(?:\.\d+)?$/);
    return match ? match[1] : text;
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
      summary.textContent = `${fileCountLabel(chosenPaths.length)} selected.${omitted}`;
    } else if (ignored) {
      summary.textContent = `No files to add.${omitted}`;
    } else {
      summary.textContent = "";
    }
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

  function applyDroppedFiles(items, uriPaths) {
    const uploads = (items || []).filter((item) => item?.file);
    const diskPaths = [
      ...(uriPaths || []),
      ...uploads.map((item) => item.path).filter(Boolean),
    ];
    const uniquePaths = [...new Set(diskPaths)];
    if (uniquePaths.length && uniquePaths.length >= uploads.length) {
      applyChosenPaths(uniquePaths, "", null, 0);
      return;
    }
    const { kept, skipped } = filterUploadItems(uploads);
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenUploads = kept;
    const summary = $("#chosen-file-summary");
    if (summary) {
      const omitted = skipped
        ? ` ${skipped} ignored ${skipped === 1 ? "file" : "files"} skipped.`
        : "";
      summary.textContent = kept.length
        ? `${fileCountLabel(kept.length)} ready to add.${omitted}`
        : skipped
          ? `No files to add.${omitted}`
          : "";
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

  async function walkDirectoryHandle(dirHandle, prefix) {
    const found = [];
    for await (const [name, handle] of dirHandle.entries()) {
      const relativePath = prefix ? `${prefix}/${name}` : name;
      if (handle.kind === "directory") {
        found.push(...(await walkDirectoryHandle(handle, relativePath)));
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
          walkDirectoryHandle(handle, handle.name || "")
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
    showError($("#add-error"), "");
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenUploads = [];
    const summary = $("#chosen-file-summary");
    if (summary) summary.textContent = "";
    loadAddFolder();
    addDialog?.showModal();
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

  $("#choose-workspace-files")?.addEventListener("click", async () => {
    const projectId = addForm?.dataset.project;
    if (!projectId) return;
    showError($("#add-error"), "");
    if (!useNativePicker()) {
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
    const btn = $("#add-files-btn");
    return Boolean(btn && !btn.disabled && addForm?.dataset.project);
  }

  async function acceptPageDrop(dataTransfer) {
    if (!canAcceptDrops()) return;
    if (!addDialog?.open) {
      chosenPaths = [];
      chosenBaseFolder = null;
      chosenUploads = [];
      const summary = $("#chosen-file-summary");
      if (summary) summary.textContent = "";
      loadAddFolder();
      addDialog?.showModal();
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
    const projectId = addForm.dataset.project;
    if (!projectId) return;
    if (!chosenPaths.length && !chosenBaseFolder && !chosenUploads.length) {
      showError($("#add-error"), "Choose files or a folder first.");
      return;
    }
    const comment = String(new FormData(addForm).get("comment") || "").trim();
    const result = await withBusy(chosenBaseFolder ? "Adding folder…" : "Adding files…", async () => {
      if (chosenUploads.length) {
        const combined = { ok: [], failed: [] };
        for (let offset = 0; offset < chosenUploads.length; offset += UPLOAD_CHUNK) {
          const chunk = chosenUploads.slice(offset, offset + UPLOAD_CHUNK);
          const data = new FormData();
          if (comment && offset === 0) data.append("comment", comment);
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
            return null;
          }
          const body = await response.json();
          combined.ok.push(...(body.ok || []));
          combined.failed.push(...(body.failed || []));
        }
        return combined;
      }
      const payload = chosenBaseFolder
        ? { folder: chosenBaseFolder, base_folder: chosenBaseFolder, comment: comment || null }
        : { paths: chosenPaths, comment: comment || null };
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
    if (failed.length && !result.ok?.length) {
      const first = failed[0]?.message || "Could not add files.";
      const extra = failed.length > 1 ? ` (${failed.length} files failed)` : "";
      showError($("#add-error"), first + extra);
      return;
    }
    reloadPage();
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

  function searchRowHtml(obj, projectId) {
    const relative = String(obj.relative_path || obj.filename || "");
    const folder = folderOfPath(relative);
    const filename = String(obj.filename || "");
    const stamp = formatStamp(obj.updated_at);
    const state = String(obj.lifecycle_state || "");
    const stateLabel = titleCaseWords(state);
    const typeLabel = String(obj.type_label || "");
    const creo = String(obj.creo_release || "");
    const checkout = String(obj.checkout_status || "Available");
    const checkoutKind = obj.owned_by_me ? "mine" : obj.checkout_user ? "other" : "available";
    const rev = String(obj.display_revision || obj.revision || "");
    const pathLine = relative && relative !== filename
      ? `<div class="muted small">${escapeHtml(relative)}</div>`
      : "";
    return `<tr data-uuid="${escapeHtml(obj.uuid)}"
              data-object-type="${escapeHtml(obj.object_type || "")}"
              data-extension="${escapeHtml(obj.extension || "")}"
              data-filename="${escapeHtml(obj.filename || "")}"
              data-can-checkout="${obj.can_checkout ? "1" : "0"}"
              data-can-checkin="${obj.can_checkin ? "1" : "0"}"
              data-owned="${obj.owned_by_me ? "1" : "0"}"
              data-checked-out="${obj.owned_by_me || obj.checkout_user ? "1" : "0"}"
              data-in-workspace="${obj.in_workspace ? "1" : "0"}"
              data-tree="${escapeHtml(folder)}"
              data-sort-name="${escapeHtml(relative)}"
              data-sort-rev="${escapeHtml(folder)}/${escapeHtml(obj.revision || "")}-${padIteration(obj.iteration)}"
              data-sort-state="${escapeHtml(folder)}/${escapeHtml(state)}"
              data-sort-type="${escapeHtml(folder)}/${escapeHtml(typeLabel)}"
              data-sort-creo="${escapeHtml(folder)}/${escapeHtml(creo)}"
              data-sort-modified="${stamp.replace(/[-: ]/g, "")}"
              data-sort-checkout="${escapeHtml(folder)}/${escapeHtml(checkout)}"
              data-detail="/projects/${escapeHtml(projectId)}/objects/${escapeHtml(obj.uuid)}#history"
              class="object-row"
              style="--depth: 0">
            <td title="${escapeHtml(filename)}">
              <button type="button" class="object-open" data-uuid="${escapeHtml(obj.uuid)}" title="${escapeHtml(filename)}">${escapeHtml(filename)}</button>
              ${pathLine}
            </td>
            <td title="${escapeHtml(rev)}">${escapeHtml(rev)}</td>
            <td title="${escapeHtml(stateLabel)}"><span class="state" data-state="${escapeHtml(state)}">${escapeHtml(stateLabel)}</span></td>
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
  const checkoutBtn = $("#checkout-btn");
  const checkinBtn = $("#checkin-btn");
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

  function closeRemoveMenu() {
    if (!removeMenu || !removeMenuBtn || !removeMenuPanel) return;
    removeMenu.classList.remove("is-open");
    removeMenuPanel.hidden = true;
    removeMenuBtn.setAttribute("aria-expanded", "false");
  }

  function openRemoveMenu() {
    if (!removeMenu || !removeMenuBtn || !removeMenuPanel || removeMenuBtn.disabled) return;
    removeMenu.classList.add("is-open");
    removeMenuPanel.hidden = false;
    removeMenuBtn.setAttribute("aria-expanded", "true");
  }

  function toggleRemoveMenu() {
    if (removeMenu?.classList.contains("is-open")) closeRemoveMenu();
    else openRemoveMenu();
  }

  function rowObjectIds(row) {
    if (row.classList.contains("folder-row")) {
      return (row.dataset.objectIds || "").split(",").map((item) => item.trim()).filter(Boolean);
    }
    return row.dataset.uuid ? [row.dataset.uuid] : [];
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
    // Keep the control in layout; only enable/disable so the toolbar does not jump.
    button.hidden = false;
    button.disabled = !visible;
    const tip = button.closest(".toolbar-tip");
    if (tip) tip.hidden = false;
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

  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.flatMap(rowObjectIds);
    if (openBtn) openBtn.disabled = !selectedOpenSpec();
    if (historyBtn) {
      const one = selected.length === 1 ? selected[0] : null;
      historyBtn.disabled = !rowHistoryHref(one);
    }
    const canCheckout = selected.length > 0 && selected.every((row) => row.dataset.canCheckout === "1");
    const canCheckin = selected.length > 0 && selected.every((row) => row.dataset.canCheckin === "1");
    const canUndo = selected.length > 0 && selected.every((row) => row.dataset.owned === "1");
    const addOnly = selectionIsAddOnly(selected);
    if (checkoutBtn) checkoutBtn.disabled = !canCheckout;
    setToolbarActionVisible(checkoutBtn, canCheckout);
    if (checkinBtn) {
      checkinBtn.textContent = addOnly ? "Add" : "Check In";
      const tip = checkinBtn.closest(".toolbar-tip");
      if (tip) {
        tip.title = addOnly
          ? "Add selected new files to the project (uploads local workspace files first)."
          : "Check in selected files.";
      }
    }
    setToolbarActionVisible(checkinBtn, canCheckin);
    setToolbarActionVisible(undoBtn, canUndo);
    if (workspaceBtn) workspaceBtn.disabled = !selected.some((row) => row.dataset.inWorkspace !== "1");
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
    const canRemoveProject = ids.length > 0;
    const canPurgeVersions = Boolean(
      purgeVersionsBtn?.dataset.project || openWorkspaceBtn?.dataset.project || checkinBtn?.dataset.project
    );
    if (discardLocalBtn) discardLocalBtn.disabled = !canDiscardLocal;
    if (purgeBtn) purgeBtn.disabled = !canPurge;
    if (purgeVersionsBtn) purgeVersionsBtn.disabled = !canPurgeVersions;
    if (removeBtn) removeBtn.disabled = !canRemoveProject;
    if (removeMenuBtn) {
      removeMenuBtn.disabled = !(canDiscardLocal || canPurge || canRemoveProject || canPurgeVersions);
      if (removeMenuBtn.disabled) closeRemoveMenu();
    }
    const filtering = metricButtons().some((btn) => metricMode(btn) === "filter");
    const summary = $("#selection-summary");
    if (summary) {
      const count = selected.length || ids.length;
      if (count) {
        summary.removeAttribute("hidden");
        summary.classList.add("is-active");
        summary.textContent = `${count} selected${filtering ? ". The list is filtered" : ""}.`;
      } else {
        summary.setAttribute("hidden", "");
        summary.classList.remove("is-active");
        summary.textContent = "";
      }
    }
  }

  function setCheckinQueueCounts(pendingSaves, newFiles) {
    if (!checkinBtn) return;
    checkinBtn.dataset.pendingSaves = String(pendingSaves || 0);
    checkinBtn.dataset.newFiles = String(newFiles || 0);
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
  }

  function toggleRow(row) {
    markRowSelected(row, !row.classList.contains("is-selected"));
    lastSelectRow = row;
    syncToolbar();
  }

  function selectOnly(row) {
    rows().forEach((item) => markRowSelected(item, item === row));
    lastSelectRow = row;
    syncToolbar();
  }

  function selectRange(toRow, additive = false) {
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
    syncToolbar();
  }

  let lastSelectRow = null;

  function sortValue(row, key, columnIndex) {
    const dataKey = `sort${key.charAt(0).toUpperCase()}${key.slice(1)}`;
    const fromData = row.dataset[dataKey];
    if (fromData !== undefined && fromData !== "") return fromData;
    const cell = row.children[columnIndex];
    return cell ? cell.textContent.replace(/\s+/g, " ").trim() : "";
  }

  function currentProjectId() {
    return (
      $("#rename-project-btn")?.dataset.project ||
      $("#delete-project-btn")?.dataset.project ||
      $("#open-workspace-btn")?.dataset.project ||
      new URLSearchParams(window.location.search).get("project") ||
      ""
    );
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
      if (metricKey(btn) === "files" && mode === "select") mode = "filter";
      if (mode !== "select" && mode !== "filter" && mode !== "off") return;
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
    const projectId = $("#rename-project-btn")?.dataset.project;
    const path = folder?.dataset.folder || "";
    if (projectId && path) {
      window.location.href = `/?project=${projectId}&folder=${encodeURIComponent(path)}`;
    }
  }

  function onFileTableClick(event) {
    const target = eventEl(event);
    const folder = target?.closest(".folder-row");
    const folderLink = target?.closest(".folder-open");
    if (folderLink && folder && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      openFolderRow(folder);
      return;
    }
    const row = target?.closest(".object-row, .folder-row, .queue-row");
    if (!row) return;
    const openLink = target?.closest(".object-open");
    if (openLink) event.preventDefault();
    if (event.shiftKey) {
      event.preventDefault();
      selectRange(row, event.ctrlKey || event.metaKey);
      return;
    }
    if (event.ctrlKey || event.metaKey) {
      event.preventDefault();
      toggleRow(row);
      return;
    }
    selectOnly(row);
    if (row.classList.contains("folder-row")) return;
    if (!openLink || event.detail > 1) return;
    const uuid = openLink.dataset.uuid || row.dataset.uuid;
    if (uuid) {
      void openPdmObject(uuid);
      return;
    }
    const relativePath = openLink.dataset.relativePath || row.dataset.relativePath;
    if (relativePath) void openPdmObject({ relativePath, projectId: currentProjectId() });
  }

  function onFileTableDblclick(event) {
    const target = eventEl(event);
    if (target?.closest(".folder-open")) {
      event.preventDefault();
      const folder = target.closest(".folder-row");
      if (folder) openFolderRow(folder);
      return;
    }
    if (target?.closest(".folder-row")) return;
    if (target?.closest(".object-open")) return;
    const row = target?.closest(".object-row, .queue-row");
    const href = rowHistoryHref(row);
    if (!href) return;
    event.preventDefault();
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
    const next = key === "files"
      ? (current === "filter" ? "off" : "filter")
      : (current === "off" ? "select" : current === "select" ? "filter" : "off");
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

  function hostedCreoJS() {
    try {
      if (!window.CreoJS) return false;
      if (typeof window.CreoJS.isAvailable === "function") {
        return Boolean(window.CreoJS.isAvailable());
      }
      return typeof window.CreoJS.openModel === "function";
    } catch {
      return false;
    }
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
    const inSession = hostedCreoJS();
    document.querySelectorAll(".creo-session-only").forEach((el) => {
      el.hidden = false;
      const btn = el.tagName === "BUTTON" ? el : el.querySelector("button");
      if (!btn) return;
      // Reserve space before Creo.JS is ready; enable only in a Creo session.
      if (!inSession) {
        btn.disabled = true;
        return;
      }
      if (btn.id === "set-creo-dir-btn") {
        btn.disabled = !btn.dataset.workspace;
      }
    });
    const pill = $("#creo-status");
    if (!pill || !inSession) return null;
    const modeKey = creoOpenMode() || "association";
    const modeName = modeKey === "embedded" ? "Embedded" : modeKey === "association" ? "OS" : modeKey;
    if (modeKey === "embedded") {
      const agent =
        prefetchedAgent !== undefined ? prefetchedAgent : await probeCreoAgent();
      if (agent) {
        pill.textContent = `Creo: Connected · ${modeName}`;
        pill.dataset.state = "ok";
        pill.title = "Creo session connected. Local creopdm-agent is running.";
      } else {
        pill.textContent = `Creo: Agent offline · ${modeName}`;
        pill.dataset.state = "idle";
        pill.title =
          "Creo session is open, but creopdm-agent is not running on this PC. Start creopdm-agent-tray for Embedded open.";
      }
      return agent;
    }
    pill.textContent = `Creo: Connected · ${modeName}`;
    pill.dataset.state = "ok";
    pill.title = "Opens Creo models as a browser download for the OS association";
    return null;
  }

  function showCreoSessionControls() {
    void refreshCreoStatusPill();
  }
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
      let seconds = 0;
      if (agent && Object.prototype.hasOwnProperty.call(agent, "status_poll_interval_seconds")) {
        const parsed = Number(agent.status_poll_interval_seconds);
        seconds = Number.isFinite(parsed) ? parsed : 0;
      }
      if (modeKey === "embedded" && seconds > 0) {
        const interval = Math.min(120000, Math.max(1000, Math.round(seconds * 1000)));
        window.setInterval(() => {
          void refreshCreoStatusPill();
        }, interval);
      }
    })();
  });

  async function agentWorkdir(projectId) {
    const query = projectId ? `?project_id=${encodeURIComponent(projectId)}` : "";
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
      const directory = await agentWorkdir(currentProjectId());
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

  function openRequestBody(target, launch) {
    const spec = typeof target === "string" ? { objectId: target } : target || {};
    if (spec.objectId) return { object_id: spec.objectId, launch };
    return {
      project_id: spec.projectId || currentProjectId(),
      relative_path: spec.relativePath,
      launch,
    };
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
    const response = await fetch(
      `${agentBase()}/files?project_id=${encodeURIComponent(projectId)}`,
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

  async function countLocalNewWorkspaceFiles(projectId) {
    if (!projectId) return 0;
    const [cacheFiles, known] = await Promise.all([
      listAgentCacheFiles(projectId),
      ensureKnownWorkspacePaths(projectId),
    ]);
    return localOnlyCacheFiles(cacheFiles, known).length;
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
    await openPdmObject(spec);
  });

  checkoutBtn?.addEventListener("click", async () => {
    const ids = selectedRows().filter((row) => row.dataset.canCheckout === "1").flatMap(rowObjectIds);
    const fallback = selectedIds();
    const objectIds = ids.length ? ids : fallback;
    if (!objectIds.length) return;
    if (objectIds.length === 1 && !selectedRows().length) {
      const result = await postAction(`/api/objects/${objectIds[0]}/checkout`, undefined, "POST", "Checking out…");
      if (result) reloadPage();
      return;
    }
    const result = await postAction("/api/objects/batch/checkout", { object_ids: objectIds }, "POST", "Checking out…");
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) reloadPage();
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
          body: JSON.stringify({ project_id: projectId, folder }),
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
    const objectIds = ids.length ? ids : fallback;
    if (!objectIds.length) return;
    if (objectIds.length === 1 && !selectedRows().length) {
      const result = await postAction(`/api/objects/${objectIds[0]}/undo-checkout`, undefined, "POST", "Cancelling checkout…");
      if (result) {
        rememberWatchView();
        reloadPage();
      }
      return;
    }
    const result = await postAction(
      "/api/objects/batch/undo-checkout",
      { object_ids: objectIds },
      "POST",
      "Cancelling checkout…"
    );
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) reloadPage();
  });

  checkinBtn?.addEventListener("click", async () => {
    const queued = selectedRows().filter((row) => row.classList.contains("queue-row"));
    const owned = selectedRows().filter((row) => {
      return row.dataset.canCheckin === "1" && !row.classList.contains("queue-row");
    });
    const addOnly = selectionIsAddOnly(selectedRows());
    const projectId = checkinBtn.dataset.project || openWorkspaceBtn?.dataset.project;
    if (!checkinDialog) return;
    const fallbackId = checkinBtn.dataset.uuid || "";
    let objectId = "";
    if (!queued.length && owned.length === 1) {
      objectId = owned[0].dataset.uuid;
    } else if (!queued.length && !owned.length && fallbackId) {
      objectId = fallbackId;
    }
    const useQueue = !objectId;
    if (useQueue && !projectId) return;
    showError($("#checkin-error"), "");
    showError($("#toolbar-error"), "");
    const pushItems = [];
    if (!addOnly) {
      if (objectId) {
        const name =
          owned[0]?.dataset.filename ||
          document.querySelector(".detail-head .object-open")?.textContent?.trim() ||
          "";
        pushItems.push({ object_id: objectId, filename: name });
      } else {
        owned.forEach((row) => {
          if (row.dataset.uuid) {
            pushItems.push({
              object_id: row.dataset.uuid,
              filename: row.dataset.filename || "",
            });
          }
        });
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
      pushItems.length &&
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
    if (title) title.textContent = addOnly ? "Add files" : "Check In";
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
        if (selectedIdsForQueue.length) {
          checkinIds = selectedIdsForQueue.filter((id) => pendingSet.has(id));
        } else if (ownedIds.length) {
          checkinIds = ownedIds.filter((id) => pendingSet.has(id));
        } else {
          checkinIds = pendingIds.slice();
        }
      }
      checkinDialog.dataset.objectIds = JSON.stringify(checkinIds);
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
        : !queued.length
          ? pendingNames
          : pendingIds.map((id, index) => (wantedIds.has(id) ? pendingNames[index] : "")).filter(Boolean);
      names.forEach((name) => {
        const item = document.createElement("li");
        item.textContent = `✓ Check in ${name}`;
        list.appendChild(item);
      });
      const newCount = queued.length
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
      } else if (!names.length && !newCount) {
        const item = document.createElement("li");
        item.textContent = "– Nothing to check in. Use Undo Checkout to release locks without a new version.";
        list.appendChild(item);
        canSubmit = false;
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
        : data.force_checkin
          ? "Check In anyway"
          : "Check In";
      submitBtn.disabled = !canSubmit;
    }
    const commentBox = $("#checkin-comment");
    if (commentBox) {
      commentBox.disabled = !canSubmit;
      if (!canSubmit) commentBox.value = "";
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
      queued.map((row) => row.dataset.relativePath).filter(Boolean)
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
      if (!objectIds.length && !added.length) {
        showError(
          $("#checkin-error"),
          "Nothing to check in. Use Undo Checkout to release locks without a new version."
        );
        return;
      }
      result = await postAction(`/api/projects/${projectId}/checkin-queue`, {
        comment,
        object_ids: objectIds,
        add_relative_paths: added,
      }, "POST", busyLabel);
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

  function confirmByProjectName({ title, lead, note, submitLabel, detailsHtml = "" }) {
    const dialog = $("#danger-confirm-dialog");
    const form = $("#danger-confirm-form");
    const expected = expectedProjectName();
    if (!dialog || !form || !expected) return Promise.resolve(false);
    const titleEl = $("#danger-confirm-title");
    const leadEl = $("#danger-confirm-lead");
    const noteEl = $("#danger-confirm-note");
    const noteStrong = noteEl?.querySelector("strong");
    const detailsEl = $("#danger-confirm-details");
    const submitBtn = $("#danger-confirm-submit");
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
        if (dialog.open) dialog.close();
        resolve(ok);
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

  function formatPurgeConfirmDetails(preview) {
    const deleted = Array.isArray(preview?.ok) ? preview.ok : [];
    const floors = Array.isArray(preview?.floors) ? preview.floors : [];
    const parts = [];
    if (deleted.length) {
      parts.push(
        `<p><strong>${deleted.length}</strong> local save(s) would be deleted from the agent cache:</p>`
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
      "<p>Unrelated local files, newer-than-vault work, and everything in the vault are left alone.</p>"
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
  document.addEventListener("click", (event) => {
    if (!removeMenu?.classList.contains("is-open")) return;
    if (removeMenu.contains(eventEl(event))) return;
    closeRemoveMenu();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeRemoveMenu();
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
    if (!confirmed) return;

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
          ? "This deletes the file from the local workspace on this PC (creopdm-agent cache). The vault and project list are unchanged."
          : "These files are deleted from the local workspace on this PC (creopdm-agent cache). The vault and project list are unchanged.",
      note: "This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Workspace",
    });
    if (!confirmed) return;
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
    const confirmed = await confirmByProjectName({
      title: "Purge workspace",
      lead:
        wouldDelete > 0
          ? `About to delete ${wouldDelete} older local Creo model save(s) from the agent cache on this PC. The vault revision and any newer local work stay. The vault is not changed.`
          : "No older local Creo model saves match the vault floors. You can still confirm, but nothing will be deleted.",
      detailsHtml: formatPurgeConfirmDetails(preview),
      note: "This cannot be undone from CreoPDM.",
      submitLabel: wouldDelete > 0 ? `Purge ${wouldDelete} save(s)` : "Purge workspace",
    });
    if (!confirmed) return;
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
    if (!ids.length) return;
    const confirmed = await confirmByProjectName({
      title: ids.length === 1 ? "Remove from project" : `Remove ${ids.length} files from project`,
      lead:
        ids.length === 1
          ? "CreoPDM vault copies are deleted. The original in your project folder is not deleted."
          : "CreoPDM vault copies are deleted. Originals in your project folder are not deleted.",
      note: "The file is removed from this project list. This cannot be undone from CreoPDM.",
      submitLabel: "Remove from Project",
    });
    if (!confirmed) return;
    if (ids.length === 1 && !isListPage) {
      const result = await postAction(`/api/objects/${ids[0]}`, null, "DELETE", "Removing from project…");
      if (result) window.location.href = projectHome();
      return;
    }
    const result = await postAction("/api/objects/batch/remove", { object_ids: ids }, "POST", "Removing from project…");
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) reloadPage();
  });

  async function loadChangesTab() {
    const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
    const body = $("#changes-table tbody");
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (!projectId || !body) return;
    body.replaceChildren();
    const loading = document.createElement("tr");
    loading.className = "empty-row";
    const loadingCell = document.createElement("td");
    loadingCell.colSpan = 5;
    loadingCell.textContent = "Looking for vault and local workspace changes…";
    loading.appendChild(loadingCell);
    body.appendChild(loading);
    refreshTabMetrics();
    try {
      const [queueResponse, cacheFiles] = await Promise.all([
        fetch(`/api/projects/${projectId}/checkin-queue`),
        listAgentCacheFiles(projectId),
      ]);
      if (!queueResponse.ok) throw new Error("queue");
      const data = await queueResponse.json();
      const saves = data.saves || [];
      const vaultNew = data.new_files || [];
      const known = await loadKnownWorkspacePaths(
        projectId,
        vaultNew.map((item) => item.relative_path || "")
      );
      const created = [...vaultNew, ...localOnlyCacheFiles(cacheFiles, known)];
      const pending = saves.length + created.length;
      if (tab) tab.textContent = pending ? `New files · ${pending}` : "New files";
      setCheckinQueueCounts(saves.length, created.length);
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
        return;
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
        row.dataset.canCheckin = "1";
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
            // Use a span — Creo/CEF paints an opaque fill on <button> that shows as a white band.
            const link = document.createElement("span");
            link.className = "object-open";
            link.setAttribute("role", "link");
            link.tabIndex = 0;
            link.textContent = filename;
            link.title = filename;
            if (meta.uuid) link.dataset.uuid = meta.uuid;
            if (meta.relativePath) link.dataset.relativePath = meta.relativePath;
            cell.appendChild(link);
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
      refreshTabMetrics();
    } catch {
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
      else refreshTabMetrics();
    });
  });

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
    heartbeat.timer = window.setInterval(() => {
      heartbeat.ids.forEach((id) => {
        fetch(`/api/objects/${id}/heartbeat`, { method: "POST" });
      });
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
    return document.hidden || busyDepth > 0 || Boolean(document.querySelector("dialog[open]"));
  }

  const watchProjectId = openWorkspaceBtn?.dataset.project || addForm?.dataset.project;
  let watchStamp = null;
  let watchReloadTimer = 0;

  async function pollWorkspaceWatch() {
    if (!watchProjectId || watchPaused()) return;
    try {
      const [response, localNew] = await Promise.all([
        fetch(`/api/projects/${watchProjectId}/workspace-watch`),
        countLocalNewWorkspaceFiles(watchProjectId),
      ]);
      if (!response.ok) return;
      const data = await response.json();
      setCheckinQueueCounts(data.pending_saves, Number(data.new_files || 0) + Number(localNew || 0));
      const next = data.stamp || "";
      if (watchStamp === null) {
        watchStamp = next;
        return;
      }
      if (next === watchStamp) return;
      watchStamp = next;
      knownWorkspacePaths.at = 0; // vault changed — refresh known paths on next count
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
    setInterval(pollWorkspaceWatch, pollMs);
    document.addEventListener("visibilitychange", () => {
      if (!document.hidden) pollWorkspaceWatch();
    });
    pollWorkspaceWatch();
  }

  document.querySelector(".detail-head .object-open")?.addEventListener("click", async (event) => {
    event.preventDefault();
    const id = event.currentTarget.dataset.uuid;
    if (id) await openPdmObject(id);
  });

  restoreStoredFilters();
  syncToolbar();
})();
