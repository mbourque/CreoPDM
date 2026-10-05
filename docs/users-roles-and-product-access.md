# Users, roles, and product access

## Phase 1 (shipped): login and users admin

CreoPDM uses **session cookie** authentication. Passwords are stored as **Argon2id** hashes only — there is no default password in the source tree.

### First-run setup

When the `users` table has **zero** rows, opening the app redirects to **`/setup`**:

1. Enter display name, username (suggestion: `admin`; letters, numbers, or underscore only — no spaces), **email** (`name@example.com`), password, and confirm.
2. CreoPDM creates an **ACTIVE** user on the **Administrator** starter role, signs you in, and sends you to the app.
3. After any user exists, `/setup` is disabled; unauthenticated visitors go to **`/login`**.

### Sign in / out

| Page | Purpose |
| --- | --- |
| `/login` | Username + password. After a **wrong password** for a **known active** username, a **Forgot password?** control appears (submits the current username plus a one-time token; hides if you change the field). Disabled accounts never get the control. |
| `/forgot-password` | **GET is never allowed** (typed URLs redirect to sign-in). The email form is returned only from the login **Forgot password?** POST when the session grant and token match. Submitting any well-formed email shows the same confirmation; a reset mail is sent only when it matches that account. The grant is spent after one try so emails cannot be probed. |
| `/reset-password?token=…&username=…` | Choose a new password; username is shown **disabled** and must match the token. Token alone (no matching username) is rejected. |
| `/logout` | Clears the session cookie |
| `/account/password` | Change password while signed in (required when `must_change_password` is set) |

Disabled accounts cannot sign in. Too many forgot-password attempts for one email in 24 hours **disable** that account (except full Administration accounts) and notify the administrator email. Checkout, check-in, and activity rows store the **login username** as text (same columns as before; no `user_id` FK yet).

### Administration

Users with any CreoPDM Administration capability (`users.manage`, `users.password`, `roles.assign`, `roles.manage`, `products.assign`, `products.manage`, `settings.manage`, `email.manage`) see **Administration** (`/admin`):

- **Users** — list accounts (Products column: **All** or membership count); click a **name** to edit the user, or a **role** name to open that role (`roles.manage`); **Add user** (`users.manage` + `users.password` for the initial password). Username is 2–64 characters (letters, numbers, or underscore only — no spaces or special characters; sign-in is not case-sensitive). Email is required and must be a valid `name@domain.tld`. New users get **no product access**; membership is not edited here.
- **Roles** — list/create/edit/delete roles and their permission checkboxes (`roles.manage`). The role editor groups **CreoPDM Administration** (`users.manage`, `users.password`, `roles.assign`, `roles.manage`, `products.assign`, `products.manage`, `settings.manage`, `email.manage`, and all `utilities.*` keys), **Products** (`products.view`, `products.create`, `products.edit`, `products.delete`), and **Objects**.
- **Membership** — decide who can open which products (`products.assign`): hub with **By product** and **By user** list pages, then edit members / All-products for one row
- **Products** — list every active product on the server; create, edit, and soft-delete (`products.manage`). Not limited by the signed-in user’s product membership list. (Files-page New/Delete still use `products.create` / `products.delete`.)
- **Email** — choose Local Postfix (`127.0.0.1:25`) or Authenticated SMTP; From address, administrator email, Test Email (`email.manage`). When notifications are **enabled**, signed-in users with product access and a valid email can **Watch** a product (bell next to the gear on Files) and receive activity summaries; the bell is hidden when notifications are disabled.
- **Utilities** — per-tool keys: Availability (`utilities.availability`), Email all users (`utilities.email_users`), Compact (`utilities.compact_product`), Rebuild product DB (`utilities.rebuild_product`), Delete products (`utilities.delete_product`), Audit log (`utilities.audit`), Health/Logs (`utilities.health`). Hub opens with any of those; Administrator has all by default.
- **System Settings** — server options hub (Creo open mode, vault, file types, agent, database, …) (`settings.manage`)
- **AI** — disabled placeholder tile on the hub (coming soon); always visible, not linked
- After a successful **Add user** / **Save** / role save / product save / membership save, you return to the list
- New users must change their password on first sign-in

Others do not see Administration; direct URLs return **403**.

**Lockout safety:** at least one **ACTIVE** user must keep **all** CreoPDM Administration permissions on the same account. Saving a role, demoting/disabling a user, or deleting a role is rejected if it would leave nobody with the full set. You also cannot change **name**, **description**, or **CreoPDM Administration** checkboxes on a role **assigned to you**, and you cannot **delete** your own role — ask another administrator.

**Admins edit admins only:** a full administrator (all Administration caps) may edit **other** full administrators. Full administrators may also edit **their own** account from Users admin (the only self-edit exception), but **cannot** change their own role or disable/change their own status — ask another administrator. Full administrators may assign **any** role (including Administrator). Other accounts with `roles.assign` may only assign a role with **fewer** permissions than their own. Other accounts still cannot edit themselves — ask another administrator, or use **Account → password** for your own password.

