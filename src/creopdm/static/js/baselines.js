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
          '<tr class="empty-row"><td colspan="7">No baselines yet. Create one to freeze this product’s current configuration.</td></tr>';
        return;
      }
      body.innerHTML = items
        .map((item) => {
          const description = String(item.description || "").trim();
          return `<tr class="baseline-row${item.status === "ARCHIVED" ? " is-archived" : ""}" data-baseline="${esc(item.uuid)}">
            <td class="baseline-name-cell"><button type="button" class="baseline-open" data-open-baseline="${esc(
              item.uuid
            )}" title="Show the exact versions in this baseline">${esc(item.name)}</button>${
              description ? `<div class="muted small">${esc(description)}</div>` : ""
            }</td>
            <td>${esc(titleCase(item.baseline_type))}${
              item.release_label ? ` <span class="baseline-release-badge">${esc(item.release_label)}</span>` : ""
            }</td>
            <td title="${esc(statusHint(item.status))}">${esc(titleCase(item.status))}</td>
            <td>${esc(item.member_count)}</td>
            <td title="${esc(item.created_at || "")}">${esc(formatWhen(item.created_at))}</td>
            <td>${esc(item.created_by)}</td>
            <td class="baseline-details-cell"><button type="button" class="btn baseline-details-btn" data-baseline-details="${esc(
              item.uuid
            )}" title="Structure, Git, integrity, compare and download for this baseline">Details…</button></td>
          </tr>`;
        })
        .join("");
    }

    async function loadBaselinesTab() {
      // An open baseline stays open (also through the "N Baselines" pill, and after Details or
      // Back brought us to a fresh page): only the breadcrumb returns to the list.
      if (!browseUuid) {
        const remembered = rememberedBaseline();
        if (remembered) void browseBaseline(remembered);
      }
      const pid = productId();
      const body = $("#baselines-table tbody");
      if (!pid || !body) return;
      try {
        const showArchived = Boolean($("#baselines-show-archived")?.checked);
        const response = await fetch(
          `/api/products/${encodeURIComponent(pid)}/baselines${showArchived ? "?include_archived=true" : ""}`
        );
        if (!response.ok) throw new Error(await readError(response));
        const items = await response.json();
        const list = Array.isArray(items) ? items : [];
        baselineList = list;
        renderRows(sortedRows("baselines", list));
        // The tab and the pill count what is in everyday use, not archived baselines.
        paintCounts(list.filter((item) => item.status !== "ARCHIVED").length);
      } catch (err) {
        body.innerHTML = `<tr class="empty-row"><td colspan="7">Could not load baselines (${esc(
          err?.message || "error"
        )}).</td></tr>`;
      }
    }

    // ---- The files of one baseline, shown in the Baselines tab itself (read-only) ----------
    // The rows are Files-page rows (".object-row" with the same data-* attributes), so the
    // page's own selection, pills (counts, filter, select) and hover preview work on them.
    let browseUuid = "";
    let browseData = [];
    let browseInfo = null;
    let pendingOpen = 0;

    function browseVisible() {
      const pane = $("#baseline-browse");
      return Boolean(pane && !pane.hidden);
    }

    function baselinesTabActive() {
      return document.querySelector(".tabs .tab.is-active")?.getAttribute("data-tab") === "baselines";
    }

    function showBrowse(on) {
      for (const id of ["baselines-head", "baselines-table-wrap"]) {
        const el = $(`#${id}`);
        if (el) el.hidden = on;
      }
      const pane = $("#baseline-browse");
      if (pane) pane.hidden = !on;
    }

    /** Keep the address in step so a refresh, Back or a shared link opens the same baseline. */
    function setBaselineParam(uuid) {
      try {
        const url = new URL(window.location.href);
        if (uuid) {
          url.searchParams.set("tab", "baselines");
          url.searchParams.set("baseline", uuid);
        } else {
          url.searchParams.delete("baseline");
          if (url.searchParams.get("tab") === "baselines") url.searchParams.delete("tab");
        }
        window.history.replaceState(window.history.state, "", url);
      } catch {
        /* the address is a convenience only */
      }
    }

    /**
     * What the page shows follows the tab: on the Baselines tab with a baseline open the Files
     * toolbar gives way to the one button that applies (Details), on other tabs nothing of
     * this view leaks out. The open baseline is remembered while another tab is shown.
     */
    function syncBrowseChrome() {
      const on = Boolean(browseUuid) && baselinesTabActive();
      showBrowse(on);
      document.body.classList.toggle("is-baseline-browse", on);
      setBaselineParam(on ? browseUuid : "");
      syncFooterDetails();
    }

    function selectedBrowseRows() {
      return [...document.querySelectorAll("#baseline-browse-table tbody tr.object-row.is-selected")].filter(
        (row) => !row.hidden && row.style.display !== "none"
      );
    }

    /** The footer shows Details only while exactly one file is selected. */
    function syncFooterDetails() {
      const button = $("#baseline-browse-file-details");
      if (!button) return;
      button.hidden = !(browseVisible() && selectedBrowseRows().length === 1);
    }

    /** Back to the list: only the breadcrumb does this. */
    const REMEMBER_KEY = "creopdm.openBaseline";

    function rememberBaseline(uuid) {
      try {
        const all = JSON.parse(window.sessionStorage.getItem(REMEMBER_KEY) || "{}");
        if (uuid) all[productId()] = uuid;
        else delete all[productId()];
        window.sessionStorage.setItem(REMEMBER_KEY, JSON.stringify(all));
      } catch {
        /* private mode / blocked storage: the address still carries it */
      }
    }

    function rememberedBaseline() {
      try {
        const all = JSON.parse(window.sessionStorage.getItem(REMEMBER_KEY) || "{}");
        return String(all[productId()] || "");
      } catch {
        return "";
      }
    }

    function leaveBrowse() {
      rememberBaseline("");
      browseUuid = "";
      browseData = [];
      browseInfo = null;
      syncBrowseChrome();
      shell.refreshTabMetrics?.();
    }

    function topLevelAssemblyVersions(members, edges) {
      const typeOf = new Map(members.map((m) => [m.version_uuid, String(m.object_type || "").toUpperCase()]));
      const used = new Set();
      for (const edge of edges) {
        // Drawings referring to a model do not make it a sub-assembly.
        if (typeOf.get(edge.parent_version_uuid) === "CREO_ASSEMBLY" && edge.child_version_uuid) {
          used.add(edge.child_version_uuid);
        }
      }
      return new Set(
        members
          .filter((m) => String(m.object_type || "").toUpperCase() === "CREO_ASSEMBLY" && !used.has(m.version_uuid))
          .map((m) => m.version_uuid)
      );
    }

    function fileExtension(name) {
      const match = /\.([a-z0-9_+]+)(?:\.\d+)?$/i.exec(String(name || ""));
      return match ? match[1].toLowerCase() : "";
    }

    function paintBrowse() {
      const body = $("#baseline-browse-table tbody");
      if (!body) return;
      if (!browseData.length) {
        body.innerHTML = '<tr class="empty-row"><td colspan="5">This baseline has no files.</td></tr>';
        shell.refreshTabMetrics?.();
        syncFooterDetails();
        return;
      }
      const tops = topLevelAssemblyVersions(browseData, browseEdges);
      body.innerHTML = sortedRows("browse", browseData)
        .map((m) => {
          const newer = m.status === "OUT_OF_DATE";
          const now = newer ? `Newer: ${esc(m.current_display_version || "—")}` : "Same version";
          const ext = fileExtension(m.filename);
          const type = String(m.object_type || "").toUpperCase();
          const detail =
            browseInfo?.product_uuid && m.object_uuid && m.version_uuid
              ? `/products/${encodeURIComponent(browseInfo.product_uuid)}/objects/${encodeURIComponent(
                  m.object_uuid
                )}/versions/${encodeURIComponent(m.version_uuid)}?baseline=${encodeURIComponent(browseUuid)}`
              : "";
          const icon = shell.typeIconHtml ? shell.typeIconHtml({ objectType: type, extension: ext }) : "";
          return `<tr class="object-row baseline-file-row" data-uuid="${esc(m.object_uuid)}" data-version="${esc(
            m.version_uuid
          )}" data-filename="${esc(m.filename)}" data-object-type="${esc(type)}" data-extension="${esc(
            ext ? `.${ext}` : ""
          )}" data-content-hash="${esc(m.content_hash || "")}"${detail ? ` data-detail="${esc(detail)}"` : ""}${
            tops.has(m.version_uuid) ? ' data-top-level-assembly="1"' : ""
          }>
            <td class="baseline-name-cell"><span class="name-with-icon">${icon}<button type="button" class="baseline-file-open thumb-preview-target" data-filename="${esc(
              m.filename
            )}" data-extension="${esc(ext ? `.${ext}` : "")}" data-object-type="${esc(type)}" data-content-hash="${esc(
              m.content_hash || ""
            )}" title="Open exactly ${esc(m.display_version)} (double-click for its details)">${esc(
              m.filename
            )}</button></span>${
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
      shell.refreshTabMetrics?.();
      syncFooterDetails();
    }

    let browseEdges = [];

    /** Show the exact versions of one baseline in the tab (the list steps aside). */
    async function browseBaseline(baselineUuid) {
      if (!baselineUuid) return;
      browseUuid = baselineUuid;
      openBaselineUuid = baselineUuid;
      rememberBaseline(baselineUuid);
      browseData = [];
      browseEdges = [];
      browseInfo = null;
      resetSorts();
      syncBrowseChrome();
      showError($("#baseline-browse-error"), "");
      const title = $("#baseline-browse-title");
      const meta = $("#baseline-browse-meta");
      const row = $(`#baselines-table tr[data-baseline="${CSS.escape(baselineUuid)}"]`);
      if (title) title.textContent = row?.querySelector(".baseline-open")?.textContent || "Baseline";
      if (meta) meta.textContent = "Loading…";
      const body = $("#baseline-browse-table tbody");
      if (body) body.innerHTML = '<tr class="empty-row"><td colspan="5">Loading…</td></tr>';
      try {
        const [baselineResp, membersResp, edgesResp] = await Promise.all([
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/members`),
          fetch(`/api/baselines/${encodeURIComponent(baselineUuid)}/dependencies`),
        ]);
        if (browseUuid !== baselineUuid) return; // the user went elsewhere meanwhile
        if (!baselineResp.ok) throw new Error(await readError(baselineResp));
        if (!membersResp.ok) throw new Error(await readError(membersResp));
        browseInfo = await baselineResp.json();
        const members = await membersResp.json();
        browseData = Array.isArray(members) ? members : [];
        const edges = edgesResp.ok ? await edgesResp.json() : [];
        browseEdges = Array.isArray(edges) ? edges : [];
        if (title) title.textContent = browseInfo.name || "Baseline";
        if (meta) {
          meta.textContent =
            `Frozen snapshot, read-only · ${titleCase(browseInfo.status)} · ` +
            `${titleCase(browseInfo.baseline_type)}${browseInfo.release_label ? ` ${browseInfo.release_label}` : ""} · ` +
            `${browseInfo.member_count} file${browseInfo.member_count === 1 ? "" : "s"} · ` +
            `created ${formatWhen(browseInfo.created_at)} by ${browseInfo.created_by}` +
            (browseInfo.status === "ARCHIVED" ? " · Archived" : "");
        }
        paintBrowse();
      } catch (err) {
        if (browseUuid !== baselineUuid) return;
        // A baseline that is gone or not allowed: back to the list, with the reason.
        leaveBrowse();
        await loadBaselinesTab();
        const body = $("#baselines-table tbody");
        if (body && !body.querySelector(".empty-row")) {
          body.insertAdjacentHTML(
            "afterbegin",
            `<tr class="empty-row"><td colspan="7">That baseline could not be opened (${esc(
              err?.message || "error"
            )}).</td></tr>`
          );
        }
      }
    }

    /**
     * Open one file of the baseline the way Files opens a file: put the baseline's exact files on
     * this PC (read-only folder, skipped when it is already there and unchanged), then open the
     * file from that folder in the Creo session, or with Windows when this is not Creo's browser.
     */
    async function openBaselineFile(row) {
      const info = browseInfo;
      const member = browseData.find((m) => m.version_uuid === row?.dataset?.version);
      const errorEl = $("#baseline-browse-error");
      showError(errorEl, "");
      if (!info || !member) return;
      const agent = await shell.probeCreoAgent();
      if (!agent) {
        showError(
          errorEl,
          "Start creopdm-agent on this PC so the baseline's files can be downloaded before opening."
        );
        return;
      }
      let folder = "";
      try {
        await shell.withBusy("Preparing the baseline…", async () => {
          if (info.workspace_folder) {
            const check = await agentJson("/baseline-workspace/check", info, { folder: info.workspace_folder });
            const b = check.body || {};
            if (check.ok && b.installed && !(b.missing?.length || 0) && !(b.modified?.length || 0)) {
              folder = b.path || "";
            }
          }
          if (folder) return;
          const response = await fetch(`/api/baselines/${encodeURIComponent(info.uuid)}/workspace-manifest`);
          if (!response.ok) throw new Error(await readError(response));
          const manifest = await response.json();
          const result = await agentJson("/baseline-workspace", info, { manifest, overwrite: false });
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
        showError(errorEl, err?.message || "The baseline could not be put on this PC.");
        return;
      }
      if (!folder) {
        showError(errorEl, "The agent did not say where the baseline is.");
        return;
      }
      const fullPath = shell.joinLocalWorkspacePath(folder, member.relative_path || member.filename);
      const dir = String(fullPath).replace(/[\\/][^\\/]*$/, "");
      const creoModel = ["prt", "asm", "drw"].includes(fileExtension(member.filename));
      try {
        if (creoModel && shell.hostedCreoJS?.() && shell.creoOpenMode?.() === "embedded") {
          await shell.withBusy("Opening in Creo…", async () => {
            await shell.whenCreoJSReady();
            const opened = await window.CreoJS.openModel(dir, member.filename, "", member.filename, fullPath);
            const text = opened == null ? "" : String(opened);
            if (text.indexOf("CREOPDM_ERROR:") === 0) throw new Error(text.slice("CREOPDM_ERROR:".length));
          });
          return;
        }
        await shell.withBusy("Opening…", async () => {
          const response = await fetch(`${shell.agentBase()}/open`, {
            method: "POST",
            headers: shell.agentAuthHeaders({ "Content-Type": "application/json" }),
            body: JSON.stringify({ path: fullPath, mode: "association" }),
          });
          if (!response.ok) throw new Error(await readError(response));
        });
      } catch (err) {
        showError(errorEl, err?.message || "The file could not be opened.");
      }
    }

    function cancelPendingBaselineOpen() {
      if (pendingOpen) window.clearTimeout(pendingOpen);
      pendingOpen = 0;
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
        // Archived baselines are still readable, so they can be compared with.
        const response = pid
          ? await fetch(`/api/products/${encodeURIComponent(pid)}/baselines?include_archived=true`)
          : null;
        const rows = response && response.ok ? await response.json() : [];
        for (const row of Array.isArray(rows) ? rows : []) {
          if (row.uuid === openBaselineUuid) continue;
          const option = document.createElement("option");
          option.value = row.uuid;
          option.textContent = `${row.name} (${titleCase(row.baseline_type)}${
            row.status === "ARCHIVED" ? ", archived" : ""
          })`;
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
      const rows = sortedRows(
        "compare",
        compareResult.items.filter((r) => showSame || r.status !== "UNCHANGED")
      );
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

    // ---- sortable columns (Files, Structure, Compare): click a header, click again to reverse ----
    // Sorting is done on the rows already loaded, so it is instant and never asks the server again.
    const sorts = { baselines: null, browse: null, files: null, structure: null, compare: null }; // { key, dir } or null (server order)
    let baselineList = [];
    const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });
    let filesData = [];
    let filesInfo = null;
    let structureData = [];

    /** "A.12" -> revision letters (A < B < ... < Z < AA) then iteration as a number. */
    function compareVersions(a, b) {
      const parse = (v) => {
        const match = /^([A-Za-z]+)\.(\d+)/.exec(String(v || ""));
        return match ? [match[1].toUpperCase(), Number(match[2])] : null;
      };
      const pa = parse(a);
      const pb = parse(b);
      if (!pa && !pb) return 0;
      if (!pa) return 1; // an empty version sorts after real ones
      if (!pb) return -1;
      if (pa[0].length !== pb[0].length) return pa[0].length - pb[0].length;
      if (pa[0] !== pb[0]) return pa[0] < pb[0] ? -1 : 1;
      return pa[1] - pb[1];
    }
    const byText = (get) => (x, y) => collator.compare(String(get(x) ?? ""), String(get(y) ?? ""));
    const byNumber = (get) => (x, y) => Number(get(x) ?? 0) - Number(get(y) ?? 0);
    const CHANGE_ORDER = { VERSION_CHANGED: 0, ADDED: 1, REMOVED: 2, UNCHANGED: 3 };
    const COLUMNS = {
      // The product's Baselines tab. Created sorts as the ISO timestamp text (oldest first).
      baselines: {
        name: byText((b) => b.name),
        type: (x, y) =>
          collator.compare(String(x.baseline_type || ""), String(y.baseline_type || "")) ||
          collator.compare(String(x.release_label || ""), String(y.release_label || "")),
        status: byText((b) => b.status),
        members: byNumber((b) => b.member_count),
        created: byText((b) => b.created_at),
        by: byText((b) => b.created_by),
      },
      files: {
        name: byText((m) => m.filename),
        rev: (x, y) => compareVersions(x.display_version, y.display_version),
        state: byText((m) => stateLabel(m.lifecycle_state)),
        type: byText((m) => String(m.object_type || "").replace(/^CREO_/, "")),
        // "Same version" first, then the files the product has moved on from (by what it has now).
        now: (x, y) =>
          (x.status === "OUT_OF_DATE") - (y.status === "OUT_OF_DATE") ||
          compareVersions(x.current_display_version, y.current_display_version),
      },
      structure: {
        parent: byText((e) => e.parent_filename),
        uses: byText((e) => e.child_filename),
        type: byText((e) => e.dependency_type),
        qty: byNumber((e) => e.quantity),
        resolved: (x, y) => Number(Boolean(x.resolved)) - Number(Boolean(y.resolved)),
      },
      compare: {
        name: byText((r) => r.filename),
        change: (x, y) => (CHANGE_ORDER[x.status] ?? 9) - (CHANGE_ORDER[y.status] ?? 9),
        mine: (x, y) => compareVersions(x.from_version, y.from_version),
        other: (x, y) => compareVersions(x.to_version, y.to_version),
      },
    };

    function sortedRows(table, rows) {
      const state = sorts[table];
      const compare = state && COLUMNS[table][state.key];
      if (!compare) return rows;
      // Array.prototype.sort is stable: equal rows keep their order, so a tie never shuffles.
      return [...rows].sort((x, y) => state.dir * (compare(x, y) || 0));
    }

    // The in-tab file list sorts on the same columns as the dialog's Files table.
    COLUMNS.browse = COLUMNS.files;

    const SORT_TABLE_IDS = {
      "baselines-table": "baselines",
      "baseline-browse-table": "browse",
      "baseline-members-table": "files",
      "baseline-structure-table": "structure",
      "baseline-compare-table": "compare",
    };

    /** Show the arrow on the sorted column (aria-sort) and none on the others. */
    function paintSortHeaders(table) {
      const id = Object.keys(SORT_TABLE_IDS).find((key) => SORT_TABLE_IDS[key] === table);
      const state = sorts[table];
      document.querySelectorAll(`#${id} th[data-sort]`).forEach((th) => {
        const active = state && th.getAttribute("data-sort") === state.key;
        if (active) th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
        else th.removeAttribute("aria-sort");
      });
    }

    function resetSorts() {
      for (const table of Object.keys(sorts)) {
        sorts[table] = null;
        paintSortHeaders(table);
      }
    }

    /** The captured structure: each parent version, the exact child version it uses, or "Unresolved". */
    function renderStructure(edges) {
      const tab = $("#baseline-structure-tab");
      const body = $("#baseline-structure-table tbody");
      structureData = Array.isArray(edges) ? edges : [];
      const list = structureData;
      if (tab) {
        tab.hidden = !list.length;
        tab.textContent = `Structure · ${list.length}`;
      }
      paintStructure();
    }

    function paintStructure() {
      const body = $("#baseline-structure-table tbody");
      if (!body) return;
      body.innerHTML = sortedRows("structure", structureData)
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
      )}/versions/${encodeURIComponent(m.version_uuid)}${
        info.uuid ? `?baseline=${encodeURIComponent(info.uuid)}` : ""
      }`;
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
      resetCopyStatus();
      resetSorts();
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
        void refreshCopyStatus(info);
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
            `${titleCase(info.status)} · ${titleCase(info.baseline_type)}${
              info.release_label ? ` ${info.release_label}` : ""
            } · ` +
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
        filesData = Array.isArray(members) ? members : [];
        filesInfo = info;
        paintFiles();
      } catch (err) {
        if (body) body.innerHTML = "";
        showError($("#baseline-members-error"), `Could not load the baseline: ${err?.message || "error"}`);
      }
    }

    function paintFiles() {
      const body = $("#baseline-members-table tbody");
      if (!body) return;
      body.innerHTML = sortedRows("files", filesData)
        .map((m) => {
          const newer = m.status === "OUT_OF_DATE";
          const now = newer
            ? `Newer: ${esc(m.current_display_version || "—")}`
            : "Same version";
          return `<tr data-version="${esc(m.version_uuid)}" data-object="${esc(m.object_uuid)}">
            <td class="baseline-name-cell">${versionLink(filesInfo, m)}${
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

    // ---- exact, read-only copy of a baseline on this PC --------------------------------------

    function formatSize(bytes) {
      const mb = Number(bytes || 0) / (1024 * 1024);
      return mb >= 10 ? `${Math.round(mb)} MB` : `${Math.round(mb * 10) / 10} MB`;
    }

    /** Ask the agent which product folder name it uses, then the agent does the rest. */
    function agentBody(info, extra) {
      return JSON.stringify({
        pdm_url: window.location.origin,
        product_id: info?.product_uuid || productId(),
        vault_folder: shell.currentVaultFolder ? shell.currentVaultFolder() : "",
        ...shell.agentPdmAuth(),
        ...extra,
      });
    }

    async function agentJson(path, info, extra) {
      const response = await fetch(`${shell.agentBase()}${path}`, {
        method: "POST",
        headers: shell.agentAuthHeaders({ "Content-Type": "application/json" }),
        body: agentBody(info, extra),
      });
      let body = null;
      try {
        body = await response.json();
      } catch {
        body = null;
      }
      return { ok: response.ok, status: response.status, body };
    }

    function agentMessage(result, fallback) {
      const detail = result.body?.detail;
      if (detail && typeof detail === "object") return detail.message || fallback;
      return (typeof detail === "string" && detail) || fallback;
    }

    function resetCopyStatus() {
      for (const id of ["#baseline-copy-status", "#baseline-ws-open", "#baseline-ws-remove"]) {
        const el = $(id);
        if (el) el.hidden = true;
      }
      const add = $("#baseline-ws-add");
      if (add) add.textContent = "Download baseline…";
    }

    /** Is this baseline already downloaded to this PC? Shows its state and the Open/Delete buttons. */
    async function refreshCopyStatus(info) {
      const uuid = info?.uuid;
      resetCopyStatus();
      if (!uuid || !info.workspace_folder) return;
      const agent = await shell.probeCreoAgent();
      if (!agent || openBaselineUuid !== uuid) return;
      let result;
      try {
        result = await agentJson("/baseline-workspace/check", info, { folder: info.workspace_folder });
      } catch {
        return;
      }
      if (openBaselineUuid !== uuid || !result.ok || !result.body?.installed) return;
      const body = result.body;
      const changed = (body.missing?.length || 0) + (body.modified?.length || 0);
      const extras = body.extras?.length || 0;
      const status = $("#baseline-copy-status");
      if (status) {
        status.hidden = false;
        status.textContent =
          `Downloaded to this PC: ${body.path}` +
          (changed ? ` — ${changed} file${changed === 1 ? "" : "s"} changed or missing` : "") +
          (extras ? ` — ${extras} extra file${extras === 1 ? "" : "s"} not part of the baseline` : "");
      }
      for (const id of ["#baseline-ws-open", "#baseline-ws-remove"]) {
        const el = $(id);
        if (el) el.hidden = false;
      }
      const add = $("#baseline-ws-add");
      if (add) add.textContent = "Download again…";
    }

    async function openCopyFolder() {
      const uuid = openBaselineUuid;
      if (!uuid) return;
      showError($("#baseline-members-error"), "");
      try {
        const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}`);
        const info = response.ok ? await response.json() : null;
        if (!info?.workspace_folder) throw new Error("The baseline folder name is not known.");
        const result = await agentJson("/baseline-workspace/open", info, { folder: info.workspace_folder });
        if (!result.ok) throw new Error(agentMessage(result, "The folder could not be opened."));
      } catch (err) {
        showError($("#baseline-members-error"), err?.message || "Could not open the baseline folder.");
      }
    }

    async function openAddToWorkspace() {
      const dialog = $("#baseline-workspace-dialog");
      const form = $("#baseline-workspace-form");
      const uuid = openBaselineUuid;
      if (!(dialog instanceof HTMLDialogElement) || !form || !uuid) return;
      const start = $("#baseline-ws-start");
      const cancel = $("#baseline-ws-cancel");
      const error = $("#baseline-ws-error");
      const resultBox = $("#baseline-ws-result");
      const overwriteRow = $("#baseline-ws-overwrite-row");
      const overwrite = $("#baseline-ws-overwrite");
      const wd = $("#baseline-ws-wd");
      const wdRow = $("#baseline-ws-wd-row");
      const wdNote = $("#baseline-ws-wd-note");
      if (wdRow) wdRow.hidden = false;
      showError(error, "");
      if (resultBox) resultBox.hidden = true;
      if (overwriteRow) overwriteRow.hidden = true;
      if (overwrite) overwrite.checked = false;
      if (start) {
        start.disabled = true;
        start.textContent = "Download";
      }
      $("#baseline-ws-name").textContent = $("#baseline-members-title")?.textContent || "";
      $("#baseline-ws-files").textContent = "Checking the baseline…";
      $("#baseline-ws-folder").textContent = "—";
      // The checkbox only works inside Creo's browser with the agent running.
      const canSetWd = shell.canSetCreoWorkingDirectory ? await shell.canSetCreoWorkingDirectory() : false;
      if (wd) {
        wd.checked = false;
        wd.disabled = !canSetWd;
      }
      if (wdNote) {
        wdNote.textContent = canSetWd ? "" : "(only available when this page is open inside Creo)";
      }
      if (!dialog.open) dialog.showModal();

      let manifest = null;
      try {
        const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}/workspace-manifest`);
        if (!response.ok) throw new Error(await readError(response));
        manifest = await response.json();
      } catch (err) {
        $("#baseline-ws-files").textContent = "—";
        showError(error, err?.message || "The baseline cannot be reconstructed.");
      }
      let info = null;
      try {
        const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}`);
        info = response.ok ? await response.json() : null;
      } catch {
        info = null;
      }
      if (manifest) {
        const total = manifest.files.reduce((sum, f) => sum + Number(f.size || 0), 0);
        $("#baseline-ws-files").textContent =
          `${manifest.files.length} file${manifest.files.length === 1 ? "" : "s"} · ${formatSize(total)}`;
        $("#baseline-ws-folder").textContent = `…\\_baselines\\${
          manifest.product?.vault_folder || manifest.product?.name || ""
        }\\${manifest.folder}`;
        const agent = await shell.probeCreoAgent();
        if (!agent) {
          showError(error, "Start creopdm-agent on this PC, then open this dialog again.");
        } else if (start) {
          start.disabled = false;
        }
      }

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
          if (!manifest || !start) return;
          // After a successful install the same button just closes the dialog.
          if (start.dataset.done === "1") {
            start.dataset.done = "";
            finish();
            return;
          }
          start.disabled = true;
          showError(error, "");
          start.textContent = "Downloading…";
          let result;
          try {
            result = await agentJson("/baseline-workspace", info, {
              manifest,
              overwrite: Boolean(overwrite?.checked),
            });
          } catch {
            showError(error, "The agent did not answer. Is creopdm-agent running?");
            start.disabled = false;
            start.textContent = "Download";
            return;
          }
          if (!result.ok) {
            const conflicts = result.body?.detail?.conflicts;
            showError(error, agentMessage(result, "The baseline could not be installed."));
            if (Array.isArray(conflicts) && conflicts.length && overwriteRow) overwriteRow.hidden = false;
            start.disabled = false;
            start.textContent = "Download";
            return;
          }
          const done = result.body || {};
          const extra = Array.isArray(done.extras) && done.extras.length
            ? ` ${done.extras.length} extra file${done.extras.length === 1 ? "" : "s"} in that folder ` +
              `are not part of the baseline (${done.extras.slice(0, 3).join(", ")}${
                done.extras.length > 3 ? ", …" : ""
              }).`
            : "";
          if (resultBox) {
            resultBox.hidden = false;
            resultBox.textContent =
              `Downloaded ${done.files_total} file${done.files_total === 1 ? "" : "s"} ` +
              `(${done.downloaded} new, ${done.kept} already correct), read-only, to ${done.path}.${extra}` +
              (done.folder_locked
                ? " The folder is locked, so Creo cannot save new files into it."
                : ` The folder could not be locked${done.lock_error ? ` (${done.lock_error})` : ""}, so Creo may still save new numbered files into it.`);
          }
          $("#baseline-ws-folder").textContent = done.path || "";
          if (wd?.checked && shell.setCreoWorkingDirectory) {
            await shell.setCreoWorkingDirectory({
              directory: done.path,
              message: "Creo working directory set to the baseline folder.",
            });
          }
          // The working directory is only applied during the install, so the box would now be a
          // button that does nothing: take it away.
          if (wdRow) wdRow.hidden = true;
          if (overwriteRow) overwriteRow.hidden = true;
          void refreshCopyStatus(info);
          start.dataset.done = "1";
          start.disabled = false;
          start.textContent = "Done";
          if (cancel) cancel.hidden = true;
        };
        const onCancel = () => finish();
        const onClose = () => finish();
        if (cancel) cancel.hidden = false;
        form.addEventListener("submit", onSubmit);
        cancel?.addEventListener("click", onCancel);
        dialog.addEventListener("close", onClose);
      });
    }

    async function removeFromWorkspace() {
      const uuid = openBaselineUuid;
      if (!uuid) return;
      showError($("#baseline-members-error"), "");
      try {
        const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}`);
        const info = response.ok ? await response.json() : null;
        if (!info?.workspace_folder) throw new Error("The baseline folder name is not known.");
        if (!window.confirm(
          `Delete the downloaded copy of “${info.name}” from this PC? Nothing in CreoPDM changes, and you can download it again.`
        )) return;
        const result = await agentJson("/baseline-workspace/remove", info, { folder: info.workspace_folder });
        if (!result.ok) throw new Error(agentMessage(result, "The folder could not be removed."));
        await refreshCopyStatus(info);
        if (result.body?.removed && result.body.folder_in_use) {
          // The folder is still there (something holds it): keep the button so it can be finished.
          const again = $("#baseline-ws-remove");
          if (again) again.hidden = false;
          // The files are gone but Windows will not delete a folder something has open.
          shell.showOk(
            `The copy's files were deleted, but the folder itself is still in use (${result.body.path}). ` +
              "It is probably Creo's working directory or open in Explorer: switch away or close it, " +
              "then press Delete downloaded copy again. The baseline itself is unchanged in CreoPDM."
          );
        } else {
          shell.showOk(
            result.body?.removed
              ? `Deleted the downloaded copy from this PC (${result.body.path}). The baseline itself is unchanged in CreoPDM.`
              : "This baseline has not been downloaded to this PC."
          );
        }
      } catch (err) {
        showError($("#baseline-members-error"), err?.message || "Could not remove the baseline folder.");
      }
    }

    $("#baseline-ws-add")?.addEventListener("click", () => void openAddToWorkspace());
    $("#baseline-ws-remove")?.addEventListener("click", () => void removeFromWorkspace());
    $("#baseline-ws-open")?.addEventListener("click", () => void openCopyFolder());

    mod.openBaselineMembers = openBaselineMembers;
    mod.browseBaseline = browseBaseline;
    mod.syncBrowseChrome = syncBrowseChrome;
    mod.showBaselineList = () => {
      leaveBrowse();
      return loadBaselinesTab();
    };
    mod.loadBaselinesTab = loadBaselinesTab;
    mod.openCreateBaselineDialog = openCreateBaselineDialog;

    // Click a column header to sort the list (click again to reverse).
    $("#baselines-table")?.addEventListener("click", (event) => {
      const th = event.target instanceof Element ? event.target.closest("th[data-sort]") : null;
      if (!th) return;
      const key = th.getAttribute("data-sort") || "";
      const current = sorts.baselines;
      sorts.baselines = current && current.key === key ? { key, dir: -current.dir } : { key, dir: 1 };
      paintSortHeaders("baselines");
      renderRows(sortedRows("baselines", baselineList));
    });

    $("#baselines-table")?.addEventListener("click", (event) => {
      // Buttons, not <a href="#">: the page-wide link handler soft-navigates every anchor,
      // and "#" is this very page, so an anchor here reloaded the Files tab.
      const target = event.target instanceof Element ? event.target : null;
      const details = target?.closest("[data-baseline-details]");
      if (details) {
        event.preventDefault();
        void openBaselineMembers(details.getAttribute("data-baseline-details") || "");
        return;
      }
      const link = target?.closest("[data-open-baseline]");
      if (!link) return;
      event.preventDefault();
      void browseBaseline(link.getAttribute("data-open-baseline") || "");
    });

    $("#baseline-browse-back")?.addEventListener("click", (event) => {
      event.preventDefault();
      leaveBrowse();
      void loadBaselinesTab();
    });
    $("#baseline-browse-details")?.addEventListener("click", () => {
      if (browseUuid) void openBaselineMembers(browseUuid);
    });
    // A click on a file name opens it (after a beat, so a double-click can open Details instead);
    // selection itself is the Files page's own handler.
    $("#baseline-browse-table")?.addEventListener("click", (event) => {
      const target = event.target instanceof Element ? event.target : null;
      const link = target?.closest(".baseline-file-open");
      if (!link || event.shiftKey || event.ctrlKey || event.metaKey) return;
      const row = link.closest("tr.object-row");
      if (!row) return;
      cancelPendingBaselineOpen();
      pendingOpen = window.setTimeout(() => {
        pendingOpen = 0;
        void openBaselineFile(row);
      }, 280);
    });
    $("#baseline-browse-table")?.addEventListener("dblclick", cancelPendingBaselineOpen);
    $("#baseline-browse-file-details")?.addEventListener("click", () => {
      const rows = selectedBrowseRows();
      const href = rows.length === 1 ? rows[0].dataset.detail : "";
      if (href) shell.leavePage(href);
    });
    // The footer button follows the selection (the Files page marks rows with .is-selected).
    const browseBody = $("#baseline-browse-table tbody");
    if (browseBody && typeof MutationObserver === "function") {
      new MutationObserver(syncFooterDetails).observe(browseBody, {
        subtree: true,
        attributes: true,
        attributeFilter: ["class"],
        childList: true,
      });
    }
    $("#baseline-browse-compare")?.addEventListener("click", async () => {
      if (!browseUuid) return;
      await openBaselineMembers(browseUuid);
      setBaselineView("compare");
      void loadCompareChoices();
    });
    $("#baseline-browse-download")?.addEventListener("click", async () => {
      if (!browseUuid) return;
      openBaselineUuid = browseUuid;
      await openAddToWorkspace();
    });
    $("#baseline-browse")?.addEventListener("click", (event) => {
      const th = event.target instanceof Element ? event.target.closest("#baseline-browse-table th[data-sort]") : null;
      if (!th) return;
      const key = th.getAttribute("data-sort") || "";
      const current = sorts.browse;
      sorts.browse = current && current.key === key ? { key, dir: -current.dir } : { key, dir: 1 };
      paintSortHeaders("browse");
      paintBrowse();
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

    $("#baseline-members-dialog")?.addEventListener("click", (event) => {
      const th = event.target instanceof Element ? event.target.closest("th[data-sort]") : null;
      const tableEl = th?.closest("table");
      const table = tableEl ? SORT_TABLE_IDS[tableEl.id] : null;
      if (!th || !table) return;
      const key = th.getAttribute("data-sort") || "";
      const current = sorts[table];
      sorts[table] = current && current.key === key ? { key, dir: -current.dir } : { key, dir: 1 };
      paintSortHeaders(table);
      if (table === "files") paintFiles();
      else if (table === "structure") paintStructure();
      else renderCompare();
    });

    $("#baseline-compare-to")?.addEventListener("change", () => void runCompare());
    $("#baseline-compare-unchanged")?.addEventListener("change", () => renderCompare());

    $("#baseline-members-dialog")?.addEventListener("click", (event) => {
      const button = event.target instanceof Element ? event.target.closest("[data-baseline-view]") : null;
      if (!button) return;
      event.preventDefault();
      setBaselineView(button.getAttribute("data-baseline-view") || "files");
    });

    $("#baselines-show-archived")?.addEventListener("change", () => void loadBaselinesTab());

    $("#create-baseline-btn")?.addEventListener("click", () => {
      void openCreateBaselineDialog();
    });
  },
};
