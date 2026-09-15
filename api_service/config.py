"""
Production Configuration for Silkmoon Bot & Fraud Detection Service
Adheres to 12-factor application design, configurable via environment variables.
"""

import os
from typing import List


class Settings:
    PROJECT_NAME: str = "Silkmoon Bot & Fraud Detection Core API"
    VERSION: str = "1.0.0"

    # Server binding
    HOST: str = os.getenv("BOT_API_HOST", "0.0.0.0")
    PORT: int = int(os.getenv("BOT_API_PORT", "8000"))
    WORKERS: int = int(os.getenv("BOT_API_WORKERS", "1"))

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
    TRUST_PROXY_HEADERS: bool = os.getenv("BOT_TRUST_PROXY_HEADERS", "false").lower() in ("1", "true", "yes")
    TRUSTED_PROXIES: List[str] = [
        proxy.strip()
        for proxy in os.getenv("BOT_TRUSTED_PROXIES", "127.0.0.1/32,::1/128").split(",")
        if proxy.strip()
    ]

    # Classification Thresholds
    THRESHOLD: float = float(os.getenv("BOT_DECISION_THRESHOLD", "0.70"))
    SUSPECT_THRESHOLD: float = float(os.getenv("BOT_SUSPECT_THRESHOLD", "0.45"))

    # Capacity limits & Protection
    MAX_BUFFER_SIZE: int = int(os.getenv("BOT_MAX_TELEMETRY_BUFFER", "1000"))
    MAX_GRAPH_SESSIONS: int = int(os.getenv("BOT_MAX_GRAPH_SESSIONS", "10000"))
    RATE_LIMIT_PER_MINUTE: int = int(os.getenv("BOT_RATE_LIMIT_PER_MINUTE", "240"))
    MAX_PAYLOAD_BYTES: int = int(os.getenv("BOT_MAX_PAYLOAD_BYTES", "262144"))


settings = Settings()
