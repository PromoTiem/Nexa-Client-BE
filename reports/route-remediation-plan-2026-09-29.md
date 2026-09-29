# Route remediation plan

Based on the [72-operation audit](route-audit-2026-09-29.md). This plan covers all 15 finding groups, documentation drift, and architecture/test gaps. Implementation and deployment have not started.

## Delivery order

| Change set | Priority | Audit findings | Dependencies |
|---|---|---|---|
| 1. Account recovery and account access | Critical | 1, 5, 6, user portion of 13 | None |
| 2. Tenant boundaries and safe filters | High | 2, 3, 7, 10 | None; shared helpers reused later |
| 3. Restricted public submissions | High | 4, 8 | Safe filters from 2; submission contract review |
| 4. Site/storage lifecycle | High | 9 | Ownership helpers from 2 |
| 5. Analytics and insights correctness/limits | Medium | 11, 12, date portion of 13 | 2 |
| 6. Remaining API consistency | Medium | 14, 15 | Safe filters from 2 |
| 7. Documentation, integration validation, release | Required | All documentation/architecture observations | Relevant preceding changes |

Keep each change set independently reviewable. Include its regression tests and affected documentation in the same delivery; change set 7 is a final reconciliation, not a reason to postpone documentation. Ship the critical account-recovery fix without waiting for unrelated refactoring.

## 1. Account recovery and account access

**Files:** auth/user routes and DTOs, auth dependencies, RBAC, PocketBase client; new application account service as needed.

- Replace password replacement/return with PocketBase's supported email-token password-reset workflow. Verify the installed/deployed PocketBase reset contract before implementing infrastructure methods; avoid creating a parallel token system.
- Return the same acknowledgment for known and unknown addresses. Never return credentials or mutate a password merely because reset was requested. Keep auth rate limits; handle upstream failures without revealing account existence.
- Provide a reset-confirm route only if the existing frontend/PocketBase reset page does not already own confirmation. Coordinate the changed response and reset link destination with the client integration.
- If mail/reset delivery is unavailable at release time, disable the unsafe recovery operation with an explicit unavailable response until delivery works. Do not retain the temporary-password fallback.
- Apply one account-access policy to login, refresh, and authenticated dependencies: reject inactive, suspended, or soft-deleted users; continue requiring a client tenant. Inspect missing-status records before deciding whether they need a migration.
- Load the target user before applying management rules. Proposed policy: administrative role/status/delete operations target strictly lower-ranked users; owner accounts cannot be demoted/deleted through generic user CRUD. Self-profile changes remain under `/users/me`. Any owner transfer becomes an explicit separate workflow.
- Reject explicit null for non-nullable role/status updates with 422; omitted fields remain unchanged.

**Acceptance:** recovery responses contain no password; unknown/known email responses are indistinguishable; expired/reused reset tokens fail; disabled accounts cannot authenticate or reuse tokens; an admin cannot demote, suspend, or delete an owner; allowed lower-role operations still succeed; null-role requests never produce 500.

**Deployment dependency:** verify PocketBase auth rules also reject disabled/deleted accounts. API checks alone do not revoke direct PocketBase access for clients holding its tokens.

## 2. Tenant boundaries and safe filters

**Files:** shared auth/tenant/filter helpers, analytics/insights/site/build routes, property/analytics/insight/file services, PocketBase infrastructure utilities.

- Put PocketBase literal escaping/filter construction in the infrastructure layer so services can reuse it without importing interface helpers. Keep authorization policy in application/interface code.
- Use consistent public-ID versus PocketBase-record-ID resolution. Reuse it for individual and bulk file authorization; missing parent sites fail closed with 404.
- Enforce site ownership before analytics/insights reads, aggregation, queueing, or LLM calls. Validate property membership in the authorized site, including soft-delete rules.
- Pre-authorize every distinct site in event batches before buffering any event. Proposed contract: a foreign/missing site rejects the whole request with 404 and queues nothing. Preserve existing partial acceptance only for subsequent per-event processing failures, and document that distinction.
- Resolve site template references and build template overrides with the same tenant scope as content GET routes. Preserve same-tenant and any explicitly documented shared-template behavior; do not infer global access from missing tenant data.
- Replace unsafe interpolation throughout the audited paths: build query values, analytics property filters, insight types, property slugs/category children, file IDs, and public-ID lookups. Validate identifiers/enums as well as escaping literals.
- Review stored IDs used in template expansion and helper-generated expressions, not just direct query parameters. Parenthesize composed user conditions before appending tenant constraints.
- Inspect deployed collection rules in staging against the documented schema. Confirm whether direct PocketBase access can bypass API RBAC; record and remediate rule gaps alongside API changes, with a migration owned by the schema repository where appropriate.

