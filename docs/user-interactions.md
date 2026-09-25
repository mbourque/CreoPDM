# User interactions — Files page & toolbar

Source of truth for **manual testing** and **unit/regression tests**. Describes correct user-facing behavior after the Add ▾ / folder open / Remove from Project / Check In ▾ / soft-nav refresh work.

**Primary code:** `src/creopdm/templates/app.html`, `src/creopdm/static/js/app.js`, `src/creopdm/api/objects.py`, `src/creopdm/api/projects.py`, `src/creopdm/services/workspace_service.py`, `src/creopdm/schemas/common.py`.

**How to use this doc**

- Each subsection: **happy path** → **field validation** → **negative / must-not**.
- Prefer reproducing in Creo’s embedded browser *and* a normal browser; soft-nav and Creo.JS matter most in Creo.
- After any mutation that changes the Files list, the list must match the vault **without** a hard refresh.

---

## Table of contents

1. [Global: soft navigation & busy UI](#1-global-soft-navigation--busy-ui)
2. [Project sidebar & project settings](#2-project-sidebar--project-settings)
3. [Files list header: crumbs, search, metrics, tabs, sort](#3-files-list-header-crumbs-search-metrics-tabs-sort)
4. [Folder rows](#4-folder-rows)
5. [File rows](#5-file-rows)
6. [Toolbar overview & enablement](#6-toolbar-overview--enablement)
7. [Set Working Directory](#7-set-working-directory)
8. [Add ▾](#8-add-)
9. [Open Workspace / Open / History / Copy to Vault](#9-open-workspace--open--history--copy-to-vault)
10. [Checkout ▾](#10-checkout-)
11. [Check In ▾](#11-check-in-)
12. [Remove ▾](#12-remove-)
13. [Danger confirm dialog (shared)](#13-danger-confirm-dialog-shared)
14. [End-to-end smoke scripts](#14-end-to-end-smoke-scripts)
15. [Regression test mapping](#15-regression-test-mapping)
16. [Do not regress](#16-do-not-regress)

---

## 1. Global: soft navigation & busy UI

### Happy path

| User action | Correct behavior |
|-------------|------------------|
| Click same-origin shell link (project, folder crumb, Settings, soft-nav `a[href]`) | `main.shell` HTML is fetched and swapped. **Creo.JS stays live.** Status pill does not flash Not Connected. |
| Soft fetch | `cache: "no-store"`; refresh URLs include cache-bust `r=`. |
| Several soft navigations / refreshes in a row | Serialized (`softNavTail`). Latest navigation/refresh is **not** dropped. |
| Action with busy overlay (Add, Remove, Check In, …) | Overlay + message; UI marked busy; workspace-watch pauses while `busyDepth > 0`. |
| Hard browser refresh | Full document load; Creo may show Not Connected until reconnect. Prefer soft nav in Creo. |

### Negative / must-not

| # | Action | Must not |
|---|--------|----------|
| G1 | Soft-nav to folder / project / Settings | Must not hard-reload shell pages (SSR Not Connected flash / kill Creo.JS). |
| G2 | Soft-nav while another soft-nav is in flight | Must not silently no-op the later navigation. |
| G3 | Soft list fetch after remove/add | Must not paint a **cached** HTML body that still lists deleted items. |
| G4 | Soft boot after shell swap | Must not re-probe Creo.JS / agent or rewrite the status pill as offline. |

---

## 2. Project sidebar & project settings

### Happy path

| User action | Correct behavior |
|-------------|------------------|
| Click a project in the sidebar | Soft-nav to that project’s Files view; selection remembered. |
| Collapse / expand sidebar | Layout toggles; preference persists as implemented. |
| **New** project | Project dialog; on success, project appears and can be selected. |
| Project settings ▾ → Rename | Renames project; UI updates. |
| Rebuild Where Used | Background index; does not wipe the Files list. |
| Collect all metadata | Creo session metadata pass (when Creo connected). |
| Delete project | Danger confirm (type project name). Deletes CreoPDM vault/registry; **does not** delete original CAD source files the user imported from. Optional local workspace delete when offered. |

### Field validation (new / rename project — high level)

| Field | Valid | Invalid → expected |
|-------|-------|---------------------|
| Project name | Required, non-empty | **“A project name is required.”** (or equivalent) |
| Vault/workspace name | Single segment; or Use hash | Empty when not using hash → prompt to enter name or check Use hash; **no spaces** in custom vault folder name |

### Negative

| # | Must not |
|---|----------|
| P1 | Delete project with wrong confirm name — must not delete. |
| P2 | Delete project — must not delete the user’s original import folder on disk (only vault / optional agent cache). |

---

## 3. Files list header: crumbs, search, metrics, tabs, sort

### Folder crumb

| User action | Correct behavior |
|-------------|------------------|
| Click a crumb segment | Soft-nav to that folder (or project root). Creo stays connected. |
| Current folder label | Shows the folder you are in; matches URL `folder=` query. |

### Search

| User action | Correct behavior |
|-------------|------------------|
| Type a query | Debounced search across project; table shows matches; crumb may hide. |
| Clear search | Restores **folder view** for the current folder. |
| Clear search after Remove | Must restore folder view **without** reappearing deleted rows (tbody snapshot updated on remove). |

### Metric chips (Files, Parts, Assemblies, …)

| User action | Correct behavior |
|-------------|------------------|
| Click a metric | Filters and selects matching **files** in the current view. Click again clears (per chip title). |
| Folder rows | Metric selection must **not** clear or steal folder selection incorrectly; folders are not type-filtered as files. |

### Tabs (Files / Checked out / Changes)

| User action | Correct behavior |
|-------------|------------------|
| Switch tab | Shows that panel; selection/toolbar rules follow the active list. |
| Changes tab | Loads vault + local pending changes; can refresh in place when pending counts change. |

### Column sort

| User action | Correct behavior |
|-------------|------------------|
| Click sortable column header | Sorts; click again reverses. Preference may persist per table. |

### Negative

| # | Must not |
|---|----------|
| H1 | Clearing search after delete — must not resurrect removed folder/file rows from cache. |
| H2 | Metric chip — must not open a folder or navigate away. |

---

## 4. Folder rows

Applies to empty **Create folder** rows and folders that appear after **Add folder…** / **Add folders…** / catalog merge.

### Happy path

| User action | Correct behavior |
|-------------|------------------|
| Click **folder name link** (icon + name, `a.folder-open`) | **Opens** folder (`/?project=…&folder=…`) via soft-nav (`leavePage`). |
| Click **row chrome** (file count, empty cells, padding) | **Selects** only (for Remove, etc.). Does **not** open. |
| Ctrl/Cmd-click row chrome | Toggle multi-select. |
| Shift-click row chrome | Range select. |
| Double-click anywhere on the row | **Opens** the folder. |
| Ctrl/Cmd/Shift + click on the name link | Does **not** open; selection modifiers apply. |
| Tooltip on row | Explains: name opens; elsewhere selects; double-click opens. |

### Negative / must-not

| # | Action | Must not |
|---|--------|----------|
| F1 | Click folder **name** | Must not only select (must open). |
| F2 | Click folder **row chrome** | Must not navigate/open. |
| F3 | Soft-nav into folder | Must not flash Not Connected / kill Creo.JS. |
| F4 | Document-level soft-nav capture on `a.folder-open` | Must not steal the click so open never runs. |
| F5 | Empty Create-folder row (no `data-object-ids`) | Must not be impossible to select or remove. |

---

## 5. File rows

### Happy path

| User action | Correct behavior |
|-------------|------------------|
| Click row (not the name) | Select only. |
| Click file name (`object-open`) | Select, then open in Creo or OS after a short delay (~280 ms). |
| Double-click row | Opens History / object detail (not folder open). |
| Ctrl/Cmd / Shift | Multi-select / range as with folders. |
| State “Modified” | Shown when local newer save + owned / can check in. |

### Negative

| # | Must not |
|---|----------|
| R1 | Single-click name — must not open History (that is double-click). |
| R2 | Double-click — must not also fire the delayed Open if cancelled by dblclick. |

---

## 6. Toolbar overview & enablement

Left → right (typical): **Set Working Directory** (Creo session) → **Add ▾** → **Open Workspace** → **Open** → **Checkout ▾** → **Check In ▾** → **History** → **Copy to Vault** → **Remove ▾**.

| Control | Enabled when | Disabled when |
|---------|--------------|---------------|
| Add ▾ | Project selected | No project |
| Open Workspace | Project selected | No project |
| Open | One openable selection | None / not openable |
| Checkout ▾ | Can checkout selected, checkout project, or undo | None of those |
| Check In ▾ | Can check in selected/add or check in project | Nothing pending for either |
| History | One selected file with detail href | No file selection |
| Copy to Vault | Selection not already in workspace as required | N/A / nothing to copy |
| Remove ▾ | Any remove submenu action available | Nothing selected for any remove action |
| Remove from Project | `object_ids` **or** `folder_paths` from selection | No files and no folders selected |

Only one toolbar fly-up menu open at a time; outside click / Escape closes menus.

---

## 7. Set Working Directory

| User action | Correct behavior |
|-------------|------------------|
| Click (Creo session) | Sets Creo working directory to this project’s local workspace (agent cache) when possible. |
| Outside Creo | Control hidden or inactive (`creo-session-only`). |

---

## 8. Add ▾

### Menu order & labels (top → bottom)

1. **Create folder…**
2. **Add files…**
3. **Add folder…**
4. **Add folders…**

### 8.1 Create folder…

#### Happy path

| Step | Correct behavior |
|------|------------------|
| Open | Dialog; location line shows current folder or project root. |
| Enter name → Create | `POST /api/projects/{id}/folders` with `parent_folder` = current Files folder. Empty vault folder + `.gitkeep`. |
| After success | Dialog closes; list refreshes; folder row appears **without hard refresh**. |
| Nesting | If you are inside `Drawings/`, new folder is `Drawings/{name}`, not vault root. |

#### Field validation

| Field / rule | Valid | Invalid → expected |
|--------------|-------|---------------------|
| Name required | 1–200 chars, one segment | Empty/whitespace → **“Enter a folder name.”**; no API call |
| `maxlength` | ≤ 200 | Browser blocks longer input |
| Schema | `min_length=1`, `max_length=200` | Empty → 422 |
| No path separators | `Drawings`, `Assy_01` | `a/b`, `a\b`, `.`, `..` → **“Enter a folder name without path separators.”** |
| No leading dot | `Drawings` | `.hidden` → **“Folder names cannot start with a dot.”** |
| Unique under parent | New name | Exists with content/`.gitkeep` → **“Folder already exists: …”** |
| Not a file path | — | File at path → **“A file already exists at …”** |

#### Negative

| # | Must not |
|---|----------|
| A1 | Blank submit — create vault folder or success toast |
| A2 | `Foo/Bar` — create nested path from one name field |
| A3 | `.cache` — create dot-folder |
| A4 | Duplicate — overwrite existing contents |
| A5 | While in `Drawings/` — create at project root |

---

### 8.2 Add files…

#### Happy path

| Step | Correct behavior |
|------|------------------|
| Open | Add dialog in files mode; pick via agent (preferred), native picker, or drag-drop. |
| Import | Files copy into vault under current `parent_folder` when nested. |
| After success | List refresh; new files visible without hard refresh. |

#### Field validation / errors

| Rule | Invalid → expected |
|------|---------------------|
| Nothing selected | **“Choose files or a folder first.”** |
| Double submit | **“Add is already running — wait for it to finish.”** |
| Dropped folder tree in files mode | **“Use Add folders or Add Folder to import a folder tree.”** |
| Agent paths, agent down | **“Start creopdm-agent…”** |
| Empty / ignored files | Skipped or PathValidation; warning as applicable |

#### Negative

| # | Must not |
|---|----------|
| A6 | Silently import a nested folder tree as “Add files” |
| A7 | Start two parallel imports |
| A8 | Call import API with empty selection |

---

### 8.3 Add folder… (non-recursive)

#### Happy path

| Step | Correct behavior |
|------|------------------|
| Pick one folder | Imports **top-level files only** (not subfolders). |
| Nesting | Lands under current Files `parent_folder` when applicable. |
| Folder row | Appears in parent list; openable/selectable like other folders. |

#### Field validation / errors

| Rule | Invalid → expected |
|------|---------------------|
| Nothing chosen | **“Choose a folder first.”** |
| Only nested files under subfolders | **“No top-level files found in that folder. Subfolder files are skipped for Add Folder.”** |
| LAN `http://` pick | Agent native folder pick **before** browser directory picker |

#### Negative

| # | Must not |
|---|----------|
| A9 | Import `Folder/sub/file.prt` in Add folder… mode |
| A10 | Skip agent pick on LAN and jump straight to broken browser picker |

---

### 8.4 Add folders… (recursive)

#### Happy path

| Step | Correct behavior |
|------|------------------|
| Pick one or more folder roots | Recursive import; relative paths preserved (`Alpha/lib/a.prt`). |
| Multi-root | Each tree imported under its root name (and `parent_folder` if nested view). |

#### Negative

| # | Must not |
|---|----------|
| A11 | Flatten `Alpha/lib/a.prt` → `a.prt` at vault root |
| A12 | Lose sibling subfolders when walking a dropped tree |

---

## 9. Open Workspace / Open / History / Copy to Vault

| Control | Happy path | Notes |
|---------|------------|--------|
| Open Workspace | Opens local agent cache folder for the project (fallback: vault on host) | Needs project |
| Open | Opens selected file in Creo or OS association | Delayed after name click |
| History | Navigates to object detail / history | Single file selection |
| Copy to Vault | Copies selected into vault without checkout | Does not check out |

---

## 10. Checkout ▾

### Menu order

1. **Checkout selected**  
2. **Checkout project**  
3. **Undo Checkout**

| Item | Happy path | Disabled / negative |
|------|------------|---------------------|
| Checkout selected | Locks + downloads selection to local workspace | Disabled if nothing checkoutable; other’s lock → fail that item |
| Checkout project | All available (not locked by others) | Disabled if checkoutable count is 0; title: nothing left to check out |
| Undo Checkout | Releases **your** lock only; does not delete vault file or create a version | Disabled if you own no checkouts; must not undo someone else’s |

Open-from-UI may offer checkout companions / set working directory in the open dialog when applicable.

---

## 11. Check In ▾

### Menu order & labels

1. **Check in project…**  
2. **Check in selected…** (becomes **Add selected…** when selection is only new files to add)

### Happy path

| Item | Correct behavior |
|------|------------------|
| Check in project… | Pending saves + new files; releases unchanged checkouts so project looks fully checked in. |
| Check in selected… | Check in / add for current selection. |
| Dialog comment | Required. |
| After success | Table patches; soft reload; list matches vault. |

### Field validation

| Field / rule | Valid | Invalid → expected |
|--------------|-------|---------------------|
| Comment | Non-empty | Browser `required`; API **“A check-in comment is required.”** |
| Project scope | Pending saves, new files, and/or checkouts | Both menu items disabled with explanatory titles |
| Agent for local sync | Agent up when pushing local saves | Offline → sync incomplete; toolbar error/warning |

### Negative

| # | Must not |
|---|----------|
| C1 | Empty comment — complete check-in |
| C2 | Nothing pending — succeed as empty project check-in |
| C3 | Check-in dialog navigation in Creo — rely only on form navigation (table must patch; `reloadPageAfterDialog`) |

---

## 12. Remove ▾

### Menu order (typical)

1. **Remove from Workspace** — agent cache → Recycle Bin; vault/list unchanged  
2. **Purge workspace** — older local numbered saves below vault floor → Recycle Bin  
3. **Remove from Vault** — delete vault copies only; originals in project folder stay; cancels checkouts  
4. **Remove from Project** — unregister from project + delete vault copies; originals stay  

All destructive list actions that use project-name confirm share [§13](#13-danger-confirm-dialog-shared).

---

### 12.1 Remove from Workspace

| Happy path | Negative |
|------------|----------|
| Selected **local-new** queue rows with agent cache | Wrong selection type — control disabled |
| Files move to Recycle Bin on this PC | Must not change vault or project catalog |
| Agent required | Agent down → start-agent message |

---

### 12.2 Purge workspace

| Happy path | Negative |
|------------|----------|
| Preview then confirm; deletes older local saves only | Nothing to purge → OK message, no delete |
| Keeps vault revision and newer local work | Must not delete vault objects |

---

### 12.3 Remove from Vault

| Happy path | Negative |
|------------|----------|
| Project-name confirm; vault copies deleted | Must not delete user’s original CAD folder files |
| Checkouts cancelled | — |

---

### 12.4 Remove from Project (critical — list refresh regressions)

#### Happy path

| Step | Correct behavior |
|------|------------------|
| Select file row(s) | Enabled; API `object_ids`. |
| Select folder row(s), including **empty Create folder** | Enabled; API `folder_paths` (+ descendant object ids). |
| Mix | Both `object_ids` and `folder_paths`. |
| Confirm | Project name; optional “also delete local workspace” for file paths. |
| Vault vs originals | Vault copies deleted. **Originals in user’s CAD folder are not deleted** (unless workspace checkbox cleans agent cache). |
| Empty Create folder | Vault tree including `.gitkeep` removed. |
| Add folder / Add folders tree | Objects under path unregistered; vault folder removed via `folder_paths`. |
| **UI after success** | Rows **gone immediately**. Soft reload must **not** bring them back. **No hard refresh.** |
| Server | `POST /api/objects/batch/remove` **`db.commit()` before return** so soft reload cannot race an uncommitted delete. |
| Client refresh | Await soft-nav (`no-store` + `r=`), then `__creopdmStripRemovedListRows` strips any lagged rows; `folderTbodyHtml` updated on DOM remove. |

#### API / schema validation

| Rule | Invalid → expected |
|------|---------------------|
| No ids and no folders | **“Choose files or a folder to remove.”** |
| Folders only, no `project_id` and no ids | **“Choose a project before removing folders.”** |
| Object checked out by another user | That item in `failed` (`CHECKOUT_OWNERSHIP`); others may succeed |

#### Negative / must-not

| # | Action | Must not |
|---|--------|----------|
| V1 | Wrong confirm name | Call `batch/remove` |
| V2 | Empty Create-folder selected | Leave Remove from Project disabled |
| V3 | Successful folder remove | Leave folder visible until hard refresh |
| V4 | Successful remove | Delete originals in user’s CAD/source folder (unless intentional workspace cleanup) |
| V5 | Soft reload right after JSON 200 | Re-paint deleted rows due to post-response DB commit |
| V6 | Clear search after remove | Restore rows from stale `folderTbodyHtml` |
| V7 | Other user’s checkout | Remove that object |
| V8 | Cancel confirm | Change vault or list |
| V9 | API failure mid-batch | Pretend full success; refresh should stay honest |

---

## 13. Danger confirm dialog (shared)

Used by Delete project, Remove from Project, Remove from Vault, Purge, Discard local, etc.

| Field / rule | Valid | Invalid → expected |
|--------------|-------|---------------------|
| Confirm name | Exact project name (trim; case-sensitive match) | **“Type the project name exactly to confirm.”**; stay open |
| Cancel / Esc / close | — | `{ ok: false }`; no API |
| Workspace checkbox | When `workspaceOption` | Unchecked = vault/project only; checked = also recycle agent-cache paths |

### Negative

| # | Must not |
|---|----------|
| D1 | Proceed on wrong or empty name |
| D2 | Treat cancel as confirm |

---

## 14. End-to-end smoke scripts

### 14.1 Create folder → open → remove

1. Open a project on Files (root or a subfolder).  
2. **Add ▾ → Create folder…** → `UxTest`.  
3. Expect: row appears without hard refresh.  
4. Click **name link** → enters `UxTest`; Creo stays connected if it was.  
5. Crumb back to parent.  
6. Click **row chrome** → selected; Remove from Project enabled.  
7. Confirm with exact project name.  
8. Expect: success toast; **`UxTest` gone immediately**; vault folder gone; hard refresh not required.  

Repeat with **Add folder…** (one top-level file) and **Add folders…** (nested tree).

### 14.2 Quick negative pass

9. Create folder blank → **Enter a folder name.**  
10. Create folder `Bad/Name` → error; no junk path.  
11. Create `UxTest2` twice → second **already exists**.  
12. Remove → wrong project name → error; row remains.  
13. Remove → Cancel → no change.  
14. Click folder chrome only → must not open.  
15. Click folder name → must open.  

### 14.3 Add mode negatives

16. Add files… drop a folder tree → error to use Add folder(s).  
17. Add folder… folder with only nested files → no top-level files message.  
18. Add folders… verify nested relative paths in list after import.  

### 14.4 Check In negative

19. Open check-in with empty comment → blocked.  
20. With nothing pending, Check In ▾ items stay disabled.  

---

## 15. Regression test mapping

| Behavior | Test hooks |
|----------|------------|
| Add menu order & labels | `test_add_toolbar_is_menu_with_modes` |
| Check In order & labels | `test_checkout_checkin_toolbar_menus_and_open_wd`, checkout integration |
| Folder link opens / row selects | `test_folder_row_click_selects_double_click_opens` |
| Remove sends `folder_paths` | `test_remove_from_project_sends_folder_paths` |
| Create + Add folder removable via API | `test_batch_remove_by_folder_path_removes_created_and_uploaded` |
| Commit before soft reload | `test_batch_remove_commits_before_response` |
| Soft reload / strip after remove | `test_remove_rows_update_folder_tbody_cache_and_soft_reload` |
| Soft-nav serialize / no-store | `test_soft_nav_does_not_silently_drop_when_busy`, `test_soft_nav_skips_creojs_reconnect` |
| Agent before browser folder pick | `test_choose_folder_uses_agent_before_browser_picker` |
| Nested paths on folder add | `test_dropped_folder_keeps_nested_relative_paths`, `test_from_disk_folders_list_imports_each_tree` |
| Create folder name rules | Unit `create_folder` / PathValidation messages |
| BatchRemoveRequest empty / no project | Schema: choose files or folder / choose a project |
| Confirm name mismatch | UI string `Type the project name exactly to confirm.` |
| Add files rejects folder tree | Client string about Add folders / Add Folder |
| Checkout ownership on remove | Integration: item in `failed`, not deleted |

**Suggested additional unit tests:** table-driven A1–A5 (create folder), A6–A9 (add filters), V3–V6 (list honesty after remove), schema N22/V folder-without-project.

---

## 16. Do not regress

- Soft-nav must not re-probe Creo.JS or flash Not Connected on folder/project/Settings switches.  
- Soft-nav capture must not steal folder-name clicks (table handler → `leavePage` / `openFolderRow`).  
- Remove from Project must not require a hard refresh for the Files list to match the vault.  
- Empty Create-folder rows must be selectable and removable via `folder_paths` without object ids.  
- Field validation failures must not look like success (no OK toast, no silent API, no vanishing row that “comes back”).  
- Add folder… must stay non-recursive; Add folders… must keep nested relative paths.  
- Remove from Project must not delete the user’s original CAD source files (vault only, unless workspace cleanup is explicitly checked).  
