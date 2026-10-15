# Payment recovery follow-up

Candidate branch: `fix/32-payment-recovery`, based on deployed `de1e704`.
Local source changes only; not deployed.

Four regressions reproduced before fixes:
- Cancelling an order still pending after a payment-status write failure left
  its committed simulated payment completed.
- Retrying cancellation of an already-cancelled order did not reconcile payments.
- A paid order with a cancelled payment could still be fulfilled after an
  interrupted cancellation.
- Pending order detail returned a stale cached total after an item write
  succeeded but the parent-total update failed.

Changes: all cancellation requests reconcile simulated completed payments;
fulfillment requires completed payments in matching currency summing exactly to
the stored total, without pending/refunded entries; pending detail derives totals
from persisted items without writing on GET. Historical settled totals remain
unchanged.

Verification: 395 unit tests and eight disposable PocketBase flow tests passed;
changed-file Ruff lint/format passed. Production source and services untouched.

## Follow-up implementation

- Optional `idempotency_key` on order creation and item addition. Preserve the
  same key and exact payload when retrying. Different payload returns 409.
- Stable order/item identifiers and a persisted creation fingerprint let a retry
  resume a hidden draft after partial creation. Already-deleted completed orders
  are not resurrected. Historical unkeyed drafts are not auto-deleted/recovered.
- Item-add retry repairs the cached parent total without duplicating the item.
- Pending list/detail totals derive from persisted items; list queries batch
  order IDs. Historical settled totals remain unchanged.
- Order mutations now acquire site then order locks and recheck the site's
  lifecycle, coordinating with same-host retention. Creation uses the same site
  lock. This does not cover direct database or cross-host mutations.

Verification: 395 unit tests and ten transaction flow tests passed after these
changes; an additional disposable identity-rule test passed separately.

## Identity/site rule review

`scripts/identity_rule_candidate.py` prepares conservative user/site rules with
no apply command. The user rule was tested with real ordinary-user tokens:
role/tenant/status/superuser/verified changes and foreign-user reads are denied;
own profile-name update succeeds. Site rules lock writes and restrict reads.

These rules are NOT deployed. Current account administration and site editing
use caller credentials and require compatible server-mediated paths before
locked writes can be activated. Site-rule acceptance, login/account lifecycle
coverage and a coordinated migration remain outstanding. Applying these rules
alone would break existing management operations.

The new `DELETE /orders/{order_id}/items/{item_id}` endpoint authorizes the
parent even when the item is absent, repairs the cached total, and returns 204
on repeat. The legacy unscoped deletion endpoint is retained for compatibility.
The last remaining item cannot be removed.

Read-only inventory: `python scripts/inventory_order_drafts.py --site-id SITE`.
Reports distinguish keyed interrupted creation, historical unkeyed drafts,
deleted completed orders, and any draft with payment records. No automatic
publication/deletion is performed; ordinary API retries recover keyed drafts.

Latest verification: **397 unit tests and 12 disposable flow tests passed**,
including interrupted item deletion/retry, actual persisted totals, real user
tokens, order creation recovery, capacity and profile-rule checks.

Remaining limitations: retries without keys can still duplicate item additions;
old unkeyed drafts need operator reconciliation. No production changes.
