window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.modifications = {
  init(shell) {
    const mod = window.__creopdmModules.modifications;
    const $ = shell.$;
    const withBusy = shell.withBusy;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const readError = shell.readError;
    const reloadPage = shell.reloadPage;
    const eventEl = shell.eventEl;
    const currentProductId = shell.currentProductId;
    const currentVaultFolder = shell.currentVaultFolder;
    const assertProductAllows = shell.assertProductAllows;
    const probeCreoAgent = shell.probeCreoAgent;
    const materializeViaAgent = shell.materializeViaAgent;
    const abortSignalAfter = shell.abortSignalAfter;
    const publishBusyMessage = shell.publishBusyMessage;
    const gatherCreoMetadataForFilename = shell.gatherCreoMetadataForFilename;
    const aiSnapshotBodyFromGather = shell.aiSnapshotBodyFromGather;
    const aiFeaturesEnabled = shell.aiFeaturesEnabled;
    const canGatherCreoMetadata = shell.canGatherCreoMetadata;
    const waitForCreoMetadataBridge = shell.waitForCreoMetadataBridge;
    const confirmByProductName = shell.confirmByProductName;
    const tryEraseModelsFromCreoSession = shell.tryEraseModelsFromCreoSession;
    const creoYieldForDeferredErase = shell.creoYieldForDeferredErase;
    const CREO_REVERT_SESSION_HINT = shell.CREO_REVERT_SESSION_HINT;
    const setToolbarActionVisible = shell.setToolbarActionVisible;
    const syncDetailToolbar = shell.syncDetailToolbar;
    const agentWorkdir = shell.agentWorkdir;
    const listAgentCacheFiles = shell.listAgentCacheFiles;
    const listAgentCacheFilesPreferringVault = shell.listAgentCacheFilesPreferringVault;
    const ensureProductObjects = shell.ensureProductObjects;
    const latestLocalCacheTipForObject = shell.latestLocalCacheTipForObject;
    const resolveNewerLocalCacheSaves = shell.resolveNewerLocalCacheSaves;
    const loadCheckinQueueParts = shell.loadCheckinQueueParts;
    const logicalUploadName = shell.logicalUploadName;
    const PathBasename = shell.PathBasename;
    const creoSaveNumber = shell.creoSaveNumber;
    const looksLikeLocalWindowsPath = shell.looksLikeLocalWindowsPath;
    const joinLocalWorkspacePath = shell.joinLocalWorkspacePath;
    const rememberPendingCheckinIds = shell.rememberPendingCheckinIds;
    const checkinDialog = shell.checkinDialog;
    const addPageListener =
      shell.addPageListener ||
      ((target, type, listener, options) => target.addEventListener(type, listener, options));
    function onPage(el, type, listener, options) {
      if (!el) return;
      addPageListener(el, type, listener, options);
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
      return `=== ${roleLabel} (${rev}) ===\n${text}`;
    }

    function aiSnapshotPanel() {
      return $("#panel-snapshot") || $("#panel-compare-revisions");
    }

    function syncAiSnapshotAskVisibility(livePendingReady) {
      const askRow = $("#ai-snapshot-ask-row");
      const askAiBtn = $("#ai-snapshot-ask-ai");
      if (!askRow) return;
      const mode = String($("#ai-snapshot-compare")?.dataset.mode || "");
      const rightIsModified = isAiSnapshotModifiedValue(
        $("#ai-snapshot-rev-b")?.value
      );
      // What changed works with AI off; Ask AI stays gated.
      let rowReady = false;
      if (mode === "pending" || rightIsModified) {
        rowReady = Boolean(livePendingReady);
      } else if (mode === "compare") {
        rowReady = true;
      }
      askRow.hidden = !rowReady;
      if (askAiBtn) {
        askAiBtn.hidden = !rowReady || !aiFeaturesEnabled();
      }
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
      // Live binding: app.js reassigns the cache object (not a stable reference).
      const checkinQueueCache = shell.checkinQueueCache;
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
      // Live binding: app.js reassigns this Set when pending ids are remembered.
      const wasPending = shell.pendingCheckinIds.has(objectId);
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

    async function copyTextToClipboard(text, opts) {
      // Creo's embedded browser often lacks navigator.clipboard (or blocks it).
      // Prefer the Clipboard API, then execCommand('copy') via a temporary textarea.
      // When a modal <dialog> is open, append the textarea inside it — body-level
      // execCommand often fails while the dialog holds top-layer focus.
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
      const openDialog = aiSnapshotResultDialog();
      const host =
        (opts && opts.root && opts.root.nodeType === 1)
          ? opts.root
          : (openDialog && openDialog.open ? openDialog : document.body);
      try {
        const ta = document.createElement("textarea");
        ta.value = value;
        ta.setAttribute("readonly", "");
        ta.style.cssText =
          "position:fixed;left:0;top:0;width:1px;height:1px;padding:0;margin:0;"
          + "border:0;opacity:0;overflow:hidden;";
        host.appendChild(ta);
        ta.focus();
        ta.select();
        ta.setSelectionRange(0, value.length);
        const ok = document.execCommand("copy");
        host.removeChild(ta);
        return Boolean(ok);
      } catch {
        return false;
      }
    }

    function copyElementTextToClipboard(el) {
      if (!el) return false;
      try {
        const sel = window.getSelection();
        if (!sel) return false;
        const range = document.createRange();
        range.selectNodeContents(el);
        sel.removeAllRanges();
        sel.addRange(range);
        const ok = document.execCommand("copy");
        sel.removeAllRanges();
        return Boolean(ok);
      } catch {
        return false;
      }
    }

    function formatAiWhatChangedPayload(payload) {
      const diff = String(payload?.computed_differences || "").trim();
      if (diff) return diff;
      return "=== Computed differences ===\n(none)";
    }

    function _englishListToBullets(title, listText) {
      const raw = String(listText || "").replace(/\.$/, "").trim();
      if (!raw) return [title + ":"];
      const names = raw
        .split(/\s*,\s*|\s+and\s+/i)
        .map((s) => s.trim())
        .filter(Boolean);
      return [title + ":", ...names.map((n) => `- ${n}`)];
    }

    /**
     * What changed modal only (Computed differences): drop banner / empty “(none)”,
     * space sections. Does not rewrite Ask AI prose into bullets.
     */
    function formatAiWhatChangedDisplay(rawDiff) {
      const kept = [];
      const pushSection = (lines) => {
        if (!lines.length) return;
        if (kept.length) kept.push("");
        kept.push(...lines);
      };
      let pending = [];
      const flushPending = () => {
        if (!pending.length) return;
        pushSection(pending);
        pending = [];
      };
      for (const raw of String(rawDiff || "").split(/\r?\n/)) {
        const line = raw.trimEnd();
        const t = line.trim();
        if (!t) continue;
        if (/^=== Computed differences ===$/i.test(t)) continue;
        if (/:\s*\(none\)\s*$/i.test(t)) continue;

        // Server may still emit older one-line SimpRep prose in Computed differences.
        let m = t.match(/^Added simplified representations\s+(.+)$/i);
        if (m) {
          flushPending();
          pushSection(_englishListToBullets("Simplified representations added", m[1]));
          continue;
        }
        m = t.match(/^Removed simplified representations\s+(.+)$/i);
        if (m) {
          flushPending();
          pushSection(
            _englishListToBullets("Simplified representations removed", m[1])
          );
          continue;
        }
        m = t.match(/^Active simplified representation changed:\s*(.+)$/i);
        if (m) {
          flushPending();
          pushSection([
            "Active simplified representation changed:",
            `- ${m[1].trim()}`,
          ]);
          continue;
        }

        const isHeader = /:\s*$/.test(t) && !t.startsWith("-");
        if (isHeader) {
          flushPending();
          pending = [line];
          continue;
        }
        if (!pending.length) pending = [];
        pending.push(line);
      }
      flushPending();
      if (!kept.length) return "No computed differences.";
      return kept.join("\n");
    }

    /**
     * Ask AI modal: keep model prose (no bullets). Split into short paragraphs so
     * the modal matches Copy — models often glue SimpRep onto the dimensions line.
     */
    function formatAiSummaryDisplay(rawSummary) {
      let text = String(rawSummary || "").trim();
      if (!text) return "";
      // ", and simplified representations X, Y" → its own sentence/paragraph.
      text = text.replace(
        /,\s*and\s+(simplified representations?\s+)/gi,
        ".\n\nAdded $1"
      );
      // Sentence ends → blank line (Copy already had this; modal must show it too).
      text = text.replace(/([.!?])\s+(?=[A-Z0-9])/g, "$1\n\n");
      // Title-case section openers still stuck mid-paragraph (no /i — "the removed
      // features" must not become its own paragraph).
      text = text.replace(
        /([^\n])\s+(?=(?:Added|Removed)\s+(?:components?|dimensions?|features?|simplified representations?)\b)/g,
        "$1\n\n"
      );
      return text
        .replace(/[ \t]+\n/g, "\n")
        .replace(/\n{3,}/g, "\n\n")
        .trim();
    }

    /**
     * Render paragraphs + hard line breaks so CEF shows What changed bullets and
     * AI summary sentence breaks (plain \\n / pre-wrap is unreliable there).
     */
    function fillAiSnapshotResultBody(el, text) {
      if (!el) return;
      el.replaceChildren();
      const raw = String(text || "");
      const blocks = raw.split(/\n\s*\n/).map((b) => b.trim()).filter(Boolean);
      if (!blocks.length) {
        el.textContent = "";
        return;
      }
      for (const block of blocks) {
        const p = document.createElement("p");
        p.className = "ai-snapshot-result-para";
        const lines = block.split(/\n/);
        lines.forEach((line, i) => {
          if (i) p.appendChild(document.createElement("br"));
          p.appendChild(document.createTextNode(line));
        });
        el.appendChild(p);
      }
    }

    function aiSnapshotResultDialog() {
      return $("#ai-snapshot-result-dialog");
    }

    function resetAiSnapshotResultScroll() {
      const dialog = aiSnapshotResultDialog();
      const form = $("#ai-snapshot-result-form");
      const bodyEl = $("#ai-snapshot-result-body");
      if (dialog) dialog.scrollTop = 0;
      if (form) form.scrollTop = 0;
      if (bodyEl) bodyEl.scrollTop = 0;
    }

    function openAiSnapshotResultDialog({ title, meta, body, showCopy, copyText }) {
      const dialog = aiSnapshotResultDialog();
      const titleEl = $("#ai-snapshot-result-title");
      const metaEl = $("#ai-snapshot-result-meta");
      const bodyEl = $("#ai-snapshot-result-body");
      const copyBtn = $("#ai-snapshot-result-copy");
      if (!dialog || typeof dialog.showModal !== "function") {
        showError($("#toolbar-error"), "Could not open the result dialog.");
        return;
      }
      if (titleEl) titleEl.textContent = String(title || "").trim() || "Result";
      if (metaEl) metaEl.textContent = String(meta || "").trim();
      const text = String(body || "");
      if (bodyEl) {
        fillAiSnapshotResultBody(bodyEl, text);
        bodyEl.classList.toggle(
          "is-empty",
          /^No computed differences\.?$/i.test(text.trim())
        );
      }
      if (copyBtn) {
        copyBtn.hidden = !showCopy;
        copyBtn.dataset.copyText = showCopy
          ? String(copyText != null ? copyText : text)
          : "";
      }
      resetAiSnapshotResultScroll();
      if (!dialog.open) dialog.showModal();
      // Do not let focus jump to Close at the bottom (scrolls long diffs off the top).
      if (titleEl) {
        if (!titleEl.hasAttribute("tabindex")) titleEl.setAttribute("tabindex", "-1");
        try {
          titleEl.focus({ preventScroll: true });
        } catch {
          titleEl.focus();
        }
      }
      resetAiSnapshotResultScroll();
      requestAnimationFrame(() => resetAiSnapshotResultScroll());
    }

    function closeAiSnapshotResultDialog() {
      const dialog = aiSnapshotResultDialog();
      if (dialog?.open) dialog.close();
    }

    async function postAiSnapshotCompareUrl(url, body, timeoutMs, timeoutHint) {
      let response;
      try {
        response = await fetch(url, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          credentials: "same-origin",
          cache: "no-store",
          signal: abortSignalAfter(timeoutMs),
          body: JSON.stringify(body),
        });
      } catch (errFetch) {
        const aborted =
          errFetch?.name === "AbortError"
          || /aborted|timeout/i.test(String(errFetch?.message || errFetch || ""));
        throw new Error(
          aborted
            ? timeoutHint
            : String(errFetch?.message || errFetch || "Could not reach CreoPDM.")
        );
      }
      if (!response.ok) throw new Error(await readError(response));
      return response.json();
    }

    function aiSnapshotCompareRequestBody() {
      const mode = String($("#ai-snapshot-compare")?.dataset.mode || "");
      const olderId = String($("#ai-snapshot-rev-a")?.value || "").trim();
      const newerId = String($("#ai-snapshot-rev-b")?.value || "").trim();
      if (mode === "pending" || isAiSnapshotModifiedValue(newerId)) {
        const gather = aiSnapshotPendingGather;
        if (!gather?.snapshot) {
          throw new Error(
            "Gather a live workspace outline first (open the model in Creo or Save a local tip)."
          );
        }
        return {
          kind: "pending",
          body: {
            newer_snapshot: gather.snapshot,
            newer_display_revision: gather.displayRevision || "Modified",
            older_version_id: olderId || null,
          },
        };
      }
      if (mode !== "compare") {
        throw new Error("Need two revisions with snapshots before comparing.");
      }
      if (!olderId || !newerId) {
        throw new Error("Choose older and newer snapshot revisions.");
      }
      if (olderId === newerId) {
        throw new Error("Pick two different revisions to compare.");
      }
      return {
        kind: "history",
        body: {
          older_version_id: olderId,
          newer_version_id: newerId,
        },
      };
    }

    async function showAiWhatChanged() {
      const panel = aiSnapshotPanel();
      const objectId = String(panel?.dataset.objectId || "").trim();
      const compare = $("#ai-snapshot-compare");
      if (!objectId || !compare) {
        showError($("#toolbar-error"), "Open Modifications first.");
        return;
      }
      showError($("#toolbar-error"), "");
      try {
        const { text, meta } = await withBusy("Building what changed…", async () => {
          const req = aiSnapshotCompareRequestBody();
          const url =
            req.kind === "pending"
              ? `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/what-changed-pending`
              : `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/what-changed`;
          const payload = await postAiSnapshotCompareUrl(
            url,
            req.body,
            60_000,
            "Timed out building the What changed preview."
          );
          const olderRev = String(payload?.older_display_revision || "").trim();
          const newerRev = String(payload?.newer_display_revision || "").trim();
          return {
            text: formatAiWhatChangedPayload(payload),
            meta: olderRev && newerRev ? `${olderRev} → ${newerRev}` : "",
          };
        });
        const display = formatAiWhatChangedDisplay(text);
        openAiSnapshotResultDialog({
          title: "What changed",
          meta,
          body: display,
          showCopy: true,
          copyText: display,
        });
      } catch (err) {
        showError(
          $("#toolbar-error"),
          String(err?.message || err || "Could not build What changed.")
        );
      }
    }

    async function askAiSnapshotCompare() {
      const panel = aiSnapshotPanel();
      const objectId = String(panel?.dataset.objectId || "").trim();
      const compare = $("#ai-snapshot-compare");
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

      try {
        const payload = await withBusy("Asking AI what changed…", async () => {
          const req = aiSnapshotCompareRequestBody();
          const url =
            req.kind === "pending"
              ? `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/compare-pending`
              : `/api/objects/${encodeURIComponent(objectId)}/ai-snapshot/compare`;
          return postAiSnapshotCompareUrl(
            url,
            req.body,
            120_000,
            "Ollama timed out after 2 minutes. Is it running on the CreoPDM server and is the model loaded?"
          );
        });
        const summary = String(payload?.summary || "").trim();
        if (!summary) {
          showError($("#toolbar-error"), "Ollama returned an empty summary.");
          return;
        }
        const olderRev = String(payload?.older_display_revision || "").trim();
        const newerRev = String(payload?.newer_display_revision || "").trim();
        const model = String(payload?.model || "").trim();
        const parts = [];
        if (olderRev && newerRev) parts.push(`${olderRev} → ${newerRev}`);
        if (model) parts.push(model);
        const display = formatAiSummaryDisplay(summary);
        openAiSnapshotResultDialog({
          title: "AI summary",
          meta: parts.join(" · "),
          body: display,
          showCopy: true,
          copyText: display,
        });
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
        onPage($(`#ai-snapshot-rev-${pane}`), "change", () => {
          const selectA = $("#ai-snapshot-rev-a");
          const selectB = $("#ai-snapshot-rev-b");
          fillAiSnapshotOrderedSelects(
            selectA?.value,
            selectB?.value,
            pane === "a" ? "old" : "new"
          );
          void renderAiSnapshotCompare(objectId).then(() => resetAiSnapshotScroll());
        });
        onPage($(`#ai-snapshot-copy-${pane}`), "click", async () => {
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
      onPage(rail, "scroll", () => {
        applyAiSnapshotScrollOffset(rail.scrollTop || 0);
      });
      // Wheel over either text pane drives the center scrollbar only.
      const diffRow = $("#ai-snapshot-diff-row");
      onPage(
        diffRow,
        "wheel",
        (event) => {
          if (!rail) return;
          if (Math.abs(event.deltaY) < Math.abs(event.deltaX)) return;
          event.preventDefault();
          rail.scrollTop += event.deltaY;
        },
        { passive: false }
      );
      onPage(window, "resize", () => {
        syncAiSnapshotScrollLayout();
      });
      onPage($("#ai-snapshot-what-changed"), "click", () => {
        void showAiWhatChanged();
      });
      onPage($("#ai-snapshot-ask-ai"), "click", () => {
        void askAiSnapshotCompare();
      });
      const resultDialog = aiSnapshotResultDialog();
      onPage($("#ai-snapshot-result-close"), "click", () => {
        closeAiSnapshotResultDialog();
      });
      onPage($("#ai-snapshot-result-copy"), "click", async () => {
        const btn = $("#ai-snapshot-result-copy");
        const body = $("#ai-snapshot-result-body");
        const dialog = aiSnapshotResultDialog();
        // Prefer dataset (keeps \\n\\n); <p> textContent can collapse breaks.
        let text = String(btn?.dataset.copyText || "").trim();
        if (!text && body) text = String(body.textContent || "").trim();
        if (!text) {
          showError($("#toolbar-error"), "Nothing to copy yet.");
          return;
        }
        let ok = await copyTextToClipboard(text, { root: dialog || undefined });
        if (!ok && body) ok = copyElementTextToClipboard(body);
        if (!ok) {
          showError(
            $("#toolbar-error"),
            "Could not copy. Select the text and use Ctrl+C."
          );
          return;
        }
        if (btn) {
          const prev = btn.textContent;
          btn.textContent = "Copied";
          btn.disabled = true;
          window.setTimeout(() => {
            btn.textContent = prev || "Copy";
            btn.disabled = false;
          }, 1200);
        }
      });
      // Esc is native <dialog> cancel; click the dimmed backdrop to close.
      onPage(resultDialog, "click", (event) => {
        if (event.target === resultDialog) closeAiSnapshotResultDialog();
      });
    }

    mod.loadAiSnapshotTab = loadAiSnapshotTab;
    mod.syncRevertVersionButton = syncRevertVersionButton;
    mod.askAiCheckinComment = askAiCheckinComment;
    mod.clearAiSnapshotClientCache = clearAiSnapshotClientCache;
    mod.selectHistoryVersionRow = selectHistoryVersionRow;

    bindAiSnapshotControls();

    onPage($("#panel-history"), "click", (event) => {
      const row = eventEl(event)?.closest("tr.version-row");
      if (!row || !row.closest("#panel-history")) return;
      event.preventDefault();
      selectHistoryVersionRow(row);
    });

    onPage($("#revert-version-btn"), "click", async () => {
      const btn = $("#revert-version-btn");
      const row = selectedHistoryVersionRow();
      const objectId = btn?.dataset.object || "";
      const versionId = row?.dataset.versionUuid || "";
      const display = row?.dataset.versionDisplay || "this version";
      if (!btn || btn.disabled || !objectId || !versionId || row?.dataset.canRevert !== "1") return;
      const revertGate = await assertProductAllows(currentProductId(), "checkin");
      if (!revertGate.ok) return;
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
  },
};
