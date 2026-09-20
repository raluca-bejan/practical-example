import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    api_key: str = field(default="", repr=False)
    model: str = "gpt-4.1-mini"

    @classmethod
    def load(cls, path: Path = ROOT / ".env") -> "Settings":
        local = dotenv_values(path) if path.exists() else {}
        return cls(
            api_key=os.environ.get("OPENAI_API_KEY", local.get("OPENAI_API_KEY") or "").strip(),
            model=os.environ.get("OPENAI_MODEL", local.get("OPENAI_MODEL") or "gpt-4.1-mini").strip(),
        )
