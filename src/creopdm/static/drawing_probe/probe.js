(function () {
  "use strict";

  var statusNode = document.getElementById("status");
  var metaNode = document.getElementById("meta");
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

  function setMeta(result) {
    if (!result || result.ok !== true) {
      metaNode.hidden = true;
      metaNode.textContent = "";
      return;
    }
    var bits = [];
    if (result.fileName) bits.push(result.fileName);
    if (result.sheetCount != null) bits.push(result.sheetCount + " sheet(s)");
    if (result.currentSheet != null) bits.push("current " + result.currentSheet);
    if (result.viewCount != null) bits.push(result.viewCount + " view(s)");
    if (result.noteCount != null) bits.push(result.noteCount + " note(s)");
    if (result.dimensionCount != null) bits.push(result.dimensionCount + " dim(s)");
    if (result.tableCount != null) bits.push(result.tableCount + " table(s)");
    if (result.modelCount != null) bits.push(result.modelCount + " model(s)");
    var models = result.models || [];
    if (models.length) {
      var names = [];
      for (var i = 0; i < models.length; i++) names.push(models[i].filename || "");
      bits.push("models: " + names.join(", "));
    }
    var probeNotes = result.notes || [];
    if (probeNotes.length) bits.push("notes: " + probeNotes.join("; "));
    metaNode.textContent = bits.join(" · ");
    metaNode.hidden = !bits.length;
  }

  function setBusy(busy) {
    btnList.disabled = busy;
    if (busy) btnCopy.disabled = true;
  }

  function requireCreo() {
    if (
      typeof CreoJS === "undefined" ||
      typeof CreoJS.listSessionDrawingStructure !== "function"
    ) {
      setStatus(
        "err",
        "CreoJS.listSessionDrawingStructure is missing. Open this page in Creo's embedded browser."
      );
      return false;
    }
    return true;
  }

  function toAppRow(r) {
    var row = r || {};
    return {
      name: row.name || "",
      id: row.id == null ? null : row.id,
      creoId: row.creoId == null ? null : row.creoId,
      type: row.type || "",
      subType: row.subType || "",
      sheet: row.sheet == null ? null : row.sheet,
      scale: row.scale == null ? null : row.scale,
      model: row.model || "",
      detail: row.detail || "",
      level: row.level == null ? 1 : row.level,
      status: row.status || "",
      path: row.path || ""
    };
  }

  function toAppListPayload(result) {
    var components = (result && result.components) || [];
    var rows = [];
    for (var i = 0; i < components.length; i++) rows.push(toAppRow(components[i]));
    return {
      ok: !!(result && result.ok),
      fileName: (result && result.fileName) || "",
      sheetCount: result && result.sheetCount,
      currentSheet: result && result.currentSheet,
      viewCount: result && result.viewCount,
      noteCount: result && result.noteCount,
      dimensionCount: result && result.dimensionCount,
      tableCount: result && result.tableCount,
      modelCount: result && result.modelCount,
      models: (result && result.models) || [],
      notes: (result && result.notes) || [],
      componentCount: rows.length,
      components: rows,
      tree: (result && result.tree) || []
    };
  }

  function renderTable(components) {
    rowsNode.innerHTML = "";
    var items = components || [];
    for (var i = 0; i < items.length; i++) {
      var r = toAppRow(items[i]);
      var tr = document.createElement("tr");
      var lv = Number(r.level) || 1;

      var nameTd = document.createElement("td");
      nameTd.style.paddingLeft = 0.5 + Math.max(0, lv - 1) * 1.25 + "rem";
      nameTd.textContent = (lv > 1 ? "└ " : "") + (r.name || "");
      tr.appendChild(nameTd);

      var cells = [
        r.type,
        r.subType,
        r.creoId != null ? String(r.creoId) : r.id == null ? "" : String(r.id),
        r.sheet == null ? "" : String(r.sheet),
        r.scale == null ? "" : String(r.scale),
        r.model,
        r.detail,
        String(lv),
        r.status
      ];
      for (var c = 0; c < cells.length; c++) {
        var td = document.createElement("td");
        if (c === 6) td.className = "detail";
        td.textContent = cells[c];
        tr.appendChild(td);
      }
      rowsNode.appendChild(tr);
    }
  }

  function describePayloadProblem(result) {
    if (result == null) {
      return "listSessionDrawingStructure returned null/undefined (script may not have loaded).";
    }
    if (typeof result !== "object") {
      return "listSessionDrawingStructure returned " + typeof result + ": " + String(result);
    }
    if (typeof result.then === "function" && result.ok === undefined) {
      return "Got a Promise instead of drawing data (CallPromise/then misuse).";
    }
    if (result.ok === false) return result.error || "listSessionDrawingStructure failed (ok:false).";
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
      setMeta(null);
      renderTable((result && result.components) || []);
      btnCopy.disabled = false;
      return;
    }
    renderTable(result.components);
    lastPayload = toAppListPayload(result);
    setMeta(result);
    setStatus("", "");
    btnCopy.disabled = false;
  }

  function listDrawing() {
    if (!requireCreo()) return;
    setBusy(true);
    setStatus("", "Listing…");
    CreoJS.listSessionDrawingStructure()
      .then(function (result) {
        if (result == null) {
          finishList({
            ok: false,
            error: "listSessionDrawingStructure returned empty. Hard-refresh after deploy."
          });
          return;
        }
        finishList(result);
      })
      .catch(function (error) {
        setBusy(false);
        lastPayload = {
          ok: false,
          error: error && error.message ? error.message : String(error)
        };
        setStatus("err", lastPayload.error);
        setMeta(null);
        btnCopy.disabled = false;
      });
  }

  btnList.addEventListener("click", listDrawing);
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

  window.startDrawingProbe = function () {
    if (typeof CreoJS === "undefined" || typeof CreoJS.$ADD_ON_LOAD !== "function") {
      setStatus("warn", "CreoJS not ready yet — click List drawing after Creo connects.");
      return;
    }
    setStatus("ok", "Creo.JS ready. Open a drawing, then List drawing.");
    CreoJS.$ADD_ON_LOAD(function () {
      setStatus("ok", "Creo.JS loaded. Open a drawing, then List drawing.");
    });
  };
})();
