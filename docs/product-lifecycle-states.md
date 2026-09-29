````markdown
# Enhancement: Project States and Project Access Modes

## Summary

CreoPDM should support basic **Project States** that control what users are allowed to do within a project.

Currently, projects effectively have one state:

```text
IN_WORK
```

Project states should provide a simple way to control whether a project is:

- Actively being worked on
- Temporarily on hold
- Released
- Closed
- Archived

Project state should not be only a visual label.

It should enforce functionality at the **server/API level**.

The initial recommended project states are:

```text
IN_WORK
ON_HOLD
RELEASED
CLOSED
ARCHIVED
```

In addition, projects should have an independent:

```text
READ_ONLY
```

access mode/flag.

This allows a project to be temporarily made read-only without changing its actual lifecycle state.

---

# 1. Project States

Recommended initial states:

| State | Purpose |
|---|---|
| `IN_WORK` | Active engineering project |
| `ON_HOLD` | Engineering work temporarily suspended |
| `RELEASED` | Project/design has been formally released |
| `CLOSED` | Project activity has ended |
| `ARCHIVED` | Project retained for history but removed from normal workflows |

Additionally:

```text
read_only = true / false
```

should control whether modifications are temporarily permitted.

---

# 2. IN_WORK

`IN_WORK` is the normal active engineering state.

This should be the default state for newly created projects.

```text
IN_WORK
```

means:

> The project is active and engineering work is permitted.

## Allow

```text
✓ View project
✓ Search
✓ Download
✓ Add to Workspace
✓ Open in Creo
✓ Add objects
✓ Import objects
✓ Check Out
✓ Check In
✓ Revise
✓ Rename
✓ Create folders
✓ Modify metadata
✓ Modify CAD structures
✓ Create baselines
✓ Create Engineering Changes
✓ Perform Copy Design
✓ Perform Save As
✓ Archive objects according to permissions
✓ Delete according to permissions and integrity rules
```

Normal user permissions and object lifecycle rules still apply.

For example:

```text
Project = IN_WORK
```

does not automatically mean every user can Check Out every object.

The user must still have the appropriate permission.

---

# 3. ON_HOLD

`ON_HOLD` means:

> Engineering activity on the project has been intentionally suspended, but the project is not finished.

Example:

```text
Project:
Gearbox Redesign

State:
ON_HOLD
```

This could be used when:

- Project funding is paused
- Engineering work is temporarily stopped
- Waiting for customer approval
- Waiting for management decision
- Project priority has changed
- Engineering should not continue until some external event occurs

## Allow

```text
✓ View
✓ Search
✓ Download
✓ Add to Workspace
✓ Open in Creo
✓ View BOM
✓ Where Used
✓ View history
✓ View baselines
✓ View releases
✓ View Engineering Changes
```

## Block

```text
✗ Add objects
✗ Import objects
✗ Check Out
✗ Check In
✗ Revise
✗ Rename
✗ Delete
✗ Archive objects
✗ Modify metadata
✗ Modify structure
✗ Copy Design into the project
✗ Save As into the project
```

A normal transition would be:

```text
IN_WORK
   ↓
ON_HOLD
   ↓
IN_WORK
```

`ON_HOLD` should be reversible.

---

# 4. RELEASED

`RELEASED` means:

> The project represents a completed/released engineering configuration and normal engineering modification has ended.

This should be treated as a significant project state.

## Allow

```text
✓ View
✓ Search
✓ Download
✓ Add to Workspace
✓ Open in Creo
✓ View BOM
✓ Where Used
✓ View history
✓ View baselines
✓ View release records
✓ View Engineering Changes
✓ Retrieve historical versions
```

## Block

```text
✗ Add new objects
✗ Import new objects
✗ Check Out
✗ Check In
✗ Revise
✗ Rename
✗ Delete
✗ Modify metadata
✗ Modify project structure
✗ Copy Design into project
✗ Save As into project
```

---

# 5. Project RELEASED vs Object RELEASED

Project lifecycle and object lifecycle must remain separate concepts.

Do not assume:

```text
Project = RELEASED

therefore

Every Object = RELEASED
```

Instead:

```text
Project State
    ≠
Object Lifecycle State
```

An object might have its own lifecycle:

