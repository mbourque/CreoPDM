# Product lifecycle states

CreoPDM product (project) lifecycle — separate from object `lifecycle_state`.

## States (Administration → Products order)

| State | Description | Mutations | Open / download / export |
|---|---|---|---|
| **In Work** | Being created or modified. Not approved. | Yes (unless read-only) | Yes |
| **In Review** | Submitted for engineering review. | No | Yes |
| **Approved** | Reviewed and approved but not necessarily released. | No | Yes |
| **Released** | Official version approved for manufacturing or downstream use. | No | Yes |
| **Under Change** | A modification is underway against a previously released design. | Yes (unless read-only) | Yes |
| **Obsolete** | No longer valid for new designs or production. | No | Yes |
| **Archived** | Retained for historical reference (hidden from normal Files list). | No | Yes |
| **Locked** | List files only — administrative freeze stricter than read-only. | No | No |

`read_only` remains an independent flag: freeze mutations without changing lifecycle state. Open / download still work when read-only (unlike **Locked**).

## Legacy remaps

Migration `033_product_lifecycle` and `parse_product_state` aliases:

- `ON_HOLD` → `IN_REVIEW`
- `CLOSED` → `OBSOLETE`

## Enforcement

- UI: `product_ui_capabilities()` → `product_ui.show_*` in templates
- API: `ensure_product_mutable` / `ensure_product_content_accessible` / `ensure_product_deletable`
- Contract: `tests/unit/test_product_access_policy_contract.py`
- Behavior: `docs/user-interactions.md` (read-only / Locked rows)
