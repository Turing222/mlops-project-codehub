from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache
from typing import Optional

class Settings(BaseSettings):
    """
    Application Settings configuration class.
    Inherits from BaseSettings to automatically load environment variables.
    """

    # --- Project Info ---
    PROJECT_NAME: str = "Obsidian Mentor AI"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # --- Database Configuration (PostgreSQL) ---
    # Field(...) indicates this field is required and has no default value.
    # If not found in env, the app will crash at startup (Fail Fast principle).
    POSTGRES_USER: str
    POSTGRES_PASSWORD: str
    POSTGRES_SERVER: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "mentor_ai"

    # --- LLM & AI Configuration ---
    # Optional[str] means it can be None (e.g., if using local LLM only).
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    
    # Path to your Obsidian Vault (Local Volume Mount)
    OBSIDIAN_VAULT_PATH: str = "/data/obsidian"

    # --- Security ---
    # Secret key for JWT token generation (FastAPI Users)
    SECRET_KEY: str

    # Configuration for loading .env file
    model_config = SettingsConfigDict(
        env_file=".env", 
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    @property
    def database_url(self) -> str:
        """
        Constructs the SQLAlchemy connection string dynamically.
        Format: postgresql+asyncpg://user:password@server:port/db
        """
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_SERVER}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

# --- Singleton Pattern Implementation ---
@lru_cache
def get_settings() -> Settings:
    """
    Creates a singleton instance of Settings.
    lru_cache ensures we read the .env file only once per execution context.
    """
    return Settings()

# Global settings instance
settings = get_settings()