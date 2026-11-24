"""Settings from environment variables, optionally loaded from a local .env file.

Keys are never logged or written anywhere by the engine.
"""

import os
from pathlib import Path

# Presets: (model id, RPM, RPD). Conservative free-tier guesses; they change, so check Google AI
# Studio and override with GEMINI_MODEL / GEMINI_RPM / GEMINI_RPD or --model.
# Checked Nov 2026 with a new key: the 2.5 models and the "-latest" aliases return 404 for new
# users, and the 3.x flash models were often busy (503), while 3.5 flash-lite answered.
GEMINI_PRESETS = {
    "quality": ("gemini-3.8-flash", 5, 20),
    "volume": ("gemini-3.5-flash-lite", 15, 500),
}
# Quality by default: the flash-lite models invented Bulgarian words in real clips (Nov 2026).
GEMINI_DEFAULT_PRESET = "quality"
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
    preset = GEMINI_PRESETS.get(os.environ.get("GEMINI_PRESET", GEMINI_DEFAULT_PRESET),
                                GEMINI_PRESETS[GEMINI_DEFAULT_PRESET])
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


# Ollama (local, free). Default: BgGPT 9B, Q4_K_M (~5.8 GB, fits 8 GB VRAM). On 6 GB cards
# use the 2.6B build or accept partial CPU offload. Small batches: local models are weaker at JSON.
OLLAMA_DEFAULT_MODEL = "hf.co/INSAIT-Institute/BgGPT-Gemma-2-9B-IT-v1.0-GGUF:Q4_K_M"


def ollama_settings(model: str | None = None) -> dict:
    return {
        "model": model or os.environ.get("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL,
        "host": os.environ.get("OLLAMA_HOST_URL", "http://localhost:11434"),
        "batch_size": int(os.environ.get("OLLAMA_BATCH") or 15),
        "num_ctx": int(os.environ.get("OLLAMA_NUM_CTX") or 4096),
    }


def cache_dir() -> Path:
    return Path(os.environ.get("SUBTRANS_CACHE_DIR") or Path.home() / ".subtrans" / "cache")
