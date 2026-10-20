window.__creopdmModules = window.__creopdmModules || {};
window.__creopdmModules.comments = {
  /**
   * Discussion: threads of comments on a product, a file, an exact version, a baseline or a
   * baseline's file. One component (`mount`) serves the Details "Discussion" tab, the product's
   * Discussion tab (a feed of every thread) and the baseline discussion dialog.
   *
   * @mentions: typing "@" opens a list of the product's people (those with access), each further
   * letter narrows it, a click / Enter / Tab inserts "@username". Images: paste (Ctrl+V), drop, or
   * "Attach image"; they are uploaded as drafts and linked when the comment is sent.
   * Loaded lazily the first time a Discussion surface is opened.
   */
  init(shell) {
    const mod = window.__creopdmModules.comments;
    const $ = shell.$;
    const MAX_IMAGES = 4;
    const MAX_BYTES = 5 * 1024 * 1024;
    const canAdd = document.body?.dataset.canAddComments === "1";

    function esc(value) {
      return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
    }

    async function request(path, options) {
      const response = await fetch(path, options);
      if (!response.ok) throw new Error(await shell.readError(response));
      return response.status === 204 ? null : response.json();
    }

    function json(method, body) {
      return { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) };
    }

    const when = (iso) => shell.formatStamp(iso) || "";
    const whenPretty = (iso) => shell.formatStampPretty(iso) || "";

    function bodyHtml(comment) {
      let html = esc(comment.body);
      for (const person of comment.mentions || []) {
        const pattern = new RegExp(`@${person.username}(?![A-Za-z0-9_])`, "gi");
        html = html.replace(
          pattern,
          `<span class="cm-mention" title="@${esc(person.username)}">@${esc(person.display_name)}</span>`
        );
      }
      return html.replace(/\n/g, "<br>");
    }

    function sizeText(bytes) {
      return shell.formatByteSize ? shell.formatByteSize(bytes) : `${Math.round(bytes / 1024)} KB`;
    }

    // ------------------------------------------------------------------ lightbox
    function lightbox() {
      let dialog = document.getElementById("cm-lightbox");
      if (dialog) return dialog;
      dialog = document.createElement("dialog");
      dialog.id = "cm-lightbox";
      dialog.className = "dialog cm-lightbox";
      dialog.innerHTML =
        `<div class="cm-lightbox-bar"><span class="cm-lightbox-name"></span>` +
        `<span><button type="button" class="btn" data-lb="prev" title="Previous image">‹</button> ` +
        `<button type="button" class="btn" data-lb="next" title="Next image">›</button> ` +
        `<a class="btn" data-lb="download" download>Download</a> ` +
        `<button type="button" class="btn" data-lb="close">Close</button></span></div>` +
        `<img class="cm-lightbox-img" alt="">`;
      document.body.appendChild(dialog);
      dialog.addEventListener("click", (event) => {
        if (event.target === dialog) dialog.close();
      });
      return dialog;
    }

    function openLightbox(images, index) {
      const dialog = lightbox();
      let at = index;
      const paint = () => {
        const image = images[at];
        dialog.querySelector(".cm-lightbox-img").src = image.url;
        dialog.querySelector(".cm-lightbox-name").textContent = `${image.filename} (${at + 1}/${images.length})`;
        const link = dialog.querySelector('[data-lb="download"]');
        link.href = image.url;
        link.download = image.filename;
        dialog.querySelectorAll('[data-lb="prev"],[data-lb="next"]').forEach((b) => (b.hidden = images.length < 2));
      };
      dialog.onclick = (event) => {
        const action = event.target.closest?.("[data-lb]")?.getAttribute("data-lb");
        if (action === "close" || event.target === dialog) dialog.close();
        else if (action === "prev") {
          at = (at + images.length - 1) % images.length;
          paint();
        } else if (action === "next") {
          at = (at + 1) % images.length;
          paint();
        }
      };
      paint();
      dialog.showModal();
    }

    // ------------------------------------------------------------------ composer
    /**
     * A comment box: textarea with @mention list, image chips, Attach image. Used for a new
     * comment, a reply and an edit. `images` are the images an edited comment already has.
     */
    function composer(cfg) {
      const root = document.createElement("div");
      root.className = "cm-composer";
      root.innerHTML =
        `<div class="cm-input-wrap"><textarea class="cm-input" rows="${cfg.rows || 3}" maxlength="4000" ` +
        `placeholder="${esc(cfg.placeholder || "Write a comment. Type @ to mention someone; paste an image with Ctrl+V.")}"></textarea>` +
        `<div class="cm-mention-list" role="listbox" hidden></div></div>` +
        `<div class="cm-chips"></div>` +
        `<div class="cm-actions"><button type="button" class="btn cm-attach" title="Add an image (PNG, JPEG, GIF or WebP, up to 5 MB)">Attach image</button>` +
        `<input type="file" class="cm-file" accept="image/png,image/jpeg,image/gif,image/webp" multiple hidden>` +
        `<span class="small muted cm-hint"></span>` +
        `<span class="cm-actions-end">${cfg.onCancel ? `<button type="button" class="btn cm-cancel">Cancel</button> ` : ""}` +
        `<button type="button" class="btn btn-primary cm-send">${esc(cfg.submitLabel || "Comment")}</button></span></div>` +
        `<p class="error cm-error" hidden></p>`;
      const input = root.querySelector(".cm-input");
      const list = root.querySelector(".cm-mention-list");
      const chips = root.querySelector(".cm-chips");
      const fileInput = root.querySelector(".cm-file");
      const errorEl = root.querySelector(".cm-error");
      const sendButton = root.querySelector(".cm-send");
      input.value = cfg.text || "";

      // images: existing ones of an edited comment, then drafts uploaded now
      const images = (cfg.images || []).map((image) => ({ ...image, status: "ready", existing: true }));
      const removed = [];
      let uploading = 0;

      function showErr(message) {
        errorEl.hidden = !message;
        errorEl.textContent = message || "";
      }

      function paintChips() {
        chips.innerHTML = images
          .map(
            (image, index) =>
              `<span class="cm-chip is-${image.status}" data-chip="${index}">` +
              (image.thumb_url ? `<img src="${esc(image.thumb_url)}" alt="">` : `<span class="cm-chip-wait">…</span>`) +
              `<span class="cm-chip-name" title="${esc(image.filename)}">${esc(image.filename)}` +
              `${image.size ? ` · ${esc(sizeText(image.size))}` : ""}${image.status === "uploading" ? " · uploading" : ""}</span>` +
              `<button type="button" class="cm-chip-x" aria-label="Remove image" title="Remove">×</button></span>`
          )
          .join("");
        chips.querySelectorAll(".cm-chip-x").forEach((button) => {
          button.addEventListener("click", () => {
            const index = Number(button.closest("[data-chip]").getAttribute("data-chip"));
            const [gone] = images.splice(index, 1);
            if (gone?.existing) removed.push(gone.uuid);
            paintChips();
          });
        });
        root.querySelector(".cm-attach").disabled = images.length >= MAX_IMAGES;
      }

      async function addFiles(files) {
        showErr("");
        for (const file of files) {
          if (!/^image\/(png|jpeg|gif|webp)$/i.test(file.type)) {
            showErr("Only PNG, JPEG, GIF and WebP images can be attached.");
            continue;
          }
          if (file.size > MAX_BYTES) {
            showErr("An image can be at most 5 MB.");
            continue;
          }
          if (images.length >= MAX_IMAGES) {
            showErr(`A comment can have at most ${MAX_IMAGES} images.`);
            break;
          }
          const name =
            file.name && file.name !== "image.png"
              ? file.name
              : `Pasted image ${when(new Date().toISOString())}`;
          const draft = { filename: name, size: file.size, status: "uploading", uuid: "" };
          images.push(draft);
          uploading += 1;
          paintChips();
          try {
            const done = await request(
              `/api/products/${encodeURIComponent(cfg.product)}/comment-attachments?filename=${encodeURIComponent(name)}`,
              { method: "POST", headers: { "Content-Type": file.type }, body: file }
            );
            Object.assign(draft, done, { status: "ready" });
          } catch (error) {
            images.splice(images.indexOf(draft), 1);
            showErr(error.message || "The image could not be uploaded.");
          } finally {
            uploading -= 1;
            paintChips();
          }
        }
      }

      root.querySelector(".cm-attach").addEventListener("click", () => fileInput.click());
      fileInput.addEventListener("change", () => {
        void addFiles([...fileInput.files]);
        fileInput.value = "";
      });
      input.addEventListener("paste", (event) => {
        const files = [...(event.clipboardData?.items || [])]
          .filter((item) => item.kind === "file" && item.type.startsWith("image/"))
          .map((item) => item.getAsFile())
          .filter(Boolean);
        if (!files.length) return;
        event.preventDefault();
        void addFiles(files);
      });
      root.addEventListener("dragover", (event) => {
        if ([...(event.dataTransfer?.types || [])].includes("Files")) {
          event.preventDefault();
          root.classList.add("is-drop");
        }
      });
      root.addEventListener("dragleave", () => root.classList.remove("is-drop"));
      root.addEventListener("drop", (event) => {
        root.classList.remove("is-drop");
        const files = [...(event.dataTransfer?.files || [])];
        if (!files.length) return;
        event.preventDefault();
        void addFiles(files);
      });

      // ---- @mention autocomplete
      let people = [];
      let active = 0;
      let token = null; // { start, end }
      let fetchTimer = 0;
      let fetchSeq = 0;

      function closeList() {
        list.hidden = true;
        token = null;
      }

      function paintList() {
        if (!people.length) {
          closeList();
          return;
        }
        list.hidden = false;
        list.innerHTML = people
          .map(
            (person, index) =>
              `<div class="cm-mention-item${index === active ? " is-active" : ""}" role="option" data-index="${index}">` +
              `<strong>${esc(person.display_name)}</strong> <span class="muted small">${esc(person.username)}</span></div>`
          )
          .join("");
      }

      function pick(index) {
        const person = people[index];
        if (!person || !token) return;
        const before = input.value.slice(0, token.start);
        const after = input.value.slice(token.end);
        input.value = `${before}@${person.username} ${after}`;
        const caret = (before + "@" + person.username + " ").length;
        input.setSelectionRange(caret, caret);
        closeList();
        input.focus();
      }

      list.addEventListener("mousedown", (event) => {
        // mousedown (not click) so the textarea keeps focus and the caret position
        const item = event.target.closest("[data-index]");
        if (!item) return;
        event.preventDefault();
        pick(Number(item.getAttribute("data-index")));
      });

      function updateMention() {
        const caret = input.selectionStart ?? input.value.length;
        const upto = input.value.slice(0, caret);
        const found = /(^|[\s(])@([A-Za-z0-9_]*)$/.exec(upto);
        if (!found) {
          closeList();
          return;
        }
        const query = found[2];
        token = { start: caret - query.length - 1, end: caret };
        window.clearTimeout(fetchTimer);
        const seq = ++fetchSeq;
        fetchTimer = window.setTimeout(async () => {
          try {
            const rows = await request(
              `/api/products/${encodeURIComponent(cfg.product)}/mentionable?q=${encodeURIComponent(query)}`
            );
            if (seq !== fetchSeq || !token) return;
            people = rows || [];
            active = 0;
            paintList();
          } catch {
            closeList();
          }
        }, query ? 120 : 0);
      }

      input.addEventListener("input", updateMention);
      input.addEventListener("click", updateMention);
      input.addEventListener("blur", () => window.setTimeout(closeList, 150));
      input.addEventListener("keydown", (event) => {
        if (!list.hidden) {
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            active = (active + (event.key === "ArrowDown" ? 1 : people.length - 1)) % people.length;
            paintList();
            return;
          }
          if (event.key === "Enter" || event.key === "Tab") {
            event.preventDefault();
            pick(active);
            return;
          }
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            closeList();
            return;
          }
        }
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
          event.preventDefault();
          void send();
        }
      });

      async function send() {
        if (sendButton.disabled) return;
        showErr("");
        if (uploading > 0) {
          showErr("Wait for the image to finish uploading.");
          return;
        }
        const text = input.value.trim();
        const fresh = images.filter((image) => !image.existing).map((image) => image.uuid);
        if (!text && !images.length) {
          showErr("Write something first.");
          return;
        }
        sendButton.disabled = true;
        try {
          await cfg.onSubmit({ text, attachment_uuids: fresh, remove_attachment_uuids: removed });
          input.value = "";
          images.length = 0;
          removed.length = 0;
          paintChips();
        } catch (error) {
          showErr(error.message || "The comment could not be saved.");
        } finally {
          sendButton.disabled = false;
        }
      }

      sendButton.addEventListener("click", () => void send());
      root.querySelector(".cm-cancel")?.addEventListener("click", () => cfg.onCancel());
      paintChips();
      root.focusInput = () => input.focus();
      return root;
    }

    // ------------------------------------------------------------------ discussion
    /**
     * cfg: { product, targetType, target, feed, filter, onChange(summary) }.
     * `feed` shows every thread of the product (grouped by what they are about) with filters.
     */
    function mount(host, cfg) {
      const state = {
        filter: cfg.feed ? "open" : "open",
        threads: [],
        replyTo: "",
        editing: "",
        resolving: "",
      };
      host.classList.add("cm-host");
      host.textContent = "";
      const bar = document.createElement("div");
      bar.className = "cm-bar";
      const composerHost = document.createElement("div");
      composerHost.className = "cm-new";
      const listEl = document.createElement("div");
      listEl.className = "cm-threads";
      const errorEl = document.createElement("p");
      errorEl.className = "error";
      errorEl.hidden = true;
      host.append(errorEl, bar, composerHost, listEl);

      const FILTERS = [
        ["open", "Open"],
        ["mentions", "Mentions me"],
        ["mine", "Mine"],
        ["resolved", "Resolved"],
      ];
      bar.innerHTML = FILTERS.map(
        ([key, label]) => `<button type="button" class="cm-filter${key === state.filter ? " is-active" : ""}" data-filter="${key}">${label}</button>`
      ).join("");
      bar.addEventListener("click", (event) => {
        const button = event.target.closest("[data-filter]");
        if (!button) return;
        state.filter = button.getAttribute("data-filter");
        bar.querySelectorAll(".cm-filter").forEach((b) => b.classList.toggle("is-active", b === button));
        void reload();
      });

      function fail(error) {
        errorEl.hidden = !error;
        errorEl.textContent = error ? error.message || String(error) : "";
      }

      function query() {
        const params = new URLSearchParams({ filter: state.filter });
        if (!cfg.feed) {
          params.set("target_type", cfg.targetType);
          params.set("target", cfg.target);
        }
        return params.toString();
      }

      async function reload() {
        try {
          state.threads = await request(`/api/products/${encodeURIComponent(cfg.product)}/comments?${query()}`);
          fail(null);
          paint();
          cfg.onChange?.();
        } catch (error) {
          fail(error);
        }
      }

      async function post(payload) {
        const result = await request(`/api/products/${encodeURIComponent(cfg.product)}/comments`, json("POST", payload));
        if (result?.not_notified?.length) {
          fail(new Error(`Not notified (no access or no such user): ${result.not_notified.map((n) => "@" + n).join(", ")}`));
        } else fail(null);
        await reload();
      }

      function targetFor() {
        return cfg.feed
          ? { target_type: "PRODUCT", target: cfg.product }
          : { target_type: cfg.targetType, target: cfg.target };
      }

      function whereLink(comment) {
        const p = encodeURIComponent(cfg.product);
        const t = `&thread=${encodeURIComponent(comment.uuid)}`;
        const name = esc(comment.target_name || "Product");
        if (comment.target_type === "OBJECT") return `<a href="/products/${p}/objects/${encodeURIComponent(comment.target_uuid)}?tab=discussion${t}">${name}</a>`;
        if (comment.target_type === "BASELINE") return `<a href="/?product=${p}&tab=baselines&baseline=${encodeURIComponent(comment.target_uuid)}&discussion=1${t}">Baseline ${name}</a>`;
        return `<span>${name}</span>`;
      }

      function commentHtml(comment, isReply) {
        if (comment.deleted) {
          return `<div class="cm-comment is-deleted" data-comment="${comment.uuid}"><span class="muted small">This comment was deleted.</span></div>`;
        }
        const tools = [];
        if (comment.can_edit && canAdd) tools.push(`<button type="button" class="cm-link" data-act="edit">Edit</button>`);
        if (comment.can_delete) tools.push(`<button type="button" class="cm-link" data-act="delete">Delete</button>`);
        const images = (comment.images || [])
          .map(
            (image, index) =>
              `<a class="cm-thumb" href="${esc(image.url)}" data-image="${index}" title="${esc(image.filename)}"><img src="${esc(image.thumb_url)}" alt="${esc(image.filename)}" loading="lazy"></a>`
          )
          .join("");
        const editing = state.editing === comment.uuid;
        return (
          `<div class="cm-comment${isReply ? " is-reply" : ""}" data-comment="${comment.uuid}">` +
          `<div class="cm-head"><strong>${esc(comment.author_display)}</strong> ` +
          `<span class="muted small" title="${esc(whenPretty(comment.created_at))}">${esc(when(comment.created_at))}</span>` +
          `${comment.edited_at ? ` <span class="muted small" title="${esc(whenPretty(comment.edited_at))}">· edited</span>` : ""}` +
          `${comment.version_display && !isReply ? ` <span class="muted small">· on ${esc(comment.version_display)}</span>` : ""}</div>` +
          (editing ? `<div class="cm-edit-host"></div>` : `<div class="cm-body">${bodyHtml(comment)}</div><div class="cm-images">${images}</div>`) +
          (tools.length && !editing ? `<div class="cm-tools small">${tools.join(" · ")}</div>` : "") +
          `</div>`
        );
      }

      function threadHtml(thread) {
        const resolved = thread.resolved;
        const live = [thread, ...(thread.replies || [])].filter((c) => !c.deleted);
        const mentionsMe = false;
        void mentionsMe;
        const status = resolved
          ? `<div class="cm-resolved small">Resolved by <strong>${esc(thread.resolved_by)}</strong> ` +
            `<span title="${esc(whenPretty(thread.resolved_at))}">${esc(when(thread.resolved_at))}</span>` +
            `${thread.resolved_in_version ? ` · at ${esc(thread.resolved_in_version)}` : ""}` +
            `${thread.resolution_note ? ` — ${esc(thread.resolution_note)}` : ""}</div>`
          : "";
        const actions = [];
        // Replying to a thread only you have written adds nothing (edit it instead): Reply appears
        // once someone else is in the conversation. can_edit is true only for your own comments.
        const othersTalked = live.some((c) => !c.can_edit);
        if (!thread.deleted && canAdd && othersTalked) {
          actions.push(`<button type="button" class="cm-link" data-act="reply">Reply</button>`);
        }
        if (thread.can_resolve && !thread.deleted) {
          actions.push(
            resolved
              ? `<button type="button" class="cm-link" data-act="reopen">Reopen</button>`
              : `<button type="button" class="cm-link" data-act="resolve">Resolve</button>`
          );
        }
        return (
          `<article class="cm-thread${resolved ? " is-resolved" : ""}" data-thread="${thread.uuid}" id="cm-${thread.uuid}">` +
          (cfg.feed ? `<div class="cm-where small">${whereLink(thread)}${thread.version_display ? ` ${esc(thread.version_display)}` : ""}</div>` : "") +
          commentHtml(thread, false) +
          (thread.replies || []).map((reply) => commentHtml(reply, true)).join("") +
          status +
          (live.length ? `<div class="cm-thread-actions small">${actions.join(" · ")}</div>` : "") +
          `<div class="cm-inline" hidden></div></article>`
        );
      }

      function allComments() {
        const map = new Map();
        for (const thread of state.threads) {
          map.set(thread.uuid, thread);
          for (const reply of thread.replies || []) map.set(reply.uuid, reply);
        }
        return map;
      }

      function paint() {
        listEl.innerHTML = state.threads.length
          ? state.threads.map(threadHtml).join("")
          : `<p class="muted cm-empty">${
              state.filter === "open" ? "No open comments yet." : "Nothing matches this filter."
            }</p>`;
        const map = allComments();
        // edit boxes
        listEl.querySelectorAll(".cm-edit-host").forEach((hostEl) => {
          const id = hostEl.closest("[data-comment]").getAttribute("data-comment");
          const comment = map.get(id);
          const box = composer({
            product: cfg.product,
            text: comment.body,
            images: comment.images,
            submitLabel: "Save",
            rows: 3,
            onCancel: () => {
              state.editing = "";
              paint();
            },
            onSubmit: async (value) => {
              await request(`/api/comments/${id}`, json("PATCH", {
                body: value.text,
                add_attachment_uuids: value.attachment_uuids,
                remove_attachment_uuids: value.remove_attachment_uuids,
              }));
              state.editing = "";
              await reload();
            },
          });
          hostEl.appendChild(box);
          box.focusInput();
        });
        // a deep link (?thread=) scrolls to and marks its thread
        const wanted = new URLSearchParams(window.location.search).get("thread");
        if (wanted && !host.__scrolled) {
          const el = listEl.querySelector(`[data-thread="${CSS.escape(wanted)}"]`);
          if (el) {
            host.__scrolled = true;
            el.classList.add("is-target");
            el.scrollIntoView({ block: "center" });
          }
        }
      }

      listEl.addEventListener("click", async (event) => {
        const thumb = event.target.closest(".cm-thumb");
        const commentEl = event.target.closest("[data-comment]");
        if (thumb && commentEl) {
          event.preventDefault();
          const comment = allComments().get(commentEl.getAttribute("data-comment"));
          openLightbox(comment.images, Number(thumb.getAttribute("data-image")));
          return;
        }
        const button = event.target.closest("[data-act]");
        if (!button) return;
        const act = button.getAttribute("data-act");
        const threadEl = button.closest("[data-thread]");
        const threadId = threadEl.getAttribute("data-thread");
        const inline = threadEl.querySelector(".cm-inline");
        try {
          if (act === "edit") {
            state.editing = commentEl.getAttribute("data-comment");
            paint();
          } else if (act === "delete") {
            if (!window.confirm("Delete this comment? Its images are removed too.")) return;
            await request(`/api/comments/${commentEl.getAttribute("data-comment")}`, { method: "DELETE" });
            await reload();
          } else if (act === "reply") {
            inline.hidden = false;
            inline.textContent = "";
            const box = composer({
              product: cfg.product,
              rows: 2,
              submitLabel: "Reply",
              placeholder: "Write a reply. Type @ to mention someone.",
              onCancel: () => {
                inline.hidden = true;
                inline.textContent = "";
              },
              onSubmit: (value) => post({ parent: threadId, body: value.text, attachment_uuids: value.attachment_uuids }),
            });
            inline.appendChild(box);
            box.focusInput();
          } else if (act === "resolve") {
            inline.hidden = false;
            inline.innerHTML =
              `<input type="text" class="cm-note" maxlength="500" placeholder="Optional note, for example: Done in B.1"> ` +
              `<button type="button" class="btn btn-primary" data-do="resolve">Resolve</button> ` +
              `<button type="button" class="btn" data-do="cancel">Cancel</button>`;
            const note = inline.querySelector(".cm-note");
            note.focus();
            inline.onclick = async (ev) => {
              const what = ev.target.closest("[data-do]")?.getAttribute("data-do");
              if (what === "cancel") {
                inline.hidden = true;
                return;
              }
              if (what === "resolve") {
                try {
                  await request(`/api/comments/${threadId}/resolve`, json("POST", { note: note.value }));
                  await reload();
                } catch (error) {
                  fail(error);
                }
              }
            };
            note.onkeydown = (ev) => {
              if (ev.key === "Enter") inline.querySelector('[data-do="resolve"]').click();
              if (ev.key === "Escape") inline.hidden = true;
            };
          } else if (act === "reopen") {
            await request(`/api/comments/${threadId}/reopen`, { method: "POST" });
            await reload();
          }
        } catch (error) {
          fail(error);
        }
      });

      if (canAdd) {
        composerHost.appendChild(
          composer({
            product: cfg.product,
            rows: 3,
            submitLabel: "Comment",
            onSubmit: (value) =>
              post({ ...targetFor(), body: value.text, attachment_uuids: value.attachment_uuids }),
          })
        );
      }
      void reload();
      // "Comment…" from a right-click lands here ready to type.
      if (new URLSearchParams(window.location.search).get("compose") === "1") {
        composerHost.querySelector(".cm-input")?.focus();
      }
      return { reload };
    }

    /** A Discussion tab panel: its data-* attributes say what it is about. */
    function mountPanel(panel) {
      if (!panel) return;
      if (!panel.__cmMounted) {
        const countLabel = () => void refreshCounts();
        panel.__cmMounted = mount(panel.querySelector(".cm-panel-host") || panel, {
          product: panel.dataset.product,
          targetType: panel.dataset.targetType || "PRODUCT",
          target: panel.dataset.target || panel.dataset.product,
          feed: panel.dataset.feed === "1",
          onChange: countLabel,
        });
      } else {
        void panel.__cmMounted.reload();
      }
    }

    // ------------------------------------------------------------------ counts and glyphs
    // The summary, the tab / pill counts and the glyphs are painted by notifications.js (always on,
    // so a quiet Files page does not have to load this module); this module only asks it to refresh.
    function productUuid() {
      return (
        $("#panel-discussion")?.dataset.product ||
        $("#metric-filters")?.dataset.product ||
        shell.currentProductId?.() ||
        ""
      );
    }

    async function refreshCounts() {
      await window.__creopdmModules.notifications?.refreshCounts?.();
    }

    /** Baseline discussion: a dialog on the baseline view. */
    function openBaselineDiscussion(baselineUuid, name) {
      const dialog = $("#baseline-discussion-dialog");
      const host = $("#baseline-discussion-host");
      if (!dialog || !host) return;
      const title = $("#baseline-discussion-title");
      if (title) title.textContent = name ? `Discussion: ${name}` : "Discussion";
      mount(host, {
        product: productUuid(),
        targetType: "BASELINE",
        target: baselineUuid,
        feed: false,
        onChange: () => void refreshCounts(),
      });
      if (!dialog.open) dialog.showModal();
    }

    $("#baseline-discussion-close")?.addEventListener("click", () => $("#baseline-discussion-dialog")?.close());

    mod.mount = mount;
    mod.mountPanel = mountPanel;
    mod.refreshCounts = refreshCounts;
    mod.openBaselineDiscussion = openBaselineDiscussion;
  },
};
