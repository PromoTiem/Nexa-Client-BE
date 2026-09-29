# Client API route audit — 2026-09-29

Reviewed all **72 operations across 16 route modules**, their DTOs, shared authentication/RBAC/tenant helpers, and relevant service/infrastructure paths. Compared against `../Nexa-Documentation`, especially the core API, authentication, RBAC, analytics, collection schema, and upload-flow specifications.

This is a review, not a remediation patch. No application code or documentation in the sibling repository was changed. Findings below distinguish implementation bugs from documentation drift. Live PocketBase rules, credentials, S3, Cloudflare, and LLM behavior were not exercised.

## Critical and high-priority findings

### 1. Critical — unauthenticated password recovery enables account takeover

**Route:** `POST /auth/forgot-password`

[auth.py:58](/home/phantomal/Nexa-Client-BE/app/interface/routes/auth.py:58) looks up an arbitrary email using admin credentials, replaces its password, then returns that password to the unauthenticated requester at line 102. Knowing a victim's email is sufficient to reset their password and obtain the replacement, provided the configured admin connection works. The 404 response also reveals whether the account exists.

The [auth specification](/home/phantomal/Nexa-Documentation/specs/features/auth-api-spec.md:316) explicitly documents this behavior: this is an unsafe contract, not merely documentation drift. Replace it with an expiring, single-use recovery token delivered to the verified email address; return a generic acknowledgment to the caller.

### 2. High — analytics and insights omit tenant ownership enforcement

**Routes:** all site-scoped `/analytics/*` and `/insights/*` operations.

[analytics.py:115](/home/phantomal/Nexa-Client-BE/app/interface/routes/analytics.py:115) and [insights.py:56](/home/phantomal/Nexa-Client-BE/app/interface/routes/insights.py:56) check role permissions and ID syntax but never call `ctx.enforce_site()`. Their services query by supplied site/property IDs without adding the caller's tenant boundary. This permits cross-tenant reads and operations under the authenticated-only PocketBase rules described in the [RBAC specification](/home/phantomal/Nexa-Documentation/specs/features/rbac-spec.md:14).

Tracking is particularly clear: the shared collector persists with a background admin client ([main.py:68](/home/phantomal/Nexa-Client-BE/app/main.py:68)), so downstream user-token collection rules cannot protect those writes. A mock invocation accepted an event for `foreign_site` and performed **zero ownership queries**. The event pairs the foreign site ID with the attacker's tenant ID.

Enforce ownership before every read/write and check each distinct site in event batches. Validate property-to-site membership where applicable. Live read exploitability still depends on deployed collection rules; the missing application boundary and privileged tracking path are confirmed.

### 3. High — user-controlled filters can bypass scope conditions

**Routes:** `GET /builds`, dashboard/trends with `property_id`, insights recommendations with `type`, and property create/update validation.

[build.py:95](/home/phantomal/Nexa-Client-BE/app/interface/routes/build.py:95) directly interpolates `site_id` and `status`. A mock request with status `queued" || status!="` generated:

```text
tenant_id="pb_tenant_a" && status="queued" || status!=""
```

The injected OR branch escapes the tenant clause. With the documented broad PocketBase rules this can expose other tenants' builds. The same escaping omission occurs in [analytics_service.py:342](/home/phantomal/Nexa-Client-BE/app/application/services/analytics_service.py:342), [insight_service.py:96](/home/phantomal/Nexa-Client-BE/app/application/services/insight_service.py:96), and slug/child-category checks in [property_service.py:37](/home/phantomal/Nexa-Client-BE/app/application/services/property_service.py:37).

Validate IDs, constrain enums, and escape every string used in a PocketBase expression. Keep tenant clauses outside a parenthesized user-filter expression. Shared public-ID resolution also interpolates values without escaping; site template/domain inputs are not validated before reaching it.

### 4. High — public property creation exposes unrestricted content writes

**Route:** `POST /public/sites/{site_id}/properties`

[property.py:315](/home/phantomal/Nexa-Client-BE/app/interface/routes/property.py:315) accepts the full authenticated create DTO, including arbitrary property type, `status="published"`, fields, groups, and metadata. It checks only ID syntax, with no site-existence/ownership check, allowed submission type, publication restriction, or route rate limit. [PropertyService](/home/phantomal/Nexa-Client-BE/app/application/services/property_service.py:106) adds field/category validation but no such boundary.

