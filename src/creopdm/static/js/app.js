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
  };

  const projectDialog = $("#project-dialog");
  const projectForm = $("#project-form");
  const addDialog = $("#add-dialog");
  const addForm = $("#add-form");
  const checkinDialog = $("#checkin-dialog");
  const checkinForm = $("#checkin-form");
  const settingsForm = $("#settings-form");

  $("#new-project-btn")?.addEventListener("click", () => {
    showError($("#project-error"), "");
    projectDialog?.showModal();
  });
  $("#project-cancel")?.addEventListener("click", () => projectDialog?.close());

  projectForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(projectForm);
    const body = {
      name: String(data.get("name") || "").trim(),
      number: String(data.get("number") || "").trim() || null,
      description: String(data.get("description") || "").trim() || null,
      repository_path: String(data.get("repository_path") || "").trim(),
    };
    const response = await fetch("/api/projects", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!response.ok) {
      showError($("#project-error"), await readError(response));
      return;
    }
    const project = await response.json();
    window.location.href = `/?project=${project.uuid}`;
  });

  let chosenPaths = [];

  async function loadAddFolder() {
    const projectId = addForm?.dataset.project;
    const label = $("#add-folder-label");
    if (!projectId || !label) return;
    const response = await fetch(`/api/projects/${projectId}/workspace/add-folder`);
    if (!response.ok) return;
    const data = await response.json();
    label.textContent = `Opens in: ${data.initial_directory}`;
  }

  $("#add-files-btn")?.addEventListener("click", () => {
    showError($("#add-error"), "");
    chosenPaths = [];
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
    const response = await fetch(`/api/projects/${projectId}/workspace/choose-files`, { method: "POST" });
    if (!response.ok) {
      showError($("#add-error"), await readError(response));
      return;
    }
    const data = await response.json();
    const label = $("#add-folder-label");
    if (label && data.initial_directory) label.textContent = `Opens in: ${data.initial_directory}`;
    chosenPaths = data.selected || [];
    const list = $("#chosen-file-list");
    if (list) {
      list.innerHTML = "";
      chosenPaths.forEach((path) => {
        const item = document.createElement("li");
        item.textContent = path.split(/[/\\]/).pop() || path;
        list.appendChild(item);
      });
    }
  });

  addForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const projectId = addForm.dataset.project;
    if (!projectId) return;
    if (!chosenPaths.length) {
      showError($("#add-error"), "Choose at least one file from the workspace.");
      return;
    }
    const comment = String(new FormData(addForm).get("comment") || "").trim();
    const response = await fetch(`/api/projects/${projectId}/objects/from-disk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: chosenPaths, comment: comment || null }),
    });
    if (!response.ok) {
      showError($("#add-error"), await readError(response));
      return;
    }
    const result = await response.json();
    const failed = result.failed || [];
    if (failed.length && !result.ok?.length) {
      showError($("#add-error"), failed.map((item) => item.message).join(" "));
      return;
    }
    window.location.reload();
  });

  const searchInput = $("#search-input");
  const rows = () => [...document.querySelectorAll(".object-row")];
  const isListPage = Boolean(document.querySelector("#object-table"));
  searchInput?.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    rows().forEach((row) => {
      row.hidden = q ? !row.textContent.toLowerCase().includes(q) : false;
    });
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

  function selectedRows() {
    const picked = rows().filter((row) => row.classList.contains("is-selected") && !row.hidden);
    if (picked.length) return picked;
    if (checkoutBtn?.dataset.uuid) return [];
    return [];
  }

  function selectedIds() {
    const ids = selectedRows().map((row) => row.dataset.uuid).filter(Boolean);
    if (ids.length) return ids;
    const fallback = checkoutBtn?.dataset.uuid || openBtn?.dataset.uuid;
    return fallback ? [fallback] : [];
  }

  function syncToolbar() {
    if (!isListPage) return;
    const selected = selectedRows();
    const ids = selected.map((row) => row.dataset.uuid).filter(Boolean);
    if (openBtn) openBtn.disabled = ids.length !== 1;
    if (historyBtn) historyBtn.disabled = ids.length !== 1;
    if (checkoutBtn) checkoutBtn.disabled = !selected.some((row) => row.dataset.canCheckout === "1");
    if (checkinBtn) checkinBtn.disabled = selected.filter((row) => row.dataset.canCheckin === "1").length !== 1;
    if (undoBtn) undoBtn.disabled = !selected.some((row) => row.dataset.owned === "1");
    if (workspaceBtn) workspaceBtn.disabled = ids.length === 0;
    if (purgeBtn) purgeBtn.disabled = ids.length === 0;
    if (removeBtn) removeBtn.disabled = ids.length === 0;
    const summary = $("#selection-summary");
    if (summary) {
      summary.textContent = ids.length
        ? `${ids.length} selected. Checkout or To Workspace copies them into the workspace.`
        : "Click a count to select that group. Click a row to toggle one file.";
    }
    document.querySelectorAll(".metric").forEach((btn) => {
      const key = btn.dataset.filter;
      const types = FILTERS[key];
      const matches = rows().filter((row) => !row.hidden && (types === null || types.includes(row.dataset.objectType)));
      const allOn = matches.length > 0 && matches.every((row) => row.classList.contains("is-selected"));
      btn.classList.toggle("is-active", allOn);
    });
  }

  function toggleRow(row) {
    row.classList.toggle("is-selected");
    syncToolbar();
  }

  document.querySelector("#object-table")?.addEventListener("click", (event) => {
    if (event.target.closest("a")) return;
    const row = event.target.closest(".object-row");
    if (!row) return;
    toggleRow(row);
  });

  document.querySelector("#metric-filters")?.addEventListener("click", (event) => {
    const btn = event.target.closest(".metric");
    if (!btn) return;
    const types = FILTERS[btn.dataset.filter];
    const matches = rows().filter((row) => !row.hidden && (types === null || types.includes(row.dataset.objectType)));
    const allOn = matches.length > 0 && matches.every((row) => row.classList.contains("is-selected"));
    matches.forEach((row) => row.classList.toggle("is-selected", !allOn));
    syncToolbar();
  });

  async function postAction(url, body, method = "POST") {
    showError($("#toolbar-error"), "");
    showOk("");
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
    await postAction("/api/creo/open", { object_id: ids[0] });
  });

  checkoutBtn?.addEventListener("click", async () => {
    const ids = selectedRows().filter((row) => row.dataset.canCheckout === "1").map((row) => row.dataset.uuid);
    const fallback = selectedIds();
    const objectIds = ids.length ? ids : fallback;
    if (!objectIds.length) return;
    if (objectIds.length === 1 && !selectedRows().length) {
      const result = await postAction(`/api/objects/${objectIds[0]}/checkout`);
      if (result) window.location.reload();
      return;
    }
    const result = await postAction("/api/objects/batch/checkout", { object_ids: objectIds });
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) window.location.reload();
  });

  workspaceBtn?.addEventListener("click", async () => {
    const ids = selectedIds();
    if (!ids.length) return;
    const result = await postAction("/api/objects/batch/workspace", { object_ids: ids });
    if (!result) return;
    const warning = formatBatch(result);
    const copied = result.ok?.length || 0;
    if (warning) showError($("#toolbar-error"), warning);
    else showOk(`${copied} file(s) copied to the workspace.`);
  });

  openWorkspaceBtn?.addEventListener("click", async () => {
    const projectId = openWorkspaceBtn.dataset.project;
    if (!projectId) return;
    const result = await postAction(`/api/projects/${projectId}/workspace/open`);
    if (result) showOk("Opened the workspace folder.");
  });

  undoBtn?.addEventListener("click", async () => {
    const ids = selectedRows().filter((row) => row.dataset.owned === "1").map((row) => row.dataset.uuid);
    const fallback = selectedIds();
    const id = (ids[0] || fallback[0]);
    if (!id) return;
    const result = await postAction(`/api/objects/${id}/undo-checkout`);
    if (result) window.location.reload();
  });

  checkinBtn?.addEventListener("click", async () => {
    const owned = selectedRows().filter((row) => row.dataset.canCheckin === "1");
    const id = owned[0]?.dataset.uuid || selectedIds()[0];
    if (!id || !checkinDialog) return;
    showError($("#checkin-error"), "");
    const preview = await fetch(`/api/objects/${id}/checkin-preview`);
    if (!preview.ok) {
      showError($("#toolbar-error"), await readError(preview));
      return;
    }
    const data = await preview.json();
    $("#checkin-filename").textContent = data.filename;
    $("#checkin-current").textContent = data.current_display;
    $("#checkin-next").textContent = data.next_display;
    $("#checkin-comment").value = "";
    const list = $("#checkin-changes");
    list.innerHTML = "";
    [
      [data.file_modified, "File modified"],
      [data.parameters_changed, "Parameters changed"],
      [data.dependencies_unchanged, "Dependencies unchanged"],
    ].forEach(([flag, label]) => {
      const item = document.createElement("li");
      item.textContent = `${flag ? "✓" : "–"} ${label}`;
      list.appendChild(item);
    });
    const wrap = $("#checkin-new-wrap");
    const box = $("#checkin-new-files");
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
        input.checked = Boolean(item.same_folder);
        label.appendChild(input);
        label.append(` ${item.filename}`);
        const hint = document.createElement("span");
        hint.className = "muted small";
        hint.textContent = ` ${item.relative_path}`;
        label.appendChild(hint);
        box.appendChild(label);
      });
    }
    checkinDialog.dataset.objectId = id;
    checkinDialog.showModal();
  });

  $("#checkin-cancel")?.addEventListener("click", () => checkinDialog?.close());
  checkinForm?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const id = checkinDialog?.dataset.objectId || selectedIds()[0];
    const comment = String($("#checkin-comment")?.value || "").trim();
    if (!id) return;
    if (!comment) {
      showError($("#checkin-error"), "A check-in comment is required.");
      return;
    }
    const result = await postAction(`/api/objects/${id}/checkin`, {
      comment,
      add_relative_paths: [...document.querySelectorAll("#checkin-new-files input:checked")].map(
        (input) => input.value
      ),
    });
    if (result) window.location.reload();
  });

  historyBtn?.addEventListener("click", () => {
    const row = selectedRows()[0];
    const link = row?.querySelector("a");
    if (link) window.location.href = `${link.href}#history`;
  });

  function confirmPurge(ids) {
    const n = ids.length;
    return window.confirm(
      n === 1
        ? "Remove this file from the workspace? The project copy stays in the vault. If you have it checked out, that checkout is cancelled."
        : `Remove ${n} files from the workspace? Project copies stay in the vault. Your checkouts on those files are cancelled.`
    );
  }

  function confirmRemove(ids) {
    const n = ids.length;
    return window.confirm(
      n === 1
        ? "Permanently remove this file from the project? This deletes the vault file and workspace copies. You cannot undo this from CreoPDM."
        : `Permanently remove ${n} files from the project? This deletes vault files and workspace copies. You cannot undo this from CreoPDM.`
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
      const result = await postAction(`/api/objects/${ids[0]}/purge-workspace`);
      if (result) window.location.reload();
      return;
    }
    const result = await postAction("/api/objects/batch/purge-workspace", { object_ids: ids });
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
      const result = await postAction(`/api/objects/${ids[0]}`, null, "DELETE");
      if (result) window.location.href = projectHome();
      return;
    }
    const result = await postAction("/api/objects/batch/remove", { object_ids: ids });
    if (!result) return;
    const warning = formatBatch(result);
    if (warning) showError($("#toolbar-error"), warning);
    if (result.ok?.length) window.location.reload();
  });

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

  syncToolbar();
})();
