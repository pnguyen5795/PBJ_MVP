from dataclasses import dataclass, field
from pathlib import Path
import os

from dotenv import load_dotenv

from .security import MAX_SECRET_BYTES


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
LOCAL_SESSION_SECRET = "pbj-local-development-only"


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
    twelve_labs_model: str = os.getenv("TWELVE_LABS_MODEL", "pegasus1.5")
    access_code: str = os.getenv("PBJ_ACCESS_CODE", "")
    owner_code: str = os.getenv("PBJ_OWNER_CODE", "")
    session_secret: str = os.getenv("PBJ_SESSION_SECRET", LOCAL_SESSION_SECRET)
    session_days: int = 7
    max_upload_batch_bytes: int = 2 * 1024 * 1024 * 1024
    hosted_mode: bool = field(default_factory=lambda: env_flag("PBJ_HOSTED_MODE"))
    https_only: bool = env_flag("PBJ_HTTPS_ONLY")
    shared_workspace: bool = env_flag("PBJ_SHARED_WORKSPACE")
    shared_workspace_id: str = os.getenv("PBJ_SHARED_WORKSPACE_ID", "pbj-private-workspace")

    def __post_init__(self) -> None:
        # RENDER is a read-only platform marker. A missing, false, or malformed
        # application flag must never downgrade a Render service into local mode.
        if env_flag("RENDER") and not self.hosted_mode:
            object.__setattr__(self, "hosted_mode", True)

    @property
    def templates_dir(self) -> Path:
        return self.root_dir / "app" / "templates"

    @property
    def static_dir(self) -> Path:
        return self.root_dir / "app" / "static"


def validate_settings(candidate: Settings) -> None:
    """Reject unsafe hosted configuration before the web process starts."""
    for name, value in (
        ("PBJ_ACCESS_CODE", candidate.access_code),
        ("PBJ_OWNER_CODE", candidate.owner_code),
    ):
        if not value:
            continue
        try:
            encoded = value.encode("utf-8")
        except (AttributeError, UnicodeError) as exc:
            raise RuntimeError(f"{name} must be valid UTF-8 text.") from exc
        if len(encoded) > MAX_SECRET_BYTES:
            raise RuntimeError(
                f"{name} must be at most {MAX_SECRET_BYTES} bytes when UTF-8 encoded."
            )
    if not candidate.hosted_mode:
        return
    if not candidate.access_code:
        raise RuntimeError("PBJ_ACCESS_CODE is required when PBJ_HOSTED_MODE=true.")
    if (
        candidate.session_secret == LOCAL_SESSION_SECRET
        or len(candidate.session_secret.encode("utf-8")) < 32
    ):
        raise RuntimeError(
            "PBJ_SESSION_SECRET must be a unique value of at least 32 bytes "
            "when PBJ_HOSTED_MODE=true."
        )
    if not candidate.https_only:
        raise RuntimeError("PBJ_HTTPS_ONLY=true is required when PBJ_HOSTED_MODE=true.")


settings = Settings()
validate_settings(settings)


def save_local_settings(values):
    """Update only explicitly permitted entries in the ignored local .env."""
    if settings.hosted_mode:
        raise RuntimeError("Hosted secrets must be changed in the Render dashboard.")
    allowed = (
        "OPENAI_API_KEY", "TWELVE_LABS_API_KEY",
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
