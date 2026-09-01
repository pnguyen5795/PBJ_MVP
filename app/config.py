from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def env_flag(name: str, default: bool = False) -> bool:
    """Parse an explicit environment feature flag without truthy-string surprises."""
    fallback = "true" if default else "false"
    return os.getenv(name, fallback).strip().casefold() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    root_dir: Path = ROOT_DIR
    data_dir: Path = ROOT_DIR / os.getenv("APP_DATA_DIR", "data")
    agent_default_model: str = os.getenv("PBJ_AGENT_MODEL", "gpt-5.6-luna")
    editing_agent_model: str = os.getenv("PBJ_EDITING_AGENT_MODEL", os.getenv("PBJ_AGENT_MODEL", "gpt-5.6-luna"))
    repair_agent_model: str = os.getenv("PBJ_REPAIR_AGENT_MODEL", os.getenv("PBJ_AGENT_MODEL", "gpt-5.6-luna"))
    learning_agent_model: str = os.getenv("PBJ_LEARNING_AGENT_MODEL", os.getenv("PBJ_AGENT_MODEL", "gpt-5.6-luna"))
    agent_reasoning_effort: str = os.getenv("PBJ_AGENT_REASONING_EFFORT", "medium")
    # Compatibility alias for older provenance consumers. New OpenAI calls use
    # the explicit role settings above.
    openai_model: str = os.getenv("PBJ_EDITING_AGENT_MODEL", os.getenv("PBJ_AGENT_MODEL", "gpt-5.6-luna"))
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.7-flash")
    twelve_labs_model: str = os.getenv("TWELVE_LABS_MODEL", "pegasus1.5")
    access_code: str = os.getenv("PBJ_ACCESS_CODE", "")
    owner_code: str = os.getenv("PBJ_OWNER_CODE", "")
    session_secret: str = os.getenv("PBJ_SESSION_SECRET", "pbj-local-development-only")
    session_days: int = 7
    max_upload_batch_bytes: int = 2 * 1024 * 1024 * 1024
    openreel_origin: str = os.getenv("PBJ_OPENREEL_ORIGIN", "").rstrip("/")
    openreel_port: int = int(os.getenv("PBJ_OPENREEL_PORT", "5173"))

    @property
    def templates_dir(self) -> Path:
        return self.root_dir / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return self.root_dir / "app" / "static"


settings = Settings()


def save_local_settings(values):
    """Update only explicitly permitted entries in the ignored local .env."""
    allowed = (
        "OPENAI_API_KEY", "GEMINI_API_KEY", "TWELVE_LABS_API_KEY",
        "PBJ_ACCESS_CODE", "PBJ_OWNER_CODE", "PBJ_SESSION_SECRET", "PBJ_HTTPS_ONLY",
    )
    env_path = ROOT_DIR / ".env"
    lines = env_path.read_text().splitlines() if env_path.exists() else []
    positions = {}
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        if key in allowed:
            positions[key] = index
    for key in allowed:
        value = (values.get(key) or "").strip()
        if not value:
            continue
        replacement = "%s=%s" % (key, value)
        if key in positions:
            lines[positions[key]] = replacement
        else:
            positions[key] = len(lines)
            lines.append(replacement)
        os.environ[key] = value
    temporary = env_path.parent / ".env.tmp"
    temporary.write_text("\n".join(lines) + "\n")
    temporary.replace(env_path)


def save_api_keys(values):
    save_local_settings(values)
