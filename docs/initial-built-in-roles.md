# Initial Built-In Roles

Provide the following built-in roles:

## Administrator

Full system administration access.

Typical permissions:

- Manage users
- Manage roles
- Manage system settings
- Create projects
- Modify projects
- Delete/archive projects
- Manage project membership
- Manage repositories/remotes
- Manage Windows agents
- Override stale checkouts
- Manage lifecycle states
- View audit logs
- Perform normal engineering operations
- Copy to Vault

Administrators should have access to the complete **Administration** section.

---

## PDM Manager

Responsible for managing engineering data without having full server administration privileges.

Typical permissions:

- Create projects
- Modify project settings
- Manage project membership
- Add objects
- Check out objects
- Check in objects
- Revise objects
- Change lifecycle state
- Release objects
- Manage stale checkouts
- View BOMs
- View Where Used
- View history
- View audit information related to projects
- Manage project-level configuration
- Copy to Vault (`objects.copy_to_vault`)

Should NOT normally be able to:

- Manage global users
- Manage global roles
- Modify server configuration
- Delete audit history
- Manage authentication configuration

---

## Engineer

Normal CAD/PDM user.

Typical permissions:

- View assigned projects
- Download files
- Open files locally
- Open CAD files in Creo
- Create objects
- Upload files
- Check out objects
- Check in objects
- Undo own checkout
- Get Latest
- View history
- View BOM
- View Where Used
- View parameters
- View assembly structure
- Request/update Creo metadata
- Restore an older version as a new working version

Should NOT normally be able to:

- Manage users
- Manage roles
- Delete projects
- Override another user's checkout
- Change global settings
- Delete history
- Copy to Vault
- Release engineering data unless explicitly granted

---

## Viewer

Read-only access.

Typical permissions:

- View assigned projects
- View objects
- View metadata
- View BOM
- View Where Used
- View assembly structure
- View parameters
- View history
- Download permitted files
- **`objects.view`** (browse / open / download)

Cannot:

- Upload
- Check out
- Check in
- Modify objects
- Delete objects
- Change lifecycle state
- Manage projects
- Manage users
- Copy to Vault

Viewer should be appropriate for users who need access to engineering information but do not author it.

Examples may include manufacturing, purchasing, quality, management, or other downstream users.

---

# Optional Contributor Role

Consider adding a built-in **Contributor** role.

This would sit between Viewer and Engineer.

Typical use case:

A user needs to add or update supporting documents but does not need CAD authoring permissions.

Permissions might include:

- View projects
- View BOM
- View Where Used
- Download files
- Upload non-CAD files
- Check out/check in permitted documents
- Add attachments

But not:

- Modify Creo CAD
- Update CAD structure
- Release CAD
- Override checkouts

This role can be deferred if it is not needed for the initial release


# Recommended Initial Permission Matrix

| Permission | Administrator | PDM Manager | Engineer | Viewer |

|---|:---:|:---:|:---:|:---:|

| View project | ✓ | ✓ | ✓ | ✓ |

| Create project | ✓ | ✓ |  |  |

| Edit project | ✓ | ✓ |  |  |

| Archive project | ✓ | ✓ |  |  |

| Delete project | ✓ |  |  |  |

| Add object | ✓ | ✓ | ✓ |  |

| Download object | ✓ | ✓ | ✓ | ✓ |

| Check out | ✓ | ✓ | ✓ |  |

| Check in | ✓ | ✓ | ✓ |  |

| Undo own checkout | ✓ | ✓ | ✓ |  |

| Override checkout | ✓ | ✓ |  |  |

| View history | ✓ | ✓ | ✓ | ✓ |

| Restore version | ✓ | ✓ | ✓ |  |

| View BOM | ✓ | ✓ | ✓ | ✓ |

| Export BOM | ✓ | ✓ | ✓ | ✓ |

| View Where Used | ✓ | ✓ | ✓ | ✓ |

| View parameters | ✓ | ✓ | ✓ | ✓ |

| Update CAD metadata | ✓ | ✓ | ✓ |  |

| Change lifecycle | ✓ | ✓ |  |  |

| Release object | ✓ | ✓ |  |  |

| Manage project members | ✓ | ✓ |  |  |

| View users | ✓ | ✓ |  |  |

| Manage users | ✓ |  |  |  |

| Manage roles | ✓ |  |  |  |

| Manage agents | ✓ | ✓ |  |  |

| View audit log | ✓ | ✓ |  |  |

| Change global settings | ✓ |  |  |  |

This matrix should be treated as the initial default configuration.

Permissions should remain independently configurable internally.

---

# Project Membership

A user's global role should not automatically give access to every project.

Separate:

```text

User

  ↓

Global Role

```

from:

