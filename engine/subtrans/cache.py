r"""Per-run translation progress on disk, so an interrupted run can resume.

Location: %USERPROFILE%\.subtrans\cache\ (override with SUBTRANS_CACHE_DIR).
"""

import hashlib
import json
from pathlib import Path

from .config import cache_dir


def cache_key(video_id: str, source: str, target: str, provider: str, model: str) -> str:
    raw = json.dumps([video_id, source, target, provider, model])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class TranslationCache:
    def __init__(self, video_id: str, source: str, target: str, provider: str, model: str,
                 root: Path | None = None):
        self.meta = {"video_id": video_id, "source": source, "target": target,
                     "provider": provider, "model": model}
        self.path = Path(root or cache_dir()) / f"{cache_key(video_id, source, target, provider, model)}.json"
        self.cues: list[dict] = []  # source cues, so a cached run needs no new caption fetch
        self.complete = False

    def load(self) -> dict[int, str]:
        if not self.path.is_file():
            return {}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.cues = data.get("cues", [])
        self.complete = data.get("complete", False)
        return {int(k): v for k, v in data.get("done", {}).items()}

    def save(self, done: dict[int, str], complete: bool = False) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({**self.meta, "complete": complete, "cues": self.cues,
                                   "done": {str(k): v for k, v in done.items()}},
                                  ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)
