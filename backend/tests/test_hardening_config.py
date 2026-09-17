"""Production secret guard (T5): validate_production must reject every
default/missing credential category and never leak values."""
from __future__ import annotations

import pytest

from app.config import ProductionSecretError, Settings


def _prod_settings(**overrides) -> Settings:
    base = dict(
        environment="production",
        jwt_secret="a-production-secret-that-is-long-and-random",
        station_api_key="a-production-station-key-just-as-random",
        mqtt_username="backend",
        mqtt_password="real-broker-password",
        allowed_origins="https://scwt.example.org",
        debug=False,
        debug_image_hash=False,
        seed_demo_user=False,
        email_provider="console",
        # Production-grade session/link settings required by validate_production:
        # short-lived access tokens and a real public base URL for emails.
        jwt_access_token_minutes=240,
        public_base_url="https://scwt.example.org",
    )
    base.update(overrides)
    return Settings(**base)


def test_valid_production_config_passes():
    _prod_settings().validate_production()


def test_default_jwt_secret_rejected():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(jwt_secret="dev-only-change-me").validate_production()
    assert "JWT_SECRET" in str(exc.value)


def test_default_station_key_rejected():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(station_api_key="scwt-dev-station-key").validate_production()
    assert "STATION_API_KEY" in str(exc.value)


def test_missing_mqtt_credentials_rejected():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(mqtt_username="", mqtt_password="").validate_production()
    assert "MQTT_PASSWORD" in str(exc.value)
    assert "MQTT_USERNAME" in str(exc.value)


def test_wildcard_or_empty_cors_rejected():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(allowed_origins="*").validate_production()
    assert "ALLOWED_ORIGINS" in str(exc.value)


def test_debug_flags_and_demo_seed_rejected_in_production():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(debug=True, debug_image_hash=True, seed_demo_user=True).validate_production()
    value = str(exc.value)
    assert "DEBUG" in value and "SEED_DEMO_USER" in value


def test_smtp_without_password_rejected():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(email_provider="smtp", smtp_password="").validate_production()
    assert "SMTP_PASSWORD" in str(exc.value)


def test_error_lists_categories_never_values():
    with pytest.raises(ProductionSecretError) as exc:
        _prod_settings(
            jwt_secret="dev-only-change-me", mqtt_password=""
        ).validate_production()
    message = str(exc.value)
    assert "dev-only-change-me" not in message
    assert "JWT_SECRET" in message


def test_development_environment_is_not_guarded():
    dev = Settings(environment="development", jwt_secret="dev-only-change-me")
    dev.validate_production()  # must not raise
