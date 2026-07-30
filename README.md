# Nexa-Client-BE

Client-facing API for the Nexa site builder platform. Handles tenant-scoped site, property, media, and storage management.

## Overview

Nexa-Client-BE is the client-facing FastAPI backend for Nexa. It provides:

- **Site management** — CRUD operations for tenant-scoped websites
- **Property management** — Unified content model (products, posts, services, categories)
- **Media management** — File upload, confirm, list, download for site media
- **Storage management** — File upload, confirm, list, download for data files
- **Authentication** — Token-based auth via PocketBase

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
| GET/POST | `/sites` | List/create sites |
| GET/PATCH/DELETE | `/sites/{site_id}` | Site operations |
| POST | `/sites/{site_id}/properties` | Create property |
| GET | `/sites/{site_id}/properties` | List properties |
| GET/PATCH/DELETE | `/properties/{property_id}` | Property operations |
| GET/POST | `/media` | Media file operations |
| GET/POST | `/storage` | Storage file operations |

## Testing

```bash
python -m pytest tests/ -q
```

## License

Private — PromoTiem
