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

Users with `users.manage`, `roles.manage`, or `settings.manage` see **Administration** (`/admin`):

- **Users** — list accounts; click a **name** to edit (display name, email, role, status, project access, set/reset password); **Add user** (`users.manage`)
- **Roles** — list/create/edit/delete roles and their permission checkboxes (`roles.manage`)
- **Settings** — workstation options (Creo open mode, vault, file types, …) (`settings.manage`)
- After a successful **Add user** / **Save** / role save, you return to the list
- New users must change their password on first sign-in

Others do not see Administration; direct URLs return **403**.

### Project access (per user)

On **Add user** / **Edit user**, admins set which projects the account may open:

| Control | Behavior |
| --- | --- |
| **All projects** (checkbox, default on) | User sees every project; the project list below is disabled |
| Project multi-select (scrollable) | When All projects is off, only selected projects appear in the app and APIs |
| None selected (All off) | User can sign in but cannot browse or open any project (**empty** project list / **403** on project URLs) |

Creating a project while signed in as a restricted user automatically grants that user access to the new project.

### Checkout exclusivity

A file may be checked out by **one** user at a time. If Paul has a checkout, David cannot check out the same file until Paul checks in or undoes the checkout. The checkout row stores the login **username**.

Empty databases seed four **starter** roles (**Administrator**, **PDM Manager**, **Engineer**, **Viewer**) once. After that, permissions live only in the database — see Phase 3. Reference matrix: [initial-built-in-roles.md](initial-built-in-roles.md).

## Phase 2 (shipped): core role matrix

Permission keys (`projects.*`, `objects.*` including **`objects.view`**, `users.manage`, `roles.manage`, `settings.manage`) gate APIs (**403** when missing). Browse/open/download requires **`objects.view`** — a role with no permissions cannot use the Files page. After sign-in, accounts **without** `objects.view` land on **`/admin`** when they have any Administration capability, otherwise on a plain **`/no-access`** page (not a JSON error). Administration breadcrumbs omit the **Projects** link when `objects.view` is missing. The Files toolbar and project New/Delete controls hide when the matching capability is false. Viewer Open dialog offers view-only open (no “Check out … then open”) when `objects.checkout` is missing (`data-can-checkout` on the page).

| Starter role (default seed) | Can do | Cannot |
| --- | --- | --- |
| **Viewer** | Browse, open/download, Details (`objects.view` only; Open goes straight to open — no checkout dialog) | Authoring toolbar, Copy to Vault, checkout-on-open, Administration |
| **Engineer** | View + Add, checkout, check-in, remove, revert, metadata | Create/edit/delete projects, Copy to Vault, users, roles, settings |
| **PDM Manager** | Create/edit projects + Engineer authoring + **Copy to Vault** | Delete project, users, roles, settings |
| **Administrator** | Everything above + delete project + users + roles + settings | — |

Automated coverage: `tests/unit/test_auth.py::test_every_starter_role_login_permission_matrix` creates one ephemeral user per starter role, logs each in, and asserts allow/deny for every built-in permission key (plus Files toolbar chrome and **project membership**: All / one project / none). Dedicated UI + lifecycle coverage: `test_admin_user_project_access_filters_projects`.

When `auth_enabled` is false (unit tests with a static identity), all authoring and project caps are granted so the existing suite stays green.

## Phase 3 (shipped): Roles admin (DB is source of truth)

- **`/admin/roles`** — create roles, edit name/description/permissions, delete unused roles
- Runtime caps come only from `role_permissions` (no Administrator-by-name short-circuit; starter templates are not re-applied on restart)
- Safety: cannot leave zero **ACTIVE** users with `users.manage`; cannot delete a role that is still assigned
- Starter roles are editable like any other role

### Deferred (later phases)

- Project-level roles (different role per project)
- Override-checkout UI; lifecycle / release product surfaces
- Agents / Storage / Audit admin sections

### Agent auth (shipped)

Signed-in pages expose a short-lived **agent Bearer** (`data-agent-token`). The browser passes it to creopdm-agent on materialize/push/add; the agent sends `Authorization: Bearer …` to CreoPDM. The server verifies the token as that user (same caps). Open outside Creo’s embedded browser uses agent cache + **Windows association**.
