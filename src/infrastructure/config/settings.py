from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # --- Database ---
    database_url: str = "sqlite:///./data/networking.db"

    # --- Redis / Celery ---
    redis_url: str = "redis://localhost:6379/0"
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/1"

    # --- General ---
    default_retention_days: int = 180
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # --- Phase 2: Scraping ---
    linkedin_li_at_cookie: str = ""
    scrape_delay_min: float = 1.0        # seconds between requests (min)
    scrape_delay_max: float = 5.0        # seconds between requests (max)
    linkedin_daily_limit: int = 80       # max LinkedIn profiles per day
    proxy_file: str = "./data/proxies.txt"
    screenshot_dir: str = "./data/screenshots"
    headless: bool = True                # run Playwright in headless mode

    # --- Phase 3: LLM Extraction ---
    llm_provider: str = "ollama"
    llm_model: str = "ollama/llama3.1:8b"
    llm_base_url: str = "http://localhost:11434"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4000

    # --- Phase 3: Enrichment APIs ---
    apollo_api_key: str = ""
    apollo_monthly_budget: int = 10000
    hunter_api_key: str = ""
    hunter_monthly_budget: int = 25
    enrichment_primary: str = "apollo"
    enrichment_fallback: str = "hunter"
    enrich_phone: bool = False

    # --- Phase 4: Email / SMTP ---
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    sender_name: str = "Networking Engine"
    sender_email: str = ""
    daily_email_limit: int = 50
    daily_linkedin_limit: int = 25

    # --- Phase 4: Business Hours ---
    business_hours_start: int = 9
    business_hours_end: int = 18
    timezone: str = "America/New_York"
    business_days: str = "mon,tue,wed,thu,fri"

    # --- Phase 4: Compliance ---
    respect_robots: bool = True
    privacy_notice_url: str = "https://yoursite.com/privacy"
    physical_address: str = "Your Address Here"

    # --- Phase 4: RAG ---
    embedding_model: str = "all-MiniLM-L6-v2"
    chroma_persist_dir: str = "./data/chroma"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
