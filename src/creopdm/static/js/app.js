(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  function inCreoBrowser() {
    try {
      return Boolean(window.external && window.external.ptc);
    } catch {
      return false;
    }
  }

  const creoJSReady = (function loadHostedCreoJS() {
    if (!inCreoBrowser()) return Promise.resolve(false);
    if (window.CreoJS) return Promise.resolve(true);
    return new Promise((resolve) => {
      const script = document.createElement("script");
      script.src = "/creojs.js";
      script.onload = () => {
        try {
          if (document.readyState === "complete" && window.CreoJS && typeof window.CreoJS.$INITIALIZE === "function") {
            window.CreoJS.$INITIALIZE();
          }
        } catch {
          resolve(false);
          return;
        }
        resolve(true);
      };
      script.onerror = () => resolve(false);
      document.head.appendChild(script);
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

  const storedNotice = sessionStorage.getItem("creopdmNotice");
  if (storedNotice) {
    sessionStorage.removeItem("creopdmNotice");
    showError($("#toolbar-error"), storedNotice);
  }

  let busyDepth = 0;
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
      if (!err) return response.statusText;
      const extra = err.details?.user
        ? ` ${err.details.user} on ${err.details.machine || "unknown machine"} since ${err.details.since || "unknown"}.`
        : "";
      return `${err.message}${extra}`;
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

  function metricMode(btn) {
    return btn.dataset.mode || "off";
  }

  function isParentMetric(key) {
    return key === "files" || key === "cad_models";
  }

  function clearMetricFilters(keys) {
    metricButtons().forEach((item) => {
      if (keys.has(item.dataset.filter) && metricMode(item) !== "off") setMetricMode(item, "off");
    });
  }

  function cadModelsExtensions() {
    return listedExtensions("cadModels");
  }

  function documentExtensions() {
    return listedExtensions("documents");
  }

  function listedExtensions(datasetKey) {
    const raw = document.querySelector("#metric-filters")?.dataset[datasetKey] || "";
    return raw.split(/[\s,;]+/).map((item) => {
      const ext = item.trim().toLowerCase();
      if (!ext) return "";
      return ext.startsWith(".") ? ext : `.${ext}`;
    }).filter(Boolean);
  }

  function rowExtension(row) {
    const ext = String(row.dataset.extension || "").trim().toLowerCase();
    if (!ext) return "";
    return ext.startsWith(".") ? ext : `.${ext}`;
  }

  function rowMatchesMetric(row, key) {
    if (key === "checked_out") return row.dataset.checkedOut === "1";
    if (key === "cad_models") return cadModelsExtensions().includes(rowExtension(row));
    if (key === "documents") return documentExtensions().includes(rowExtension(row));
    if (key === "other") return !cadModelsExtensions().includes(rowExtension(row));
    const types = FILTERS[key];
    return types === null || types.includes(row.dataset.objectType);
  }

  function rememberMetricCounts() {
    metricButtons().forEach((btn) => {
      const strong = btn.querySelector("strong");
      if (!strong || btn.dataset.folderCount != null) return;
      btn.dataset.folderCount = strong.textContent.trim();
    });
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
    if (root.id === "panel-changes") {
      return [...root.querySelectorAll(".queue-row")];
    }
    return [...root.querySelectorAll(".object-row")];
  }

  function updateMetricCounts() {
    rememberMetricCounts();
    const root = fileListRoot();
    const filesTab = !root || root.id === "panel-files";
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
      const key = btn.dataset.filter;
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
    btn.classList.toggle("is-selected", mode === "select");
    btn.classList.toggle("is-filtered", mode === "filter");
    const key = btn.dataset.filter;
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

  function applyMetricVisibility() {
    const metrics = metricButtons();
    const typeFilterBtns = metrics.filter((btn) => {
      return !isCheckoutMetric(btn.dataset.filter) && metricMode(btn) === "filter";
    });
    const checkoutFiltering = metrics.some((btn) => {
      return isCheckoutMetric(btn.dataset.filter) && metricMode(btn) === "filter";
    });
    const typeRestricts = typeFilterBtns.length > 0 || checkoutFiltering;
    const viewBtns = metrics.filter((btn) => {
      const key = btn.dataset.filter;
      if (isCheckoutMetric(key)) return false;
      const mode = metricMode(btn);
      if (mode === "off" || !typeRestricts) return false;
      if (mode === "select" && isParentMetric(key) && typeFilterBtns.length) return false;
      return true;
    });
    const q = searchInput?.value.trim().toLowerCase() || "";
    const searchingAll = $("#object-table")?.dataset.searching === "1";
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        const matchesSearch = searchingAll ? false : (!q || row.textContent.toLowerCase().includes(q));
        row.hidden = Boolean(q) && !matchesSearch;
        return;
      }
      const matchesSearch = searchingAll || !q || row.textContent.toLowerCase().includes(q);
      const matchesView = !viewBtns.length || viewBtns.some((btn) => rowMatchesMetric(row, btn.dataset.filter));
      const matchesCheckout = !checkoutFiltering || rowMatchesMetric(row, "checked_out");
      row.hidden = !(matchesSearch && matchesView && matchesCheckout);
    });
  }

  function applyMetricSelection() {
    const active = metricButtons().filter((btn) => metricMode(btn) !== "off");
    const typeActive = active.filter((btn) => !isCheckoutMetric(btn.dataset.filter));
    const checkoutOn = active.some((btn) => isCheckoutMetric(btn.dataset.filter));
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        if (!active.length) row.classList.remove("is-selected");
        return;
      }
      if (!active.length) {
        row.classList.remove("is-selected");
        return;
      }
      const matchesType = !typeActive.length || typeActive.some((btn) => rowMatchesMetric(row, btn.dataset.filter));
      const matchesCheckout = !checkoutOn || rowMatchesMetric(row, "checked_out");
      row.classList.toggle("is-selected", !row.hidden && matchesType && matchesCheckout);
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
  $("#rename-project-btn")?.addEventListener("click", () => showProjectDialog("rename"));
  $("#project-cancel")?.addEventListener("click", () => projectDialog?.close());

  const forgetDialog = $("#forget-dialog");
  const forgetForm = $("#forget-form");
  $("#forget-project-btn")?.addEventListener("click", () => {
    const btn = $("#forget-project-btn");
    showError($("#forget-error"), "");
    if (forgetForm) forgetForm.reset();
    forgetDialog?.showModal();
  });
  $("#forget-cancel")?.addEventListener("click", () => forgetDialog?.close());
  forgetForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const btn = $("#forget-project-btn");
    const projectId = btn?.dataset.project;
    const expected = (btn?.dataset.name || "").trim();
    if (!projectId) return;
    const typed = String(new FormData(forgetForm).get("confirm_name") || "").trim();
    if (typed !== expected) {
      showError($("#forget-error"), "Type the project name exactly to forget it.");
      return;
    }
    const response = await withBusy("Forgetting project…", () =>
      fetch(`/api/projects/${projectId}/forget`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ confirm_name: typed }),
      })
    );
    if (!response.ok) {
      showError($("#forget-error"), await readError(response));
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

  async function loadAddFolder() {
    const projectId = addForm?.dataset.project;
    const label = $("#add-folder-label");
    if (!projectId || !label) return;
    const response = await fetch(`/api/projects/${projectId}/workspace/add-folder`);
    if (!response.ok) return;
    const data = await response.json();
    label.textContent = `Opens in: ${data.initial_directory}`;
  }

  function fileCountLabel(count) {
    return count === 1 ? "1 file" : `${count} files`;
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
    chosenPaths = [];
    chosenBaseFolder = null;
    chosenUploads = uploads;
    const summary = $("#chosen-file-summary");
    if (summary) {
      summary.textContent = uploads.length
        ? `${fileCountLabel(uploads.length)} dropped.`
        : "";
    }
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

  $("#choose-workspace-files")?.addEventListener("click", async () => {
    const projectId = addForm?.dataset.project;
    if (!projectId) return;
    showError($("#add-error"), "");
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
        const data = new FormData();
        if (comment) data.append("comment", comment);
        chosenUploads.forEach((item) => {
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
        return response.json();
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
    window.location.reload();
  });

  const searchInput = $("#search-input");
  const fileListRoot = () => {
    const panels = ["panel-checked-out", "panel-changes", "panel-files"];
    const open = panels.map((id) => document.getElementById(id)).find((el) => el && !el.hidden);
    return open || $("#panel-files") || document;
  };
  const rows = () => [...fileListRoot().querySelectorAll(".object-row, .folder-row, .queue-row")];
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
  const removeBtn = $("#remove-project-btn");

  function rowObjectIds(row) {
    if (row.classList.contains("folder-row")) {
      return (row.dataset.objectIds || "").split(",").map((item) => item.trim()).filter(Boolean);
    }
    return row.dataset.uuid ? [row.dataset.uuid] : [];
  }

  function selectedRows() {
    const picked = rows().filter((row) => row.classList.contains("is-selected") && !row.hidden);
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

  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.flatMap(rowObjectIds);
    if (openBtn) openBtn.disabled = !selectedOpenSpec();
    if (historyBtn) historyBtn.disabled = ids.length !== 1;
    if (checkoutBtn) checkoutBtn.disabled = !selected.some((row) => row.dataset.canCheckout === "1");
    const checkinable = selected.filter((row) => row.dataset.canCheckin === "1");
    const queued = Number(checkinBtn?.dataset.newFiles || 0) + Number(checkinBtn?.dataset.pendingSaves || 0);
    if (checkinBtn) checkinBtn.disabled = checkinable.length === 0 && queued === 0;
    if (undoBtn) undoBtn.disabled = !selected.some((row) => row.dataset.owned === "1");
    if (workspaceBtn) workspaceBtn.disabled = !selected.some((row) => row.dataset.inWorkspace !== "1");
    if (purgeBtn) purgeBtn.disabled = !selected.some((row) => row.dataset.inWorkspace !== "0");
    if (removeBtn) removeBtn.disabled = ids.length === 0;
    const filtering = metricButtons().some((btn) => metricMode(btn) === "filter");
    const summary = $("#selection-summary");
    if (summary) {
      const count = selected.length || ids.length;
      if (count) {
        summary.hidden = false;
        summary.textContent = `${count} selected${filtering ? ". The list is filtered" : ""}.`;
      } else {
        summary.hidden = true;
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
      tab.textContent = pending ? `Files to check in · ${pending}` : "Files to check in";
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
    row.classList.toggle("is-selected");
    lastSelectRow = row;
    syncToolbar();
  }

  function selectOnly(row) {
    rows().forEach((item) => item.classList.toggle("is-selected", item === row));
    lastSelectRow = row;
    syncToolbar();
  }

  function selectRange(toRow, additive = false) {
    const visible = rows().filter((row) => !row.hidden);
    const end = visible.indexOf(toRow);
    const start = lastSelectRow ? visible.indexOf(lastSelectRow) : end;
    if (end < 0) return;
    const from = start < 0 ? end : Math.min(start, end);
    const until = start < 0 ? end : Math.max(start, end);
    if (!additive) {
      visible.forEach((row) => row.classList.remove("is-selected"));
    }
    visible.slice(from, until + 1).forEach((row) => row.classList.add("is-selected"));
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
      $("#forget-project-btn")?.dataset.project ||
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
      const name = btn.dataset.filter;
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
      let mode = saved[btn.dataset.filter];
      if (btn.dataset.filter === "files" && mode === "select") mode = "filter";
      if (mode !== "select" && mode !== "filter" && mode !== "off") return;
      setMetricMode(btn, mode);
      applied = true;
    });
    const files = metricButtons().find((btn) => btn.dataset.filter === "files");
    if (files && metricMode(files) !== "off") {
      metricButtons().forEach((item) => {
        if (item !== files && !isCheckoutMetric(item.dataset.filter)) setMetricMode(item, "off");
      });
    }
    const cadModels = metricButtons().find((btn) => btn.dataset.filter === "cad_models");
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
      const cmp = sortValue(a, key, columnIndex).localeCompare(
        sortValue(b, key, columnIndex),
        undefined,
        { numeric: true, sensitivity: "base" }
      );
      return dir === "asc" ? cmp : -cmp;
    });
    [...pending, ...sortable, ...empty].forEach((row) => tbody.appendChild(row));
  }

  function enableTableSort(table) {
    const heads = [...table.querySelectorAll("th[data-sort]")];
    if (!heads.length) return;
    table.tHead?.addEventListener("click", (event) => {
      const th = event.target.closest("th[data-sort]");
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
    const folder = event.target.closest(".folder-row");
    const folderLink = event.target.closest(".folder-open");
    if (folderLink && folder && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      openFolderRow(folder);
      return;
    }
    const row = event.target.closest(".object-row, .folder-row, .queue-row");
    if (!row) return;
    const openLink = event.target.closest(".object-open");
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
    if (event.target.closest(".folder-open")) {
      event.preventDefault();
      const folder = event.target.closest(".folder-row");
      if (folder) openFolderRow(folder);
      return;
    }
    if (event.target.closest(".folder-row")) return;
    if (event.target.closest(".object-open")) return;
    const row = event.target.closest(".object-row");
    if (!row?.dataset.detail) return;
    event.preventDefault();
    window.location.href = row.dataset.detail;
  }

  document.querySelector("#object-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#object-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#checked-out-table")?.addEventListener("click", onFileTableClick);
  document.querySelector("#checked-out-table")?.addEventListener("dblclick", onFileTableDblclick);
  document.querySelector("#changes-table")?.addEventListener("click", onFileTableClick);

  document.querySelector("#metric-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest(".metric");
    if (!btn || btn.disabled) return;
    const current = metricMode(btn);
    const key = btn.dataset.filter;
    const next = key === "files"
      ? (current === "filter" ? "off" : "filter")
      : (current === "off" ? "select" : current === "select" ? "filter" : "off");
    setMetricMode(btn, next);
    if (key === "files" && next !== "off") {
      metricButtons().forEach((item) => {
        if (item !== btn && !isCheckoutMetric(item.dataset.filter)) setMetricMode(item, "off");
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

  function hostedCreoJS() {
    try {
      return Boolean(
        window.CreoJS &&
          typeof window.CreoJS.isAvailable === "function" &&
          window.CreoJS.isAvailable()
      );
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

  function showCreoSessionControls() {
    document.querySelectorAll(".creo-session-only").forEach((el) => {
      el.hidden = !hostedCreoJS();
    });
  }
  void creoJSReady.then(showCreoSessionControls);

  async function setCreoWorkingDirectory() {
    const directory = setCreoDirBtn?.dataset.workspace || "";
    if (!directory) {
      showError($("#toolbar-error"), "No project workspace is selected.");
      return;
    }
    try {
      await creoJSReady;
      if (!hostedCreoJS()) {
        showError($("#toolbar-error"), "Open this page in Creo's built-in browser to set the working directory.");
        return;
      }
      await whenCreoJSReady();
      await window.CreoJS.setWorkingDirectory(directory);
      showOk("Creo working directory set to this project.");
    } catch (err) {
      const message = err && err.message ? err.message : String(err);
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

  async function openPdmObject(target) {
    await creoJSReady;
    if (hostedCreoJS()) {
      const prepared = await postAction(
        "/api/creo/open",
        openRequestBody(target, false),
        "POST",
        ""
      );
      if (!prepared) return null;
      if (prepared.creo_object) {
        try {
          await whenCreoJSReady();
          const opened = await window.CreoJS.openModel(
            prepared.working_directory,
            prepared.filename,
            prepared.creo_release || ""
          );
          const openedText = opened == null ? "" : String(opened);
          if (openedText.indexOf("CREOPDM_ERROR:") === 0) {
            showError($("#toolbar-error"), openedText.slice("CREOPDM_ERROR:".length));
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
      } else {
        return postAction("/api/creo/open", openRequestBody(target, true), "POST", "");
      }
      return prepared;
    }
    return postAction("/api/creo/open", openRequestBody(target, true), "POST", "");
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
      if (result) window.location.reload();
      return;
    }
    const result = await postAction("/api/objects/batch/checkout", { object_ids: objectIds }, "POST", "Checking out…");
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) window.location.reload();
  });

  workspaceBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) return;
    const result = await postAction("/api/objects/batch/workspace", { object_ids: ids }, "POST", "Copying to workspace…");
    if (!result) return;
    const warning = formatBatch(result);
    const copied = result.ok?.length || 0;
    if (warning) showError($("#toolbar-error"), warning);
    else showOk(`${copied} file(s) copied to the workspace.`);
  });

  openWorkspaceBtn?.addEventListener("click", async () => {
    const projectId = openWorkspaceBtn.dataset.project;
    if (!projectId) return;
    const folder = openWorkspaceBtn.dataset.folder || currentFolder() || "";
    const query = folder ? `?folder=${encodeURIComponent(folder)}` : "";
    const result = await postAction(
      `/api/projects/${projectId}/workspace/open${query}`,
      undefined,
      "POST",
      "Opening workspace…"
    );
    if (result) showOk("Opened the workspace folder.");
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
        window.location.reload();
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
    if (result.ok?.length) window.location.reload();
  });

  checkinBtn?.addEventListener("click", async () => {
    const queued = selectedRows().filter((row) => row.classList.contains("queue-row"));
    const owned = selectedRows().filter((row) => {
      return row.dataset.canCheckin === "1" && !row.classList.contains("queue-row");
    });
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
    const preview = await withBusy("Preparing check-in…", () =>
      fetch(
        useQueue
          ? `/api/projects/${projectId}/checkin-preview`
          : `/api/objects/${objectId}/checkin-preview`
      )
    );
    if (!preview.ok) {
      showError($("#toolbar-error"), await readError(preview));
      return;
    }
    const data = await preview.json();
    $("#checkin-filename").textContent = data.filename;
    $("#checkin-current").textContent = data.current_display;
    $("#checkin-next").textContent = data.next_display;
    ["checkin-current", "checkin-next", "checkin-current-label", "checkin-next-label"].forEach((itemId) => {
      const el = $("#" + itemId);
      if (el) el.hidden = useQueue;
    });
    $("#checkin-comment").value = "";
    if (checkinDialog) {
      checkinDialog.dataset.force = data.force_checkin ? "1" : "";
      checkinDialog.dataset.queue = useQueue ? "1" : "";
      checkinDialog.dataset.objectId = useQueue ? "" : objectId;
      const selectedIdsForQueue = queued
        .map((row) => row.dataset.uuid)
        .filter(Boolean);
      checkinDialog.dataset.objectIds = JSON.stringify(
        selectedIdsForQueue.length ? selectedIdsForQueue : data.object_ids || []
      );
    }
    const forceWarn = $("#checkin-force-warn");
    if (forceWarn) {
      forceWarn.hidden = !data.warning;
      forceWarn.textContent = data.warning || "";
    }
    const submitBtn = checkinForm?.querySelector("button[type='submit']");
    if (submitBtn) submitBtn.textContent = data.force_checkin ? "Check In anyway" : "Check In";
    const list = $("#checkin-changes");
    list.innerHTML = "";
    if (useQueue) {
      const wantedIds = new Set(queued.map((row) => row.dataset.uuid).filter(Boolean));
      const pendingNames = data.pending_files || [];
      const pendingIds = data.object_ids || [];
      const names = !queued.length
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
      if (!names.length && !newCount) {
        const item = document.createElement("li");
        item.textContent = "– Nothing to check in";
        list.appendChild(item);
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
    }
    const wrap = $("#checkin-new-wrap");
    const box = $("#checkin-new-files");
    const help = $("#checkin-new-help");
    if (help) {
      help.textContent = useQueue
        ? "New files found in the workspace. Checked items are added to the project with this check-in."
        : "New files found in the workspace. These are models Creo saved next to the checked-out file. Checked items are added to the project with this check-in.";
    }
    if (wrap && box) {
      box.innerHTML = "";
      const news = data.new_files || [];
      wrap.hidden = news.length === 0;
      const selectedNew = new Set(
        queued.map((row) => row.dataset.relativePath).filter(Boolean)
      );
      news.forEach((item) => {
        const label = document.createElement("label");
        label.className = "choice";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.relative_path;
        input.checked = queued.length
          ? selectedNew.has(item.relative_path)
          : Boolean(item.same_folder) || useQueue;
        label.appendChild(input);
        label.append(` ${item.filename}`);
        const hint = document.createElement("span");
        hint.className = "muted small";
        hint.textContent = ` ${item.relative_path}`;
        label.appendChild(hint);
        box.appendChild(label);
      });
    }
    checkinDialog.showModal();
  });

  $("#checkin-cancel")?.addEventListener("click", () => checkinDialog?.close());
  checkinForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = checkinDialog?.dataset.objectId || "";
    const comment = String($("#checkin-comment")?.value || "").trim();
    if (!comment) {
      showError($("#checkin-error"), "A check-in comment is required.");
      return;
    }
    if (checkinDialog?.dataset.force === "1") {
      const name = $("#checkin-filename")?.textContent || "This file";
      if (!window.confirm(`${name} is not checked out. Check in the workspace save anyway?`)) return;
    }
    const added = [...document.querySelectorAll("#checkin-new-files input:checked")].map(
      (input) => input.value
    );
    let result;
    if (checkinDialog?.dataset.queue === "1") {
      const projectId = checkinBtn?.dataset.project;
      if (!projectId) return;
      let objectIds = [];
      try {
        objectIds = JSON.parse(checkinDialog.dataset.objectIds || "[]");
      } catch {
        objectIds = [];
      }
      result = await postAction(`/api/projects/${projectId}/checkin-queue`, {
        comment,
        object_ids: objectIds,
        add_relative_paths: added,
      }, "POST", "Checking in…");
    } else {
      if (!id) return;
      result = await postAction(`/api/objects/${id}/checkin`, {
        comment,
        add_relative_paths: added,
      }, "POST", "Checking in…");
    }
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok ? result.ok.length : true) {
      rememberWatchView();
      window.location.reload();
    }
  });

  historyBtn?.addEventListener("click", () => {
    const row = selectedRows()[0];
    const href = row?.dataset.detail;
    if (href) window.location.href = href;
  });

  function confirmPurge(ids) {
    const n = ids.length;
    return window.confirm(
      n === 1
        ? "Remove this file from the workspace? Only the CreoPDM working copy is deleted. The original in your project folder stays. If you have it checked out, that checkout is cancelled."
        : `Remove ${n} files from the workspace? Only CreoPDM working copies are deleted. Originals in your project folder stay. Your checkouts on those files are cancelled.`
    );
  }

  function confirmRemove(ids) {
    const n = ids.length;
    return window.confirm(
      n === 1
        ? "Remove this file from the project? CreoPDM workspace copies are deleted. The original in your project folder is not deleted."
        : `Remove ${n} files from the project? CreoPDM workspace copies are deleted. Originals in your project folder are not deleted.`
    );
  }

  function projectHome() {
    return document.querySelector(".crumb a")?.href || "/";
  }

  purgeBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) return;
    if (!confirmPurge(ids)) return;
    if (ids.length === 1 && !isListPage) {
      const result = await postAction(`/api/objects/${ids[0]}/purge-workspace`, undefined, "POST", "Removing from workspace…");
      if (result) window.location.reload();
      return;
    }
    const result = await postAction("/api/objects/batch/purge-workspace", { object_ids: ids }, "POST", "Removing from workspace…");
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    else showOk(`${result.ok?.length || 0} file(s) removed from the workspace.`);
    if (result.ok?.length) window.location.reload();
  });

  removeBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) return;
    if (!confirmRemove(ids)) return;
    if (ids.length === 1 && !isListPage) {
      const result = await postAction(`/api/objects/${ids[0]}`, null, "DELETE", "Removing from project…");
      if (result) window.location.href = projectHome();
      return;
    }
    const result = await postAction("/api/objects/batch/remove", { object_ids: ids }, "POST", "Removing from project…");
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) window.location.reload();
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
    loadingCell.textContent = "Looking for workspace changes…";
    loading.appendChild(loadingCell);
    body.appendChild(loading);
    refreshTabMetrics();
    try {
      const response = await fetch(`/api/projects/${projectId}/checkin-queue`);
      if (!response.ok) throw new Error("queue");
      const data = await response.json();
      const saves = data.saves || [];
      const created = data.new_files || [];
      const pending = saves.length + created.length;
      if (tab) tab.textContent = pending ? `Files to check in · ${pending}` : "Files to check in";
      setCheckinQueueCounts(saves.length, created.length);
      body.replaceChildren();
      if (!pending) {
        const row = document.createElement("tr");
        row.className = "empty-row";
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "Nothing in the workspace is waiting to be checked in.";
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
        row.dataset.extension = ext;
        row.dataset.objectType = meta.objectType || typeFromExtension(ext);
        row.dataset.checkedOut = meta.checkedOut || "0";
        row.dataset.canCheckin = "1";
        if (meta.uuid) row.dataset.uuid = meta.uuid;
        if (meta.relativePath) row.dataset.relativePath = meta.relativePath;
        values.forEach((text, index) => {
          const cell = document.createElement("td");
          if (index === 1) {
            cell.className = "filename-cell";
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "object-open";
            btn.textContent = filename;
            btn.title = filename;
            if (meta.uuid) btn.dataset.uuid = meta.uuid;
            if (meta.relativePath) btn.dataset.relativePath = meta.relativePath;
            cell.appendChild(btn);
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
            item.file_size != null ? `${item.file_size} bytes` : "",
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
            "New file",
            item.filename || "",
            "Not in the project yet. Use Check In to add it.",
            item.size != null ? `${item.size} bytes` : "",
            "—",
          ],
          "",
          { filename: item.filename, objectType: item.object_type, relativePath: item.relative_path }
        );
      });
      refreshTabMetrics();
    } catch {
      body.replaceChildren();
      const row = document.createElement("tr");
      row.className = "empty-row";
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "Could not load workspace changes.";
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
    const names = {
      executable: "Parametric",
      view: "Creo View",
      association: "Windows",
      embedded: "Embedded",
    };
    const titles = {
      executable: parametricPath || "Opens CAD with Creo Parametric",
      view: viewPath || "Opens CAD with Creo View",
      association: "Opens CAD with the Windows file association",
      embedded: "Opens CAD in the Creo session showing this page",
    };
    const key = String(mode || "executable");
    const status = (pill.textContent || "Creo:").split("·")[0].trim() || "Creo:";
    pill.textContent = `${status} · ${names[key] || names.executable}`;
    pill.title = titles[key] || titles.executable;
  }

  settingsForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    showError($("#settings-error"), "");
    const ok = $("#settings-ok");
    if (ok) ok.hidden = true;
    const data = new FormData(settingsForm);
    const body = {
      creo_open_mode: String(data.get("creo_open_mode") || "executable"),
      creo_executable: String(data.get("creo_executable") || "").trim() || null,
      creo_view_executable: String(data.get("creo_view_executable") || "").trim() || null,
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
    const button = event.target.closest(".type-label-remove");
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
      creo_open_mode: String(new FormData(typeLabelsForm).get("creo_open_mode") || "executable"),
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

  const ownedIds = rows()
    .filter((row) => row.dataset.owned === "1")
    .map((row) => row.dataset.uuid);
  if (undoBtn?.dataset.uuid && !undoBtn.disabled) ownedIds.push(undoBtn.dataset.uuid);
  if (ownedIds.length) {
    setInterval(() => {
      ownedIds.forEach((id) => {
        fetch(`/api/objects/${id}/heartbeat`, { method: "POST" });
      });
    }, 60000);
  }

  const WATCH_KEY = "creopdmWatchRestore";
  function rememberWatchView() {
    const activeTab = document.querySelector(".tabs .tab.is-active")?.dataset.tab || "";
    sessionStorage.setItem(
      WATCH_KEY,
      JSON.stringify({
        ids: selectedIds(),
        tab: activeTab,
      })
    );
  }
  function restoreWatchView() {
    const raw = sessionStorage.getItem(WATCH_KEY);
    if (!raw) return;
    sessionStorage.removeItem(WATCH_KEY);
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
      rows().forEach((row) => row.classList.toggle("is-selected", wanted.has(row.dataset.uuid)));
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
      const response = await fetch(`/api/projects/${watchProjectId}/workspace-watch`);
      if (!response.ok) return;
      const data = await response.json();
      setCheckinQueueCounts(data.pending_saves, data.new_files);
      const next = data.stamp || "";
      if (watchStamp === null) {
        watchStamp = next;
        return;
      }
      if (next === watchStamp) return;
      watchStamp = next;
      window.clearTimeout(watchReloadTimer);
      watchReloadTimer = window.setTimeout(() => {
        if (watchPaused()) return;
        rememberWatchView();
        window.location.reload();
      }, 400);
    } catch {
      /* ignore a missed poll */
    }
  }

  if (watchProjectId) {
    setInterval(pollWorkspaceWatch, 2000);
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
