from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AUTO_RESEARCH_", extra="ignore")

    app_name: str = "AutoEarningsResearch"
    data_dir: Path = Path("data")
    db_path: Path = Path("data/app.db")
    run_dir: Path = Path("data/runs")
    user_agent: str = "AutoEarningsResearch/1.0 (portfolio project; contact: demo@example.com)"

    max_iterations: int = 5
    target_score: int = 85
    min_improvement: int = 2
    patience: int = 2
    openai_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("AUTO_RESEARCH_OPENAI_API_KEY", "OPENAI_API_KEY"),
    )
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5.4"
    openai_reasoning_effort: str = "medium"
    openai_timeout_seconds: float = 45.0


settings = Settings()
