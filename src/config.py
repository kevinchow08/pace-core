from pydantic_settings import BaseSettings, PydanticBaseSettingsSource


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

    jwt_secret_key: str
    jwt_expire_minutes: int = 60 * 24 * 7  # 7天

    model_config = {"env_file": [".env", ".env.local"], "extra": "ignore"}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ):
        # pydantic-settings 默认优先级：系统环境变量 > .env 文件。
        # 这里反过来：.env/.env.local 优先，系统环境变量兜底。
        # 原因：编辑器/终端工具（如 VS Code）可能把项目自己的 .env 注入成 shell
        # 环境变量，一旦发生就会一直覆盖 .env.local 的本地开发配置，难以排查。
        # 让 dotenv 文件优先，配置行为只取决于文件内容，不受运行环境里
        # 意外存在的同名变量影响。
        return init_settings, dotenv_settings, env_settings, file_secret_settings


settings = Settings()
