# Transaction ownership and migration design - BE #137

Status: proposed source design, not a migration approval or deployed policy.
Inspected baseline: `a48bbdd` (integrated transaction candidate), layered on
reviewed lifecycle candidate `70d2d63`. Working branch:
`design/137-transaction-ownership`.

## Source findings

| Source | Finding and consequence |
|---|---|
| `app/interface/routes/transactional.py` | CRUD passes `ctx.token` into services. Current authorization depends on both API checks and caller-token PocketBase rules. |
| `scripts/migrate_transactional.py` | New collections receive authenticated-global list/view rules, but no caller create/update/delete rules. Direct database readers can bypass API tenant checks; user-token writes are locked by default. |
| Same migration | Existing collections are skipped without verifying fields, rules, or indexes. Non-200 lookup responses also lead to creation attempts rather than distinguishing 404 from errors. |
| Same migration | `created_at` and `updated_at` are absent although clients write them and services sort/filter on them. `required` on numeric totals and `is_active` needs zero/false acceptance testing. |
| `app/interface/route_helpers.py` | Users expose a public tenant ID; `sites.tenant_id` is a PocketBase record relation. A direct equality between these values is not an ownership rule. |
| `app/application/services/transactional_service.py` | Parent IDs are text business IDs, not PocketBase relations. Orders reference sites; payments/items reference orders; items/bookings/availability reference properties. |
| `scripts/backfill_bookings.py` | Lookup reads top-level `legacy_property_id`; writes put it in metadata. Lookup-then-insert has no unique source claim and is not concurrent-safe. |
| `app/application/services/public_submission_service.py` | Public submission uses a server static token and dual-writes bookings. API user rules alone will not constrain this path. |

These are source findings. No live schema, data, or deployed policy was exported
or certified in this batch.

## Proposed authority model

Preserve caller-token reads and API authentication. Add explicit internal
relations without replacing the existing public text IDs consumed by clients.
Resolve relations from canonical parents; never trust a submitted tenant field.

| Collection | Existing public key / parent | Additive internal relations |
|---|---|---|
| orders | `order_id`, `site_id` | `site_ref` -> sites |
| order_items | `item_id`, `order_id`, `property_id` | `order_ref` -> orders, `property_ref` -> properties |
| payments | `payment_id`, `order_id` | `order_ref` -> orders |
| bookings | `booking_id`, `site_id`, `property_id` | `site_ref` -> sites, `property_ref` -> properties; `source_submission_ref` -> properties for legacy origin |
| availability | `availability_id`, `site_id`, `property_id` | `site_ref` -> sites, `property_ref` -> properties |

Relations are single-valued and non-cascading. Public identifiers remain
immutable. User `tenant_id` resolves through `tenants.tenant_id`, while site
ownership resolves through the tenant record relation. Never infer ownership
from who last edited a record or from customer contact fields.

### Read predicates (semantic contract, not executable PocketBase syntax)

1. Auth record belongs to the accepted client users collection, passes the same
   account-status checks as `enforce_account_access`, and has a valid tenant.
2. Resolve parent site through `site_ref`, or `order_ref.site_ref` for children.
3. Site tenant's public ID equals the authenticated user's public tenant ID.
4. Site is active under the lifecycle policy; soft-deleted orders/bookings and
   their child rows are hidden from ordinary clients.
5. Enforce the relevant read permission. Guest access follows the accepted RBAC
   contract, never an implicit global authenticated-user rule.
6. Missing/ambiguous relationships deny access. Both list and single-record
   routes enforce the same predicate, including expansions and realtime access.

Exact PocketBase rule expressions must be validated on the release schema and
version, including absent JSON lifecycle keys. Do not ship untested expressions
from this design. Explicitly test two sites within one tenant as well as two
different tenants: tenant ownership alone cannot validate a property reference.

### Write boundary decision

Simply allowing tenant-scoped writes would let direct PocketBase callers bypass
FSM, authoritative totals, payment idempotency, and availability constraints in
the API. Simply locking all writes would break the existing user-token service.

Preferred candidate: keep user-token writes only alongside database-side
validation hooks that enforce ownership and transaction invariants for every
write path. Required checks include:

- Canonicalize and cross-check each public-ID/relation pair on creation;
  reject changes of owner, site, order, or source marker on update.
- Require same-site property ownership and current publication eligibility
  where required; preserve historical financial/property snapshots.
- Apply state transitions, authoritative pricing/currency/totals, payment
  uniqueness, and lifecycle checks in the database write boundary as well as API
  UX validation. Metadata cannot override these values.
- User request hooks enforce identity/role/account status. Record-level hooks
  enforce data invariants for internal saves, backfill, and static-token public
  submissions too. Superuser bypass of API rules is not proof of valid data.
- Hard deletes remain locked to ordinary clients; soft-delete updates require
  policy checks. Parent deletion must not cascade financial history.

