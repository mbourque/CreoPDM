(() => {
  const $ = (sel, root = document) => root.querySelector(sel);

  function showError(el, message) {
    if (!el) return;
    el.hidden = !message;
    el.textContent = message || "";
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
  function setBusy(message) {
    busyDepth += 1;
    const overlay = $("#busy-overlay");
    const text = $("#busy-message");
    if (text) text.textContent = message || "Working…";
    if (overlay) overlay.hidden = false;
    document.body.classList.add("is-busy");
    document.body.setAttribute("aria-busy", "true");
  }
  function clearBusy() {
    busyDepth = Math.max(0, busyDepth - 1);
    if (busyDepth > 0) return;
    const overlay = $("#busy-overlay");
    if (overlay) overlay.hidden = true;
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
  const METRIC_LABELS = {
    files: "all files",
    creo_parts: "Creo parts",
    assemblies: "assemblies",
    drawings: "drawings",
    documents: "documents",
    other: "non-CAD files",
    checked_out: "checked out files",
  };

  function metricButtons() {
    return [...document.querySelectorAll(".metric")];
  }

  function metricMode(btn) {
    return btn.dataset.mode || "off";
  }

  function rowMatchesMetric(row, key) {
    if (key === "checked_out") return row.dataset.checkedOut === "1";
    const types = FILTERS[key];
    return types === null || types.includes(row.dataset.objectType);
  }

  function setMetricMode(btn, mode) {
    btn.dataset.mode = mode;
    btn.classList.toggle("is-selected", mode === "select");
    btn.classList.toggle("is-filtered", mode === "filter");
    const label = METRIC_LABELS[btn.dataset.filter] || btn.dataset.filter;
    if (mode === "off") {
      btn.title = `Select ${label}. Click again to filter. Click a third time to clear.`;
    } else if (mode === "select") {
      btn.title = `Selected ${label}. Click to filter the list to this group.`;
    } else {
      btn.title = `Filtering to ${label}. Click to clear.`;
    }
  }

  function applyMetricVisibility() {
    const metrics = metricButtons();
    const filterBtns = metrics.filter((btn) => metricMode(btn) === "filter");
    const viewBtns = metrics.filter((btn) => {
      const mode = metricMode(btn);
      if (mode === "off" || !filterBtns.length) return false;
      if (mode === "select" && FILTERS[btn.dataset.filter] === null) return false;
      return true;
    });
    const q = searchInput?.value.trim().toLowerCase() || "";
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        const matchesSearch = !q || row.textContent.toLowerCase().includes(q);
        row.hidden = Boolean(q) && !matchesSearch;
        return;
      }
      const matchesSearch = !q || row.textContent.toLowerCase().includes(q);
      const matchesView = !viewBtns.length || viewBtns.some((btn) => rowMatchesMetric(row, btn.dataset.filter));
      row.hidden = !(matchesSearch && matchesView);
    });
  }

  function applyMetricSelection() {
    const active = metricButtons().filter((btn) => metricMode(btn) !== "off");
    rows().forEach((row) => {
      if (row.classList.contains("folder-row")) {
        if (!active.length) row.classList.remove("is-selected");
        return;
      }
      if (!active.length) {
        row.classList.remove("is-selected");
        return;
      }
      const matchesActive = active.some((btn) => rowMatchesMetric(row, btn.dataset.filter));
      row.classList.toggle("is-selected", !row.hidden && matchesActive);
    });
  }

  const projectDialog = $("#project-dialog");
  const projectForm = $("#project-form");
  const addDialog = $("#add-dialog");
  const addForm = $("#add-form");
  const checkinDialog = $("#checkin-dialog");
  const checkinForm = $("#checkin-form");
  const settingsForm = $("#settings-form");

  $("#new-project-btn")?.addEventListener("click", () => showProjectDialog("create"));
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
    window.location.href = "/";
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
    window.location.href = `/?project=${project.uuid}`;
  });

  let chosenPaths = [];
  let chosenBaseFolder = null;

  async function loadAddFolder() {
    const projectId = addForm?.dataset.project;
    const label = $("#add-folder-label");
    if (!projectId || !label) return;
    const response = await fetch(`/api/projects/${projectId}/workspace/add-folder`);
    if (!response.ok) return;
    const data = await response.json();
    label.textContent = `Opens in: ${data.initial_directory}`;
  }

  function chosenDisplayName(path, folder) {
    if (!folder) return path.split(/[/\\]/).pop() || path;
    const norm = String(path).replace(/\\/g, "/");
    const root = String(folder).replace(/\\/g, "/").replace(/\/$/, "");
    const prefix = root.toLowerCase() + "/";
    if (norm.toLowerCase().startsWith(prefix)) {
      return `${root.split("/").pop()}/${norm.slice(root.length + 1)}`;
    }
    return path.split(/[/\\]/).pop() || path;
  }

  function applyChosenPaths(paths, labelText, baseFolder) {
    chosenPaths = paths || [];
    chosenBaseFolder = baseFolder || null;
    const label = $("#add-folder-label");
    if (label && labelText) label.textContent = labelText;
    const list = $("#chosen-file-list");
    if (list) {
      list.innerHTML = "";
      chosenPaths.forEach((path) => {
        const item = document.createElement("li");
        item.textContent = chosenDisplayName(path, chosenBaseFolder);
        list.appendChild(item);
      });
    }
  }

  $("#add-files-btn")?.addEventListener("click", () => {
    showError($("#add-error"), "");
    chosenPaths = [];
    chosenBaseFolder = null;
    const list = $("#chosen-file-list");
    if (list) list.innerHTML = "";
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
        data.initial_directory ? `Opens in: ${data.initial_directory}` : ""
      );
      if (data.warning) showError($("#add-error"), data.warning);
    });
  });

  $("#choose-workspace-folder")?.addEventListener("click", async () => {
    const projectId = addForm?.dataset.project;
    if (!projectId) return;
    showError($("#add-error"), "");
    await withHtmlDialogClosed(addDialog, async () => {
      const response = await fetch(`/api/projects/${projectId}/workspace/choose-folder`, { method: "POST" });
      if (!response.ok) {
        showError($("#add-error"), await readError(response));
        return;
      }
      const data = await response.json();
      if (data.cancelled) return;
      if (data.warning) {
        applyChosenPaths([], data.initial_directory ? `Opens in: ${data.initial_directory}` : "");
        showError($("#add-error"), data.warning);
        return;
      }
      const folder = data.folder || data.initial_directory;
      applyChosenPaths(
        data.selected || [],
        folder ? `${(data.selected || []).length} file(s) from ${folder}` : "",
        folder
      );
      if (!(data.selected || []).length) {
        showError($("#add-error"), "No files to add were found in that folder.");
      }
    });
  });

  addForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectId = addForm.dataset.project;
    if (!projectId) return;
    if (!chosenPaths.length) {
      showError($("#add-error"), "Choose files or a folder first.");
      return;
    }
    const comment = String(new FormData(addForm).get("comment") || "").trim();
    const result = await withBusy("Adding files…", async () => {
      const response = await fetch(`/api/projects/${projectId}/objects/from-disk`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          paths: chosenPaths,
          comment: comment || null,
          base_folder: chosenBaseFolder,
        }),
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
  const rows = () => [...document.querySelectorAll(".object-row, .folder-row")];
  const isListPage = Boolean(document.querySelector("#object-table"));
  searchInput?.addEventListener("input", () => {
    applyMetricVisibility();
    syncToolbar();
  });

  const historyBtn = $("#history-btn");
  const openBtn = $("#open-btn");
  const checkoutBtn = $("#checkout-btn");
  const checkinBtn = $("#checkin-btn");
  const undoBtn = $("#undo-btn");
  const workspaceBtn = $("#workspace-btn");
  const openWorkspaceBtn = $("#open-workspace-btn");
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

  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.flatMap(rowObjectIds);
    if (openBtn) openBtn.disabled = ids.length !== 1;
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
      summary.textContent = ids.length
        ? `${ids.length} selected${filtering ? ". The list is filtered" : ""}. Copy to Workspace is for files that are not already in the workspace.`
        : "Click a count to select a group. Click a row to select it; Shift-click a range; Ctrl-click to add or remove. Click a filename to open it. Click a folder name to open the folder. Double-click a file for history.";
    }
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
      const mode = saved[btn.dataset.filter];
      if (mode !== "select" && mode !== "filter" && mode !== "off") return;
      if (btn.disabled) {
        setMetricMode(btn, "off");
        return;
      }
      setMetricMode(btn, mode);
      applied = true;
    });
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

  document.querySelector("#object-table")?.addEventListener("click", (event) => {
    const folder = event.target.closest(".folder-row");
    const folderLink = event.target.closest(".folder-open");
    if (folderLink && folder && !event.shiftKey && !event.ctrlKey && !event.metaKey) {
      event.preventDefault();
      openFolderRow(folder);
      return;
    }
    const row = event.target.closest(".object-row, .folder-row");
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
    if (!openLink?.dataset.uuid || event.detail > 1) return;
    void postAction("/api/creo/open", { object_id: openLink.dataset.uuid }, "POST", "");
  });

  document.querySelector("#object-table")?.addEventListener("dblclick", (event) => {
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
  });

  document.querySelector("#metric-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest(".metric");
    if (!btn || btn.disabled) return;
    const current = metricMode(btn);
    const next = current === "off" ? "select" : current === "select" ? "filter" : "off";
    setMetricMode(btn, next);
    if (next === "filter" && btn.dataset.filter !== "files") {
      metricButtons().forEach((item) => {
        if (item.dataset.filter === "files" && metricMode(item) !== "off") setMetricMode(item, "off");
      });
    }
    if (btn.dataset.filter === "files" && next !== "off") {
      metricButtons().forEach((item) => {
        if (item !== btn && metricMode(item) === "filter") setMetricMode(item, "select");
      });
    }
    applyMetricVisibility();
    applyMetricSelection();
    writeStoredFilters();
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

  openBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (ids.length !== 1) {
      showError($("#toolbar-error"), "Select one file to open.");
      return;
    }
    await postAction("/api/creo/open", { object_id: ids[0] }, "POST", "");
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
    const owned = selectedRows().filter((row) => row.dataset.canCheckin === "1");
    const projectId = checkinBtn.dataset.project || openWorkspaceBtn?.dataset.project;
    if (!checkinDialog) return;
    const fallbackId = checkinBtn.dataset.uuid || "";
    let objectId = "";
    if (owned.length === 1) {
      objectId = owned[0].dataset.uuid;
    } else if (!owned.length && fallbackId) {
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
      const selectedIdsForQueue = owned.map((row) => row.dataset.uuid);
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
      (data.pending_files || []).forEach((name) => {
        const item = document.createElement("li");
        item.textContent = `✓ Check in ${name}`;
        list.appendChild(item);
      });
      if (!(data.pending_files || []).length && !(data.new_files || []).length) {
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
      news.forEach((item) => {
        const label = document.createElement("label");
        label.className = "choice";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.value = item.relative_path;
        input.checked = Boolean(item.same_folder) || useQueue;
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

  let changesLoaded = false;
  async function loadChangesTab() {
    const projectId = checkinBtn?.dataset.project || openWorkspaceBtn?.dataset.project;
    const body = $("#changes-table tbody");
    const tab = document.querySelector('.tab[data-tab="changes"]');
    if (!projectId || !body || changesLoaded) return;
    changesLoaded = true;
    body.replaceChildren();
    const loading = document.createElement("tr");
    loading.className = "empty-row";
    const loadingCell = document.createElement("td");
    loadingCell.colSpan = 5;
    loadingCell.textContent = "Looking for workspace changes…";
    loading.appendChild(loadingCell);
    body.appendChild(loading);
    try {
      const response = await fetch(`/api/projects/${projectId}/checkin-queue`);
      if (!response.ok) throw new Error("queue");
      const data = await response.json();
      const saves = data.saves || [];
      const created = data.new_files || [];
      const pending = saves.length + created.length;
      if (tab) tab.textContent = pending ? `Would check in · ${pending}` : "Would check in";
      body.replaceChildren();
      if (!pending) {
        const row = document.createElement("tr");
        row.className = "empty-row";
        const cell = document.createElement("td");
        cell.colSpan = 5;
        cell.textContent = "Nothing in the workspace is waiting to be checked in.";
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      const addRow = (values, className) => {
        const row = document.createElement("tr");
        if (className) row.className = className;
        values.forEach((text) => {
          const cell = document.createElement("td");
          cell.textContent = text;
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
          "is-pending"
        );
      });
      created.forEach((item) => {
        addRow([
          "New file",
          item.filename || "",
          "Not in the project yet. Offered when you check in a nearby file.",
          item.size != null ? `${item.size} bytes` : "",
          "—",
        ]);
      });
    } catch {
      body.replaceChildren();
      const row = document.createElement("tr");
      row.className = "empty-row";
      const cell = document.createElement("td");
      cell.colSpan = 5;
      cell.textContent = "Could not load workspace changes.";
      row.appendChild(cell);
      body.appendChild(row);
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
      workspace_root: String(data.get("workspace_root") || "").trim() || null,
      cad_model_extensions: String(data.get("cad_model_extensions") || "")
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
      const next = (await response.json()).stamp || "";
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
    if (id) await postAction("/api/creo/open", { object_id: id }, "POST", "");
  });

  restoreStoredFilters();
  syncToolbar();
})();
