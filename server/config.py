"""Application configuration loaded from environment variables.

Single source of truth for all settings. Validated at import time through Pydantic.
Uses the Factory pattern: AppConfig is a singleton cached by get_config().

Azure CosmosDB for PostgreSQL connection strings use SSL (sslmode=require).
Passwords with special characters must be URL-encoded in the connection URL.
"""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
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

    # --- Azure CosmosDB for PostgreSQL ---
    # Accepts both AZURE_COSMOSDB_PG_URL and DATABASE_URL (legacy)
    azure_cosmosdb_pg_url: str = Field(
        default="",
        alias="azure_cosmosdb_pg_url",
    )
    database_url: str = Field(default="")
    db_pool_min_size: int = 2
    db_pool_max_size: int = 10

    @model_validator(mode="after")
    def resolve_database_url(self) -> "AppConfig":
        """Use azure_cosmosdb_pg_url if set, otherwise fall back to database_url."""
        if self.azure_cosmosdb_pg_url and len(self.azure_cosmosdb_pg_url) > 0:
            self.database_url = self.azure_cosmosdb_pg_url
        if not self.database_url:
            raise ValueError(
                "Either azure_cosmosdb_pg_url or database_url must be provided"
            )
        return self

    @field_validator("database_url")
    @classmethod
    def validate_postgres_url(cls, value: str) -> str:
        if not value:
            return value  # will be caught by model_validator if both are empty
        if not value.startswith(("postgresql://", "postgres://")):
            raise ValueError("database_url must start with postgresql:// or postgres://")
        return value

    # --- Azure Blob Storage ---
    azure_storage_connection_string: str = Field(..., min_length=20)
    azure_storage_container: str = "resume-archive"
    template_blob_path: str = "templates/master_resume.tex"

    # --- Blob Storage — Versioned resume path structure ---
    # Path template for archived resumes:
    #   resumes/{company_slug}/{role_slug}/{company}_{role}_{session_key}/
    blob_resumes_prefix: str = "resumes"
    blob_templates_prefix: str = "templates"

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

    @field_validator("cors_origins")
    @classmethod
    def split_origins(cls, value: str) -> list[str]:
        return [origin.strip() for origin in value.split(",") if origin.strip()]

    @property
    def database_url_final(self) -> str:
        """The resolved database URL, guaranteed non-empty after validation."""
        return self.database_url

    def build_resume_blob_path(
        self,
        company_slug: str,
        role_slug: str,
        session_key: str,
    ) -> str:
        """Build a versioned blob path for a generated resume.

        Example:
            resumes/tata-consultancy-services/ai-ml-engineer/tcs_aiml_abc123/
        """
        return (
            f"{self.blob_resumes_prefix}/{company_slug}/{role_slug}/"
            f"{company_slug}_{role_slug}_{session_key}"
        )

    def as_dict(self) -> dict:
        """Return config as plain dict for dependency injection."""
        return self.model_dump()


@lru_cache
def get_config() -> AppConfig:
    """Singleton config instance. Cached to avoid re-parsing env vars."""
    return AppConfig()
