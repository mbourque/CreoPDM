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
13. [Entering your password to confirm](#13-entering-your-password-to-confirm)
14. [Mobile browse](#14-mobile-browse)
15. [Administration (users, roles, membership, email, utilities, system settings)](#15-administration-users-roles-membership-email-utilities-system-settings)
16. [Quick walkthroughs](#16-quick-walkthroughs)
17. [For developers (tests)](#17-for-developers-tests)

---

## 1. Moving around the app

| You do | App should | App must not |
|--------|------------|--------------|
| Click around the signed-in app (product, folder breadcrumb, **Details** / History tab, double-click a file, Administration including Products/Membership/Email/Utilities, System Settings, account password) | Soft-nav the shell so Creo **stays Connected**; if Creo.JS is live, the pill shows **Connected** (not a stale Session offline) when **Set Working Directory** is shown; inside Creo’s embedded browser while Creo.JS is still linking, show a **Connecting to Creo…** overlay that blocks clicks until Connected (or ~15s), then clear it — never in Chrome/Edge and **never on Logout → sign-in** (`/login` / auth pages — do not block typing for ~15s); on a **fresh open** of Creo’s browser (close/reopen), promote **Connected** as soon as the bridge is live (do not wait on creopdm-agent `/health`), start `/creojs.js` after a short grace if Creo has not injected it yet, and poll the overlay ~100ms so the spinner clears quickly; after a server update, soft-nav must pick up the new `app.js` (cache-bust) and refresh **Open Creo models with** on the Creo pill so Modified / New files Open does not stay on a stale Windows-association path; if soft-nav **Loading…** cannot get HTML within ~45s (server busy on Open / index), fall back to a normal navigation instead of spinning forever | Hard-reload shell pages (SSR Session offline / drop Creo.JS); flash Session offline while Set Working Directory is visible; treat Logout / Login / setup as soft-nav; leave the connecting overlay up in a standalone browse; leave **Connecting to Creo…** up on the sign-in page after Logout; leave **Loading…** stuck forever when the server worker is blocked; trap clicks forever when Session stays offline; keep running an old in-memory `app.js` after deploy while only the HTML shell updates; leave Open mode stuck on association after Settings → Embedded because the live Creo pill was not refreshed; wait several seconds for agent `/health` before showing Connected when Creo.JS is already live |
| Sign in as **Viewer** | View products (`products.view`); open/download files and use **Details** (Overview/History) via the bottom toolbar or double-click (`objects.view`); Open without checking out (**no Open dialog** — only one choice) | See Add / Checkout / Check In / Remove / Export ▾ (including an empty **Checkout ▾** fly-up), New product, Copy to Vault, or “Check out … then open” in the Open dialog |
| Sign in with Administration only (no `products.view`) | Land on **Administration**; breadcrumb has no **Products** link; visiting `/` redirects to `/admin` | See a JSON error; see a Products crumb that opens Files |
| Sign in with a role that has **no permissions** | Land on a clear **No Files access** page (not JSON); product APIs stay **403** | Use the app as if signed in with Viewer |
| Add or remove files/folders | Update the list so it matches reality | Leave old rows on screen until you press F5 |
| Wait while something big runs (Add, Remove, Check In…) | Show a busy message so you know it’s working | Sit frozen with no feedback |
| Press **Escape** on the busy overlay | For **cancellable** jobs only (**Rebuild Where Used**, **Collect metadata**, Utilities delete-and-rebuild Where Used): stop that job and clear the overlay. For other busy work (Add, Check In, Open, Compact…): keep the overlay up — do not abort mid-flight. If the overlay is closed while the app still thinks it is busy, clear the stuck state so the page is usable again | Show a redundant Cancel button on the busy overlay; dismiss Add/Check In/Open mid-flight and leave half-done work looking finished; leave a stuck modal / unclickable page after Escape |

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
| **Rebuild Where Used** (product gear) | Show whenever you have metadata permission and the product allows edits (Chrome/Edge and Creo — server vault scan, no Creo.JS); hide when the product is read-only or not **In work**. Uses the same busy overlay as Add (**Indexing Where Used… N of M**, with total primed before the first vault chunk) and refreshes Files when done so **Top level assemblies** appears; **Escape** stops the server job, clears the busy overlay, and tells you to rebuild again if Top Level looks incomplete; **clears** old assembly/drawing Where Used links first, then re-indexes bounded ``name.ext`` **and** bare Creo component names (ASCII and UTF-16). Assemblies falsely claimed by dozens of parents (Creo name-table “magnets”, often the project root) have those incoming links pruned so Top Level can show the real root. Bare stems that are Creo datum/view words (``front``, ``top``, …) are ignored (``front.asm`` still matches). Names glued inside longer tokens still do not match | Require Creo’s embedded browser / Connected session; show when the product is read-only / On hold / Released / Closed / Archived; leave stale false parents; leave busy text without N of M for the whole first chunk; leave the busy modal stuck after Escape; treat a product-wide name table as real members; finish indexing without refreshing the Files metrics |
| **Collect all metadata** (product gear) | Show only inside Creo’s embedded browser when Creo.JS is connected (and you have metadata permission); hide when the product is read-only or not **In work**; hide in Chrome/Edge and when Session offline. Shows the same busy overlay as Add (progress count) and blocks navigation / product switch / delete until it finishes; **Escape** (or the toolbar Cancel while Collect is running) stops between models and clears the overlay; keep the **Collecting… N of M** busy text while fetching local tips (do not flash **Local workspace already up to date…** between models); materialize **only that tip** per model (not the full Open dependency tree); reuse tips already in the local workspace (one agent file list up front); batch Creo Erase instead of once per file; list Features during Collect using Creo’s ``feature.name`` (then `GetName`) when set; if Creo has no name, show type (not subtype placeholders like ``General`` / ``Edge``) — do not invent order numbers; **wait as long as Creo needs** for each model (no per-file skip timeout — large roots like ``844j.asm`` must be allowed to finish); when finished and at least one model was saved, **refresh the Files list once** so **Type** (and related columns) update without F5 (not a soft-refresh after every file); do not flash a stuck “Loading…” overlay when you try to leave mid-Collect | Show Collect in a standalone browser; Collect without Creo.JS; show when the product is read-only / On hold / Released / Closed / Archived; leave the busy modal stuck after Escape; let you browse away mid-Collect and leave it half done; leave a “Loading…” busy state after a blocked product click; flash workspace-up-to-date over Collect progress; skip large assemblies on a short JS timeout; prepare full Where Used / companion trees for every Collect tip; Erase from session after every tip; soft-refresh Files after every saved model; leave stale Type labels until a hard refresh after Collect saved metadata |
| Product is **read only** or not **In work** | Show the product state badge next to the product name (same blue-dot style as file State); show a short banner (“This product is **On Hold**.” / “This product is **read only**.”) without listing blocked actions; **Checkout** column shows **Read only** / **On hold** / etc. (not **Available**); hide Add, **Checkout selected**, **Checkout product**, Check In, Remove from Product, Rename, Collect, Rebuild; keep **Delete product** on the product gear when the role allows (password re-auth confirm — must purge vault + DB row even when locked/Archived); admins can also delete from **Utilities → Delete products**; keep **Undo Checkout** / **Force Undo Checkout** when the role allows; selecting a folder must not enable checkout; API rejects content mutations (Add/Checkout/Check In/Remove files/Rename/…) but **allows** product delete/forget. Open / History / right-click **Download selected to workspace** still work. **Archived** products are hidden from the Files list (restore under Administration → Products, or delete via **Utilities → Delete products**) | Leave Checkout selected / Checkout product / Check In visible when the product cannot be modified; allow Rename while read-only; trap Archived products so they cannot be removed; show Archived in the normal Files product list; hide the product state from the Files header; show **Available** in Checkout when checkout is blocked; list every blocked action in the banner; let folder select offer Checkout selected |
| Open a product on Files | Always show the current product state next to the name (**In Work**, **On Hold**, …); append **Read only** on the badge when that flag is set | Only show state in Administration |
| Click the **bell** next to the gear (when Email notifications are enabled) | Ask to confirm Watch / Stop watching; then toggle **your** watching state for that product | Change watching when you Cancel the confirmation; show the bell when notifications are disabled; show another user’s watching state as your own |
| Watch a product with a valid account email | Receive email summaries for adds, removes, checkout, undo checkout, check-in, restore, and product rename/info (not for browse or background scans); no historical mail | Email yourself for your own actions |
| Log in as a different user after someone else watched | Show **not** watching unless **you** subscribed; keep the other user’s subscription | Steal or clear another user’s watch when you open the product or click Stop on your own bell |
| Open a product when your account email is invalid | Show the bell disabled with a clear reason | Let you subscribe until email is fixed |
| **Force Undo Checkout** (role permission) | Release another user’s checkout without a new version; email that user when notifications are enabled (they need a valid account email; watching is not required) | Show without `objects.force_undo_checkout`; commit a version |
| Delete product (product gear, or **Utilities → Delete products**) | Ask you to enter your **password**; remove CreoPDM’s vault (working copies + Git) and unregister the product from the database (works when the product is locked or **Archived** too) | Delete your original CAD folders on disk just because you deleted the product; delete if you entered the wrong password; leave an orphan vault folder under the vaults root; leave a DB row / Utilities compact entry after a successful remove; keep a Remove form on Administration → Products → Edit; show the **Utilities → Delete products** tip on Administration → Products when the role lacks delete (or Utilities) permission |

**Name rules (new / rename)**

- Product name is required and must be **unique** (case-insensitive) across every product on the server — including Archived / inactive. Two products cannot share a name.
- Custom vault/workspace name: no spaces; or use the hash option instead.
- Administration → Products shows **Created** (date/time) so you can tell products apart when cleaning up.
- The **Utilities → Delete products** tip on Administration → Products (list and Edit) appears only when the role can delete products and open Utilities.

---

## 3. Finding and filtering files

| You do | App should | App must not |
|--------|------------|--------------|
| Click a breadcrumb (Home / folder path) | Take you to that folder; Creo stays connected | |
| Type in Search (Files tab only) | Show matching files across the product. Plain text is a substring match on name, path, revision, lifecycle, parameters, and the **Type** column (including collected Creo labels like SHEETMETAL, SKELETON, MFG, PART). `*` / `?` wildcards and `^` / `$` anchors work (`*.prt`, `^CAD/`, `.prt$`). Hover the search box for short examples. Under each match, show the vault-relative path with the **middle truncated** when it is long (first folder + … + leaf; hover the path for the full string) | Treat `*.prt` as literal characters to find; run full regex; ignore Type column values; show Search on **Checked out** / **Modified** / **New files**; leave a deep path untruncated so it crowds the Name column |
| Open **Details** / History from a search (toolbar or double-click), then use the browser **Back** button (or return to Files) | Keep the search text, re-run the product-wide matches, and re-select the file you had selected when you left; also keep the Files list tab you were on (**Files** / **Checked out** / **Modified** / **New files**) — Details must not clear that saved tab | Clear search or show the empty folder list just because you opened Details / History or pressed Back; reset to the **Files** tab when you left from **Modified** or **New files** |
| Clear Search | Show the normal folder view again | Bring back folders/files you already removed |
| Open a product with **no objects** yet (empty vault / never added) | Hide the whole metric filter row (Folders, Files, Parts, Assemblies, Modified, …) and hide **Search** | Show zeroed filter pills or an empty Search box on an empty product |
| Click a metric (Parts, Assemblies, …) | Filter and select those files; click again to clear | Jump into a folder or leave the page |
| Click **Folders** | Filter to folder rows and select them; show the pill count of folders in the current list (including **0**); stays **on** together with **Files** if both were turned on (clicking Files does not turn Folders off, and does not force Folders back on); turning **Folders** or **Files** off **stays off** after folder/product navigation (latest pill state wins — not an older folder’s saved filters); turning **Folders** off **unselects** folder rows even if **Files** stays on; clicking another type pill (Creo Models, Parts, …) with Folders off **hides and unselects** folders | Hide the **Folders** pill when the count is 0; select files when only Folders is on; look “off” while Files is on and folders are still in the filtered selection; leave folders selected after Folders is turned off; re-activate Folders or Files after navigation just because an older folder still had them on; keep folders selected/visible under Creo Models when Folders is off |
| See **Top level assemblies** (after Where Used exists for the product) | Show the pill after **Drawings** (so Parts / Assemblies / Drawings stay together); **count is for the current folder only** (product-wide top-level list still drives which rows match — so root can show many while a subfolder shows few); assemblies not used by another **assembly** (a drawing that references it does not disqualify Top Level); click to filter/select them. Default Creo datum-named assemblies (``front.asm``, ``left.asm``, ``right.asm``, ``back.asm``) are omitted from Top Level — not common roots like ``top.asm``. Where Used / Top Level come from bounded ``name.ext`` **and** unique bare Creo component names in vault files (or Creo.JS BOM) — not names glued inside longer tokens. Where Used is built during **Add**, **Rebuild Where Used**, or **Open**; **Rebuild** clears and re-indexes (and prunes name-table magnets). Add / Rebuild refresh Files when indexing finishes so the pill appears without F5; after **Open** captures Creo metadata (BOM / deps), soft-refresh Files the same way so **Top level assemblies** / Type update without a hard refresh | Show the pill when the product has no Where Used / dependency index yet; treat a drawing that references an assembly as “used”; expect the same Top Level count in every folder; count ``front.asm`` / ``left.asm`` as a second root because files mention ``FRONT`` / ``LEFT``; mark an assembly as used just because its number is glued inside another token; insert it between Assemblies and Drawings; leave the pill missing after Add until you hard-refresh |
| Click **Top level assemblies** | Filter and select those top-level assemblies; turn **off** every other pill (Folders, Files, Parts, Assemblies, Modified, …); click again to clear | Leave Assemblies / Modified / other pills on with Top level |
| Click **Modified** | Filter and select files with local changes you can check in; click again to clear. **Modified** pill count matches rows shown as Modified (including after local/agent detection) | Select unmodified checkouts or someone else’s files; leave the pill at 0 while a row shows Modified |
| Click **Checked out** | Filter and select checked out files in the current group; click again to clear | |
| Switch tabs: **Files** / **Checked out** / **Modified** / **New files** | Show that list; show Search only on **Files** (hide it on the other list tabs); tab labels show live counts for Modified and New files (same detection as Check In); when a count changes, refresh/warm the row list so the table matches the badge (never leave **· 1** with an empty table from a stale cache); **never flash** a temporary **· N** on Modified / New files from a workspace-watch guess — only paint the badge after the confirmed queue load (false local/vault hits must not flicker on/off); opening the tab must not flash “Looking for…”; show Check In help blurb on **Checked out** only when that action is available (role ∩ product state); no tip blurb on **Modified** or **New files**; after **Details** / Back (or soft return to the product list), reopen the same tab | Mix modified product files into **New files**; leave Modified / New files counts stale while workspace-watch can see changes; show a count on the tab while the list stays empty because of a stale prefetch; flash “Looking for…” after the badge already updated; flash **New files · 1** / **Modified · 1** then clear because a poll estimate was wrong; tell you to Add or Check In when you cannot do those actions; drop you on **Files** after Back from Details when you left from another list tab; leave Search visible on Checked out / Modified / New files |
| Click a column header | Sort; click again to reverse | |
| Collect Creo metadata | Uses Creo.JS **feature**, **assembly structure**, and **drawing structure** inventories (same logic as the feature/assembly/drawing probes) for Details **Features** / **Structure**, AI snapshots, and stored metadata; falls back to the legacy feature walk when an inventory script is unavailable. Assembly **Structure** labels prefer the referenced model tip (never Creo’s literal `no_name` on IFX assemble features); IFX assemble COMPONENT siblings nest under the `IFX_*` group. When metadata includes **Model type** / **Subtype**, the Files **Type** column prefers a distinctive subtype (SHEETMETAL, SKELETON, MFG, …) else the model type (PART, ASSEMBLY, …) instead of the extension-based label. Skeleton uses Creo’s IsSkeleton flag when available, else whether a session assembly lists it as its GetSkeleton, else common names (`*_skel`, `*_skeleton`, `skel_*`). After **Collect all metadata** saves at least one model, refresh the list so those Type labels appear without F5. Day-to-day use also captures metadata when Creo.JS is **Connected** (Creo embedded browser only — never Chrome/Edge): after **Add** / zip / folder Add (**any** count — Where Used first, then **Collecting Creo metadata… N of M** on the same busy overlay), after **Check In**, and after **Open** into the Creo session (the opened model — session-first so it does not erase what you just opened; when Open saves metadata, soft-refresh Files or Details so Type / Top Level / Features match without F5). Gear **Collect all metadata** remains the backfill for files nobody has opened yet. Batch Collect / Add metadata runs **parts first, assemblies next, drawings last**, and materializes drawing companions so Creo does not pop “Model X.PRT is not in this directory” when retrieving a `.drw` before its part is on disk | Keep showing “Creo Assembly” for a manufacturing assembly after metadata says MFG; keep showing PART for a sheet-metal part after subtype is SHEETMETAL; leave Files or Details Features stale until a hard refresh after Open saved metadata; leave the Files list stale until a hard refresh after Collect; require gear Collect for every file users already Open / Add / Check In inside Creo; run Add metadata outside Creo / when Session offline; cap Add metadata at 50 files; collect drawings before their referenced parts in the same batch |

**Modified tab** (between **Checked out** and **New files**) lists product files that already exist in the vault with a newer save in the vault or your local workspace — the same pending-save detection that drives Check In and the Modified count on the tab. Use **Check In** here.

**New files tab** shows only files waiting in the **vault** (and sometimes local workspace) that aren’t in the product yet — not modified vault tips. Deleting only from your PC workspace does **not** clear vault “new” files — those live on the CreoPDM vault until you remove them from there. Local workspace copies of vault files (including folders with spaces like `from ptc`) must not appear here just because an older agent rewrote the folder as `from_ptc`. For **New file (local)** Creo siblings, show the **highest** save (`test-part.prt.2`, not a leftover `test-part.prt.1`). Opening a **New file (local)** or Modified **Newer local save** name opens it from the local workspace via creopdm-agent (or Creo.JS when Connected) — it must not look in the vault or show **Vault file not found**. Creo.JS opens with the **logical** tip (`test-part.prt`) while the on-disk file may still be `test-part.prt.2`.

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
| **Right-click** a file or folder row (or a multi-selection) | Show CreoPDM’s menu (not the browser menu) with the same labels as the toolbar where possible: **Open selected**, **Details**, **Checkout selected**, **Undo Checkout**, **Add selected…** (New files only, needs `objects.add`), **Check in selected…**, **Download selected to workspace**, **Export selected…**, **Remove from Workspace…** (local **New file (local)** rows only — same as Remove ▾ when that item is shown; ellipsis because it opens a confirm); if the row was not selected, select it first; **hide** each item when that action is not possible (same rules as the toolbar — do not grey items here); Open when one openable file is selected; Details when one file with a Details page is selected; Download needs `objects.view` and file ids, and is hidden when the selection is already local-workspace tips (**Newer local save** / **New file (local)**); Add selected only when every selected row is a **New files** queue row; Checkout / Undo / Check In / Export / Remove from Workspace follow role ∩ selection like the bottom buttons; use **…** only when the action opens a confirm/dialog (not on **Open selected** / **Open workspace**) | Show **Download selected to workspace** for rows that are already in the local workspace; show **Add selected…** for Modified / Files / Checked out rows; show **Remove from Workspace…** when Remove ▾ hides that item or the selection has no local New files; omit the ellipsis on a confirm action; put **…** on **Open selected** / **Open workspace**; show actions the toolbar would not allow; check files out via Download; fail silently when the agent is offline on Download (say to start creopdm-agent); show the browser menu when at least one action is available |
| See **Modified** | Means the local tip’s **content hash** differs from the vault tip (a higher Creo `.N` usually does; size/date alone never counts). Local workspace tips use `.creopdm_cache_index.json` (via the agent file list) when the on-disk size still matches the index — that proves the file is real before comparing to the vault tip; missing/stale index entries fall back to hashing. After refresh, clear Modified when vault/local no longer report that file as pending | Treat a rematerialized copy with the same hash as changed (including when only `.N`, size, or date differs); leave Modified stuck after a later refresh proves the tip matches; invent Modified rows that are not on disk / not in the local index |

---

## 6. Toolbar buttons (overview)

Typical order: **Set Working Directory** → **Add ▾** → **Open ▾** → **Checkout ▾** → **Check In ▾** → **Details** → **Copy to Vault** → **Export ▾** → **Remove ▾**.

| Button | Available when | Hidden when |
|--------|----------------|-------------|
| Set Working Directory | Inside Creo’s browser **and** Creo.JS connected, with a product workspace (Files page); pill shows **Connected** (same bridge signal) | Hidden outside Creo, when Creo is not connected, and on the file **Details** page; shown while the pill still says Session offline |
| Add ▾ | A product is open **and** the product allows edits (In work, not read-only) | No product; product is read-only / On hold / Released / Closed / Archived |
| Open ▾ | A product is open (workspace) and/or a file can be opened (**Files** page) | No product and nothing to open; always hidden on the file **Details** page |
| Open selected | A file you can open is selected (no ellipsis — does not open a confirm/dialog by itself) | Nothing useful selected; show **Open selected…** |
| Open workspace | A product is open **and** creopdm-agent is running on this PC (no ellipsis — opens the folder directly) | No product; agent offline (do not offer a host-vault fallback); show **Open workspace…** |
| Checkout ▾ | Something can be checked out, undone, or force-undone (**Files** page) **and** your role has the matching permission. On a locked product, **Undo Checkout** / **Force Undo Checkout** may still appear | Nothing to do; role lacks checkout/undo/force-undo; empty fly-up (no items); always hidden on the file **Details** page |
| Check In ▾ | Something can be checked in or added **and** the product allows edits | Nothing pending; product is locked (read-only / not In work) |
| Details | One file selected | No file |
| Copy to Vault | You have **Copy to Vault** permission and selected files are not already in the vault | Nothing to copy; role lacks `objects.copy_to_vault` (hidden for Viewer / Engineer by default) |
| Export ▾ | A product is open **and** you have `products.export` and/or `objects.export`, **and** at least one menu item is usable (product has vault files and/or a selection). Works on locked / Released products | No product; role lacks both export permissions; every Export item would be greyed (empty product with nothing selected); always hidden on the file **Details** page |
| Remove ▾ | Something can be removed (**Files** page). Local workspace remove/purge still work on a locked product | Nothing selected; always hidden on the file **Details** page |
| Remove from Product… | Files **and/or folders** selected (including empty folders); product allows edits | Nothing selected; product is locked |
| Remove from Vault… | Selected vault files; product allows edits | Nothing selected; product is locked |

Inactive top-level buttons and inactive items inside ▾ menus are **hidden** (not greyed out), so the toolbar only shows what you can use right now — **except** **Export product…** (greyed when the product has no vault files while **Export selected…** is still usable), **Export selected…**, and **Check in selected…**, which stay visible and greyed with a hover title that explains why (empty product / nothing selected / no Modified work). When **every** Export item would be greyed, hide **Export ▾** itself. Same rule for **permissions** and **product lock** (read-only / not In work): the server builds one `product_ui` flag set (role ∩ product state) and the page only shows those controls — if the signed-in role cannot do an action (or the PC cannot — e.g. Open workspace without creopdm-agent), **do not show the control**. **Set Working Directory** and **Collect all metadata** show only inside Creo when Creo.JS is connected (embedded browser); hide them outside Creo / when Session offline. **Rebuild Where Used** stays on the product gear in Chrome/Edge too (server indexing). Set Working Directory also needs a product workspace ready and stays hidden on the file **Details** page. On the file **Details** page (every tab, including History) Open, Checkout, Remove, Set Working Directory, and **Check In ▾** are all hidden — that toolbar is **Revert to selected…** only (when an older History row is selected). Check In stays on the Files page.

Only one ▾ menu open at a time. Click outside or press Escape to close.

---

## 7. Add ▾

Needs `objects.add` and a product that allows edits (In work, not read-only). Menu order:

1. **Create folder…**
2. **Add files…**
3. **Add folder…**
4. **Add folders…**
5. **Compressed data…**
6. **Add selected…** (enabled only when the selection is **New files** rows — vault or local workspace; greyed otherwise)

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
| Pick or drop individual files | Copy them into the product at the current location; store Creo models under the **logical** name (`shaft.prt`, not `shaft.prt.3`) so Git versions one stable path; blank comment becomes `Add {name}` or `Add N files` using the **full** pick count on **every** upload chunk (agent 5-file chunks, browser chunks, multi-folder Add); after **all** chunks finish, keep the busy overlay and run **Where Used** indexing there (never mid-upload; never clear the overlay and return to Files before indexing finishes), then — **only inside Creo** when Creo.JS is Connected — **Collecting Creo metadata… N of M** for the added Creo models (any count; parts/asms before drawings; skip in Chrome/Edge / Session offline), then refresh Files once so **Top level assemblies** and Type labels are ready. Same Where Used (+ Creo metadata when Connected) overlay step for **Add folder…**, **Add folders…**, **Compressed data…**, and **Add selected…** | Keep Creo `.N` in the vault filename; label History `Add 5 files` just because the agent uploaded in 5-file chunks; put the typed comment only on the first chunk; start Where Used after the first chunk while Add is still running (slows the upload); dismiss the overlay and leave indexing in the background so Top Level stays missing until a later refresh; skip Where Used after zip / folder Add; run metadata after Add outside Creo; cap metadata at 50 files; collect metadata before Where Used finishes; open a drawing for metadata before its part is materialized and leave Creo’s “not in this directory” dialog |
| Pick a very large multi-select (hundreds/thousands) | Keep a busy message after the OS picker closes while it resolves latest numbered saves, then show the Add dialog summary; warn before starting a bulk Add | Sit frozen with the Add dialog closed and no busy feedback after you confirm the OS picker |
| Drop a whole folder tree | Tell you to use Add folder… / Add folders… | Quietly import the whole tree as “files” |
| Click Add with nothing chosen | Ask you to choose files first | Start an empty import |
| Click Add twice quickly | Say an add is already running | Run two imports at once |

For thousands of Creo models, prefer **Add folders…** (picks a folder and lists files on the agent) over multi-select in **Add files…**.

### Add selected…

| You do | App should | App must not |
|--------|------------|--------------|
| Select one or more rows on the **New files** tab (vault **New file** or **New file (local)**), then **Add ▾ → Add selected…** (or right-click **Add selected…**) | Ask for a comment; upload local workspace files via creopdm-agent when needed; add those paths to the product; run Where Used then (Creo Connected only) Collect metadata; refresh so the rows leave New files | Offer **Add selected…** for Modified, Files, or Checked out rows; run when the menu item is greyed; require `objects.checkin` instead of `objects.add`; appear when Add ▾ is hidden; run metadata outside Creo |
| Open **Add ▾** with no New files selection | Keep **Add selected…** visible but **greyed**, with a hover title that says to select New files | Hide the item with no explanation; enable it for a mixed selection that includes non–New-files rows |

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
| Click **Import** with a `.zip` chosen | Show a busy overlay with **phase text** that keeps updating through the whole job (uploading zip with size, extracting, importing N of M, committing to Git, saving to the database, then **Finishing vault files… N of M** for read-only/cleanup — not frozen after upload while extract/import run — then **Where Used** indexing **N of M** on the **same** overlay, then — **only inside Creo** when Connected — **Collecting Creo metadata… N of M**); only then refresh Files once so new rows, **Top level assemblies**, and Type labels appear | Leave a single static “Uploading…” message for the whole job; freeze the overlay on the last upload % while extract/import continue; label the vault finish pass as “Recording in database”; clear the overlay and return you to Files before Where Used finishes (sparse Top Level); skip Where Used after zip import; run zip metadata outside Creo |
| Pick a non-`.zip` file | Say to choose a `.zip` | Upload it anyway |
| Zip has one top-level folder only (e.g. `MyExport/…`) | Strip that outer folder and import under the **current** Files location | Keep an extra `MyExport/` layer just because of how the zip was packed |
| Zip has folders and files | Keep nested structure under the current location (same idea as **Add folders…**) | Flatten everything to basenames; create empty folders from empty zip dirs |
| File already in the product | Fail that entry (same as Add); import the rest; show a summary | Overwrite vault content or auto-rename CAD files |
| Zip over 2 GB, password-protected, or corrupt | Clear error; add nothing | Hang or invent content |
| Junk (`.DS_Store`, `__MACOSX`, Thumbs.db, ignore patterns) | Skip like other Add paths | Import OS metadata junk as product files |

---

## 8. Open, workspace, history

**Open ▾** menu (top → bottom):

1. **Open selected**
2. **Open workspace**

| You do | App should | App must not |
|--------|------------|--------------|
| **Open ▾ → Open workspace** | Open this product’s local working folder on this PC via creopdm-agent; if nothing has been checked out / materialized yet, create the empty local folder and open it; no ellipsis (no confirm/dialog) | Open a folder on the CreoPDM Linux host; show the item when the agent is offline; fail with a raw WinError just because the local workspace is still empty; label it **Open workspace…** |
| **Open ▾ → Open selected** (or click a file name) | Offer how to open (see below); no ellipsis on the menu item; show the busy overlay from prepare/materialize until Creo (or Windows) is ready to open, with phase text: **Preparing…** → **Finding dependencies…** (full Where Used member tree from the DB when present — including large products with thousands of members; when that tree is still short of the product’s vault files, **fill the rest** (same tips zip/Add stored — not only Creo-openable) so companions are not missing; folder-first vault scan only when the index is missing or sparse — **do not** copy vault tips during this step; **store** bounded parent→child edges so Top Level / next open use the DB; **do not** throw away a large Where Used tree and open with only a handful of files) → **Updating local workspace…** (skip unchanged tips) → **Opening in Creo…** / **Opening with Windows…** (wait long enough for large assemblies — do not fail at 90s with “session may be offline” while Creo is still retrieving; clear the overlay on error or timeout — outside Creo say to check creopdm-agent, not “Creo is Connected”); when Open mode is **Embedded** and you are inside Creo’s embedded browser but Creo.JS is not Connected yet, wait briefly then **warn** and do not open via Windows file association (that would launch another Creo); when the file is fetched to the local workspace, keep its vault folders (do not flatten) and use the **logical** tip name (`shaft.prt`, not `shaft.prt.1`); inside Creo, Embedded Open drives **File > Open** to that workspace folder (Assembly type for `.asm`) and does **not** set Creo’s working directory by default (trail open is enough; Set WD locks the local workspace folder so Delete product / remove-folder can hit WinError 32 — use the chooser checkbox or toolbar **Set Working Directory** only when you want WD); not Toolkit `OpenFile`/`RetrieveModel` first (and not an early manufacturing `OpenFile` on every `.asm`) so large assemblies do not flood Creo messages or break combine-state groups; nested assemblies still resolve; when you are **not** checked out, align the local tip to the vault tip (remove newer local `.N` leftovers); **outside** Creo’s embedded browser (or when Open mode is OS association), download via creopdm-agent and open with the **Windows association** (or browser download if the agent is offline); for **New file (local)** or Modified **Newer local save**, open the existing agent-workspace file (no vault prepare); after a successful **Creo.JS** open of a product Creo model, quietly **Capturing Creo metadata…** from the session once the model is in (soft-fail — Open already succeeded; do not disk-Retrieve again after Open; skip when Session offline / Windows association / no object id); when that capture saves, soft-refresh Files or **Details** (**Refreshing…**) so **Type**, **Top level assemblies**, and **Features** names update without leaving and coming back | Throw away the vault-scan dependency list without writing Where Used; leave Type / Top Level / Features stale until a hard refresh or revisit after Open metadata saved; open via Windows file association from Creo’s embedded browser while Creo.JS is still Session offline; fail silently with no message; leave the busy overlay stuck forever; sit on a vague **Opening…** through dependency find + download with no phase change; put nested vault files at the workspace root; fail open just because the file lives under a vault subfolder; invent a Creo `.N` on materialize; leave a newer local `.prt.N` after opening a vault tip you do not have checked out; require Creo’s embedded browser when Open mode is association; show **Vault file not found** for a **New file (local)** or **Newer local save** that is only (or newer) in the local workspace; erase the model you just opened while capturing metadata; fail Open because metadata capture failed; prefer Toolkit Retrieve over File > Open for Embedded native models; set Creo working directory on every Embedded Open by default (locks the workspace folder) |
| **Details** (toolbar / double-click) | Open the file **Details** page on the **Overview** tab (first tab) via soft-nav so **Creo stays Connected**; page shows a **Details** title under the breadcrumb; History tab on that page keeps Connected too | Hard-reload Details (SSR Session offline / drop Creo.JS); open the History tab by default; jump to History from a single-click on the file name |
| Open **Compare Revisions** (Creo model Details) | Show the tab **only when two or more History revisions have saved snapshots**; side-by-side **plain-language outlines** from the same Creo inventories as Details (**Features** / assembly **Structure** / drawing inventory — nested level + status; drawing notes/tables as well as **Views**/sheets; BOM qty when inventory structure is missing), plus dimensions, parameters, **materials**, **units** — not raw JSON; Creo **internal / invisible** construction features are omitted so deleting a pattern does not look like a deleted unnamed DATUM PLANE) with **Copy** (Clipboard API, or `execCommand` fallback so Creo’s embedded browser can copy too); panes headed `=== OLD snapshot (rev) ===` / `=== NEW snapshot (rev) ===` (toolbar **OLD** / **NEW**); default **NEW** = latest snapshot and **OLD** = the one before it whenever the tab loads; each dropdown only lists revisions that keep OLD older than NEW (you cannot pick A.2 on OLD while NEW is A.1, or A.1 on NEW while OLD is A.2); two side-by-side text panes with **one scrollbar between them** that scrolls both together (wheel over either pane drives it); line highlights like a GitHub / git unified diff aligned by **Creo id** (feature/structure lines always end with `(id)` when known; dims by `dN`; parameters by name) — markers are **` `** (space) for matching, **`-`** removed / old, **`+`** added / new (not a list bullet on every line); **light green** matching, **light red** removed, **yellow** only when that **same id** changed text (OLD shows `-`, NEW shows `+`; a new `ROUND (146)` next to a removed `CUT (95)` stays red + blue — not yellow), **light blue** new; for **assemblies**, outlines and Ask AI (Compare Revisions and Check In Ask AI for comment) use the same **Structure/BOM** tree as the Structure tab (filename × qty) for component add/remove/qty — normalize Creo family-table FullName brackets so `name<<instance>>.prt` matches the tip Structure name; when both sides have Structure, do not invent feature removes from the incomplete non-component feature list; Features intentionally omit `FEATTYPE_COMPONENT` members so they are not a complete component list; dimension lines include the owning **feature name** in parentheses right after the dim id when known (e.g. `d258 (Extrude) = 95.461 in` — never the Creo feature id; ownership comes from searching each feature’s `ListSubItems` for the dim id, including internal/sketch features promoted to the visible parent / PATTERN; re-Collect / Check In after deploy so older snaps that never stored ownership pick it up); enrich tip snapshots from the same Collect/Open metadata gathers as Overview (not a second Creo Retrieve); for **drawings** (`.drw`) capture views / sheets / drawing dims on the drawing handle — never walk the referenced solid; session lookup must match `.drw` (not the same-stem `.prt`); refuse to save a PART solid snapshot on a drawing object; mark **Erase View** as `status: erased`; **do not** overwrite the tip AI snapshot from Collect while the file is **Modified**; tip snapshots update on Check In / Open / Collect when the tip matches the workspace; include dimension tolerance limits when Creo exposes them; when **Enable AI features** is on, **Ask AI what changed** sends both **OLD/NEW outlines** plus the **Snapshot compare prompt** from **Administration → AI** to Ollama, then writes the summary **above** the panes; Check In can **Ask AI for comment** the same way (tip vs modified model) | Show the tab with only one snapshot; dump raw snapshot JSON; use two independent pane scrollbars; default both dropdowns to the newest rev; mix this into Overview / Features / Parameters; invent snapshots for old revs that were never Collected; fail Creo metadata save just because snapshot post failed; silently do nothing on **Copy** when `navigator.clipboard` is missing; omit materials/units that Collect already gathered; invent ± tolerances in the AI prompt; leave Ask AI clickable when AI is off; hide the AI answer under the outline panes; keep a compare prompt hard-coded in Python when the AI page already stores it |
| **Details** (file page) | Show a clear **Details** title near the top (under the breadcrumb, Library-sized), then the file name with an **Open…** button beside it (same open/checkout dialog as Files — not the bottom toolbar), then tabs (Overview, History, Snapshot for Creo models, …); **Features** and **Structure** tabs use Creo inventory tables (nested **Level**, **Status**, probe-style columns — no List/Copy JSON; Name/Component text lines up under the column header — nest indent stacks on normal cell padding, it does not zero out level-1 left padding); **Structure** on assemblies shows the flat component inventory when captured, else the linked BOM tree; drawings show sheet/view/note/dim/table inventory under **Features**; BOM tab stays the quantity table; BOM / Where Used **Qty** as whole numbers (`1`, not `1.0`); **Where Used** only for files whose extension is in **Settings → Creo Models**; click a parent filename on **Where Used** to soft-nav that file’s Details **already on the Where Used tab** (`#where-used`) so you can keep traversing up the tree without re-picking the tab; same light panel background as Files; **Overview** Identity labels the model **Name** (not Number), shows **Model type** / **Subtype** when Creo metadata was collected (e.g. PART + SHEETMETAL, PART or ASSEMBLY + SKELETON for skeleton models, or MFG + MFG for manufacturing assemblies that Creo reports as `.asm`); when Where Used exists and this assembly is top-level (not used by another assembly; drawings ignored), show **(Top Level)** on **Model type** in Overview (or `ASSEMBLY (Top Level)` if model type was not collected yet); do **not** repeat a type · path line under the file name; on **Where Used** for a Top Level assembly with no parents, show a short **No parent assemblies (Top Level)** note — do **not** show the “Not listed in any captured… Open parent assemblies…” empty hint; shows **Date created** and **Date modified** only when modified differs (hide Date modified when it matches Date created), and omits content hash and **Origin** (Creo’s path is the local workspace, already covered by Open workspace); date values keep the short stamp on screen and show a pretty hover title (e.g. Monday, July 23, 2026 at 5:30pm); skips duplicate identity fields (same name/instance) and omits Revision / Lifecycle already shown in the header; when the file is checked out, **Overview → Checkout** shows **Checked out by** and **Checked out** (when), and the header checkout badge has a pretty hover for when; use one body font and size on all Details tabs (no mixed monospace); file/open links use regular ink color (underline on hover), not accent/orange; bottom toolbar shows **Revert to selected…** on History only — never **Check In ▾**, **Open ▾**, **Set Working Directory**, **Checkout ▾**, or **Remove ▾** on Details | Show Where Used for Documents / Other / non–Creo Models extensions; open a Where Used parent on Overview and force you to click Where Used again to keep traversing; drop `#where-used` / `#history` on soft-nav; urge “Open parent assemblies…” on Where Used when the file already shows **(Top Level)**; Show Check In, Open ▾, Set Working Directory, Checkout, or Remove on the Details **bottom toolbar**; omit **Open…** next to the Details file name; keep a separate History page title; keep a separate Version History view; label the model identity as Number; show content hash on Overview; show **Origin** / a full workspace file path under Identity; always show Date modified when it equals Date created; omit created/modified dates; hide who/when for an active checkout; repeat Revision / Lifecycle header badges again in Overview Identity; mix monospace and UI fonts on Details tabs; use orange or accent-colored hyperlinks on Details; label a sub-assembly as Top Level; show Top Level when Where Used has not been built |
| **Open ▾ → Open current…** | (Files page / file name) Open the **current** tip of this file | |
| Select an **older** History row → **Revert to selected…** (bottom toolbar, red like Remove) | Ask you to enter your **password** (same confirm dialog as Remove); explain that content restores to the vault tip and local **in one step** (new version recorded — no Check In prompt); vault tip stays the **logical** name (`shaft.prt`); remove newer numbered siblings so locate/open don’t prefer a leftover `.3`; leave the file Available (not checked out); show Revert only when an older row is selected; warn that Creo may keep old geometry in memory if the model is already open; when Creo is connected, try to **Erase** that model from session after vault/local restore (best-effort — fails if the model is displayed in a window); if erase did not clear it, tell you to close the window or use **File → Erase**, then **Open** again from CreoPDM | Offer Revert for the current version, a pending unsaved row, or when this file has only one version; revert someone else’s checkout; proceed if the password is wrong or Cancel; rename the vault tip back to an old `.prt.N` just because History still shows that leaf; leave a newer local cache save after vault restore; leave you checked out with a Check In prompt; show floating “choose an older row” hint text in the toolbar; use a plain browser `confirm` instead of entering your password; pretend Creo already shows the restored geometry when the model stayed open in a window; force-close Creo windows or use Erase With Dependencies |
| **Copy to Vault** | Put a copy in the vault without checking out (requires `objects.copy_to_vault`; starter: Administrator + PDM Manager only) | Check the file out; show the button to Viewer / Engineer by default |

### When you open a file that’s not checked out to you

If you **cannot** check out (Viewer role, no `objects.checkout`, or the file is not free to check out), the app **opens immediately** — no dialog. There is only “open without checking out,” so asking is pointless.

Otherwise the app asks how you want to open it (must show the chooser in Creo’s embedded browser too — do not skip straight to Open because `<dialog>` / `dataset` detection failed, do not treat a stale owned flag as “already mine” when the Checkout column still says Available, and do not auto-submit the chooser):

| You choose | App should | App must not |
|------------|------------|--------------|
| **Open without checking out** | Bring what Creo needs into the local workspace and open for view/reference — **no edit lock**; overlay: **Finding dependencies…** then **Checking local index…** using prepare hashes against `.creopdm_cache_index.json` in `CreoPDM-agent\workspaces\<product>\` (no second 900-id manifest); download only missing tips | Re-fetch agent-cache-manifest when prepare already had identities; spend ~20s “verifying” a warm index |
| **Open a file already checked out to you** | Keep your local tip (including modified / higher `.N` saves); do **not** overwrite with vault bytes; still bring **missing** dependencies only | Redownload / wipe your checked-out local work just because you opened again |
| **Check out this file, then open** | Lock this file, download it, then open | |
| **Check out this file and its dependencies, then open** | Lock this file plus the same full dependency tree Creo needs (same automatic walk — no Where Used rebuild required), then open | |

**Set Creo working directory…** appears on that dialog **only inside Creo’s embedded browser** (off by default — check it only when you want WD). When the dialog is skipped (already yours, or no checkout choice), Embedded Open does **not** set WD. Outside Creo (Chrome/Edge/etc.) it is hidden and is never applied — working directory only exists in Creo. Use the toolbar **Set Working Directory** when you explicitly want WD (Creo only).

If open seems to do nothing, check the error line under the toolbar, and that creopdm-agent is running on the Creo PC. Large downloads can take a while.

**Settings → Open Creo models with:** **Embedded** options (help + Creo.JS path) sit under that radio and are grayed out when **OS file association** is selected. Embedded only uses Creo.JS inside Creo’s embedded browser; otherwise Open uses the OS association (including when the pill says **Creo: Session offline** in Chrome/Edge — do not tell the user to open from Creo’s built-in browser just because Embedded is selected). The top-bar Creo pill shows session only (**Creo: Connected** / **Creo: Session offline**), not the open-mode name.

**Set Working Directory** (toolbar) does the same WD step on its own; it only appears inside Creo’s browser when Creo.JS is connected.

---

## 9. Checkout ▾

1. **Checkout selected**  
2. **Checkout product**  
3. **Undo Checkout**  
4. **Force Undo Checkout** (only with `objects.force_undo_checkout`)

| You do | App should | App must not |
|--------|------------|--------------|
| Checkout selected | Lock those files and download them for editing under logical tip names, keeping vault folder paths in the local workspace | Steal a file someone else has checked out; flatten nested files to the workspace root; invent Creo `.N` on download; appear without `objects.checkout` |
| Checkout product | Check out everything that’s free under logical tip names, keeping vault folder paths locally | Offer checkout when nothing is left; flatten nested files to the workspace root; invent Creo `.N` on download; appear without `objects.checkout` |
| Undo Checkout | Release **your** locks only | Undo someone else’s checkout; delete the vault file; create a new version; appear without `objects.checkout` |
| Force Undo Checkout | Release **another user’s** checkout lock (abandoned checkout); no new version; confirm first; email the former owner when Email notifications are enabled | Appear without `objects.force_undo_checkout`; commit a new version; delete the vault file; unlock Checkout selected/product without `objects.checkout`; leave **Checkout ▾** open with an empty panel when the role has no checkout/undo items |
| Role lacks `objects.checkout` (e.g. Viewer) | Hide Checkout selected / Checkout product / Undo; open files without an Open checkout dialog | Show an empty **Checkout ▾** fly-up; treat `#checkout-menu` alone as checkout permission |

---

## 10. Check In ▾

1. **Check in product…**  
2. **Check in selected…** (Modified / owned pending work — not New files; those use **Add ▾ → Add selected…**)

| You do | App should | App must not |
|--------|------------|--------------|
| Check in product… | Record pending saves and new files (including same-name workspace replaces with no new Creo `.N`); show each pending tip’s local name in the dialog (e.g. `shaft.prt.2`) and note the vault tip will be logical (`shaft.prt`); write the vault tip as the **logical** name and drop numbered siblings so Git history stays on one path; release unchanged checkouts so the product looks checked in | Treat a rematerialized tip with the same content hash as changed; treat a replaced workspace file as unchanged when its content hash differs from the vault tip; strip the Creo `.N` in the Check In dialog (show only the vault logical name); store `shaft.prt.4` as the vault tip; run when there’s nothing to do (button should stay disabled); appear without `objects.checkin` |
| Check in selected… | Check in what you selected (vault tip stays logical); show the **local Creo tip** as Object (`shaft.prt.2`) plus a short note that the vault tip will be `shaft.prt`; when the Check In menu is open, keep **Check in selected…** visible but **greyed** if the selection has no pending Modified work (clean checkout / rematerialized tip matches vault / New-files-only selection), and put the reason on the hover title (New files → use Add selected…); for **one** modified Creo model (Creo Connected) when **Enable AI features** is on, show **Ask AI for comment** in the dialog — compare the **saved tip snapshot** (e.g. A.1) to a **fresh gather** of the open model using the **same** `aiSnapshotBodyFromGather` → `prepare_snapshot_for_compare` → outline/computed-diff → Ollama path as **Compare Revisions → Ask AI** (parts, assemblies, and drawings — not a separate check-in-only prompt); keep the Creo window open (do not Erase/retrieve over it); fall back to the local workspace tip only if it is not in session; never re-materialize the vault tip; does not overwrite the tip snapshot; uses the **AI** settings prompt; send Ollama a plain-language outline per revision, each block labeled **OLD snapshot** (tip already checked in) then **NEW snapshot** (what you are checking in) so the model cannot swap them (features or drawing **Views**/sheets/referenced models, dimensions, material, parameters — not raw snapshot JSON; pattern-member shells collapsed onto numbered PATTERN lines (`PATTERN 1`, `PATTERN 2`, … with member counts) so a deleted pattern can be named singularly; CreoPDM also appends an authoritative OLD→NEW feature/dimension/Structure diff so the model cannot invent a value change by pairing two different removed symbols (e.g. d248 = 7 with d255 = 6)); put the summary into the Comment box so you can edit then Check In (drawings compare views/sheets/drawing dims — not the referenced PART; **Delete View** removes a view from the list — **Erase View** may still look unchanged if Creo does not expose erased state) | Relabel to **Add selected…** (that lives under Add ▾); hide the item with no explanation when clean checkouts are selected; strip the Creo `.N` in the Check In dialog so you cannot tell which local save is being recorded; appear without `objects.checkin`; run while greyed; show Ask AI for multi-file / Add-only / outside Creo without explaining why; dump hundreds of unnamed `Feature NNNN` rows into the AI prompt |
| Leave the comment blank | Block check-in until you write a comment | Save a version with no comment |
| Finish successfully | List and status update to match the vault; when creopdm-agent is online, rematerialize each **checked-in** file as the **logical** local tip (`shaft.prt`) and **trash higher local `.N` leftovers** (e.g. drop `shaft.prt.2`); **keep Creo windows open** (do not Erase the session on check-in — History Revert may still erase); if a higher `.N` stays because the model is still open/locked, tell you to close that window or use **File → Erase**, then Open again; Creo saves afterward may create higher `.N` siblings for the next edit | Leave the vault tip renamed to a Creo `.N`; invent `.prt.1` on materialize when the vault tip is logical; leave `shaft.prt.2` (or higher) in the local workspace after a clean check-in of that file when nothing holds the lock; Erase unrelated open models or every product checkout released by **Check in product…** |

---

## 11. Export ▾

Toolbar menu **Export ▾** (same pattern as Check In ▾). Confirm, then busy overlay, then save the zip (creopdm-agent Save As when available; otherwise browser download).

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Export ▾** | Show **Export product…** (when you have `products.export`) enabled when the product has at least one vault file, otherwise greyed with a hover title; show **Export selected…** (when you have `objects.export`) greyed out until files or folders are selected; **hide Export ▾** when every item would be greyed (empty product and nothing selected) | Hide **Export product…** just because nothing is selected while the product still has vault files; leave **Export product…** enabled on an empty product; leave **Export ▾** visible when both items are greyed; require the product to be In work |
| Click **Export product…** | Confirm whole-product export in the CreoPDM dialog; zip the vault tip for every file under the **logical** name (`shaft.prt`, not `shaft.prt.1`); require `products.export` and at least one vault file | Run while the menu item is greyed (empty product); check out or lock anything; use a browser `confirm`; switch to selection export because something is selected; pack Creo `.N` save numbers into the zip |
| Click **Export selected…** with files and/or folders selected | Confirm selection export in the CreoPDM dialog; zip only those vault tip files (folders include descendants) under logical names; require `objects.export` | Run while the menu item is greyed (nothing selected); appear without `objects.export`; use a browser `confirm`; pack Creo `.N` save numbers into the zip |
| Cancel the confirm or Save dialog | Stop with no zip | Leave a partial download claimed as success |
| Agent offline | Fall back to a browser zip download | Fail only because the agent is offline |

Starter roles: Administrator, PDM Manager, and Engineer get both export permissions. Viewer does not.

---

## 12. Remove ▾

1. **Remove from Workspace…** — trash local copies on this PC only; vault and product list unchanged (ellipsis — opens a confirm)  
2. **Purge workspace…** — trash older local numbered saves that are below the vault version; vault unchanged (warning dialog)  
3. **Clear workspace…** — trash everything **inside** this product’s local workspace folder on this PC (including local-only new files); keep the empty folder so Creo’s working directory can stay set; vault and product list unchanged  
4. **Remove from Vault…** — delete CreoPDM’s vault copies; your original CAD folder stays; checkouts cancelled (warning dialog)  
5. **Remove from Product…** — remove from this product and delete vault copies; originals stay (warning dialog) 

Destructive actions ask you to enter your password ([§13](#13-entering-your-password-to-confirm)).

### Remove from Workspace…

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Remove from Workspace…** (Remove ▾ or right-click) | Show the ellipsis (opens a confirm); move selected local “new” files to the Recycle Bin on this PC; right-click shows the item only when the toolbar button would be available | Omit the ellipsis when it opens a confirm; change the vault or product file list; show the right-click item when Remove ▾ / Remove from Workspace… is hidden |
| Agent not running | Tell you to start creopdm-agent | |

### Purge workspace…

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Purge workspace…** | Show the danger-confirm warning (red menu item + ellipsis) | Omit the ellipsis or red styling when it opens a confirm |
| Confirm purge | Remove only older local saves below the vault tip floor (logical vault tips use floor `.1`); keep vault copy and newer local work | Delete anything from the vault |
| Nothing to purge | Say so; delete nothing | |

### Clear workspace…

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Clear workspace…** | Show the same danger-confirm warning dialog used elsewhere (Cancel / Clear workspace) — no password — explaining everything inside the local workspace on this PC is deleted, including local-only **new** files that were never added; say the empty folder stays (Creo WD can remain); vault copies and the product list stay (rematerialize later) | Ask you to enter your password; use a plain browser `confirm`; delete the workspace folder itself when Creo’s WD points there; delete vault files or change the product list |
| Confirm | Move local workspace **contents** to the Recycle Bin on this PC in **one** operation (not file-by-file); leave the workspace folder | Walk/recycle each file one at a time; leave local-only new files behind when the clear succeeded; fail just because Creo’s working directory is still the workspace folder |
| Agent not running / Creo still has files open | Show a clear error; change nothing on the vault | Silently fail or claim vault was cleared |
| Cancel | Change nothing | |

### Remove from Vault…

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Remove from Vault…** | Show the danger-confirm warning (red menu item + ellipsis) | Omit the ellipsis or red styling when it opens a confirm |
| Confirm | Delete vault copies of the selection | Delete files in your original product folder on disk |

### Remove from Product…

| You do | App should | App must not |
|--------|------------|--------------|
| Select files and/or folders (including empty folders) | Enable **Remove from Product…** (ellipsis — opens the warning dialog) | Stay disabled just because a folder is empty; omit the ellipsis when it opens a confirm |
| Confirm with your password | Remove from the product; delete vault copies; **rows disappear right away** | Leave the folder/file visible until F5 |
| Optionally also delete local workspace | Clean local copies if you checked that box | Delete your original CAD source folder unless you asked for workspace cleanup |
| Enter the wrong password | Show an error; change nothing | Remove anything |
| Cancel | Change nothing | |
| File checked out by someone else | Skip that file with an error; may still remove others | Quietly remove their locked file |

---

## 13. Entering your password to confirm

Used for delete product, remove from product/vault, purge, History **Revert to selected…**, Utilities compact/rebuild/delete, and similar. **Clear workspace…** uses the same danger-confirm warning dialog but does **not** require your password.

| You do | App should | App must not |
|--------|------------|--------------|
| Enter your signed-in account password | Verify it on the server, then allow Continue (including **Delete product** on the gear — password only, never type the product name) | Trust a product-name match alone; accept a wrong password; show **Type the product name exactly to delete it** after you entered a password |
| Wrong password or blank | Show an error (Incorrect password / Enter your password…) | Proceed; echo the password back into the form; ask for the product name |
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
| Open a file’s Details page | No bottom Details toolbar (no Revert / Check In chrome); Creo stays Connected | Show the desktop Details action bar; hard-reload and drop Creo |

### Lists and columns

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Files** or **Checked out** | Show **Name** and **Rev** only | Force sideways scrolling for State / Type / Creo / Modified / Checkout |
| Open **Modified** or **New files** | Show **Filename** only | Crush headers into vertical “CHANGE” / “FILENAME ()” text |
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

## 15. Administration (users, roles, membership, email, utilities, system settings)

Use a normal browser for these checks. You need the matching Administration permission for each live tile. **Audit log** lives under **Utilities** (not a separate Administration tile).

### Hub

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Administration** | Show permission-gated tiles (Users, Roles, Membership, Products, Email, **Utilities**, **System Settings**, **AI**); **AI** opens `/settings/ai`; **Utilities** blurb mentions Audit log; **System Settings** opens a hub of section tiles | Keep a greyed **AI** “coming soon” placeholder; keep a separate disabled **Audit** tile on Administration; label the settings tile only **Settings**; dump every system setting on one long page from Administration |
| Open **System Settings** | Open `/settings` as a hub of short tiles in the same order as before (**Open Creo models**, **Vault**, **Creo Models**, **Documents**, **Creo-openable models**, **Text files**, **Non openable CAD**, **Numbered saves**, **File type names**, **Ignored files**, **Network**, **Local Creo agent**, **Database**, **AI**); each tile opens its own page to edit that section | Dump every settings section on one long page; reorder tiles differently from the former single page; keep **Availability** under System Settings (it lives under **Utilities**) |
| Open **AI** (Administration or System Settings) | Show Ollama host URL, model, and an editable **Snapshot compare prompt** (paste your own text — nothing is seeded from code); **Refresh models** asks the CreoPDM server first, then this browser if the server cannot reach Ollama; Save persists URL + model + prompt in server settings; **Enable AI features** checkbox (on by default) gates every Ask AI control and the compare API when unchecked, and grays out / disables the Ollama URL, model, Refresh models, and compare-prompt fields until AI is turned back on; **Ask AI what changed** uses the saved prompt as **system** instructions only (errors if empty); CreoPDM appends labeled **OLD** / **NEW** outlines (same text as the Snapshot panes) plus a **Computed differences** fact block (component/feature/dimension bullets — no narrative cite rules in code) | Bake narrative Ask AI instructions into Python; offer Reset-to-default that reloads code text; leave Ask AI clickable when AI is off; clear the model list when Ollama is offline without keeping a saved model option; fail silently with no status text; dump raw snapshot JSON into Ollama |
| Set **CreoPDM unavailable** and save | Non-administrators see the maintenance message on their **next page open or navigation** (including soft-nav); the default message gets a pretty **Since …** date automatically; administrators keep using the app and the **Unavailable** warning pill appears **immediately** after Save (no need to leave Settings); uploads / check-ins / API calls already in progress are **not** cancelled | Block or roll back in-flight API / Git / DB work; hide the app from administrators; wait until you leave Settings to show the reminder pill; omit when the outage started from the default message |
| Set **CreoPDM available** again and save | Everyone sees normal pages again; Unavailable pill hides right away after Save | |
| Leave a product Files page open with no mouse/keyboard/touch for longer than **Pause refresh after idle** | Stop file-list / agent workspace polling until the user interacts again (or the tab becomes visible again); default 10 minutes; **0** = never pause for idle | Keep polling overnight while the tab sits idle with a non-zero idle pause |
| Open **Administration**, **System Settings**, or a file **Details** page (or soft-nav away from the product Files list) | Stop workspace-watch / file-list change polling while that page is open; do not probe creopdm-agent `/health` for the status pill on those pages (Files list only); resume when you return to a product Files list | Keep polling for list/check-in changes while Admin, Settings, or Details is open; hit agent `/health` on every Admin/login load |

### First-run setup

| You do | App should | App must not |
|--------|------------|--------------|
| Open the app when **no users** exist yet | Send you to **Create administrator** (`/setup`) | Let you use Files / login as if accounts already exist |
| Create the first admin with display name, username, **email**, and password | Create an **Administrator** with **All products**, sign you in, and take you to the app | Accept a blank email or an incomplete address like `user@host` (no domain suffix); leave email optional |
| Try `/setup` again after any user exists | Redirect to login | Create a second “first” admin |

### Sign in and forgot password

| You do | App should | App must not |
|--------|------------|--------------|
| Open `/login` with no recent failure (including after **Logout** in Creo’s embedded browser) | Show username + password only; do **not** show a blocking **Connecting to Creo…** overlay (Creo.JS may re-link in the background; pill may briefly say Session offline) | Show **Forgot password?** before a failed attempt; trap the sign-in form behind **Connecting to Creo…** for many seconds after Logout |
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
| Edit permissions on a role | Save when at least one ACTIVE user still has full CreoPDM Administration (including `email.manage` and all `utilities.*` keys) | Strip the last full admin’s Administration set |
| Change name / description / Administration checkboxes on **your own** role | Reject the change | Let you lock yourself out of Administration |

### Utilities (Administration → Utilities)

Needs the matching Utilities permission for each tool (`utilities.availability`, `utilities.email_users`, `utilities.compact_product`, `utilities.rebuild_product`, `utilities.delete_product`, `utilities.audit`, `utilities.health`, `utilities.logs`). Administrator has all of them by default. The hub opens if you have **any** of those keys.

| You do | App should | App must not |
|--------|------------|--------------|
| Open **Utilities** | Show only the hub tiles your role grants (Availability also when you have `settings.manage`); same pattern as Administration home | Dump every tool and health section on one long page; let PDM Manager / Engineer open a tool without its permission; keep Remove/Delete on Administration → Products → Edit; leave **Availability** only under System Settings; keep a single `utilities.access` umbrella |
| Open **Availability** | Show the site available / unavailable radios and maintenance message (same Save as System Settings used to); works when locked for maintenance so admins can turn it back on; old `/settings/availability` links redirect here | Hide Availability from Utilities; leave non-admins able to change it |
| Open **Audit log** | Show a filterable table of server-side PDM events (Timestamp, Event, User, Client, Product, Object, Comment/summary) with human-readable event names (including **Product state changed** when lifecycle state or read-only changes on product Edit/Save); **Timestamp** shows the compact local stamp with a hover of the same pretty long form used on Files/Details (e.g. Monday, July 23, 2026 at 5:30pm); **Client** is the requester IP (or workstation name when auth is off); **Filters** in a multi-column grid (search full width; Event/User/Product/Object/dates beside each other on wide screens) so the Events table is not pushed far down; **Search** across user/file/product/comment/commit (not hidden server vault paths in event details); dropdowns for Event, User (name, or “no longer in users”), and Product (name + short UUID); **Event** filter lists common daily actions first (**Check in/Check out**, **Object added**, **Sign in/Sign out**, **Sign-in failed**, **Password changed**, …) with rarer admin ops last; **Check in/Check out** and **Sign in/Sign out** are each one filter choice (table rows still show Checked in / Checked out / Signed in / Signed out); optional object text + date range (**From** defaults to one week ago; **To** defaults to today); filter fields share one width and site font; newest first; page capped; **Export CSV** sits on the right of the **Events (up to N)** heading and downloads the same filtered results shown in the table (up to the page cap) using the current filters; Object/summary show filename from details even when the file row is gone; batch Object cells show the first name plus a clickable **(+N more)** that expands a list of the other stored filenames under that row (toggle again to collapse); multi-chunk Adds (browser uploads, agent 25-path `/add-paths` calls, and agent 5-file upload sub-chunks) share one Audit **Object added** row via a single `import_batch_id` for the whole Add (Comment shows e.g. Add 935 files — not one row per chunk each claiming Add 935 files); Comment/summary holds real comments / iteration / git / state notes — not a repeat of the Object label for Add/Remove/Checkout; **Product** / **Object** are links only when you can open that product (membership + view permission) — Product opens Files, Object opens Details; audit rows are **append-only** and survive **Delete product** / object purge (product name shows as **Name (deleted)** when the product is gone; a **Product deleted** event is recorded); deleting a product must **not** wipe its prior Add/Check In/Checkout history; name/number/description edits stay **Product updated**; state/read-only alone is **Product state changed** (both when Save changes identity and lifecycle together) | Treat vault Git history / blame as the audit trail; offer delete or edit of audit rows; wipe audit history when a product is deleted; expose Audit to users without `utilities.audit`; require typing product UUIDs to filter; leave From/To blank by default; show a useless Machine=`web` label; stack filters in one tall single column; leave **(+N more)** as plain non-clickable text; duplicate the Object label into Comment/summary for every Add; write a separate Audit row for every 5-file upload chunk or every agent 25-path `/add-paths` call of one Add; link into products the viewer cannot open; log state/read-only changes only as **Product updated**; alphabetize Event filter; list Signed in and Signed out (or Checked in and Checked out) as separate Event filter choices; omit CSV export for the filtered results; stack **Export CSV** under the Events heading; show a muted “Not vault Git history” intro under the Audit log title |
| Open **Email all users** | Show the broadcast form on its own page | |
| Fill subject + message, check the confirm box, **Send email to all users** | Email each **active** user individually (using Administration → Email delivery settings); skip disabled accounts; keep addresses private | Send without confirm; put every address in one To/Cc list; email disabled users |
| Open **Compact product vault history** | Show the compact form on its own page | |
| Choose a product, enter your **password**, check the danger box, **Compact vault history** | Show the busy overlay (**Compacting vault history for …**) until the server finishes; squash that product’s vault to one tip commit, prune older History versions in the DB, and Git-gc so removed-file bytes leave `.git/objects`; tip files stay; report before/after `.git` size; auto-align leftover working-tree drift after Remove-from-Product (do not fail only because purge left deleted paths uncommitted) | Leave you staring at a frozen form with no busy feedback; run without password / danger confirm; run while any checkout is active; rewrite other products; keep old History rows that point at deleted Git commits |
| Open **Rebuild product database** | Show the repair form on its own page (product pick + **one** action radio + password + danger confirm). All three actions start **unselected** — choose exactly one before running | Offer multi-select checkboxes that imply combining rebuild + clear metadata + Where Used in one click |
| Choose a product, pick **one** action, enter your **password**, check the danger box, **Run selected action** | Show the busy overlay until the server finishes. **Rebuild** / **Delete Creo metadata** use a matching busy line. **Delete and rebuild Where Used** returns the form response first, then Start returns with parent count so the overlay moves to **Indexing Where Used… N of M** (same as the product gear), with **Escape** aborting in-flight Start/polls, stopping the job, and clearing the overlay (not leaving the page hung on preparing…). **Rebuild** clears that product’s file/version/checkout/Where Used/metadata rows and re-registers tip files from the vault Git tip (hashes + HEAD; release checkouts first). **Delete Creo metadata** nulls collected identity/BOM/etc. and parameters without removing file rows. Keep the product row and vault Git history; works when locked or **Archived**; tell you to collect metadata again when it was cleared | Let more than one repair action run together; return Start with parents_total=0 while another Start is still priming; leave Escape dead while Start/poll fetch is hung; start Where Used indexing under the open form DB session so the busy overlay stays on preparing…; swallow Run with preventDefault and no handler; leave the busy modal stuck after Cancel; show a generic “Repairing…” busy line; leave Where Used busy text without N of M; rewrite Git history; delete the vault; run with no action selected / without password / danger confirm; run **Rebuild** while any checkout is active; change other products; invent tip files that are not tracked |
| Open **Delete products** | Show the delete form on its own page (product pick + password + danger confirm) | Offer delete on the product Edit form |
| Choose a product, enter your **password**, check the danger box, **Delete product** | Show the busy overlay until the server finishes; delete the CreoPDM vault and unregister the product (works when locked or **Archived** too) | Delete original CAD folders you imported from; run without password / danger confirm; leave an orphan vault folder or DB row |
| Open **Health** | Show system health, database probe, Git version, **CPU** load, **I/O** (I/O wait % on Linux + disk read/write + network receive/send rates; loopback excluded), **Products** (lightweight vault/tip checks: missing vault or `.git`, broken git HEAD, tip commit missing from repo, orphan vault folders, files with history but no current version — issues mark overall health **degraded**), disk space (**System** volume free/used once; Data / Vaults / Logs each show that folder’s used size), product/user/checkout counts, and server paths. CPU and I/O are display-only; Products issues do degrade overall status. Logs folder paths are plain text unless you also have `utilities.logs` | Repeat the same volume free/used under every path; treat high CPU / I/O wait as overall health error; walk every vault file or run `git fsck` / compact on Refresh; create or repair vaults from Health; link Logs paths when the role lacks `utilities.logs` |
| Open **Logs** (Utilities hub tile, or a Logs path link on Health when you also have Logs) | Open `/admin/utilities/logs` listing files in the server logs folder and show the end of the selected log (default `creopdm.log`); needs `utilities.logs` (separate from Health) | Expose files outside the logs directory; open a Windows Explorer window on the server path; open Logs with only `utilities.health`; show a Logs link on Health without `utilities.logs` |
| Click **Refresh** on Health or Logs | Re-run the probes / reload the log tail | Change settings or mutate vault data |

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
7. Confirm with your password.  
8. Folder is gone from the list immediately; no F5 needed.

Try the same with **Add folder…**, **Add folders…**, and **Compressed data…** (agent + `.zip`).

### Things that should fail (and say why)

- Create folder with blank name, `Bad/Name`, or a duplicate name.  
- Remove with the wrong password, or Cancel.  
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
- Utilities without any `utilities.*` → 403 on hub; with a tool key → only that tile; Logs hub tile / Health Logs links open `/admin/utilities/logs` only with `utilities.logs` (Health alone shows Logs paths as plain text); product Edit has no Remove form; Delete-products tip needs `utilities.delete_product`.
- Audit log without `utilities.audit` → 403; filters are GET-only (search + dropdowns); no delete/edit UI; Git is not the audit source; Object/summary show filenames from event details; **(+N more)** expands stored filenames under the row; Product/Object links only when the viewer can open that product; product delete keeps prior audit rows and records **Product deleted**; product Edit state/read-only Save records **Product state changed** (name edits stay **Product updated**); Timestamp hover shows the pretty long date; Event filter leads with **Check in/Check out** (common first) and groups **Sign in/Sign out**; **Password changed** is logged for account change, admin set, and forgot-password reset; **Export CSV** downloads the filtered table results; Search does not match solely on hidden vault filesystem paths in event details.
- Compact vault history → tip stays; older History gone; blocked when checkouts active or vault dirty; busy overlay until the form POST returns.
- Utilities email-all without confirm or blank subject → blocked; disabled users not emailed.
- Cancel Watch / Stop watching confirmation → subscription unchanged.
- Notifications disabled → no product watch bell on Files.
- User A watches; user B opens the same product → B is not watching; B’s Stop does not clear A.

---

## 17. For developers (tests)

Automated coverage lives mainly in:

- `tests/unit/test_ui_regressions.py` (includes `test_mobile_browse_css_is_minimal`, `test_details_where_used_tab_gated_on_creo_models`, `test_files_search_survives_details_and_back`, `test_modified_tab_between_checked_out_and_new_files`, `test_locked_product_changes_help_does_not_offer_add_checkin`)
- `tests/unit/test_ai_snapshots.py` (Compare Revisions tab + `object_version_snapshots` API/service)
- `tests/unit/test_user_interaction_validations.py`
- `tests/integration/test_objects.py` (create folder / batch remove)
- `tests/integration/test_checkin.py` (History revert restores Creo `.prt.N` name, not tip overwrite)
- `tests/unit/test_auth.py` (role matrix + Roles admin + Viewer `products.view` / `objects.view` / `data-can-checkout`; empty-home `products.create` hero; empty-product `objects.add` invite; `test_every_starter_role_login_permission_matrix`; `test_role_with_no_permissions_cannot_browse`; `test_admin_without_products_view_lands_on_administration`; `test_setup_and_admin_user_require_email`; `test_username_rejects_spaces_and_email_needs_domain`; `test_admin_email_settings_save_and_gate`; `test_admin_utilities_status_and_gate`; `test_admin_utilities_email_all_users`; `test_admin_utilities_compact_vault_gate`; `test_admin_membership_product_access_filters_products`; `test_role_assign_must_be_strictly_below_actor`; new users default to no product access)
- `tests/unit/test_activity_audit.py` (list_events filters; force-undo → `CHECKOUT_OVERRIDE`; settings password redaction; Activity model columns)
- `tests/unit/test_vault_compact.py` (compact tip-only history; drop removed-file blobs; reject dirty vault / active checkout / wrong name)
- `tests/unit/test_utilities_rebuild_product.py` (rebuild from vault tip; clear Creo metadata; delete and rebuild Where Used; require exactly one action)
- `tests/unit/test_where_used_auto_index.py` (prime parents total on Start for 0 of N; Escape → DELETE cancel wiring; Add waits under busy overlay)
- `tests/unit/test_top_level_assemblies.py` (Where Used index gate; drawing parents ignored for top-level; Rebuild clears false asm→asm parents; bare Creo names collapse Top Level)
- `tests/unit/test_where_used_name_match.py` (Where Used bounded stems + unique stems; glued tokens ignored)
- `tests/unit/test_creo_dependencies.py` (open dependencies walk sub-assemblies + parts across folders; walk returns storeable edges)
- `tests/unit/test_open_large_assembly_contract.py` (JD-scale Open: no WU discard, product-fill, magnet prune ≥200, scaled Creo open timeout)
- `tests/integration/test_creo_open.py` (`test_open_dependencies_prefer_where_used_db`, `test_open_dependencies_trust_large_where_used_tree`, `test_open_dependencies_sparse_where_used_falls_back_to_vault_scan`, nested vault-scan stores Where Used / Top Level)
- `tests/unit/test_creopdm_agent.py` (`test_agent_materialize_skips_unchanged_local_files`)
- `tests/unit/test_password_reset.py` (forgot link only after wrong password; GET blocked; wrong email same confirmation / one try; spam disable)
- `tests/unit/test_product_watch.py` (bell when email enabled; per-user watch; subscribe/unsubscribe; one email per bulk action; actor excluded; notifications off skips mail; Force Undo Checkout emails former owner)
- `tests/unit/test_launch.py` / `tests/unit/test_creopdm_agent.py` (Open workspace creates empty agent cache and opens via ShellExecute explore)
- `tests/integration/test_settings.py` (Settings open-mode copy mentions OS association fallback)
- `tests/unit/test_site_availability.py` (unavailable is display-only HTML for non-admins; API stays up; admin pill + Utilities → Availability panel)
- `tests/integration/test_creo_metadata.py` (Collect is `creo-session-only`; Rebuild Where Used is always on the gear when metadata tools are allowed; Details **Where Used** only for Settings → Creo Models extensions)
- `tests/integration/test_checkout.py` (product lock UI: ON_HOLD / read-only hide Add & Check In; Checkout stays for Undo)
- `tests/integration/test_product_lifecycle_lock.py` (locked product rejects add/checkout/check-in/remove/rename/metadata; forget/delete still purges; undo still allowed)
- `tests/integration/test_products.py` (`test_forget_archived_and_inactive_products_purges_db`)
- `tests/unit/test_product_state.py` (allows_mutation / ensure helpers / `product_ui_capabilities`)
- `tests/unit/test_product_access_policy_contract.py` (mutation modules call `ensure_*`; templates use `product_ui`; `app.js` does not re-encode lock)
- Related checkout / check-in / soft-nav tests

Mobile browse is CSS-only in `app.css`: `@media` with `pointer: coarse` and `hover: none` (plus width/height limits). Do **not** gate browse mode on `max-width` alone.

When you change any behavior above, update **this document** in the same change and add or adjust tests so the “must not” cases stay covered. See `.cursor/rules/user-interactions.mdc`.
