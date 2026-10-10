window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.checkout = {
  /**
   * Checkout / Undo / Force Undo from the Files toolbar.
   * Loaded lazily (ensureModule("checkout")) on first Checkout — Files browse never needs it.
   */
  init(shell) {
    const mod = window.__creopdmModules.checkout;
    const $ = shell.$;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const withBusy = shell.withBusy;
    const setBusyMessage = shell.setBusyMessage;
    const postAction = shell.postAction;
    const assertProductAllows = shell.assertProductAllows;
    const currentProductId = shell.currentProductId;
    const confirmLargeBulk = shell.confirmLargeBulk;
    const selectedRows = shell.selectedRows;
    const selectedIds = shell.selectedIds;
    const rowObjectIds = shell.rowObjectIds;
    const formatBatch = shell.formatBatch;
    const applyCheckedOutOnRows = shell.applyCheckedOutOnRows;
    const applyUndoCheckoutOnRows = shell.applyUndoCheckoutOnRows;
    const materializeCheckedOutToAgentCache = shell.materializeCheckedOutToAgentCache;
    const setCheckoutableCount = shell.setCheckoutableCount;
    const rememberWatchView = shell.rememberWatchView;
    const reloadPage = shell.reloadPage;
    const readError = shell.readError;
    const BULK_AGENT_CACHE_ZIP_THRESHOLD = shell.BULK_AGENT_CACHE_ZIP_THRESHOLD;
    const BULK_SLOW_WARN_THRESHOLD = shell.BULK_SLOW_WARN_THRESHOLD;

    const checkoutProductBtn = $("#checkout-product-btn");
    const openWorkspaceBtn = $("#open-workspace-btn");
    const forceUndoBtn = $("#force-undo-btn");

    async function runCheckoutObjects(objectIds) {
      const ids = [...new Set((objectIds || []).filter(Boolean))];
      if (!ids.length) return false;
      const gate = await assertProductAllows(currentProductId(), "checkout");
      if (!gate.ok) return false;
      if (!confirmLargeBulk("Check out", ids.length)) return false;
      showError($("#toolbar-error"), "");
      let checkoutResult = null;
      if (ids.length === 1 && !selectedRows().length) {
        checkoutResult = await postAction(
          `/api/objects/${ids[0]}/checkout`,
          undefined,
          "POST",
          "Checking out…"
        );
        if (!checkoutResult) return false;
      } else {
        const CHECKOUT_CHUNK = 50;
        const total = ids.length;
        checkoutResult = await withBusy(`Checking out… 0 of ${total}`, async () => {
          const merged = { ok: [], failed: [] };
          for (let start = 0; start < ids.length; start += CHECKOUT_CHUNK) {
            const chunk = ids.slice(start, start + CHECKOUT_CHUNK);
            setBusyMessage(`Checking out… ${Math.min(start + chunk.length, total)} of ${total}`);
            const part = await postAction(
              "/api/objects/batch/checkout",
              { object_ids: chunk },
              "POST",
              ""
            );
            if (!part) return null;
            if (Array.isArray(part.ok)) merged.ok.push(...part.ok);
            if (Array.isArray(part.failed)) merged.failed.push(...part.failed);
          }
          return merged;
        });
        if (!checkoutResult) return false;
        const warning = formatBatch(checkoutResult);
        if (warning) showError($("#toolbar-error"), warning);
        if (!checkoutResult.ok?.length) return false;
      }
      const syncedIds =
        Array.isArray(checkoutResult.ok) && checkoutResult.ok.length
          ? checkoutResult.ok.map((item) => item.uuid).filter(Boolean)
          : ids;
      const sync = await withBusy("Downloading checked-out files to local workspace…", async () => {
        try {
          return await materializeCheckedOutToAgentCache(syncedIds, (done, total) => {
            if (total >= BULK_AGENT_CACHE_ZIP_THRESHOLD && done === 0) {
              setBusyMessage(`Checking local workspace for ${total} files…`);
            } else {
              setBusyMessage(`Downloading checked-out files… ${done} of ${total}`);
            }
          });
        } catch (err) {
          showError($("#toolbar-error"), err?.message || String(err));
          return null;
        }
      });
      if (sync?.agentOffline) {
        showError(
          $("#toolbar-error"),
          "Checked out on the server, but creopdm-agent is not running — local workspace was not updated. Start the agent and open the files, or check out again."
        );
      } else if (sync && sync.failed && !sync.ok) {
        showError(
          $("#toolbar-error"),
          "Checked out, but could not download files into the local workspace."
        );
      } else if (sync?.ok) {
        const note = sync.failed
          ? `${sync.ok} file(s) in local workspace (${sync.failed} failed).`
          : sync.downloaded != null && (sync.skipped || sync.keptNewer)
            ? `${sync.ok} file(s) ready (${sync.downloaded} downloaded, ${sync.skipped || 0} already local` +
              (sync.keptNewer ? `, ${sync.keptNewer} kept newer local` : "") +
              `).`
            : `${sync.ok} file(s) downloaded to the local workspace.`;
        showOk(note);
      }
      // Paint before reload — Creo often collapses the browser on open and may
      // ignore form navigation while a folder view is showing.
      applyCheckedOutOnRows(syncedIds);
      const remaining = Math.max(
        0,
        Number(checkoutProductBtn?.dataset.checkoutable || 0) - syncedIds.length
      );
      setCheckoutableCount(remaining);
      reloadPage({ keepBusy: true });
      return true;
    }

    async function checkoutSelected() {
      const ids = selectedRows().filter((row) => row.dataset.canCheckout === "1").flatMap(rowObjectIds);
      const fallback = selectedIds();
      const objectIds = [...new Set((ids.length ? ids : fallback).filter(Boolean))];
      await runCheckoutObjects(objectIds);
    }

    async function checkoutProduct() {
      const productId =
        checkoutProductBtn?.dataset.product ||
        openWorkspaceBtn?.dataset.product ||
        currentProductId() ||
        "";
      if (!productId) {
        showError($("#toolbar-error"), "Select a product first.");
        return;
      }
      showError($("#toolbar-error"), "");
      const listed = await withBusy("Listing product files…", async () => {
        const response = await fetch(`/api/products/${encodeURIComponent(productId)}/objects`);
        if (!response.ok) {
          showError($("#toolbar-error"), await readError(response));
          return null;
        }
        return response.json();
      });
      if (!listed) return;
      const objectIds = (Array.isArray(listed) ? listed : [])
        .filter((item) => item && item.can_checkout && item.uuid)
        .map((item) => String(item.uuid));
      if (!objectIds.length) {
        showError($("#toolbar-error"), "No files available to check out in this product.");
        setCheckoutableCount(0);
        return;
      }
      await runCheckoutObjects(objectIds);
    }

    async function undoCheckout() {
      const ids = selectedRows().filter((row) => row.dataset.owned === "1").flatMap(rowObjectIds);
      const fallback = selectedIds();
      const objectIds = [...new Set((ids.length ? ids : fallback).filter(Boolean))];
      if (!objectIds.length) return;
      const undoGate = await assertProductAllows(currentProductId(), "checkout");
      if (!undoGate.ok) return;
      const count = objectIds.length;
      const slowNote =
        count > BULK_SLOW_WARN_THRESHOLD
          ? "\n\nThis can take several minutes. Keep this window open until it finishes."
          : "";
      const confirmMsg =
        count === 1
          ? "Undo checkout of this file?\n\nYour lock is released. Unsaved vault changes for this file may be discarded. Local workspace files are kept."
          : `Undo checkout of ${count} files?\n\nYour locks are released. Unsaved vault changes for these files may be discarded. Local workspace files are kept.${slowNote}`;
      if (!window.confirm(confirmMsg)) return;
      showError($("#toolbar-error"), "");
      if (count === 1 && !selectedRows().length) {
        const result = await postAction(
          `/api/objects/${objectIds[0]}/undo-checkout`,
          undefined,
          "POST",
          "Cancelling checkout…"
        );
        if (result) {
          rememberWatchView();
          applyUndoCheckoutOnRows(objectIds);
          reloadPage({ keepBusy: true });
        }
        return;
      }
      const UNDO_CHUNK = 50;
      const undoResult = await withBusy(`Cancelling checkout… 0 of ${count}`, async () => {
        const merged = { ok: [], failed: [] };
        for (let start = 0; start < objectIds.length; start += UNDO_CHUNK) {
          const chunk = objectIds.slice(start, start + UNDO_CHUNK);
          setBusyMessage(`Cancelling checkout… ${Math.min(start + chunk.length, count)} of ${count}`);
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
      });
      if (!undoResult) return;
      const warning = formatBatch(undoResult);
      if (warning) showError($("#toolbar-error"), warning);
      if (undoResult.ok?.length) {
        const undone = undoResult.ok.map((item) => item.uuid).filter(Boolean);
        applyUndoCheckoutOnRows(undone.length ? undone : objectIds);
        reloadPage({ keepBusy: true });
      }
    }

    async function forceUndoCheckout() {
      const ids = selectedRows()
        .filter((row) => row.dataset.checkedOut === "1" && row.dataset.owned !== "1")
        .flatMap(rowObjectIds);
      const detailId = forceUndoBtn?.dataset.uuid;
      const objectIds = [...new Set((ids.length ? ids : detailId ? [detailId] : []).filter(Boolean))];
      if (!objectIds.length) return;
      const forceGate = await assertProductAllows(currentProductId(), "checkout");
      if (!forceGate.ok) return;
      const count = objectIds.length;
      const slowNote =
        count > BULK_SLOW_WARN_THRESHOLD
          ? "\n\nThis can take several minutes. Keep this window open until it finishes."
          : "";
      const confirmMsg =
        count === 1
          ? "Force Undo Checkout for this file?\n\nThe other user’s checkout lock is released. No new version is recorded. Unsaved vault changes for this file may be discarded."
          : `Force Undo Checkout for ${count} files?\n\nOther users’ checkout locks are released. No new version is recorded. Unsaved vault changes may be discarded.${slowNote}`;
      if (!window.confirm(confirmMsg)) return;
      showError($("#toolbar-error"), "");
      if (count === 1) {
        const result = await postAction(
          `/api/objects/${objectIds[0]}/force-undo-checkout`,
          undefined,
          "POST",
          "Force undoing checkout…"
        );
        if (result) {
          rememberWatchView();
          applyUndoCheckoutOnRows(objectIds);
          reloadPage({ keepBusy: true });
        }
        return;
      }
      const FORCE_CHUNK = 50;
      const forceResult = await withBusy(`Force undoing checkout… 0 of ${count}`, async () => {
        const merged = { ok: [], failed: [] };
        for (let start = 0; start < objectIds.length; start += FORCE_CHUNK) {
          const chunk = objectIds.slice(start, start + FORCE_CHUNK);
          setBusyMessage(
            `Force undoing checkout… ${Math.min(start + chunk.length, count)} of ${count}`
          );
          const part = await postAction(
            "/api/objects/batch/force-undo-checkout",
            { object_ids: chunk },
            "POST",
            ""
          );
          if (!part) return null;
          if (Array.isArray(part.ok)) merged.ok.push(...part.ok);
          if (Array.isArray(part.failed)) merged.failed.push(...part.failed);
        }
        return merged;
      });
      if (!forceResult) return;
      const warning = formatBatch(forceResult);
      if (warning) showError($("#toolbar-error"), warning);
      if (forceResult.ok?.length) {
        const undone = forceResult.ok.map((item) => item.uuid).filter(Boolean);
        applyUndoCheckoutOnRows(undone.length ? undone : objectIds);
        reloadPage({ keepBusy: true });
      }
    }

    mod.runCheckoutObjects = runCheckoutObjects;
    mod.checkoutSelected = checkoutSelected;
    mod.checkoutProduct = checkoutProduct;
    mod.undoCheckout = undoCheckout;
    mod.forceUndoCheckout = forceUndoCheckout;
  },
};
