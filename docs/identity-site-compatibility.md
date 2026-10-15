# Identity/site compatibility candidate

Local source follow-up to recovery PR #38. Not deployed.

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
