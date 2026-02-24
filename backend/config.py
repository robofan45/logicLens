from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    LLM_PROVIDER: str = "openai"
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = ""
    OPENAI_MODEL: str = "gpt-4o"
    MOCK_LLM: bool = False

    AZURE_OPENAI_ENDPOINT: str = ""
    AZURE_OPENAI_API_KEY: str = ""
    AZURE_OPENAI_DEPLOYMENT: str = "gpt-4o"
    AZURE_OPENAI_API_VERSION: str = "2024-12-01-preview"

    YOLO_MODEL_PATH: str = "models/yolo/best.pt"
    YOLO_BASE_MODEL: str = "rtdetr-l.pt"
    YOLO_CONFIDENCE_THRESHOLD: float = 0.15
    YOLO_IOU_THRESHOLD: float = 0.45
    YOLO_IMG_SIZE: int = 960
    YOLO_MAX_DETECTIONS: int = 300
    YOLO_ENABLE_TTA: bool = True
    YOLO_HEURISTIC_MIN_AREA: int = 18
    YOLO_HEURISTIC_MAX_AREA_RATIO: float = 0.10
    YOLO_HEURISTIC_MAX_BOXES: int = 120
    YOLO_HEURISTIC_OVERLAP_IOU: float = 0.40

    SESSION_TTL_SECONDS: int = 3600
    BLUR_THRESHOLD: float = 15.0


@lru_cache()
def get_settings() -> Settings:
    return Settings()
