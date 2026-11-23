"""Settings from environment variables, optionally loaded from a local .env file.

Keys are never logged or written anywhere by the engine.
"""

import os
from pathlib import Path

# Presets: (model id, RPM, RPD). Conservative free-tier values reported around Oct 2026;
# they change, so users should check Google AI Studio and override with GEMINI_RPM / GEMINI_RPD.
GEMINI_PRESETS = {
    "quality": ("gemini-flash-latest", 5, 20),
    "volume": ("gemini-flash-lite-latest", 15, 500),
}
DEFAULT_PRESET = "quality"


def load_dotenv(path: str | Path = ".env") -> None:
    """Minimal .env reader: KEY=VALUE lines; existing environment variables win."""
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def gemini_settings(model: str | None = None, rpm: int | None = None, rpd: int | None = None) -> dict:
    preset = GEMINI_PRESETS.get(os.environ.get("GEMINI_PRESET", DEFAULT_PRESET), GEMINI_PRESETS[DEFAULT_PRESET])
    return {
        "model": model or os.environ.get("GEMINI_MODEL") or preset[0],
        "rpm": int(rpm or os.environ.get("GEMINI_RPM") or preset[1]),
        "rpd": int(rpd or os.environ.get("GEMINI_RPD") or preset[2]),
    }


# Claude (paid, the user's own Anthropic API key): (model id, RPM, RPD). Limits are a safety
# margin only; the real limits depend on the user's Anthropic account tier.
CLAUDE_PRESETS = {
    "quality": ("claude-opus-5-5", 20, 5000),
    "economy": ("claude-haiku-5-5", 20, 5000),
}


def claude_settings(model: str | None = None, rpm: int | None = None, rpd: int | None = None) -> dict:
    preset = CLAUDE_PRESETS.get(os.environ.get("ANTHROPIC_PRESET", DEFAULT_PRESET), CLAUDE_PRESETS[DEFAULT_PRESET])
    return {
        "model": model or os.environ.get("ANTHROPIC_MODEL") or preset[0],
        "rpm": int(rpm or os.environ.get("ANTHROPIC_RPM") or preset[1]),
        "rpd": int(rpd or os.environ.get("ANTHROPIC_RPD") or preset[2]),
    }


def cache_dir() -> Path:
    return Path(os.environ.get("SUBTRANS_CACHE_DIR") or Path.home() / ".subtrans" / "cache")
