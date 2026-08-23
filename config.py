# config.py
from pathlib import Path
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Soulseek
    soulseek_user: str = "audio_archivist"
    soulseek_pass: str = ""
    
    # VK
    vk_timeout_sec: int = 10
    vk_token: str = ""
    
    # Directories
    data_dir: Path = Path("./data")
    downloads_dir: Path = Path("./downloads")
    db_path: Path = Path("./data/jobs.db")   # <-- ADD THIS
    
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"   # <-- IMPORTANT: ignore extra fields in .env

settings = Settings()

# Create directories
settings.data_dir.mkdir(exist_ok=True)
settings.downloads_dir.mkdir(exist_ok=True)