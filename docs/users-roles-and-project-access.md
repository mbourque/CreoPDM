# Users, roles, and project access

## Phase 1 (shipped): login and users admin

CreoPDM uses **session cookie** authentication. Passwords are stored as **Argon2id** hashes only — there is no default password in the source tree.

### First-run setup

When the `users` table has **zero** rows, opening the app redirects to **`/setup`**:

1. Enter display name, username (suggestion: `admin`), password, and confirm.
2. CreoPDM creates an **ACTIVE** Administrator, signs you in, and sends you to the app.
3. After any user exists, `/setup` is disabled; unauthenticated visitors go to **`/login`**.

### Sign in / out

| Page | Purpose |
| --- | --- |
| `/login` | Username + password |
| `/logout` | Clears the session cookie |
| `/account/password` | Change password (required when `must_change_password` is set) |

Disabled accounts cannot sign in. Checkout, check-in, and activity rows store the **login username** as text (same columns as before; no `user_id` FK yet).

### Administration

Administrators see an **Administration** link in the top bar (hub at `/admin`):

- **Users** — list accounts; click a **name** to edit (display name, email, role, status, set/reset password); **Add user**
- **Settings** — workstation options (Creo open mode, vault, file types, …). Only `settings.manage` (built-in Administrator)
- After a successful **Add user** or **Save** on edit, you return to the users list
- New users must change their password on first sign-in
- More admin sections will be added to this hub later

Engineers and other roles do not see Administration; direct URLs return **403**.

### Checkout exclusivity

A file may be checked out by **one** user at a time. If Paul has a checkout, David cannot check out the same file until Paul checks in or undoes the checkout. The checkout row stores the login **username**.

Built-in roles are seeded: **Administrator**, **PDM Manager**, **Engineer**, **Viewer**. Full capability matrix: [initial-built-in-roles.md](initial-built-in-roles.md).

## Phase 2 (shipped): core role matrix

Permission keys are seeded on roles (`projects.*`, `objects.*`, `users.manage`, `settings.manage`). Mutating APIs return **403** when the signed-in user lacks the key. The Files toolbar and project New/Delete controls hide when the matching capability is false.

| Role | Can do now | Cannot |
| --- | --- | --- |
| **Viewer** | Browse projects, open/download, Details | Add / Checkout / Check In / Remove, New project, Administration |
| **Engineer** | Add, checkout, check-in, remove, revert, metadata | Create/edit/delete projects, users, settings |
| **PDM Manager** | Create/edit projects + Engineer authoring | Delete project, users, settings |
| **Administrator** | Everything above + delete project + users + settings | — |

When `auth_enabled` is false (unit tests with a static identity), all authoring and project caps are granted so the existing suite stays green.

### Deferred (later phases)

- Project membership / “assigned projects only” / project-level roles
- Override-checkout UI; lifecycle / release product surfaces
- Roles admin UI; Agents / Storage / Audit admin sections
- Binding Windows agent Bearer tokens to the session user
