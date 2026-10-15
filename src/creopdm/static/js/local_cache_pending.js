/**
 * Shared local-workspace → Modified / pending check-in detection.
 * Used by Files (app.js) and the Creo navigator embed — keep one algorithm.
 */
(function (global) {
  "use strict";

  var DEFAULT_PURGEABLE = [
    ".asm", ".dat", ".drw", ".err", ".frm", ".gph", ".inf", ".lsl", ".lst",
    ".mat", ".mrd", ".ncl", ".neu", ".prt", ".sec", ".sym", ".tbl", ".tph",
    ".txt", ".xml",
  ];

  function pathBasename(value) {
    var text = String(value || "").replace(/\\/g, "/");
    var parts = text.split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : text;
  }

  function purgeableSet(fromDom) {
    var raw = String(fromDom || "").trim();
    var list = raw
      ? raw
          .split(/[\s,;]+/)
          .map(function (item) {
            return item.trim().toLowerCase();
          })
          .filter(Boolean)
          .map(function (item) {
            return item.charAt(0) === "." ? item : "." + item;
          })
      : DEFAULT_PURGEABLE.slice();
    var set = Object.create(null);
    list.forEach(function (ext) {
      set[ext] = true;
    });
    return set;
  }

  function isPurgeable(extension, purgeable) {
    var key = String(extension || "").trim().toLowerCase();
    if (!key) return false;
    var dotted = key.charAt(0) === "." ? key : "." + key;
    return Boolean(purgeable[dotted]);
  }

  function logicalUploadName(name, purgeable) {
    var text = pathBasename(name);
    var parts = text.split(".");
    if (parts.length >= 3 && parts[0]) {
      var last = parts[parts.length - 1];
      var prev = parts[parts.length - 2];
      if (/^\d+$/.test(last) && isPurgeable("." + prev, purgeable)) {
        return parts.slice(0, -1).join(".");
      }
      if (/^\d+$/.test(prev) && isPurgeable("." + last, purgeable)) {
        return parts.slice(0, -2).concat([last]).join(".");
      }
    }
    return text;
  }

  function creoSaveNumber(filename, purgeable) {
    var name = pathBasename(filename);
    var parts = name.split(".");
    if (parts.length < 3 || !parts[0]) return 0;
    var last = parts[parts.length - 1];
    var prev = parts[parts.length - 2];
    if (/^\d+$/.test(last) && isPurgeable("." + prev, purgeable)) {
      return Number.parseInt(last, 10) || 0;
    }
    if (/^\d+$/.test(prev) && isPurgeable("." + last, purgeable)) {
      return Number.parseInt(prev, 10) || 0;
    }
    return 0;
  }

  function logicalRelativePath(rel, purgeable) {
    var norm = String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
    var parts = norm.split("/").filter(Boolean);
    var name = parts.pop() || "";
    var logical = logicalUploadName(name, purgeable);
    return parts.length ? parts.join("/") + "/" + logical : logical;
  }

  function agentCacheSafeSegment(value) {
    var text = String(value || "").trim().replace(/[^A-Za-z0-9._\-]+/g, "_");
    return (text || "x").slice(0, 180);
  }

  function agentCacheSafeRelativePath(rel) {
    var norm = String(rel || "").replace(/\\/g, "/").replace(/^\/+/, "");
    var parts = norm.split("/").filter(function (part) {
      return part && part !== "." && part !== "..";
    });
    if (!parts.length) return "";
    return parts.map(agentCacheSafeSegment).join("/");
  }

  function indexLocalCacheTipsByLogical(cacheFiles, purgeable) {
    /** Highest Creo .N per logical path (and unique basename) from agent /files. */
    var bestByLogical = Object.create(null);
    var bestByBasename = Object.create(null);
    (cacheFiles || []).forEach(function (item) {
      var rel = String(item.relative_path || "").replace(/\\/g, "/");
      if (!rel) return;
      var key = logicalRelativePath(rel, purgeable).toLowerCase();
      var filename = item.filename || pathBasename(rel);
      var saveNumber = creoSaveNumber(filename, purgeable);
      var base = logicalUploadName(filename, purgeable).toLowerCase();
      var entry = { item: item, rel: rel, filename: filename, saveNumber: saveNumber };
      var prev = bestByLogical[key];
      if (!prev || saveNumber > prev.saveNumber) {
        bestByLogical[key] = entry;
      }
      var safeKey = logicalRelativePath(agentCacheSafeRelativePath(rel), purgeable).toLowerCase();
      if (safeKey && safeKey !== key) {
        var prevSafe = bestByLogical[safeKey];
        if (!prevSafe || saveNumber > prevSafe.saveNumber) {
          bestByLogical[safeKey] = entry;
        }
      }
      var prevBase = bestByBasename[base];
      var flatter =
        prevBase &&
        saveNumber === prevBase.saveNumber &&
        rel.split("/").length < prevBase.rel.split("/").length;
      if (!prevBase || saveNumber > prevBase.saveNumber || flatter) {
        bestByBasename[base] = entry;
      }
    });
    return { bestByLogical: bestByLogical, bestByBasename: bestByBasename };
  }

  function planNewerLocalCacheSaves(cacheFiles, objects, purgeable) {
    // Prefer full vault-relative path. Older flat agent caches (basename only)
    // still match when that basename is unique in the product.
    var indexed = indexLocalCacheTipsByLogical(cacheFiles, purgeable);
    var bestByLogical = indexed.bestByLogical;
    var bestByBasename = indexed.bestByBasename;
    var vaultBasenameCounts = Object.create(null);
    (Array.isArray(objects) ? objects : []).forEach(function (obj) {
      var vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      if (!vaultRel) return;
      var base = logicalUploadName(pathBasename(vaultRel), purgeable).toLowerCase();
      vaultBasenameCounts[base] = (vaultBasenameCounts[base] || 0) + 1;
    });
    var needsHash = [];
    (Array.isArray(objects) ? objects : []).forEach(function (obj) {
      var vaultRel = String(obj.relative_path || obj.filename || "").replace(/\\/g, "/");
      if (!vaultRel) return;
      var key = logicalRelativePath(vaultRel, purgeable).toLowerCase();
      var safeKey = logicalRelativePath(
        agentCacheSafeRelativePath(vaultRel),
        purgeable
      ).toLowerCase();
      var local = bestByLogical[key] || bestByLogical[safeKey];
      if (!local) {
        var base = logicalUploadName(pathBasename(vaultRel), purgeable).toLowerCase();
        if ((vaultBasenameCounts[base] || 0) === 1) {
          local = bestByBasename[base];
        }
      }
      if (!local) return;
      var vaultNumber = Math.max(
        creoSaveNumber(obj.filename || pathBasename(vaultRel), purgeable),
        creoSaveNumber(
          (obj.current_version && obj.current_version.filename) || "",
          purgeable
        ),
        creoSaveNumber(pathBasename(vaultRel), purgeable)
      );
      var newerSave = local.saveNumber > vaultNumber;
      var vaultHash = String(
        (obj.current_version && obj.current_version.content_hash) || ""
      )
        .trim()
        .toLowerCase();
      if (!vaultHash) return;
      // Older local tip than vault is not pending check-in work.
      if (local.saveNumber < vaultNumber) return;
      var canCheckin = Boolean(obj.can_checkin);
      var indexHash = String(local.item.content_hash || "").trim().toLowerCase();
      needsHash.push({
        uuid: String(obj.uuid || "").trim(),
        canCheckin: canCheckin,
        newerSave: newerSave,
        vaultHash: vaultHash,
        rel: local.rel,
        indexHash: indexHash,
      });
    });
    return needsHash;
  }

  /**
   * Resolve which check-in-eligible object uuids have a newer/different local tip.
   * hashPathsFn(relativePaths) → Promise<{ [relLower]: contentHash }>
   */
  async function resolvePendingCheckinUuids(cacheFiles, objects, hashPathsFn, options) {
    var opts = options || {};
    var purgeable = purgeableSet(opts.purgeable);
    var planned = planNewerLocalCacheSaves(cacheFiles, objects, purgeable);
    var out = [];
    var seen = Object.create(null);
    var needHashPaths = [];

    function pushUuid(uuid, canCheckin) {
      if (!uuid || !canCheckin || seen[uuid]) return;
      seen[uuid] = true;
      out.push(uuid);
    }

    planned.forEach(function (item) {
      if (!item.uuid) return;
      if (item.indexHash && item.indexHash !== item.vaultHash) {
        // .creopdm_cache_index.json + on-disk size match — file is real and differs.
        pushUuid(item.uuid, item.canCheckin);
        return;
      }
      if (item.indexHash && item.indexHash === item.vaultHash && !item.newerSave) {
        // Index agrees with vault tip; skip rehash.
        return;
      }
      // Missing index, size-stale index, or newer .N — verify via /hash-paths.
      needHashPaths.push(item);
    });

    if (!needHashPaths.length || typeof hashPathsFn !== "function") return out;
    var hashes = await hashPathsFn(
      needHashPaths.map(function (item) {
        return item.rel;
      })
    );
    var map = hashes || {};
    needHashPaths.forEach(function (item) {
      var localHash = map[String(item.rel || "").toLowerCase()] || "";
      if (localHash && localHash !== item.vaultHash) {
        pushUuid(item.uuid, item.canCheckin);
      }
    });
    return out;
  }

  global.CreoPdmLocalCachePending = {
    pathBasename: pathBasename,
    logicalUploadName: logicalUploadName,
    logicalRelativePath: logicalRelativePath,
    agentCacheSafeRelativePath: agentCacheSafeRelativePath,
    creoSaveNumber: creoSaveNumber,
    indexLocalCacheTipsByLogical: indexLocalCacheTipsByLogical,
    planNewerLocalCacheSaves: planNewerLocalCacheSaves,
    resolvePendingCheckinUuids: resolvePendingCheckinUuids,
  };
})(typeof window !== "undefined" ? window : globalThis);
