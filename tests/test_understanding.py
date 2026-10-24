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
