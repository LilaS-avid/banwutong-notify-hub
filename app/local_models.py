from __future__ import annotations

import os
from dataclasses import dataclass

import httpx


@dataclass(slots=True)
class LocalModelInfo:
    server: str
    base_url: str
    model: str


MODEL_PRIORITY = (
    "qwen3",
    "qwen2.5",
    "qwen",
    "deepseek-r1",
    "deepseek",
    "llama3.3",
    "llama3",
    "mistral",
)


def _rank_model(model: str) -> tuple[int, str]:
    lowered = model.lower()
    for index, prefix in enumerate(MODEL_PRIORITY):
        if prefix in lowered:
            return index, lowered
    return len(MODEL_PRIORITY), lowered


def _model_ids(payload: object) -> list[str]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    models: list[str] = []
    for item in data:
        if isinstance(item, dict):
            model_id = item.get("id")
        else:
            model_id = item
        if isinstance(model_id, str) and model_id.strip():
            models.append(model_id.strip())
    return list(dict.fromkeys(models))


def detect_local_model() -> LocalModelInfo | None:
    candidates: list[tuple[str, str]] = []
    configured = os.getenv("BANWUTONG_LOCAL_BASE_URL", "").strip()
    if configured:
        candidates.append(("自定义本地模型", configured))
    candidates.extend(
        [
            ("Ollama", "http://127.0.0.1:11434/v1"),
            ("LM Studio", "http://127.0.0.1:1234/v1"),
        ]
    )

    preferred = os.getenv("BANWUTONG_LOCAL_MODEL", "").strip()
    seen: set[str] = set()
    for server, raw_base_url in candidates:
        base_url = raw_base_url.rstrip("/")
        if base_url in seen:
            continue
        seen.add(base_url)
        models_url = f"{base_url}/models"
        try:
            response = httpx.get(models_url, timeout=1.2)
            response.raise_for_status()
            models = _model_ids(response.json())
        except Exception:
            continue
        if not models:
            continue
        if preferred and any(model == preferred for model in models):
            selected = preferred
        else:
            selected = min(models, key=_rank_model)
        return LocalModelInfo(
            server=server,
            base_url=base_url,
            model=selected,
        )
    return None
