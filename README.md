# Nexa-Client-BE

Client-facing API for the Nexa site builder platform. Handles tenant-scoped site, property, media, and storage management.

## Overview

Nexa-Client-BE is the client-facing FastAPI backend for Nexa. It provides:

- **Site management** — CRUD operations for tenant-scoped websites
- **Property management** — Unified content model (products, posts, services, categories)
- **Media management** — File upload, confirm, list, download for site media
- **Storage management** — File upload, confirm, list, download for data files
- **Authentication** — Token-based auth via PocketBase
- **Build & Serve** — Trigger builds and serve/deploy tenant sites
- **Content library** — Tenant-scoped templates, styles, blocks, pages, sections
- **RBAC** — Role-based access control (owner / admin / member / guest)

## Architecture

```
app/
  config.py              # Settings (env vars + config.yaml)
  main.py                # FastAPI app, lifespan, middleware

  interface/             # HTTP/API layer
    routes/              # FastAPI route handlers
    dto/                 # Request/response models
    dependencies.py      # Dependency injection factories
    route_helpers.py     # Shared route helpers

  application/           # Business logic
    services/

  infrastructure/        # External integrations
    pocketbase/
    cloudflare/
    storage/
```

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Copy and configure environment
cp config.example.yaml config.yaml

# Run the server
python run.py
```

## Configuration

Key settings in `config.yaml`:

| Setting | Description | Default |
|---------|-------------|---------|
| `client_app_port` | Server port | 8002 |
| `client_auth_collection` | PocketBase auth collection | `users` |
| `pocketbase_url` | PocketBase instance URL | - |
| `storage.endpoint_url` | RustFS/S3 endpoint | - |

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/auth/login` | Login |
| POST | `/auth/refresh` | Refresh token |
| POST | `/auth/forgot-password` | Request a temporary password (admin-backed) |
| GET/POST | `/sites` | List/create sites |
| GET/PATCH/DELETE | `/sites/{site_id}` | Site operations |
| GET | `/sites/{site_id}/serve` | Serve/deploy a site |
| POST | `/sites/{site_id}/stop` | Stop a served site |
| GET | `/sites/{site_id}/pipeline` | Build pipeline status |
| POST | `/sites/{site_id}/properties` | Create property |
| GET | `/sites/{site_id}/properties` | List properties |
| GET/PATCH/DELETE | `/properties/{property_id}` | Property operations |
| GET | `/templates` | List templates (tenant-scoped) |
| GET | `/templates/{template_id}` | Get template (supports `expand`) |
| GET | `/styles` | List styles (tenant-scoped) |
| GET | `/styles/{style_id}` | Get style |
| GET | `/blocks` | List blocks (tenant-scoped) |
| GET | `/blocks/{block_id}` | Get block |
| GET | `/pages` | List pages (tenant-scoped) |
| GET | `/pages/{page_id}` | Get page |
| GET | `/sections` | List sections (tenant-scoped) |
| GET | `/sections/{section_id}` | Get section |
| GET/POST | `/builds` | List/create builds |
| GET/PATCH/DELETE | `/builds/{build_id}` | Build operations |
| GET/POST/PATCH/DELETE | `/users` | User CRUD (tenant-scoped) |
| GET/PATCH | `/users/me` | Current user profile |
| GET/POST | `/media` | Media file operations |
| GET/POST | `/storage` | Storage file operations |

### Roles & permissions

Access is controlled by RBAC. Every authenticated user carries a `role`
(`owner`, `admin`, `member`, or `guest`); a missing role defaults to `guest`
(fail-closed, read-only). Routes enforce permissions via
`enforce_permission(ctx.auth, Permission.X)`.

All content and build endpoints are tenant-scoped: queries filter by the
caller's `tenant_id`, so a user can only see records belonging to their tenant.

## Testing

```bash
python -m pytest tests/ -q
```

## License

Private — PromoTiem
