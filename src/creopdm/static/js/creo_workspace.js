window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.creo_workspace = {
  /**
   * Creo session metadata gather/push + agent workspace materialize.
   * Shared by Open (open.js), Collect (metadata.js), Check In and bulk Checkout.
   * Loaded lazily via ensureModule("creo_workspace"); app.js keeps async wrappers.
   * Agent cache listing/hash helpers stay in app.js (Files list needs them on quiet boot).
   */
  init(shell) {
    const mod = window.__creopdmModules.creo_workspace;
    const withBusy = shell.withBusy;
    const setBusyMessage = shell.setBusyMessage;
    const publishBusyMessage = shell.publishBusyMessage;
    const metadataBusyText = shell.metadataBusyText;
    const readError = shell.readError;
    const postAction = shell.postAction;
    const agentBase = shell.agentBase;
    const agentAuthHeaders = shell.agentAuthHeaders;
    const agentPdmAuth = shell.agentPdmAuth;
    const abortSignalAfter = shell.abortSignalAfter;
    const probeCreoAgent = shell.probeCreoAgent;
    const currentProductId = shell.currentProductId;
    const currentVaultFolder = shell.currentVaultFolder;
    const canGatherCreoMetadata = shell.canGatherCreoMetadata;
    const whenCreoJSReady = shell.whenCreoJSReady;
    const looksLikeLocalWindowsPath = shell.looksLikeLocalWindowsPath;
    const metadataNeedsOpenDependencies = shell.metadataNeedsOpenDependencies;
    const sortMetadataCollectTargets = shell.sortMetadataCollectTargets;
    const isCreoMetadataCandidate = shell.isCreoMetadataCandidate;
    const checkedInItemsFromResult = shell.checkedInItemsFromResult;
    const postAiSnapshotFromGather = shell.postAiSnapshotFromGather;
    const setOpenDownloadBusyMessage = shell.setOpenDownloadBusyMessage;
    const BULK_AGENT_CACHE_ZIP_THRESHOLD = shell.BULK_AGENT_CACHE_ZIP_THRESHOLD;

    async function prepareLocalPathForMetadata(objectId, filename) {
      if (!objectId) return null;
      try {
        // Tip-only for parts/assemblies — Collect must not walk/materialize the
        // full Where Used tree for every file (that made 900+ Collects feel stuck).
        // Drawings still need referenced models beside them in the workspace.
        const includeDependencies = metadataNeedsOpenDependencies(filename);
        const response = await fetch("/api/creo/open", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            object_id: objectId,
            launch: false,
            include_dependencies: includeDependencies,
          }),
        });
        if (!response.ok) return null;
        const prepared = await response.json();
        const agent = await probeCreoAgent();
        if (!agent) {
          const dir = String(prepared.working_directory || prepared.directory || "").trim();
          const name = String(prepared.disk_name || prepared.filename || "").trim();
          if (dir && name && looksLikeLocalWindowsPath(dir)) {
            return `${dir.replace(/[\\/]+$/, "")}\\${name}`;
          }
          return null;
        }
        const openSpec = await materializeViaAgent(
          {
            ...prepared,
            replace_newer: Boolean(prepared.replace_newer),
          },
          // Keep Collect's "N of M" busy text — do not flash workspace-up-to-date.
          { quietBusy: true }
        );
        const materialized = String(openSpec.path || "").trim();
        if (materialized && looksLikeLocalWindowsPath(materialized)) {
          return materialized;
        }
        const workdir = String(openSpec.working_directory || "").trim();
        const diskName = String(openSpec.disk_name || openSpec.filename || "").trim();
        if (workdir && diskName) {
          const rel = String(diskName).replace(/\//g, "\\");
          if (rel.includes("\\")) {
            return `${workdir.replace(/[\\/]+$/, "")}\\${rel}`;
          }
          return `${workdir.replace(/[\\/]+$/, "")}\\${diskName}`;
        }
        return null;
      } catch {
        return null;
      }
    }

    async function gatherCreoMetadataForFilename(filename, filePath, options) {
      if (!canGatherCreoMetadata() || !filename) return null;
      const opts = options && typeof options === "object" ? options : {};
      const deferErase = Boolean(opts.deferErase);
      // Default on — Boolean(undefined) was false and wiped Collect/Open names.
      const featureNames = opts.featureNames !== false;
      const preferDisk = opts.preferDisk === true;
      const pendingErase = Array.isArray(opts.pendingErase) ? opts.pendingErase : null;
      try {
        await whenCreoJSReady();
        if (typeof window.CreoJS.gatherModelMetadata !== "function") return null;
        const snapshot = await window.CreoJS.gatherModelMetadata(filename, filePath || "", {
          featureNames,
          preferDisk: preferDisk && !!filePath,
        });
        if (!snapshot || typeof snapshot !== "object") return null;
        if (typeof snapshot === "string" && snapshot.startsWith("CREOPDM_ERROR:")) return null;
        if (snapshot.__error) {
          return {
            __error: String(snapshot.__error || "gather_failed"),
            __detail: String(snapshot.__detail || ""),
          };
        }
        const eraseKeys = Array.isArray(snapshot._pdm_erase_keys)
          ? snapshot._pdm_erase_keys.filter((name) => typeof name === "string" && name.trim())
          : [];
        delete snapshot._pdm_erase_keys;
        // PTC defers Erase until Creo regains control — must be a separate Creo.JS turn.
        // Collect batches erases (deferErase) so 935 models are not 935 Erase turns.
        if (eraseKeys.length) {
          if (deferErase && pendingErase) {
            eraseKeys.forEach((key) => pendingErase.push(key));
          } else if (typeof window.CreoJS.eraseSessionModelsByNames === "function") {
            try {
              await window.CreoJS.eraseSessionModelsByNames(eraseKeys, { allowUndisplayed: false });
            } catch {
              /* best-effort session cleanup */
            }
          }
        }
        return snapshot;
      } catch {
        return null;
      }
    }

    async function pushCreoMetadataForItems(items, options) {
      const opts = options && typeof options === "object" ? options : {};
      const sessionOnly = Boolean(opts.sessionOnly);
      const sessionWaitRounds = Math.max(0, Number(opts.sessionWaitRounds) || 0);
      const sessionWaitMs = Math.max(50, Number(opts.sessionWaitMs) || 500);
      const featureNames = opts.featureNames !== false;
      const showProgress = opts.progress !== false;
      const targets = sortMetadataCollectTargets(
        (items || [])
          .map((item) => ({
            uuid: String(item?.uuid || item?.object_id || "").trim(),
            filename: String(item?.filename || "").trim(),
            path: String(item?.path || "").trim(),
            versionId: String(item?.version_id || item?.current_version?.uuid || "").trim(),
          }))
          .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename))
      );
      let saved = 0;
      if (!targets.length || !canGatherCreoMetadata()) return saved;
      for (let i = 0; i < targets.length; i += 1) {
        const target = targets[i];
        if (showProgress) {
          publishBusyMessage(metadataBusyText(i + 1, targets.length, target.filename));
        }
        // Session first (Open / Check In often already have the model) — avoids
        // re-Retrieve + erase of a model the user just opened.
        let snapshot = null;
        for (let round = 0; round <= sessionWaitRounds; round += 1) {
          snapshot = await gatherCreoMetadataForFilename(target.filename, "", {
            featureNames,
          });
          if (snapshot && snapshot.__error) snapshot = null;
          if (snapshot) break;
          if (round < sessionWaitRounds) {
            await new Promise((resolve) => window.setTimeout(resolve, sessionWaitMs));
          }
        }
        // After File > Open trail, do not Retrieve from disk — that re-floods the
        // Creo message log on large assemblies the trail already opened quietly.
        if (!snapshot && !sessionOnly) {
          let filePath = looksLikeLocalWindowsPath(target.path) ? target.path : "";
          if (!filePath) {
            filePath = (await prepareLocalPathForMetadata(target.uuid, target.filename)) || "";
          }
          if (!filePath) continue;
          snapshot = await gatherCreoMetadataForFilename(target.filename, filePath, {
            featureNames,
          });
          if (snapshot && snapshot.__error) snapshot = null;
        }
        if (!snapshot) continue;
        const identityName = String(
          snapshot.identity?.file_name || snapshot.identity?.full_name || ""
        ).trim();
        if (!identityName) continue;
        const body = {
          version_id: target.versionId || null,
          identity: snapshot.identity || null,
          parameters: Array.isArray(snapshot.parameters) ? snapshot.parameters : [],
          materials: snapshot.materials || null,
          dependencies: Array.isArray(snapshot.dependencies) ? snapshot.dependencies : [],
          bom: snapshot.bom || null,
          units: snapshot.units || null,
          // Mass unsupported without a displayed solid — omit so mass_json is preserved.
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
          const response = await fetch(
            `/api/objects/${encodeURIComponent(target.uuid)}/creo-metadata`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify(body),
            }
          );
          if (response.ok) {
            saved += 1;
            // Check In / Open tip capture — force so Modified row paint cannot skip.
            await postAiSnapshotFromGather(target.uuid, target.versionId || null, snapshot, {
              force: true,
              objectFilename: target.filename,
            });
          }
        } catch {
          /* soft-fail — metadata is best-effort */
        }
      }
      return saved;
    }

    function metadataItemsFromOpenResult(result) {
      // Only after a Creo.JS session open (not Windows association / browser download).
      if (!result || !result.creo_object) return [];
      const uuid = String(result.object_id || "").trim();
      const filename = String(result.filename || "").trim();
      if (!uuid || !filename || !isCreoMetadataCandidate(filename)) return [];
      return [
        {
          uuid,
          filename,
          // Prefer session gather; local path only as fallback inside push.
          path: looksLikeLocalWindowsPath(result.path) ? result.path : "",
          version_id: String(result.version_id || "").trim(),
        },
      ];
    }

    async function captureCreoMetadataAfterOpen(result) {
      if (!canGatherCreoMetadata()) return 0;
      const items = metadataItemsFromOpenResult(result);
      if (!items.length) return 0;
      let saved = 0;
      await withBusy("Capturing Creo metadata…", async () => {
        // Embedded Open prefers File > Open trail (returns before retrieve finishes).
        // Wait for the model in session; never disk-Retrieve after Open.
        saved = await pushCreoMetadataForItems(items, {
          sessionOnly: true,
          sessionWaitRounds: 60,
          sessionWaitMs: 500,
          featureNames: true,
        });
      });
      return saved;
    }

    /**
     * After a clean check-in the vault tip is logical (shaft.prt), but Creo may
     * still leave shaft.prt.2 in the agent cache. Rematerialize with replace_newer
     * so higher .N siblings are trashed.
     *
     * Do NOT Erase from the Creo session here — check-in leaves models open for
     * continued work (and product check-in must not wipe unrelated open files).
     * History revert still erases; if .N stays locked, the toast hints File → Erase.
     */
    async function rematerializeCheckedInLocalTips(result) {
      const items = checkedInItemsFromResult(result);
      if (!items.length) return { agentOffline: false, ok: 0, failed: 0, erased: 0 };
      const agent = await probeCreoAgent();
      if (!agent) return { agentOffline: true, ok: 0, failed: 0, erased: 0 };

      let ok = 0;
      let failed = 0;
      const total = items.length;
      let purgedTotal = 0;
      await withBusy(
        total === 1
          ? "Updating local workspace…"
          : `Updating local workspace… 0 of ${total}`,
        async () => {
          for (let i = 0; i < items.length; i += 1) {
            if (total > 1) {
              setBusyMessage(`Updating local workspace… ${i + 1} of ${total}`);
            }
            const item = items[i];
            try {
              // Avoid postAction here — it paints toolbar errors and clears OK toasts.
              const response = await fetch("/api/creo/open", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                  object_id: item.uuid,
                  launch: false,
                  include_dependencies: false,
                }),
              });
              if (!response.ok) {
                failed += 1;
                continue;
              }
              const prepared = await response.json();
              const openSpec = await materializeViaAgent({
                ...prepared,
                replace_newer: true,
              });
              purgedTotal += Array.isArray(openSpec?.purged_newer)
                ? openSpec.purged_newer.length
                : 0;
              ok += 1;
            } catch {
              failed += 1;
            }
          }
        }
      );

      return {
        agentOffline: false,
        ok,
        failed,
        erased: 0,
        purged: purgedTotal,
      };
    }

    async function materializeViaAgentPerFile(prepared, dependencies, { quietBusy = false } = {}) {
      const response = await fetch(`${agentBase()}/materialize`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        signal: abortSignalAfter(180000),
        body: JSON.stringify({
          pdm_url: window.location.origin,
          ...agentPdmAuth(),
          object_id: prepared.object_id || null,
          product_id: prepared.product_id || currentProductId() || null,
          vault_folder: currentVaultFolder(),
          relative_path: prepared.relative_path || null,
          filename: prepared.filename || null,
          disk_name: prepared.disk_name || prepared.filename || null,
          content_hash: prepared.content_hash || null,
          file_size: prepared.file_size || 0,
          prefer_local: Boolean(prepared.prefer_local),
          replace_newer: Boolean(prepared.replace_newer),
          dependencies: (dependencies || []).map((item) => ({
            object_id: item.object_id || null,
            product_id: item.product_id || prepared.product_id || currentProductId() || null,
            relative_path: item.relative_path || null,
            filename: item.filename || null,
            disk_name: item.disk_name || item.filename || null,
            content_hash: item.content_hash || null,
            file_size: item.file_size || 0,
            prefer_local: Boolean(item.prefer_local),
          })),
        }),
      });
      if (!response.ok) {
        const message = await readError(response);
        throw new Error(message || "Local CreoPDM agent could not fetch the file.");
      }
      const body = await response.json();
      if (!quietBusy) {
        const skipped = Number(body.skipped_count) || 0;
        const downloaded = Number(body.dependencies_written) || 0;
        if (downloaded > 0) {
          setBusyMessage(
            `Updated local workspace (${downloaded} downloaded, ${skipped} already local)…`
          );
        } else if (skipped > 0) {
          setBusyMessage("Local workspace already up to date…");
        }
      }
      return body;
    }

    async function materializeViaAgent(prepared, { quietBusy = false } = {}) {
      const dependencies = Array.isArray(prepared.dependencies) ? prepared.dependencies : [];
      const ids = [];
      if (prepared.object_id) ids.push(String(prepared.object_id));
      dependencies.forEach((item) => {
        if (item?.object_id) ids.push(String(item.object_id));
      });
      const unique = [...new Set(ids)];
      // Empty / large trees: one zip from CreoPDM (same as bulk checkout), not 900 GETs.
      // Agent plans first — matching local tips are skipped (no re-download).
      if (unique.length >= BULK_AGENT_CACHE_ZIP_THRESHOLD) {
        try {
          if (!quietBusy) {
            setBusyMessage(`Checking local index (${unique.length} files)…`);
          }
          // Pass prepare identities so the agent skips a second 935-id manifest fetch
          // and only looks up `.creopdm_cache_index.json` + file size.
          const zipResult = await materializeCheckedOutToAgentCacheZip(unique, prepared);
          if (!quietBusy) {
            const downloaded = Number(zipResult?.download_count || 0);
            const skipped = Number(zipResult?.skipped_count || 0);
            if (downloaded > 0) {
              setBusyMessage(`Downloaded ${downloaded} missing file${downloaded === 1 ? "" : "s"}…`);
            } else if (skipped > 0) {
              setBusyMessage(`Local workspace up to date (${skipped} files)…`);
            } else {
              setBusyMessage("Local workspace already up to date…");
            }
          }
          // Resolve the primary open path only — deps are already on disk.
          return await materializeViaAgentPerFile(prepared, [], { quietBusy });
        } catch {
          /* fall back to per-file materialize */
          if (!quietBusy) setOpenDownloadBusyMessage(prepared);
        }
      }
      return materializeViaAgentPerFile(prepared, dependencies, { quietBusy });
    }

    function cachePlanItemsFromPrepared(prepared) {
      const items = [];
      const push = (item) => {
        const objectId = String(item?.object_id || "").trim();
        const contentHash = String(item?.content_hash || "").trim();
        if (!objectId || !contentHash) return;
        items.push({
          object_id: objectId,
          product_id: item?.product_id || prepared?.product_id || currentProductId() || "",
          relative_path: item?.relative_path || "",
          filename: item?.filename || item?.disk_name || "",
          disk_name: item?.disk_name || item?.filename || "",
          content_hash: contentHash,
          file_size: Number(item?.file_size) || 0,
        });
      };
      if (prepared) push(prepared);
      (Array.isArray(prepared?.dependencies) ? prepared.dependencies : []).forEach(push);
      return items;
    }

    async function materializeCheckedOutToAgentCacheZip(objectIds, prepared) {
      const planItems = cachePlanItemsFromPrepared(prepared);
      const response = await fetch(`${agentBase()}/materialize-zip`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({
          pdm_url: window.location.origin,
          ...agentPdmAuth(),
          product_id: currentProductId() || null,
          vault_folder: currentVaultFolder(),
          object_ids: objectIds,
          items: planItems,
        }),
      });
      if (!response.ok) {
        const message = await readError(response);
        throw new Error(message || "Local CreoPDM agent could not download the archive.");
      }
      return response.json();
    }

    async function materializeCheckedOutToAgentCache(objectIds, onProgress) {
      const ids = [...new Set((objectIds || []).filter(Boolean))];
      if (!ids.length) return { agentOffline: false, ok: 0, failed: 0 };
      const agent = await probeCreoAgent();
      if (!agent) return { agentOffline: true, ok: 0, failed: 0 };
      const total = ids.length;
      if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD) {
        if (typeof onProgress === "function") onProgress(0, total);
        try {
          const zipResult = await materializeCheckedOutToAgentCacheZip(ids);
          const extracted = Number(zipResult?.extracted_count) || 0;
          const skipped = Number(zipResult?.skipped_count) || 0;
          const keptNewer = Number(zipResult?.kept_newer_count) || 0;
          const downloaded = Number(zipResult?.download_count) || extracted;
          if (typeof onProgress === "function") onProgress(total, total);
          const ok = extracted + skipped + keptNewer;
          return {
            agentOffline: false,
            ok,
            failed: Math.max(0, total - ok),
            skipped,
            keptNewer,
            downloaded,
          };
        } catch {
          /* fall back to per-file download */
        }
      }
      let ok = 0;
      let failed = 0;
      for (let i = 0; i < ids.length; i += 1) {
        const objectId = ids[i];
        if (typeof onProgress === "function") onProgress(i + 1, total);
        try {
          const prepared = await postAction(
            "/api/creo/open",
            { object_id: objectId, launch: false, include_dependencies: false },
            "POST",
            ""
          );
          if (!prepared) {
            failed += 1;
            continue;
          }
          await materializeViaAgent(prepared);
          ok += 1;
        } catch {
          failed += 1;
        }
      }
      return { agentOffline: false, ok, failed };
    }

    mod.prepareLocalPathForMetadata = prepareLocalPathForMetadata;
    mod.gatherCreoMetadataForFilename = gatherCreoMetadataForFilename;
    mod.pushCreoMetadataForItems = pushCreoMetadataForItems;
    mod.captureCreoMetadataAfterOpen = captureCreoMetadataAfterOpen;
    mod.rematerializeCheckedInLocalTips = rematerializeCheckedInLocalTips;
    mod.materializeViaAgent = materializeViaAgent;
    mod.materializeViaAgentPerFile = materializeViaAgentPerFile;
    mod.materializeCheckedOutToAgentCache = materializeCheckedOutToAgentCache;
    mod.materializeCheckedOutToAgentCacheZip = materializeCheckedOutToAgentCacheZip;
  },
};
