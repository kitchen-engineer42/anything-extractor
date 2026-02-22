"""Application configuration from environment variables."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API keys
    siliconflow_api_key: str = ""
    siliconflow_base_url: str = "https://api.siliconflow.cn/v1"
    mineru_api_key: str = ""

    # LLM models
    ae_worker_model: str = "Qwen/Qwen3-VL-235B-A22B-Instruct"
    ae_builder_model: str = "Pro/zai-org/GLM-5"
    ae_observer_model: str = "Pro/moonshotai/Kimi-K2.5"
    ae_observer_vision_model: str = "Qwen/Qwen3-VL-235B-A22B-Instruct"

    # Model downgrade tiers
    ae_worker_model_tiers: str = (
        "Qwen/Qwen3-VL-235B-A22B-Instruct,"
        "Qwen/Qwen3-32B,"
        "Qwen/Qwen3-14B,"
        "Qwen/Qwen3-8B"
    )

    # Database (defaults to SQLite if PostgreSQL not configured)
    ae_database_url: str = "sqlite:///./data/anything_extractor.db"
    ae_redis_url: str = ""  # Optional; empty = use in-memory cache

    # Language
    ae_language: Literal["en", "zh", "bilingual"] = "bilingual"

    # Evolution
    max_iterations: int = 20

    # Paths
    ae_workflows_dir: str = "./workflows"
    ae_data_dir: str = "./data"

    @property
    def worker_model_tiers(self) -> list[str]:
        return [t.strip() for t in self.ae_worker_model_tiers.split(",") if t.strip()]

    @property
    def workflows_path(self) -> Path:
        return Path(self.ae_workflows_dir).resolve()

    @property
    def data_path(self) -> Path:
        return Path(self.ae_data_dir).resolve()

    @property
    def input_path(self) -> Path:
        return self.data_path / "input"

    @property
    def output_path(self) -> Path:
        return self.data_path / "output"


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