The endpoint is intentionally public according to [api.md:71](/home/phantomal/Nexa-Documentation/specs/core/api.md:71). That does not require giving anonymous submissions the entire content-authoring contract. Introduce a restricted public submission DTO/workflow, verify the destination site's submission policy, force a non-public initial state, and add abuse controls. If privileged authentication succeeds, the current route can create published content for arbitrary site IDs.

### 5. High — disabled and soft-deleted users are not rejected by API authentication

[dependencies.py:139](/home/phantomal/Nexa-Client-BE/app/interface/dependencies.py:139) rejects missing tenants but never checks `status` or `is_deleted`. Login and refresh likewise return PocketBase's result directly. [User deletion](/home/phantomal/Nexa-Client-BE/app/interface/routes/user.py:313) only sets `status="inactive"` and `is_deleted=true`.

An isolated auth check accepted a refreshed record containing both those values. Consequently, disabling/deleting an account does not itself guarantee loss of API access; it depends entirely on an external PocketBase auth rule that was not verified here. Reject inactive/suspended/deleted users centrally and align the PocketBase auth rule and recovery flow with that policy.

### 6. High — admins can demote or disable owners

[user.py:292](/home/phantomal/Nexa-Client-BE/app/interface/routes/user.py:292) checks the requested new role, but never checks the target user's current role. An admin can PATCH an owner to `guest`, set their status inactive, or DELETE them. A mock invocation confirmed `admin -> owner -> guest` succeeds.

The docs specify restrictions on assigning roles but do not explicitly define protection of higher-ranked target users. This is therefore also a policy gap: the current behavior makes the owner/admin hierarchy ineffective for protecting owners. Define target-management rules and enforce them after loading the target, including self-deletion and last-owner protection if required by the product.

### 7. High — media/storage bulk deletion compares incompatible tenant identifiers

**Routes:** `POST /media/bulk-delete`, `POST /storage/bulk-delete`

[site_file_service.py:302](/home/phantomal/Nexa-Client-BE/app/application/services/site_file_service.py:302) compares `sites.tenant_id` (internal PocketBase relation ID) directly with `auth.record.tenant_id` (public business ID). Individual file deletion resolves these IDs correctly through `enforce_file()`.

A mock using `pb_tenant_a` versus `tenant_a` returned `not_found` for an owned file and never deleted it. Resolve the tenant relation consistently before comparison, and fail closed for files without a valid parent site. Existing tests use matching identifiers and miss this real schema distinction.

## Functional and consistency findings

### 8. Medium — public property authentication uses the wrong collection for admin credentials

[dependencies.py:77](/home/phantomal/Nexa-Client-BE/app/interface/dependencies.py:77) logs in with `pocketbase_admin_email/password` against `pocketbase_auth_collection`, whose client default is `users`. Other privileged flows correctly call `auth_admin()` for `_superusers`.

In the documented split between client users and PocketBase superusers, this makes public property submission fail even with valid admin credentials. Use the actual privileged auth method, after restricting the public operation described above. Configurations with a matching account in `users` can behave differently; no live login was attempted.

### 9. Medium — site bucket lifecycle has rollback, collision, CORS, and cleanup gaps

[site.py:136](/home/phantomal/Nexa-Client-BE/app/interface/routes/site.py:136) ensures a bucket exists, but if PocketBase creation fails, it unconditionally deletes the bucket at line 159—even if the bucket existed before this request. A mock confirmed the unconditional deletion attempt. An empty existing bucket can be removed; a nonempty S3 bucket instead fails deletion and can mask the original error.

Bucket names are normalized without a collision check (`Foo_Bar` and `foo-bar` both become `foo-bar`). Site creation also omits `site_base_domain`, so `create_bucket_for_site()` skips CORS configuration. Later upload setup only configures CORS when the bucket does not yet exist, leaving already-created buckets without the browser upload configuration unless externally provisioned.

On site deletion, [site.py:310](/home/phantomal/Nexa-Client-BE/app/interface/routes/site.py:310) derives a bucket name instead of using the persisted `bucket_name`; the storage client calls S3 `DeleteBucket` without emptying it. Failures are logged and the site record is still deleted. The [documented full cleanup](/home/phantomal/Nexa-Documentation/specs/core/api.md:45) therefore does not hold for populated buckets.

