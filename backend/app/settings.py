"""Typed, environment-driven configuration.

Every setting is read from an environment variable named ``LOGICLENS_<FIELD>`` (case-insensitive)
unless noted. ``ANTHROPIC_API_KEY`` and ``REDIS_URL`` are also accepted without the prefix.
No .env file is read: configuration comes from the process environment only.
The README lists every variable with its default.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, List, Literal, Optional

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

EngineChoice = Literal["auto", "yolo", "claude", "hybrid", "stub"]

_ORIGIN_RE = re.compile(r"^https?://[A-Za-z0-9.\-\[\]:]+$")
MIN_API_KEY_CHARS = 16


def _split_csv(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [part.strip() for part in value.split(",") if part.strip()]
    return value


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="LOGICLENS_",
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,
        frozen=True,
    )

    # ---- vision engines -------------------------------------------------------------------
    engine: EngineChoice = "auto"
    yolo_onnx: Optional[Path] = None
    yolo_conf: float = Field(0.25, ge=0.01, le=0.99)
    yolo_iou: float = Field(0.45, ge=0.05, le=0.95)
    yolo_imgsz: int = Field(640, ge=64, le=2048, description="Input size when the model's is dynamic")
    yolo_threads: int = Field(1, ge=0, le=64, description="onnxruntime intra-op threads; 0 = ORT default")
    ocr: bool = True
    ocr_passes: int = Field(5, ge=1, le=5, description="tesseract passes voted per operand (accuracy vs CPU)")
    tesseract_cmd: str = "tesseract"
    ocr_timeout_s: float = Field(20.0, gt=0, le=120)

    # ---- LLM (Anthropic) ----------------------------------------------------------------
    anthropic_api_key: Optional[SecretStr] = Field(
        None, validation_alias=AliasChoices("LOGICLENS_ANTHROPIC_API_KEY", "ANTHROPIC_API_KEY", "anthropic_api_key")
    )
    vision_model: str = Field("claude-sonnet-5-5", min_length=1, max_length=100)
    explain_model: str = Field("claude-sonnet-5-5", min_length=1, max_length=100)
    chat_model: str = Field("claude-sonnet-5-5", min_length=1, max_length=100)
    deep_model: str = Field("claude-opus-5-5", min_length=1, max_length=100)
    llm_timeout_s: float = Field(60.0, gt=0, le=600)
    llm_max_retries: int = Field(1, ge=0, le=5)
    vision_max_tokens: int = Field(8192, ge=256, le=64000)
    explain_max_tokens: int = Field(4096, ge=256, le=32000)
    chat_max_tokens: int = Field(1500, ge=64, le=16000)
    llm_concurrency: int = Field(4, ge=1, le=256)
    llm_queue: int = Field(16, ge=0, le=10_000)
    llm_max_program_chars: int = Field(60_000, ge=100, le=200_000, description="cost guard for explain/chat")

    # ---- input limits -------------------------------------------------------------------
    max_upload_mb: float = Field(8, gt=0, le=64)
    max_image_pixels: int = Field(40_000_000, ge=10_000, le=200_000_000)
    max_image_side: int = Field(8000, ge=64, le=30_000)
    max_json_kb: int = Field(256, ge=1, le=10_240)

    # ---- CPU inference gate (per worker process) -----------------------------------------
    inference_concurrency: int = Field(1, ge=1, le=64)
    inference_queue: int = Field(8, ge=0, le=10_000)
    queue_timeout_s: float = Field(15.0, gt=0, le=600)

    # ---- HTTP -------------------------------------------------------------------------------
    cors_origins: Annotated[List[str], NoDecode] = ["http://localhost:5173"]
    api_keys: Annotated[List[SecretStr], NoDecode] = []
    docs: bool = False

    # ---- rate limiting ----------------------------------------------------------------------
    redis_url: Optional[SecretStr] = Field(
        None, validation_alias=AliasChoices("LOGICLENS_REDIS_URL", "REDIS_URL", "redis_url")
    )
    rate_limit_per_min: int = Field(60, ge=0, le=1_000_000, description="0 disables")
    llm_rate_limit_per_min: int = Field(10, ge=0, le=1_000_000, description="0 disables")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_origins(cls, value):
        out = []
        for origin in _split_csv(value):
            origin = str(origin).strip().rstrip("/")
            if origin != "*" and not _ORIGIN_RE.match(origin):
                raise ValueError(f"invalid CORS origin {origin!r}: use scheme://host[:port] with no path")
            out.append(origin)
        return out

    @field_validator("api_keys", mode="before")
    @classmethod
    def _parse_keys(cls, value):
        keys = []
        for key in _split_csv(value):
            raw = key.get_secret_value() if isinstance(key, SecretStr) else str(key)
            if len(raw) < MIN_API_KEY_CHARS:
                raise ValueError(f"every API key must be at least {MIN_API_KEY_CHARS} characters")
            keys.append(raw)
        return keys

    @field_validator("log_level", mode="before")
    @classmethod
    def _upper_level(cls, value):
        return str(value).upper() if value is not None else value

    # ---- derived ------------------------------------------------------------------------------
    @property
    def upload_cap_bytes(self) -> int:
        return int(self.max_upload_mb * 1024 * 1024)

    @property
    def json_cap_bytes(self) -> int:
        return self.max_json_kb * 1024

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def llm_enabled(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_api_key.get_secret_value().strip())
