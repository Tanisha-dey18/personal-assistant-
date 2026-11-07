"""Central configuration. Every value can be overridden with an environment variable
(or a line in backend/.env). Nothing secret is hardcoded here."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SECRET = "dev-only-change-me"
BASE_DIR = Path(__file__).resolve().parents[2]  # the backend/ folder


def _abs(p: str) -> str:
    """Resolve ./relative paths against backend/ so the server works from any working directory."""
    path = Path(p)
    return str(path if path.is_absolute() else (BASE_DIR / path).resolve())


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(BASE_DIR / ".env"), extra="ignore")

    APP_NAME: str = "ASTRA"
    ENV: str = "development"  # development | production
    SECRET_KEY: str = DEFAULT_SECRET  # signs JWTs
    ENCRYPTION_KEY: str = ""  # Fernet key for sensitive data; derived from SECRET_KEY if empty
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7
    ALLOW_REGISTRATION: bool = True  # turn off after you create your account

    # URLs
    FRONTEND_URL: str = "http://localhost:5173"
    BACKEND_PUBLIC_URL: str = "http://localhost:8000"
    CORS_ORIGINS: str = "http://localhost:5173,http://127.0.0.1:5173"

    # Storage. SQLite + embedded Qdrant are used automatically when the URLs are empty,
    # so the app runs on a laptop without Docker. Use Postgres/Qdrant/Redis in production.
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/astra.db"
    QDRANT_URL: str = ""
    QDRANT_API_KEY: str = ""
    QDRANT_PATH: str = "./data/qdrant"
    REDIS_URL: str = ""
    UPLOAD_DIR: str = "./data/uploads"
    MAX_UPLOAD_MB: int = 25

    # AI provider (any OpenAI-compatible API works via OPENAI_BASE_URL)
    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    CHAT_MODEL: str = "gpt-4.1-mini"
    FAST_MODEL: str = "gpt-4.1-mini"  # memory extraction, titles, summaries
    AVAILABLE_MODELS: str = "gpt-4.1-mini,gpt-4.1,gpt-4o,gpt-4o-mini,gpt-5,gpt-5-mini"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    EMBEDDING_DIM: int = 1536
    STT_MODEL: str = "gpt-4o-mini-transcribe"
    TTS_MODEL: str = "gpt-4o-mini-tts"
    DEFAULT_VOICE: str = "nova"

    # Tools / integrations
    TAVILY_API_KEY: str = ""
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""

    # Limits
    RATE_LIMIT_PER_MINUTE: int = 40
    AUTH_RATE_LIMIT_PER_MINUTE: int = 10
    PROACTIVE_INTERVAL_SECONDS: int = 60

    @property
    def cors_origins(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def available_models(self) -> list[str]:
        return [m.strip() for m in self.AVAILABLE_MODELS.split(",") if m.strip()]

    @property
    def async_database_url(self) -> str:
        url = self.DATABASE_URL
        # Render/Railway give postgres:// URLs; SQLAlchemy async needs the asyncpg driver.
        if url.startswith("sqlite") and ":///" in url:
            prefix, path = url.split(":///", 1)
            if path not in ("", ":memory:"):
                url = f"{prefix}:///{_abs(path)}".replace("\\", "/")
        if url.startswith("postgres://"):
            url = "postgresql+asyncpg://" + url[len("postgres://"):]
        elif url.startswith("postgresql://"):
            url = "postgresql+asyncpg://" + url[len("postgresql://"):]
        # Neon/Supabase URLs use libpq params (sslmode, channel_binding) that asyncpg rejects.
        if url.startswith("postgresql+asyncpg://") and "?" in url:
            from urllib.parse import parse_qsl, urlencode

            base, query = url.split("?", 1)
            params = dict(parse_qsl(query))
            sslmode = params.pop("sslmode", None)
            params.pop("channel_binding", None)
            if sslmode and sslmode != "disable" and "ssl" not in params:
                params["ssl"] = "require"
            url = base + ("?" + urlencode(params) if params else "")
        return url

    @property
    def qdrant_path(self) -> str:
        return _abs(self.QDRANT_PATH)

    @property
    def google_redirect_uri(self) -> str:
        return f"{self.BACKEND_PUBLIC_URL.rstrip('/')}/api/integrations/google/callback"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    if s.ENV == "production" and s.SECRET_KEY == DEFAULT_SECRET:
        raise RuntimeError("Set a strong SECRET_KEY before running in production.")
    return s


settings = get_settings()
