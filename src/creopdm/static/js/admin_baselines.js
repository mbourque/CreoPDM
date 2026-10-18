/* Administration -> Baselines: global list, integrity check, archive / restore.
 *
 * A lazy client module (like baselines.js): the app swaps only <main.shell> on a soft navigation
 * and never runs <script> tags in it, so app.js starts this module after every page swap
 * (init runs once per page view, on the fresh DOM).
 */
window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.admin_baselines = {
  init() {
    const page = document.getElementById("admin-baselines-page");
    if (!page) return;

  const $ = (sel) => document.querySelector(sel);
  const esc = (v) =>
    String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const titleCase = (v) => {
    const t = String(v || "").toLowerCase();
    return t ? t.charAt(0).toUpperCase() + t.slice(1) : "—";
  };
  const when = (iso) => {
    if (!iso) return "—";
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
  };
  const showError = (text) => {
    const el = $("#baseline-admin-error");
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
  };
  const showNote = (text) => {
    const el = $("#baseline-admin-note");
    if (!el) return;
    el.hidden = !text;
    el.textContent = text || "";
  };
  async function errorText(response) {
    try {
      const body = await response.json();
      return body?.error?.message || body?.detail || `Request failed (${response.status}).`;
    } catch {
      return `Request failed (${response.status}).`;
    }
  }

  let items = [];
  const health = new Map(); // baseline uuid -> integrity report (this page view only)
  let currentReport = null;

  const STATUS_LABEL = { HEALTHY: "Healthy", WARNING: "Warning", ERROR: "Error" };

  function healthCell(uuid) {
    const report = health.get(uuid);
    if (!report) return '<span class="muted">Not checked</span>';
    const label = STATUS_LABEL[report.status] || report.status;
    const detail = report.problem_count
      ? `${report.problem_count} problem${report.problem_count === 1 ? "" : "s"}`
      : report.tag_warning
        ? "tag"
        : "";
    return `<button type="button" class="baseline-health is-${esc(report.status.toLowerCase())}" data-details="${esc(uuid)}"
      title="Show the integrity details">${esc(label)}${detail ? ` · ${esc(detail)}` : ""}</button>`;
  }

  function updateHealthStats() {
    const reports = [...health.values()];
    $("#bstat-warning").textContent = reports.length ? String(reports.filter((r) => r.status === "WARNING").length) : "—";
    $("#bstat-error").textContent = reports.length ? String(reports.filter((r) => r.status === "ERROR").length) : "—";
  }

  function render() {
    const body = $("#baseline-admin-table tbody");
    if (!body) return;
    if (!items.length) {
      body.innerHTML = '<tr class="empty-row"><td colspan="9">No baselines match.</td></tr>';
      return;
    }
    body.innerHTML = items
      .map((item) => {
        const archived = item.status === "ARCHIVED";
        const kind = `${titleCase(item.baseline_type)}${
          item.release_label ? ` <span class="baseline-release-badge">${esc(item.release_label)}</span>` : ""
        }`;
        return `<tr data-baseline="${esc(item.uuid)}" class="${archived ? "is-archived" : ""}">
          <td class="baseline-name-cell">${esc(item.product_name)}</td>
          <td class="baseline-name-cell"><a href="/?product=${encodeURIComponent(item.product_uuid)}#baselines"
              title="Open this product's Baselines tab">${esc(item.name)}</a>${
            item.description ? `<div class="muted small">${esc(item.description)}</div>` : ""
          }</td>
          <td>${kind}</td>
          <td>${esc(titleCase(item.status))}</td>
          <td>${esc(item.member_count)}</td>
          <td title="${esc(item.created_at || "")}">${esc(when(item.created_at))}</td>
          <td>${esc(item.created_by)}</td>
          <td>${healthCell(item.uuid)}</td>
          <td class="baseline-admin-actions">
            <button type="button" class="btn" data-check="${esc(item.uuid)}">Check</button>
            <button type="button" class="btn" data-${archived ? "restore" : "archive"}="${esc(item.uuid)}">${
              archived ? "Restore" : "Archive"
            }</button>
          </td>
        </tr>`;
      })
      .join("");
  }

  async function load() {
    showError("");
    const params = new URLSearchParams();
    const q = $("#baseline-admin-q")?.value.trim();
    if (q) params.set("q", q);
    const type = $("#baseline-admin-type")?.value;
    if (type) params.set("type", type);
    const status = $("#baseline-admin-status")?.value;
    if (status) params.set("status", status);
    try {
      const response = await fetch(`/api/admin/baselines?${params}`);
      if (!response.ok) throw new Error(await errorText(response));
      const data = await response.json();
      items = Array.isArray(data.items) ? data.items : [];
      for (const key of ["total", "finalized", "archived", "release", "manual"]) {
        const el = $(`#bstat-${key}`);
        if (el) el.textContent = String(data.summary?.[key] ?? 0);
      }
      render();
      updateHealthStats();
    } catch (err) {
      showError(`Could not load the baselines: ${err?.message || "error"}`);
    }
  }

  function showReport(report) {
    currentReport = report;
    const dialog = $("#baseline-integrity-dialog");
    if (!(dialog instanceof HTMLDialogElement)) return;
    $("#baseline-integrity-title").textContent = `${report.name} — ${STATUS_LABEL[report.status] || report.status}`;
    $("#baseline-integrity-sub").textContent =
      `${report.product_name} · ${titleCase(report.baseline_type)} · checked ${new Date(report.checked_at).toLocaleString()}` +
      (report.deep ? " (file hashes verified)" : " (quick check)");
    const tag = report.tag_name
      ? `${report.tag_name}: ${titleCase(String(report.tag_state).replace(/_/g, " "))}`
      : "No Git tag";
    const facts = [
      ["Members", `${report.members}`],
      ["Member records", `${report.versions_ok} / ${report.members} available`],
      ["Content in the vault", `${report.content_ok} / ${report.members} found`],
      ["File hashes", report.hashes_ok == null ? "not checked (use Verify file hashes)" : `${report.hashes_ok} / ${report.members} valid`],
      ["Git commit", report.stored_commit ? `${report.stored_commit.slice(0, 12)} — ${titleCase(String(report.commit).replace(/_/g, " "))}` : "not recorded"],
      ["Git tag", tag],
    ];
    $("#baseline-integrity-facts").innerHTML = facts
      .map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`)
      .join("");
    const rows = [...(report.problems || [])];
    if (report.tag_warning) rows.push({ code: "TAG", file: "", version: "", reason: report.tag_warning });
    $("#baseline-integrity-problems tbody").innerHTML = rows.length
      ? rows
          .map(
            (p) => `<tr><td>${esc(String(p.code).replace(/_/g, " ").toLowerCase())}</td>
            <td class="baseline-name-cell">${esc(p.file)}</td><td>${esc(p.version)}</td><td>${esc(p.reason)}</td></tr>`
          )
          .join("")
      : '<tr class="empty-row"><td colspan="4">No problems found.</td></tr>';
    $("#baseline-integrity-deep").hidden = Boolean(report.deep);
    if (!dialog.open) dialog.showModal();
  }

  async function check(uuid, deep) {
    showError("");
    try {
      const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}/integrity?deep=${deep ? "true" : "false"}`, {
        method: "POST",
      });
      if (!response.ok) throw new Error(await errorText(response));
      const report = await response.json();
      health.set(uuid, report);
      render();
      updateHealthStats();
      return report;
    } catch (err) {
      showError(`Could not check the baseline: ${err?.message || "error"}`);
      return null;
    }
  }

  async function checkAll() {
    showError("");
    const button = $("#baseline-admin-check-all");
    if (button) button.disabled = true;
    showNote("Checking every baseline…");
    try {
      const response = await fetch("/api/admin/baselines/integrity", { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      const reports = await response.json();
      for (const report of reports) health.set(report.baseline_uuid, report);
      render();
      updateHealthStats();
      const bad = reports.filter((r) => r.status !== "HEALTHY").length;
      showNote(
        `Checked ${reports.length} baseline${reports.length === 1 ? "" : "s"}: ${
          bad ? `${bad} need attention (click a result for details).` : "all healthy."
        } Hashes are verified per baseline with Check → Verify file hashes.`
      );
    } catch (err) {
      showNote("");
      showError(`Integrity check failed: ${err?.message || "error"}`);
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function act(uuid, action) {
    showError("");
    try {
      const response = await fetch(`/api/baselines/${encodeURIComponent(uuid)}/${action}`, { method: "POST" });
      if (!response.ok) throw new Error(await errorText(response));
      await load();
    } catch (err) {
      showError(`Could not ${action} the baseline: ${err?.message || "error"}`);
    }
  }

  $("#baseline-admin-table")?.addEventListener("click", async (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (!target) return;
    const checkBtn = target.closest("[data-check]");
    if (checkBtn) {
      const report = await check(checkBtn.getAttribute("data-check") || "", false);
      if (report) showReport(report);
      return;
    }
    const details = target.closest("[data-details]");
    if (details) {
      const report = health.get(details.getAttribute("data-details") || "");
      if (report) showReport(report);
      return;
    }
    const archive = target.closest("[data-archive]");
    if (archive) {
      const uuid = archive.getAttribute("data-archive") || "";
      const name = items.find((i) => i.uuid === uuid)?.name || "this baseline";
      if (window.confirm(`Archive “${name}”? It stays protected and can be restored; nothing is deleted.`)) {
        await act(uuid, "archive");
      }
      return;
    }
    const restore = target.closest("[data-restore]");
    if (restore) await act(restore.getAttribute("data-restore") || "", "restore");
  });

  $("#baseline-integrity-deep")?.addEventListener("click", async (event) => {
    event.preventDefault();
    if (!currentReport) return;
    const button = event.currentTarget;
    if (button instanceof HTMLButtonElement) button.disabled = true;
    const report = await check(currentReport.baseline_uuid, true);
    if (button instanceof HTMLButtonElement) button.disabled = false;
    if (report) showReport(report);
  });

  $("#baseline-admin-check-all")?.addEventListener("click", () => void checkAll());
  let timer = 0;
  for (const id of ["#baseline-admin-q"]) {
    $(id)?.addEventListener("input", () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => void load(), 250);
    });
  }
  for (const id of ["#baseline-admin-type", "#baseline-admin-status"]) {
    $(id)?.addEventListener("change", () => void load());
  }
    void load();
  },
};
