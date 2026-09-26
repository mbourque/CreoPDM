# User interactions — what you do, what CreoPDM should do

Plain-language guide for **manual testing**. For each action: what you do, what the app **should** do, and what it **must not** do.

After you add, remove, or open something, the Files list should update **on its own** — you should not need a hard browser refresh (F5).

Test in Creo’s built-in browser when you can (Creo connection matters there). A normal browser is fine for most list/toolbar checks.

On a **phone** (portrait or landscape), CreoPDM switches to a **browse-only** layout: Settings / Status / Creo pills, New project, gear, metric chips, and the bottom toolbar are hidden; file tables keep **Name** and **Rev** only (New files keeps Filename only) so you should not need sideways scrolling; empty lists hide the crushed column headers and show a full-width message; **only folders** can be opened — file names and rows do not open Creo/Windows or Details. Detection is **touch-only** (`pointer: coarse` and `hover: none`) plus a phone-sized viewport—narrowing Creo’s desktop browser must **not** switch to browse mode.

---

## Contents

1. [Moving around the app](#1-moving-around-the-app)
2. [Projects (sidebar)](#2-projects-sidebar)
3. [Finding and filtering files](#3-finding-and-filtering-files)
4. [Folders in the list](#4-folders-in-the-list)
5. [Files in the list](#5-files-in-the-list)
6. [Toolbar buttons (overview)](#6-toolbar-buttons-overview)
7. [Add ▾](#7-add-)
8. [Open, workspace, history](#8-open-workspace-history)
9. [Checkout ▾](#9-checkout-)
10. [Check In ▾](#10-check-in-)
11. [Remove ▾](#11-remove-)
12. [Typing the project name to confirm](#12-typing-the-project-name-to-confirm)
13. [Quick walkthroughs](#13-quick-walkthroughs)
14. [For developers (tests)](#14-for-developers-tests)

---

## 1. Moving around the app

| You do | App should | App must not |
|--------|------------|--------------|
| Click a project, folder breadcrumb, or Settings | Show the new page quickly; if Creo was connected, it **stays** connected | Flash “Creo: Not Connected” or drop the Creo link just because you changed folders; hard-reload the page during a folder/project switch |
| Add or remove files/folders | Update the list so it matches reality | Leave old rows on screen until you press F5 |
| Wait while something big runs (Add, Remove, Check In…) | Show a busy message so you know it’s working | Sit frozen with no feedback |

---

## 2. Projects (sidebar)

| You do | App should | App must not |
|--------|------------|--------------|
| Click a project | Open that project’s Files list | Lose track of which project you picked |
| Collapse / expand the sidebar | Hide or show the project list | Break the Files list |
| Click **New** | Ask for a project name (and vault name options); then show the new project | Create a project with a blank name |
| Rename (project settings) | Update the name everywhere you see it | |
| Delete project | Ask you to type the **exact** project name; remove CreoPDM’s copy of the project | Delete your original CAD folders on disk just because you deleted the project; delete if you typed the wrong name |

**Name rules (new / rename)**

- Project name is required.
- Custom vault/workspace name: no spaces; or use the hash option instead.

---

## 3. Finding and filtering files

| You do | App should | App must not |
|--------|------------|--------------|
| Click a breadcrumb (Home / folder path) | Take you to that folder; Creo stays connected | |
| Type in Search | Show matching files across the project | |
| Clear Search | Show the normal folder view again | Bring back folders/files you already removed |
| Click a metric (Parts, Assemblies, …) | Filter and select those files; click again to clear | Jump into a folder or leave the page |
| Switch tabs: **Files** / **Checked out** / **New files** | Show that list | |
| Click a column header | Sort; click again to reverse | |

**New files tab** shows files waiting in the **vault** (and sometimes local cache) that aren’t fully in the project yet. Deleting only from your PC workspace does **not** clear vault “new” files — those live on the CreoPDM vault until you remove them from there.

---

## 4. Folders in the list

Empty folders you create and folders from Add folder(s) behave the same.

| You do | App should | App must not |
|--------|------------|--------------|
| Click the **folder name** (icon + name) | **Open** that folder | Only highlight the row |
| Click elsewhere on the folder row (empty cells, “N files”, padding) | **Select** the folder (for Remove, etc.) | Open the folder |
| Double-click the row | Open the folder | |
| Ctrl/Cmd-click or Shift-click on the row (not for opening) | Multi-select / range select | |

Empty folders (no files inside yet) must still be selectable and removable.

---

## 5. Files in the list

| You do | App should | App must not |
|--------|------------|--------------|
| Click the row (not the name) | Select the file | |
| Click the **file name** | Select, then open in Creo or Windows | Jump straight to Details |
| Double-click the row | Open **Details** (Overview tab) | Also fire a second “Open” |
| See **Modified** | Means you have a newer local save that can be checked in | |

---

## 6. Toolbar buttons (overview)

Typical order: **Set Working Directory** → **Add ▾** → **Open ▾** → **Checkout ▾** → **Check In ▾** → **Details** → **Copy to Vault** → **Remove ▾**.

| Button | Available when | Hidden when |
|--------|----------------|-------------|
| Set Working Directory | Inside Creo’s browser with a project workspace (Files page) | Hidden on the file **Details** page; otherwise stays greyed when not usable |
| Add ▾ | A project is open | No project |
| Open ▾ | A project is open (workspace) and/or a file can be opened (**Files** page) | No project and nothing to open; always hidden on the file **Details** page |
| Open selected… | A file you can open is selected | Nothing useful selected |
| Open workspace… | A project is open | No project |
| Checkout ▾ | Something can be checked out or undone (**Files** page) | Nothing to do; always hidden on the file **Details** page |
| Check In ▾ | Something can be checked in or added | Nothing pending |
| Details | One file selected | No file |
| Copy to Vault | Selected files are not already in the vault | Nothing to copy |
| Remove ▾ | Something can be removed (**Files** page) | Nothing selected; always hidden on the file **Details** page |
| Remove from Project | Files **and/or folders** selected (including empty folders) | Nothing selected |

Inactive top-level buttons and inactive items inside ▾ menus are **hidden** (not greyed out), so the toolbar only shows what you can use right now. Exception: **Set Working Directory** always stays visible on the Files page so it remains easy to find; it is greyed out outside Creo’s browser or when no project workspace is ready. On the file **Details** page (every tab, including History) Open, Checkout, Remove, Set Working Directory, and **Check In ▾** are all hidden — that toolbar is **Revert to selected…** only (when an older History row is selected). Check In stays on the Files page.

Only one ▾ menu open at a time. Click outside or press Escape to close.

---

## 7. Add ▾

Menu order:

1. **Create folder…**
2. **Add files…**
3. **Add folder…**
4. **Add folders…**

### Create folder…

| You do | App should | App must not |
|--------|------------|--------------|
| Choose Create folder… | Ask for a name; say whether it’s under the current folder or project root | |
| Enter a good name and Create | New empty folder appears in the list (no F5) | |
| Create while inside e.g. Drawings | Folder is created **inside Drawings** | Create it at project root by mistake |
| Leave the name blank | Show an error; stay on the dialog | Create anything |
| Enter `Foo/Bar` or `.hidden` | Reject with a clear error | Create weird or nested junk from one name |
| Use a name that already exists | Say it already exists | Overwrite what’s there |

### Add files…

| You do | App should | App must not |
|--------|------------|--------------|
| Pick or drop individual files | Copy them into the project at the current location | |
| Drop a whole folder tree | Tell you to use Add folder… / Add folders… | Quietly import the whole tree as “files” |
| Click Add with nothing chosen | Ask you to choose files first | Start an empty import |
| Click Add twice quickly | Say an add is already running | Run two imports at once |

### Add folder… (one folder, top level only)

| You do | App should | App must not |
|--------|------------|--------------|
| Pick one folder | Import only files sitting **directly** in that folder | Pull in files from subfolders |
| Folder only has files in subfolders | Explain that nothing top-level was found | Import nested files anyway |

### Add folders… (one or more folders, including subfolders)

| You do | App should | App must not |
|--------|------------|--------------|
| Pick folder trees | Keep the folder structure (e.g. Alpha/lib/part.prt stays nested) | Flatten everything to the project root |
| Pick several roots | Import each tree | Lose sibling folders |

On a normal office network (`http://…`), the app should try the CreoPDM agent’s folder picker first (more reliable than the browser’s).

---

## 8. Open, workspace, history

**Open ▾** menu (top → bottom):

1. **Open selected…**
2. **Open workspace…**

| You do | App should | App must not |
|--------|------------|--------------|
| **Open ▾ → Open workspace…** | Open this project’s local working folder on this PC (falls back to vault if needed) | |
| **Open ▾ → Open selected…** (or click a file name) | Offer how to open (see below); open in Creo or Windows; when the file is fetched to the local workspace, keep its vault folders (do not flatten); Creo opens from that folder so nested assemblies still resolve; when you are **not** checked out, align the local tip to the vault tip (remove newer local `.N` leftovers) | Fail silently with no message; put nested vault files at the workspace root; fail open just because the file lives under a vault subfolder; leave a newer local `.prt.N` after opening a vault tip you do not have checked out |
| **Details** (toolbar / double-click) | Open the file **Details** page on the **Overview** tab (first tab); page shows a **Details** title under the breadcrumb | Open the History tab by default; jump to History from a single-click on the file name |
| **Details** (file page) | Show a clear **Details** title near the top (under the breadcrumb, Library-sized), then the file name and tabs (Overview, History, …); same light panel background as Files; **Overview** Identity labels the model **Name** (not Number), shows **Date created** and **Date modified** only when modified differs (hide Date modified when it matches Date created), and omits content hash; date values keep the short stamp on screen and show a pretty hover title (e.g. Monday, July 23, 2026 at 5:30pm); skips duplicate identity fields (same name/instance) and omits Revision / Lifecycle / Checkout already shown in the header; use one body font and size on all Details tabs (no mixed monospace); file/open links use regular ink color (underline on hover), not accent/orange; bottom toolbar shows **Revert to selected…** on History only — never **Check In ▾**, **Open ▾**, **Set Working Directory**, **Checkout ▾**, or **Remove ▾** on Details | Show Check In, Open, Set Working Directory, Checkout, or Remove on Details; keep a separate History page title; keep a separate Version History view; label the model identity as Number; show content hash on Overview; always show Date modified when it equals Date created; omit created/modified dates; repeat header badges again in Overview Identity; mix monospace and UI fonts on Details tabs; use orange or accent-colored hyperlinks on Details |
| **Open ▾ → Open current…** | (Files page / file name) Open the **current** tip of this file | |
| Select an **older** History row → **Revert to selected…** (bottom toolbar, red like Remove) | Ask you to type the **exact** project name (same confirm dialog as Remove); explain that content and filename (including Creo `.prt.N`) restore to vault and local **in one step** (new version recorded — no Check In prompt); remove newer numbered siblings so the tip is not left as `.3` after reverting to `.1`; leave the file Available (not checked out); show Revert only when an older row is selected | Offer Revert for the current version, a pending unsaved row, or when this file has only one version; revert someone else’s checkout; proceed if the typed name is wrong or Cancel; keep a newer `.prt.N` name while only swapping bytes; leave Revert greyed at the top of the History list; leave a newer local cache save after vault restore; leave you checked out with a Check In prompt; show floating “choose an older row” hint text in the toolbar; use a plain browser `confirm` instead of typing the project name |
| **Copy to Vault** | Put a copy in the vault without checking out | Check the file out |

### When you open a file that’s not checked out to you

The app asks how you want to open it:

| You choose | App should |
|------------|------------|
| **Open without checking out** | Download what Creo needs into the local cache and open for view/reference — **no edit lock** |
| **Check out this file, then open** | Lock this file, download it, then open |
| **Check out this file and its companions, then open** | Lock this file plus related models Creo needs, then open |

Optional: **Set Creo working directory…** (on by default) points Creo at the local workspace folder.

If open seems to do nothing, check the error line under the toolbar, and that creopdm-agent is running on the Creo PC. Large downloads can take a while.

**Set Working Directory** (toolbar) does the same WD step on its own; it only applies inside Creo’s browser.

---

## 9. Checkout ▾

1. **Checkout selected**  
2. **Checkout project**  
3. **Undo Checkout**

| You do | App should | App must not |
|--------|------------|--------------|
| Checkout selected | Lock those files and download them for editing, keeping vault folder paths in the local workspace | Steal a file someone else has checked out; flatten nested files to the workspace root |
| Checkout project | Check out everything that’s free, keeping vault folder paths locally | Offer checkout when nothing is left; flatten nested files to the workspace root |
| Undo Checkout | Release **your** locks only | Undo someone else’s checkout; delete the vault file; create a new version |

---

## 10. Check In ▾

1. **Check in project…**  
2. **Check in selected…** (may say **Add selected…** if you’re only adding new files)

| You do | App should | App must not |
|--------|------------|--------------|
| Check in project… | Record pending saves and new files; release unchanged checkouts so the project looks checked in | Run when there’s nothing to do (button should stay disabled) |
| Check in selected… | Check in / add what you selected | |
| Leave the comment blank | Block check-in until you write a comment | Save a version with no comment |
| Finish successfully | List and status update to match the vault | |

---

## 11. Remove ▾

1. **Remove from Workspace** — trash local copies on this PC only; vault and project list unchanged  
2. **Purge workspace** — trash older local numbered saves that are below the vault version; vault unchanged  
3. **Remove from Vault** — delete CreoPDM’s vault copies; your original CAD folder stays; checkouts cancelled  
4. **Remove from Project** — remove from this project and delete vault copies; originals stay  

Destructive actions ask you to type the project name ([§12](#12-typing-the-project-name-to-confirm)).

### Remove from Workspace

| You do | App should | App must not |
|--------|------------|--------------|
| Select local “new” files on New files and remove | Move them to the Recycle Bin on this PC | Change the vault or project file list |
| Agent not running | Tell you to start creopdm-agent | |

### Purge workspace

| You do | App should | App must not |
|--------|------------|--------------|
| Confirm purge | Remove only older local saves; keep vault copy and newer local work | Delete anything from the vault |
| Nothing to purge | Say so; delete nothing | |

### Remove from Vault

| You do | App should | App must not |
|--------|------------|--------------|
| Confirm | Delete vault copies of the selection | Delete files in your original project folder on disk |

### Remove from Project

| You do | App should | App must not |
|--------|------------|--------------|
| Select files and/or folders (including empty folders) | Enable Remove from Project | Stay disabled just because a folder is empty |
| Confirm with the correct project name | Remove from the project; delete vault copies; **rows disappear right away** | Leave the folder/file visible until F5 |
| Optionally also delete local workspace | Clean local copies if you checked that box | Delete your original CAD source folder unless you asked for workspace cleanup |
| Type the wrong project name | Show an error; change nothing | Remove anything |
| Cancel | Change nothing | |
| File checked out by someone else | Skip that file with an error; may still remove others | Quietly remove their locked file |

---

## 12. Typing the project name to confirm

Used for delete project, remove from project/vault, purge, History **Revert to selected…**, and similar.

| You do | App should | App must not |
|--------|------------|--------------|
| Type the project name exactly | Allow Continue | |
| Typo, wrong case, or blank | Show “Type the project name exactly…” | Proceed |
| Cancel / Escape | Abort | Treat as confirm |

---

## 13. Quick walkthroughs

### Create → open → remove a folder

1. Open a project (any folder).  
2. **Add ▾ → Create folder…** → name `UxTest` → Create.  
3. Folder appears without F5.  
4. Click the **name** → you enter the folder; Creo stays connected if it was.  
5. Go up via the breadcrumb.  
6. Click the row **beside** the name → selected; Remove from Project is available.  
7. Confirm with the real project name.  
8. Folder is gone from the list immediately; no F5 needed.

Try the same with **Add folder…** and **Add folders…**.

### Things that should fail (and say why)

- Create folder with blank name, `Bad/Name`, or a duplicate name.  
- Remove with the wrong project name, or Cancel.  
- Click folder row chrome → must select, not open; click name → must open.  
- Add files… by dropping a whole folder tree → told to use Add folder(s).  
- Check In with an empty comment → blocked.  
- Check In ▾ with nothing pending → options stay disabled.

---

## 14. For developers (tests)

Automated coverage lives mainly in:

- `tests/unit/test_ui_regressions.py`
- `tests/unit/test_user_interaction_validations.py`
- `tests/integration/test_objects.py` (create folder / batch remove)
- `tests/integration/test_checkin.py` (History revert restores Creo `.prt.N` name, not tip overwrite)
- Related checkout / check-in / soft-nav tests

When you change any behavior above, update **this document** in the same change and add or adjust tests so the “must not” cases stay covered. See `.cursor/rules/user-interactions.mdc`.
