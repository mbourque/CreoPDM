# User interactions — Files page & toolbar

What the user does on the Files page, and what should happen. Use this for manual checks and as the behavior contract for regression tests.

**Code that implements this:** `app.html`, `app.js`, objects/projects APIs, workspace service, shared schemas.

**How to read each section**

- **What you do** — the user action in plain language.
- **What happens** — the correct result.
- **If something’s wrong** — validation messages and things that must never happen.
- Prefer checking in Creo’s embedded browser *and* a normal browser. Soft navigation (staying connected to Creo) matters most in Creo.
- After add, remove, or check-in, the Files list should match the vault **without** a full page refresh.

---

## Table of contents

1. [Moving around without losing Creo](#1-moving-around-without-losing-creo)
2. [Projects (sidebar & settings)](#2-projects-sidebar--settings)
3. [Finding your way in the Files list](#3-finding-your-way-in-the-files-list)
4. [Working with folders](#4-working-with-folders)
5. [Working with files](#5-working-with-files)
6. [Toolbar at a glance](#6-toolbar-at-a-glance)
7. [Set Working Directory](#7-set-working-directory)
8. [Add ▾](#8-add-)
9. [Open Workspace / Open / History / Copy to Vault](#9-open-workspace--open--history--copy-to-vault)
10. [Checkout ▾](#10-checkout-)
11. [Check In ▾](#11-check-in-)
12. [Remove ▾](#12-remove-)
13. [Danger confirm dialog](#13-danger-confirm-dialog)
14. [Quick smoke scripts](#14-quick-smoke-scripts)
15. [Regression test mapping](#15-regression-test-mapping)
16. [Do not regress](#16-do-not-regress)

---

## 1. Moving around without losing Creo

**What this is for:** Clicking projects, folders, and Settings should feel like staying in the same app. In Creo, the connection status should not flicker offline.

| What you do | What happens |
|-------------|--------------|
| Click a project, folder crumb, Settings, or other in-app link | The main content updates. Creo stays connected. The status pill does not flash “Not Connected.” |
| Click several places quickly | Each click is handled in order. The last place you went to is where you end up. |
| Do something that takes a moment (Add, Remove, Check In, …) | A busy overlay appears. Background workspace watching pauses until it finishes. |
| Refresh the browser the hard way (F5 / reload) | Full page reload. Creo may show Not Connected until it reconnects. Prefer clicking around in-app instead. |

**Must not**

| # | Must not |
|---|----------|
| G1 | Hard-reload the shell when moving between project / folder / Settings (that flashes Not Connected and can kill Creo.JS). |
| G2 | Silently ignore a later click while an earlier navigation is still loading. |
| G3 | After remove/add, show a stale list that still has deleted items. |
| G4 | After an in-app page swap, re-check Creo as if you just opened the app, or mark the status pill offline. |

---

## 2. Projects (sidebar & settings)

**What this is for:** Pick a project, create one, rename it, or delete it.

| What you do | What happens |
|-------------|--------------|
| Click a project in the sidebar | You land on that project’s Files view. Your choice is remembered. |
| Collapse or expand the sidebar | Layout changes; your preference is kept. |
| Create a **New** project | Fill in the dialog. On success, the project appears and you can open it. |
| Project settings ▾ → Rename | The project is renamed; the UI updates. |
| Rebuild Where Used | Index rebuilds in the background. Your Files list stays put. |
| Collect all metadata | Pulls metadata from Creo when Creo is connected. |
| Delete project | Type the project name to confirm. Removes the CreoPDM vault/registry. **Does not** delete the CAD files you originally imported from. You may optionally also clear the local workspace cache. |

**When creating or renaming**

| Field | OK | Not OK |
|-------|----|--------|
| Project name | Something non-empty | “A project name is required.” (or equivalent) |
| Vault / workspace folder name | One simple name, or Use hash | Empty (unless Use hash); no spaces in a custom vault folder name |

**Must not**

| # | Must not |
|---|----------|
| P1 | Delete the project if the confirm name is wrong. |
| P2 | Delete the user’s original import folder on disk (only vault / optional agent cache). |

---

## 3. Finding your way in the Files list

**What this is for:** Move up/down the folder tree, search, filter by type, switch views, and sort.

### Folder crumbs

| What you do | What happens |
|-------------|--------------|
| Click a crumb | You go to that folder (or project root). Creo stays connected. |
| Look at the current crumb | It matches the folder you’re in. |

### Search

| What you do | What happens |
|-------------|--------------|
| Type a search | Matches across the project show in the table. Crumbs may hide. |
| Clear search | You’re back in the normal folder view for where you are. |
| Clear search after removing something | Deleted rows stay gone (they must not reappear from an old snapshot). |

### Metric chips (Files, Parts, Assemblies, …)

| What you do | What happens |
|-------------|--------------|
| Click a chip | Matching **files** in the current view are filtered/selected. Click again to clear. |
| Have folders selected | Folders are not treated as typed files; chips must not steal folder selection incorrectly. |

### Tabs (Files / Checked out / Changes)

| What you do | What happens |
|-------------|--------------|
| Switch tab | That list shows; toolbar rules follow whatever is active. |
| Changes tab | Shows vault + local pending changes; can update when pending counts change. |

### Column sort

| What you do | What happens |
|-------------|--------------|
| Click a sortable column header | Sorts. Click again to reverse. Preference may stick per table. |

**Must not**

| # | Must not |
|---|----------|
| H1 | After delete + clear search, bring back removed folders/files from cache. |
| H2 | Open a folder or navigate away just because you clicked a metric chip. |

---

## 4. Working with folders

**What this is for:** Open a folder to look inside it, or select it (for Remove, etc.) without opening.

Applies to empty **Create folder** rows and folders from **Add folder…** / **Add folders…**.

| What you do | What happens |
|-------------|--------------|
| Click the **folder name** (icon + name) | **Opens** the folder. |
| Click elsewhere on the row (counts, empty space, padding) | **Selects** the folder only. Does **not** open. |
| Ctrl/Cmd-click the row (not the name) | Toggle multi-select. |
| Shift-click the row (not the name) | Range select. |
| Double-click anywhere on the row | **Opens** the folder. |
| Ctrl/Cmd/Shift + click the name | Does **not** open; selection modifiers apply instead. |
| Hover for the tooltip | Reminds you: name opens; elsewhere selects; double-click opens. |

**Must not**

| # | Must not |
|---|----------|
| F1 | Click the folder **name** and only select (it must open). |
| F2 | Click the **rest of the row** and open/navigate. |
| F3 | Opening a folder flash Not Connected or kill Creo.JS. |
| F4 | A global click handler steal the name-click so the folder never opens. |
| F5 | Make an empty Create-folder row impossible to select or remove. |

---

## 5. Working with files

**What this is for:** Select files, open them in Creo/OS, or open History.

| What you do | What happens |
|-------------|--------------|
| Click the row (not the name) | Select only. |
| Click the **file name** | Selects, then opens in Creo or the OS after a short pause. |
| Double-click the row | Opens History / object detail (not a folder). |
| Ctrl/Cmd or Shift | Multi-select / range, same idea as folders. |
| See “Modified” | Local save is newer and you own it / can check in. |

**Must not**

| # | Must not |
|---|----------|
| R1 | A single click on the name open History (that’s double-click). |
| R2 | A double-click also fire the delayed Open afterward. |

---

## 6. Toolbar at a glance

Left → right (typical): **Set Working Directory** → **Add ▾** → **Open Workspace** → **Open** → **Checkout ▾** → **Check In ▾** → **History** → **Copy to Vault** → **Remove ▾**.

| Control | Available when | Unavailable when |
|---------|----------------|------------------|
| Add ▾ | A project is open | No project |
| Open Workspace | A project is open | No project |
| Open | One openable file selected | Nothing / not openable |
| Checkout ▾ | You can checkout selection, checkout the project, or undo | None of those apply |
| Check In ▾ | Something to check in (selection or project) | Nothing pending |
| History | One file selected that has a detail page | No file selected |
| Copy to Vault | Selection needs copying into the vault | Nothing to copy |
| Remove ▾ | Any remove action applies | Nothing selected for remove |
| Remove from Project | Files and/or folders selected | Nothing selected |

Only one toolbar menu open at a time. Click outside or press Escape to close.

---

## 7. Set Working Directory

**What this is for:** Point Creo at this project’s local workspace so Open/Checkout land in the right place.

| What you do | What happens |
|-------------|--------------|
| Click it while in a Creo session | Creo’s working directory becomes this project’s local workspace when possible. |
| Use the UI outside Creo | Control is hidden or inactive. |

---

## 8. Add ▾

**What this is for:** Create an empty folder in the vault, or bring files/folders into the project from disk.

Menu (top → bottom):

1. **Create folder…**
2. **Add files…**
3. **Add folder…**
4. **Add folders…**

### 8.1 Create folder…

**What you do:** Add ▾ → Create folder… → type a name → Create.

**What happens:** An empty folder appears under the folder you’re currently viewing (not always at project root). The dialog closes; the list updates; no hard refresh needed.

| Rule | OK | Not OK |
|------|----|--------|
| Name required | 1–200 characters, one segment | Empty → “Enter a folder name.” |
| Length | ≤ 200 | Longer input blocked |
| No path separators | `Drawings`, `Assy_01` | `a/b`, `a\b`, `.`, `..` → “Enter a folder name without path separators.” |
| No leading dot | `Drawings` | `.hidden` → “Folder names cannot start with a dot.” |
| Unique under parent | New name | Already exists → “Folder already exists: …” |
| Not a file path | — | File already there → “A file already exists at …” |

**Must not**

| # | Must not |
|---|----------|
| A1 | Treat a blank name as success. |
| A2 | Create a nested path from one name field (`Foo/Bar`). |
| A3 | Create a dot-folder (`.cache`). |
| A4 | Overwrite an existing folder’s contents on duplicate. |
| A5 | While you’re inside `Drawings/`, create the folder at project root instead. |

---

### 8.2 Add files…

**What you do:** Add ▾ → Add files… → pick files (agent picker preferred, or native picker / drag-drop).

**What happens:** Files go into the vault under the folder you’re in. New files show in the list without a hard refresh.

| Problem | What you should see |
|---------|---------------------|
| Nothing chosen | “Choose files or a folder first.” |
| Click Add twice | “Add is already running — wait for it to finish.” |
| Drop a whole folder tree in files mode | “Use Add folders or Add Folder to import a folder tree.” |
| Agent paths needed but agent is down | “Start creopdm-agent…” |
| Empty / ignored files | Skipped, with a warning when appropriate |

**Must not**

| # | Must not |
|---|----------|
| A6 | Quietly import a nested folder tree as “Add files.” |
| A7 | Run two imports at once. |
| A8 | Call import with an empty selection. |

---

### 8.3 Add folder… (this folder only — not subfolders)

**What you do:** Add ▾ → Add folder… → pick one folder.

**What happens:** Only the **top-level files** in that folder are imported (subfolders are skipped). The folder appears under where you are and can be opened or selected like any other folder.

| Problem | What you should see |
|---------|---------------------|
| Nothing chosen | “Choose a folder first.” |
| Folder has files only in subfolders | “No top-level files found in that folder. Subfolder files are skipped for Add Folder.” |
| Picking a folder over LAN (`http://`) | Agent’s folder picker runs **before** the browser’s |

**Must not**

| # | Must not |
|---|----------|
| A9 | Pull in files from subfolders (`Folder/sub/file.prt`) in this mode. |
| A10 | Skip the agent picker on LAN and jump to a broken browser picker. |

---

### 8.4 Add folders… (whole trees)

**What you do:** Add ▾ → Add folders… → pick one or more folder roots.

**What happens:** Each tree is imported with its structure kept (`Alpha/lib/a.prt` stays nested). Multiple roots each keep their own top folder name.

**Must not**

| # | Must not |
|---|----------|
| A11 | Flatten nested paths down to the vault root. |
| A12 | Drop sibling subfolders when walking a dropped tree. |

---

## 9. Open Workspace / Open / History / Copy to Vault

| What you do | What happens |
|-------------|--------------|
| **Open Workspace** | Opens this project’s local workspace folder on disk (agent cache; falls back to vault on the host). Needs a project. |
| **Open** | Opens the selected file in Creo or with the OS. (Name-click waits a moment before opening.) |
| **History** | Goes to that file’s detail / history page. Needs one file selected. |
| **Copy to Vault** | Puts the selection into the vault without checking it out. |

---

## 10. Checkout ▾

**What this is for:** Lock files for edit and get them into your local workspace — or give up your lock without checking in.

Menu:

1. **Checkout selected**
2. **Checkout project**
3. **Undo Checkout**

| What you do | What happens | When it’s unavailable / fails |
|-------------|--------------|-------------------------------|
| Checkout selected | Locks and downloads what you selected | Nothing checkoutable; someone else’s lock fails that item |
| Checkout project | Checks out everything available (not locked by others) | Nothing left to check out |
| Undo Checkout | Releases **your** lock only. Does not delete the vault file or create a version | You don’t own any checkouts; must not undo someone else’s |

Opening a file from the UI may also offer checkout companions / set working directory when that makes sense.

---

## 11. Check In ▾

**What this is for:** Save your work back to the vault and release locks so the project looks checked in.

Menu:

1. **Check in project…**
2. **Check in selected…** (shows as **Add selected…** when the selection is only new files)

| What you do | What happens |
|-------------|--------------|
| Check in project… | Pending saves + new files go up; unchanged checkouts are released so the project looks fully checked in. |
| Check in selected… | Check in / add for what you selected. |
| Enter a comment | Required before you can finish. |
| After success | The list updates to match the vault (soft reload, no hard refresh). |

| Rule | OK | Not OK |
|------|----|--------|
| Comment | Non-empty | Browser blocks empty; API: “A check-in comment is required.” |
| Something to do | Pending saves, new files, and/or checkouts | Both menu items disabled with a clear reason |
| Agent for local sync | Agent running when pushing local saves | Offline → incomplete sync; toolbar warning |

**Must not**

| # | Must not |
|---|----------|
| C1 | Complete check-in with an empty comment. |
| C2 | Succeed as an “empty” project check-in when nothing is pending. |
| C3 | In Creo, rely only on form navigation after check-in — the table must update in place. |

---

## 12. Remove ▾

**What this is for:** Clean up local workspace files, vault copies, or unregister items from the project — without wiping the user’s original CAD source folder unless they explicitly choose workspace cleanup.

Menu (typical):

1. **Remove from Workspace** — local cache → Recycle Bin; vault and project list unchanged  
2. **Purge workspace** — older local numbered saves below the vault floor → Recycle Bin  
3. **Remove from Vault** — delete vault copies only; originals stay; checkouts cancelled  
4. **Remove from Project** — unregister from the project **and** delete vault copies; originals stay  

Destructive actions that ask you to type the project name share [§13](#13-danger-confirm-dialog).

### 12.1 Remove from Workspace

| What you do | What happens | Must not |
|-------------|--------------|----------|
| Select local-new queue rows that have agent cache, then remove | Those files go to Recycle Bin on this PC | Change the vault or project catalog |
| Try it with the wrong kind of selection | Control stays disabled | — |
| Agent is down | You’re told to start the agent | Silently succeed |

### 12.2 Purge workspace

| What you do | What happens | Must not |
|-------------|--------------|----------|
| Preview, then confirm | Older local saves are deleted; vault revision and newer local work stay | Delete vault objects |
| Nothing to purge | OK message; nothing deleted | — |

### 12.3 Remove from Vault

| What you do | What happens | Must not |
|-------------|--------------|----------|
| Confirm with the project name | Vault copies deleted; checkouts cancelled | Delete the user’s original CAD folder files |

### 12.4 Remove from Project

**What you do:** Select files and/or folders (including an empty Create-folder row) → Remove ▾ → Remove from Project → type the project name to confirm.

**What happens**

- Selected files and folders leave the project and their vault copies are deleted.
- Empty Create folders and whole Add-folder trees go away the same way.
- Your **original CAD files on disk stay** (unless you check the optional “also delete local workspace” box for agent-cache cleanup).
- Rows disappear **immediately**. A soft list refresh must **not** bring them back. No hard refresh required.

| Problem | What you should see |
|---------|---------------------|
| Nothing selected | “Choose files or a folder to remove.” |
| Folders only, but no project context | “Choose a project before removing folders.” |
| Someone else has it checked out | That item fails ownership; others may still succeed |

**Must not**

| # | Must not |
|---|----------|
| V1 | Call remove if the confirm name is wrong. |
| V2 | Leave Remove from Project disabled when only an empty Create folder is selected. |
| V3 | Leave a successfully removed folder visible until a hard refresh. |
| V4 | Delete originals in the user’s CAD/source folder (unless they opted into workspace cleanup). |
| V5 | Soft-reload right after success and paint deleted rows again because the delete hadn’t been saved yet. |
| V6 | Clear search after remove and restore rows from a stale list snapshot. |
| V7 | Remove an object checked out by someone else. |
| V8 | Change vault or list if they Cancel the confirm. |
| V9 | Pretend full success if the API failed mid-batch. |

---

## 13. Danger confirm dialog

**What this is for:** Dangerous deletes (Delete project, Remove from Project, Remove from Vault, Purge, Discard local, etc.) ask you to type the project name so a mis-click doesn’t wipe things.

| What you do | What happens |
|-------------|--------------|
| Type the project name exactly (trim; case-sensitive) | Confirm proceeds. |
| Wrong or empty name | “Type the project name exactly to confirm.” Dialog stays open. |
| Cancel / Esc / close | Nothing happens; no API call. |
| Optional “also delete local workspace” | Unchecked = vault/project only; checked = also recycle agent-cache paths. |

**Must not**

| # | Must not |
|---|----------|
| D1 | Proceed on a wrong or empty name. |
| D2 | Treat Cancel as Confirm. |

---

## 14. Quick smoke scripts

### 14.1 Create folder → open → remove

1. Open a project on Files (root or a subfolder).  
2. **Add ▾ → Create folder…** → name it `UxTest`.  
3. Expect: the row appears without a hard refresh.  
4. Click the **name** → you enter `UxTest`; Creo stays connected if it was.  
5. Use the crumb to go back to the parent.  
6. Click the **row (not the name)** → selected; Remove from Project is enabled.  
7. Confirm with the exact project name.  
8. Expect: success toast; **`UxTest` gone immediately**; vault folder gone; no hard refresh needed.  

Repeat with **Add folder…** (one top-level file) and **Add folders…** (a nested tree).

### 14.2 Quick negative pass

9. Create folder blank → “Enter a folder name.”  
10. Create folder `Bad/Name` → error; no junk path.  
11. Create `UxTest2` twice → second says already exists.  
12. Remove → wrong project name → error; row remains.  
13. Remove → Cancel → no change.  
14. Click folder chrome only → must not open.  
15. Click folder name → must open.  

### 14.3 Add mode negatives

16. Add files… drop a folder tree → error telling you to use Add folder(s).  
17. Add folder… folder with only nested files → no top-level files message.  
18. Add folders… nested relative paths still show after import.  

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
| Create folder invalid names (A1–A3) | `test_create_project_folder_rejects_invalid_names` |
| Create folder empty / duplicate (A1, A4) | `test_create_project_folder_rejects_empty_schema_and_duplicate` |
| Create folder nests under parent (A5) | `test_create_project_folder_empty_appears_on_disk` |
| BatchRemoveRequest schema (N22) | `test_batch_remove_request_*` in `test_user_interaction_validations.py` |
| Batch remove API empty / no project | `test_batch_remove_rejects_empty_and_folder_without_project` |
| Checkout ownership on batch remove (N21) | `test_batch_remove_respects_checkout_ownership` |
| Add / Create / confirm client negatives (A6–A10, D1, V2) | `test_user_interaction_negative_client_guards` |
| Confirm name mismatch string | `test_user_interaction_negative_client_guards`, checkin HTML |
| Check-in blank comment | `test_checkin_increments_iteration_and_releases_lock` (whitespace → 422) |
| Non-recursive Add folder | `test_from_disk_folder_non_recursive_skips_nested`, `filterTopLevelUploads` guard |
| Vault folder name rules (spaces/paths) | `test_vault_folder.py`, project dialog UI strings |
| Delete project wrong confirm (P1) | `test_projects.py` confirm_name wrong |

Still manual / no automated browser E2E: §14 smoke click paths in Creo’s embedded browser, metric chips, full toolbar enablement state machine.

---

## 16. Do not regress

- Moving between project / folder / Settings must not re-probe Creo.JS or flash Not Connected.  
- Clicking a folder **name** must open the folder (global click handling must not steal that click).  
- After Remove from Project, the Files list must match the vault without a hard refresh.  
- Empty Create-folder rows must be selectable and removable even with no file ids.  
- Validation failures must not look like success (no OK toast, no silent API, no vanishing row that “comes back”).  
- Add folder… stays top-level only; Add folders… keeps nested paths.  
- Remove from Project must not delete the user’s original CAD source files (vault only, unless they check workspace cleanup).  