```text
IN_WORK
IN_REVIEW
RELEASED
OBSOLETE
```

while the containing project has:

```text
IN_WORK
ON_HOLD
RELEASED
CLOSED
ARCHIVED
```

These should be evaluated independently.

---

# 6. Reusing Objects From Released Projects

A released project should prevent users from adding or modifying objects **inside that project**.

However, do not automatically prevent another active project from referencing a released object.

For example:

```text
Project A
State: RELEASED

BEARING.PRT
State: RELEASED
```

Another project:

```text
Project B
State: IN_WORK
```

may legitimately reuse:

```text
BEARING.PRT
```

if the user's permissions and object lifecycle rules permit it.

Therefore:

```text
Project RELEASED
```

should mean:

```text
Cannot modify Project A
```

not necessarily:

```text
Nothing in Project A can ever be referenced elsewhere.
```

Reuse policy should be controlled separately.

---

# 7. CLOSED

`CLOSED` means:

> Work on this project has ended, but the project should remain normally accessible for historical/reference purposes.

## Allow

```text
✓ View
✓ Search
✓ Download
✓ Add to Workspace
✓ Open in Creo
✓ View BOM
✓ Where Used
✓ View history
✓ View baselines
✓ View releases
✓ View Engineering Changes
✓ Retrieve historical versions
```

## Block

```text
✗ Add objects
✗ Import
✗ Check Out
✗ Check In
✗ Revise
✗ Rename
✗ Delete
✗ Modify metadata
✗ Modify structure
✗ Copy Design into project
✗ Save As into project
```

---

# 8. RELEASED vs CLOSED

The distinction is primarily semantic.

```text
RELEASED
```

means:

> The engineering configuration has been formally released.

```text
CLOSED
```

means:

> Project activity has ended.

This distinction is useful because not every closed project necessarily resulted in a released product.

For example:

```text
Prototype Project
      ↓
IN_WORK
      ↓
Project Cancelled
      ↓
CLOSED
```

The project never reached:

```text
RELEASED
```

but should still remain in CreoPDM for historical purposes.

---

# 9. ARCHIVED

`ARCHIVED` means:

> The project is retained for historical and data-integrity purposes but removed from normal day-to-day engineering workflows.

Archive must NOT mean:

```text
Delete project
```

and should NOT physically destroy or move engineering history unless a separate storage architecture explicitly requires that behavior.

Conceptually:

```text
project.state = ARCHIVED
```

is primarily a lifecycle/query/access change.

---

# 10. Archived Project Visibility

Archived projects should normally be hidden from:

```text
Default project list
Normal project picker
Normal search results
Create dialogs
Add-object dialogs
Normal engineering workflows
```

Search could provide:

```text
☐ Include Archived Projects
```

An administrator could also have:

```text
Archived Projects
```

as a separate view.

---

# 11. Archived Project Access

## Allow

Depending on permissions:

```text
✓ Administrator access
✓ Explicit historical access
✓ View project
✓ View objects
✓ View history
✓ View BOM
✓ Where Used
✓ View audit
✓ View baselines
✓ View releases
✓ View Engineering Changes
✓ Integrity verification
✓ Restore / Unarchive
```

## Block

```text
✗ Add objects
✗ Import
✗ Check Out
✗ Check In
✗ Revise
✗ Rename
✗ Delete
✗ Modify metadata
✗ Modify structure
✗ Copy Design into project
✗ Save As into project
```

---

# 12. Archive Must Preserve Engineering History

Changing:

```text
CLOSED
    ↓
ARCHIVED
```

must not remove:

```text
Object UUIDs
Version UUIDs
Versions
Iterations
Revisions
CAD files
Metadata snapshots
Dependency snapshots
BOM information
Where Used information
Baselines
Releases
Engineering Changes
Audit history
User attribution
```

Historical references to archived projects and objects must continue working.

---

# 13. Restore Archived Project

Administrators should have:

```text
Restore Project
```

or:

```text
Unarchive Project
```

Restoring should NOT create a new project.

The existing:

```text
Project UUID
```

must remain unchanged.

For example:

```text
ARCHIVED
    ↓
Restore
    ↓
CLOSED
```

Alternatively, the administrator could be asked which permitted state to restore to.

