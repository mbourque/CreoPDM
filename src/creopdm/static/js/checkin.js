window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.checkin = {
  /**
   * Check-in / Add selected: preview dialog, vault sync, queue submit, Ask AI comment.
   * Loaded lazily (ensureModule("checkin")) on first Check In — Files browse never needs it.
   */
  init(shell) {
    const mod = window.__creopdmModules.checkin;
    const $ = shell.$;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const withBusy = shell.withBusy;
    const setBusyMessage = shell.setBusyMessage;
    const readError = shell.readError;
    const postAction = shell.postAction;
    const assertProductAllows = shell.assertProductAllows;
    const currentProductId = shell.currentProductId;
    const confirmLargeBulk = shell.confirmLargeBulk;
    const defaultAddHistoryComment = shell.defaultAddHistoryComment;
    const listAgentCacheFiles = shell.listAgentCacheFiles;
    const ensureProductObjects = shell.ensureProductObjects;
    const loadKnownWorkspacePaths = shell.loadKnownWorkspacePaths;
    const localOnlyCacheFiles = shell.localOnlyCacheFiles;
    const resolveNewerLocalCacheSaves = shell.resolveNewerLocalCacheSaves;
    const pushLocalWorkspaceToVault = shell.pushLocalWorkspaceToVault;
    const pushLocalNewPathsToVault = shell.pushLocalNewPathsToVault;
    const PathBasename = shell.PathBasename;
    const logicalUploadName = shell.logicalUploadName;
    const isCreoMetadataCandidate = shell.isCreoMetadataCandidate;
    const aiFeaturesEnabled = shell.aiFeaturesEnabled;
    const canGatherCreoMetadata = shell.canGatherCreoMetadata;
    const formatBatch = shell.formatBatch;
    const applyUndoCheckoutOnRows = shell.applyUndoCheckoutOnRows;
    const applyCheckedInResult = shell.applyCheckedInResult;
    const rematerializeCheckedInLocalTips = shell.rematerializeCheckedInLocalTips;
    const indexWhereUsedUnderBusy = shell.indexWhereUsedUnderBusy;
    const pushCreoMetadataForItems = shell.pushCreoMetadataForItems;
    const metadataTargetsFromResult = shell.metadataTargetsFromResult;
    const rememberWatchView = shell.rememberWatchView;
    const reloadPageAfterDialog = shell.reloadPageAfterDialog;
    const eventEl = shell.eventEl;
    const initJobModule = shell.initJobModule;
    const selectedRows = shell.selectedRows;
    const canOfferAdd = shell.canOfferAdd;
    const selectionIsAddOnly = shell.selectionIsAddOnly;
    const selectionCanCheckin = shell.selectionCanCheckin;
    const userCanCheckin = shell.userCanCheckin;
    const checkinDialog = shell.checkinDialog;
    const addPageListener =
      shell.addPageListener ||
      ((target, type, listener, options) => target.addEventListener(type, listener, options));
    function onPage(el, type, listener, options) {
      if (!el) return;
      addPageListener(el, type, listener, options);
    }

    const checkinBtn = $("#checkin-btn");
    const checkinProductBtn = $("#checkin-product-btn");
    const checkinMenuBtn = $("#checkin-menu-btn");
    const checkinForm = $("#checkin-form");
    const openWorkspaceBtn = $("#open-workspace-btn");
    const addForm = $("#add-form");

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
      const checkinGate = await assertProductAllows(currentProductId(), "checkin");
      if (!checkinGate.ok) return;
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

    // Toolbar Check In buttons stay as thin stubs in app.js (like Open).
    // Form / cancel / Ask AI bind here so soft-nav tears them down with the page.
    onPage($("#checkin-ask-ai"), "click", () => {
      void initJobModule("modifications", window.__creopdmShell).then((m) =>
        m.askAiCheckinComment?.()
      );
    });
    onPage($("#checkin-cancel"), "click", () => checkinDialog?.close());
    onPage(checkinForm, "submit", async (event) => {
      event.preventDefault();
      const submitGate = await assertProductAllows(currentProductId(), "checkin", {
        errorEl: $("#checkin-error"),
        reloadOnDeny: false,
      });
      if (!submitGate.ok) return;
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

    mod.beginAddSelected = beginAddSelected;
    mod.beginCheckin = beginCheckin;
    mod.syncCheckinAiAskRow = syncCheckinAiAskRow;
  },
};