**Fine-grained Users admin caps** (separate from `users.manage`):

| Permission | Allows |
| --- | --- |
| `roles.assign` | Change another user’s role. Full administrators may pick any role (including Administrator). Everyone else may only pick a role with **fewer** permissions than their own. Without this cap, Role is read-only and new users default to **Engineer** |
| `users.password` | Set initial password on Add user, or reset password on Edit |
| `products.assign` | Open **Administration → Membership** (By product / By user). New users default to **no** product access |

Assignable roles are always a **proper subset** of the signed-in user’s permissions (never peer or higher).

### Product access (Membership)

On **Administration → Membership** (`products.assign`):

| Mode | Behavior |
| --- | --- |
| **By user** | **All products** or a multi-select product list; none selected → empty product list / **403** on product URLs (new users start with none) |
| **By product** | Tick which **restricted** users are members. Users with All products are listed read-only (they already see the product); change All products under By user |
| **Hub summary** | Table of products with **Members** (who can open = restricted + All-products users), **Restricted** counts, and **Manage** links |

Creating a product while signed in as a restricted user automatically grants that user access to the new product.

### Checkout exclusivity

A file may be checked out by **one** user at a time. If Paul has a checkout, David cannot check out the same file until Paul checks in or undoes the checkout. The checkout row stores the login **username**.

Empty databases seed four **starter** roles (**Administrator**, **PDM Manager**, **Engineer**, **Viewer**) once. After that, permissions live only in the database — see Phase 3. Reference matrix: [initial-built-in-roles.md](initial-built-in-roles.md).

## Phase 2 (shipped): core role matrix

Permission keys (`products.*` including **`products.view`**, `objects.*` including **`objects.view`** and **`objects.force_undo_checkout`**, `users.manage`, `users.password`, `roles.assign`, `roles.manage`, `products.assign`, `products.manage`, `settings.manage`, `email.manage`) gate APIs (**403** when missing). Seeing the Files/products page requires **`products.view`** (granted to every role by default). Browse/open/download files requires **`objects.view`**. A role with no permissions cannot use the Files page. After sign-in, accounts **without** `products.view` land on **`/admin`** when they have any Administration capability, otherwise on a plain **`/no-access`** page (not a JSON error). Administration breadcrumbs omit the **Products** link when `products.view` is missing. The Files toolbar and product New/Delete controls hide when the matching capability is false. Viewer Open dialog offers view-only open (no “Check out … then open”) when `objects.checkout` is missing (`data-can-checkout` on the page).

| Starter role (default seed) | Can do | Cannot |
| --- | --- | --- |
| **Viewer** | View products (`products.view`) and browse/open/download / Details/History (`objects.view`; Open goes straight to open — no checkout dialog; Files toolbar **Details** when one file is selected, same as double-click) | Authoring toolbar, Copy to Vault, checkout-on-open, Administration |
| **Engineer** | View + Add, checkout, check-in, remove, revert, metadata | Create/edit/delete products, Copy to Vault, Force Undo Checkout, users, roles, settings |
| **PDM Manager** | Create/edit products (Files/API) + Engineer authoring + **Copy to Vault** + **Force Undo Checkout** | Delete product, Administration → Products (`products.manage`), users, roles, settings, email |
| **Administrator** | Everything above + delete product + full CreoPDM Administration (including Admin → Products and Email) | — |

Automated coverage: `tests/unit/test_auth.py::test_every_starter_role_login_permission_matrix` creates one ephemeral user per starter role, logs each in, and asserts allow/deny for every built-in permission key (plus Files toolbar chrome and **product membership**: All / one product / none). Dedicated UI + lifecycle coverage: `test_admin_membership_product_access_filters_products`.

When `auth_enabled` is false (unit tests with a static identity), all authoring and product caps are granted so the existing suite stays green.

## Phase 3 (shipped): Roles admin (DB is source of truth)

- **`/admin/roles`** — create roles, edit name/description/permissions, delete unused roles
- Runtime caps come only from `role_permissions` (no Administrator-by-name short-circuit; starter templates are not re-applied on restart)
- Safety: cannot leave zero **ACTIVE** users with full CreoPDM Administration (`users.manage` + `users.password` + `roles.assign` + `roles.manage` + `products.assign` + `products.manage` + `settings.manage` + `email.manage` on the same account); cannot delete a role that is still assigned; cannot rename, re-describe, change Administration permissions on, or delete a role assigned to yourself
- Starter roles are editable like any other role

### Deferred (later phases)

- Product-level roles (different role per product)
- Lifecycle / release product surfaces
- Per-user notification subscriptions; Agents / Storage / Audit admin sections

### Agent auth (shipped)

Signed-in pages expose a short-lived **agent Bearer** (`data-agent-token`). The browser passes it to creopdm-agent on materialize/push/add; the agent sends `Authorization: Bearer …` to CreoPDM. The server verifies the token as that user (same caps). Open outside Creo’s embedded browser uses the local workspace + **Windows association**.