Example:

```text
Restore Project

Restore To:

○ CLOSED
○ IN_WORK

Reason:
_________________________

[ Restore ]
```

The state transition should be audited.

---

# 14. READ_ONLY Should Be Separate

Instead of making:

```text
READ_ONLY
```

a project lifecycle state, implement it as an independent project access mode.

For example:

```text
Project State:
IN_WORK

Read Only:
TRUE
```

This means:

> The project is still an active project, but modifications have temporarily been disabled.

This is useful for:

- Maintenance
- Migration
- Administrative freeze
- Review
- Investigation
- Temporary engineering freeze
- Data-integrity operations

---

# 15. Read-Only Project

When:

```text
read_only = true
```

allow:

```text
✓ View
✓ Search
✓ Download
✓ Add to Workspace
✓ Open in Creo
✓ View BOM
✓ Where Used
✓ View history
✓ View baselines
✓ View releases
✓ View Engineering Changes
```

Block:

```text
✗ Add objects
✗ Import
✗ Check Out
✗ Check In
✗ Revise
✗ Rename
✗ Delete
✗ Archive objects
✗ Modify metadata
✗ Modify structure
✗ Copy Design into project
✗ Save As into project
```

---

# 16. Why READ_ONLY Should Be Independent

Consider:

```text
Project State:
IN_WORK

Read Only:
TRUE
```

This means:

> The project is still active but has been temporarily frozen.

Later:

```text
Read Only:
FALSE
```

and the project remains:

```text
IN_WORK
```

No artificial lifecycle transition was required.

Likewise:

```text
Project State:
RELEASED

Read Only:
TRUE
```

is valid.

Therefore the basic data model could be:

```text
Project

state:
    IN_WORK
    ON_HOLD
    RELEASED
    CLOSED
    ARCHIVED

read_only:
    true / false
```

---

# 17. Project State Capability Matrix

Initial behavior could be:

| Operation | IN_WORK | ON_HOLD | RELEASED | CLOSED | ARCHIVED |
|---|---:|---:|---:|---:|---:|
| View | ✓ | ✓ | ✓ | ✓ | Restricted |
| Search | ✓ | ✓ | ✓ | ✓ | Optional |
| Download | ✓ | ✓ | ✓ | ✓ | Permission |
| Add to Workspace | ✓ | ✓ | ✓ | ✓ | Permission |
| Open in Creo | ✓ | ✓ | ✓ | ✓ | Permission |
| BOM | ✓ | ✓ | ✓ | ✓ | ✓ |
| Where Used | ✓ | ✓ | ✓ | ✓ | ✓ |
| History | ✓ | ✓ | ✓ | ✓ | ✓ |
| Add Object | ✓ | ✗ | ✗ | ✗ | ✗ |
| Import | ✓ | ✗ | ✗ | ✗ | ✗ |
| Check Out | ✓ | ✗ | ✗ | ✗ | ✗ |
| Check In | ✓ | ✗ | ✗ | ✗ | ✗ |
| Revise | ✓ | ✗ | ✗ | ✗ | ✗ |
| Modify Metadata | ✓ | ✗ | ✗ | ✗ | ✗ |
| Rename | ✓ | ✗ | ✗ | ✗ | ✗ |
| Modify Structure | ✓ | ✗ | ✗ | ✗ | ✗ |
| Copy Design Into | ✓ | ✗ | ✗ | ✗ | ✗ |
| Save As Into | ✓ | ✗ | ✗ | ✗ | ✗ |

Normal role and object permissions still apply.

---

# 18. READ_ONLY Override

The project state should establish the normal capability set.

Then:

```text
read_only = true
```

removes modification capabilities.

For example:

```text
Project State:
IN_WORK

Read Only:
FALSE
```

allows:

```text
CHECKOUT
CHECKIN
ADD
REVISE
MODIFY
```

but:

```text
Project State:
IN_WORK

Read Only:
TRUE
```

removes those capabilities.

Conceptually:

```text
Project State Capabilities
        +
User Permissions
        +
Read-Only Restriction
        +
Object Lifecycle
        +
Object State
        =
Effective Capabilities
```

---

# 19. Do Not Hard-Code This Only in the UI

Avoid implementing project states only like:

