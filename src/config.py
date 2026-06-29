from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    coros_email: str
    coros_password: str
    coros_region: str = "cn"

    llm_api_key: str
    llm_base_url: str
    llm_model: str

    ntfy_topic: str
    db_url: str = "sqlite:///pacecoach.db"
    poll_interval_minutes: int = 10

    model_config = {"env_file": [".env", ".env.local"], "extra": "ignore"}


settings = Settings()
