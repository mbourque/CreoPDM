window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.baselines = {
  /**
   * Baselines tab on the Files page: list the product's baselines and create a new one.
   * Loaded lazily (ensureModule("baselines")) the first time the Baselines tab is opened.
   * A baseline is an exact, frozen snapshot: the server resolves the configuration itself, the
   * client only sends a name, a description and one retry id per dialog open.
   */
  init(shell) {
    const mod = window.__creopdmModules.baselines;
    const $ = shell.$;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const readError = shell.readError;
    const currentProductId = shell.currentProductId;

    function esc(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    function formatWhen(value) {
      if (!value) return "—";
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return "—";
      const pad = (n) => String(n).padStart(2, "0");
      return (
        `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
        `${pad(date.getHours())}:${pad(date.getMinutes())}`
      );
    }

    function titleCase(value) {
      const text = String(value || "").toLowerCase();
      return text ? text.charAt(0).toUpperCase() + text.slice(1) : "—";
    }

    function statusHint(status) {
      return String(status || "").toUpperCase() === "FINALIZED"
        ? "Finalized: what this baseline captured can never change. Create a new baseline for a different configuration."
        : "";
    }

    /** IN_WORK → "In Work", RELEASED → "Released": the same wording as the Files list. */
    function stateLabel(value) {
      const words = String(value || "")
        .toLowerCase()
        .split(/[_\s]+/)
        .filter(Boolean);
      if (!words.length) return "—";
      return words.map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(" ");
    }

    function productId() {
      return $("#panel-baselines")?.dataset.product || currentProductId() || "";
    }

    /** Tab label and the header pill follow the number of baselines. */
    function paintCounts(count) {
      const n = Number(count) || 0;
      const tab = $("#baselines-tab");
      if (tab) tab.textContent = n ? `Baselines · ${n}` : "Baselines";
      const pill = $("#baselines-pill-item");
      if (pill) pill.hidden = n === 0;
      const strong = $("#baselines-pill-count");
      if (strong) strong.textContent = String(n);
    }

    function renderRows(items) {
      const body = $("#baselines-table tbody");
      if (!body) return;
      if (!items.length) {
        body.innerHTML =
          '<tr class="empty-row"><td colspan="6">No baselines yet. Create one to freeze this product’s current configuration.</td></tr>';
        return;
      }
      body.innerHTML = items
        .map((item) => {
          const description = String(item.description || "").trim();
          return `<tr class="baseline-row" data-baseline="${esc(item.uuid)}">
            <td class="baseline-name-cell"><button type="button" class="baseline-open" data-open-baseline="${esc(
              item.uuid
            )}" title="Show the exact versions in this baseline">${esc(item.name)}</button>${
              description ? `<div class="muted small">${esc(description)}</div>` : ""
            }</td>
            <td>${esc(titleCase(item.baseline_type))}</td>
            <td title="${esc(statusHint(item.status))}">${esc(titleCase(item.status))}</td>
            <td>${esc(item.member_count)}</td>
            <td title="${esc(item.created_at || "")}">${esc(formatWhen(item.created_at))}</td>
            <td>${esc(item.created_by)}</td>
          </tr>`;
        })
        .join("");
    }

    async function loadBaselinesTab() {
      const pid = productId();
      const body = $("#baselines-table tbody");
      if (!pid || !body) return;
      try {
        const response = await fetch(`/api/products/${encodeURIComponent(pid)}/baselines`);
        if (!response.ok) throw new Error(await readError(response));
        const items = await response.json();
        const list = Array.isArray(items) ? items : [];
        renderRows(list);
        paintCounts(list.length);
      } catch (err) {
        body.innerHTML = `<tr class="empty-row"><td colspan="6">Could not load baselines (${esc(
          err?.message || "error"
        )}).</td></tr>`;
      }
    }

    /** The exact versions captured, read through the stored version ids (not the current ones). */
    async function openBaselineMembers(baselineUuid) {
      const dialog = $("#baseline-members-dialog");
      if (!(dialog instanceof HTMLDialogElement)) return;
      const body = $("#baseline-members-table tbody");
      const title = $("#baseline-members-title");
      const meta = $("#baseline-members-meta");
      showError($("#baseline-members-error"), "");
      if (body) body.innerHTML = '<tr class="empty-row"><td colspan="5">Loading…</td></tr>';
      const row = $(`#baselines-table tr[data-baseline="${CSS.escape(baselineUuid)}"]`);
      if (title) title.textContent = row?.querySelector(".baseline-open")?.textContent || "Baseline";
      if (meta) meta.textContent = "";
      if (!dialog.open) dialog.showModal();
      try {
        const [baselineResp, membersResp] = await Promise.all([
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/members`),
        ]);
        if (!membersResp.ok) throw new Error(await readError(membersResp));
        const members = await membersResp.json();
        if (baselineResp.ok && meta) {
          const info = await baselineResp.json();
          meta.textContent =
            `${titleCase(info.status)} · ${titleCase(info.baseline_type)} · ` +
            `${info.member_count} member${info.member_count === 1 ? "" : "s"} · ` +
            `created ${formatWhen(info.created_at)} by ${info.created_by}`;
        }
        if (!body) return;
        body.innerHTML = (Array.isArray(members) ? members : [])
          .map((m) => {
            const newer = m.status === "OUT_OF_DATE";
            const now = newer
              ? `Newer: ${esc(m.current_display_version || "—")}`
              : "Same version";
            return `<tr data-version="${esc(m.version_uuid)}" data-object="${esc(m.object_uuid)}">
              <td class="baseline-name-cell">${esc(m.filename)}${
                m.relative_path && m.relative_path !== m.filename
                  ? `<div class="muted small">${esc(m.relative_path)}</div>`
                  : ""
              }</td>
              <td>${esc(m.display_version)}</td>
              <td>${esc(stateLabel(m.lifecycle_state))}</td>
              <td>${esc(String(m.object_type || "").replace(/^CREO_/, "").toLowerCase() || "—")}</td>
              <td class="${newer ? "is-newer" : ""}">${now}</td>
            </tr>`;
          })
          .join("");
      } catch (err) {
        if (body) body.innerHTML = "";
        showError($("#baseline-members-error"), `Could not load the baseline: ${err?.message || "error"}`);
      }
    }

    function newOperationId() {
      return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
        ? crypto.randomUUID()
        : `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }

    async function openCreateBaselineDialog() {
      const dialog = $("#baseline-dialog");
      const form = $("#baseline-form");
      if (!(dialog instanceof HTMLDialogElement) || !form) return;
      const pid = productId();
      if (!pid) return;
      const name = $("#baseline-name");
      const description = $("#baseline-description");
      const confirm = $("#baseline-confirm");
      const cancel = $("#baseline-cancel");
      if (name) name.value = "";
      if (description) description.value = "";
      if (confirm) confirm.disabled = false;
      showError($("#baseline-error"), "");
      const files = $("#metric-filters")?.dataset.productObjects;
      const count = $("#baseline-file-count");
      if (count) {
        count.textContent =
          files != null && files !== "" ? `${files} file${Number(files) === 1 ? "" : "s"}` : "—";
      }
      // One id per dialog open: pressing Create again after a lost answer returns the same
      // baseline instead of an error or a second copy.
      const operationId = newOperationId();
      let created = null;
      await new Promise((resolve) => {
        const finish = () => {
          form.removeEventListener("submit", onSubmit);
          cancel?.removeEventListener("click", onCancel);
          dialog.removeEventListener("close", onClose);
          if (dialog.open) dialog.close();
          resolve();
        };
        const onSubmit = async (event) => {
          event.preventDefault();
          const text = String(name?.value || "").trim();
          if (!text) {
            showError($("#baseline-error"), "Enter a name for the baseline.");
            name?.focus();
            return;
          }
          showError($("#baseline-error"), "");
          if (confirm) confirm.disabled = true;
          let response;
          try {
            response = await fetch(`/api/products/${encodeURIComponent(pid)}/baselines`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                name: text,
                description: String(description?.value || "").trim() || null,
                operation_id: operationId,
              }),
            });
          } catch {
            showError(
              $("#baseline-error"),
              "The server did not answer. Press Create again — it will not make a second baseline."
            );
            if (confirm) confirm.disabled = false;
            return;
          }
          if (!response.ok) {
            showError($("#baseline-error"), await readError(response));
            if (confirm) confirm.disabled = false;
            return;
          }
          created = await response.json();
          finish();
        };
        const onCancel = () => finish();
        const onClose = () => finish();
        form.addEventListener("submit", onSubmit);
        cancel?.addEventListener("click", onCancel);
        dialog.addEventListener("close", onClose);
        dialog.showModal();
        name?.focus();
      });
      if (created) {
        showOk(
          `Baseline “${created.name}” created: ${created.member_count} file${
            created.member_count === 1 ? "" : "s"
          } captured at their exact current versions.`
        );
        await loadBaselinesTab();
      }
    }

    mod.openBaselineMembers = openBaselineMembers;
    mod.loadBaselinesTab = loadBaselinesTab;
    mod.openCreateBaselineDialog = openCreateBaselineDialog;

    $("#baselines-table")?.addEventListener("click", (event) => {
      // A button, not <a href="#">: the page-wide link handler soft-navigates every anchor,
      // and "#" is this very page, so an anchor here reloaded the Files tab.
      const link = event.target instanceof Element ? event.target.closest("[data-open-baseline]") : null;
      if (!link) return;
      event.preventDefault();
      void openBaselineMembers(link.getAttribute("data-open-baseline") || "");
    });

    $("#create-baseline-btn")?.addEventListener("click", () => {
      void openCreateBaselineDialog();
    });
  },
};