Track resource ownership during creation, reject normalized-name collisions, configure CORS for both existing/new buckets, and implement a recoverable cleanup workflow using the stored bucket identity.

### 10. Medium — site template assignment bypasses content tenant isolation

[site.py:132](/home/phantomal/Nexa-Client-BE/app/interface/routes/site.py:132) and the PATCH template branch resolve templates solely by public ID. Unlike `GET /templates/{template_id}`, they do not add a tenant clause. Under the documented authenticated-only rules, callers can attach another tenant's template even though normal template reads reject it. Apply the same tenant-scoped resolution as content read routes. Build template overrides likewise need a membership check.

### 11. Medium — analytics parameters are accepted but ignored or misrepresented

- [analytics.py:197](/home/phantomal/Nexa-Client-BE/app/interface/routes/analytics.py:197): trends `period=weekly|monthly` is only copied into the response; `get_trend()` always returns daily records. The [spec promises aggregation granularity](/home/phantomal/Nexa-Documentation/specs/analytics/analytics-api-spec.md:238).
- [analytics.py:238](/home/phantomal/Nexa-Client-BE/app/interface/routes/analytics.py:238): top-products `type` is unused. Returned items never populate `type`, `unique_visitors`, or `conversion_rate`, so the DTO supplies null/zero instead of the [documented values](/home/phantomal/Nexa-Documentation/specs/analytics/analytics-api-spec.md:299).
- [analytics.py:145](/home/phantomal/Nexa-Client-BE/app/interface/routes/analytics.py:145): dashboard `property_id` scopes current KPIs, but percentage changes are computed over the entire site; the result mixes two populations.
- [insights.py:95](/home/phantomal/Nexa-Client-BE/app/interface/routes/insights.py:95): batch analysis ignores `property_type`, includes soft-deleted properties, and fetches only the first 500 records without pagination. The supplied filter cannot prevent unwanted LLM work, and larger sites are only partially analyzed.

Implement the advertised filters and aggregation, or reject unsupported options and correct the contract. Apply filtering before ranking/limiting and exclude soft-deleted content consistently.

### 12. Medium — documented analytics/insights rate limits are absent

The [analytics specification](/home/phantomal/Nexa-Documentation/specs/analytics/analytics-api-spec.md:737) lists per-tenant limits for event ingestion, aggregation, reads, and AI analysis. Neither route module has limit decorators or an equivalent dependency. The app's limiter has no default limits; only auth routes declare limits.

Authenticated callers can repeatedly queue analyses or request large date-range aggregations without those promised controls. Add explicit per-tenant limits and bounded aggregation ranges. An LLM budget mechanism is not an HTTP request-rate limit.

### 13. Medium — valid DTO inputs can result in internal errors

- `PATCH /users/{id}` accepts `{"role":null}` in `UserUpdateRequest`, then calls `UserRole(None)`. A mock reproduced an uncaught `ValueError` at [user.py:294](/home/phantomal/Nexa-Client-BE/app/interface/routes/user.py:294), resulting in HTTP 500 through the global handler. Decide whether null means omission or is invalid, and validate accordingly.
- Aggregate dates are unconstrained strings in [dto/analytics.py](/home/phantomal/Nexa-Client-BE/app/interface/dto/analytics.py:136); [analytics_service.py:77](/home/phantomal/Nexa-Client-BE/app/application/services/analytics_service.py:77) calls `strptime()` outside error handling. Invalid dates yield 500; reversed dates return a misleading successful zero-work response. Use typed dates, ordered-range validation, and a maximum span.

### 14. Medium — template tag filter expression is malformed

[template.py:118](/home/phantomal/Nexa-Client-BE/app/interface/routes/template.py:118) generates `~tags~"value"`, while other filters use the field as the left-hand operand. The leading `~` produces an invalid field/operator expression. Confirm the intended matching semantics for the deployed tags field and generate the corresponding valid PocketBase filter. No live parser request was sent.

### 15. Low — content list validation and response mapping are inconsistent

`GET /styles`, `/blocks`, `/pages`, and `/sections` pass `sort` directly to PocketBase; sites, builds, properties, and templates use `validate_sort()` with allowlists. Add consistent validation rather than forwarding arbitrary field/expression strings.

