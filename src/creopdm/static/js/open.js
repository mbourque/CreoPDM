window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.open = {
  /**
   * Open from vault / local workspace: chooser, checkout-before-open, prepare,
   * materialize (via creo_workspace), File > Open trail, Windows association.
   * Loaded lazily (ensureModule("open")) on first Open — Files browse never needs it.
   *
   * open-large-assembly-deps: keep creoOpenModelTimeoutMs(preparedDependencyCount(…)),
   * openWorkTimeoutMs, File > Open trail (no WD by default), session-only metadata after Open.
   */
  init(shell) {
    const mod = window.__creopdmModules.open;
    const $ = shell.$;
    const showError = shell.showError;
    const withBusy = shell.withBusy;
    const setBusyMessage = shell.setBusyMessage;
    const withTimeout = shell.withTimeout;
    const postAction = shell.postAction;
    const assertProductAllows = shell.assertProductAllows;
    const currentProductId = shell.currentProductId;
    const currentVaultFolder = shell.currentVaultFolder;
    const probeCreoAgent = shell.probeCreoAgent;
    const agentBase = shell.agentBase;
    const agentAuthHeaders = shell.agentAuthHeaders;
    const abortSignalAfter = shell.abortSignalAfter;
    const readError = shell.readError;
    const creoOpenMode = shell.creoOpenMode;
    const hostedCreoJS = shell.hostedCreoJS;
    const likelyStandaloneBrowser = shell.likelyStandaloneBrowser;
    const creoJSReady = shell.creoJSReady;
    const whenCreoJSReady = shell.whenCreoJSReady;
    const setCreoWorkingDirectory = shell.setCreoWorkingDirectory;
    const agentWorkdir = shell.agentWorkdir;
    const joinLocalWorkspacePath = shell.joinLocalWorkspacePath;
    const PathBasename = shell.PathBasename;
    const logicalUploadName = shell.logicalUploadName;
    const creoOpenModelTimeoutMs = shell.creoOpenModelTimeoutMs;
    const openWorkTimeoutMs = shell.openWorkTimeoutMs;
    const preparedDependencyCount = shell.preparedDependencyCount;
    const openRequestBody = shell.openRequestBody;
    const openTargetObjectId = shell.openTargetObjectId;
    const openTargetFilename = shell.openTargetFilename;
    const rowCheckoutKind = shell.rowCheckoutKind;
    const rowOffersCheckout = shell.rowOffersCheckout;
    const userCanCheckout = shell.userCanCheckout;
    const isModalDialog = shell.isModalDialog;
    const applyCheckedOutOnRows = shell.applyCheckedOutOnRows;
    const formatBatch = shell.formatBatch;
    const reloadPage = shell.reloadPage;
    const isListPage = shell.isListPage;
    const setOpenPrepareBusyMessage = shell.setOpenPrepareBusyMessage;
    const setOpenDownloadBusyMessage = shell.setOpenDownloadBusyMessage;
    // creo_workspace wrappers (load that module on demand).
    const materializeViaAgent = shell.materializeViaAgent;
    const captureCreoMetadataAfterOpen = shell.captureCreoMetadataAfterOpen;

    function promptOpenCheckout({ filename, canCheckout }) {
      const dialog = $("#open-checkout-dialog");
      const form = $("#open-checkout-form");
      const lead = $("#open-checkout-lead");
      const fileWrap = $("#open-checkout-file-wrap");
      const dependenciesWrap = $("#open-checkout-dependencies-wrap");
      const dependenciesNote = $("#open-checkout-dependencies-note");
      const wdWrap = $("#open-checkout-wd-wrap");
      const wdBox = $("#open-checkout-set-wd");
      const openRadio = $("#open-action-open");
      const cancelBtn = $("#open-checkout-cancel");
      const err = $("#open-checkout-error");
      // Object availability AND signed-in user objects.checkout capability.
      const allowCheckout = Boolean(canCheckout) && userCanCheckout();
      // Working directory only applies inside Creo's embedded browser.
      // Off by default — File > Open trail is enough; Set WD locks the workspace
      // folder (WinError 32 on Delete product / remove-folder). Opt-in via checkbox.
      const showWd = hostedCreoJS();
      // Viewer (or any case with no checkout choice): skip a one-option dialog.
      if (!allowCheckout) {
        return Promise.resolve({ action: "open", setWorkingDirectory: false });
      }
      if (!dialog || !form || !openRadio) {
        // Do not silently open when checkout was an option — that hid the chooser.
        showError(
          $("#toolbar-error"),
          "Could not show the Open dialog. Hard-refresh (F5) and try again."
        );
        return Promise.resolve({ action: "cancel", setWorkingDirectory: false });
      }
      if (lead) {
        lead.textContent = `How do you want to open ${filename}?`;
      }
      showError(err, "");
      if (fileWrap) fileWrap.hidden = false;
      if (dependenciesWrap) dependenciesWrap.hidden = false;
      if (dependenciesNote) dependenciesNote.hidden = false;
      if (wdWrap) wdWrap.hidden = !showWd;
      openRadio.checked = true;
      if (wdBox) {
        wdBox.disabled = !showWd;
        wdBox.checked = false;
      }
      const fileRadio = $("#open-action-checkout-file");
      const dependenciesRadio = $("#open-action-checkout-dependencies");
      if (fileRadio) fileRadio.disabled = false;
      if (dependenciesRadio) dependenciesRadio.disabled = false;

      return new Promise((resolve) => {
        const finish = (action) => {
          form.removeEventListener("submit", onSubmit);
          cancelBtn?.removeEventListener("click", onCancel);
          dialog.removeEventListener("cancel", onCancel);
          try {
            if (dialog.open) dialog.close();
            else dialog.removeAttribute("open");
          } catch {
            try {
              dialog.removeAttribute("open");
            } catch {
              /* ignore */
            }
          }
          resolve({
            action,
            setWorkingDirectory: showWd && Boolean(wdBox?.checked),
          });
        };
        const onCancel = (event) => {
          event?.preventDefault?.();
          finish("cancel");
        };
        const onSubmit = (event) => {
          event.preventDefault();
          event.stopPropagation?.();
          const selected = form.querySelector('input[name="open_action"]:checked');
          finish(selected?.value || "open");
        };
        form.addEventListener("submit", onSubmit);
        cancelBtn?.addEventListener("click", onCancel);
        dialog.addEventListener("cancel", onCancel);
        try {
          if (isModalDialog(dialog)) {
            if (!dialog.open) dialog.showModal();
          } else {
            // Last resort when showModal is missing — still block behind a visible panel.
            dialog.setAttribute("open", "");
          }
        } catch {
          dialog.setAttribute("open", "");
        }
        if (!dialog.open && !dialog.hasAttribute("open")) {
          showError(
            $("#toolbar-error"),
            "Could not show the Open dialog. Hard-refresh (F5) and try again."
          );
          finish("cancel");
        }
      });
    }

    async function checkoutBeforeOpen(target, withDependencies) {
      const objectId = openTargetObjectId(target);
      if (!objectId) return [];
      const gate = await assertProductAllows(currentProductId(), "checkout");
      if (!gate.ok) return null;
      if (!withDependencies) {
        const result = await postAction(
          `/api/objects/${objectId}/checkout`,
          undefined,
          "POST",
          "Checking out…"
        );
        return result ? [objectId] : null;
      }
      const prepared = await postAction(
        "/api/creo/open",
        openRequestBody(target, false, true),
        "POST",
        "Finding dependencies…"
      );
      if (!prepared) return null;
      const ids = [
        objectId,
        ...((prepared.dependencies || []).map((item) => item.object_id).filter(Boolean)),
      ];
      const unique = [...new Set(ids)];
      if (unique.length === 1) {
        const result = await postAction(
          `/api/objects/${unique[0]}/checkout`,
          undefined,
          "POST",
          "Checking out…"
        );
        return result ? unique : null;
      }
      const result = await postAction(
        "/api/objects/batch/checkout",
        { object_ids: unique },
        "POST",
        `Checking out ${unique.length} files…`
      );
      if (!result) return null;
      const warning = formatBatch(result);
      if (warning) showError($("#toolbar-error"), warning);
      if (!result.ok?.length) return null;
      return result.ok.map((item) => item.uuid).filter(Boolean);
    }

    async function openPdmObjectFromUi(target, row) {
      const openGate = await assertProductAllows(currentProductId(), "download");
      if (!openGate.ok) return;
      const objectId = openTargetObjectId(target);
      const filename = openTargetFilename(target, row);
      const kind = rowCheckoutKind(row);
      // Only skip the chooser when the Checkout column says it is already mine.
      // Do not trust data-owned alone — a stale "1" was opening Available files
      // with no modal. Do not Set WD on Open by default (locks workspace folder).
      if (objectId && kind === "mine") {
        return openPdmObject(target, { setWorkingDirectory: false });
      }
      const canCheckout =
        Boolean(objectId) &&
        userCanCheckout() &&
        kind !== "other" &&
        kind !== "locked" &&
        (kind === "available" || kind === "" || rowOffersCheckout(row));
      const choice = await promptOpenCheckout({
        filename,
        canCheckout,
        owned: false,
      });
      const action = typeof choice === "string" ? choice : choice?.action;
      const setWd = Boolean(choice && typeof choice === "object" && choice.setWorkingDirectory);
      if (action === "cancel") return null;
      if (action === "checkout-file" || action === "checkout-dependencies") {
        const checkedOutIds = await checkoutBeforeOpen(
          target,
          action === "checkout-dependencies"
        );
        if (!checkedOutIds) return null;
        // Paint before openModel — Creo collapses the embedded browser on Display.
        applyCheckedOutOnRows(checkedOutIds);
      }
      // WD is applied inside openPdmObjectWork (before openModel) so skip-chooser
      // and chooser paths share one place; quiet during the Opening… overlay.
      return openPdmObject(target, { setWorkingDirectory: setWd });
    }

    async function openViaAgent(localPath, mode) {
      const response = await fetch(`${agentBase()}/open`, {
        method: "POST",
        headers: agentAuthHeaders({ "Content-Type": "application/json" }),
        signal: abortSignalAfter(60000),
        body: JSON.stringify({ path: localPath, mode: mode || "association" }),
      });
      if (!response.ok) {
        const message = await readError(response);
        throw new Error(message || "Local CreoPDM agent could not open the file.");
      }
      return response.json();
    }

    async function openLocalCacheRelative(productId, relativePath, options) {
      // New file (local) / Modified newer local — open agent workspace tip.
      // Creo.JS needs the logical tip name (shaft.prt); disk may still be shaft.prt.1.
      const objectId = String(options?.objectId || "").trim();
      const wantSetWd = options?.setWorkingDirectory === true;
      const agent = await probeCreoAgent();
      if (!agent) {
        throw new Error(
          "Start creopdm-agent on this Creo PC to open files that exist only in the local workspace."
        );
      }
      const directory = await agentWorkdir(productId, currentVaultFolder());
      const fullPath = joinLocalWorkspacePath(directory, relativePath);
      if (!fullPath) {
        throw new Error("Could not resolve the local workspace path for that file.");
      }
      const diskName = PathBasename(relativePath) || "file";
      const logicalName = logicalUploadName(diskName) || diskName;
      const embeddedMode = creoOpenMode() === "embedded";
      // Same brief Creo.JS wait as vault Open — do not fall through to Windows
      // association from the embedded browser while the bridge is still linking.
      if (embeddedMode && !hostedCreoJS() && !likelyStandaloneBrowser()) {
        setBusyMessage("Waiting for Creo.JS…");
        try {
          await Promise.race([
            creoJSReady,
            new Promise((resolve) => window.setTimeout(resolve, 8000)),
          ]);
        } catch {
          /* ignore */
        }
        for (let i = 0; i < 12 && !hostedCreoJS(); i += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
      }
      const useCreoSession = hostedCreoJS() && embeddedMode;
      if (useCreoSession) {
        setBusyMessage("Opening in Creo…");
        await whenCreoJSReady();
        // Opt-in only — Set WD locks the workspace folder for later remove-folder.
        if (wantSetWd) {
          await setCreoWorkingDirectory({ quiet: true });
        }
        const opened = await withTimeout(
          window.CreoJS.openModel(directory, logicalName, "", diskName, fullPath),
          creoOpenModelTimeoutMs(1),
          "Creo did not finish opening the model (session may be offline)."
        );
        const openedText = opened == null ? "" : String(opened);
        if (openedText.indexOf("CREOPDM_ERROR:") === 0) {
          throw new Error(openedText.slice("CREOPDM_ERROR:".length));
        }
        return {
          path: fullPath,
          filename: logicalName,
          working_directory: directory,
          object_id: objectId || null,
          // Same flag as vault Creo.JS open — enables opportunistic metadata capture.
          creo_object: true,
        };
      }
      if (embeddedMode && !useCreoSession && !likelyStandaloneBrowser()) {
        throw new Error(
          "Creo.JS is not connected yet. Wait until the status shows Creo: Connected, then open the file again — do not open via Windows file association from the embedded browser."
        );
      }
      setBusyMessage("Opening with Windows…");
      await openViaAgent(fullPath, "association");
      return {
        path: fullPath,
        filename: logicalName,
        working_directory: directory,
        object_id: objectId || null,
        creo_object: false,
      };
    }

    function openTimeoutMessage() {
      if (creoOpenMode() === "embedded" && !likelyStandaloneBrowser()) {
        return "Open timed out. Check creopdm-agent and that Creo is Connected, then try again.";
      }
      return "Open timed out. Check that creopdm-agent is running, then try again.";
    }

    async function openPdmObject(target, options) {
      // Keep the busy overlay up through prepare + materialize until Creo/OS open starts.
      // Always clear on timeout/error so Session offline / hung agent cannot leave Opening… stuck.
      const openOpts = options && typeof options === "object" ? options : {};
      let result = null;
      await withBusy("Preparing…", async () => {
        try {
          result = await withTimeout(
            openPdmObjectWork(target, openOpts),
            openWorkTimeoutMs(5000),
            openTimeoutMessage()
          );
        } catch (err) {
          const message = err && err.message ? err.message : String(err);
          showError($("#toolbar-error"), message || "Could not open the file.");
          result = null;
        }
      });
      // Best-effort: fill Creo identity/type/deps while the model is in session.
      // Metadata POST updates Type / Features / Where Used — soft-refresh Files or
      // Details so SSR is not stale until the user navigates away and back.
      let metadataSaved = 0;
      try {
        metadataSaved = Number(await captureCreoMetadataAfterOpen(result)) || 0;
      } catch {
        /* soft-fail — open already succeeded */
      }
      const onDetail = Boolean($("article.detail"));
      if (metadataSaved > 0 && (isListPage || onDetail)) {
        try {
          if (onDetail) {
            // Keep Features (etc.) selected across the soft-refresh.
            const tab = document
              .querySelector(".tabs .tab.is-active")
              ?.getAttribute("data-tab");
            if (tab && tab !== "overview") {
              try {
                const url = new URL(window.location.href);
                url.hash = tab;
                window.history.replaceState(window.history.state, "", url.toString());
              } catch {
                /* ignore */
              }
            }
          }
          await reloadPage({ keepBusy: true, busyMessage: "Refreshing…" });
        } catch {
          /* soft-fail — Open + metadata already succeeded */
        }
      }
      return result;
    }

    async function openPdmObjectWork(target, options) {
      const spec = typeof target === "string" ? { objectId: target } : target || {};
      const openOpts = options && typeof options === "object" ? options : {};
      // Set WD only when the Open chooser checkbox was checked (or caller opted in).
      // Default off — File > Open trail resolves companions; WD locks the folder.
      const wantSetWd = Boolean(openOpts.setWorkingDirectory);
      // Local-workspace tips (New file local / Newer local save on Modified) must
      // open from the agent cache — not /api/creo/open (vault tip / missing file).
      if (spec.localCache && spec.relativePath) {
        const productId = spec.productId || currentProductId();
        if (!productId) {
          showError($("#toolbar-error"), "No product is selected.");
          return null;
        }
        return openLocalCacheRelative(productId, spec.relativePath, {
          objectId: spec.objectId || "",
          setWorkingDirectory: wantSetWd,
        });
      }
      // Only use Creo.JS when we are actually in Creo's embedded browser.
      // Outside Creo (Chrome/Edge), always materialize + Windows association.
      // Do not await creoJSReady first on the association path — Session offline
      // can stall that load forever while the Opening… overlay stays up.
      const embeddedMode = creoOpenMode() === "embedded";
      // Only wait inside Creo (or unknown hosts). Plain Chrome/Edge must not stall.
      if (embeddedMode && !hostedCreoJS() && !likelyStandaloneBrowser()) {
        // Brief wait — clicking Open before the bridge attaches used to fall through
        // to Windows file association and launch a second Creo.
        setBusyMessage("Waiting for Creo.JS…");
        try {
          await Promise.race([
            creoJSReady,
            new Promise((resolve) => window.setTimeout(resolve, 8000)),
          ]);
        } catch {
          /* ignore */
        }
        for (let i = 0; i < 12 && !hostedCreoJS(); i += 1) {
          await new Promise((resolve) => window.setTimeout(resolve, 250));
        }
      }
      const useCreoSession = hostedCreoJS() && embeddedMode;
      if (embeddedMode && !useCreoSession && !likelyStandaloneBrowser()) {
        showError(
          $("#toolbar-error"),
          "Creo.JS is not connected yet. Wait until the status shows Creo: Connected, then open the file again — do not open via Windows file association from the embedded browser."
        );
        return null;
      }
      if (useCreoSession) {
        await creoJSReady;
        setOpenPrepareBusyMessage();
        const prepared = await postAction(
          "/api/creo/open",
          openRequestBody(target, false),
          "POST",
          ""
        );
        if (!prepared) return null;

        // Every Creo-openable model must land in the local workspace before open.
        let openSpec = prepared;
        const needsCache =
          prepared.requires_agent_cache || prepared.creo_object || prepared.open_with_creo;
        if (needsCache) {
          const agent = await probeCreoAgent();
          if (!agent) {
            showError(
              $("#toolbar-error"),
              "Start creopdm-agent on this Creo PC so the file can download into the local workspace before open."
            );
            return null;
          }
          try {
            setOpenDownloadBusyMessage(prepared);
            openSpec = await materializeViaAgent(prepared);
          } catch (err) {
            const message = err && err.message ? err.message : String(err);
            showError(
              $("#toolbar-error"),
              message || "Local CreoPDM agent could not download the file into the workspace."
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
            setBusyMessage("Opening in Creo…");
            await whenCreoJSReady();
            // Opt-in Set WD only (checkbox); trail open does not need WD.
            if (wantSetWd) {
              await setCreoWorkingDirectory({ quiet: true });
            }
            const opened = await withTimeout(
              window.CreoJS.openModel(
                openSpec.working_directory,
                openSpec.filename || prepared.filename,
                prepared.creo_release || "",
                openSpec.disk_name || openSpec.filename || prepared.filename,
                openSpec.path || ""
              ),
              creoOpenModelTimeoutMs(preparedDependencyCount(prepared)),
              "Creo did not finish opening the model (session may be offline)."
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
              "Open SolidWorks / Multi-CAD files from Creo's built-in browser so the running session can use the local workspace."
            );
            return null;
          }
          try {
            setBusyMessage("Opening in Creo…");
            await whenCreoJSReady();
            const directory = openSpec.working_directory || "";
            const diskName = openSpec.disk_name || openSpec.filename || prepared.filename;
            // Do not set Creo session WD — the File > Open trail navigates to the
            // agent cache folder via opt_EMBED_BROWSER_TB_SAB_LAYOUT.
            const opened = await withTimeout(
              window.CreoJS.openModel(
                directory,
                openSpec.filename || prepared.filename,
                "",
                diskName,
                openSpec.path || ""
              ),
              creoOpenModelTimeoutMs(preparedDependencyCount(prepared)),
              "Creo did not finish opening the Multi-CAD file (session may be offline)."
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
                setOpenDownloadBusyMessage(prepared);
                openSpec = await materializeViaAgent(prepared);
              }
              setBusyMessage("Opening with Windows…");
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

      // Not in Creo embedded browser: download via agent and open with Windows association.
      setOpenPrepareBusyMessage();
      const prepared = await postAction(
        "/api/creo/open",
        openRequestBody(target, false),
        "POST",
        ""
      );
      if (!prepared) return null;
      try {
        const agent = await probeCreoAgent();
        if (agent) {
          setOpenDownloadBusyMessage(prepared);
          const openSpec = await materializeViaAgent(prepared);
          if (!openSpec?.path) {
            showError($("#toolbar-error"), "Local agent did not return a workspace path.");
            return null;
          }
          setBusyMessage("Opening with Windows…");
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
      // No agent: browser download (OS association after save).
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

    mod.openPdmObjectFromUi = openPdmObjectFromUi;
    mod.openPdmObject = openPdmObject;
    mod.openPdmObjectWork = openPdmObjectWork;
    mod.openLocalCacheRelative = openLocalCacheRelative;
    mod.openViaAgent = openViaAgent;
    mod.promptOpenCheckout = promptOpenCheckout;
    mod.checkoutBeforeOpen = checkoutBeforeOpen;
    mod.openPdmLaunchResult = openPdmLaunchResult;
  },
};
