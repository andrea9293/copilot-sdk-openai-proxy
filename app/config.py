import os

from dotenv import load_dotenv

load_dotenv()


class Settings:
    host: str = os.environ.get("HOST", "0.0.0.0")
    port: int = int(os.environ.get("PORT", "8000"))
    log_level: str = os.environ.get("LOG_LEVEL", "info")


settings = Settings()
