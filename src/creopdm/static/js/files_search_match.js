/**
 * Shared Files / navigator search matching — field terms, wildcards, ^/$.
 * Loaded by base.html (Files) and embed_explorer.html (Creo navigator).
 * Server product-wide Search uses the same grammar via utils/search_query.py.
 * Do not fork matching logic in app.js or embed_explorer.js.
 *
 * Terms are separated by spaces and ALL must match; double quotes keep spaces (name="my part").
 *   plain text      substring of the file name, number, path, Type label or Subtype label
 *   field=value     exact (case-insensitive); * and ? make a partial match: type=bulk, name=*shaft*
 *   fields          name number path type subtype model state rev creo, and param.NAME=VALUE
 */
(function (global) {
  "use strict";

  var SEARCH_FIELDS = ["name", "number", "path", "type", "subtype", "model", "state", "rev", "creo"];
  var PARAM_PREFIX = "param.";

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

  /** Split on spaces; double quotes keep spaces inside a term (the quotes themselves are dropped). */
  function splitSearchTerms(text) {
    var terms = [];
    var current = "";
    var quoted = false;
    var started = false;
    var s = String(text || "");
    for (var i = 0; i < s.length; i += 1) {
      var ch = s.charAt(i);
      if (ch === '"') {
        quoted = !quoted;
        started = true;
        continue;
      }
      if (/\s/.test(ch) && !quoted) {
        if (started) terms.push(current);
        current = "";
        started = false;
        continue;
      }
      current += ch;
      started = true;
    }
    if (started) terms.push(current);
    return terms.filter(function (term) {
      return term !== "";
    });
  }

  /** Terms of a search box text: {field, value, paramName}; field is null for plain text. */
  function parseSearchQuery(text) {
    var terms = [];
    splitSearchTerms(text).forEach(function (token) {
      var index = token.indexOf("=");
      if (index > 0) {
        var rawField = token.slice(0, index).trim();
        var field = rawField.toLowerCase();
        var value = token.slice(index + 1).trim();
        if (SEARCH_FIELDS.indexOf(field) !== -1) {
          if (value) terms.push({ field: field, value: value, paramName: "" });
          return;
        }
        if (field.indexOf(PARAM_PREFIX) === 0 && field.length > PARAM_PREFIX.length) {
          if (value) {
            terms.push({ field: "param", value: value, paramName: rawField.slice(PARAM_PREFIX.length) });
          }
          return;
        }
      }
      terms.push({ field: null, value: token, paramName: "" });
    });
    return terms;
  }

  /** One value against one pattern: `exact` for a field=value term, substring for plain text. */
  function textMatches(candidate, raw, exact) {
    var parsed = parseSearchAnchors(String(raw || "").trim());
    var body = parsed.body;
    if (!body) return true;
    var text = String(candidate || "");
    if (body.indexOf("*") !== -1 || body.indexOf("?") !== -1) {
      try {
        return globToRegExp(body).test(text);
      } catch (err) {
        return false;
      }
    }
    text = text.toLowerCase();
    var needle = body.toLowerCase();
    if (parsed.anchoredStart && parsed.anchoredEnd) return text === needle;
    if (parsed.anchoredStart) return text.indexOf(needle) === 0;
    if (parsed.anchoredEnd) {
      return text.length >= needle.length && text.slice(-needle.length) === needle;
    }
    return exact ? text === needle : text.indexOf(needle) !== -1;
  }

  function list(value) {
    return (Array.isArray(value) ? value : [value])
      .map(function (item) {
        return String(item == null ? "" : item);
      })
      .filter(Boolean);
  }

  /**
   * Match a query against plain fields (navigator objects / API rows / Files rows).
   * @param {{name?:string, path?:string, number?:string, typeLabel?:string, subtype?:string,
   *   model?:string, state?:string, rev?:string, creo?:string, params?:Object}} fields
   * @param {string} query
   */
  function fieldsMatchSearchQuery(fields, query) {
    var terms = parseSearchQuery(query);
    if (!terms.length) return true;
    fields = fields || {};
    var name = String(fields.name || "");
    var path = String(fields.path || "").replace(/\\/g, "/");
    var base = path.split("/").pop() || "";
    var state = String(fields.state || "");
    var rev = String(fields.rev || "");
    var byField = {
      name: list([name, base]),
      number: list(fields.number),
      path: list(path),
      type: list(fields.typeLabel),
      subtype: list(fields.subtype),
      model: list(fields.model),
      state: list([state, state.replace(/_/g, " ")]),
      rev: list([rev, rev.split(".")[0]]),
      creo: list(fields.creo),
    };
    var plain = [].concat(byField.name, byField.number, byField.path, byField.type, byField.subtype);
    return terms.every(function (term) {
      if (term.field === null) {
        return plain.some(function (item) {
          return textMatches(item, term.value, false);
        });
      }
      if (term.field === "param") {
        // The page does not carry parameters: the server (product-wide Search) decides these.
        if (!fields.params) return true;
        return Object.keys(fields.params).some(function (key) {
          return (
            textMatches(key, term.paramName, true) && textMatches(fields.params[key], term.value, true)
          );
        });
      }
      return (byField[term.field] || []).some(function (item) {
        return textMatches(item, term.value, true);
      });
    });
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
    return fieldsMatchSearchQuery(
      {
        name: name,
        path: path,
        number: rowAttr(row, "data-number"),
        typeLabel: typeLabel,
        subtype: rowAttr(row, "data-subtype"),
        model: rowAttr(row, "data-model"),
        state: rowAttr(row, "data-lifecycle"),
        rev: rowAttr(row, "data-rev"),
        creo: rowAttr(row, "data-creo"),
      },
      query
    );
  }

  /**
   * Navigator / API object matcher — same rules as Files list filtering.
   */
  function objectMatchesSearchQuery(obj, query) {
    if (!obj) return !String(query || "").trim();
    return fieldsMatchSearchQuery(
      {
        name: String(obj.filename || obj.name || ""),
        path: String(obj.relative_path || "").replace(/\\/g, "/"),
        number: String(obj.number || ""),
        typeLabel: String(obj.type_label || ""),
        subtype: String(obj.model_role || ""),
        model: String(obj.model_type || ""),
        state: String(obj.lifecycle_state || ""),
        rev: String(obj.display_revision || obj.revision || ""),
        creo: String(obj.creo_release || ""),
      },
      query
    );
  }

  global.CreoPdmFilesSearchMatch = {
    parseSearchAnchors: parseSearchAnchors,
    globToRegExp: globToRegExp,
    splitSearchTerms: splitSearchTerms,
    parseSearchQuery: parseSearchQuery,
    textMatches: textMatches,
    fieldsMatchSearchQuery: fieldsMatchSearchQuery,
    rowMatchesSearchQuery: rowMatchesSearchQuery,
    objectMatchesSearchQuery: objectMatchesSearchQuery,
  };
})(typeof window !== "undefined" ? window : globalThis);