Alternative requiring a separate architecture decision: lock direct client
writes and introduce a narrowly scoped server-mediated command boundary. Do not
silently substitute a superuser client in transaction routes as a shortcut.
Neither approach is enabled by this design; #32/#33 must implement and test the
chosen write boundary before any rules are widened.

## Migration phases

1. **Inventory and decision:** record exact source/schema/hook revisions and
   authenticated collection/account semantics. Take a recoverable schema/data
   snapshot; inspect all pages, not a default first-page sample. Resolve the
   write-boundary decision before preparing executable rules.
2. **Offline preflight:** run the tool below on the complete snapshot. Quarantine
   missing or ambiguous parents, duplicate IDs/source markers, cross-site
   properties, and retained/deleted history needing a separate policy. Do not
   delete or silently reparent rows to make validation pass.
3. **Additive schema candidate:** add optional non-cascading relations, required
   timestamp fields, and the canonical source marker. Review unique public-ID
   indexes. Use collection-specific status vocabularies. Verify zero monetary
   values and false booleans; do not make them nonzero through `required` flags.
4. **Compatible writers:** deploy tested canonical relationship population and
   invariant hooks while relations remain optional for legacy rows. Freeze or
   coordinate concurrent writers while snapshot-derived ownership is backfilled;
   stale mappings must be rechecked at each mutation.
5. **Backfill:** resumable batches with durable checkpoints and explicit errors.
   Derive source markers from existing metadata, verify the source is a same-site
   legacy submission, and preserve both dynamic fields and original submissions.
   Enforce a unique nonempty `source_submission_ref` claim before enabling
   concurrent backfill/dual-write. Duplicate conflicts require explicit review.
6. **Constrain:** after complete coverage and exact-head disposable acceptance,
   install reviewed tenant read rules and the chosen write boundary atomically
   with compatible hooks. Recheck existing collections rather than skipping them.
7. **Accept:** record before/after schema hashes, affected row counts, index
   definitions, executed tests, and rollback compatibility. Obtain migration and
   rollout approval before applying production changes.

Rollback must preserve newly created records and additive fields. A down
migration must not drop relations or delete history to restore an older binary.
If access must be restricted during rollback, use an explicit maintenance mode
and compatible API version rather than restoring global authenticated reads.

## Offline preflight

```bash
python scripts/transaction_ownership_preflight.py /private/complete-snapshot.json
```

The script only reads the supplied file and prints findings. It does not import
runtime config, connect to a database, create credentials, or apply changes.
Required JSON shape:

```json
{
  "collections": [{"name": "orders", "fields": [], "listRule": null}],
  "complete_collections": ["users", "tenants", "sites", "properties", "orders", "order_items", "payments", "bookings", "availability"],
  "record_counts": {"users": 0, "tenants": 0, "sites": 0, "properties": 0, "orders": 0, "order_items": 0, "payments": 0, "bookings": 0, "availability": 0},
  "records": {"users": [], "tenants": [], "sites": [], "properties": [], "orders": [], "order_items": [], "payments": [], "bookings": [], "availability": []}
}
```

Provide all five transaction schema definitions, including fields and rules; the
abbreviated shape above intentionally produces schema findings. `record_counts`
must match complete exported arrays. This detects declared truncation; it cannot
prove a caller's completeness declaration without the export provenance.

Exit 1: invalid/incomplete input. Exit 2: findings requiring resolution/review.
Exit 0: inspected snapshot without findings, **not migration approval**. Rules
that look scoped are still marked for review: the tool is not a rule evaluator.
Reports include collection names, internal record IDs, counts, and finding
codes, not customer emails, phone numbers, payment amounts, or raw row values.
Snapshots and reports should remain private; do not commit production exports.

## Acceptance required before rollout

- Real PocketBase two-tenant direct API tests for lists/details, all writes,
  expansions, realtime subscriptions, and denied user auth/profile escalation.
- Same-tenant cross-site items/services denied; public IDs cannot masquerade as
  record IDs; parent reassignment and forged relation fields denied.
- Disabled/tenantless users denied; owner/admin/member/guest behavior tested.
- Retention versus create/update races and lock/claim recovery verified across
  both API and direct database paths.
- Money, FSM, payment replay and child partial-write recovery under #32.
- Published spa-service eligibility, date/time/availability semantics,
  dual-write recovery and repeat/concurrent backfill under #33.
- Replay migration on already-created collections; unexpected schema drift,
  authorization errors, and duplicate-index conflicts fail explicitly.

## Local verification - 2026-10-14

14 focused tests passed (`pytest ... -o addopts=''`; only this offline tool was
tested). Coverage includes public/record-ID distinctions, same-tenant cross-site
links, orphans, ambiguous parents, incomplete inventories, retained history,
conflicting/duplicate legacy markers, the actual historical migration's schema
definitions (parsed without executing it), report privacy, and read-only CLI.
This is a design/preflight milestone, not real-database rule acceptance.

Next: review the write-boundary decision, then implement #32/#33 with the
matching database hooks and disposable release-schema test matrix. The legacy
migration/backfill scripts remain unchanged and must not be used as the new
migration candidate.
