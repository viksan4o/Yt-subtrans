import pytest


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path, monkeypatch):
    """Keep tests away from the real cache, real keys and any local .env."""
    monkeypatch.setenv("SUBTRANS_CACHE_DIR", str(tmp_path / "cache"))
    for var in ("GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_RPM", "GEMINI_RPD", "GEMINI_PRESET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.chdir(tmp_path)
