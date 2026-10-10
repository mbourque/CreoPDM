window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.metadata = {
  /**
   * Collect Creo metadata job, Where Used indexing / Rebuild, gear Utilities rebuild.
   * Loaded lazily (ensureModule("metadata")) when Collect / Rebuild / Add index needs it.
   */
  init(shell) {
    const mod = window.__creopdmModules.metadata;
    const $ = shell.$;
    const withBusy = shell.withBusy;
    const setBusy = shell.setBusy;
    const setBusyMessage = shell.setBusyMessage;
    const setBusyCancelHandler = shell.setBusyCancelHandler;
    const clearBusy = shell.clearBusy;
    const forceClearBusy = shell.forceClearBusy;
    const getBusyDepth = shell.getBusyDepth;
    const publishBusyMessage = shell.publishBusyMessage;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const readError = shell.readError;
    const reloadPage = shell.reloadPage;
    const currentProductId = shell.currentProductId;
    const currentVaultFolder = shell.currentVaultFolder;
    const assertProductAllows = shell.assertProductAllows;
    const waitForCreoMetadataBridge = shell.waitForCreoMetadataBridge;
    const ensureProductObjects = shell.ensureProductObjects;
    const sortMetadataCollectTargets = shell.sortMetadataCollectTargets;
    const isCreoMetadataCandidate = shell.isCreoMetadataCandidate;
    const looksLikeLocalWindowsPath = shell.looksLikeLocalWindowsPath;
    const prepareLocalPathForMetadata = shell.prepareLocalPathForMetadata;
    const gatherCreoMetadataForFilename = shell.gatherCreoMetadataForFilename;
    const postAiSnapshotFromGather = shell.postAiSnapshotFromGather;
    const agentWorkdir = shell.agentWorkdir;
    const listAgentCacheFiles = shell.listAgentCacheFiles;
    const joinLocalWorkspacePath = shell.joinLocalWorkspacePath;
    const PathBasename = shell.PathBasename;
    const logicalUploadName = shell.logicalUploadName;
    const reconcileProductLifecycleChrome = shell.reconcileProductLifecycleChrome;
    const metadataCollectJob = shell.metadataCollectJob;
    const saveMetadataCollectState = shell.saveMetadataCollectState;
    const loadMetadataCollectState = shell.loadMetadataCollectState;
    const syncMetadataCollectControls = shell.syncMetadataCollectControls;
    const METADATA_COLLECT_WARN_THRESHOLD = 50;
    const addPageListener =
      shell.addPageListener ||
      ((target, type, listener, options) => target.addEventListener(type, listener, options));
    function onPage(el, type, listener, options) {
      if (!el) return;
      addPageListener(el, type, listener, options);
    }

    function sleepMs(ms, signal) {
      return new Promise((resolve) => {
        if (signal?.aborted) {
          resolve();
          return;
        }
        const timer = window.setTimeout(resolve, ms);
        if (!signal) return;
        const onAbort = () => {
          window.clearTimeout(timer);
          resolve();
        };
        signal.addEventListener("abort", onAbort, { once: true });
      });
    }

    function whereUsedBusyText(doneCount, total) {
      if (total > 0) return `Indexing Where Used… ${doneCount} of ${total}`;
      return "Indexing Where Used… preparing…";
    }

    function metadataBusyText(doneCount, total, filename) {
      const name = filename ? `: ${filename}` : "";
      if (total > 0) return `Collecting Creo metadata… ${doneCount} of ${total}${name}`;
      return "Collecting Creo metadata…";
    }

    async function cancelWhereUsedIndex(productId) {
      if (!productId) return;
      try {
        await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`, {
          method: "DELETE",
        });
      } catch {
        /* still clear UI even if cancel request fails */
      }
    }

    async function runWhereUsedProgress(productId) {
      // Caller already owns the busy overlay — keep it up through N of M.
      setBusyMessage("Indexing Where Used… preparing…");
      return awaitWhereUsedIndex(productId, {
        onProgress: (doneCount, total) => {
          publishBusyMessage(whereUsedBusyText(doneCount, total));
        },
      });
    }

    async function indexWhereUsedUnderBusy(productId) {
      if (!productId) return null;
      // Nested under Add/Compressed busy: do not clearBusy between import and index
      // (that flashed the Files list before Where Used finished — false Top Level).
      if (getBusyDepth() > 0) {
        return runWhereUsedProgress(productId);
      }
      try {
        return await withBusy("Indexing Where Used… preparing…", () =>
          runWhereUsedProgress(productId)
        );
      } finally {
        // Escape cancel must never leave the modal stuck over the app.
        if (getBusyDepth() > 0) forceClearBusy();
      }
    }

    function utilitiesRepairNotice(form, { ok, error } = {}) {
      const article = form?.closest("article") || document.querySelector(".admin-utilities");
      if (!article) return;
      article.querySelectorAll("p.ok, p.error").forEach((el) => el.remove());
      const p = document.createElement("p");
      p.className = error ? "error" : "ok";
      p.textContent = error || ok || "";
      const h1 = article.querySelector("h1");
      if (h1) h1.after(p);
      else article.prepend(p);
    }

    async function runUtilitiesRebuildWithWhereUsed(form) {
      if (!(form instanceof HTMLFormElement)) return;
      const select = form.querySelector('select[name="product_id"]');
      const productId = (select?.value || "").trim();
      const label = select?.selectedOptions?.[0]?.textContent?.trim() || "product";
      const fd = new FormData(form);
      const action = String(fd.get("repair_action") || "");
      let initial = "Indexing Where Used… preparing…";
      if (action === "rebuild") initial = `Rebuilding product database for ${label}…`;
      else if (action === "clear_metadata") {
        initial = `Deleting Creo metadata for ${label}…`;
      }
      const btn = form.querySelector('button[type="submit"]');
      if (btn instanceof HTMLButtonElement) btn.disabled = true;
      try {
        await withBusy(initial, async () => {
          const response = await fetch(form.getAttribute("action") || form.action, {
            method: "POST",
            body: fd,
          });
          const html = await response.text();
          const parsed = new DOMParser().parseFromString(html, "text/html");
          if (!response.ok) {
            utilitiesRepairNotice(form, {
              error:
                parsed.querySelector("p.error")?.textContent?.trim()
                || "Could not start the selected action.",
            });
            return;
          }
          const priorOk = parsed.querySelector("p.ok")?.textContent?.trim() || "";
          publishBusyMessage("Indexing Where Used… preparing…");
          // Form POST schedules Start after the response (so the HTML fetch is not
          // blocked by the indexer write lock). POST Start here for N of M + Cancel
          // (no-op if the background task already started the same run).
          const outcome = await awaitWhereUsedIndex(productId, {
            start: true,
            onProgress: (doneCount, total) => {
              publishBusyMessage(whereUsedBusyText(doneCount, total));
            },
          });
          if (outcome?.state === "cancelled") {
            utilitiesRepairNotice(form, {
              ok:
                "Where Used indexing cancelled. Run Delete and rebuild Where Used again "
                + "if Top Level / dependencies look incomplete.",
            });
            return;
          }
          if (!outcome || outcome.state === "error" || outcome.state === "timeout") {
            utilitiesRepairNotice(form, {
              error: outcome?.error || "Where Used indexing failed.",
            });
            return;
          }
          if (outcome.state === "done") {
            const missMsg = outcome.parentsMissing
              ? ` ${outcome.parentsMissing} parent file(s) missing from vault.`
              : "";
            const wu =
              `Where Used index ready: ${outcome.edgesAdded} new link(s), `
              + `${outcome.edgesExisting} already stored.${missMsg}`;
            const msg = priorOk && !/where used/i.test(priorOk) ? `${priorOk} ${wu}` : wu;
            utilitiesRepairNotice(form, { ok: msg });
          }
        });
      } finally {
        forceClearBusy();
        if (btn instanceof HTMLButtonElement) btn.disabled = false;
      }
    }

    /**
     * Start Where Used indexing and wait until done/error/cancelled.
     * Used under the Add (and gear Rebuild) busy overlay — not fire-and-forget.
     * Escape stops the server job and clears the overlay.
     */
    async function awaitWhereUsedIndex(productId, { onProgress, start = true } = {}) {
      if (!productId) return { started: false };
      let expectStartedAt = 0;
      let sawActive = false;
      let userCancelled = false;
      let cancelInFlight = false;
      const ac = new AbortController();
      const requestCancel = async () => {
        if (userCancelled || cancelInFlight) return;
        cancelInFlight = true;
        userCancelled = true;
        publishBusyMessage("Cancelling Where Used indexing…");
        // Abort Start/poll fetches — otherwise a hung Start left Cancel looking dead.
        try {
          ac.abort();
        } catch {
          /* ignore */
        }
        await cancelWhereUsedIndex(productId);
      };
      setBusyCancelHandler(requestCancel);
      try {
        if (start) {
          let startResponse;
          try {
            startResponse = await fetch(
              `/api/products/${encodeURIComponent(productId)}/rebuild-where-used`,
              { method: "POST", signal: ac.signal }
            );
          } catch (exc) {
            if (userCancelled || ac.signal.aborted) {
              return { started: true, state: "cancelled" };
            }
            return { started: false, error: exc?.message || "Could not reach CreoPDM." };
          }
          if (userCancelled) return { started: true, state: "cancelled" };
          if (!startResponse.ok) {
            return { started: false, error: await readError(startResponse) };
          }
          try {
            const startBody = await startResponse.json();
            expectStartedAt = Number(startBody.started_at) || 0;
            const startState = String(startBody.state || "");
            if (startState === "queued" || startState === "running") sawActive = true;
            const startTotal = Number(startBody.parents_total) || 0;
            const startDone = Number(startBody.parents_done) || 0;
            onProgress?.(startDone, startTotal);
          } catch {
            /* status body optional */
          }
        }
        for (let tries = 0; tries < 1800; tries += 1) {
          if (userCancelled || ac.signal.aborted) {
            return { started: true, state: "cancelled" };
          }
          try {
            const response = await fetch(
              `/api/products/${encodeURIComponent(productId)}/rebuild-where-used`,
              { signal: ac.signal }
            );
            if (!response.ok) {
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            const body = await response.json();
            const state = String(body.state || "");
            const startedAt = Number(body.started_at) || 0;
            const total = Number(body.parents_total) || 0;
            const doneCount = Number(body.parents_done) || 0;
            // Ignore a prior job's terminal status (utilities used to flash "done" instantly).
            if (
              expectStartedAt
              && startedAt
              && startedAt + 0.001 < expectStartedAt
              && state !== "queued"
              && state !== "running"
            ) {
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            if (state === "queued" || state === "running") {
              sawActive = true;
              onProgress?.(doneCount, total);
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            if (state === "done") {
              if (expectStartedAt && startedAt && startedAt + 0.001 < expectStartedAt) {
                await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
                continue;
              }
              // Stale idle→done (no Start stamp) or unfinished progress — keep waiting.
              if (start && !sawActive) {
                await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
                continue;
              }
              if (total > 0 && doneCount < total) {
                onProgress?.(doneCount, total);
                await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
                continue;
              }
              onProgress?.(doneCount, total);
              return {
                started: true,
                state: "done",
                edgesAdded: Number(body.edges_added) || 0,
                edgesExisting: Number(body.edges_existing) || 0,
                parentsMissing: Number(body.parents_missing_vault) || 0,
                parentsTotal: total,
                parentsDone: doneCount,
              };
            }
            if (state === "cancelled") {
              return { started: true, state: "cancelled" };
            }
            if (state === "error") {
              return {
                started: true,
                state: "error",
                error: body.error || "Where Used indexing failed.",
              };
            }
            // idle while waiting for a job we started — keep polling
            if (expectStartedAt || start) {
              await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
              continue;
            }
            return { started: true, state: state || "idle" };
          } catch {
            if (userCancelled || ac.signal.aborted) {
              return { started: true, state: "cancelled" };
            }
            /* ignore transient poll errors */
          }
          await sleepMs(tries < 20 ? 250 : 1000, ac.signal);
        }
        return {
          started: true,
          state: "timeout",
          error: "Where Used indexing timed out. Try Rebuild Where Used from the product gear.",
        };
      } finally {
        setBusyCancelHandler(null);
      }
    }

    function watchWhereUsedIndex(productId) {
      if (!productId) return;
      let tries = 0;
      const tick = async () => {
        tries += 1;
        try {
          const response = await fetch(`/api/products/${encodeURIComponent(productId)}/rebuild-where-used`);
          if (!response.ok) return;
          const body = await response.json();
          const state = String(body.state || "");
          if (state === "queued" || state === "running") {
            const total = Number(body.parents_total) || 0;
            const doneCount = Number(body.parents_done) || 0;
            if (total > 0) {
              showOk(`Indexing Where Used in background… ${doneCount} of ${total} assemblies/drawings`);
            }
            if (tries < 600) window.setTimeout(tick, 2000);
            return;
          }
          if (state === "done") {
            const added = Number(body.edges_added) || 0;
            const existing = Number(body.edges_existing) || 0;
            const miss = Number(body.parents_missing_vault) || 0;
            const missMsg = miss ? ` ${miss} parent file(s) missing from vault.` : "";
            try {
              sessionStorage.setItem(
                "creopdmNotice",
                `Where Used index ready: ${added} new link(s), ${existing} already stored.${missMsg}`
              );
            } catch {
              /* private mode / blocked storage */
            }
            // Refresh Files so Top level assemblies / Where Used gates appear.
            reloadPage();
            return;
          }
          if (state === "cancelled") {
            return;
          }
          if (state === "error") {
            showError($("#toolbar-error"), body.error || "Where Used indexing failed.");
          }
        } catch {
          /* ignore transient poll errors */
        }
      };
      window.setTimeout(tick, 800);
    }

    function confirmCollectMetadata(total) {
      const dialog = $("#collect-metadata-dialog");
      const form = $("#collect-metadata-form");
      const lead = $("#collect-metadata-lead");
      const warn = $("#collect-metadata-warn");
      if (!(dialog instanceof HTMLDialogElement) || !form || !lead) {
        return Promise.resolve(window.confirm(`Collect Creo metadata for ${total} model(s)?`));
      }
      lead.textContent =
        `Capture parameters, materials, units, features, and BOM/structure for ${total} Creo model(s) in this product. ` +
        "Each model is retrieved in the Creo session when needed. Mass properties are not collected (unsupported in silent Collect).";
      if (warn) {
        if (total > METADATA_COLLECT_WARN_THRESHOLD) {
          warn.hidden = false;
          warn.textContent =
            `This is ${total} models (over ${METADATA_COLLECT_WARN_THRESHOLD}). It can take a long time and may make Creo sluggish. A busy overlay stays up until Collect finishes — keep this CreoPDM window open.`;
        } else {
          warn.hidden = true;
          warn.textContent = "";
        }
      }
      return new Promise((resolve) => {
        const onCancel = () => {
          cleanup();
          dialog.close();
          resolve(false);
        };
        const onSubmit = (event) => {
          event.preventDefault();
          cleanup();
          dialog.close();
          resolve(true);
        };
        function cleanup() {
          form.removeEventListener("submit", onSubmit);
          $("#collect-metadata-cancel")?.removeEventListener("click", onCancel);
        }
        form.addEventListener("submit", onSubmit);
        $("#collect-metadata-cancel")?.addEventListener("click", onCancel);
        if (!dialog.open) dialog.showModal();
      });
    }

    async function pushOneCreoMetadataTarget(target, options) {
      // No per-file JS timeout — large assemblies (e.g. 844j.asm) can take many
      // minutes in Creo. Skipping them loses the metadata we care about most.
      // Cancel still works between models; during a Creo retrieve the UI may pause.
      // Bulk Collect: tip-only prepare, no empty-session probe, defer Erase, skip
      // feature.name reads (Open session capture fills renamed Features later).
      const opts = options && typeof options === "object" ? options : {};
      try {
        let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
        if (!filePath) {
          filePath = (await prepareLocalPathForMetadata(target.uuid, target.filename)) || "";
        }
        if (!filePath) {
          return { ok: false, reason: "materialize_failed" };
        }
        let snapshot = await gatherCreoMetadataForFilename(target.filename, filePath, {
          deferErase: opts.deferErase !== false,
          // Default on — Details Features need tree names (RIGHT, DEFAULT_CS, …).
          featureNames: opts.featureNames !== false,
          pendingErase: opts.pendingErase,
        });
        if (snapshot && snapshot.__error) {
          return {
            ok: false,
            reason: String(snapshot.__error),
            detail: String(snapshot.__detail || ""),
          };
        }
        if (!snapshot) return { ok: false, reason: "gather_failed" };
        // Require a real identity filename so empty/failed snapshots are never "saved".
        const identityName = String(snapshot.identity?.file_name || snapshot.identity?.full_name || "").trim();
        if (!identityName) {
          return { ok: false, reason: "empty_identity" };
        }
        const body = {
          version_id: target.versionId || null,
          identity: snapshot.identity || null,
          parameters: Array.isArray(snapshot.parameters) ? snapshot.parameters : [],
          materials: snapshot.materials || null,
          dependencies: Array.isArray(snapshot.dependencies) ? snapshot.dependencies : [],
          bom: snapshot.bom || null,
          units: snapshot.units || null,
          // Mass unsupported in silent Collect — omit so existing mass_json is preserved.
          family_table: snapshot.family_table || null,
          features: Array.isArray(snapshot.features) && snapshot.features.length
            ? snapshot.features
            : null,
          structure: Array.isArray(snapshot.structure) ? snapshot.structure : null,
          simp_reps: snapshot.simp_reps && typeof snapshot.simp_reps === "object"
            ? snapshot.simp_reps
            : null,
        };
        try {
          const response = await fetch(`/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
          if (response.ok) {
            await postAiSnapshotFromGather(target.uuid, target.versionId || null, snapshot, {
              objectFilename: target.filename,
            });
            return { ok: true, reason: "" };
          }
          let detail = "";
          try {
            const errBody = await response.json();
            detail = String(errBody?.error?.message || errBody?.detail || "").trim();
          } catch {
            /* ignore */
          }
          return {
            ok: false,
            reason: "post_failed",
            status: response.status,
            detail: detail || `HTTP ${response.status}`,
          };
        } catch {
          return { ok: false, reason: "post_failed", status: 0 };
        }
      } catch {
        return { ok: false, reason: "exception" };
      }
    }

    async function attachCollectLocalPaths(productId, targets) {
      // Warm workspace: resolve tip paths once so Collect skips per-file open-prepare.
      if (!productId || !Array.isArray(targets) || !targets.length) return;
      try {
        const [workdir, cacheFiles] = await Promise.all([
          agentWorkdir(productId, currentVaultFolder()).catch(() => ""),
          listAgentCacheFiles(productId),
        ]);
        if (!workdir || !Array.isArray(cacheFiles) || !cacheFiles.length) return;
        const byRel = new Map();
        const byLogical = new Map();
        cacheFiles.forEach((item) => {
          const rel = String(item?.relative_path || item?.path || "")
            .replace(/\\/g, "/")
            .replace(/^\/+/, "");
          if (!rel) return;
          const full = joinLocalWorkspacePath(workdir, rel);
          if (!full || !looksLikeLocalWindowsPath(full)) return;
          byRel.set(rel.toLowerCase(), full);
          const base = PathBasename(rel);
          const logical = (logicalUploadName(base) || base).toLowerCase();
          if (logical && !byLogical.has(logical)) byLogical.set(logical, full);
        });
        targets.forEach((target) => {
          if (looksLikeLocalWindowsPath(target.path)) return;
          const rel = String(target.relativePath || "").replace(/\\/g, "/").replace(/^\/+/, "");
          if (rel && byRel.has(rel.toLowerCase())) {
            target.path = byRel.get(rel.toLowerCase());
            return;
          }
          const logical = (logicalUploadName(target.filename) || target.filename || "").toLowerCase();
          if (logical && byLogical.has(logical)) {
            target.path = byLogical.get(logical);
          }
        });
      } catch {
        /* prepare-per-file still works */
      }
    }

    async function flushPendingMetadataErase(pendingErase) {
      const list = Array.isArray(pendingErase) ? pendingErase.splice(0, pendingErase.length) : [];
      if (!list.length) return;
      if (typeof window.CreoJS?.eraseSessionModelsByNames !== "function") return;
      try {
        await window.CreoJS.eraseSessionModelsByNames(list, { allowUndisplayed: false });
      } catch {
        /* best-effort */
      }
    }

    async function runMetadataCollectLoop(state) {
      if (metadataCollectJob.running) return;
      const targets = Array.isArray(state.targets) ? state.targets : [];
      if (!targets.length) {
        saveMetadataCollectState(null);
        return;
      }
      metadataCollectJob.running = true;
      metadataCollectJob.cancel = false;
      syncMetadataCollectControls();
      showError($("#toolbar-error"), "");
      setBusy("Collecting Creo metadata…");
      // Same Escape cancel as Where Used — stops between models; clears overlay via finally.
      setBusyCancelHandler(() => {
        metadataCollectJob.cancel = true;
        publishBusyMessage("Cancelling metadata collection…");
        showOk("Cancelling metadata collection…");
      });
      let index = Math.max(0, Number(state.index) || 0);
      let captured = Number(state.captured) || 0;
      let failed = Number(state.failed) || 0;
      let lastReason = "";
      let shouldRefreshList = false;
      const pendingErase = [];
      try {
        // Fresh runs: parts/asms before drawings so companions land before .drw Retrieve.
        // Do not re-order mid-resume (index would point at the wrong file).
        if (index === 0 && targets.length > 1) {
          const sorted = sortMetadataCollectTargets(targets);
          targets.splice(0, targets.length, ...sorted);
          state.targets = targets;
        }
        if (state.productId) {
          setBusyMessage("Checking local workspace tips…");
          await attachCollectLocalPaths(state.productId, targets);
        }
        while (index < targets.length) {
          if (metadataCollectJob.cancel) break;
          const target = targets[index];
          const message =
            `Collecting Creo metadata… ${index + 1} of ${targets.length}: ${target.filename}` +
            ` (${captured} saved, ${failed} skipped` +
            (lastReason ? `, last: ${lastReason}` : "") +
            `)`;
          setBusyMessage(message);
          // Avoid showOk every file — toolbar churn; busy overlay carries progress.
          saveMetadataCollectState({
            ...state,
            status: "running",
            index,
            captured,
            failed,
            message,
            lastReason,
            updatedAt: Date.now(),
          });
          const result = await pushOneCreoMetadataTarget(target, {
            deferErase: true,
            featureNames: true,
            pendingErase,
          });
          if (result.ok) {
            captured += 1;
            // Keep mass/units/feature gap hints on success so we can watch Collect.
            lastReason = String(result.reason || "");
          } else {
            failed += 1;
            lastReason = String(result.detail || result.reason || "skipped");
            // Lifecycle / validation: stop immediately — do not Creo-walk the rest.
            const locked =
              Number(result.status) === 400 ||
              /cannot update metadata|in review|is locked|validation/i.test(lastReason);
            if (locked) {
              showError($("#toolbar-error"), lastReason);
              saveMetadataCollectState(null);
              metadataCollectJob.cancel = true;
              await reconcileProductLifecycleChrome(state.productId, {
                requireEditMetadata: true,
                showError: false,
              });
              break;
            }
          }
          index += 1;
          if (pendingErase.length >= 25) {
            await flushPendingMetadataErase(pendingErase);
          }
          saveMetadataCollectState({
            ...state,
            status: "running",
            index,
            captured,
            failed,
            lastReason,
            message:
              `Collecting Creo metadata… ${index} of ${targets.length}` +
              ` (${captured} saved, ${failed} skipped` +
              (lastReason ? `, last: ${lastReason}` : "") +
              `)`,
            updatedAt: Date.now(),
          });
          await new Promise((resolve) => window.setTimeout(resolve, 0));
        }
        await flushPendingMetadataErase(pendingErase);
        if (typeof window.CreoJS?.eraseUndisplayedModelsQuiet === "function") {
          try {
            await window.CreoJS.eraseUndisplayedModelsQuiet();
          } catch {
            /* final sweep is best-effort */
          }
        }
        if (metadataCollectJob.cancel) {
          const msg =
            `Metadata collection cancelled after ${captured + failed} of ${targets.length} ` +
            `(${captured} saved, ${failed} skipped).`;
          showOk(msg);
          saveMetadataCollectState(null);
        } else {
          const msg =
            `Metadata collection finished: ${captured} saved` +
            (failed ? `, ${failed} skipped` : "") +
            `.`;
          showOk(msg);
          saveMetadataCollectState(null);
        }
        // Type column (SHEETMETAL / MFG / …) comes from SSR — refresh Files after saves.
        shouldRefreshList = captured > 0;
      } finally {
        setBusyCancelHandler(null);
        clearBusy();
        forceClearBusy();
        metadataCollectJob.running = false;
        metadataCollectJob.cancel = false;
        syncMetadataCollectControls();
      }
      if (shouldRefreshList) {
        await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
      }
    }

    async function runCollectAllMetadata(productId) {
      if (metadataCollectJob.running) {
        showOk("Metadata collection is already running.");
        return;
      }
      const gate = await assertProductAllows(productId, "edit_metadata");
      if (!gate.ok) return;
      // Bridge often arrives after first paint — same wait as Resume.
      showOk("Waiting for Creo.JS…");
      const ready = await waitForCreoMetadataBridge();
      if (!ready) {
        showError(
          $("#toolbar-error"),
          "Collect metadata needs Creo’s embedded browser with Creo.JS available."
        );
        return;
      }
      showOk("");
      const existing = loadMetadataCollectState();
      if (
        existing &&
        existing.status === "running" &&
        existing.productId === productId &&
        Array.isArray(existing.targets) &&
        existing.targets.length
      ) {
        await runMetadataCollectLoop(existing);
        return;
      }
      const rows = await ensureProductObjects(productId, { force: true });
      const targets = sortMetadataCollectTargets(
        (Array.isArray(rows) ? rows : [])
          .map((row) => ({
            uuid: String(row.uuid || "").trim(),
            filename: String(row.filename || "").trim(),
            path: "",
            relativePath: String(row.relative_path || "").trim(),
            versionId: String(row.current_version?.uuid || row.version_id || "").trim(),
          }))
          .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename))
      );
      if (!targets.length) {
        showOk("No Creo parts, assemblies, or drawings to capture.");
        return;
      }
      const okToStart = await confirmCollectMetadata(targets.length);
      if (!okToStart) return;

      const state = {
        productId,
        status: "running",
        index: 0,
        captured: 0,
        failed: 0,
        targets,
        message: `Collecting Creo metadata… 0 of ${targets.length}`,
        updatedAt: Date.now(),
      };
      saveMetadataCollectState(state);
      await runMetadataCollectLoop(state);
    }

    async function resumeMetadataCollectIfNeeded(opts = {}) {
      const fromButton = Boolean(opts && opts.fromButton);
      const state = loadMetadataCollectState();
      if (!state || state.status !== "running") return;
      if (!Array.isArray(state.targets) || !state.targets.length) {
        saveMetadataCollectState(null);
        return;
      }
      if (metadataCollectJob.running) {
        if (state.message) showOk(state.message);
        syncMetadataCollectControls();
        return;
      }
      const productId = currentProductId();
      if (productId && state.productId && productId !== state.productId) {
        showOk(
          `Metadata collection paused for another product (${state.index || 0} of ${state.targets.length}).`
        );
        syncMetadataCollectControls();
        return;
      }
      if (state.message) showOk(state.message);
      syncMetadataCollectControls();
      // Bridge often appears after first paint (same race as the status pill).
      if (!(await waitForCreoMetadataBridge())) {
        showOk(
          `Metadata collection paused at ${state.index || 0} of ${state.targets.length}. ` +
            (fromButton
              ? "Creo.JS still unavailable — open CreoPDM inside Creo, then click Resume."
              : "Click Resume when Creo.JS is connected, or re-open CreoPDM inside Creo.")
        );
        syncMetadataCollectControls();
        return;
      }
      await runMetadataCollectLoop(state);
    }

    mod.indexWhereUsedUnderBusy = indexWhereUsedUnderBusy;
    mod.awaitWhereUsedIndex = awaitWhereUsedIndex;
    mod.watchWhereUsedIndex = watchWhereUsedIndex;
    mod.runUtilitiesRebuildWithWhereUsed = runUtilitiesRebuildWithWhereUsed;
    mod.runCollectAllMetadata = runCollectAllMetadata;
    mod.resumeMetadataCollectIfNeeded = resumeMetadataCollectIfNeeded;
    mod.pushOneCreoMetadataTarget = pushOneCreoMetadataTarget;
    mod.metadataBusyText = metadataBusyText;
  },
};
