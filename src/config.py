from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coros_email: str
    coros_password: str
    coros_region: str = "cn"

    anthropic_api_key: str

    ntfy_topic: str
    db_url: str = "sqlite:///pacecoach.db"
    poll_interval_minutes: int = 10

    class Config:
        env_file = ".env"


settings = Settings()
