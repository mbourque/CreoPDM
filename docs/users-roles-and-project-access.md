# Users, roles, and project access

## Phase 1 (shipped): login and users admin

CreoPDM uses **session cookie** authentication. Passwords are stored as **Argon2id** hashes only — there is no default password in the source tree.

### First-run setup

When the `users` table has **zero** rows, opening the app redirects to **`/setup`**:

1. Enter display name, username (suggestion: `admin`), password, and confirm.
2. CreoPDM creates an **ACTIVE** user on the **Administrator** starter role, signs you in, and sends you to the app.
3. After any user exists, `/setup` is disabled; unauthenticated visitors go to **`/login`**.

### Sign in / out

| Page | Purpose |
| --- | --- |
| `/login` | Username + password |
| `/logout` | Clears the session cookie |
| `/account/password` | Change password (required when `must_change_password` is set) |

Disabled accounts cannot sign in. Checkout, check-in, and activity rows store the **login username** as text (same columns as before; no `user_id` FK yet).

### Administration

Users with any CreoPDM Administration capability (`users.manage`, `users.password`, `roles.assign`, `roles.manage`, `projects.assign`, `projects.manage`, `settings.manage`, `email.manage`) see **Administration** (`/admin`):

- **Users** — list accounts (Projects column: **All** or membership count); click a **name** to edit the user, or a **role** name to open that role (`roles.manage`); **Add user** (`users.manage` + `users.password` for the initial password). New users get **All projects**; membership is not edited here.
- **Roles** — list/create/edit/delete roles and their permission checkboxes (`roles.manage`). The role editor groups **CreoPDM Administration** (`users.manage`, `users.password`, `roles.assign`, `roles.manage`, `projects.assign`, `projects.manage`, `settings.manage`, `email.manage`), **Projects**, and **Objects**.
- **Membership** — decide who can open which projects (`projects.assign`): hub with **By project** and **By user** list pages, then edit members / All-projects for one row
- **Projects** — list every active project on the server; create, edit, and soft-delete (`projects.manage`). Not limited by the signed-in user’s project membership list. (Files-page New/Delete still use `projects.create` / `projects.delete`.)
- **Email** — SMTP (defaults `localhost:25` for local Postfix), From address, administrator email, optional auth/TLS, Test Email (`email.manage`)
- **Settings** — server options (Creo open mode, vault, file types, …) (`settings.manage`)
- After a successful **Add user** / **Save** / role save / project save / membership save, you return to the list
- New users must change their password on first sign-in

Others do not see Administration; direct URLs return **403**.

**Lockout safety:** at least one **ACTIVE** user must keep **all** CreoPDM Administration permissions on the same account. Saving a role, demoting/disabling a user, or deleting a role is rejected if it would leave nobody with the full set. You also cannot change **name**, **description**, or **CreoPDM Administration** checkboxes on a role **assigned to you**, and you cannot **delete** your own role — ask another administrator.

**Admins edit admins only:** a full administrator (all Administration caps) may edit **other** full administrators and assign full-admin roles. Full administrators may also edit **their own** account from Users admin (the only self-edit exception), but **cannot** change their own role or disable/change their own status — ask another administrator. Other accounts still cannot edit themselves — ask another administrator, or use **Account → password** for your own password.

**Fine-grained Users admin caps** (separate from `users.manage`):

| Permission | Allows |
| --- | --- |
| `roles.assign` | Change another user’s role (otherwise Role is read-only; new users default to **Engineer**) |
| `users.password` | Set initial password on Add user, or reset password on Edit |
| `projects.assign` | Open **Administration → Membership** (By project / By user). New users still default to All projects |

Full-admin roles still require a full administrator to assign.

### Project access (Membership)

On **Administration → Membership** (`projects.assign`):

