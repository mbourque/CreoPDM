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
    if (
      typeof CreoJS === "undefined" ||
      typeof CreoJS.listSessionAssemblyStructure !== "function"
    ) {
      setStatus(
        "err",
        "CreoJS.listSessionAssemblyStructure is missing. Open this page in Creo's embedded browser."
      );
      return false;
    }
    return true;
  }

  function toAppComponentRow(r) {
    var row = r || {};
    return {
      name: row.name || "",
      id: row.id == null ? null : row.id,
      type: row.type || "",
      subType: row.subType || "",
      level: row.level == null ? 1 : row.level,
      status: row.status || row.Status || "",
      suppressed: !!row.suppressed,
      path: row.path || ""
    };
  }

  function toAppListPayload(result) {
    var components = (result && result.components) || [];
    var rows = [];
    for (var i = 0; i < components.length; i++) {
      rows.push(toAppComponentRow(components[i]));
    }
    return {
      ok: !!(result && result.ok),
      fileName: (result && result.fileName) || "",
      componentCount: rows.length,
      components: rows,
      tree: (result && result.tree) || []
    };
  }

  function renderTable(components) {
    rowsNode.innerHTML = "";
    var items = components || [];
    for (var i = 0; i < items.length; i++) {
      var r = toAppComponentRow(items[i]);
      var tr = document.createElement("tr");
      var lv = Number(r.level) || 1;

      var nameTd = document.createElement("td");
      nameTd.className = "comp-name";
      // Same idea as Details Structure tab: indent by depth, branch for nested rows.
      nameTd.style.paddingLeft = 0.5 + Math.max(0, lv - 1) * 1.25 + "rem";
      nameTd.textContent = (lv > 1 ? "└ " : "") + (r.name || "");
      tr.appendChild(nameTd);

      var cells = [
        r.id == null ? "" : String(r.id),
        r.type,
        r.subType || "",
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
      return "listSessionAssemblyStructure returned null/undefined (script may not have loaded).";
    }
    if (typeof result !== "object") {
      return "listSessionAssemblyStructure returned " + typeof result + ": " + String(result);
    }
    if (typeof result.then === "function" && result.ok === undefined) {
      return "Got a Promise instead of structure data (CallPromise/then misuse).";
    }
    if (result.ok === false) return result.error || "listSessionAssemblyStructure failed (ok:false).";
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
      renderTable((result && result.components) || []);
      btnCopy.disabled = false;
      return;
    }
    renderTable(result.components);
    lastPayload = toAppListPayload(result);
    setStatus("", "");
    btnCopy.disabled = false;
  }

  function listStructure() {
    if (!requireCreo()) return;
    setBusy(true);
    setStatus("", "Listing…");
    CreoJS.listSessionAssemblyStructure()
      .then(function (result) {
        if (result == null) {
          finishList({
            ok: false,
            error: "listSessionAssemblyStructure returned empty. Hard-refresh after deploy."
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
        btnCopy.disabled = false;
      });
  }

  btnList.addEventListener("click", listStructure);
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

  window.startAssemblyProbe = function () {
    if (typeof CreoJS === "undefined" || typeof CreoJS.$ADD_ON_LOAD !== "function") {
      setStatus("warn", "CreoJS not ready yet — click List structure after Creo connects.");
      return;
    }
    setStatus("ok", "Creo.JS ready. Open an assembly, then List structure.");
    CreoJS.$ADD_ON_LOAD(function () {
      setStatus("ok", "Creo.JS loaded. Open an assembly, then List structure.");
    });
  };
})();