**Acceptance:** a two-tenant test matrix rejects foreign IDs for every affected operation; no denied operation buffers events, calls the LLM, writes records, or deletes objects. Owned bulk files succeed with distinct public/internal tenant IDs. Quotes, backslashes, and OR expressions cannot alter scope. Existing valid filters still work against an actual staging PocketBase parser.

## 3. Restricted public submissions

**Files:** public property route, dedicated submission DTO/service, static PocketBase dependency; submission consumer documentation.

- Inspect the documented booking/contact workflows and existing client payloads before choosing the allowlisted submission types and fields.
- Replace the general content-authoring DTO with a submission-specific contract. Resolve the destination site server-side, require public submissions to be enabled, and validate payloads against its permitted submission schema.
- Generate server-controlled identifiers/publication fields where compatible with the submission workflow. Force non-public initial status; reject attempts to select publication state or arbitrary content types.
- Add public endpoint limits and request-size/field limits. Use trusted client-IP handling and a site-level quota appropriate to deployment; CORS is not an authorization control.
- Correct privileged authentication to use the superuser auth method **only in the same change that restricts the endpoint**. Never deploy the credential fix alone and activate the existing unrestricted writer.
- Document rollout for existing forms. If the allowed submission policy is unresolved, keep the endpoint disabled by default until it is configured.

**Acceptance:** permitted forms work; unknown/disabled sites and unsupported types fail; anonymous callers cannot publish or create arbitrary content; rate limits yield 429; validation failures perform no privileged write.

## 4. Site and storage lifecycle

**Files:** site route, new site lifecycle service, bucket resolver, storage client, cleanup tests.

- Move create/delete workflow and rollback into an application service.
- Return creation ownership from bucket provisioning. Roll back only resources created by the current operation; preserve the original failure if cleanup also fails.
- Prevent normalized bucket/project-name collisions before provisioning. Inspect existing assignments for collisions and custom names; do not rename existing buckets automatically. Use a uniqueness mechanism that remains safe under concurrent creation, rather than only a preflight lookup.
- Use persisted `bucket_name` for deletion and verify it is exclusively assigned to the authorized site before destructive cleanup.
- Apply approved CORS configuration to both new and existing site buckets. Make reconciliation idempotent; preserve explicitly supported custom origins.
- Implement complete, paginated bucket cleanup, including versions/delete markers if versioning is enabled. Handle partial object-deletion failures.
- Preserve a recoverable site/cleanup record until required external cleanup succeeds. Proposed synchronous behavior: return an upstream failure and keep retryable state instead of reporting 204 while leaving resources behind. If scale requires a durable asynchronous cleanup job, specify that contract before introducing it.
- Make retries safe when DNS, Pages bindings, objects, or buckets are already absent. Preserve existing public site identity and deployment behavior.

**Acceptance:** duplicate-create failure never removes an existing bucket; concurrent normalized collisions cannot share storage; browser upload preflight works; nonempty/custom-named buckets are cleaned correctly; partial failures retain retry state and a second attempt completes without affecting other sites.

## 5. Analytics and insights correctness and request limits

**Files:** analytics/insights routes, DTOs, services, aggregation helpers, limiter configuration.

- Implement daily/weekly/monthly trend buckets. Define UTC boundaries, week start, partial-bucket handling, and sum versus average semantics for each supported metric.
- Apply the top-products type filter before ranking/limiting. Populate type and supported metrics from authoritative data; verify whether unique visitor counts can be computed for the requested range rather than summing daily uniques. Explicitly document any approximation or unavailable metric.
- Apply the same property filter to current and previous-period dashboard KPIs.
- Honor batch `property_type`, exclude soft-deleted records, and paginate all eligible properties. Move batching out of the route, retain task references, bound concurrent work, and log outcomes. Do not add a new job-status API unless required by the consumer contract.
- Use typed dates, reject reversed ranges, and bound aggregation work. Proposed maximum: 366 days per request, configurable and documented; larger backfills use an administrative workflow.
- Constrain ranges, metrics, periods, insight types, and priorities to supported values; invalid inputs return 422 instead of falling back silently or failing with 500.
- Implement the documented per-tenant limits: event endpoints 100/min, aggregation 10/min, dashboard/trends 30/min, analysis 10/min, batch analysis 3/min, insight reads 30/min. Verify shared enforcement across deployed workers and define the limiter failure policy. Tenant identity must come from validated authentication.

