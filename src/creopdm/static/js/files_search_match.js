/**
 * Shared Files / navigator search matching — wildcards, ^/$, type labels.
 * Loaded by base.html (Files) and embed_explorer.html (Creo navigator).
 * Server product-wide Search uses the same rules via search_query.py (SQL ILIKE).
 * Do not fork matching logic in app.js or embed_explorer.js.
 */
(function (global) {
  "use strict";

  function parseSearchAnchors(query) {
    var q = String(query || "").trim();
    var anchoredStart = q.charAt(0) === "^";
    if (anchoredStart) q = q.slice(1);
    var anchoredEnd = q.charAt(q.length - 1) === "$";
    if (anchoredEnd) q = q.slice(0, -1);
    return { body: q, anchoredStart: anchoredStart, anchoredEnd: anchoredEnd };
  }

  function globToRegExp(pattern) {
    var body = String(pattern || "")
      .replace(/[.+^${}()|[\]\\]/g, "\\$&")
      .replace(/\*/g, ".*")
      .replace(/\?/g, ".");
    return new RegExp("^" + body + "$", "i");
  }

  /**
   * Match a query against plain fields (navigator objects / API rows).
   * @param {{name?:string, path?:string, typeLabel?:string, objectType?:string, haystack?:string}} fields
   * @param {string} query
   */
  function fieldsMatchSearchQuery(fields, query) {
    var raw = String(query || "").trim();
    if (!raw) return true;
    var parsed = parseSearchAnchors(raw);
    var body = parsed.body;
    var anchoredStart = parsed.anchoredStart;
    var anchoredEnd = parsed.anchoredEnd;
    if (!body) return true;

    var name = String((fields && fields.name) || "");
    var path = String((fields && fields.path) || "").replace(/\\/g, "/");
    var base = path.split("/").pop() || "";
    var typeLabel = String((fields && fields.typeLabel) || "");
    var objectType = String((fields && fields.objectType) || "");

    if (body.indexOf("*") !== -1 || body.indexOf("?") !== -1) {
      var re;
      try {
        re = globToRegExp(body);
      } catch (err) {
        return false;
      }
      return (
        re.test(name) ||
        re.test(path) ||
        (base && re.test(base)) ||
        (typeLabel && re.test(typeLabel)) ||
        (objectType && re.test(objectType))
      );
    }

    var needle = body.toLowerCase();
    var fieldsList = [name, path, base, typeLabel, objectType]
      .filter(Boolean)
      .map(function (item) {
        return item.toLowerCase();
      });
    if (anchoredStart || anchoredEnd) {
      return fieldsList.some(function (text) {
        if (anchoredStart && anchoredEnd) return text === needle;
        if (anchoredStart) return text.indexOf(needle) === 0;
        return text.length >= needle.length && text.slice(-needle.length) === needle;
      });
    }
    if (
      fieldsList.some(function (text) {
        return text.indexOf(needle) !== -1;
      })
    ) {
      return true;
    }
    var hay = String((fields && fields.haystack) || "").toLowerCase();
    return Boolean(hay) && hay.indexOf(needle) !== -1;
  }

  function rowAttr(row, name) {
    if (!row || typeof row.getAttribute !== "function") return "";
    return String(row.getAttribute(name) || "").trim();
  }

  /**
   * Files list row matcher — extracts fields from a table row DOM node.
   * Type column label comes from data-sort-type ("folder/TYPE").
   */
  function rowMatchesSearchQuery(row, query) {
    if (!row) return !String(query || "").trim();
    var named = rowAttr(row, "data-filename") || rowAttr(row, "data-sort-name");
    var name = named
      ? named.replace(/\\/g, "/").split("/").pop() || named
      : "";
    if (!name) {
      var openEl = row.querySelector ? row.querySelector(".object-open") : null;
      name = openEl && openEl.textContent ? String(openEl.textContent) : "";
    }
    var path = String(
      rowAttr(row, "data-relative-path") || rowAttr(row, "data-folder") || ""
    ).replace(/\\/g, "/");
    var sortType = rowAttr(row, "data-sort-type");
    var typeLabel =
      sortType.indexOf("/") !== -1 ? sortType.split("/").pop() || "" : sortType;
    var objectType = rowAttr(row, "data-object-type");
    return fieldsMatchSearchQuery(
      {
        name: name,
        path: path,
        typeLabel: typeLabel,
        objectType: objectType,
        haystack: row.textContent || "",
      },
      query
    );
  }

  /**
   * Navigator / API object matcher — same rules as Files list filtering.
   */
  function objectMatchesSearchQuery(obj, query) {
    if (!obj) return !String(query || "").trim();
    var name = String(obj.filename || obj.name || "");
    var path = String(obj.relative_path || "").replace(/\\/g, "/");
    var typeLabel = String(obj.type_label || "");
    var objectType = String(obj.object_type || "");
    var haystack = [
      name,
      path,
      typeLabel,
      objectType,
      obj.revision,
      obj.lifecycle_state,
      obj.checkout_status,
      obj.number,
    ]
      .filter(Boolean)
      .join(" ");
    return fieldsMatchSearchQuery(
      {
        name: name,
        path: path,
        typeLabel: typeLabel,
        objectType: objectType,
        haystack: haystack,
      },
      query
    );
  }

  global.CreoPdmFilesSearchMatch = {
    parseSearchAnchors: parseSearchAnchors,
    globToRegExp: globToRegExp,
    fieldsMatchSearchQuery: fieldsMatchSearchQuery,
    rowMatchesSearchQuery: rowMatchesSearchQuery,
    objectMatchesSearchQuery: objectMatchesSearchQuery,
  };
})(typeof window !== "undefined" ? window : globalThis);