[block.py:28](/home/phantomal/Nexa-Client-BE/app/interface/routes/block.py:28) and [section.py:28](/home/phantomal/Nexa-Client-BE/app/interface/routes/section.py:28) turn a legitimate `order_index=0` into null. [template.py:40](/home/phantomal/Nexa-Client-BE/app/interface/routes/template.py:40) similarly turns `is_valid=false` into null. Preserve false/zero distinctly from missing values.

PATCH semantics also differ: most resource routes skip explicit nulls, while user updates forward them. Document a consistent clear-versus-omit policy before changing behavior.

## Documentation drift

| Contract | Documentation | Current implementation / consequence |
|---|---|---|
| Direct application base URL | Core docs use `http://localhost:8002/api/v1` | Router is mounted without `/api/v1`; direct requests using that prefix return 404. A proxy could rewrite it, but that is not the direct localhost contract. |
| Site creation body | `api.md` requires `name`, makes `template_id` optional, omits required `domain` | Client DTO requires `site_id`, `template_id`, and `domain`; ignores `name`/`metadata`/create-time `domain_id`. Following the shared table can yield 422 or silently ignored fields. Split admin/client request tables. |
| Media/storage pagination | `api.md` says `per_page` | Both routes accept `limit`; response still uses `per_page`. A supplied `per_page` query is silently ignored. |
| Client user status | `api-client.md` and auth spec say `pending` | DTO accepts `active`, `inactive`, `suspended`; sending `pending` yields 422. Collection-schema doc already agrees with the DTO. |
| Embedded tenant timestamps | `api-client.md` example uses `created`, `updated` | `TenantResponse` uses `created_at`, `updated_at`. |
| Client API reference coverage | `api-client.md` covers auth/profile/sites/serve only | Omits site deletion, user admin CRUD, builds, properties, content, files, health, analytics, and insights. The shared API and analytics specs cover much of this separately. |
| RBAC helpers | `rbac-spec.md` lists `require_role()` | No such helper exists in `app/interface/rbac.py`. |
| AGENTS role overview | Members described as having broader CRUD; guests list all resources; tenantless admins bypass isolation | Detailed RBAC matrix/code deny member property/build deletion, guest storage/user reads, and all tenantless client access. Clarify AGENTS to match the client-specific contract. Template/content mutation routes do not exist. |
| Site list payload | Same site response used for list/detail | List now reads `sites_list`, a view excluding `config`, so clients need the detail endpoint for configuration. Document this explicitly in the API reference. |

Unsafe password recovery and unrestricted public property creation are documented behaviors. They require contract/security changes, not simply updating prose to describe them more accurately.

## Architecture and coverage observations

- `serve_service.py` imports interface DTOs; `site_file_service.py` imports interface auth helpers. Both violate the required dependency direction. Move shared domain types/authorization inputs to an appropriate lower layer.
- Site lifecycle rollback/cleanup, user recovery/account workflows, and insight batch processing still contain business logic in route modules. Extract these workflows into services as fixes are made.
- Content GET/list routes consistently add tenant filters, and standard site/property/media/storage single-resource routes generally perform ownership checks. The analytics/insights and bulk-file paths are notable exceptions.
- Route registration and generated OpenAPI were inspected; all 72 declared operations appeared. Public auth/health/property routes were distinguished from authenticated routes, and static user `/me` paths precede `/{user_id}`.

## Verification

- `venv/bin/python -m pytest tests/unit -q -o addopts=''`: **221 passed, 2 failed**. Failures were default configuration assertions (`app_port`, Loki enabled) reading local runtime YAML.
- Re-ran the same unit suite with `app.config._CONFIG_FILE` patched in-process to a nonexistent temporary path and the settings cache cleared: **223 passed**. No configuration file was edited.
- Isolated mock checks confirmed injected build filters, foreign-site event acceptance, owner demotion by admin, null-role `ValueError`, acceptance of a deleted auth record, owned-file bulk-delete rejection, and bucket deletion attempted on site-create failure.
- No live integration calls or external mutations were performed. Passing existing tests does not validate deployed PocketBase rules or cover the gaps above.
- Test reporting/coverage defaults were disabled to preserve the pre-existing modification to `reports/junit.xml`.

## Complete operation inventory

Generated from the registered FastAPI router; paths below are relative to the application's actual root.

