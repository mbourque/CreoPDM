(function () {
  "use strict";

  var statusNode = document.getElementById("status");
  var rowsNode = document.getElementById("rows");
  var btnList = document.getElementById("btn-list");
  var btnCopy = document.getElementById("btn-copy");
  var lastPayload = null;

  function setStatus(kind, message) {
    var text = message == null ? "" : String(message);
    if (!text) {
      statusNode.hidden = true;
      statusNode.className = "status";
      statusNode.textContent = "";
      return;
    }
    statusNode.hidden = false;
    statusNode.className = "status" + (kind ? " " + kind : "");
    statusNode.textContent = text;
  }

  function setBusy(busy) {
    btnList.disabled = busy;
    if (busy) btnCopy.disabled = true;
  }

  function requireCreo() {
    if (typeof CreoJS === "undefined" || typeof CreoJS.listSessionFeatures !== "function") {
      setStatus(
        "err",
        "CreoJS.listSessionFeatures is missing. Open this page in Creo's embedded browser."
      );
      return false;
    }
    return true;
  }

  /** Same rules as feature_probe.creojs — keep in sync. */
  function featureDisplayName(storedName, typeName, featureId) {
    var stored = String(storedName == null ? "" : storedName).trim();
    if (stored) return stored;
    var type = String(typeName == null ? "" : typeName).trim();
    var idStr = featureId == null || featureId === "" ? "" : String(featureId);
    if (type && idStr) return type + " (" + idStr + ")";
    if (type) return type;
    if (idStr) return "(" + idStr + ")";
    return "";
  }

  function featureStoredNameFromRow(row) {
    if (!row) return "";
    var candidates = [row.GetName, row.Name, row.name, row.exportFeatName];
    for (var i = 0; i < candidates.length; i++) {
      var s = String(candidates[i] == null ? "" : candidates[i]).trim();
      if (s) return s;
    }
    return "";
  }

  function applyFeatureDisplayNames(features) {
    var list = features || [];
    for (var i = 0; i < list.length; i++) {
      var row = list[i];
      if (!row) continue;
      var stored = featureStoredNameFromRow(row);
      var type = String(row.FeatTypeName || row.type || "").trim();
      row.displayName = featureDisplayName(stored, type, row.id);
    }
    return list;
  }

  function toAppFeatureRow(r) {
    var row = r || {};
    var type = row.FeatTypeName || row.type || "";
    return {
      name:
        row.displayName ||
        featureDisplayName(featureStoredNameFromRow(row), type, row.id),
      id: row.id == null ? null : row.id,
      type: type,
      subType: row.FeatSubType || row.subType || "",
      status: row.Status || row.status || "",
      suppressed: !!(row.suppressed || String(row.Status || "").toUpperCase().indexOf("SUPPRESS") >= 0),
      level: row.level == null ? 1 : row.level
    };
  }

  function toAppListPayload(result) {
    var features = (result && result.features) || [];
    var rows = [];
    for (var i = 0; i < features.length; i++) {
      rows.push(toAppFeatureRow(features[i]));
    }
    return {
      ok: !!(result && result.ok),
      fileName: (result && result.fileName) || "",
      featureCount: rows.length,
      skippedPatternMemberCount: (result && result.skippedPatternMemberCount) || 0,
      hiddenInternalCount: (result && result.hiddenInternalCount) || 0,
      features: rows
    };
  }

  function renderTable(features) {
    rowsNode.innerHTML = "";
    var items = features || [];
    for (var i = 0; i < items.length; i++) {
      var r = toAppFeatureRow(items[i]);
      var tr = document.createElement("tr");
      var lv = Number(r.level) || 1;

      var nameTd = document.createElement("td");
      nameTd.className = "feat-name";
      nameTd.style.paddingLeft = 0.5 + Math.max(0, lv - 1) * 1.25 + "rem";
      nameTd.textContent = (lv > 1 ? "└ " : "") + (r.name || "");
      tr.appendChild(nameTd);

      var cells = [
        r.id == null ? "" : String(r.id),
        r.type,
        r.subType,
        String(lv),
        r.status
      ];
      for (var c = 0; c < cells.length; c++) {
        var td = document.createElement("td");
        td.textContent = cells[c];
        tr.appendChild(td);
      }
      rowsNode.appendChild(tr);
    }
  }

  function describePayloadProblem(result) {
    if (result == null) {
      return "listSessionFeatures returned null/undefined (Creo.JS call failed or script did not load).";
    }
    if (typeof result !== "object") {
      return "listSessionFeatures returned " + typeof result + ": " + String(result);
    }
    if (typeof result.then === "function" && result.ok === undefined) {
      return "Got a Promise instead of feature data (CallPromise/then misuse).";
    }
    if (result.ok === false) return result.error || "listSessionFeatures failed (ok:false).";
    if (result.error && result.ok !== true) return String(result.error);
    if (result.ok !== true) return "Unexpected payload (no ok:true).";
    return null;
  }

  function finishList(result) {
    setBusy(false);
    var problem = describePayloadProblem(result);
    if (problem) {
      lastPayload = { ok: false, error: problem };
      setStatus("err", problem);
      renderTable((result && result.features) || []);
      btnCopy.disabled = false;
      return;
    }
    applyFeatureDisplayNames(result.features || []);
    renderTable(result.features);
    lastPayload = toAppListPayload(result);
    setStatus("", "");
    btnCopy.disabled = false;
  }

  function loadCreoTextFile(path, done) {
    if (!path) {
      done(new Error("empty path"), null);
      return;
    }
    if (typeof CreoJS.$LOAD !== "function") {
      done(new Error("CreoJS.$LOAD missing"), null);
      return;
    }
    var settled = false;
    try {
      CreoJS.$LOAD(path, function (text) {
        if (settled) return;
        settled = true;
        done(null, text == null ? "" : String(text));
      });
    } catch (err) {
      settled = true;
      done(err, null);
      return;
    }
    setTimeout(function () {
      if (settled) return;
      settled = true;
      done(new Error("$LOAD timeout: " + path), null);
    }, 20000);
  }

  function looksLikeFeatTypeLine(line) {
    var t = String(line || "").trim();
    if (!t || t.length > 48) return false;
    if (
      /^(CHILDREN|PARENTS|FEATURE\s+NUMBER|INTERNAL\s+FEATURE|NO\.|---+|FEATURES:|PART\s|MATERIAL|Units\s|Length|Mass|Force|Time|Temperature|FEATURE WAS |FEATURE IS |SUPPRESSED FEATURE)/i.test(
        t
      )
    ) {
      return false;
    }
    return /^[A-Z][A-Z0-9 /_-]*$/.test(t);
  }

  function parseInfoExportText(text, preferId) {
    var out = { typesById: {}, namesById: {} };
    if (!text) return out;
    var s = String(text).replace(/^\uFEFF/, "");
    var parts = s.split(/(?=INTERNAL\s+FEATURE\s+ID\s+\d+)/i);
    for (var b = 0; b < parts.length; b++) {
      var block = parts[b];
      if (!block || block.length < 8) continue;
      var idMatch = block.match(/INTERNAL\s+FEATURE\s+ID\s+(\d+)/i);
      if (!idMatch) continue;
      var bid = idMatch[1];
      var typeMatch = block.match(/FEATURE\s+TYPE\s*[:=]?\s*([A-Za-z][A-Za-z0-9 _-]*)/i);
      var btype = "";
      if (typeMatch) {
        btype = String(typeMatch[1] || "").trim().toUpperCase();
      } else {
        var lines = block.split(/\r?\n/);
        for (var li = 0; li < lines.length; li++) {
          if (looksLikeFeatTypeLine(lines[li])) {
            btype = String(lines[li]).trim().toUpperCase();
            break;
          }
        }
      }
      if (btype) out.typesById[bid] = btype;

      var nameMatch =
        block.match(/FEATURE\s+NAME\s*[:=]\s*([A-Za-z0-9_.-]+)/i) ||
        block.match(/^\s*\d+\s+Feature\s+Name\s+([A-Za-z0-9_.-]+)\s*$/im);
      if (nameMatch) {
        var n = String(nameMatch[1] || "").trim();
        if (n && !/^(Defined|Yes|No|True|False)$/i.test(n)) {
          out.namesById[bid] = n;
        }
      }

      if (preferId != null && String(preferId) === bid && !out.typesById[bid]) {
        // FeatInfo sometimes puts HOLE after "FEATURE WAS CREATED…"
        var holeLine = block.match(/^\s*(HOLE|CUT|ROUND|PROTRUSION|SHELL)\s*$/im);
        if (holeLine) out.typesById[bid] = String(holeLine[1]).toUpperCase();
      }
    }
    return out;
  }

  function applyParsedTypes(result, parsed) {
    if (!result || !parsed || !parsed.typesById) return;
    var features = result.features || [];
    for (var i = 0; i < features.length; i++) {
      var row = features[i];
      if (!row || row.id == null) continue;
      var t = parsed.typesById[String(row.id)];
      if (t && (row.sparse || !row.FeatTypeName)) {
        row.FeatTypeName = t;
        row.sparse = false;
      }
      var n = parsed.namesById && parsed.namesById[String(row.id)];
      if (n && !row.GetName) row.GetName = n;
    }
  }

  function loadFirstReadable(paths, done) {
    var list = [];
    for (var i = 0; i < (paths || []).length; i++) {
      if (paths[i]) list.push(paths[i]);
    }
    if (!list.length) {
      done(new Error("no readable export path"), null);
      return;
    }
    var idx = 0;
    function next(prevErr) {
      if (idx >= list.length) {
        done(prevErr || new Error("no readable export path"), null);
        return;
      }
      var path = list[idx++];
      loadCreoTextFile(path, function (err, text) {
        if (!err) {
          done(null, text);
          return;
        }
        next(err);
      });
    }
    next(null);
  }

  function enrichFromExports(result, done) {
    var info = result && result.exportInfo;
    if (!info || info.ok === false) {
      done();
      return;
    }
    var jobs = [];
    if (info.modelInfoPath || info.modelInfoFile) {
      jobs.push({ paths: [info.modelInfoPath, info.modelInfoFile] });
    }
    if (info.featFiles) {
      for (var id in info.featFiles) {
        if (!Object.prototype.hasOwnProperty.call(info.featFiles, id)) continue;
        var f = info.featFiles[id];
        jobs.push({ paths: [f && f.path, f && f.file], preferId: id });
      }
    }
    if (!jobs.length) {
      done();
      return;
    }

    setStatus("", "Reading feature types…");
    var j = 0;
    function runNext() {
      if (j >= jobs.length) {
        done();
        return;
      }
      var job = jobs[j++];
      loadFirstReadable(job.paths, function (err, text) {
        if (!err && text != null) {
          applyParsedTypes(result, parseInfoExportText(text, job.preferId));
        }
        runNext();
      });
    }
    runNext();
  }

  function afterList(result) {
    if (!result || result.ok !== true) {
      finishList(result);
      return;
    }
    if (typeof CreoJS.exportSessionInfo !== "function") {
      finishList(result);
      return;
    }
    var FEAT_INFO_CAP = 60;
    var featInfoIds = [];
    var feats = result.features || [];
    for (var fi = 0; fi < feats.length; fi++) {
      var fr = feats[fi];
      if (!fr || fr.id == null) continue;
      if (fr.sparse || !fr.FeatTypeName) featInfoIds.push(fr.id);
      if (featInfoIds.length >= FEAT_INFO_CAP) break;
    }
    setStatus("", "Reading feature types…");
    CreoJS.exportSessionInfo(featInfoIds)
      .then(function (exportInfo) {
        result.exportInfo = exportInfo || { ok: false };
        enrichFromExports(result, function () {
          finishList(result);
        });
      })
      .catch(function () {
        finishList(result);
      });
  }

  function listFeatures() {
    if (!requireCreo()) return;
    setBusy(true);
    setStatus("", "Listing…");
    // CallPromise.then does not await native Promises — never return Promise.resolve.
    CreoJS.listSessionFeatures()
      .then(function (result) {
        if (result == null) {
          finishList({
            ok: false,
            error: "listSessionFeatures returned empty. Hard-refresh after deploy."
          });
          return;
        }
        afterList(result);
      })
      .catch(function (error) {
        setBusy(false);
        lastPayload = {
          ok: false,
          error: error && error.message ? error.message : String(error)
        };
        setStatus("err", lastPayload.error);
        btnCopy.disabled = false;
      });
  }

  btnList.addEventListener("click", listFeatures);
  btnCopy.addEventListener("click", function () {
    if (!lastPayload) return;
    var text = JSON.stringify(lastPayload, null, 2);
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(
        function () {
          setStatus("ok", "JSON copied to clipboard.");
        },
        function () {
          setStatus("warn", "Clipboard blocked — could not copy JSON.");
        }
      );
    } else {
      setStatus("warn", "Clipboard API missing — could not copy JSON.");
    }
  });

  window.startFeatureProbe = function () {
    if (typeof CreoJS === "undefined" || typeof CreoJS.$ADD_ON_LOAD !== "function") {
      setStatus("warn", "CreoJS not ready yet — click List features after Creo connects.");
      return;
    }
    setStatus("ok", "Creo.JS ready. Click List features.");
    CreoJS.$ADD_ON_LOAD(function () {
      setStatus("ok", "Creo.JS loaded. Click List features.");
    });
  };
})();