```text

User

  ↓

Project Membership

  ↓

Project Access

```

Example:

```text

Bob

Role: Engineer

Projects:

    Robot Arm       Member

    Gearbox         Member

    Secret Project  No Access

```

Being an Engineer determines **what Bob can do**.

Project membership determines **where Bob can do it**.

Administrators may optionally have global project access.

---

# Future Project-Level Roles

The initial implementation can use global roles plus project membership.

However, the database design should allow future project-specific role assignment.

Example:

```text

Alice

Robot Arm:

    PDM Manager

Gearbox:

    Engineer

Prototype X:

    Viewer

```

Do not assume that one user must always have the same privileges in every project.

---

# Administration UI

Add an **Administration** section visible only to authorized users.

Suggested navigation:

```text

Administration

│

├── Users

├── Roles

├── Projects

├── Agents

├── Storage

├── Git / Remotes

├── Creo

├── System

└── Audit Log

```

Not all sections need to be implemented immediately.

---

# Users Page

Example:

```text

Administration > Users

Search [________________________]

Name          Username      Role          Status

---------------------------------------------------

Bob Smith     bsmith        Engineer      Active

Alice Jones   ajones        PDM Manager   Active

John Doe      jdoe          Viewer        Active

Admin         admin         Administrator Active

[Add User]

```

Selecting a user should show:

```text

User Details

Name:

Bob Smith

Username:

bsmith

Email:

bob@example.com

Role:

Engineer

Status:

Active

Projects:

✓ Robot Arm

✓ Gearbox

□ Prototype X

Windows Agents:

ENG-PC-17       Online

[Save]

[Disable User]

```

Prefer disabling users rather than deleting them.

Historical records must continue to reference the original user.

---

# User Status

Support:

```text

ACTIVE

DISABLED

```

Future states may include:

```text

PENDING

LOCKED

```

A disabled user:

- cannot authenticate;

- cannot acquire new checkouts;

- cannot perform PDM operations;

- remains visible in historical/audit information.

Do not delete historical ownership information when a user is disabled.

---

# Roles Page

Example:

```text

Administration > Roles

Administrator

PDM Manager

Engineer

Viewer

```

Selecting a role displays its permissions.

Example:

```text

Engineer

Projects

[x] View projects

[ ] Create projects

[ ] Delete projects

Objects

[x] View objects

[x] Add objects

[x] Download objects

PDM

[x] Check Out

[x] Check In

[x] Undo Own Checkout

[ ] Override Checkout

Engineering Data

[x] View BOM

[x] View Where Used

[x] View Parameters

[x] Update CAD Metadata

Administration

[ ] Manage Users

[ ] Manage Roles

[ ] Change System Settings

```

For the initial release, built-in role permissions may be fixed.

**Update:** Administrators manage roles and permissions in **Administration → Roles**. Starter roles are seeded once for empty databases; `role_permissions` in the database is the source of truth afterward.

Later versions can allow administrators to create custom roles.

---

# Protect Built-In Administrator Role

The built-in Administrator role must not be accidentally removed.

The system should prevent:

- deleting the Administrator role when it is the last full-admin path;

- removing any of `users.manage`, `roles.manage`, or `settings.manage` when that would leave no ACTIVE user with **all three**;

- disabling or demoting the last active account that has full CreoPDM Administration.

There must always be at least one active user who can manage Users, Roles, and Settings.

Only a full administrator (all three of those permissions) may edit another full administrator or assign a full-administrator role. An account with `users.manage` alone can manage non-admin users but cannot change administrator accounts. No user may edit their own record from Users admin — another administrator must change them.

---

# Administrator Settings

Create a central settings area.

Suggested sections:

## General

```text

System Name

Company Name

Server URL

Default Project Location

Timezone

```

---

## PDM

```text

Default revision scheme

Default lifecycle state

Require check-in comments

Allow checkout of released objects

Stale checkout threshold

```

Recommended defaults:

```text

Require check-in comments: YES

Allow checkout of released objects: NO

```

---

## Creo

```text

Supported Creo versions

Creo file extensions

Workspace settings

Creo numbered-file handling

Parameter mappings

Tracked parameters

Dependency extraction settings

```

Example tracked parameters:

```text

PART_NUMBER

DESCRIPTION

MATERIAL

REVISION

DRAWN_BY

```

Do not hard-code these as universally required parameters.

---

## Windows Agent

Settings may include:

```text

Minimum supported agent version

Heartbeat timeout

Default workspace location

Allow Open in Creo

Allow automatic downloads

Workspace cleanup policy

```

Some settings may be server defaults that can be overridden locally where appropriate.

---

## Git / Storage

Settings may include:

