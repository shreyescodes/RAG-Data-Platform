from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Database — no default: must be explicitly set via .env or environment variable
    DATABASE_URL: str

    # External APIs
    OPENAI_API_KEY: str = ""
    SEC_EDGAR_API_KEY: str = ""

    # FAISS Configuration
    FAISS_INDEX_PATH: str = "data/faiss_index"
    FAISS_DIMENSION: int = 1536

    # Models
    LLM_MODEL: str = "gpt-4o-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"

    # Server Configuration
    API_HOST: str = "0.0.0.0"
    API_PORT: int = 8000

    # Security
    # Comma-separated list of allowed CORS origins, e.g. "http://localhost:5173,https://app.example.com"
    ALLOWED_ORIGINS: str = "http://localhost:5173"
    # API key required in X-API-Key header for protected endpoints.
    # Set to a long random secret; leave empty to disable key-auth (dev only).
    API_KEY: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def allowed_origins_list(self) -> list[str]:
        """Parse the comma-separated ALLOWED_ORIGINS string into a list."""
        return [o.strip() for o in self.ALLOWED_ORIGINS.split(",") if o.strip()]


settings = Settings()
