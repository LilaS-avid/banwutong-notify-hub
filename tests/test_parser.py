from datetime import datetime
from zoneinfo import ZoneInfo

from app.parser import parse_notification


def test_extracts_core_fields() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """活动名称：创新大赛
报名截止：2026-11-05 18:00
适用对象：全体学生
报名材料：报名表、学生证照片
报名链接：https://example.com/register
联系人：学生中心""",
        now,
    )

    assert parsed.title == "创新大赛"
    assert parsed.deadline == "2026-11-05T18:00:00+08:00"
    assert parsed.audience == "全体学生"
    assert parsed.materials == ["报名表", "学生证照片"]
    assert parsed.registration_url == "https://example.com/register"
    assert parsed.needs_review is False


def test_relative_deadline_and_review_flag() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification("讲座报名\n截止时间：明天 20:30", now)

    assert parsed.deadline == "2026-10-25T20:30:00+08:00"
    assert parsed.needs_review is False


def test_next_week_weekday_without_deadline_label() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification("通知 下周五要开会", now)

    assert parsed.deadline == "2026-10-30T23:59:00+08:00"
    assert parsed.needs_review is False


def test_missing_deadline_requires_review() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification("志愿者招募\n地点：大学生活动中心", now)

    assert parsed.title == "志愿者招募"
    assert parsed.deadline is None
    assert parsed.needs_review is True

