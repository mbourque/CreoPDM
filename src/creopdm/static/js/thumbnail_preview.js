/**
 * Hover / focus / tap preview for Creo embedded model thumbnails.
 * Lazy-fetches by content_hash or object uuid; remembers 404s.
 */
(function () {
  "use strict";

  var DELAY_MS = 250;
  var PREVIEW_WIDTH = 256;
  /** @type {Map<string, "absent"|string>} */
  var cache = new Map();
  var overlay = null;
  var img = null;
  var caption = null;
  var showTimer = null;
  var activeKey = null;
  var activeEl = null;

  function ensureOverlay() {
    if (overlay) return overlay;
    overlay = document.createElement("div");
    overlay.id = "thumb-preview";
    overlay.className = "thumb-preview";
    overlay.hidden = true;
    overlay.setAttribute("role", "img");
    overlay.style.pointerEvents = "none";
    img = document.createElement("img");
    img.alt = "";
    img.width = PREVIEW_WIDTH;
    img.decoding = "async";
    caption = document.createElement("div");
    caption.className = "thumb-preview-caption";
    overlay.appendChild(img);
    overlay.appendChild(caption);
    document.body.appendChild(overlay);
    return overlay;
  }

  function hide() {
    if (showTimer) {
      clearTimeout(showTimer);
      showTimer = null;
    }
    activeKey = null;
    activeEl = null;
    if (overlay) overlay.hidden = true;
  }

  function preferRightOfLink() {
    // Narrow panes (Creo navigator) must not flip the preview over the name —
    // that covers the link and fights double-click.
    return (
      document.body &&
      document.body.getAttribute("data-thumb-place") === "right"
    );
  }

  function overlapsRect(left, top, w, h, rect) {
    return !(
      left + w <= rect.left ||
      left >= rect.right ||
      top + h <= rect.top ||
      top >= rect.bottom
    );
  }

  function positionNear(el) {
    if (!overlay || !el) return;
    var rect = el.getBoundingClientRect();
    var margin = 8;
    var w = overlay.offsetWidth || PREVIEW_WIDTH;
    var h = overlay.offsetHeight || PREVIEW_WIDTH;
    var left = rect.right + margin;
    var top = rect.top;
    var rightOnly = preferRightOfLink();
    if (rightOnly) {
      // 1) Immediately right of the name.
      // 2) Else pin to the pane’s right edge (names are left-aligned).
      // 3) Else below / above the name — never slide up over it.
      if (left + w > window.innerWidth - margin) {
        left = window.innerWidth - w - margin;
      }
      if (left < margin) left = margin;
      if (overlapsRect(left, top, w, h, rect)) {
        left = Math.max(margin, Math.min(rect.left, window.innerWidth - w - margin));
        top = rect.bottom + margin;
        if (top + h > window.innerHeight - margin) {
          top = rect.top - h - margin;
        }
        if (top < margin || overlapsRect(left, top, w, h, rect)) {
          left = Math.max(rect.right + margin, margin);
          if (left + w > window.innerWidth - margin) {
            left = window.innerWidth - w - margin;
          }
          top = rect.bottom + margin;
          if (top + h > window.innerHeight - margin) {
            top = Math.max(margin, window.innerHeight - h - margin);
          }
          // Final guard: if still on top of the name, hide rather than cover.
          if (overlapsRect(left, top, w, h, rect)) {
            overlay.hidden = true;
            return;
          }
        }
      }
    } else {
      if (left + w > window.innerWidth - margin) {
        left = rect.left - w - margin;
      }
      if (left < margin) left = margin;
      if (top + h > window.innerHeight - margin) {
        top = window.innerHeight - h - margin;
      }
      if (top < margin) top = margin;
    }
    overlay.style.left = Math.round(left) + "px";
    overlay.style.top = Math.round(top) + "px";
  }

  function showWithUrl(el, name, url) {
    ensureOverlay();
    img.onload = function () {
      if (activeEl === el && overlay && !overlay.hidden) positionNear(el);
    };
    img.src = url;
    img.alt = name || "Model preview";
    caption.textContent = name || "";
    overlay.hidden = false;
    positionNear(el);
  }

  function objectIdFromHref(href) {
    if (!href) return "";
    var m = String(href).match(/\/objects\/([^/#?]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function cacheKey(el) {
    var hash = (el.getAttribute("data-content-hash") || "").trim().toLowerCase();
    if (hash) return "h:" + hash;
    var oid = (
      el.getAttribute("data-uuid") ||
      el.getAttribute("data-object-id") ||
      ""
    ).trim();
    if (!oid) oid = objectIdFromHref(el.getAttribute("href"));
    if (oid) return "o:" + oid;
    var row = el.closest("[data-content-hash], [data-uuid]");
    if (row) {
      hash = (row.getAttribute("data-content-hash") || "").trim().toLowerCase();
      if (hash) return "h:" + hash;
      oid = (row.getAttribute("data-uuid") || "").trim();
      if (oid) return "o:" + oid;
    }
    return "";
  }

  function displayName(el) {
    return (
      el.getAttribute("data-filename") ||
      (el.textContent || "").trim() ||
      "Model"
    );
  }

  function urlForKey(key) {
    if (key.indexOf("h:") === 0) {
      return "/api/thumbnails/" + encodeURIComponent(key.slice(2));
    }
    if (key.indexOf("o:") === 0) {
      return "/api/objects/" + encodeURIComponent(key.slice(2)) + "/thumbnail";
    }
    return "";
  }

  function fetchThumb(key) {
    var hit = cache.get(key);
    if (hit === "absent") return Promise.resolve(null);
    if (hit) return Promise.resolve(hit);
    var url = urlForKey(key);
    if (!url) {
      cache.set(key, "absent");
      return Promise.resolve(null);
    }
    return fetch(url, { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) {
          cache.set(key, "absent");
          return null;
        }
        return res.blob().then(function (blob) {
          if (!blob || !blob.size) {
            cache.set(key, "absent");
            return null;
          }
          var objectUrl = URL.createObjectURL(blob);
          cache.set(key, objectUrl);
          return objectUrl;
        });
      })
      .catch(function () {
        cache.set(key, "absent");
        return null;
      });
  }

  function looksLikeCreoModel(el) {
    var row = el.closest("[data-extension], [data-filename], [data-object-type]");
    var ext = "";
    var name = "";
    var typ = "";
    if (row) {
      ext = (row.getAttribute("data-extension") || "").toLowerCase().replace(/^\./, "");
      name = (row.getAttribute("data-filename") || "").toLowerCase();
      typ = (row.getAttribute("data-object-type") || "").toLowerCase();
    }
    if (!name) {
      name = (
        el.getAttribute("data-filename") ||
        el.textContent ||
        ""
      )
        .trim()
        .toLowerCase();
    }
    if (ext === "prt" || ext === "asm" || ext === "drw") return true;
    if (typ === "part" || typ === "assembly" || typ === "drawing") return true;
    return /\.(prt|asm|drw)(\.\d+)?$/i.test(name);
  }

  function isPreviewTarget(el) {
    if (!el || !el.closest) return null;
    var node = el.closest(
      ".object-open, .thumb-preview-target, a.bom-name, #where-used-table a[href*='/objects/']"
    );
    if (!node || !looksLikeCreoModel(node)) return null;
    if (!cacheKey(node)) return null;
    return node;
  }

  function scheduleShow(el) {
    var key = cacheKey(el);
    if (!key) return;
    if (showTimer) clearTimeout(showTimer);
    activeEl = el;
    activeKey = key;
    var name = displayName(el);
    showTimer = setTimeout(function () {
      showTimer = null;
      if (activeKey !== key) return;
      fetchThumb(key).then(function (url) {
        if (activeKey !== key || !url) return;
        showWithUrl(el, name, url);
      });
    }, DELAY_MS);
  }

  function onPointerOver(ev) {
    var target = isPreviewTarget(ev.target);
    if (!target) return;
    scheduleShow(target);
  }

  function onPointerOut(ev) {
    var target = isPreviewTarget(ev.target);
    if (!target) return;
    var related = ev.relatedTarget;
    if (related && target.contains(related)) return;
    hide();
  }

  function onFocusIn(ev) {
    var target = isPreviewTarget(ev.target);
    if (!target) return;
    scheduleShow(target);
  }

  function onFocusOut() {
    hide();
  }

  function onKeyDown(ev) {
    if (ev.key === "Escape") hide();
  }

  function onContextMenu() {
    // Files right-click menu must not sit under the hover preview.
    hide();
  }

  function onClick(ev) {
    if (!(ev.pointerType === "touch" || (!ev.pointerType && "ontouchstart" in window))) {
      return;
    }
    var target = isPreviewTarget(ev.target);
    if (!target) return;
    if (activeEl === target && overlay && !overlay.hidden) {
      hide();
      return;
    }
    ev.preventDefault();
    if (showTimer) {
      clearTimeout(showTimer);
      showTimer = null;
    }
    var key = cacheKey(target);
    var name = displayName(target);
    activeEl = target;
    activeKey = key;
    fetchThumb(key).then(function (url) {
      if (activeKey !== key || !url) return;
      showWithUrl(target, name, url);
    });
  }

  function bind() {
    document.addEventListener("pointerover", onPointerOver, true);
    document.addEventListener("pointerout", onPointerOut, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("contextmenu", onContextMenu, true);
    document.addEventListener("click", onClick, true);
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})();