```python
if project.state == "RELEASED":
    disable_checkout_button()
```

The UI should disable inappropriate controls, but the backend must enforce the rules.

Otherwise a user could bypass the UI and call:

```text
POST /api/checkouts
```

directly.

---

# 20. Server-Side Capability Evaluation

CreoPDM should eventually centralize authorization/capability evaluation.

Conceptually:

```text
function canCheckout(user, object):

    project = object.project

    if project.state != IN_WORK:
        return false

    if project.read_only == true:
        return false

    if not user.hasPermission("CHECKOUT", project):
        return false

    if object.lifecycleState prohibits checkout:
        return false

    if object is already checked out:
        return false

    return true
```

This should be server-side authoritative logic.

---

# 21. Effective Permissions

Eventually an operation should depend on:

```text
USER ROLE
      +
PROJECT PERMISSIONS
      +
PROJECT STATE
      +
PROJECT READ-ONLY FLAG
      +
OBJECT LIFECYCLE STATE
      +
OBJECT CHECKOUT STATE
      +
OTHER INTEGRITY RULES
      =
ALLOWED ACTION
```

Example:

```text
User:
ENGINEER

Permission:
CHECKOUT = TRUE

Project:
IN_WORK

Read Only:
FALSE

Object:
IN_WORK

Checkout:
AVAILABLE
```

Result:

```text
CAN CHECK OUT
```

But:

```text
User:
ENGINEER

Permission:
CHECKOUT = TRUE

Project:
RELEASED
```

Result:

```text
CANNOT CHECK OUT
```

Project state restricts the operation even though the user normally has permission.

---

# 22. API Enforcement

If a user attempts an invalid operation directly:

```text
POST /api/checkouts
```

against a project in:

```text
RELEASED
```

the server should reject it.

Example response:

```text
PROJECT_NOT_MODIFIABLE

Project:
PDM-001

Project State:
RELEASED

Operation:
CHECKOUT

Checkout is not permitted while the project is RELEASED.
```

The same protection should exist for:

```text
Check-In
Revise
Add Object
Import
Rename
Delete
Metadata Update
Copy Design
Save As
```

---

# 23. UI Behavior

The web UI should obtain effective capabilities from the server.

Example project response:

```json
{
    "id": "PROJECT-123",
    "name": "Gearbox Redesign",
    "state": "RELEASED",
    "read_only": false,
    "capabilities": {
        "view": true,
        "download": true,
        "add_object": false,
        "checkout": false,
        "checkin": false,
        "revise": false,
        "modify_metadata": false,
        "archive": true
    }
}
```

The UI can then:

```text
Enable
Disable
Hide
```

controls based on the returned capabilities.

The backend remains authoritative.

---

# 24. State Transitions

A basic lifecycle could be:

```text
                    ┌───────────┐
                    │  ON_HOLD  │
                    └─────┬─────┘
                          │
                          ↕
                    ┌─────┴─────┐
                    │  IN_WORK  │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │ RELEASED  │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │  CLOSED   │
                    └─────┬─────┘
                          │
                          ▼
                    ┌───────────┐
                    │ ARCHIVED  │
                    └───────────┘
```

However, CreoPDM should also support practical paths such as:

```text
IN_WORK
   ↓
CLOSED
```

for a cancelled project.

---

# 25. Suggested Initial Transition Rules

```text
IN_WORK
    → ON_HOLD
    → RELEASED
    → CLOSED
    → ARCHIVED
```

Also allow:

```text
ON_HOLD
    → IN_WORK
```

```text
IN_WORK
    → CLOSED
```

```text
CLOSED
    → ARCHIVED
```

```text
ARCHIVED
    → CLOSED
```

Reopening a released or closed project should require elevated permission and an audit reason.

Do not automatically assume:

```text
RELEASED → IN_WORK
```

is a normal operation.

If released engineering work needs modification, object revision/change-control rules may be more appropriate.

---

# 26. State Change Dialog

Example:

```text
Change Project State

Project:
Gearbox Redesign

Current State:
IN_WORK

New State:
RELEASED

Reason:
Production design completed and approved.

[ Cancel ] [ Change State ]
```

For important transitions, `Reason` should be required.

---

# 27. Audit Project State Changes

