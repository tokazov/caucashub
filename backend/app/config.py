from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://caucashub:caucashub@localhost/caucashub"
    SECRET_KEY: str = "caucashub-secret-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # 7 days
    GEMINI_API_KEY: str = ""
    TELEGRAM_BOT_TOKEN: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
