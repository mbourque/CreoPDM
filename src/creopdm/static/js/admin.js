window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.admin = {
  /** Admin user form: All products checkbox enables/disables the multi-select. */
  syncProductAccessUi(root = document) {
    const all = root.querySelector("#access-all-products");
    const list = root.querySelector("#product-access-list");
    if (!all || !list || String(list.tagName || "").toUpperCase() !== "SELECT") return;
    const locked = Boolean(all.checked);
    list.disabled = locked;
    list.classList.toggle("is-disabled", locked);
    if (locked) list.setAttribute("aria-disabled", "true");
    else list.removeAttribute("aria-disabled");
  },

  openCreateProduct() {
    window.__creopdmModules.admin.showProductDialog?.("create");
  },

  openRenameProduct() {
    window.__creopdmModules.admin.showProductDialog?.("rename");
  },

  showProductDialog: null,

  openDeleteProduct: null,

  init(shell) {
    const $ = shell.$;
    const withBusy = shell.withBusy;
    const showError = shell.showError;
    const showOk = shell.showOk;
    const readError = shell.readError;
    const leavePage = shell.leavePage;
    const eventEl = shell.eventEl;
    const currentProductId = shell.currentProductId;
    const assertProductAllows = shell.assertProductAllows;
    const agentBase = shell.agentBase;
    const agentAuthHeaders = shell.agentAuthHeaders;
    const probeCreoAgent = shell.probeCreoAgent;
    const abortSignalAfter = shell.abortSignalAfter;
    const currentVaultFolder = shell.currentVaultFolder;
    const clearProductViewStorage = shell.clearProductViewStorage;
    const closeProductSettings = shell.closeProductSettings;
    const syncCreoStatusPill = shell.syncCreoStatusPill;
    const isMetadataCollectRunning = shell.isMetadataCollectRunning;
    const setBusy = shell.setBusy;
    const runUtilitiesRebuildWithWhereUsed = shell.runUtilitiesRebuildWithWhereUsed;
    const origAddEventListener = shell.origAddEventListener;
    const addPageListener =
      shell.addPageListener ||
      ((target, type, listener, options) => target.addEventListener(type, listener, options));
    function onPage(el, type, listener, options) {
      if (!el) return;
      addPageListener(el, type, listener, options);
    }

    const mod = window.__creopdmModules.admin;

    const productDialog = $("#product-dialog");
    const productForm = $("#product-form");
    const settingsForm = $("#settings-form");

    let productVaultHash = "";
    let productVaultCustom = "";
    let productVaultCustomTouched = false;

    function newProductVaultHash() {
      if (window.crypto?.randomUUID) return window.crypto.randomUUID();
      if (window.crypto?.getRandomValues) {
        const bytes = new Uint8Array(16);
        window.crypto.getRandomValues(bytes);
        bytes[6] = (bytes[6] & 0x0f) | 0x40;
        bytes[8] = (bytes[8] & 0x3f) | 0x80;
        const hex = Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
        return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
      }
      let hex = "";
      for (let i = 0; i < 32; i += 1) hex += Math.floor(Math.random() * 16).toString(16);
      return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-4${hex.slice(13, 16)}-a${hex.slice(17, 20)}-${hex.slice(20)}`;
    }

    function slugifyVaultFolder(name) {
      const slug = String(name || "")
        .trim()
        .toLowerCase()
        .replace(/\s+/g, "-")
        .replace(/[^a-z0-9._-]+/g, "-")
        .replace(/-+/g, "-")
        .replace(/^[-.]+|[-.]+$/g, "");
      return slug.slice(0, 200);
    }

    function fillVaultFolderFromName() {
      const input = $("#product-vault-folder");
      const useHash = $("#product-use-hash");
      if (!input || useHash?.checked || productVaultCustomTouched) return;
      const slug = slugifyVaultFolder(productForm?.elements?.name?.value || "");
      input.value = slug;
      productVaultCustom = slug;
    }

    function syncProductVaultFolderField(resetHash) {
      const input = $("#product-vault-folder");
      const useHash = $("#product-use-hash");
      if (!input || !useHash) return;
      if (resetHash || !productVaultHash) productVaultHash = newProductVaultHash();
      if (useHash.checked) {
        input.value = productVaultHash;
        input.disabled = true;
        input.readOnly = true;
      } else {
        input.disabled = false;
        input.readOnly = false;
        if (!productVaultCustomTouched) {
          fillVaultFolderFromName();
        } else {
          input.value = productVaultCustom || "";
        }
      }
    }

    function showProductDialog(mode) {
      if (!productForm || !productDialog) return;
      showError($("#product-error"), "");
      const title = $("#product-dialog-title");
      const submit = $("#product-submit");
      const vaultFields = $("#product-vault-fields");
      productForm.dataset.mode = mode;
      if (mode === "rename") {
        const btn = $("#rename-product-btn");
        if (title) title.textContent = "Rename product";
        productForm.elements.name.value = btn?.dataset.name || "";
        productForm.elements.number.value = btn?.dataset.number || "";
        productForm.elements.description.value = btn?.dataset.description || "";
        if (vaultFields) vaultFields.hidden = true;
        if (submit) submit.textContent = "Save";
      } else {
        productForm.reset();
        if (title) title.textContent = "New product";
        if (submit) submit.textContent = "Create";
        if (vaultFields) vaultFields.hidden = false;
        productVaultCustom = "";
        productVaultCustomTouched = false;
        productVaultHash = "";
        const useHash = $("#product-use-hash");
        if (useHash) useHash.checked = true;
        syncProductVaultFolderField(true);
      }
      productDialog.showModal();
    }

    mod.showProductDialog = showProductDialog;

    const deleteProductDialog = $("#delete-product-dialog");
    const deleteProductForm = $("#delete-product-form");

    mod.openDeleteProduct = () => {
      closeProductSettings?.();
      if (isMetadataCollectRunning?.()) {
        showOk("Finish Collect metadata (or cancel it) before deleting this product.");
        return;
      }
      showError($("#delete-product-error"), "");
      if (deleteProductForm) deleteProductForm.reset();
      const deleteLocal = $("#delete-local-workspace");
      if (deleteLocal) deleteLocal.checked = true;
      deleteProductDialog?.showModal();
    };

    onPage($("#product-cancel"), "click", () => productDialog?.close());

    onPage($("#delete-product-cancel"), "click", () => deleteProductDialog?.close());

    onPage(deleteProductForm, "submit", async (event) => {
      event.preventDefault();
      const btn = $("#delete-product-btn");
      const productId = btn?.dataset.product;
      if (!productId) return;
      const formData = new FormData(deleteProductForm);
      const password = String(formData.get("confirm_password") || "");
      if (!password) {
        showError($("#delete-product-error"), "Enter your password to confirm.");
        return;
      }
      const deleteLocal = Boolean($("#delete-local-workspace")?.checked);
      const vaultFolder = currentVaultFolder();
      let result;
      try {
        result = await withBusy("Deleting product…", async () => {
          const notices = [];
          if (deleteLocal) {
            const agent = await probeCreoAgent();
            if (!agent) {
              notices.push(
                "creopdm-agent is not running — local workspace on this PC was not deleted."
              );
            } else {
              try {
                const localResponse = await fetch(`${agentBase()}/delete-product-cache`, {
                  method: "POST",
                  headers: agentAuthHeaders({ "Content-Type": "application/json" }),
                  body: JSON.stringify({
                    product_id: productId,
                    vault_folder: vaultFolder,
                    remove_folder: true,
                  }),
                  signal: abortSignalAfter(60_000),
                });
                if (!localResponse.ok) {
                  notices.push(await readError(localResponse));
                } else {
                  try {
                    const localBody = await localResponse.json();
                    if (localBody?.message && localBody.deleted === false) {
                      notices.push(String(localBody.message));
                    } else if (
                      typeof localBody?.message === "string"
                      && /could not be removed|still locked|still present/i.test(localBody.message)
                    ) {
                      notices.push(String(localBody.message));
                    }
                  } catch {
                    /* ignore */
                  }
                }
              } catch (exc) {
                notices.push(
                  exc?.name === "AbortError"
                    ? "Timed out clearing the local workspace (Creo may still have files open). Server delete continues."
                    : exc?.message
                        || "Could not reach creopdm-agent to delete the local workspace."
                );
              }
            }
          }
          const forgetResponse = await fetch(`/api/products/${productId}/forget`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ confirm_password: password }),
            signal: abortSignalAfter(120_000),
          });
          if (!forgetResponse.ok) {
            throw new Error(await readError(forgetResponse));
          }
          const body = await forgetResponse.json().catch(() => ({}));
          if (body.warning) notices.push(String(body.warning));
          body.warning = notices.filter(Boolean).join(" ");
          return body;
        });
      } catch (exc) {
        showError(
          $("#delete-product-error"),
          exc?.name === "AbortError"
            ? "Delete timed out. Cancel any still-running Add, wait a few seconds, or restart CreoPDM, then try again (uncheck local workspace if Creo has that folder open)."
            : exc?.message || "Could not delete the product."
        );
        return;
      }
      if (result?.warning) sessionStorage.setItem("creopdmNotice", result.warning);
      clearProductViewStorage(productId);
      leavePage("/");
    });

    onPage($("#product-use-hash"), "change", () => {
      const useHash = $("#product-use-hash");
      if (useHash?.checked) {
        productVaultCustomTouched = false;
        syncProductVaultFolderField(true);
      } else {
        syncProductVaultFolderField(false);
        $("#product-vault-folder")?.focus();
        $("#product-vault-folder")?.select();
      }
    });

    onPage(productForm?.elements?.name, "input", () => {
      fillVaultFolderFromName();
    });

    onPage($("#product-vault-folder"), "input", () => {
      const useHash = $("#product-use-hash");
      if (useHash?.checked) return;
      productVaultCustomTouched = true;
      productVaultCustom = String($("#product-vault-folder")?.value || "").trim();
    });

    onPage(productForm, "submit", async (event) => {
      event.preventDefault();
      const data = new FormData(productForm);
      const renaming = productForm.dataset.mode === "rename";
      if (renaming) {
        const productId = $("#rename-product-btn")?.dataset.product || currentProductId();
        const gate = await assertProductAllows(productId, "rename", {
          errorEl: $("#product-error"),
        });
        if (!gate.ok) return;
      }
      const body = {
        name: String(data.get("name") || "").trim(),
        number: String(data.get("number") || "").trim() || null,
        description: String(data.get("description") || "").trim() || null,
      };
      if (!renaming) {
        const useHash = Boolean($("#product-use-hash")?.checked);
        let vaultFolder = String(data.get("vault_folder") || "").trim();
        if (useHash) {
          body.vault_folder = productVaultHash || newProductVaultHash();
        } else {
          if (!vaultFolder) {
            showError($("#product-error"), "Enter a vault/workspace name, or check Use hash.");
            $("#product-vault-folder")?.focus();
            return;
          }
          if (/\s/.test(vaultFolder)) {
            showError($("#product-error"), "Vault/workspace name cannot contain spaces.");
            return;
          }
          body.vault_folder = vaultFolder;
        }
      }
      if (!body.name) {
        showError($("#product-error"), "A product name is required.");
        return;
      }
      const productId = $("#rename-product-btn")?.dataset.product;
      const url = renaming ? `/api/products/${productId}` : "/api/products";
      const response = await withBusy(renaming ? "Saving product…" : "Creating product…", () =>
        fetch(url, {
          method: renaming ? "PATCH" : "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        })
      );
      if (!response.ok) {
        showError($("#product-error"), await readError(response));
        return;
      }
      const product = await response.json();
      leavePage(`/?product=${encodeURIComponent(product.uuid)}`);
    });

    function syncEmbeddedOpenOptions() {
      if (!settingsForm) return;
      const nested = settingsForm.querySelector("#embedded-open-options");
      if (!nested) return;
      const embeddedOn = Boolean(
        settingsForm.querySelector('input[name="creo_open_mode"][value="embedded"]')?.checked
      );
      nested.classList.toggle("is-disabled", !embeddedOn);
      if (embeddedOn) nested.removeAttribute("aria-disabled");
      else nested.setAttribute("aria-disabled", "true");
      nested.querySelectorAll("input, textarea, select").forEach((el) => {
        el.disabled = !embeddedOn;
      });
    }

    settingsForm?.querySelectorAll('input[name="creo_open_mode"]').forEach((radio) => {
      addPageListener(radio, "change", syncEmbeddedOpenOptions);
    });
    syncEmbeddedOpenOptions();

    function syncAiSettingsOptions() {
      if (!settingsForm) return;
      const card = settingsForm.querySelector("#ai-ollama-settings");
      if (!card) return;
      const aiOn = Boolean(settingsForm.querySelector('[name="ai_enabled"]')?.checked);
      card.classList.toggle("is-disabled", !aiOn);
      if (aiOn) card.removeAttribute("aria-disabled");
      else card.setAttribute("aria-disabled", "true");
      card.querySelectorAll("input, textarea, select, button").forEach((el) => {
        el.disabled = !aiOn;
      });
    }

    onPage(settingsForm?.querySelector('[name="ai_enabled"]'), "change", syncAiSettingsOptions);
    syncAiSettingsOptions();

    function prettyUnavailableSince(date = new Date()) {
      const days = [
        "Sunday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
      ];
      const months = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
      ];
      const hour = date.getHours();
      const minute = date.getMinutes();
      const hour12 = hour % 12 || 12;
      const ampm = hour < 12 ? "am" : "pm";
      return (
        `${days[date.getDay()]}, ${months[date.getMonth()]} ${date.getDate()}, ${date.getFullYear()} `
        + `at ${hour12}:${String(minute).padStart(2, "0")}${ampm}`
      );
    }

    function isStockUnavailableMessage(text, base) {
      const value = String(text || "").trim();
      const stock = String(base || "").trim();
      if (!value || !stock) return !value;
      if (value === stock) return true;
      return value.startsWith(`${stock}\n\nSince `);
    }

    function syncSiteAvailabilityOptions() {
      if (!settingsForm) return;
      const unavailableOn = Boolean(
        settingsForm.querySelector('input[name="site_availability"][value="unavailable"]')?.checked
      );
      const wrap = settingsForm.querySelector("#site-unavailable-message-wrap");
      const message = settingsForm.querySelector('[name="site_unavailable_message"]');
      if (wrap) {
        wrap.classList.toggle("is-disabled", !unavailableOn);
        if (unavailableOn) wrap.removeAttribute("aria-disabled");
        else wrap.setAttribute("aria-disabled", "true");
      }
      if (message) {
        message.disabled = !unavailableOn;
        if (unavailableOn) {
          const base = message.getAttribute("data-default-base") || "";
          if (isStockUnavailableMessage(message.value, base)) {
            message.value = `${base}\n\nSince ${prettyUnavailableSince()}.`;
          }
        }
      }
    }

    function syncUnavailableAdminPill(unavailable) {
      const pill = $("#site-unavailable-pill");
      if (!pill) return;
      pill.hidden = !unavailable;
    }

    settingsForm?.querySelectorAll('input[name="site_availability"]').forEach((radio) => {
      addPageListener(radio, "change", syncSiteAvailabilityOptions);
    });
    syncSiteAvailabilityOptions();

    function splitExtensionList(raw) {
      return String(raw || "")
        .split(/[\s,;]+/)
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function parseOptionalInt(raw, fallback) {
      const text = String(raw || "").trim();
      if (!text) return fallback;
      const parsed = Number.parseInt(text, 10);
      return Number.isFinite(parsed) ? parsed : fallback;
    }

    onPage(settingsForm, "submit", async (event) => {
      event.preventDefault();
      showError($("#settings-error"), "");
      const ok = $("#settings-ok");
      if (ok) ok.hidden = true;
      const data = new FormData(settingsForm);
      const body = {};
      if (settingsForm.querySelector('[name="site_availability"]')) {
        body.site_availability = String(data.get("site_availability") || "available");
        const unavailableMessageEl = settingsForm.querySelector('[name="site_unavailable_message"]');
        body.site_unavailable_message = String(unavailableMessageEl?.value || "").trim();
      }
      if (settingsForm.querySelector('[name="creo_open_mode"]')) {
        body.creo_open_mode = String(data.get("creo_open_mode") || "association");
        const jsLibraryInput = settingsForm.querySelector('[name="creo_js_library"]');
        body.creo_js_library = jsLibraryInput
          ? String(jsLibraryInput.value || "").trim() || null
          : null;
      }
      if (settingsForm.querySelector('[name="workspace_root"]')) {
        body.workspace_root = String(data.get("workspace_root") || "").trim() || null;
      }
      if (settingsForm.querySelector('[name="cad_model_extensions"]')) {
        body.cad_model_extensions = splitExtensionList(data.get("cad_model_extensions"));
      }
      if (settingsForm.querySelector('[name="cad_models_extensions"]')) {
        body.cad_models_extensions = splitExtensionList(data.get("cad_models_extensions"));
      }
      if (settingsForm.querySelector('[name="document_extensions"]')) {
        body.document_extensions = splitExtensionList(data.get("document_extensions"));
      }
      if (settingsForm.querySelector('[name="cad_openable_extensions"]')) {
        body.cad_openable_extensions = splitExtensionList(data.get("cad_openable_extensions"));
      }
      if (settingsForm.querySelector('[name="cad_extensions"]')) {
        body.cad_extensions = splitExtensionList(data.get("cad_extensions"));
      }
      if (settingsForm.querySelector('[name="purgeable_extensions"]')) {
        body.purgeable_extensions = splitExtensionList(data.get("purgeable_extensions"));
      }
      if (settingsForm.querySelector('[name="ignore_patterns"]')) {
        body.ignore_patterns = splitExtensionList(data.get("ignore_patterns"));
      }
      if (settingsForm.querySelector('[name="database_url"]')) {
        body.database_url = String(data.get("database_url") || "").trim();
      }
      if (settingsForm.querySelector('[name="port"]')) {
        body.port = parseOptionalInt(data.get("port"), 0);
      }
      if (settingsForm.querySelector('[name="agent_base_url"]')) {
        body.agent_base_url = String(data.get("agent_base_url") || "").trim();
      }
      if (settingsForm.querySelector('[name="workspace_poll_interval_ms"]')) {
        body.workspace_poll_interval_ms = parseOptionalInt(
          data.get("workspace_poll_interval_ms"),
          5000
        );
      }
      if (settingsForm.querySelector('[name="workspace_poll_idle_minutes"]')) {
        body.workspace_poll_idle_minutes = parseOptionalInt(
          data.get("workspace_poll_idle_minutes"),
          10
        );
      }
      if (settingsForm.querySelector('[name="ai_enabled"]')) {
        body.ai_enabled = Boolean(
          settingsForm.querySelector('[name="ai_enabled"]')?.checked
        );
      }
      const ollamaUrl = settingsForm.querySelector('[name="ollama_base_url"]');
      if (ollamaUrl) {
        body.ollama_base_url = String(ollamaUrl.value || "").trim();
        body.ollama_model = String(
          settingsForm.querySelector('[name="ollama_model"]')?.value || ""
        ).trim();
      }
      const promptEl = settingsForm.querySelector('[name="snapshot_compare_prompt"]');
      if (promptEl) {
        body.snapshot_compare_prompt = String(promptEl.value || "");
      }
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        showError($("#settings-error"), await readError(response));
        return;
      }
      if (ok) ok.hidden = false;
      const saved = await response.json().catch(() => null);
      const workspaceInput = settingsForm.querySelector('[name="workspace_root"]');
      if (workspaceInput && saved?.workspace_root) {
        workspaceInput.value = saved.workspace_root;
      }
      const messageInput = settingsForm.querySelector('[name="site_unavailable_message"]');
      if (messageInput && saved?.site_unavailable_message) {
        messageInput.value = saved.site_unavailable_message;
      }
      if (Object.prototype.hasOwnProperty.call(body, "site_availability")) {
        syncUnavailableAdminPill(
          String(saved?.site_availability || body.site_availability || "") === "unavailable"
        );
      }
      if (Object.prototype.hasOwnProperty.call(body, "ai_enabled")) {
        const on = Boolean(
          saved && Object.prototype.hasOwnProperty.call(saved, "ai_enabled")
            ? saved.ai_enabled
            : body.ai_enabled
        );
        document.body.dataset.aiEnabled = on ? "1" : "0";
      }
      if (body.creo_open_mode) {
        syncCreoStatusPill(body.creo_open_mode);
      }
    });

    const typeLabelsForm = $("#type-labels-form");
    const typeLabelRows = $("#type-label-rows");
    function typeLabelRow(extension = "", label = "") {
      const tr = document.createElement("tr");
      const extTd = document.createElement("td");
      const extInput = document.createElement("input");
      extInput.name = "extension";
      extInput.type = "text";
      extInput.value = extension;
      extInput.placeholder = ".stp, .step";
      extInput.autocomplete = "off";
      extTd.appendChild(extInput);
      const labelTd = document.createElement("td");
      const labelInput = document.createElement("input");
      labelInput.name = "label";
      labelInput.type = "text";
      labelInput.value = label;
      labelInput.placeholder = "STEP Model";
      labelInput.autocomplete = "off";
      labelTd.appendChild(labelInput);
      const actionTd = document.createElement("td");
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "btn btn-small type-label-remove";
      remove.textContent = "Remove";
      actionTd.appendChild(remove);
      tr.append(extTd, labelTd, actionTd);
      return tr;
    }
    onPage($("#type-label-add"), "click", () => {
      typeLabelRows?.appendChild(typeLabelRow());
    });
    onPage(typeLabelRows, "click", (event) => {
      const button = eventEl(event)?.closest(".type-label-remove");
      if (!button) return;
      button.closest("tr")?.remove();
      if (typeLabelRows && !typeLabelRows.querySelector("tr")) {
        typeLabelRows.appendChild(typeLabelRow());
      }
    });
    onPage(typeLabelsForm, "submit", async (event) => {
      event.preventDefault();
      showError($("#settings-error"), "");
      const ok = $("#settings-ok");
      if (ok) ok.hidden = true;
      const type_labels = [...(typeLabelRows?.querySelectorAll("tr") || [])]
        .map((row) => ({
          extension: String(row.querySelector("[name=extension]")?.value || "").trim(),
          label: String(row.querySelector("[name=label]")?.value || "").trim(),
        }))
        .filter((item) => item.extension || item.label);
      const body = { type_labels };
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) {
        showError($("#settings-error"), await readError(response));
        return;
      }
      if (ok) ok.hidden = false;
    });

    const ollamaSettings = $("#ai-ollama-settings");
    function normalizeOllamaRoot(raw) {
      let text = String(raw || "").trim().replace(/\/+$/, "");
      if (!text) text = "http://127.0.0.1:11434";
      if (!/^[a-zA-Z][a-zA-Z0-9+.-]*:\/\//.test(text)) text = `http://${text}`;
      return text;
    }
    function applyOllamaModelOptions(select, models, previous, statusEl, note) {
      select.replaceChildren();
      if (!models.length) {
        const empty = document.createElement("option");
        empty.value = "";
        empty.textContent = "No models found — pull one in Ollama first";
        select.appendChild(empty);
        if (statusEl) statusEl.textContent = note || "Reached Ollama, but no models are installed.";
        return;
      }
      for (const name of models) {
        const option = document.createElement("option");
        option.value = name;
        option.textContent = name === previous ? `${name} (current)` : name;
        if (name === previous) option.selected = true;
        select.appendChild(option);
      }
      if (previous && !models.includes(previous)) {
        const keep = document.createElement("option");
        keep.value = previous;
        keep.textContent = `${previous} (saved — not on server)`;
        keep.selected = true;
        select.insertBefore(keep, select.firstChild);
      }
      if (statusEl) {
        statusEl.textContent =
          note ||
          `Connected — ${models.length} model${models.length === 1 ? "" : "s"}.`;
      }
    }
    async function listOllamaModelsFromBrowser(baseUrl) {
      const root = normalizeOllamaRoot(baseUrl);
      const response = await fetch(`${root}/api/tags`, {
        cache: "no-store",
        mode: "cors",
      });
      if (!response.ok) {
        throw new Error(`Ollama returned HTTP ${response.status} for ${root}/api/tags`);
      }
      const payload = await response.json();
      const models = Array.isArray(payload?.models) ? payload.models : [];
      const names = [];
      const seen = new Set();
      for (const item of models) {
        const name = String(item?.name || item?.model || "").trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        names.push(name);
      }
      names.sort((a, b) => a.localeCompare(b, undefined, { sensitivity: "base" }));
      return { base_url: root, models: names };
    }
    async function refreshOllamaModels() {
      const urlInput = $("#ollama-base-url");
      const modelSelect = $("#ollama-model");
      const statusEl = $("#ollama-status");
      const refreshBtn = $("#ollama-refresh-models");
      if (!modelSelect || !urlInput) return;
      const baseUrl = String(urlInput.value || "").trim();
      const saved = String(modelSelect.dataset.savedModel || "").trim();
      const previous = String(modelSelect.value || "").trim() || saved;
      showError($("#settings-error"), "");
      if (statusEl) {
        statusEl.textContent = "Contacting Ollama via CreoPDM server…";
        statusEl.classList.remove("error");
      }
      if (refreshBtn) refreshBtn.disabled = true;
      let serverMessage = "";
      try {
        const qs = baseUrl ? `?base_url=${encodeURIComponent(baseUrl)}` : "";
        const response = await fetch(`/api/settings/ai/ollama/models${qs}`, {
          credentials: "same-origin",
          cache: "no-store",
        });
        if (response.ok) {
          const payload = await response.json();
          const models = Array.isArray(payload?.models) ? payload.models.map(String) : [];
          applyOllamaModelOptions(
            modelSelect,
            models,
            previous,
            statusEl,
            `Server reached ${payload?.base_url || baseUrl} — ${models.length} model${models.length === 1 ? "" : "s"}.`
          );
          return;
        }
        serverMessage = (await readError(response)) || `Server probe failed (HTTP ${response.status}).`;
      } catch (err) {
        serverMessage = String(err?.message || err || "Server probe failed.");
      }
      if (statusEl) {
        statusEl.textContent = `${serverMessage} Trying this browser…`;
        statusEl.classList.remove("error");
      }
      try {
        const payload = await listOllamaModelsFromBrowser(baseUrl);
        applyOllamaModelOptions(
          modelSelect,
          payload.models,
          previous,
          statusEl,
          `Browser reached ${payload.base_url} — ${payload.models.length} model${payload.models.length === 1 ? "" : "s"} (CreoPDM server could not). Save still stores the URL for later server-side use.`
        );
      } catch (err) {
        const browserMessage = String(err?.message || err || "Browser could not reach Ollama.");
        const combined =
          `${serverMessage} Browser fallback also failed: ${browserMessage}. `
          + "On the CreoPDM host, test: curl -sS -m 5 http://michael-desktop:11434/api/tags — "
          + "and on this PC: curl.exe -sS http://127.0.0.1:11434/api/tags";
        if (statusEl) {
          statusEl.textContent = combined;
          statusEl.classList.add("error");
        }
        showError($("#settings-error"), combined);
      } finally {
        if (refreshBtn) refreshBtn.disabled = false;
      }
    }
    onPage($("#ollama-refresh-models"), "click", () => {
      void refreshOllamaModels();
    });
    if (ollamaSettings) {
      void refreshOllamaModels();
    }

    if (origAddEventListener && !window.__creopdmProductAccessBound) {
      window.__creopdmProductAccessBound = true;
      const onProductAccessToggle = (event) => {
        const t = event?.target;
        if (!t || t.id !== "access-all-products") return;
        mod.syncProductAccessUi();
      };
      origAddEventListener.call(document, "change", onProductAccessToggle, true);
      origAddEventListener.call(document, "input", onProductAccessToggle, true);
    }

    if (origAddEventListener && !window.__creopdmUtilitiesBusyBound) {
      window.__creopdmUtilitiesBusyBound = true;
      origAddEventListener.call(
        document,
        "submit",
        (event) => {
          const form = event.target;
          if (!(form instanceof HTMLFormElement)) return;
          const select = form.querySelector('select[name="product_id"]');
          const label = select?.selectedOptions?.[0]?.textContent?.trim() || "product";
          let message = "";
          if (form.id === "utilities-compact-vault-form") {
            message = `Compacting vault history for ${label}…`;
          } else if (form.id === "utilities-rebuild-product-form") {
            const fd = new FormData(form);
            const action = String(fd.get("repair_action") || "");
            if (action === "rebuild_where_used") {
              const runner = runUtilitiesRebuildWithWhereUsed;
              // Never preventDefault without a runner — form would hang with no submit.
              if (typeof runner === "function") {
                event.preventDefault();
                void runner(form);
                return;
              }
            }
            if (action === "rebuild") {
              message = `Rebuilding product database for ${label}…`;
            } else if (action === "clear_metadata") {
              message = `Deleting Creo metadata for ${label}…`;
            } else {
              message = `Repairing product database for ${label}…`;
            }
          } else if (form.id === "utilities-delete-products-form") {
            message = `Deleting product ${label}…`;
          } else {
            return;
          }
          if (typeof setBusy === "function") setBusy(message);
          else {
            const text = document.getElementById("busy-message");
            if (text) text.textContent = message;
            const overlay = document.getElementById("busy-overlay");
            if (overlay instanceof HTMLDialogElement && !overlay.open) overlay.showModal();
            document.body.classList.add("is-busy");
            document.body.setAttribute("aria-busy", "true");
          }
          const btn = form.querySelector('button[type="submit"]');
          if (btn instanceof HTMLButtonElement) btn.disabled = true;
        },
        true
      );
    }

    mod.syncProductAccessUi();
  },
};
