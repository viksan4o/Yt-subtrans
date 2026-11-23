"""Local models through the Ollama HTTP API (offline, free, no key). Intended for BgGPT."""

import json
import urllib.error
import urllib.request

from .base import TranslationProvider


def _post_json(url: str, body: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


SMALL_MODEL = "hf.co/INSAIT-Institute/BgGPT-Gemma-2-2.6B-IT-v1.0-GGUF:Q4_K_M"


def _error_text(e: urllib.error.HTTPError) -> str:
    """Ollama puts the reason (out of memory, bad model...) in the JSON body as {"error": "..."}."""
    try:
        raw = e.read().decode("utf-8", "replace")
    except Exception:
        return str(e.reason)
    try:
        return json.loads(raw).get("error", raw)
    except (ValueError, AttributeError):
        return raw.strip() or str(e.reason)


class OllamaProvider(TranslationProvider):
    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", batch_size: int = 15,
                 num_ctx: int = 4096, timeout: float = 900, post=_post_json):
        self.model, self.host, self.batch_size, self.timeout = model, host.rstrip("/"), batch_size, timeout
        self.num_ctx = num_ctx
        self._post = post

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0.2, "num_ctx": self.num_ctx}}
        try:
            data = self._post(f"{self.host}/api/chat", body, self.timeout)
        except urllib.error.HTTPError as e:
            detail = _error_text(e)
            if e.code == 404:
                raise RuntimeError(f"Моделът „{self.model}“ не е изтеглен в Ollama. "
                                   f"Пусни: ollama pull {self.model}") from e
            hint = ""
            if "memory" in detail.lower() or "cuda" in detail.lower():
                hint = (" Не стига видеопамет: затвори други програми или ползвай по-малкия модел "
                        "с --model " + SMALL_MODEL)
            raise RuntimeError(f"Ollama върна грешка {e.code}: {detail}.{hint}") from e
        except (urllib.error.URLError, ConnectionError) as e:
            raise RuntimeError("Ollama не отговаря на " + self.host +
                               ". Стартирай Ollama и опитай пак.") from e
        return data.get("message", {}).get("content", "")