Every state change should create an audit event.

Example:

```text
Event:
PROJECT_STATE_CHANGED

Project UUID:
PROJECT-123

Old State:
IN_WORK

New State:
RELEASED

Changed By:
USER-456

Timestamp:
2026-09-29 14:30

Reason:
Production design completed and approved.
```

Changing:

```text
read_only
```

should also be audited.

Example:

```text
Event:
PROJECT_READ_ONLY_CHANGED

Old:
FALSE

New:
TRUE

Changed By:
ADMIN-001

Reason:
Temporary engineering freeze.
```

---

# 28. Existing Checkouts During State Change

This needs explicit handling.

Suppose:

```text
Project:
IN_WORK

SHAFT.PRT:
Checked Out by Bob
```

Administrator attempts:

```text
IN_WORK → RELEASED
```

CreoPDM should NOT silently strand the checkout.

Before entering a non-modifiable state, validate:

```text
Active Checkouts
Pending Check-Ins
Running Copy Design operations
Running Save As operations
Incomplete uploads
Other active write operations
```

If any exist, block the transition or require them to be resolved according to an explicit administrative workflow.

Example:

```text
Cannot Release Project

The project currently contains:

3 active checkouts
1 pending upload

Resolve active engineering operations before releasing the project.
```

This is safer than automatically cancelling or undoing user work.

---

# 29. State Transition Transaction

Changing project state should itself be transactional.

Conceptually:

```text
BEGIN

Lock Project

Verify Current State

Verify User Permission

Verify Requested Transition Is Allowed

Verify No Blocking Operations Exist

Update Project State

Create Audit Event

COMMIT
```

If anything fails:

```text
ROLLBACK
```

The project remains in its previous state.

---

# 30. Project State vs Administrative Lock

Do not add:

```text
LOCKED
```

as another lifecycle state unless there is a specific need.

An administrative lock is better modeled separately.

For example:

```text
Project State:
IN_WORK

Read Only:
TRUE
```

rather than:

```text
Project State:
LOCKED
```

This preserves the actual lifecycle meaning:

```text
The project is IN_WORK
```

while independently saying:

```text
Modifications are currently prohibited.
```

---

# 31. Recommended Database Model

Initial implementation could be as simple as:

```text
projects
------------------------------------------------

id
name
description

state

read_only

created_at
created_by

updated_at
updated_by
```

Where:

```text
state ENUM:

IN_WORK
ON_HOLD
RELEASED
CLOSED
ARCHIVED
```

and:

```text
read_only BOOLEAN
```

---

# 32. Optional State Metadata

Later, CreoPDM could also store:

```text
state_changed_at
state_changed_by
```

However, the complete historical record should live in the audit system rather than only storing the latest state transition.

---

# 33. Recommended Initial Admin UI

Under:

```text
Project
    ↓
Settings
```

provide:

```text
Project State

[ IN_WORK ▼ ]
```

Options:

```text
IN_WORK
ON_HOLD
RELEASED
CLOSED
ARCHIVED
```

Separately:

```text
Access

☐ Read Only
```

Show a warning/confirmation when changing to restrictive states.

---

# 34. Project Header

Display the current state clearly.

Example:

```text
Gearbox Redesign

[ RELEASED ]
```

or:

```text
Gearbox Redesign

[ IN WORK ] [ READ ONLY ]
```

This lets the user immediately understand why certain operations are unavailable.

---

# 35. Disabled Operation Explanation

Do not simply gray out buttons without explanation.

For example:

```text
Check Out
```

disabled with tooltip:

```text
Checkout is unavailable because this project is RELEASED.
```

or:

```text
Checkout is unavailable because this project is currently Read Only.
```

This will reduce user confusion.

---

# 36. Project List Filtering

Project list should support filtering:

```text
State:

☑ In Work
☑ On Hold
☑ Released
☑ Closed
☐ Archived
```

By default:

```text
ARCHIVED
```

should probably not be shown.

---

# 37. Search Behavior

Normal global search should search:

```text
IN_WORK
ON_HOLD
RELEASED
CLOSED
```

projects the user has permission to access.

Archived projects should normally be excluded.

Provide:

```text
☐ Include Archived
```

for users with appropriate access.

---

# 38. Windows Agent Behavior