**Acceptance:** daily/weekly/monthly results have correct boundaries and values; filters affect ranking and both KPI periods; batches larger than 500 are complete; deleted/nonmatching properties never reach the LLM; invalid/oversized ranges fail before work; tenant quotas are independent and consistent across workers.

## 6. API consistency and small correctness fixes

**Files:** template/style/block/page/section routes, DTOs, pagination and validation helpers.

- Confirm the deployed tags field type, then fix tag matching with the correct PocketBase expression and verify multiple-tag semantics.
- Add sort allowlists to the four unvalidated content lists. Use actual schema fields, consistent direction handling, and a stable default.
- Preserve `false`, `0`, and valid empty containers instead of treating them as missing.
- Define PATCH behavior field by field: omitted means unchanged; explicit null clears only nullable fields; null for role/status/required relationships returns 422. Avoid a blanket change that silently clears existing data.
- Preserve `limit` for media/storage clients and add `per_page` as a documented compatibility alias. If both appear with different values, return 422; keep response pagination names consistent.
- Keep current root-mounted routes. Correct the direct-localhost base URL documentation; document any verified gateway `/api/v1` rewrite separately. Do not silently relocate endpoints.

**Acceptance:** tags filter correctly; invalid sorts are rejected consistently; zero/false survive serialization; PATCH clear/omit behavior is covered; pagination aliases work without breaking current callers.

## 7. Documentation, architecture, and release validation

- Update `../Nexa-Documentation/specs/core/api-client.md` to cover every client operation or link each family to its complete contract. Split shared admin/client site DTO tables.
- Reconcile base URLs, required site fields, user statuses, tenant timestamps, list-versus-detail site config, pagination aliases, recovery/public submission changes, analytics limits, and new error behavior.
- Update auth/RBAC/analytics/upload-flow specs; remove nonexistent helper references. Align repository AGENTS role summaries with the chosen client policy rather than broadening permissions accidentally.
- Remove service imports from `app.interface`: application services return application models/data and routes map them to response DTOs. Keep infrastructure free of authorization policy. Extract workflows while fixing them rather than performing a broad unrelated rewrite.
- Isolate config-default tests from runtime YAML and environment state; keep explicit tests for YAML/environment precedence. Use fixtures with deliberately different public/internal IDs.
- Add targeted regressions for the findings, then run lint and the full unit suite. Add a minimal import-boundary check to prevent the existing layer violations from returning.
- Run opt-in staging integration tests with two disposable tenants, real PocketBase filter evaluation, and disposable S3 resources. Exercise reset emails through a test mailbox and mock/sandbox LLM calls. Always clean up test data.
- Compare registered OpenAPI operations with the audited inventory: preserve the existing 72 operations except explicitly documented contract changes/additions. Verify auth requirements, DTOs, status codes, and route order.

**Release sequence:** deploy schema/rule prerequisites compatibly, then backend fixes, coordinate frontend recovery/submission changes, and run focused smoke tests. Keep restrictive backend controls in place if a frontend rollback is necessary. Do not restore password disclosure or unrestricted public writes as a rollback strategy.

## Decisions to settle during implementation

These do not block the independent tenant/filter and bulk-delete repairs. Proposed defaults above make the plan concrete; confirm them against actual consumers before releasing behavioral changes.

| Decision | Proposed default | Evidence to inspect |
|---|---|---|
| Password reset confirmation owner | Existing PocketBase/FE reset page; add backend confirm only if needed | Installed PB version, mail settings, frontend auth flow |
| Public submission scope | Explicit site opt-in and allowlisted form/booking schema; never publish | Booking/contact specs and deployed form payloads |
| Owner management | Generic CRUD cannot demote/delete owners; admin manages lower roles | Tenant administration requirements and owner-transfer needs |
| Cleanup execution | Retryable synchronous workflow first | Object counts, request timeouts, existing job infrastructure |
| Rate-limit persistence | Shared limiter state for multiple workers | Deployment topology and existing shared storage |
| Analytics precision | Correct period semantics; explicitly label approximations | Aggregate schema, raw-event availability, frontend metric use |

## Completion criteria

All finding groups have a merged fix or a documented, evidence-backed resolution; security regressions pass; unit tests are configuration-independent; staging verifies external contracts; documentation describes the delivered API; and no denied operation produces external side effects. Deployment itself is a separate release action from preparing and reviewing these changes.
