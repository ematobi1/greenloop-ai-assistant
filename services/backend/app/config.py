from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.ai.providers.ollama import validate_loopback_url

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{(REPO_ROOT / 'data' / 'greenloop.db').as_posix()}"
LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="GREENLOOP_",
        env_file=REPO_ROOT / ".env",
        extra="ignore",
    )

    env: str = "development"
    version: str = "0.2.0"
    log_level: str = "INFO"
    database_url: str = DEFAULT_DATABASE_URL
    api_token_hash: str = ""
    allowed_hosts: list[str] = ["127.0.0.1", "localhost"]
    cors_origins: list[str] = ["http://127.0.0.1:5173", "http://localhost:5173"]

    ai_default_provider: str = "claude_cli"
    ai_enable_mock: bool = False
    ai_prompt_version: str = "v1"
    ai_timeout_seconds: float = Field(default=120.0, gt=0, le=600)
    ai_max_retries: int = Field(default=1, ge=0, le=3)
    ai_max_output_tokens: int = Field(default=2048, ge=16, le=32000)
    ai_temperature: float | None = Field(default=None, ge=0, le=2)
    ai_context_token_limit: int = Field(default=8000, ge=256)
    ai_history_message_limit: int = Field(default=40, ge=1, le=500)
    ai_max_message_chars: int = Field(default=8000, ge=1, le=100000)

    claude_cli_command: list[str] = ["claude"]
    claude_cli_model: str = ""
    claude_cli_env_passthrough: list[str] = []
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "qwen3.5:latest"

    @field_validator("ollama_base_url")
    @classmethod
    def validate_ollama_url(cls, value: str) -> str:
        return validate_loopback_url(value)

    @field_validator("claude_cli_command")
    @classmethod
    def validate_claude_command(cls, value: list[str]) -> list[str]:
        if not value or not value[0].strip():
            raise ValueError("claude_cli_command must not be empty")
        return value

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, value: str) -> str:
        upper = value.upper()
        if upper not in LOG_LEVELS:
            raise ValueError(f"log_level must be one of {sorted(LOG_LEVELS)}")
        return upper


@lru_cache
def get_settings() -> Settings:
    return Settings()