The Windows Agent should also respect effective project capabilities returned by the server.

For example:

```text
Project:
RELEASED
```

When downloaded to a workspace:

```text
Files:
Read Only
```

The Agent should not permit a normal Check-In workflow.

However, server-side enforcement remains authoritative.

The Agent must not be the only protection.

---

# 39. Existing Workspace When Project Becomes Read Only

Suppose an engineer already has:

```text
Gearbox Redesign
```

in a local workspace.

Administrator changes:

```text
read_only = false
```

to:

```text
read_only = true
```

The Agent should discover the changed project capability during synchronization.

Managed files should then be treated as read-only according to the workspace policy.

Any locally modified files must NOT be silently deleted or overwritten.

Instead report something like:

```text
PROJECT READ ONLY

Local modifications detected:

SHAFT.PRT
HOUSING.PRT

These files will not be automatically overwritten.
```

---

# 40. Existing Workspace When Project Becomes Released

Similar protection is required when:

```text
IN_WORK
    ↓
RELEASED
```

If the workstation contains local modifications, those modifications must not disappear.

The server should refuse new write operations, while the Agent preserves the local engineering work until the user or administrator resolves it.

Critical rule:

> Changing project state must never silently destroy local engineering work.

---

# 41. Project State Must Not Rewrite History

Changing:

```text
IN_WORK
    ↓
RELEASED
```

must not alter historical:

```text
Object Versions
Metadata Snapshots
Dependency Snapshots
Audit Records
Baselines
Engineering Changes
```

Project state controls future permitted operations.

It does not rewrite previous engineering history.

---

# 42. Project State Must Not Change Object Identity

State transitions must never change:

```text
Project UUID
Object UUID
Version UUID
```

For example:

```text
IN_WORK
    ↓
CLOSED
    ↓
ARCHIVED
    ↓
CLOSED
```

must still refer to the same project.

---

# 43. Basic Capability Logic

Conceptually:

```text
function getProjectCapabilities(project, user):

    capabilities =
        permissionsFor(user, project)

    if project.state == IN_WORK:

        # Normal permissions apply.
        pass


    if project.state == ON_HOLD:

        removeWriteCapabilities(capabilities)


    if project.state == RELEASED:

        removeWriteCapabilities(capabilities)


    if project.state == CLOSED:

        removeWriteCapabilities(capabilities)


    if project.state == ARCHIVED:

        removeWriteCapabilities(capabilities)

        capabilities.normalSearch = false

        capabilities.requiresArchivedAccess = true


    if project.read_only == true:

        removeWriteCapabilities(capabilities)


    return capabilities
```

---

# 44. Write Capabilities

A helper could define:

```text
removeWriteCapabilities()
```

as removing:

```text
ADD_OBJECT
IMPORT
CHECKOUT
CHECKIN
REVISE
RENAME
DELETE
MODIFY_METADATA
MODIFY_STRUCTURE
COPY_DESIGN_INTO
SAVE_AS_INTO
```

Additional operations can be added as CreoPDM grows.

---

# 45. Integrity Rules Override Everything

Project permissions must never bypass core integrity protections.

For example:

```text
Administrator
+
IN_WORK
+
Full Permissions
```

still does NOT mean the administrator can:

```text
Overwrite historical version
Delete content referenced by a release
Modify finalized baseline
Break historical dependency snapshot
Destroy released engineering history
```

Therefore:

```text
Integrity Rules
      ↓
Project State
      ↓
Project Access Mode
      ↓
Role / Permission
      ↓
Operation
```

All applicable checks must pass.

---

# 46. Initial Implementation Recommendation

For the first implementation, keep it simple.

Implement:

```text
PROJECT STATES

IN_WORK
ON_HOLD
RELEASED
CLOSED
ARCHIVED
```

and:

```text
PROJECT ACCESS

read_only = true / false
```

Do not initially create a highly configurable lifecycle engine.

The fixed states above should cover the major CreoPDM project-management requirements while keeping the implementation understandable.

---

# 47. Recommended Default Behavior

```text
NEW PROJECT

State:
IN_WORK

Read Only:
FALSE
```

Normal lifecycle:

```text
IN_WORK
   ↓
RELEASED
   ↓
CLOSED
   ↓
ARCHIVED
```

