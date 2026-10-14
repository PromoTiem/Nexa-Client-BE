# Orders #32 - first correctness batch

Branch: `fix/32-order-correctness`, based on ownership/preflight `04eb0e1`
and integrated transaction baseline `a48bbdd`. No deployment or migration.

## Implemented

- Validate pending -> paid -> fulfilled transitions, cancellation from pending
  or paid, and idempotent same-status updates. Reject invalid/null status and
  terminal-state resurrection before persistence.
- Allow item changes only on pending orders. Reject deletion of paid/fulfilled
  orders so those financial records cannot silently disappear through this API.
- Reject non-finite quantity/price/payment request values, and validate finite
  nonnegative values in service commands too. Payment currency must match the
  order; cancelled/fulfilled orders do not accept payment creation.
- Collect every page of items/payments with stable record-ID ordering and caller
  token/scope preserved. Fail on an empty intermediate page instead of returning
  a partial success. Detail child arrays now use record-ID order rather than
  timestamp order; the original migration did not define timestamp fields.
- Order creation copies the input before removing items, preserving caller data.

## Verification

2026-10-14: 27 focused order/transaction tests passed; full isolated unit suite
passed **384 tests** using `TMPDIR=/tmp/opencode python3 -m pytest tests/unit -q
-o addopts=''`. Changed-file Ruff lint/format and diff checks passed.

## Remaining gates (issue remains In progress)

- These checks are API service guards, not database-atomic invariants. Concurrent
  writes, retention races, and direct PocketBase writes still need coordinated
  locks/rechecks and the accepted database ownership/write boundary.
- Canonical catalog pricing, currency precision/rounding, overflow limits,
  recalculated parent totals after item changes, and settlement accounting remain.
  Existing float arithmetic and submitted unit prices are not certified by this
  batch's finite-number validation.
- Multi-record creation needs durable partial-write recovery; payment operations
  need idempotency keys and database uniqueness. A status transition alone does
  not establish that a payment was received or refunded.
- Resolve the explicit cancellation/refund policy for paid orders before release.
- Finish tenant/RBAC/rate-limit acceptance, immutable parent bindings, complete
  property lookup for large orders, disposable real-schema tests and OpenAPI.
- Parent design: `docs/transaction-ownership-design.md`. No broad collection-rule
  changes or migrations are included in this batch.
