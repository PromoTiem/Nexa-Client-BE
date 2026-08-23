# AGENTS.md

## Project Overview

**Nexa-Client-BE** is a FastAPI backend for the Nexa site builder client-facing API. It manages user authentication, site CRUD, property content, media uploads, and site deployment.

The service uses:

* **PocketBase** as the database and authentication provider
* **RustFS/S3** for object storage (media and storage files)
* **Cloudflare Pages** for site deployment

---

# Architecture

The project follows a three-layer architecture:

```text
app/
  config.py              # Settings (env vars + config.yaml)
  main.py                # FastAPI app, lifespan, middleware

  interface/             # HTTP/API layer
    routes/              # FastAPI route handlers
    dto/                 # Request/response models
    dependencies.py      # Dependency injection factories
    route_helpers.py     # Shared route helpers
    exception_handlers.py
    middlewares/

  application/           # Business logic
    services/

  infrastructure/        # External integrations
    pocketbase/
    cloudflare/
    storage/
    validation/
    logging.py
    loki_handler.py
    retry_utils.py
```

Dependency direction must always remain:

```text
interface -> application -> infrastructure
```

Lower layers must never import higher layers.

---

# Service Boundaries

## Route Handlers

Routes should contain only:

* request validation
* authentication and authorization
* orchestration
* response formatting

Routes should never contain business logic.

---

## Application Services

Business rules belong in:

```text
app/application/services/
```

Services coordinate infrastructure clients and implement workflows.

Examples:

* property CRUD with slug/category validation
* media upload lifecycle
* site serve/stop state machine
* Cloudflare Pages deployment

---

## Infrastructure Layer

Infrastructure clients should:

* contain no business rules
* remain reusable and stateless
* encapsulate external API details
* expose clean interfaces to services

---

# Authentication & Authorization

## Auth Flow

1. Client sends `POST /auth/login` with identity + password
2. PocketBase validates credentials and returns a JWT token
3. Client includes `Authorization: Bearer <token>` on subsequent requests
4. `get_auth_context()` calls PocketBase `auth-refresh` to validate the token
5. `get_tenant_context()` wraps the auth context with tenant isolation

## RBAC System

Four roles with ascending privileges:

| Role | Capabilities |
|------|-------------|
| `owner` | Full access to everything |
| `admin` | Same as owner |
| `member` | CRUD sites, properties, templates, builds; upload media; no delete sites/users |
| `guest` | Read-only (list all resources) |

Enforcement via `enforce_permission(auth, Permission.XXX)` in route handlers.

## Tenant Isolation

All client users must have a `tenant_id` in their PocketBase record. Admin users (no tenant_id) bypass tenant isolation.

Use `TenantContext.enforce_site()`, `TenantContext.enforce_file()`, `TenantContext.enforce_owns()` for resource-level isolation.

---

# Code Conventions

## Python Style

* Python 3.12+
* Type hints on all public functions
* Pydantic v2 for all request/response models
* `async/await` for all I/O operations
* f-strings for string formatting

## Naming

* `snake_case` for functions, variables, methods
* `PascalCase` for classes
* `UPPER_SNAKE_CASE` for constants
* Route files match their resource: `site.py`, `property.py`, `media.py`
* DTO files match their resource: `dto/site.py`, `dto/property.py`

## File Organization

* One router per route file
* One Pydantic model per DTO class
* Services are stateless classes or modules with functions
* Infrastructure clients wrap external APIs

## Error Handling

* Use `HTTPException` with appropriate status codes
* 400: validation errors, bad input
* 401: missing/invalid authentication
* 403: authenticated but not authorized
* 404: resource not found (use this for tenant isolation failures)
* 422: request validation errors (Pydantic)
* 500: internal errors (caught by global exception handler)

---

# Testing

## Test Structure

```text
tests/
  conftest.py           # Shared fixtures (client, live_client)
  helpers.py            # Test utilities (get_live_token_or_skip, cleanup_record)
  unit/                 # Fast, isolated tests (no external deps)
  integration/          # Tests against live PocketBase
  performance/          # Locust load tests
```

## Running Tests

```bash
# Unit tests (fast, no external deps)
pytest tests/unit -v

# Integration tests (requires live PocketBase)
pytest tests/integration -v

# All tests except storage/live/e2e
pytest -m "not storage and not live and not e2e"

# Performance tests
locust -f tests/performance/locustfile.py --host http://localhost:8002
```

## Test Markers

* `@pytest.mark.storage` - tests that call RustFS/S3 directly
* `@pytest.mark.live` - tests that call live external APIs
* `@pytest.mark.flaky` - known flaky tests, quarantined
* `@pytest.mark.e2e` - end-to-end pipeline tests

## Writing Tests

* Unit tests: mock all external dependencies, test one function/class
* Integration tests: use `live_client` fixture, skip gracefully with `pytest.skip()` when credentials missing
* Always clean up test data in integration tests

---

# Configuration

## Environment Variables

Nested settings use `__` delimiter:

```bash
POCKETBASE_URL=http://localhost:8090
STORAGE__ENDPOINT_URL=http://localhost:9000
LOGGING__LEVEL=DEBUG
```

## Config Files

* `config.yaml` - active runtime config (gitignored)
* `config.example.yaml` - template for new environments

---

# Security

* Never commit `config.yaml` or secrets
* Rate limiting on auth endpoints (5/min login, 30/min refresh)
* PocketBase filter values must be sanitized via `sanitize_filter_value()`
* Sort parameters validated via `validate_sort()` against allowlist
* CORS restricted to HTTPS origins in production
* Swagger/ReDoc disabled in production
* Email validation via `EmailStr` on user creation

---

# CI/CD

Two GitHub Actions workflows:

* `ci.yml` - full pipeline (lint, unit tests, integration tests, coverage)
* `test.yml` - lighter matrix-based pipeline (lint, unit tests across Python versions)

Required secrets:

* `POCKETBASE_URL`, `POCKETBASE_API_TOKEN`
* `TEST_IDENTITY`, `TEST_PASSWORD`
* `RUSTFS_ENDPOINT`, `RUSTFS_ACCESS_KEY`, `RUSTFS_SECRET_KEY`
* `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`
