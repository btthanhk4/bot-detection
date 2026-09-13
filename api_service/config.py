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
    WORKERS: int = int(os.getenv("BOT_API_WORKERS", "4"))

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

    # Classification Thresholds
    THRESHOLD: float = float(os.getenv("BOT_DECISION_THRESHOLD", "0.50"))

    # Capacity limits
    MAX_BUFFER_SIZE: int = int(os.getenv("BOT_MAX_TELEMETRY_BUFFER", "1000"))
    MAX_GRAPH_SESSIONS: int = int(os.getenv("BOT_MAX_GRAPH_SESSIONS", "10000"))


settings = Settings()