Temporary hold:

```text
IN_WORK
   ↓
ON_HOLD
   ↓
IN_WORK
```

Cancelled project:

```text
IN_WORK
   ↓
CLOSED
   ↓
ARCHIVED
```

Temporary administrative freeze:

```text
IN_WORK
Read Only = FALSE

        ↓

IN_WORK
Read Only = TRUE

        ↓

IN_WORK
Read Only = FALSE
```

---

# 48. Acceptance Criteria

Status for the current minimum implementation (Administration → Products state + read-only; Files toolbar + API gates).

## IN_WORK

```text
[x] Normal engineering operations permitted according to user permissions

[x] Checkout permitted

[x] Check-In permitted

[x] Add object permitted

[x] Revise permitted (History revert)

[x] Metadata modification permitted
```

## ON_HOLD

```text
[x] Project remains visible

[x] Files remain downloadable

[x] BOM remains viewable

[x] Where Used remains available

[x] Checkout blocked

[x] Check-In blocked

[x] Add object blocked

[x] Modification blocked
```

## RELEASED

```text
[x] Project remains visible

[x] Released configuration remains accessible

[x] Files remain downloadable

[x] Historical versions remain accessible

[x] Checkout blocked

[x] Check-In blocked

[x] New objects blocked

[x] Existing objects cannot be modified through project operations

[x] API enforces restrictions
```

## CLOSED

```text
[x] Project remains searchable

[x] Historical data remains accessible

[x] Download remains available

[x] Engineering modifications blocked
```

## ARCHIVED

```text
[x] Project hidden from normal project list (Files / API product list)

[x] Project excluded from normal search by default (not listed → not selected)

[ ] Include Archived option can expose it (Administration → Products still lists archived; Files “include archived” toggle not built yet)

[x] Historical data remains intact

[x] BOM remains intact

[x] Where Used remains intact

[x] Baselines remain intact (N/A until baselines ship — data untouched)

[x] Releases remain intact (N/A until releases ship — data untouched)

[x] Engineering Changes remain intact (N/A until EC ship — data untouched)

[x] Audit remains intact

[x] Administrator can restore project (set state back from Administration → Products)

[x] Restore retains same Project UUID
```

## READ_ONLY

```text
[x] Can be enabled independently of project state

[x] Project remains viewable

[x] Files remain downloadable

[x] Checkout blocked

[x] Check-In blocked

[x] Add object blocked

[x] Metadata modification blocked

[x] Disabling Read Only does not change project lifecycle state

[x] Change is audited (PRODUCT_UPDATED activity includes state / read_only)
```

---

# 49. Data Integrity Acceptance Criteria

```text
[ ] Project state change cannot destroy object history

[ ] Project state change cannot destroy local workspace modifications

[ ] Project state change cannot change Object UUID

[ ] Project state change cannot change Version UUID

[ ] Archive does not delete engineering content

[ ] Archive does not break Where Used

[ ] Archive does not break BOM relationships

[ ] Archive does not break baselines

[ ] Archive does not break releases

[ ] Archive does not break Engineering Changes

[ ] Restore uses existing Project UUID

[ ] State changes are audited

[ ] State changes are transactional

[ ] Direct API calls cannot bypass state restrictions

[ ] Existing active checkouts are detected before restrictive transitions
```

---

# 50. Final Model

The basic CreoPDM project model should be:

```text
PROJECT
│
├── State
│     │
│     ├── IN_WORK
│     │
│     ├── ON_HOLD
│     │
│     ├── RELEASED
│     │
│     ├── CLOSED
│     │
│     └── ARCHIVED
│
├── Access
│     │
│     └── READ_ONLY
│           ├── TRUE
│           └── FALSE
│
├── Permissions
│     │
│     ├── User
│     └── Role
│
└── Objects
      │
      └── Independent Object Lifecycle
```

Effective operation permission becomes:

```text
Core Integrity Rules
        +
User Role
        +
User Permissions
        +
Project State
        +
Project Read-Only Setting
        +
Object Lifecycle State
        +
Checkout State
        =
Effective Capability
```

This keeps project management simple while leaving room for CreoPDM to develop more advanced lifecycle and workflow functionality later.
````