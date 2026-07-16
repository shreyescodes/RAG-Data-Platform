from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql://postgres:password123@localhost:5432/RAG"
    
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

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
