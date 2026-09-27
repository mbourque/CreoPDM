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

### Administration → Users

Administrators (permission `users.manage`) see an **Administration** link in the top bar:

- List users (name, username, role, status)
- Add / edit user (display name, username, email, role, status, set/reset password)
- After a successful **Add user**, you return to the users list
- New users must change their password on first sign-in

### Settings (administrators only)

Only users with `settings.manage` (built-in **Administrator**) see the **Settings** link and can open `/settings` or call `/api/settings`. Engineers and other roles get **403**.

### Checkout exclusivity

A file may be checked out by **one** user at a time. If Paul has a checkout, David cannot check out the same file until Paul checks in or undoes the checkout. The checkout row stores the login **username**.

Built-in roles are seeded: **Administrator**, **PDM Manager**, **Engineer**, **Viewer**. Role capability details remain in [initial-built-in-roles.md](initial-built-in-roles.md).

### Deferred (later phases)

- Full permission matrix on every API
- Project membership / project-level roles
- Roles admin UI; Agents / Storage / Audit admin sections
- Binding Windows agent Bearer tokens to the session user
