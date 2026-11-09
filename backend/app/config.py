"""Runtime configuration, read from the environment."""
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


@dataclass(frozen=True)
class Settings:
    db_path: str = field(default_factory=lambda: os.getenv("HR_DB_PATH", str(DATA_DIR / "hr.db")))
    # Random per process unless set, so no signing secret ever lives in the repo.
    token_secret: str = field(default_factory=lambda: os.getenv("HR_TOKEN_SECRET") or secrets.token_hex(32))
    token_ttl_seconds: int = 3600
    llm_mode: str = field(default_factory=lambda: os.getenv("HR_LLM_MODE", "rules"))  # rules | ollama
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    chat_model: str = field(default_factory=lambda: os.getenv("HR_CHAT_MODEL", "qwen2.5:3b"))
    embed_model: str = field(default_factory=lambda: os.getenv("HR_EMBED_MODEL", "nomic-embed-text"))
    demo_password: str = field(default_factory=lambda: os.getenv("HR_DEMO_PASSWORD", "demo-only"))
    static_dir: str = field(default_factory=lambda: os.getenv("HR_STATIC_DIR", ""))
