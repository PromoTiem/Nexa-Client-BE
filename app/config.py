from functools import lru_cache
from pathlib import Path

from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

_CONFIG_FILE = Path(__file__).resolve().parent.parent / "config.yaml"


class LoggingSettings(BaseSettings):
    level: str = "INFO"
    loki_enabled: bool = False
    loki_url: str = "http://localhost:3100/loki/api/v1/push"
    loki_labels: dict[str, str] = {}


class StorageClientSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    endpoint_url: str = "http://localhost:9000"
    public_endpoint_url: str = "http://localhost:9000"
    access_key: str = ""
    secret_key: str = ""
    region: str = "us-east-1"
    presign_expiry_seconds: int = 900
    max_file_bytes: int = 10 * 1024 * 1024


class Settings(BaseSettings):
    # Nested settings are overridable via the "__" delimiter, e.g.
    # STORAGE__ENDPOINT_URL, LOGGING__LEVEL.
    model_config = SettingsConfigDict(env_nested_delimiter="__")

    # Application
    app_name: str = "Nexa-Client-BE"
    app_env: str = "development"
    app_debug: bool = False
    app_host: str = "0.0.0.0"
    app_port: int = 8002

    # PocketBase (IDP)
    pocketbase_url: str = "https://your-pocketbase-instance.example.com"
    pocketbase_auth_collection: str = "users"
    pocketbase_admin_email: str = ""
    pocketbase_admin_password: str = ""
    pocketbase_timeout: float = 10.0
    pocketbase_max_retries: int = 3
    pocketbase_retry_backoff: float = 0.5

    # Test credentials
    test_identity: str = ""
    test_password: str = ""

    # CORS
    allowed_origins: str = "http://localhost:3000"

    # Site deployment
    site_base_domain: str = "promotiem.dpdns.org"

    # Cloudflare
    cloudflare_api_token: str = ""
    cloudflare_account_id: str = ""
    cloudflare_zone_id: str = ""
    cloudflare_timeout: float = 30.0
    cloudflare_max_retries: int = 3
    cloudflare_retry_backoff: float = 1.0

    # Logging
    logging: LoggingSettings = LoggingSettings()

    # Storage (RustFS / S3)
    storage: StorageClientSettings = StorageClientSettings()

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        **kwargs: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        sources: list = [kwargs["init_settings"], kwargs["env_settings"]]
        if _CONFIG_FILE.exists():
            sources.append(
                YamlConfigSettingsSource(settings_cls, yaml_file=_CONFIG_FILE)
            )
        return tuple(sources)

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
