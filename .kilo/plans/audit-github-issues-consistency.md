# Audit — GitHub issues vs. current codebase (Nexa-Client-BE)

Branch: `feat/first-auth-password-flow`. The five issues are *mostly* implemented
in code, but an audit for **consistency and correctness** surfaced real gaps. This
plan documents status per issue and the concrete fixes needed.

## Issue-by-issue status

### 1. feat: Define user roles and implement RBAC for API access control — PARTIAL / INCONSISTENT
- `app/interface/rbac.py` defines `UserRole`, `Permission`, `ROLE_PERMISSIONS` and
  `enforce_permission`. All routes call `enforce_permission(ctx.auth, ...)` ✅.
- **Problem A (HIGH): default role mismatch.** `rbac.py` treats a missing `role`
  field as `GUEST`, but `app/interface/routes/user.py:40` serializes the same field
  as `"member"`. A user without a `role` is enforced as GUEST server-side yet shown
  as member — confusing and a latent privilege bug. Pick one source of truth.
- **Problem B (LOW): dead RBAC machinery.** `require_role`, `require_permission` and
  `RoleGuard` (the decorator path) are **never used** by any route — enforcement is
  done inline. `RoleGuard.__post_init__` also has a no-op `if/else` (both branches
  assign `self._allowed_roles = self.allowed_roles`), so `required_permission` never
  narrows roles at construction. Either adopt the decorator uniformly or remove it to
  avoid two parallel authorization patterns.

### 2. Add GET endpoints for content resources (template, style, block, page, section) — DONE but TENANT-ISOLATION GAP
- GET list/get exist for all five collections and enforce `*_LIST` permission ✅.
- **Problem C (HIGH): no tenant isolation.** Unlike `site`, `property`, `build`,
  `serve` (which filter by tenant or call `ctx.enforce_*`), the content routes
  (`template.py`, `style.py`, `block.py`, `page.py`, `section.py`) query **all**
  records with no `tenant_id`/`site_id` filter. Since `get_auth_context` requires a
  `tenant_id`, every caller has a tenant, yet these endpoints return **every tenant's
  data** → cross-tenant data exposure.
  - `templates`/`styles` may be intentionally a shared global design library — confirm
    and document explicitly; if truly global, add a comment + maybe a config flag.
  - `blocks`/`pages`/`sections` are almost certainly tenant- (or site-) scoped → must
    be filtered. Resolve tenant like `build.py` (public→record id) or enforce site
    tenant like `property.py` (`ctx.enforce_site(pb, site_id)`) when a `site_id` is
    available.
  - `template.py` `get_template` expand path (`_resolve_style`, `_resolve_batch`) also
    resolves linked records by public id only — no tenant check, can leak cross-tenant
    linked data.

### 3. feat: Build and Serve API for Nexa-Client-BE — DONE
- `build.py` and `serve.py` implemented; build filters by tenant, serve uses
  `ctx.enforce_owns` via `map_site_record`. Consistent with the rest. ✅

### 4. Remove superadmin auth path — enforce user collection only — DONE
- `auth.py` uses `settings.pocketbase_auth_collection` (`users`) for login/refresh.
  Grep for `superadmin` returns nothing. `forgot_password` uses admin creds only to
  locate the user record (operational, not a client auth path) — acceptable.
- Minor: `import secrets` is inside the function body; hoist to module top for style.

### 5. Bug: duplicate /sites path segment on property routes causes 404 — RESOLVED
- Property routes are now `/sites/{site_id}/properties` (no prefix) and
  `/properties/{property_id}`; `property_router` is included **without** a prefix and
  `serve_router` (prefix `/sites`) defines `/{site_id}/serve|stop|pipeline|...`. No
  double `/sites`. ✅ Keep/verify the regression test.

## Additional issues found
- **Problem D (LOW): README is stale.** `README.md` API table omits `/templates`,
  `/styles`, `/blocks`, `/pages`, `/sections`, `/builds`, `/sites/.../serve`,
  `/users`, and any mention of RBAC/roles. Update to match implemented surface.
- **Problem E (LOW): duplicated auth logic.** `get_auth_context` and
  `get_optional_auth_context` in `dependencies.py` share ~20 lines; extract a helper.

## Recommended fixes (priority order)
1. **Tenant isolation for content GET endpoints (Problem C).** Add `tenant_id` (or
   `site_id` + site-tenant enforcement) filtering to `list_*`/`get_*` in
   `block.py`/`page.py`/`section.py`; decide & document global vs scoped for
   `template.py`/`style.py`; add tenant checks to template `expand` resolution.
2. **Unify default role (Problem A).** Make `rbac.py` and `user.py` agree on the
   default when `role` is absent; ensure user creation/registration always sets a role.
3. **Remove or adopt RBAC decorator machinery (Problem B).** Delete unused
   `require_role`/`require_permission`/`RoleGuard` (and fix `__post_init__`) OR migrate
   routes to use them; keep a single authorization pattern.
4. **Update README (Problem D)** and minor cleanups (Problems E, hoist `secrets`).
5. **Add/keep regression tests** for: tenant isolation on content endpoints, default
   role behavior, and no duplicate `/sites` prefix.

## Verification
- `python -m pytest tests/ -q`
- `ruff check app/` (repo already uses ruff — see `.ruff_cache`)
- Manual: call each content GET as two different-tenant users and confirm isolation.
