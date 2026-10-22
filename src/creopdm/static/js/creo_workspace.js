/**
 * Creo release strings (``13.4.1.0``) and the rule "a model saved in a newer Creo cannot be opened
 * in an older one". Kept at file level so it can be tested without a browser.
 */
window.__creopdmCreoRelease = (function () {
  function parse(text) {
    const match = /(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:\.(\d+))?/.exec(String(text || ""));
    if (!match) return null;
    return [match[1], match[2], match[3], match[4]].map((part) => (part === undefined ? 0 : Number(part)));
  }
  /** True when the file's release is later than the session's in major or minor (13.4 vs 13.3). */
  function newerThanSession(fileRelease, sessionRelease) {
    const file = parse(fileRelease);
    const session = parse(sessionRelease);
    if (!file || !session) return false; // unknown on either side: never block
    if (file[0] !== session[0]) return file[0] > session[0];
    return file[1] > session[1];
  }
  return { parse, newerThanSession };
})();

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
    const showError = shell.showError;
    const $ = shell.$;
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
    const agentWorkdir = shell.agentWorkdir;
    const listAgentCacheFiles = shell.listAgentCacheFiles;
    const joinLocalWorkspacePath = shell.joinLocalWorkspacePath;
    const PathBasename = shell.PathBasename;
    const logicalUploadName = shell.logicalUploadName;

    async function attachCollectLocalPaths(productId, targets) {
      // One agent workdir + cache list so Add/Collect skips per-file open+materialize.
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
          // Prefer agent-cache tip when present (Add may pass a source path).
          const rel = String(target.relativePath || target.relative_path || "")
            .replace(/\\/g, "/")
            .replace(/^\/+/, "");
          if (rel && byRel.has(rel.toLowerCase())) {
            target.path = byRel.get(rel.toLowerCase());
            return;
          }
          const logical = (logicalUploadName(target.filename) || target.filename || "").toLowerCase();
          if (logical && byLogical.has(logical)) {
            target.path = byLogical.get(logical);
          }
          // else keep existing path (e.g. from-disk source) for Toolkit
        });
      } catch {
        /* prepare-per-file still works */
      }
    }

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
            // Collect must not trash a higher local .N (the unsaved Modified tip).
            replace_newer: false,
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

    function logicalCreoTipName(name) {
      const raw = String(name || "").trim();
      if (!raw) return "";
      const numbered = raw.match(/^(.*)\.(\d+)$/i);
      return (numbered ? numbered[1] : raw).toLowerCase();
    }

    async function readToolkitAgentError(response, fallback) {
      let detail = fallback || `HTTP ${response.status}`;
      try {
        const err = await response.json();
        detail = String(err?.detail || err?.error || detail);
      } catch {
        /* ignore */
      }
      return detail;
    }

    /**
     * Toolkit inventory via creopdm-agent → 8767. No Creo.JS inventory fallback —
     * failures return __error so Collect/Open can show Toolkit did not work.
     * Creo.JS may still open/Retrieve the tip into session when filePath is set.
     */
    // Toolkit /health once per ~60s — Collect all was paying this every tip.
    let _toolkitHealthOkUntil = 0;

    let _creoSessionRelease = "";

    /**
     * "" when the file can be used in this Creo session, otherwise why not (a model saved in a
     * newer release cannot be opened in an older one). Nothing is blocked when either release is
     * unknown, so an older Toolkit behaves as before.
     */
    async function newerReleaseMessage(filename, fileRelease) {
      const saved = String(fileRelease || "").trim();
      if (!saved) return "";
      await ensureToolkitAgentHealthy();
      const session = _creoSessionRelease;
      if (!window.__creopdmCreoRelease.newerThanSession(saved, session)) return "";
      return (
        `${filename || "The file"} was saved in Creo ${saved}, but this Creo session is ${session}. ` +
        "A model saved in a newer Creo cannot be opened in an older one."
      );
    }

    async function ensureToolkitAgentHealthy(options) {
      // force: Collect all / Rebuild must not trust a cached "ok" (the agent may have stopped).
      if (options && options.force) _toolkitHealthOkUntil = 0;
      if (Date.now() < _toolkitHealthOkUntil) return { ok: true };
      const agentOnline = await probeCreoAgent();
      if (!agentOnline) {
        return {
          ok: false,
          __error: "toolkit_agent_offline",
          __detail: "creopdm-agent is offline (need /toolkit proxy).",
        };
      }
      const base = agentBase();
      try {
        const healthResp = await fetch(`${base}/toolkit/health`, {
          headers: agentAuthHeaders(),
          signal: abortSignalAfter(5000),
        });
        if (!healthResp.ok) {
          _toolkitHealthOkUntil = 0;
          return {
            ok: false,
            __error: "toolkit_health_failed",
            __detail: await readToolkitAgentError(healthResp, `HTTP ${healthResp.status}`),
          };
        }
        const healthBody = await healthResp.json();
        if (!healthBody || healthBody.ok === false) {
          _toolkitHealthOkUntil = 0;
          return {
            ok: false,
            __error: "toolkit_health_failed",
            __detail: "Toolkit /health via agent was not ok.",
          };
        }
        _toolkitHealthOkUntil = Date.now() + 60000;
        // The Toolkit reports the running Creo release in /health ("creo": {"release": "13.4.1.0"});
        // an older Toolkit does not, and then nothing is ever blocked on release.
        const reported = String(healthBody?.toolkit?.creo?.release || "").trim();
        if (reported) _creoSessionRelease = reported;
        return { ok: true };
      } catch (exc) {
        _toolkitHealthOkUntil = 0;
        return {
          ok: false,
          __error: "toolkit_exception",
          __detail: String(exc?.message || exc || "toolkit health failed"),
        };
      }
    }

    /**
     * A bulk item has no geometry, so the full collect (features, mass, parameters…) fails for it even
     * though the Toolkit still identifies it. Ask for the identity alone: when it says BULK, that is
     * the whole metadata a bulk item has, so save it instead of reporting a failure.
     */
    async function bulkIdentitySnapshot(base, tip, path) {
      try {
        const query = new URLSearchParams({ filename: tip, domains: "identity", timeout: "40" });
        if (path) query.set("path", path);
        const resp = await fetch(`${base}/toolkit/snapshot?${query}`, {
          headers: agentAuthHeaders(),
          signal: abortSignalAfter(50 * 1000),
        });
        if (!resp.ok) return null;
        const body = await resp.json();
        const snapshot = body?.snapshot;
        const identity = snapshot && typeof snapshot === "object" ? snapshot.identity : null;
        if (!body?.ok || !identity) return null;
        const kind = String(identity.model_role || identity.subtype || "").trim().toUpperCase();
        return kind === "BULK" ? snapshot : null;
      } catch {
        return null;
      }
    }

    async function gatherViaToolkitAgent(filename, filePath) {
      const tip = String(filename || "").trim();
      if (!tip) {
        return { __error: "toolkit_bad_filename", __detail: "Missing filename." };
      }
      const health = await ensureToolkitAgentHealthy();
      if (!health.ok) {
        return {
          __error: String(health.__error || "toolkit_health_failed"),
          __detail: String(health.__detail || ""),
        };
      }
      const base = agentBase();
      try {
        // Never CreoJS.openModel here — that creates windows and hits Creo's
        // open-tabs limit (18) during Collect all. Toolkit must silent-Retrieve.
        const path = String(filePath || "").trim();
        const query = new URLSearchParams({ filename: tip });
        if (path) query.set("path", path);
        // Parts and drawings read in seconds; only assemblies and manufacturing models may take
        // long. A stuck file must not hold the rest of a Collect for two minutes.
        const seconds = /\.(asm|mfg)$/i.test(tip) ? 120 : 40;
        query.set("timeout", String(seconds));
        const snapResp = await fetch(`${base}/toolkit/snapshot?${query}`, {
          headers: agentAuthHeaders(),
          signal: abortSignalAfter((seconds + 10) * 1000),
        });
        if (!snapResp.ok) {
          const detail = await readToolkitAgentError(snapResp, `HTTP ${snapResp.status}`);
          if (/newer_release/i.test(detail)) {
            // The Toolkit refused a model saved in a newer Creo: name both releases, do not retry.
            const m = /saved in Creo ([\d.]+); this session is ([\d.]+)/i.exec(detail);
            return {
              __error: "newer_release",
              __detail: m
                ? `${tip} was saved in Creo ${m[1]}, but this Creo session is ${m[2]}. ` +
                  "A model saved in a newer Creo cannot be opened in an older one."
                : `${tip} was saved in a newer Creo than this session. A model saved in a newer Creo cannot be opened in an older one.`,
            };
          }
          return (
            (await bulkIdentitySnapshot(base, tip, path))
            || { __error: "toolkit_snapshot_failed", __detail: detail }
          );
        }
        const body = await snapResp.json();
        const snapshot = body?.snapshot;
        if (!body?.ok || !snapshot || typeof snapshot !== "object" || !snapshot.identity) {
          const bulk = await bulkIdentitySnapshot(base, tip, path);
          if (bulk) return bulk;
          return {
            __error: "toolkit_snapshot_unusable",
            __detail: "Toolkit snapshot missing identity.",
          };
        }
        return snapshot;
      } catch (exc) {
        return {
          __error: "toolkit_exception",
          __detail: String(exc?.message || exc || "toolkit call failed"),
        };
      }
    }

    async function gatherCreoMetadataForFilename(filename, filePath, options) {
      if (!canGatherCreoMetadata() || !filename) return null;
      // Toolkit via agent only (the Creo.JS inventory scripts and probe pages are gone).
      const snapshot = await gatherViaToolkitAgent(filename, filePath || "");
      if (snapshot && snapshot.__error) {
        return {
          __error: String(snapshot.__error || "toolkit_failed"),
          __detail: String(snapshot.__detail || ""),
        };
      }
      return snapshot || {
        __error: "toolkit_unavailable",
        __detail: "Toolkit collect returned nothing.",
      };
    }

    /** One audit row for a whole Collect run (Add -> Collect), never one per file. */
    async function reportMetadataCollectSummary(productId, summary) {
      if (!productId) return;
      try {
        await fetch(`/api/products/${encodeURIComponent(productId)}/metadata-collect-summary`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(summary),
        });
      } catch {
        /* best-effort: the saves themselves are already done */
      }
    }

    /**
     * Open one file of a baseline the way Files opens a file: put the baseline's exact files on this
     * PC (a read-only folder; skipped when it is already there and unchanged), then open the file
     * from that folder in the Creo session, or with Windows when this is not Creo's browser.
     * Shared by the baseline's file list and by the Details page of a baseline file.
     * Returns "" when the file was opened, otherwise the message to show.
     */
    /**
     * How a file opens, decided by the server exactly as for the Files list (Creo session,
     * Multi-CAD, Creo View, Windows) or why it does not (System Settings -> Non openable CAD).
     */
    async function openPlanFor(filename) {
      const response = await fetch("/api/creo/open-plan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename }),
      });
      if (!response.ok) return { error: await readError(response) };
      return { plan: await response.json() };
    }

    async function openBaselineVersion(info, member) {
      if (!info || !member || !member.filename) return "That file is not part of the baseline.";
      // Same decision as the Files list: refused types stop here, before anything is downloaded.
      const planned = await openPlanFor(member.filename);
      if (planned.error) return planned.error;
      const plan = planned.plan;
      const inCreoSession =
        Boolean(plan.creo_object || plan.open_with_creo) &&
        Boolean(shell.hostedCreoJS?.()) &&
        shell.creoOpenMode?.() === "embedded";
      if (inCreoSession) {
        // Before anything is downloaded: a model from a newer Creo cannot open in this session.
        const tooNew = await newerReleaseMessage(member.filename, member.creo_release);
        if (tooNew) return tooNew;
      }
      const agent = await probeCreoAgent();
      if (!agent) {
        return "Start creopdm-agent on this PC so the baseline's files can be downloaded before opening.";
      }
      const agentJson = async (path, extra) => {
        const response = await fetch(`${agentBase()}${path}`, {
          method: "POST",
          headers: agentAuthHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({
            pdm_url: window.location.origin,
            product_id: info.product_uuid || currentProductId(),
            vault_folder: currentVaultFolder(),
            ...agentPdmAuth(),
            ...extra,
          }),
        });
        let body = null;
        try {
          body = await response.json();
        } catch {
          body = null;
        }
        return { ok: response.ok, body };
      };
      const agentMessage = (result, fallback) => {
        const detail = result.body?.detail;
        if (detail && typeof detail === "object") return detail.message || fallback;
        return (typeof detail === "string" && detail) || fallback;
      };
      let folder = "";
      try {
        await withBusy("Preparing the baseline…", async () => {
          if (info.workspace_folder) {
            const check = await agentJson("/baseline-workspace/check", { folder: info.workspace_folder });
            const b = check.body || {};
            if (check.ok && b.installed && !(b.missing?.length || 0) && !(b.modified?.length || 0)) {
              folder = b.path || "";
            }
          }
          if (folder) return;
          const response = await fetch(`/api/baselines/${encodeURIComponent(info.uuid)}/workspace-manifest`);
          if (!response.ok) throw new Error(await readError(response));
          const manifest = await response.json();
          const result = await agentJson("/baseline-workspace", { manifest, overwrite: false });
          if (!result.ok) {
            const conflicts = result.body?.detail?.conflicts;
            throw new Error(
              Array.isArray(conflicts) && conflicts.length
                ? "The baseline's folder on this PC has files that differ from the baseline. Use Download… and replace them first."
                : agentMessage(result, "The baseline could not be put on this PC.")
            );
          }
          folder = result.body?.path || "";
        });
      } catch (err) {
        return err?.message || "The baseline could not be put on this PC.";
      }
      if (!folder) return "The agent did not say where the baseline is.";
      const fullPath = joinLocalWorkspacePath(folder, member.relative_path || member.filename);
      const dir = String(fullPath).replace(/[\\/][^\\/]*$/, "");
      try {
        if (inCreoSession) {
          await withBusy("Opening in Creo…", async () => {
            await whenCreoJSReady();
            const opened = await window.CreoJS.openModel(dir, member.filename, "", member.filename, fullPath);
            const text = opened == null ? "" : String(opened);
            if (text.indexOf("CREOPDM_ERROR:") === 0) throw new Error(text.slice("CREOPDM_ERROR:".length));
          });
          return "";
        }
        await withBusy("Opening…", async () => {
          const response = await fetch(`${agentBase()}/open`, {
            method: "POST",
            headers: agentAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ path: fullPath, mode: "association" }),
          });
          if (!response.ok) throw new Error(await readError(response));
        });
      } catch (err) {
        return err?.message || "The file could not be opened.";
      }
      return "";
    }

    /** Tell the user which files got no metadata, and why that usually is. */
    function noteCollectFailures(failed, fromOpen) {
      if (!failed.length) return;
      const shown = failed.slice(0, 3).map((target) => target.filename).join(", ");
      const more = failed.length > 3 ? `, +${failed.length - 3} more` : "";
      const needsModels = failed.some((target) => /\.(drw|asm)$/i.test(target.filename));
      const reason = fromOpen
        ? "Creo did not report the model in its session."
        : "Creo could not read the file.";
      const hint = needsModels
        ? " A drawing or assembly needs the models it uses to be in the product."
        : "";
      // A manual Collect knows the Toolkit's own reason for the first file: show it.
      const detail = String(failed.find((target) => target.detail)?.detail || "").trim();
      const why = detail ? ` (${detail.slice(0, 160)})` : "";
      // Files from a newer Creo: the reason IS the explanation, without the generic wording.
      let newerText = "";
      if (failed.every((target) => target.newerRelease)) {
        // One sentence for all of them (not the first file's reason): which releases, which session.
        const saved = new Set();
        const running = new Set();
        failed.forEach((target) => {
          const m = /saved in Creo (\d+(?:\.\d+)*),? but this Creo session is (\d+(?:\.\d+)*)/i.exec(target.detail || "");
          if (m) {
            saved.add(m[1]);
            running.add(m[2]);
          }
        });
        newerText =
          saved.size && running.size === 1
            ? `Metadata was not collected for ${shown}${more}: ${failed.length > 1 ? "these models were" : "this model was"} ` +
              `saved in Creo ${[...saved].join(" / ")}, but this Creo session is ${[...running][0]}. ` +
              "A model saved in a newer Creo cannot be opened in an older one."
            : `Metadata was not collected for ${shown}${more}: ${detail}`;
      }
      const text = newerText
        ? newerText
        : `Metadata was not collected for ${shown}${more}. ${reason}${why}${hint} Collect it again once that is fixed.`;
      showError($("#toolbar-error"), text);
      // A reload right after Add / Check in would clear the message: keep it for the next page,
      // but never past the moment it was meant for.
      try {
        window.sessionStorage.setItem("creopdmNotice", text);
        window.setTimeout(() => {
          try {
            if (window.sessionStorage.getItem("creopdmNotice") === text) {
              window.sessionStorage.removeItem("creopdmNotice");
            }
          } catch {
            /* ignore */
          }
        }, 8000);
      } catch {
        /* private mode / blocked storage */
      }
    }

    async function pushCreoMetadataForItems(items, options) {
      const opts = options && typeof options === "object" ? options : {};
      const collectStartedAt = Date.now();
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
            relativePath: String(
              item?.relativePath || item?.relative_path || ""
            ).trim(),
            versionId: String(item?.version_id || item?.current_version?.uuid || "").trim(),
            creoRelease: String(item?.creo_release || item?.current_version?.creo_release || "").trim(),
          }))
          .filter((item) => item.uuid && item.filename && isCreoMetadataCandidate(item.filename))
      );
      let saved = 0;
      const savedIds = new Set();
      if (!targets.length || !canGatherCreoMetadata()) return saved;
      // Add uploads to the vault only — it does not fill the product agent cache.
      // Collect must use cleaned vault tips (not the pick-folder source), so rematerialize
      // once, then resolve paths from the cache (same warm as Collect all).
      if (!sessionOnly) {
        const productId = String(opts.productId || currentProductId() || "").trim();
        targets.forEach((target) => {
          target.path = "";
        });
        const ids = targets.map((target) => target.uuid).filter(Boolean);
        if (ids.length) {
          if (showProgress) {
            publishBusyMessage(
              ids.length === 1
                ? "Updating local workspace…"
                : `Updating local workspace… 0 of ${ids.length}`
            );
          }
          try {
            await materializeCheckedOutToAgentCache(ids, (done, total) => {
              if (!showProgress || total <= 1) return;
              publishBusyMessage(`Updating local workspace… ${done} of ${total}`);
            });
          } catch {
            /* per-tip prepareLocalPathForMetadata still works */
          }
        }
        if (productId) {
          if (showProgress) {
            publishBusyMessage("Checking local workspace tips…");
          }
          await attachCollectLocalPaths(productId, targets);
        }
      }
      for (let i = 0; i < targets.length; i += 1) {
        const target = targets[i];
        if (showProgress) {
          publishBusyMessage(metadataBusyText(i + 1, targets.length, target.filename));
        }
        let snapshot = null;
        // A model saved in a newer Creo than this session cannot be read: say so, do not try.
        const tooNew = await newerReleaseMessage(target.filename, target.creoRelease);
        if (tooNew) {
          target.detail = tooNew;
          target.newerRelease = true;
          continue;
        }
        // Open (sessionOnly / wait rounds): model is already in Creo — gather by
        // tip name only. Add / Check In / batch: go straight to path= (one /collect).
        // Empty-session probes logged retrieved=0 total=0ms and doubled every tip.
        if (sessionOnly || sessionWaitRounds > 0) {
          for (let round = 0; round <= sessionWaitRounds; round += 1) {
            snapshot = await gatherCreoMetadataForFilename(target.filename, "", {
              featureNames,
            });
            if (snapshot && snapshot.__error) {
              if (snapshot.__error === "newer_release") {
                target.detail = snapshot.__detail;
                target.newerRelease = true;
              }
              snapshot = null;
            }
            if (snapshot || target.newerRelease) break; // a newer file never appears in this session
            if (round < sessionWaitRounds) {
              await new Promise((resolve) => window.setTimeout(resolve, sessionWaitMs));
            }
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
          if (snapshot && snapshot.__error) {
            if (snapshot.__error === "newer_release") {
              target.detail = snapshot.__detail;
              target.newerRelease = true;
            }
            snapshot = null;
          }
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
          // Toolkit can return mass; Creo.JS gather used to omit it — keep mass when present.
          mass:
            snapshot.mass && typeof snapshot.mass === "object" ? snapshot.mass : null,
          family_table: snapshot.family_table || null,
          features: Array.isArray(snapshot.features) && snapshot.features.length
            ? snapshot.features
            : null,
          structure: Array.isArray(snapshot.structure) ? snapshot.structure : null,
          simp_reps: snapshot.simp_reps && typeof snapshot.simp_reps === "object"
            ? snapshot.simp_reps
            : null,
          constraints: snapshot.constraints && typeof snapshot.constraints === "object"
            ? snapshot.constraints
            : null,
          relations: snapshot.relations && typeof snapshot.relations === "object"
            ? snapshot.relations
            : null,
          // Creo 2D section (.sec): Toolkit sketch domain (outline, entities, dimensions…).
          sketch: snapshot.sketch && typeof snapshot.sketch === "object" ? snapshot.sketch : null,
        };
        if (!body.mass) delete body.mass;
        if (!body.sketch) delete body.sketch;
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
            savedIds.add(target.uuid);
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
      // A file the Toolkit could not read leaves no metadata: say so instead of staying silent.
      noteCollectFailures(
        targets.filter((target) => !savedIds.has(target.uuid)),
        sessionOnly
      );
      // Add -> Collect passes audit:true. Open and Check-in collect quietly (one file at a time,
      // and Check-in already has its own audit row), so they never write a summary.
      if (opts.audit && !sessionOnly) {
        await reportMetadataCollectSummary(String(opts.productId || currentProductId() || "").trim(), {
          total: targets.length,
          saved,
          failed: Math.max(0, targets.length - saved),
          seconds: Math.max(0, (Date.now() - collectStartedAt) / 1000),
        });
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
      // A Released (or otherwise locked) product cannot take metadata: opening a file there is
      // read-only, so there is nothing to capture and nothing to report.
      const productId = String(currentProductId() || "").trim();
      if (productId) {
        try {
          const response = await fetch(`/api/products/${encodeURIComponent(productId)}`);
          const access = response.ok ? await response.json() : null;
          if (access && access.allows_edit_metadata === false) return 0;
        } catch {
          /* unknown: try the capture as before */
        }
      }
      // Nothing changed since the last collect: the current version already has its metadata
      // (it belongs to the version, so a new check-in or revise is collected again), so opening
      // the file again must not scan it again.
      const pending = [];
      for (const item of items) {
        try {
          const response = await fetch(`/api/objects/${encodeURIComponent(item.uuid)}`);
          const object = response.ok ? await response.json() : null;
          if (object && object.creo_metadata_captured === true) continue;
        } catch {
          /* unknown: collect */
        }
        pending.push(item);
      }
      if (!pending.length) return 0;
      let saved = 0;
      await withBusy("Capturing Creo metadata…", async () => {
        // Embedded Open prefers File > Open trail (returns before retrieve finishes).
        // Wait for the model in session; never disk-Retrieve after Open.
        saved = await pushCreoMetadataForItems(pending, {
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

    async function materializeCheckedOutToAgentCacheZip(objectIds, prepared, identities) {
      // Checkout supplies identities straight from its response: the agent then skips
      // the manifest fetch and the files that already match by hash and size.
      const planItems = Array.isArray(identities) && identities.length
        ? cachePlanItemsFromPrepared({
            product_id: currentProductId() || "",
            dependencies: identities,
          })
        : cachePlanItemsFromPrepared(prepared);
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

    async function materializeCheckedOutToAgentCache(objectIds, onProgress, options) {
      const ids = [...new Set((objectIds || []).filter(Boolean))];
      if (!ids.length) return { agentOffline: false, ok: 0, failed: 0 };
      const agent = await probeCreoAgent();
      if (!agent) return { agentOffline: true, ok: 0, failed: 0 };
      const total = ids.length;
      // One vault zip for 2+ tips (Add Collect was paying /creo/open + GET per file
      // until BULK_AGENT_CACHE_ZIP_THRESHOLD=50). Single tip stays per-file.
      if (total >= 2) {
        if (typeof onProgress === "function") onProgress(0, total);
        try {
          const zipResult = await materializeCheckedOutToAgentCacheZip(
            ids,
            null,
            options && Array.isArray(options.planItems) ? options.planItems : null
          );
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
      const preserveNewer = Boolean(options && options.preserveNewer);
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
          await materializeViaAgent(
            preserveNewer ? { ...prepared, replace_newer: false } : prepared
          );
          ok += 1;
        } catch {
          failed += 1;
        }
      }
      return { agentOffline: false, ok, failed };
    }

    mod.attachCollectLocalPaths = attachCollectLocalPaths;
    mod.prepareLocalPathForMetadata = prepareLocalPathForMetadata;
    mod.gatherCreoMetadataForFilename = gatherCreoMetadataForFilename;
    mod.ensureToolkitAgentHealthy = ensureToolkitAgentHealthy;
    mod.pushCreoMetadataForItems = pushCreoMetadataForItems;
    mod.noteCollectFailures = noteCollectFailures;
    mod.openBaselineVersion = openBaselineVersion;
    mod.newerReleaseMessage = newerReleaseMessage;
    mod.captureCreoMetadataAfterOpen = captureCreoMetadataAfterOpen;
    mod.rematerializeCheckedInLocalTips = rematerializeCheckedInLocalTips;
    mod.materializeViaAgent = materializeViaAgent;
    mod.materializeViaAgentPerFile = materializeViaAgentPerFile;
    mod.materializeCheckedOutToAgentCache = materializeCheckedOutToAgentCache;
    mod.materializeCheckedOutToAgentCacheZip = materializeCheckedOutToAgentCacheZip;
  },
};
