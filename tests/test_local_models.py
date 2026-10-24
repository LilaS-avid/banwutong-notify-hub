import app.local_models as local_models


class FakeModelsResponse:
    def __init__(self, models: list[str]) -> None:
        self.models = models

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "object": "list",
            "data": [{"id": model} for model in self.models],
        }


def test_detects_ollama_and_prefers_qwen(monkeypatch) -> None:
    monkeypatch.delenv("BANWUTONG_LOCAL_BASE_URL", raising=False)
    monkeypatch.delenv("BANWUTONG_LOCAL_MODEL", raising=False)

    def fake_get(url: str, timeout: float):
        if "11434" in url:
            return FakeModelsResponse(["llama3.2:3b", "qwen2.5:7b"])
        raise ConnectionError("not running")

    monkeypatch.setattr(local_models.httpx, "get", fake_get)

    detected = local_models.detect_local_model()

    assert detected is not None
    assert detected.server == "Ollama"
    assert detected.base_url == "http://127.0.0.1:11434/v1"
    assert detected.model == "qwen2.5:7b"


def test_preferred_local_model_wins(monkeypatch) -> None:
    monkeypatch.setenv(
        "BANWUTONG_LOCAL_BASE_URL",
        "http://127.0.0.1:9000/v1",
    )
    monkeypatch.setenv("BANWUTONG_LOCAL_MODEL", "custom-model")
    monkeypatch.setattr(
        local_models.httpx,
        "get",
        lambda url, timeout: FakeModelsResponse(["qwen2.5:7b", "custom-model"]),
    )

    detected = local_models.detect_local_model()

    assert detected is not None
    assert detected.server == "自定义本地模型"
    assert detected.model == "custom-model"
