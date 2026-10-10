window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.add = {
  openAddDialog: null,
  openCompressedDialog: null,
  isInFlight: null,

  init(shell) {
    const $ = shell.$;
    const withBusy = shell.withBusy;
    const setBusy = shell.setBusy;
    const setBusyMessage = shell.setBusyMessage;
    const clearBusy = shell.clearBusy;
    const publishBusyMessage = shell.publishBusyMessage;
    const showError = shell.showError;
    const readError = shell.readError;
    const reloadPage = shell.reloadPage;
    const currentProductId = shell.currentProductId;
    const currentFolder = shell.currentFolder;
    const assertProductAllows = shell.assertProductAllows;
    const agentBase = shell.agentBase;
    const agentAuthHeaders = shell.agentAuthHeaders;
    const agentPdmAuth = shell.agentPdmAuth;
    const probeCreoAgent = shell.probeCreoAgent;
    const indexWhereUsedUnderBusy = shell.indexWhereUsedUnderBusy;
    const canGatherCreoMetadata = shell.canGatherCreoMetadata;
    const pushCreoMetadataForItems = shell.pushCreoMetadataForItems;
    const metadataTargetsFromResult = shell.metadataTargetsFromResult;
    const confirmLargeBulk = shell.confirmLargeBulk;
    const defaultAddHistoryComment = shell.defaultAddHistoryComment;
    const withHtmlDialogClosed = shell.withHtmlDialogClosed;
    const closeAddMenu = shell.closeAddMenu;
    const logicalUploadName = shell.logicalUploadName;
    const PathBasename = shell.PathBasename;
    const purgeableExtensionSet = shell.purgeableExtensionSet;
    const isImportVersionedExtension = shell.isImportVersionedExtension;
    const addPageListener =
      shell.addPageListener ||
      ((target, type, listener, options) => target.addEventListener(type, listener, options));
    function onPage(el, type, listener, options) {
      if (!el) return;
      addPageListener(el, type, listener, options);
    }
    const mod = window.__creopdmModules.add;

    const addDialog = $("#add-dialog");
    const addForm = $("#add-form");

    let chosenPaths = [];
    let chosenBaseFolder = null;
    let chosenFolders = [];
    let chosenUploads = [];
    let chosenAgentPaths = [];
    let chosenAgentBaseFolder = null;
    let chosenAgentFolderBatches = [];
    let importIgnorePatterns = [];
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
      // logicalUploadName / creoSaveNumber (shared in app.js) read this list.
      shell.setImportExtensions(
        Array.isArray(data.import_extensions)
          ? data.import_extensions.map((item) => String(item || "").toLowerCase())
          : []
      );
      if (!data.native_picker) {
        label.textContent = "Choose files or a folder in this browser. Copies go into the vault.";
        return;
      }
      label.textContent = `Opens in: ${data.initial_directory}`;
    }

    function fileCountLabel(count) {
      return count === 1 ? "1 file" : `${count} files`;
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

    function logicalRelativePath(rel) {
      const norm = String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
      const parts = norm.split("/").filter(Boolean);
      const name = parts.pop() || "";
      const logical = logicalUploadName(name);
      return parts.length ? `${parts.join("/")}/${logical}` : logical;
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

    function uploadExtension(name) {
      const logical = logicalUploadName(PathBasename(name)).toLowerCase();
      const dot = logical.lastIndexOf(".");
      return dot >= 0 ? logical.slice(dot) : "";
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
      onPage(node, "dragenter", (event) => {
        event.preventDefault();
        depth += 1;
        mark(true);
      });
      onPage(node, "dragover", (event) => {
        event.preventDefault();
        if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
      });
      onPage(node, "dragleave", () => {
        depth -= 1;
        if (depth <= 0) {
          depth = 0;
          mark(false);
        }
      });
      onPage(node, "drop", (event) => {
        event.preventDefault();
        depth = 0;
        mark(false);
        onFiles(event.dataTransfer);
      });
    }

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

    onPage($("#compressed-choose-btn"), "click", () => {
      void chooseCompressedZip();
    });
    onPage($("#compressed-cancel"), "click", () => compressedDialog?.close());
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

    onPage(compressedForm, "submit", async (event) => {
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
      const zipGate = await assertProductAllows(productId, "checkin", {
        errorEl: $("#compressed-error"),
      });
      if (!zipGate.ok) return;
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

    onPage($("#choose-workspace-files"), "click", async () => {
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

    onPage($("#choose-workspace-folder"), "click", async () => {
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

    bindDropTarget($("#dropzone"), (transfer) => {
      handleDroppedTransfer(transfer);
    });

    onPage(addForm, "submit", async (event) => {
      event.preventDefault();
      if (addInFlight) {
        showError($("#add-error"), "Add is already running — wait for it to finish.");
        return;
      }
      const productId = addForm.dataset.product;
      if (!productId) return;
      const addGate = await assertProductAllows(productId, "checkin", {
        errorEl: $("#add-error"),
      });
      if (!addGate.ok) return;
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
          }
        );
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

    mod.acceptPageDrop = acceptPageDrop;

    mod.configureAddDialog = configureAddDialog;
    mod.openAddDialog = openAddDialog;
    mod.openCompressedDialog = openCompressedDialog;
    mod.isInFlight = () => addInFlight;

    onPage($("#add-cancel"), "click", () => addDialog?.close());
  },
};