| Mode | Behavior |
| --- | --- |
| **By user** | **All projects** (default) or a multi-select project list; none selected → empty project list / **403** on project URLs |
| **By project** | Tick which **restricted** users are members. Users with All projects are listed read-only (they already see the project); change All projects under By user |
| **Hub summary** | Table of projects with **Members** (who can open = restricted + All-projects users), **Restricted** counts, and **Manage** links |

Creating a project while signed in as a restricted user automatically grants that user access to the new project.

### Checkout exclusivity

A file may be checked out by **one** user at a time. If Paul has a checkout, David cannot check out the same file until Paul checks in or undoes the checkout. The checkout row stores the login **username**.

Empty databases seed four **starter** roles (**Administrator**, **PDM Manager**, **Engineer**, **Viewer**) once. After that, permissions live only in the database — see Phase 3. Reference matrix: [initial-built-in-roles.md](initial-built-in-roles.md).

## Phase 2 (shipped): core role matrix

Permission keys (`projects.*`, `objects.*` including **`objects.view`**, `users.manage`, `users.password`, `roles.assign`, `roles.manage`, `projects.assign`, `projects.manage`, `settings.manage`, `email.manage`) gate APIs (**403** when missing). Browse/open/download requires **`objects.view`** — a role with no permissions cannot use the Files page. After sign-in, accounts **without** `objects.view` land on **`/admin`** when they have any Administration capability, otherwise on a plain **`/no-access`** page (not a JSON error). Administration breadcrumbs omit the **Projects** link when `objects.view` is missing. The Files toolbar and project New/Delete controls hide when the matching capability is false. Viewer Open dialog offers view-only open (no “Check out … then open”) when `objects.checkout` is missing (`data-can-checkout` on the page).

| Starter role (default seed) | Can do | Cannot |
| --- | --- | --- |
| **Viewer** | Browse, open/download, Details (`objects.view` only; Open goes straight to open — no checkout dialog) | Authoring toolbar, Copy to Vault, checkout-on-open, Administration |
| **Engineer** | View + Add, checkout, check-in, remove, revert, metadata | Create/edit/delete projects, Copy to Vault, users, roles, settings |
| **PDM Manager** | Create/edit projects (Files/API) + Engineer authoring + **Copy to Vault** | Delete project, Administration → Projects (`projects.manage`), users, roles, settings, email |
| **Administrator** | Everything above + delete project + full CreoPDM Administration (including Admin → Projects and Email) | — |

Automated coverage: `tests/unit/test_auth.py::test_every_starter_role_login_permission_matrix` creates one ephemeral user per starter role, logs each in, and asserts allow/deny for every built-in permission key (plus Files toolbar chrome and **project membership**: All / one project / none). Dedicated UI + lifecycle coverage: `test_admin_membership_project_access_filters_projects`.

When `auth_enabled` is false (unit tests with a static identity), all authoring and project caps are granted so the existing suite stays green.

## Phase 3 (shipped): Roles admin (DB is source of truth)

- **`/admin/roles`** — create roles, edit name/description/permissions, delete unused roles
- Runtime caps come only from `role_permissions` (no Administrator-by-name short-circuit; starter templates are not re-applied on restart)
- Safety: cannot leave zero **ACTIVE** users with full CreoPDM Administration (`users.manage` + `users.password` + `roles.assign` + `roles.manage` + `projects.assign` + `projects.manage` + `settings.manage` + `email.manage` on the same account); cannot delete a role that is still assigned; cannot rename, re-describe, change Administration permissions on, or delete a role assigned to yourself
- Starter roles are editable like any other role

### Deferred (later phases)

- Project-level roles (different role per project)
- Override-checkout UI; lifecycle / release product surfaces
- Per-user notification subscriptions; Agents / Storage / Audit admin sections

### Agent auth (shipped)

Signed-in pages expose a short-lived **agent Bearer** (`data-agent-token`). The browser passes it to creopdm-agent on materialize/push/add; the agent sends `Authorization: Bearer …` to CreoPDM. The server verifies the token as that user (same caps). Open outside Creo’s embedded browser uses agent cache + **Windows association**.