| Method | Path | Route module |
|---|---|---|
| GET | `/health` | `health.py` |
| POST | `/auth/login` | `auth.py` |
| POST | `/auth/refresh` | `auth.py` |
| POST | `/auth/forgot-password` | `auth.py` |
| GET | `/users/me` | `user.py` |
| PATCH | `/users/me` | `user.py` |
| POST | `/users/me/password` | `user.py` |
| GET | `/users` | `user.py` |
| POST | `/users` | `user.py` |
| GET | `/users/{user_id}` | `user.py` |
| PATCH | `/users/{user_id}` | `user.py` |
| DELETE | `/users/{user_id}` | `user.py` |
| GET | `/sites` | `site.py` |
| POST | `/sites` | `site.py` |
| GET | `/sites/{site_id}` | `site.py` |
| PATCH | `/sites/{site_id}` | `site.py` |
| DELETE | `/sites/{site_id}` | `site.py` |
| GET | `/builds` | `build.py` |
| POST | `/builds` | `build.py` |
| GET | `/builds/{build_id}` | `build.py` |
| PATCH | `/builds/{build_id}` | `build.py` |
| DELETE | `/builds/{build_id}` | `build.py` |
| PATCH | `/sites/{site_id}/serve/status` | `serve.py` |
| POST | `/sites/{site_id}/serve` | `serve.py` |
| POST | `/sites/{site_id}/stop` | `serve.py` |
| GET | `/sites/{site_id}/pipeline` | `serve.py` |
| POST | `/sites/{site_id}/properties` | `property.py` |
| GET | `/sites/{site_id}/properties` | `property.py` |
| GET | `/properties/{property_id}` | `property.py` |
| PATCH | `/properties/{property_id}` | `property.py` |
| DELETE | `/properties/{property_id}` | `property.py` |
| POST | `/public/sites/{site_id}/properties` | `property.py` |
| GET | `/templates` | `template.py` |
| GET | `/templates/{template_id}` | `template.py` |
| GET | `/styles` | `style.py` |
| GET | `/styles/{style_id}` | `style.py` |
| GET | `/blocks` | `block.py` |
| GET | `/blocks/{block_id}` | `block.py` |
| GET | `/pages` | `page.py` |
| GET | `/pages/{page_id}` | `page.py` |
| GET | `/sections` | `section.py` |
| GET | `/sections/{section_id}` | `section.py` |
| POST | `/media/upload-url` | `media.py` |
| POST | `/media/{file_id}/confirm` | `media.py` |
| GET | `/media` | `media.py` |
| GET | `/media/{file_id}` | `media.py` |
| PATCH | `/media/{file_id}` | `media.py` |
| DELETE | `/media/{file_id}` | `media.py` |
| GET | `/media/{file_id}/download-url` | `media.py` |
| POST | `/media/bulk-delete` | `media.py` |
| POST | `/storage/upload-url` | `storage.py` |
| POST | `/storage/{file_id}/confirm` | `storage.py` |
| GET | `/storage` | `storage.py` |
| GET | `/storage/{file_id}` | `storage.py` |
| PATCH | `/storage/{file_id}` | `storage.py` |
| DELETE | `/storage/{file_id}` | `storage.py` |
| GET | `/storage/{file_id}/download-url` | `storage.py` |
| POST | `/storage/bulk-delete` | `storage.py` |
| POST | `/analytics/events` | `analytics.py` |
| POST | `/analytics/events/track` | `analytics.py` |
| GET | `/analytics/dashboard/{site_id}` | `analytics.py` |
| GET | `/analytics/trends/{site_id}` | `analytics.py` |
| GET | `/analytics/top-products/{site_id}` | `analytics.py` |
| GET | `/analytics/product/{site_id}/{property_id}` | `analytics.py` |
| POST | `/analytics/aggregate/{site_id}` | `analytics.py` |
| POST | `/insights/analyze/{site_id}/{property_id}` | `insights.py` |
| POST | `/insights/batch-analyze/{site_id}` | `insights.py` |
| GET | `/insights/score/{site_id}/{property_id}` | `insights.py` |
| GET | `/insights/seo/{site_id}/{property_id}` | `insights.py` |
| GET | `/insights/recommendations/{site_id}` | `insights.py` |
| GET | `/insights/summary/{site_id}` | `insights.py` |
| GET | `/insights/health` | `insights.py` |
