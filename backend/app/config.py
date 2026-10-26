from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    pinecone_api_key: str = ""
    pinecone_index_name: str = "rag-stock-reports"
    pinecone_cloud: str = "aws"
    pinecone_region: str = "us-east-1"

    openai_api_key: str = ""
    openai_embedding_model: str = "text-embedding-3-small"
    openai_llm_model: str = "gpt-5.6"
    embedding_dimensions: int = 1536

    data_dir: Path = BACKEND_DIR / "data"
    uploads_dir: Path = BACKEND_DIR / "uploads"
    sqlite_path: Path = BACKEND_DIR / "data" / "rag_stock.db"

    # Pricing used for learning estimates (USD per 1M tokens)
    embedding_usd_per_1m: float = 0.02
    llm_input_usd_per_1m: float = 4.00
    llm_output_usd_per_1m: float = 20.00


settings = Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
settings.uploads_dir.mkdir(parents=True, exist_ok=True)
