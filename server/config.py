"""Application configuration loaded from environment variables.

Single source of truth for all settings. Validated at import time through Pydantic.
Uses the Factory pattern: AppConfig is a singleton cached by get_config().

DATABASE_URL is a plain Postgres connection string — works with Supabase,
Azure CosmosDB for PostgreSQL, or any other Postgres provider that requires
SSL (sslmode=require). Passwords with special characters must be
URL-encoded in the connection URL.

There is no separate blob/object storage — generated PDFs and LaTeX source
are stored directly in the `sessions` table (see migrations/002_*.sql), so
the whole app only needs one database connection string.
"""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application-wide configuration. All values sourced from env vars."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Gemini ---
    gemini_api_key: str = Field(..., min_length=10)
    gemini_api_key2: str = Field(default="", min_length=0)
    gemini_api_key3: str = Field(default="", min_length=0)
    gemini_api_key4: str = Field(default="", min_length=0)
    gemini_api_key5: str = Field(default="", min_length=0)
    gemini_api_key6: str = Field(default="", min_length=0)
    gemini_model: str = "gemini-2.5-pro"
    gemini_model_fallback: str = "gemini-2.5-flash"

    # --- PostgreSQL (Supabase, or any Postgres provider) ---
    database_url: str = Field(..., min_length=10)
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    @field_validator("database_url")
    @classmethod
    def validate_postgres_url(cls, value: str) -> str:
        if not value.startswith(("postgresql://", "postgres://")):
            raise ValueError("database_url must start with postgresql:// or postgres://")
        return value

    # --- Server ---
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Auth ---
    auth_passcode_hash: str = Field(..., min_length=10)

    # --- LangGraph ---
    session_ttl_hours: int = 6
    langgraph_checkpoint_table: str = "langgraph_checkpoints"

    # --- LaTeX ---
    pdflatex_timeout_seconds: int = 30
    latex_fix_max_retries: int = 2
    latex_fix_retry_delay_seconds: float = 0.5

    # --- Caching ---
    project_bullet_cache_ttl_days: int = 90
    draft_cache_ttl_days: int = 7

    # --- LaTeX MCP (external LaTeX → PDF compiler) ---
    # REST endpoint documented in custom_latex_mcp.md: POST {latex_mcp_url}/api/convert
    latex_mcp_url: str = "http://20.212.83.231"
    latex_mcp_api_key: str = Field(..., min_length=10)
    latex_mcp_timeout_seconds: int = 30
    latex_mcp_max_retries: int = 2

    @field_validator("cors_origins")
    @classmethod
    def split_origins(cls, value: str) -> list[str]:
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    def as_dict(self) -> dict:
        """Return config as plain dict for dependency injection."""
        return self.model_dump()


@lru_cache
def get_config() -> AppConfig:
    """Singleton config instance. Cached to avoid re-parsing env vars."""
    return AppConfig()
