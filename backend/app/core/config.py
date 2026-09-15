from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Personal Healthcare API"
    ENVIRONMENT: str = "development"
    DEBUG: bool = True
    API_V1_STR: str = "/api/v1"

    # Database
    DATABASE_URL: str = (
        "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_health"
    )

    # Supabase Auth
    SUPABASE_URL: str = "https://your-project.supabase.co"
    SUPABASE_KEY: str = "your-anon-key"
    SUPABASE_JWT_SECRET: str = ""  # Deprecated: uses ES256 JWKS

    # S3 Object Storage
    S3_ENDPOINT_URL: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET_NAME: str = "medical-documents"

    # LLM Provider Gateway Configuration
    LLM_PROVIDER: str = "mock"
    LLM_MODEL: str = "gpt-4o-mini"
    LLM_API_KEY: str = ""
    LLM_TIMEOUT_SECONDS: float = 10.0
    LLM_MAX_RETRIES: int = 2

    @property
    def supabase_issuer(self) -> str:
        base = self.SUPABASE_URL.rstrip("/")
        return f"{base}/auth/v1"

    @property
    def supabase_jwks_url(self) -> str:
        base = self.SUPABASE_URL.rstrip("/")
        return f"{base}/auth/v1/.well-known/jwks.json"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
