# User interactions — what you do, what CreoPDM should do

Plain-language guide for **manual testing**. For each action: what you do, what the app **should** do, and what it **must not** do.

After you add, remove, or open something, the Files list should update **on its own** — you should not need a hard browser refresh (F5).

Test in Creo’s built-in browser when you can (Creo connection matters there). A normal browser is fine for most list/toolbar checks. On a **phone**, see [§14 Mobile browse](#14-mobile-browse).

---

## Contents

1. [Moving around the app](#1-moving-around-the-app)
2. [Products (sidebar)](#2-products-sidebar)
3. [Finding and filtering files](#3-finding-and-filtering-files)
4. [Folders in the list](#4-folders-in-the-list)
5. [Files in the list](#5-files-in-the-list)
6. [Toolbar buttons (overview)](#6-toolbar-buttons-overview)
7. [Add ▾](#7-add-)
8. [Open, workspace, history](#8-open-workspace-history)
9. [Checkout ▾](#9-checkout-)
10. [Check In ▾](#10-check-in-)
11. [Export ▾](#11-export)
12. [Remove ▾](#12-remove-)
13. [Typing the product name to confirm](#13-typing-the-product-name-to-confirm)
14. [Mobile browse](#14-mobile-browse)
15. [Administration (users, roles, membership, email)](#15-administration-users-roles-membership-email)
16. [Quick walkthroughs](#16-quick-walkthroughs)
17. [For developers (tests)](#17-for-developers-tests)

---

## 1. Moving around the app

| You do | App should | App must not |
|--------|------------|--------------|
| Click a product, folder breadcrumb, or Administration / Settings | Show the new page quickly; if Creo was connected, it **stays** connected | Flash “Creo: Session offline” or drop the Creo link just because you changed folders; hard-reload the page during a folder/product switch |
| Sign in as **Viewer** | View products (`products.view`); open/download files and use **Details** (Overview/History) via the bottom toolbar or double-click (`objects.view`); Open without checking out (**no Open dialog** — only one choice) | See Add / Checkout / Check In / Remove / Export ▾, New product, Copy to Vault, or “Check out … then open” in the Open dialog |
| Sign in with Administration only (no `products.view`) | Land on **Administration**; breadcrumb has no **Products** link; visiting `/` redirects to `/admin` | See a JSON error; see a Products crumb that opens Files |
| Sign in with a role that has **no permissions** | Land on a clear **No Files access** page (not JSON); product APIs stay **403** | Use the app as if signed in with Viewer |
| Add or remove files/folders | Update the list so it matches reality | Leave old rows on screen until you press F5 |
| Wait while something big runs (Add, Remove, Check In…) | Show a busy message so you know it’s working | Sit frozen with no feedback |

---

## 2. Products (sidebar)

| You do | App should | App must not |
|--------|------------|--------------|
| Click a product | Open that product’s Files list | Lose track of which product you picked |
| Collapse / expand the sidebar | Hide or show the product list | Break the Files list |
| Click **New** | Ask for a product name (and vault name options); then show the new product | Create a product with a blank name |
| Open Files with **no** products (and you **can** create products) | Show the empty hero inviting you to create a product | |
| Open Files with **no** products (and you **cannot** create products) | Show that no products are available; ask an administrator for access | Tell you to “Create a product…” when you have no `products.create` |
| Open an **empty** product (and you **can** add files) | Show that there are no files and invite you to add a Creo model, PDF, or document | |
| Open an **empty** product (and you **cannot** add files) | Show that there are no files | Tell you to “Add a Creo model…” when you have no `objects.add` |
| Rename (product settings) | Update the name everywhere you see it | |
| **Rebuild Where Used** / **Collect all metadata** (product gear) | Show only inside Creo’s embedded browser when Creo.JS is connected (and you have metadata permission); hide when the product is read-only or not **In work**; hide in Chrome/Edge and when Session offline. **Collect** shows the same busy overlay as Add (progress count) and blocks navigation / product switch / delete until it finishes (or you cancel); do not flash a stuck “Loading…” overlay when you try to leave mid-Collect | Show those items in a standalone browser; Collect without Creo.JS; show when the product is read-only / On hold / Released / Closed / Archived; let you browse away mid-Collect and leave it half done; leave a “Loading…” busy state after a blocked product click |
| Product is **read only** or not **In work** | Show the product state badge next to the product name (same blue-dot style as file State); show a short banner (“This product is **On Hold**.” / “This product is **read only**.”) without listing blocked actions; **Checkout** column shows **Read only** / **On hold** / etc. (not **Available**); hide Add, **Checkout selected**, **Checkout product**, Check In, Remove from Product, Rename, Delete product, Collect, Rebuild; keep **Undo Checkout** / **Force Undo Checkout** when the role allows; selecting a folder must not enable checkout; API rejects those mutations (including product delete). Open / History / Copy to workspace still work. **Archived** products are hidden from the Files list (restore from Administration → Products) | Leave Checkout selected / Checkout product / Check In visible when the product cannot be modified; allow Delete/Rename while read-only; show Archived in the normal Files product list; hide the product state from the Files header; show **Available** in Checkout when checkout is blocked; list every blocked action in the banner; let folder select offer Checkout selected |
| Open a product on Files | Always show the current product state next to the name (**In Work**, **On Hold**, …); append **Read only** on the badge when that flag is set | Only show state in Administration |
| Click the **bell** next to the gear (when Email notifications are enabled) | Ask to confirm Watch / Stop watching; then toggle **your** watching state for that product | Change watching when you Cancel the confirmation; show the bell when notifications are disabled; show another user’s watching state as your own |
| Watch a product with a valid account email | Receive email summaries for adds, removes, checkout, undo checkout, check-in, restore, and product rename/info (not for browse or background scans); no historical mail | Email yourself for your own actions |
| Log in as a different user after someone else watched | Show **not** watching unless **you** subscribed; keep the other user’s subscription | Steal or clear another user’s watch when you open the product or click Stop on your own bell |
| Open a product when your account email is invalid | Show the bell disabled with a clear reason | Let you subscribe until email is fixed |
| **Force Undo Checkout** (role permission) | Release another user’s checkout without a new version; email that user when notifications are enabled (they need a valid account email; watching is not required) | Show without `objects.force_undo_checkout`; commit a version |
| Delete product | Ask you to type the **exact** product name; remove CreoPDM’s copy of the product | Delete your original CAD folders on disk just because you deleted the product; delete if you typed the wrong name |

**Name rules (new / rename)**

- Product name is required.
- Custom vault/workspace name: no spaces; or use the hash option instead.

---

## 3. Finding and filtering files

| You do | App should | App must not |
|--------|------------|--------------|
| Click a breadcrumb (Home / folder path) | Take you to that folder; Creo stays connected | |
| Type in Search | Show matching files across the product. Plain text is a substring match; `*` / `?` wildcards work (`*.prt`, `*.prt.*`, …). Hover the search box for short examples | Treat `*.prt` as literal characters to find |
| Clear Search | Show the normal folder view again | Bring back folders/files you already removed |
| Click a metric (Parts, Assemblies, …) | Filter and select those files; click again to clear | Jump into a folder or leave the page |
| Click **Modified** | Filter and select files with local changes you can check in; click again to clear. **Modified** pill count matches rows shown as Modified (including after local/agent detection) | Select unmodified checkouts or someone else’s files; leave the pill at 0 while a row shows Modified |
| Click **Checked out** | Filter and select checked out files in the current group; click again to clear | |
| Switch tabs: **Files** / **Checked out** / **New files** | Show that list; show Add/Check In help blurbs only when those actions are available (role ∩ product state) | Tell you to Add or Check In when you cannot do those actions |
| Click a column header | Sort; click again to reverse | |

**New files tab** shows files waiting in the **vault** (and sometimes local cache) that aren’t fully in the product yet. Deleting only from your PC workspace does **not** clear vault “new” files — those live on the CreoPDM vault until you remove them from there. The Add/Check In help blurb shows only when you can Add **and** Check In; otherwise it is hidden (files can still list; local workspace remove may still work).

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
| See **Modified** | Means you have a newer local save **or** a same-name workspace replace (different size or content hash than the vault tip) that can be checked in | |

---

## 6. Toolbar buttons (overview)

Typical order: **Set Working Directory** → **Add ▾** → **Open ▾** → **Checkout ▾** → **Check In ▾** → **Details** → **Copy to Vault** → **Export ▾** → **Remove ▾**.

| Button | Available when | Hidden when |
|--------|----------------|-------------|
| Set Working Directory | Inside Creo’s browser **and** Creo.JS connected, with a product workspace (Files page) | Hidden outside Creo, when Creo is not connected, and on the file **Details** page |
| Add ▾ | A product is open **and** the product allows edits (In work, not read-only) | No product; product is read-only / On hold / Released / Closed / Archived |
| Open ▾ | A product is open (workspace) and/or a file can be opened (**Files** page) | No product and nothing to open; always hidden on the file **Details** page |
| Open selected… | A file you can open is selected | Nothing useful selected |
| Open workspace… | A product is open **and** creopdm-agent is running on this PC | No product; agent offline (do not offer a host-vault fallback) |
| Checkout ▾ | Something can be checked out, undone, or force-undone (**Files** page). On a locked product, **Undo Checkout** / **Force Undo Checkout** may still appear | Nothing to do; always hidden on the file **Details** page |
| Check In ▾ | Something can be checked in or added **and** the product allows edits | Nothing pending; product is locked (read-only / not In work) |
| Details | One file selected | No file |
| Copy to Vault | You have **Copy to Vault** permission and selected files are not already in the vault | Nothing to copy; role lacks `objects.copy_to_vault` (hidden for Viewer / Engineer by default) |
| Export ▾ | A product is open **and** you have `products.export` and/or `objects.export`. Works on locked / Released products | No product; role lacks both export permissions; always hidden on the file **Details** page |
| Remove ▾ | Something can be removed (**Files** page). Local workspace remove/purge still work on a locked product | Nothing selected; always hidden on the file **Details** page |
| Remove from Product | Files **and/or folders** selected (including empty folders); product allows edits | Nothing selected; product is locked |
| Remove from Vault | Selected vault files; product allows edits | Nothing selected; product is locked |

Inactive top-level buttons and inactive items inside ▾ menus are **hidden** (not greyed out), so the toolbar only shows what you can use right now. Same rule for **permissions** and **product lock** (read-only / not In work): the server builds one `product_ui` flag set (role ∩ product state) and the page only shows those controls — if the signed-in role cannot do an action (or the PC cannot — e.g. Open workspace without creopdm-agent), **do not show the control**. **Set Working Directory**, **Collect all metadata**, and **Rebuild Where Used** follow the same rule: show only inside Creo when Creo.JS is connected (embedded browser); hide them outside Creo / when Session offline. Set Working Directory also needs a product workspace ready and stays hidden on the file **Details** page. On the file **Details** page (every tab, including History) Open, Checkout, Remove, Set Working Directory, and **Check In ▾** are all hidden — that toolbar is **Revert to selected…** only (when an older History row is selected). Check In stays on the Files page.

Only one ▾ menu open at a time. Click outside or press Escape to close.

---

## 7. Add ▾

Menu order:

1. **Create folder…**
2. **Add files…**
3. **Add folder…**
4. **Add folders…**
5. **Compressed data…**

### Create folder…

| You do | App should | App must not |
|--------|------------|--------------|
| Choose Create folder… | Ask for a name; say whether it’s under the current folder or product root | |
| Enter a good name and Create | New empty folder appears in the list (no F5) | |
| Create while inside e.g. Drawings | Folder is created **inside Drawings** | Create it at product root by mistake |
| Leave the name blank | Show an error; stay on the dialog | Create anything |
| Enter `Foo/Bar` or `.hidden` | Reject with a clear error | Create weird or nested junk from one name |
| Use a name that already exists | Say it already exists | Overwrite what’s there |

### Add files…

| You do | App should | App must not |
|--------|------------|--------------|
| Pick or drop individual files | Copy them into the product at the current location | |
| Pick a very large multi-select (hundreds/thousands) | Keep a busy message after the OS picker closes while it resolves latest numbered saves, then show the Add dialog summary; warn before starting a bulk Add | Sit frozen with the Add dialog closed and no busy feedback after you confirm the OS picker |
| Drop a whole folder tree | Tell you to use Add folder… / Add folders… | Quietly import the whole tree as “files” |
| Click Add with nothing chosen | Ask you to choose files first | Start an empty import |
| Click Add twice quickly | Say an add is already running | Run two imports at once |

For thousands of Creo models, prefer **Add folders…** (picks a folder and lists files on the agent) over multi-select in **Add files…**.

### Add folder… (one folder, top level only)

| You do | App should | App must not |
|--------|------------|--------------|
| Pick one folder | Import only files sitting **directly** in that folder | Pull in files from subfolders |
| Folder only has files in subfolders | Explain that nothing top-level was found | Import nested files anyway |
| Leave **Keep chosen folder name** on | Store as `Library/part.prt` under the current location | |
| Turn **Keep chosen folder name** off | Store as `part.prt` in the current location | Still create a `Library/` folder just because you picked that disk folder |

### Add folders… (one or more folders, including subfolders)

| You do | App should | App must not |
|--------|------------|--------------|
| Pick folder trees | Keep nested structure under each chosen folder | Flatten everything to a single basename pile |
| Leave **Keep chosen folder name** on | Keep the chosen folder name (e.g. `Alpha/lib/part.prt`) | |
| Turn **Keep chosen folder name** off | Omit the chosen folder name (`lib/part.prt` in the current location) | Drop nested subfolders when the option is only meant to omit the outer folder name |
| Pick several roots | Import each tree | Lose sibling folders |

On a normal office network (`http://…`), the app should try the CreoPDM agent’s folder picker first (more reliable than the browser’s).

### Compressed data…

| You do | App should | App must not |
|--------|------------|--------------|
| Choose **Compressed data…** | Open a dialog that explains the zip import; require creopdm-agent | Jump straight to a picker with no explanation; run without the agent |
| Click **Choose zip…** | Use the same agent file picker as **Add files…**, but with **Zip archives (*.zip)** as the default filter; after you pick, return to the dialog showing the chosen path | Default to Creo models; invent a separate picker endpoint |
| Click **Import** with a `.zip` chosen | Show a busy overlay while the agent uploads and the server extracts + imports; then refresh Files so new rows appear | Leave you with a half-done list and no busy feedback |
| Pick a non-`.zip` file | Say to choose a `.zip` | Upload it anyway |
| Zip has one top-level folder only (e.g. `MyExport/…`) | Strip that outer folder and import under the **current** Files location | Keep an extra `MyExport/` layer just because of how the zip was packed |
| Zip has folders and files | Keep nested structure under the current location (same idea as **Add folders…**) | Flatten everything to basenames; create empty folders from empty zip dirs |
| File already in the product | Fail that entry (same as Add); import the rest; show a summary | Overwrite vault content or auto-rename CAD files |
| Zip over 2 GB, password-protected, or corrupt | Clear error; add nothing | Hang or invent content |
| Junk (`.DS_Store`, `__MACOSX`, Thumbs.db, ignore patterns) | Skip like other Add paths | Import OS metadata junk as product files |

---

## 8. Open, workspace, history

**Open ▾** menu (top → bottom):

1. **Open selected…**
2. **Open workspace…**

| You do | App should | App must not |
|--------|------------|--------------|
| **Open ▾ → Open workspace…** | Open this product’s local working folder on this PC via creopdm-agent; if nothing has been checked out / materialized yet, create the empty local folder and open it | Open a folder on the CreoPDM Linux host; show the item when the agent is offline; fail with a raw WinError just because the local cache is still empty |
| **Open ▾ → Open selected…** (or click a file name) | Offer how to open (see below); open in Creo or Windows; when the file is fetched to the local workspace, keep its vault folders (do not flatten); Creo opens from that folder so nested assemblies still resolve; when you are **not** checked out, align the local tip to the vault tip (remove newer local `.N` leftovers); **outside** Creo’s embedded browser (or when Open mode is OS association), download via creopdm-agent and open with the **Windows association** (or browser download if the agent is offline) | Fail silently with no message; put nested vault files at the workspace root; fail open just because the file lives under a vault subfolder; leave a newer local `.prt.N` after opening a vault tip you do not have checked out; require Creo’s embedded browser when Open mode is association |
| **Details** (toolbar / double-click) | Open the file **Details** page on the **Overview** tab (first tab); page shows a **Details** title under the breadcrumb | Open the History tab by default; jump to History from a single-click on the file name |
| **Details** (file page) | Show a clear **Details** title near the top (under the breadcrumb, Library-sized), then the file name and tabs (Overview, History, …); **Where Used** only for files whose extension is in **Settings → Creo Models**; same light panel background as Files; **Overview** Identity labels the model **Name** (not Number), shows **Date created** and **Date modified** only when modified differs (hide Date modified when it matches Date created), and omits content hash; date values keep the short stamp on screen and show a pretty hover title (e.g. Monday, July 23, 2026 at 5:30pm); skips duplicate identity fields (same name/instance) and omits Revision / Lifecycle already shown in the header; when the file is checked out, **Overview → Checkout** shows **Checked out by** and **Checked out** (when), and the header checkout badge has a pretty hover for when; use one body font and size on all Details tabs (no mixed monospace); file/open links use regular ink color (underline on hover), not accent/orange; bottom toolbar shows **Revert to selected…** on History only — never **Check In ▾**, **Open ▾**, **Set Working Directory**, **Checkout ▾**, or **Remove ▾** on Details | Show Where Used for Documents / Other / non–Creo Models extensions; Show Check In, Open, Set Working Directory, Checkout, or Remove on Details; keep a separate History page title; keep a separate Version History view; label the model identity as Number; show content hash on Overview; always show Date modified when it equals Date created; omit created/modified dates; hide who/when for an active checkout; repeat Revision / Lifecycle header badges again in Overview Identity; mix monospace and UI fonts on Details tabs; use orange or accent-colored hyperlinks on Details |
| **Open ▾ → Open current…** | (Files page / file name) Open the **current** tip of this file | |
| Select an **older** History row → **Revert to selected…** (bottom toolbar, red like Remove) | Ask you to type the **exact** product name (same confirm dialog as Remove); explain that content and filename (including Creo `.prt.N`) restore to vault and local **in one step** (new version recorded — no Check In prompt); remove newer numbered siblings so the tip is not left as `.3` after reverting to `.1`; leave the file Available (not checked out); show Revert only when an older row is selected | Offer Revert for the current version, a pending unsaved row, or when this file has only one version; revert someone else’s checkout; proceed if the typed name is wrong or Cancel; keep a newer `.prt.N` name while only swapping bytes; leave Revert greyed at the top of the History list; leave a newer local cache save after vault restore; leave you checked out with a Check In prompt; show floating “choose an older row” hint text in the toolbar; use a plain browser `confirm` instead of typing the product name |
| **Copy to Vault** | Put a copy in the vault without checking out (requires `objects.copy_to_vault`; starter: Administrator + PDM Manager only) | Check the file out; show the button to Viewer / Engineer by default |

### When you open a file that’s not checked out to you

If you **cannot** check out (Viewer role, no `objects.checkout`, or the file is not free to check out), the app **opens immediately** — no dialog. There is only “open without checking out,” so asking is pointless.

Otherwise the app asks how you want to open it:

| You choose | App should |
|------------|------------|
| **Open without checking out** | Download what Creo needs into the local cache and open for view/reference — **no edit lock** |
| **Check out this file, then open** | Lock this file, download it, then open |
| **Check out this file and its companions, then open** | Lock this file plus related models Creo needs, then open |

**Set Creo working directory…** appears on that dialog **only inside Creo’s embedded browser** (on by default). Outside Creo (Chrome/Edge/etc.) it is hidden and is never applied — working directory only exists in Creo. Use the toolbar **Set Working Directory** the same way (Creo only).

If open seems to do nothing, check the error line under the toolbar, and that creopdm-agent is running on the Creo PC. Large downloads can take a while.

**Settings → Open Creo models with:** **Embedded** options (help + Creo.JS path) sit under that radio and are grayed out when **OS file association** is selected. Embedded only uses Creo.JS inside Creo’s embedded browser; otherwise Open uses the OS association. The top-bar Creo pill shows session only (**Creo: Connected** / **Creo: Session offline**), not the open-mode name.

**Set Working Directory** (toolbar) does the same WD step on its own; it only appears inside Creo’s browser when Creo.JS is connected.

---

## 9. Checkout ▾

1. **Checkout selected**  
2. **Checkout product**  
3. **Undo Checkout**  
4. **Force Undo Checkout** (only with `objects.force_undo_checkout`)

| You do | App should | App must not |
|--------|------------|--------------|
| Checkout selected | Lock those files and download them for editing, keeping vault folder paths in the local workspace | Steal a file someone else has checked out; flatten nested files to the workspace root; appear without `objects.checkout` |
| Checkout product | Check out everything that’s free, keeping vault folder paths locally | Offer checkout when nothing is left; flatten nested files to the workspace root; appear without `objects.checkout` |
| Undo Checkout | Release **your** locks only | Undo someone else’s checkout; delete the vault file; create a new version; appear without `objects.checkout` |
| Force Undo Checkout | Release **another user’s** checkout lock (abandoned checkout); no new version; confirm first; email the former owner when Email notifications are enabled | Appear without `objects.force_undo_checkout`; commit a new version; delete the vault file; unlock Checkout selected/product without `objects.checkout` |

---

## 10. Check In ▾

1. **Check in product…**  
2. **Check in selected…** (may say **Add selected…** if you’re only adding new files)

| You do | App should | App must not |
|--------|------------|--------------|
| Check in product… | Record pending saves and new files (including same-name workspace replaces with no new Creo `.N`); release unchanged checkouts so the product looks checked in | Treat a replaced workspace file as unchanged / only Undo checkout when its size or content hash differs from the vault tip; run when there’s nothing to do (button should stay disabled); appear without `objects.checkin` |
| Check in selected… | Check in / add what you selected | Appear without `objects.checkin` (Add new files still uses Add ▾ / `objects.add`) |
| Leave the comment blank | Block check-in until you write a comment | Save a version with no comment |
| Finish successfully | List and status update to match the vault | |

---

## 11. Export ▾

Toolbar menu **Export ▾** (same pattern as Check In ▾). Confirm, then busy overlay, then save the zip (creopdm-agent Save As when available; otherwise browser download).

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Export ▾** | Show **Export product…** (when you have `products.export`) always enabled; show **Export selected…** (when you have `objects.export`) greyed out until files or folders are selected | Hide **Export product…** just because nothing is selected; require the product to be In work |
| Click **Export product…** | Confirm whole-product export in the CreoPDM dialog; zip the vault tip for every file; require `products.export` | Check out or lock anything; use a browser `confirm`; switch to selection export because something is selected |
| Click **Export selected…** with files and/or folders selected | Confirm selection export in the CreoPDM dialog; zip only those vault tip files (folders include descendants); require `objects.export` | Run while the menu item is greyed (nothing selected); appear without `objects.export`; use a browser `confirm` |
| Cancel the confirm or Save dialog | Stop with no zip | Leave a partial download claimed as success |
| Agent offline | Fall back to a browser zip download | Fail only because the agent is offline |

Starter roles: Administrator, PDM Manager, and Engineer get both export permissions. Viewer does not.

---

## 12. Remove ▾

1. **Remove from Workspace** — trash local copies on this PC only; vault and product list unchanged  
2. **Purge workspace** — trash older local numbered saves that are below the vault version; vault unchanged  
3. **Remove from Vault** — delete CreoPDM’s vault copies; your original CAD folder stays; checkouts cancelled  
4. **Remove from Product** — remove from this product and delete vault copies; originals stay  

Destructive actions ask you to type the product name ([§13](#13-typing-the-product-name-to-confirm)).

### Remove from Workspace

| You do | App should | App must not |
|--------|------------|--------------|
| Select local “new” files on New files and remove | Move them to the Recycle Bin on this PC | Change the vault or product file list |
| Agent not running | Tell you to start creopdm-agent | |

### Purge workspace

| You do | App should | App must not |
|--------|------------|--------------|
| Confirm purge | Remove only older local saves; keep vault copy and newer local work | Delete anything from the vault |
| Nothing to purge | Say so; delete nothing | |

### Remove from Vault

| You do | App should | App must not |
|--------|------------|--------------|
| Confirm | Delete vault copies of the selection | Delete files in your original product folder on disk |

### Remove from Product

| You do | App should | App must not |
|--------|------------|--------------|
| Select files and/or folders (including empty folders) | Enable Remove from Product | Stay disabled just because a folder is empty |
| Confirm with the correct product name | Remove from the product; delete vault copies; **rows disappear right away** | Leave the folder/file visible until F5 |
| Optionally also delete local workspace | Clean local copies if you checked that box | Delete your original CAD source folder unless you asked for workspace cleanup |
| Type the wrong product name | Show an error; change nothing | Remove anything |
| Cancel | Change nothing | |
| File checked out by someone else | Skip that file with an error; may still remove others | Quietly remove their locked file |

---

## 13. Typing the product name to confirm

Used for delete product, remove from product/vault, purge, History **Revert to selected…**, and similar.

| You do | App should | App must not |
|--------|------------|--------------|
| Type the product name exactly | Allow Continue | |
| Typo, wrong case, or blank | Show “Type the product name exactly…” | Proceed |
| Cancel / Escape | Abort | Treat as confirm |

---

## 14. Mobile browse

Phone-only **browse** mode (portrait or landscape). No Add / Checkout / Check In / Remove — look up files and open **folders** only.

### When it turns on

| You do | App should | App must not |
|--------|------------|--------------|
| Open CreoPDM on a **phone** (Safari/Chrome), portrait or landscape | Switch to browse-only layout | Stay in full desktop chrome with pills and bottom toolbar |
| Rotate the phone to landscape | **Keep** browse-only | Flash back to desktop pills/buttons just because the width got wider |
| Narrow Creo’s **desktop** browser (mouse) | Keep full desktop UI (toolbar, pills, Settings, Creo status) | Treat a skinny Creo window as a phone |

### What you see / don’t see

| You do | App should | App must not |
|--------|------------|--------------|
| Look at the top bar | Show CreoPDM brand and **Logout**; hide Administration, display name, and Creo status pills | Hide Logout; show Administration / Creo status / name pills on a phone |
| Look at the product header | Show product name and search; hide **New**, gear, and metric chips (Files / Parts / …) | Show New product, product gear, or filter pills |
| Look at the bottom | No toolbar | Show Set Working Directory, Add, Open, Checkout, Check In, or Remove |
| Open a file’s Details page | No bottom Details toolbar (no Revert / Check In chrome) | Show the desktop Details action bar |

### Lists and columns

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Files** or **Files checked out** | Show **Name** and **Rev** only | Force sideways scrolling for State / Type / Creo / Modified / Checkout |
| Open **New files** | Show **Filename** only | Crush headers into vertical “CHANGE” / “FILENAME ()” text |
| See an empty list | Full-width message; hide the useless column header row | Leave broken header cells beside the empty message |

### Opening things

| You do | App should | App must not |
|--------|------------|--------------|
| Tap a **folder** name | Open that folder (browse deeper) | |
| Tap a **file** name or file row | Do nothing (no Creo/Windows open, no jump to Details) | Open the model or Details from a file tap |
| Double-tap / long-press a file row | Still not open the file or Details | Treat it like desktop double-click → Details |

### Quick phone checks

1. Phone portrait → brand + Logout; no Administration/Creo/name pills; no bottom toolbar; Files shows Name + Rev.  
2. Rotate to landscape → still browse-only (no pills/buttons coming back except Logout).  
3. Tap a folder → enters folder; tap a file → nothing opens.  
4. On a PC, shrink Creo’s browser narrow → still full desktop UI (not browse-only).

---

## 15. Administration (users, roles, membership, email)

Use a normal browser for these checks. You need the matching Administration permission for each tile.

### First-run setup

| You do | App should | App must not |
|--------|------------|--------------|
| Open the app when **no users** exist yet | Send you to **Create administrator** (`/setup`) | Let you use Files / login as if accounts already exist |
| Create the first admin with display name, username, **email**, and password | Create an **Administrator** with **All products**, sign you in, and take you to the app | Accept a blank email or an incomplete address like `user@host` (no domain suffix); leave email optional |
| Try `/setup` again after any user exists | Redirect to login | Create a second “first” admin |

### Sign in and forgot password

| You do | App should | App must not |
|--------|------------|--------------|
| Open `/login` with no recent failure | Show username + password only | Show **Forgot password?** before a failed attempt |
| Enter a wrong password for a **known active** username | Show an error and a **Forgot password?** control under the password field (tied to that username) | Show **Forgot password?** for an unknown username, a **disabled** account, empty fields, or other validation failures |
| Open `/forgot-password` or `/forgot-password?username=…` in the address bar | Redirect to sign-in | Ever show the forgot form from a typed GET URL |
| Change the username field after a wrong-password offer, then use **Forgot password?** | Hide the control (in the browser) and reject/clear the grant on the server | Keep using the previous username’s forgot grant |
| Use **Forgot password?** (after that wrong-password attempt) + any well-formed email | Show the same “if that email matches…” confirmation either way; send a 10-minute reset link **only** when email matches that username; spend the grant so they cannot keep guessing | Tell them the email did not match; leave the form open for more guesses; accept email alone; let them change the username on the form |
| Open the reset link and set a new password | Show username as a disabled field; update password and send you to sign in | Allow reset without username; accept a link older than 10 minutes; reuse the same link afterward |
| Spam forgot-password for one account | After many tries in 24 hours, disable that account (not full Administration) and email the administrator address | Keep a non-admin account open under reset spam |

### Users

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Add user** with spaces or symbols in the username (e.g. `Pat O'Neil`, `a@b`) | Reject with a clear validation error | Accept spaces or special characters |
| Open **Add user** | Require display name, username, **email**, role (if you can assign), status, and initial password | Treat email as optional; let you set product membership on this form |
| Enter email `dfdsf@ca` / `sdfsdf@ss` or other non-`name@domain.tld` values | Reject with a clear validation error (browser and server) | Save incomplete domains or bare TLDs like `@ca` |
| Save a new user | Create the account with **no product access**; point you to **Membership** to grant access; return to the Users list | Give the new user All products or any product by default |
| Edit a user and clear email | Reject with “Email is required” (or equivalent) and keep the previous address | Save a blank email |
| Open the Role dropdown (with `roles.assign`) as a **full administrator** | List **every** role, including Administrator | Hide lower roles or block assigning Administrator |
| Open the Role dropdown (with `roles.assign`) without full Administration | List only roles with **fewer** permissions than yours (not your role, not a peer, not a higher role) | Offer your own role, a peer role, or a higher role |
| Try to change **your own** role or status | Block the change and tell you to ask another administrator | Let you demote or disable yourself |

### Membership

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Membership** | Show a hub with **By product** and **By user**, plus a short products summary | Put product checkboxes on the user Add/Edit form |
| Open **By user** → a person | Let you set **All products** or pick specific products, then Save | Leave Files still showing every product when that user is restricted |
| Open **By product** → a product | Let you add/remove members for that product | |

### Roles

| You do | App should | App must not |
|--------|------------|--------------|
| Edit permissions on a role | Save when at least one ACTIVE user still has full CreoPDM Administration (including `email.manage`) | Strip the last full admin’s Administration set |
| Change name / description / Administration checkboxes on **your own** role | Reject the change | Let you lock yourself out of Administration |

### Email (Administration → Email)

Needs `email.manage`.

| You do | App should | App must not |
|--------|------------|--------------|
| Open Email | Show enable, **Local Postfix** vs **Authenticated SMTP**, From address, administrator email, and Test email | |
| Choose **Local Postfix** | Use `127.0.0.1:25` on the CreoPDM server (no username/password panel) | Require SMTP credentials for Local |
| Choose **Authenticated SMTP** | Show host, port, TLS, auth, username/password | |
| Disable email notifications and open a product | Hide the watch bell on Files | Leave the bell visible while notifications are off |
| Change delivery settings, then **Send test email** without Save | Block with a message to Save first | Send using unsaved settings |
| Change only To / Subject / Message, then Send test | Send using the **saved** delivery settings (no Save required for those three fields) | |
| Save, then Send test | Deliver to the test recipient (or administrator email if To is blank) | |

---

## 16. Quick walkthroughs

### Create → open → remove a folder

1. Open a product (any folder).  
2. **Add ▾ → Create folder…** → name `UxTest` → Create.  
3. Folder appears without F5.  
4. Click the **name** → you enter the folder; Creo stays connected if it was.  
5. Go up via the breadcrumb.  
6. Click the row **beside** the name → selected; Remove from Product is available.  
7. Confirm with the real product name.  
8. Folder is gone from the list immediately; no F5 needed.

Try the same with **Add folder…**, **Add folders…**, and **Compressed data…** (agent + `.zip`).

### Things that should fail (and say why)

- Create folder with blank name, `Bad/Name`, or a duplicate name.  
- Remove with the wrong product name, or Cancel.  
- Click folder row chrome → must select, not open; click name → must open.  
- Add files… by dropping a whole folder tree → told to use Add folder(s).  
- Check In with an empty comment → blocked.  
- Check In ▾ with nothing pending → options stay disabled.  
- On a phone: tap a file name → must not open; shrink Creo on desktop → must not enter browse-only.  
- Setup / Add user / Edit user with blank email → blocked.  
- Setup / Add user with spaces or special characters in username → blocked.  
- Setup / Add user with `dfdsf@ca` or `sdfsdf@ss` (no real domain) → blocked.  
- Add user → new account has no products until Membership grants them.  
- Role dropdown → your own role / a peer role / a higher role must not appear.  
- Email admin: change SMTP fields then Send test without Save → blocked.
- Cancel Watch / Stop watching confirmation → subscription unchanged.
- Notifications disabled → no product watch bell on Files.
- User A watches; user B opens the same product → B is not watching; B’s Stop does not clear A.

---

## 17. For developers (tests)

Automated coverage lives mainly in:

- `tests/unit/test_ui_regressions.py` (includes `test_mobile_browse_css_is_minimal`, `test_details_where_used_tab_gated_on_creo_models`)
- `tests/unit/test_user_interaction_validations.py`
- `tests/integration/test_objects.py` (create folder / batch remove)
- `tests/integration/test_checkin.py` (History revert restores Creo `.prt.N` name, not tip overwrite)
- `tests/unit/test_auth.py` (role matrix + Roles admin + Viewer `products.view` / `objects.view` / `data-can-checkout`; empty-home `products.create` hero; empty-product `objects.add` invite; `test_every_starter_role_login_permission_matrix`; `test_role_with_no_permissions_cannot_browse`; `test_admin_without_products_view_lands_on_administration`; `test_setup_and_admin_user_require_email`; `test_username_rejects_spaces_and_email_needs_domain`; `test_admin_email_settings_save_and_gate`; `test_admin_membership_product_access_filters_products`; `test_role_assign_must_be_strictly_below_actor`; new users default to no product access)
- `tests/unit/test_password_reset.py` (forgot link only after wrong password; GET blocked; wrong email same confirmation / one try; spam disable)
- `tests/unit/test_product_watch.py` (bell when email enabled; per-user watch; subscribe/unsubscribe; one email per bulk action; actor excluded; notifications off skips mail; Force Undo Checkout emails former owner)
- `tests/unit/test_launch.py` / `tests/unit/test_creopdm_agent.py` (Open workspace creates empty agent cache and opens via ShellExecute explore)
- `tests/integration/test_settings.py` (Settings open-mode copy mentions OS association fallback)
- `tests/integration/test_creo_metadata.py` (Collect / Rebuild Where Used gear items are `creo-session-only`, hidden until Creo.JS is connected; Details **Where Used** only for Settings → Creo Models extensions)
- `tests/integration/test_checkout.py` (product lock UI: ON_HOLD / read-only hide Add & Check In; Checkout stays for Undo)
- `tests/integration/test_product_lifecycle_lock.py` (locked product rejects add/checkout/check-in/remove/rename/metadata/delete/forget; undo still allowed)
- `tests/unit/test_product_state.py` (allows_mutation / ensure helpers / `product_ui_capabilities`)
- `tests/unit/test_product_access_policy_contract.py` (mutation modules call `ensure_*`; templates use `product_ui`; `app.js` does not re-encode lock)
- Related checkout / check-in / soft-nav tests

Mobile browse is CSS-only in `app.css`: `@media` with `pointer: coarse` and `hover: none` (plus width/height limits). Do **not** gate browse mode on `max-width` alone.

When you change any behavior above, update **this document** in the same change and add or adjust tests so the “must not” cases stay covered. See `.cursor/rules/user-interactions.mdc`.