```text

Repository storage location

Git executable/configuration

Git LFS configuration

Remote synchronization

GitHub integration

Maximum upload size

```

Credentials/secrets must not be displayed after they have been stored.

---

# Database Model

Suggested tables:

```text

users

roles

permissions

role_permissions

user_roles

project_members

```

Possible future table:

```text

project_member_roles

```

---

## users

Suggested fields:

```text

id

uuid

username

display_name

email

status

created_at

updated_at

last_login_at

```

Do not use username as the primary identity.

Use UUID.

---

## roles

```text

id

uuid

name

description

is_builtin

created_at

updated_at

```

---

## permissions

```text

id

key

description

```

Example:

```text

key = "checkout.override"

description = "Override or cancel another user's checkout"

```

Permission keys should be unique and stable.

---

## role_permissions

```text

role_id

permission_id

```

---

## user_roles

```text

user_id

role_id

```

Even if the initial UI allows only one role per user, using a join table avoids unnecessarily restricting the database design.

---

## project_members

```text

project_id

user_id

created_at

created_by

```

This determines which projects the user can access.

---

# Authorization Flow

Every protected server operation should perform authorization on the server.

Example:

```text

POST /api/v1/objects/{uuid}/checkout

        ↓

Authenticate user

        ↓

Is account active?

        ↓

Does user have access to project?

        ↓

Does user have checkout.create?

        ↓

Is object eligible for checkout?

        ↓

Acquire lock

```

The web UI and Windows Agent should **not** be trusted to enforce authorization.

They may hide unavailable controls for usability, but the Linux API must perform the actual permission check.

---

# Windows Agent Authorization

The Windows Agent acts on behalf of an authenticated user.

The agent should not gain additional privileges simply because it is an installed workstation application.

Example:

```text

Windows Agent

    ↓

Authenticated as Bob

    ↓

Bob is Engineer

    ↓

Bob requests checkout

    ↓

Server evaluates Bob's permissions

```

The agent itself does not bypass PDM permissions.

---

# Audit Requirements

Administrative actions should be logged.

Examples:

```text

USER_CREATED

USER_DISABLED

USER_ENABLED

ROLE_ASSIGNED

ROLE_REMOVED

PROJECT_MEMBER_ADDED

PROJECT_MEMBER_REMOVED

CHECKOUT_OVERRIDDEN

LIFECYCLE_CHANGED

SYSTEM_SETTING_CHANGED

```

Where practical, record:

```text

timestamp

acting_user

action

target

previous_value

new_value

machine/agent

```

Audit records should not be editable by normal users.

---

# API Requirements

Potential endpoints:

```text

GET    /api/v1/users

POST   /api/v1/users

GET    /api/v1/users/{uuid}

PATCH  /api/v1/users/{uuid}

GET    /api/v1/roles

POST   /api/v1/roles

GET    /api/v1/roles/{uuid}

PATCH  /api/v1/roles/{uuid}

GET    /api/v1/permissions

GET    /api/v1/projects/{uuid}/members

POST   /api/v1/projects/{uuid}/members

DELETE /api/v1/projects/{uuid}/members/{user_uuid}

GET    /api/v1/admin/settings

PATCH  /api/v1/admin/settings

```

Every endpoint must perform server-side authorization.

---

# Initial Implementation Scope

For the first version implement:

- [ ] Administrator role

- [ ] PDM Manager role

- [ ] Engineer role

- [ ] Viewer role

- [ ] Permission model

- [ ] User management

- [ ] Enable/disable users

- [ ] Role assignment

- [ ] Project membership

- [ ] Administration navigation

- [ ] Users page

- [x] Basic Roles page

- [ ] General settings page

- [x] Server-side authorization

- [ ] Audit administrative actions

- [x] Prevent disabling the last Administrator

Do not initially implement:

- [x] Complex custom-role editor (Roles admin with permission checkboxes; free-form keys still out of scope)

- [ ] Project-specific role overrides

- [ ] Active Directory/LDAP

- [ ] SSO

- [ ] Approval groups

- [ ] Department hierarchy

- [ ] Fine-grained per-object ACLs

These can be added later.

---

# Key Design Principle

Keep these concepts separate:

```text

Authentication

    WHO are you?

Role / Permission

    WHAT are you allowed to do?

Project Membership

    WHERE are you allowed to do it?

Lifecycle

    WHAT operations are currently valid

    for this engineering object?

```

For example:

```text

Bob

    ↓

authenticated

    ↓

Engineer

    ↓

has checkout.create

    ↓

member of Robot Arm project

    ↓

SHAFT.PRT is IN_WORK

    ↓

Checkout permitted

```

This separation should be maintained throughout the server architecture.

The **Linux CreoPDM server is authoritative for all authorization decisions**.