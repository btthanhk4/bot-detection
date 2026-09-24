"""
Production Configuration for Silkmoon Bot & Fraud Detection Service
Adheres to 12-factor application design, configurable via environment variables.
"""

import os
from typing import List


def _env_int(name: str, default: int, minimum: int, maximum: int = None) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an integer, got {raw_value!r}") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be >= {minimum}{upper}, got {value}")
    return value


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a number, got {raw_value!r}") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}, got {value}")
    return value


class Settings:
    PROJECT_NAME: str = "DATACAT Bot Detection API"
    VERSION: str = "1.0.0"

    # Server binding
    HOST: str = os.getenv("BOT_API_HOST", "0.0.0.0")
    PORT: int = _env_int("BOT_API_PORT", 8000, 1, 65535)
    # Fallback buffering and rate limiting are process-local. Running more than
    # one worker would split those guarantees across processes.
    WORKERS: int = _env_int("BOT_API_WORKERS", 1, 1, 1)

    # Model paths
    WEIGHTS_DIR: str = os.getenv(
        "BOT_WEIGHTS_DIR",
        os.path.join(os.path.dirname(__file__), "..", "core_ml", "weights")
    )

    # Security & Networking
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv("BOT_CORS_ORIGINS", "*").split(",")
        if origin.strip()
    ]
    ADMIN_TOKEN: str = os.getenv("BOT_ADMIN_TOKEN", "").strip()
    READ_TOKEN: str = (os.getenv("BOT_READ_TOKEN") or ADMIN_TOKEN).strip()
    TRUST_PROXY_HEADERS: bool = os.getenv("BOT_TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")
    TRUSTED_PROXIES: List[str] = [
        proxy.strip()
        for proxy in os.getenv("BOT_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",")
        if proxy.strip()
    ]

    # Classification Thresholds
    THRESHOLD: float = _env_float("BOT_DECISION_THRESHOLD", 0.70, 0.0, 1.0)
    SUSPECT_THRESHOLD: float = _env_float("BOT_SUSPECT_THRESHOLD", 0.45, 0.0, THRESHOLD)
    MIN_MOUSE_POINTS_FOR_BOT: int = _env_int("BOT_MIN_MOUSE_POINTS_FOR_BOT", 24, 0)

    # Capacity limits & Protection
    MAX_BUFFER_SIZE: int = _env_int("BOT_MAX_TELEMETRY_BUFFER", 1000, 1)
    MAX_TELEMETRY_RETRIES: int = _env_int("BOT_MAX_TELEMETRY_RETRIES", 3, 0, 100)
    MAINTENANCE_INTERVAL_SECONDS: int = _env_int("BOT_MAINTENANCE_INTERVAL_SECONDS", 10, 1, 3600)
    HEALTH_CACHE_SECONDS: int = _env_int("BOT_HEALTH_CACHE_SECONDS", 10, 0, 300)
    RATE_LIMIT_PER_MINUTE: int = _env_int("BOT_RATE_LIMIT_PER_MINUTE", 240, 0)
    MAX_PAYLOAD_BYTES: int = _env_int("BOT_MAX_PAYLOAD_BYTES", 262144, 1024)
    DATA_RETENTION_DAYS: int = _env_int("BOT_DATA_RETENTION_DAYS", 30, 1, 3650)


settings = Settings()
