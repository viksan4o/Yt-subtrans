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


class OllamaProvider(TranslationProvider):
    name = "ollama"

    def __init__(self, model: str, host: str = "http://localhost:11434", batch_size: int = 25,
                 timeout: float = 600, post=_post_json):
        self.model, self.host, self.batch_size, self.timeout = model, host.rstrip("/"), batch_size, timeout
        self._post = post

    def complete(self, system: str, user: str) -> str:
        body = {"model": self.model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "options": {"temperature": 0.2}}
        try:
            data = self._post(f"{self.host}/api/chat", body, self.timeout)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise RuntimeError(f"Моделът „{self.model}“ не е изтеглен в Ollama. "
                                   f"Пусни: ollama pull {self.model}") from e
            raise
        except (urllib.error.URLError, ConnectionError) as e:
            raise RuntimeError("Ollama не отговаря на " + self.host +
                               ". Стартирай Ollama и опитай пак.") from e
        return data.get("message", {}).get("content", "")
