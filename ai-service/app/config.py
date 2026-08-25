"""AI service configuration."""
from __future__ import annotations

from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AISettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "Recycle Vision AI"
    # classifier = real | development
    # Production default is `real` (trained ONNX artifact). `development` is
    # only an isolated test fixture; its DEVELOPMENT_FORCE_* knobs never
    # affect the real classifier.
    classifier: str = Field(
        "real",
        validation_alias=AliasChoices("AI_SERVICE_CLASSIFIER", "classifier"),
    )
    # Real classifier: path to the trained model artifact (onnx/tflite/torch).
    model_path: str = Field(
        "models/model.onnx",
        validation_alias=AliasChoices("AI_MODEL_PATH", "model_path"),
    )

    # Development classifier overrides (test/scenario reproducibility only).
    development_force_class: str = ""
    development_force_confidence: float = 0.0

    classes: tuple[str, ...] = ("plastic", "metal", "paper", "other")

    # Defensive application-level upload cap for /predict, in bytes.
    # Station-camera frames are ~0.1-0.5 MB and even multi-megapixel photos
    # land well under this; the model downsamples anyway. Enforced BEFORE
    # decode/gate/inference so an oversized body can never be fully buffered.
    max_upload_bytes: int = Field(
        default=10 * 1024 * 1024,
        ge=1,
        validation_alias=AliasChoices("AI_MAX_UPLOAD_BYTES", "max_upload_bytes"),
    )

    host: str = "0.0.0.0"
    port: int = 8051


@lru_cache
def get_ai_settings() -> AISettings:
    return AISettings()


ai_settings = get_ai_settings()