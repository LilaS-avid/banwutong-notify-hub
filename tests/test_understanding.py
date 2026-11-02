import json
from datetime import datetime
from zoneinfo import ZoneInfo

import app.understanding as understanding_module
from app.documents import DocumentBlock
from app.understanding import chat_with_model, understand_document


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "choices": [
                {
                    "message": {
                        "content": """{
                          "activities": [{
                            "title": "创新大赛",
                            "audience": "全体学生",
                            "deadline": "2026-11-05T18:00:00+08:00",
                            "location": "线上",
                            "materials": ["报名表"],
                            "registration_url": "https://example.com",
                            "contact": "张老师",
                            "change_type": "new",
                            "evidence": ["page-1"]
                          }]
                        }"""
                    }
                }
            ]
        }


def test_llm_extracts_structured_activity(monkeypatch) -> None:
    monkeypatch.setenv("BANWUTONG_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("BANWUTONG_LLM_MODEL", "test-model")
    monkeypatch.setenv("BANWUTONG_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        understanding_module.httpx,
        "post",
        lambda *args, **kwargs: FakeResponse(),
    )
    blocks = [
        DocumentBlock(
            locator="page-1",
            block_type="page",
            text="活动名称：创新大赛\n报名截止：2026-11-05 18:00",
        )
    ]

    result = understand_document(
        blocks,
        datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        provider="cloud",
    )

    assert result.method == "cloud"
    assert len(result.activities) == 1
    activity = result.activities[0]
    assert activity.parsed.title == "创新大赛"
    assert activity.parsed.deadline == "2026-11-05T18:00:00+08:00"
    assert activity.evidence == ["page-1"]


class FakeProcess:
    returncode = 0
    stderr = ""
    stdout = """{
      "activities": [{
        "title": "Codex 提取活动",
        "audience": "学生",
        "deadline": "2026-11-06T18:00:00+08:00",
        "location": "教室",
        "materials": ["报名表"],
        "registration_url": null,
        "contact": null,
        "change_type": "new",
        "evidence": ["page-1"]
      }]
    }"""


def test_codex_provider_uses_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        understanding_module.shutil,
        "which",
        lambda name: "codex.exe" if name == "codex" else None,
    )
    monkeypatch.setattr(
        understanding_module.subprocess,
        "run",
        lambda *args, **kwargs: FakeProcess(),
    )
    blocks = [
        DocumentBlock(
            locator="page-1",
            block_type="page",
            text="活动名称：Codex 提取活动",
        )
    ]

    result = understand_document(
        blocks,
        datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        provider="codex",
    )

    assert result.method == "codex"
    assert result.activities[0].parsed.title == "Codex 提取活动"


class FakeChatProcess:
    returncode = 0
    stderr = ""
    stdout = "这是模型回复。"


def test_codex_chat_uses_cli(monkeypatch) -> None:
    monkeypatch.setattr(
        understanding_module.shutil,
        "which",
        lambda name: "codex.exe" if name == "codex" else None,
    )
    monkeypatch.setattr(
        understanding_module.subprocess,
        "run",
        lambda *args, **kwargs: FakeChatProcess(),
    )

    reply, provider = chat_with_model(
        [{"role": "user", "content": "你好"}],
        "当前没有已保存事项。",
        provider="codex",
    )

    assert reply == "这是模型回复。"
    assert provider == "codex"


# --- 模型自评是否需要人工核对 -------------------------------------------


class FakeVerdictResponse:
    def __init__(self, payload: dict) -> None:
        self._content = json.dumps(payload, ensure_ascii=False)

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"choices": [{"message": {"content": self._content}}]}


def _cloud_result(monkeypatch, text: str, payload: dict):
    monkeypatch.setenv("BANWUTONG_LLM_BASE_URL", "https://llm.example/v1")
    monkeypatch.setenv("BANWUTONG_LLM_MODEL", "test-model")
    monkeypatch.setenv("BANWUTONG_LLM_API_KEY", "test-key")
    monkeypatch.setattr(
        understanding_module.httpx,
        "post",
        lambda *args, **kwargs: FakeVerdictResponse(payload),
    )
    blocks = [DocumentBlock(locator="page-1", block_type="page", text=text)]
    return understand_document(
        blocks,
        datetime(2026, 11, 2, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai")),
        provider="cloud",
    )


def _activity_payload(deadline: str | None, **overrides) -> dict:
    payload = {
        "title": "消防演练安排",
        "audience": None,
        "deadline": deadline,
        "location": None,
        "materials": [],
        "registration_url": None,
        "contact": None,
        "change_type": "new",
        "evidence": ["page-1"],
    }
    payload.update(overrides)
    return {"kind": "notice", "activities": [payload]}


AMBIGUOUS_TEXT = "消防演练安排\n2026-12-10 09:00 集合，补演安排在 2026-12-17 09:00"


def test_model_verdict_passes_ambiguous_deadline(monkeypatch) -> None:
    """规则觉得有多个日期，但模型核验说没问题，就不进待核对。"""
    result = _cloud_result(
        monkeypatch,
        AMBIGUOUS_TEXT,
        _activity_payload("2026-12-10T09:00:00+08:00", needs_review=False),
    )

    parsed = result.activities[0].parsed
    assert parsed.deadline == "2026-12-10T09:00:00+08:00"
    assert parsed.review_reasons == []
    assert parsed.needs_review is False


def test_model_verdict_uncertain_goes_to_review(monkeypatch) -> None:
    result = _cloud_result(
        monkeypatch,
        AMBIGUOUS_TEXT,
        _activity_payload("2026-12-10T09:00:00+08:00", needs_review=True),
    )

    parsed = result.activities[0].parsed
    assert "ai_uncertain" in parsed.review_reasons
    assert parsed.needs_review is True


def test_model_cannot_waive_missing_deadline(monkeypatch) -> None:
    result = _cloud_result(
        monkeypatch,
        "志愿者招募\n地点：大学生活动中心",
        _activity_payload(None, needs_review=False, title="志愿者招募"),
    )

    parsed = result.activities[0].parsed
    assert parsed.deadline is None
    assert parsed.review_reasons == ["deadline_missing"]
    assert parsed.needs_review is True


def test_deadline_mismatch_is_flagged_without_model_verdict(monkeypatch) -> None:
    """模型和规则对不上，又没有自评时，默认还是要人工看。"""
    result = _cloud_result(
        monkeypatch,
        "活动名称：交材料\n报名截止：2026-12-15 18:00",
        _activity_payload("2026-12-01T18:00:00+08:00", title="交材料"),
    )

    parsed = result.activities[0].parsed
    assert "deadline_mismatch" in parsed.review_reasons
    assert parsed.needs_review is True
