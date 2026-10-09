# Product lifecycle states

CreoPDM product (project) lifecycle — separate from object `lifecycle_state`.

Configurable under **Administration → Lifecycle states** (stored in `settings.json` → `lifecycle`). Role permissions still apply on top (`state ∩ role`).

## Built-in states (default order)

| State | Description | Default mutations | Default open / download |
|---|---|---|---|
| **Pre-Work** | Unrestricted experimentation without formal review or revision controls. | Yes | Yes |
| **In Work** | Being created or modified. Not approved. **Default for new products.** | Yes | Yes |
| **In Review** | Submitted for engineering review. | No | Yes |
| **Approved** | Reviewed and approved but not necessarily released. | No | Yes |
| **Released** | Official version approved for manufacturing or downstream use. | No | Yes |
| **Under Change** | A modification is underway against a previously released design. | Yes | Yes |
| **Obsolete** | No longer valid for new designs or production. | No | Yes |
| **Archived** | Retained for historical reference (hidden from normal Files list). | No | Yes |
| **Locked** | List files only (default). | No | No |

Admins can **add custom states**, edit labels/descriptions/order, and toggle Allowed/Blocked per operation. Built-in keys cannot be deleted.

## Operations in the matrix

`view`, `download` (open/export), `checkout` (also Undo / Force Undo Checkout), `checkin` (add/upload/folders), `remove`, `edit_metadata`, `rename` (product), `change_state`, `history`.

`read_only` on a product still blocks mutation ops independently of the matrix.

## Enforcement

- UI: `product_ui_capabilities()` → `product_ui.show_*`
- API: `ensure_product_allows` / `ensure_product_mutable` / `ensure_product_content_accessible`
- Contract: `tests/unit/test_product_access_policy_contract.py`
- UX: `docs/user-interactions.md`
