"""Application configuration.

All values come from environment variables (`.env` is supported) so nothing is
hardcoded: database URL, MQTT broker, AI service URL, deposit thresholds and
session lifetime are all configurable (see `.env.example`).

Production safety: when `ENVIRONMENT=production`, `validate_production()`
refuses to start with development-default secrets or missing credentials.
Failure messages name the offending CATEGORY only — never a secret value.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# Values that are ONLY acceptable in development. A production deployment
# running with any of these fails fast at startup.
_DEV_DEFAULT_SECRETS = frozenset(
    {
        "dev-only-change-me-in-production",
        "dev-only-change-me",
        "dev-secret-not-for-prod",
        "change-me-in-production",
        "dev-station-key",
        "scwt-dev-station-key",
    }
)


class ProductionSecretError(RuntimeError):
    """Raised at startup when production mode has missing/default secrets.

    The message intentionally contains requirement descriptions only — never
    the configured values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- API -----------------------------------------------------------------
    app_name: str = "SCWT API"
    api_v1_prefix: str = "/api/v1"
    debug: bool = False
    # development | production. Production enables the startup secret guard,
    # requires explicit CORS origins and MQTT credentials.
    environment: str = "development"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    # -- Security ------------------------------------------------------------
    jwt_secret: str = "dev-only-change-me-in-production"
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 60 * 24  # 24h dev sessions

    # -- CORS ----------------------------------------------------------------
    # Comma-separated list of exact origins allowed to call the API with
    # credentials. Never "*" with credentials. Development defaults cover the
    # local Flutter/web runners; production MUST set explicit origins.
    allowed_origins: str = "http://localhost:3000,http://localhost:8080"

    # -- Database ------------------------------------------------------------
    database_url: str = "postgresql+psycopg2://scwt:scwt@localhost:5432/scwt_db"

    # -- AI service ----------------------------------------------------------
    ai_service_url: str = "http://localhost:8052"
    ai_timeout_seconds: float = 15.0

    # -- MQTT ----------------------------------------------------------------
    mqtt_broker_host: str = "localhost"
    mqtt_broker_port: int = 1886
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_client_id: str = "scwt-backend"
    mqtt_topic_prefix: str = "scwt/stations"
    # TLS (HiveMQ Cloud and any broker with listener 8883). Certificate
    # validation always uses the system trust store — no bypasses.
    mqtt_tls: bool = False
    mqtt_tls_port: int = 8883

    # -- Station camera -------------------------------------------------------
    # Shared secret authenticating the station camera when it uploads a capture
    # to `POST /api/v1/deposit/capture`. The camera carries it in the
    # `X-Station-Key` header. Production replaces this with per-station keys.
    station_api_key: str = "scwt-dev-station-key"
    station_capture_timeout_seconds: int = 20

    # -- Upload limits ---------------------------------------------------------
    # Station JPEG frames are ~100-500 KB; 8 MB rejects abuse before the AI
    # sees the bytes while leaving generous headroom for full-res sensors.
    max_upload_bytes: int = 8 * 1024 * 1024

    # -- Auth rate limiting ------------------------------------------------------
    # Sliding window per client identity/IP. Login is deliberately tight;
    # register slightly looser so a lab room of students can sign up.
    auth_login_rate_limit: int = 5
    auth_register_rate_limit: int = 10
    auth_rate_window_seconds: int = 60

    # -- Deposit / routing policy --------------------------------------------
    min_deposit_weight_grams: float = 1.0
    ai_high_confidence: float = 0.80
    ai_medium_confidence: float = 0.50
    deposit_session_ttl_seconds: int = 5 * 60  # 5 minutes, configurable
    automatic_routing_required: bool = False  # HIGH is auto; MEDIUM = manual ok

    # -- Seed data -----------------------------------------------------------
    seed_on_startup: bool = True
    # When true, `seed()` also creates the well-known dev/test account
    # (`demo@scwt.campus` / `demo123`, 45 pts). Default OFF so the runtime
    # DB contains no demo users; test suites and the software E2E opt in.
    seed_demo_user: bool = False

    # -- Email (password reset / verification) ---------------------------------
    # Delivery provider is pluggable: `console` logs the message (development),
    # `smtp` sends via the configured server. Credentials come from env only.
    email_provider: str = "console"  # console | smtp
    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str = "noreply@scwt.campus"
    password_reset_token_ttl_seconds: int = 30 * 60
    email_verification_token_ttl_seconds: int = 24 * 60 * 60

    # Student handoff QR: the student app displays a short-lived single-use
    # token; the station tablet scans it and claims the deposit session with
    # its station key. Short TTL + single use => non-replayable.
    deposit_handoff_token_ttl_seconds: int = 120
    # When true, unverified accounts are refused at login. Requires a real
    # delivery path (SMTP): the console provider only logs the link server-side,
    # so gating login with it would lock every new user out permanently.
    email_verification_required: bool = False
    # Base URL used inside reset/verification links (env-configured).
    public_base_url: str = "http://localhost:3000"

    # -- Profile avatars -----------------------------------------------------
    # Directory where uploaded profile photos are stored as
    # <user_id>.jpg (re-encoded server-side is out of scope; the file keeps
    # its validated image bytes). Version counter lives in users.avatar_version.
    avatars_dir: str = "data/avatars"
    avatar_max_bytes: int = 2 * 1024 * 1024  # 2 MB hard ceiling

    # -- Debug ---------------------------------------------------------------
    # When true, mounts the debug-only /debug/image-sha256 fingerprint route
    # used by the hardware validation harness to prove byte identity of station
    # camera captures. Never enable in production — it exists only for the
    # verification harness.
    debug_image_hash: bool = False

    def allowed_origin_list(self) -> list[str]:
        """Parses ALLOWED_ORIGINS into a clean list (no wildcards survive)."""
        origins: list[str] = []
        for raw in self.allowed_origins.split(","):
            origin = raw.strip().rstrip("/")
            if origin and origin != "*":
                origins.append(origin)
        return origins

    def validate_production(self) -> None:
        """Fails fast in production when secrets are default or missing.

        Only category names are reported — never values."""
        if not self.is_production:
            return
        problems: list[str] = []

        if not self.jwt_secret or self.jwt_secret in _DEV_DEFAULT_SECRETS:
            problems.append("JWT_SECRET must be set to a unique production value")
        if not self.station_api_key or self.station_api_key in _DEV_DEFAULT_SECRETS:
            problems.append("STATION_API_KEY must be set to a unique production value")
        if not self.mqtt_password:
            problems.append("MQTT_PASSWORD is required in production")
        if not self.mqtt_username:
            problems.append("MQTT_USERNAME is required in production")
        if not self.allowed_origin_list():
            problems.append("ALLOWED_ORIGINS must list explicit origins in production")
        if self.debug:
            problems.append("DEBUG must be false in production")
        if self.debug_image_hash:
            problems.append("DEBUG_IMAGE_HASH must be false in production")
        if self.seed_demo_user:
            problems.append("SEED_DEMO_USER must be false in production")
        if self.email_provider == "smtp" and not self.smtp_password:
            problems.append("SMTP_PASSWORD is required when EMAIL_PROVIDER=smtp")
        if self.jwt_access_token_minutes > 240:
            problems.append(
                f"JWT_ACCESS_TOKEN_MINUTES={self.jwt_access_token_minutes} is too long for production "
                "(recommended ≤ 240 minutes / 4 hours)"
            )
        if self.public_base_url.startswith("http://localhost"):
            problems.append(
                "PUBLIC_BASE_URL must not be localhost in production "
                "(password reset / verification links will be broken)"
            )
        if self.email_provider == "smtp" and not self.smtp_host:
            problems.append("SMTP_HOST is required when EMAIL_PROVIDER=smtp")
        if self.email_verification_required and self.email_provider != "smtp":
            problems.append(
                "EMAIL_VERIFICATION_REQUIRED=true requires EMAIL_PROVIDER=smtp "
                "(the console provider cannot deliver verification links, so "
                "every new account would be locked out)"
            )

        if problems:
            raise ProductionSecretError(
                "production configuration rejected:\n  - " + "\n  - ".join(problems)
            )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
