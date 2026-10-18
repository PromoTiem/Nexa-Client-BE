# Identity/site compatibility candidate

Local source follow-up to recovery PR #38. Not deployed.

## Fresh schema parity findings and candidate

Live inspection found users.status = active/inactive/pending, with no is_deleted
field. API accepts suspended and soft-deletion writes is_deleted. Candidate DTO
now accepts pending (authentication still rejects non-active states).
`scripts/user_schema_parity.py` is a pure additive transformation: preserve
existing field IDs and pending, append suspended, add optional boolean is_deleted,
reject unknown types/status values for manual review. It has no live apply path.
427 unit tests passed. Disposable PocketBase confirms repeat application,
preserved pending users, persisted suspended/deleted state, and rule rollback
without removing fields or losing upgraded data. Production not migrated.

Admin writer inspection found the live build webhook still calls
`_update_site_status()` using a static token that returned 401 on a superuser-only
schema check. The existing `origin/fix/137-source-audit` candidate already changes
that helper to a no-op: deployment state belongs to serve/stop, not build completion.
Prefer reviewing/adopting that established correction rather than making the
obsolete build-to-live projection operational. Admin source/runtime integration
and complete build/serve/upload acceptance remain pending.

## Serve/bucket writer follow-up

Local candidate adds SiteWorkflowGateway with separate serve and bucket field
allowlists. Serve mutation routes use the serve gateway; media/storage upload-URL
routes use the bucket gateway. Other resource methods retain caller credentials.
Each elevated site write checks active account, owner/admin/member role, parent
tenant and site lifecycle. Bucket writes initialize only the canonical name and
cannot replace an existing identity. Existing service-level transitions and
route locks remain in place.

422 unit tests pass. Disposable PocketBase acceptance confirms direct user site
PATCH is denied while serve bookkeeping and canonical bucket initialization
succeed through the gateway. This tests database persistence, not a real
Cloudflare deployment or S3 upload. No production changes in this follow-up.
Still required: inventory admin/backend-hook writers and exercise the complete
serve/build/upload pipeline before applying production site-rule restrictions.

## Reset-mail test scope

At user direction, reset-mail dispatch is mocked for now. Four HTTP contract
tests pass for `/auth/forgot-password`: identical acknowledgements for known
and unknown addresses, invalid-email rejection without dispatch, upstream 503
handling, and the three-per-minute dispatch limit. Mocking is confined to the
test dependency; production delivery behavior is unchanged. Actual SMTP
delivery, emailed URL contents and reset-token completion/replay/expiry remain
unverified and are deferred rather than counted as accepted.

## Implemented

- Tenant-admin account operations use AccountGateway, with active account,
  tenant ownership, lower-role hierarchy and field allowlists before privileged
  persistence. Self-service operations retain caller credentials.
- Site POST/PATCH/DELETE management routes use SiteGateway. Reads retain caller
  credentials, writes verify ownership and role. Hard deletion is restricted to
  records created in the same provisioning request, for rollback only.
- Profile metadata stays user-editable, matching the existing profile DTO.
  Authorization must use top-level role/tenant/status fields, never metadata.
  Direct rules protect those fields plus is_deleted, is_superuser and verified.
- Schema transformations modify rules only and preserve existing fields. Reapply
  and rollback were exercised on disposable PocketBase; records survived rollback.

## Verified

410 unit tests passed. Disposable identity test verifies real-user login,
refresh, name/metadata updates, password change, old-password rejection,
new-password login, account gateway administration, direct-create denial,
foreign-user denial and escalation denial. Disposable site test verifies scoped
read, locked direct creation, gateway create/update/retention, hidden retained
site, repeated migration and rule rollback with preserved data.

## Required before production rule migration

- Verify production field/status parity (including is_deleted and suspended)
  using a fresh schema snapshot; do not infer parity from synthetic fixtures.
- Exercise complete HTTP account/site routes, provisioning storage rollback,
  and password recovery mail/token handling. Current new acceptance tests call
  real PocketBase and gateways, not all public HTTP routes or email delivery.
- Inventory all remaining site writers: serve/build/storage workflows may still
  use caller credentials to update sites. Locking site writes before migrating
  those writers can break deployment/status flows.
- Ensure metadata is not used as authority by any downstream consumer.
- Snapshot production rules and data, record exact deployed compatible source,
  then apply the reviewed rule changes and repeat public acceptance. Existing
  production rules and source remain unchanged by this batch.
