from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    soulseek_user: str
    soulseek_pass: str
    data_dir: str = "./data"
    vk_timeout_sec: int = 10

    class Config:
        env_file = ".env"

settings = Settings()