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
    /** Files and Structure are two views of one dialog; the visible table gets all the height. */
    function setBaselineView(view) {
      const wanted =
        view === "structure" && !$("#baseline-structure-tab")?.hidden
          ? "structure"
          : view === "compare"
            ? "compare"
            : "files";
      const panes = {
        files: $("#baseline-members-table-wrap"),
        structure: $("#baseline-structure-wrap"),
        compare: $("#baseline-compare-wrap"),
      };
      for (const [name, pane] of Object.entries(panes)) if (pane) pane.hidden = name !== wanted;
      $("#baseline-files-tab")?.classList.toggle("is-active", wanted === "files");
      $("#baseline-structure-tab")?.classList.toggle("is-active", wanted === "structure");
      $("#baseline-compare-tab")?.classList.toggle("is-active", wanted === "compare");
      if (wanted === "compare") void loadCompareChoices();
    }

    let compareResult = null;
    let compareChoicesFor = "";

    /** The "compare with" list: the product as it is now, then every other baseline. */
    async function loadCompareChoices() {
      const select = $("#baseline-compare-to");
      if (!(select instanceof HTMLSelectElement) || !openBaselineUuid) return;
      if (compareChoicesFor === openBaselineUuid && select.options.length) return;
      compareChoicesFor = openBaselineUuid;
      select.innerHTML = '<option value="current">Current product</option>';
      const pid = productId();
      try {
        const response = pid ? await fetch(`/api/products/${encodeURIComponent(pid)}/baselines`) : null;
        const rows = response && response.ok ? await response.json() : [];
        for (const row of Array.isArray(rows) ? rows : []) {
          if (row.uuid === openBaselineUuid) continue;
          const option = document.createElement("option");
          option.value = row.uuid;
          option.textContent = `${row.name} (${titleCase(row.baseline_type)})`;
          select.appendChild(option);
        }
      } catch {
        /* the product option still works */
      }
      await runCompare();
    }

    const CHANGE_LABEL = {
      VERSION_CHANGED: "Changed",
      ADDED: "Added",
      REMOVED: "Removed",
      UNCHANGED: "Same",
    };

    function renderCompare() {
      const body = $("#baseline-compare-table tbody");
      const summary = $("#baseline-compare-summary");
      const head = $("#baseline-compare-with");
      if (!body || !compareResult) return;
      const showSame = Boolean($("#baseline-compare-unchanged")?.checked);
      const s = compareResult.summary;
      if (head) head.textContent = compareResult.to_baseline.name;
      if (summary) {
        summary.textContent =
          `Changed ${s.changed} · Added ${s.added} · Removed ${s.removed} · Unchanged ${s.unchanged}` +
          ` — ${compareResult.from_baseline.name} → ${compareResult.to_baseline.name}`;
      }
      const rows = compareResult.items.filter((r) => showSame || r.status !== "UNCHANGED");
      body.innerHTML = rows.length
        ? rows
            .map(
              (r) => `<tr class="compare-${esc(r.status.toLowerCase())}">
              <td class="baseline-name-cell">${esc(r.filename)}</td>
              <td>${esc(CHANGE_LABEL[r.status] || r.status)}</td>
              <td>${esc(r.from_version || "—")}</td>
              <td>${esc(r.to_version || "—")}</td>
            </tr>`
            )
            .join("")
        : '<tr class="empty-row"><td colspan="4">No differences.</td></tr>';
    }

    async function runCompare() {
      const select = $("#baseline-compare-to");
      const body = $("#baseline-compare-table tbody");
      if (!(select instanceof HTMLSelectElement) || !openBaselineUuid) return;
      showError($("#baseline-members-error"), "");
      if (body) body.innerHTML = '<tr class="empty-row"><td colspan="4">Comparing…</td></tr>';
      try {
        const response = await fetch(
          `/api/baselines/${encodeURIComponent(openBaselineUuid)}/compare?to=${encodeURIComponent(
            select.value || "current"
          )}`
        );
        if (!response.ok) throw new Error(await readError(response));
        compareResult = await response.json();
        renderCompare();
      } catch (err) {
        if (body) body.innerHTML = "";
        showError($("#baseline-members-error"), `Could not compare: ${err?.message || "error"}`);
      }
    }

    /** The captured structure: each parent version, the exact child version it uses, or "Unresolved". */
    function renderStructure(edges) {
      const tab = $("#baseline-structure-tab");
      const body = $("#baseline-structure-table tbody");
      const list = Array.isArray(edges) ? edges : [];
      if (tab) {
        tab.hidden = !list.length;
        tab.textContent = `Structure · ${list.length}`;
      }
      if (!body) return;
      body.innerHTML = list
        .map((e) => {
          const uses = e.resolved
            ? `${esc(e.child_filename)} <span class="muted">${esc(e.child_display_version || "")}</span>`
            : `${esc(e.child_filename)} <span class="baseline-unresolved">Unresolved</span>`;
          const kind = String(e.dependency_type || "").replace(/_/g, " ").toLowerCase();
          return `<tr${e.resolved ? "" : ' class="is-unresolved"'}>
            <td class="baseline-name-cell">${esc(e.parent_filename)} <span class="muted">${esc(
              e.parent_display_version
            )}</span></td>
            <td class="baseline-name-cell">${uses}</td>
            <td>${esc(kind || "—")}${e.required ? "" : ' <span class="muted small">(optional)</span>'}</td>
            <td>${esc(e.quantity)}</td>
            <td>${e.resolved ? "Yes" : "No"}</td>
          </tr>`;
        })
        .join("");
    }

    let openBaselineUuid = "";

    /** The file name links to the EXACT captured version (by its version uuid), never to "latest". */
    function versionLink(info, m) {
      if (!info?.product_uuid || !m.object_uuid || !m.version_uuid) return esc(m.filename);
      const href = `/products/${encodeURIComponent(info.product_uuid)}/objects/${encodeURIComponent(
        m.object_uuid
      )}/versions/${encodeURIComponent(m.version_uuid)}`;
      return `<a class="baseline-version-link" href="${href}" title="Open exactly ${esc(
        m.display_version
      )}, even if the file has moved on">${esc(m.filename)}</a>`;
    }

    /** The optional Git tag: a note when it is fine, a warning when it moved, a retry when it failed. */
    function renderTag(info, check) {
      const line = $("#baseline-tag-line");
      const text = $("#baseline-tag-text");
      const retry = $("#baseline-tag-retry");
      const warning = $("#baseline-tag-warning");
      if (warning) {
        warning.hidden = !check?.warning;
        warning.textContent = check?.warning || "";
      }
      const name = info?.git_tag_name;
      if (line) line.hidden = !name;
      if (!name || !text) return;
      const state = check?.state;
      if (state === "OK") text.textContent = `Git tag ${name} points at this commit.`;
      else if (state === "MOVED" || state === "MISSING") text.textContent = `Git tag ${name}`;
      else {
        text.textContent =
          `Git tag ${name} was not created` + (info.git_tag_error ? `: ${info.git_tag_error}` : ".") +
          " The baseline itself is complete.";
      }
      // Only someone who may create baselines is offered the retry.
      if (retry) retry.hidden = !(state === "NOT_CREATED" && $("#create-baseline-btn"));
    }

    async function openBaselineMembers(baselineUuid) {
      openBaselineUuid = baselineUuid;
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
      compareChoicesFor = "";
      compareResult = null;
      setBaselineView("files");
      renderTag(null, null);
      const staleDesc = $("#baseline-members-desc");
      if (staleDesc) staleDesc.hidden = true;
      const staleCommit = $("#baseline-commit-line");
      if (staleCommit) staleCommit.hidden = true;
      if (!dialog.open) dialog.showModal();
      // Start at the top: without this the browser focuses a scrollable table and scrolls to it.
      dialog.scrollTop = 0;
      title?.focus({ preventScroll: true });
      try {
        const [baselineResp, membersResp, structureResp, checkResp] = await Promise.all([
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/members`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/dependencies`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/git-check`),
        ]);
        if (!membersResp.ok) throw new Error(await readError(membersResp));
        const members = await membersResp.json();
        let info = null;
        if (baselineResp.ok) info = await baselineResp.json();
        const descLine = $("#baseline-members-desc");
        if (descLine) {
          descLine.hidden = !info?.description;
          descLine.textContent = info?.description || "";
        }
        const commitLine = $("#baseline-commit-line");
        const commitCode = $("#baseline-commit-sha");
        if (commitLine && commitCode) {
          const sha = String(info?.git_commit_sha || "");
          commitLine.hidden = !sha;
          commitCode.textContent = sha ? sha.slice(0, 12) : "";
          commitCode.title = sha ? `Full commit SHA: ${sha}` : "Full commit SHA";
        }
        if (info && meta) {
          meta.textContent =
            `${titleCase(info.status)} · ${titleCase(info.baseline_type)} · ` +
            (info.product_name ? `${info.product_name} · ` : "") +
            `${info.member_count} member${info.member_count === 1 ? "" : "s"} · ` +
            `${info.dependency_count || 0} link${info.dependency_count === 1 ? "" : "s"}` +
            (info.unresolved_dependency_count
              ? ` (${info.unresolved_dependency_count} unresolved)`
              : "") +
            " · " +
            `created ${formatWhen(info.created_at)} by ${info.created_by}`;
        }
        renderStructure(structureResp.ok ? await structureResp.json() : []);
        renderTag(info, checkResp.ok ? await checkResp.json() : null);
        const noStructure = $("#baseline-no-structure");
        if (noStructure) noStructure.hidden = !(info && info.structure_indexed === false);
        if (!body) return;
        body.innerHTML = (Array.isArray(members) ? members : [])
          .map((m) => {
            const newer = m.status === "OUT_OF_DATE";
            const now = newer
              ? `Newer: ${esc(m.current_display_version || "—")}`
              : "Same version";
            return `<tr data-version="${esc(m.version_uuid)}" data-object="${esc(m.object_uuid)}">
              <td class="baseline-name-cell">${versionLink(info, m)}${
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
      const structureBox = $("#baseline-structure-confirm");
      if (structureBox) structureBox.hidden = true;
      const acceptStructure = $("#baseline-accept-structure");
      if (acceptStructure) acceptStructure.checked = false;
      const releaseBox = $("#baseline-release");
      if (releaseBox) releaseBox.checked = false;
      const tagOn = $("#baseline-tag-on");
      const tagField = $("#baseline-tag-field");
      const tagInput = $("#baseline-tag");
      if (tagOn) tagOn.checked = false;
      if (tagField) tagField.hidden = true;
      if (tagInput) tagInput.value = "";
      tagEdited = false;
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
          const acceptBox = $("#baseline-accept-structure");
          let response;
          try {
            response = await fetch(`/api/products/${encodeURIComponent(pid)}/baselines`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                name: text,
                description: String(description?.value || "").trim() || null,
                operation_id: operationId,
                accept_missing_structure: Boolean(acceptBox?.checked),
                baseline_type: $("#baseline-release")?.checked ? "RELEASE" : "MANUAL",
                git_tag: $("#baseline-tag-on")?.checked
                  ? String($("#baseline-tag")?.value || "").trim() || null
                  : null,
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
            let code = "";
            try {
              code = (await response.clone().json())?.error?.code || "";
            } catch {
              code = "";
            }
            showError($("#baseline-error"), await readError(response));
            if (code === "BASELINE_STRUCTURE_NOT_INDEXED") {
              // Nothing was created. Offer the explicit choice instead of a silent empty structure.
              const box = $("#baseline-structure-confirm");
              if (box) box.hidden = false;
            }
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
        const tagNote =
          created.git_tag_status === "FAILED"
            ? ` The Git tag “${created.git_tag_name}” could not be created (${
                created.git_tag_error || "see the log"
              }); the baseline is complete — open it to retry the tag.`
            : "";
        showOk(
          `Baseline “${created.name}” created: ${created.member_count} file${
            created.member_count === 1 ? "" : "s"
          } captured at their exact current versions.${tagNote}`
        );
        await loadBaselinesTab();
      }
    }

    /** baseline/<name> as a safe tag: lowercase, letters digits . _ - only. */
    function suggestTag(name) {
      const slug = String(name || "")
        .toLowerCase()
        .replace(/[^a-z0-9._-]+/g, "-")
        .replace(/^[-.]+|[-.]+$/g, "");
      return slug ? `baseline/${slug}` : "baseline/";
    }

    // The suggested tag follows the baseline name until the user types their own tag.
    let tagEdited = false;

    $("#baseline-tag-on")?.addEventListener("change", (event) => {
      const on = event.currentTarget instanceof HTMLInputElement && event.currentTarget.checked;
      const field = $("#baseline-tag-field");
      const input = $("#baseline-tag");
      if (field) field.hidden = !on;
      if (on && input && (!input.value || !tagEdited)) {
        input.value = suggestTag($("#baseline-name")?.value);
        tagEdited = false;
      }
      if (on) input?.focus();
    });

    $("#baseline-tag")?.addEventListener("input", (event) => {
      const input = event.currentTarget;
      // Clearing the box hands control back to the suggestion.
      tagEdited = input instanceof HTMLInputElement && input.value.trim() !== "";
    });

    $("#baseline-name")?.addEventListener("input", () => {
      const input = $("#baseline-tag");
      if (!$("#baseline-tag-on")?.checked || tagEdited || !input) return;
      input.value = suggestTag($("#baseline-name")?.value);
    });

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

    $("#baseline-tag-retry")?.addEventListener("click", async (event) => {
      event.preventDefault();
      const uuid = openBaselineUuid;
      if (!uuid) return;
      const button = event.currentTarget;
      if (button instanceof HTMLButtonElement) button.disabled = true;
      try {
        const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}/git-tag`, {
          method: "POST",
        });
        if (!response.ok) showError($("#baseline-members-error"), await readError(response));
      } catch {
        showError($("#baseline-members-error"), "The server did not answer. Try the tag again.");
      }
      if (button instanceof HTMLButtonElement) button.disabled = false;
      await openBaselineMembers(uuid);
    });

    $("#baseline-compare-to")?.addEventListener("change", () => void runCompare());
    $("#baseline-compare-unchanged")?.addEventListener("change", () => renderCompare());

    $("#baseline-members-dialog")?.addEventListener("click", (event) => {
      const button = event.target instanceof Element ? event.target.closest("[data-baseline-view]") : null;
      if (!button) return;
      event.preventDefault();
      setBaselineView(button.getAttribute("data-baseline-view") || "files");
    });

    $("#create-baseline-btn")?.addEventListener("click", () => {
      void openCreateBaselineDialog();
    });
  },
};
