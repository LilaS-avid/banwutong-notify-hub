from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}


@dataclass(slots=True)
class ParsedActivity:
    title: str
    audience: str | None
    deadline: str | None
    location: str | None
    materials: list[str]
    registration_url: str | None
    contact: str | None
    change_type: str
    needs_review: bool
    dedupe_key: str


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" \t\r\n-—")
    return cleaned or None


def _line_field(text: str, *labels: str) -> str | None:
    label_group = "|".join(re.escape(label) for label in labels)
    match = re.search(
        rf"(?:^|\n)\s*(?:{label_group})\s*[：:]\s*([^\n；;]+)",
        text,
        flags=re.IGNORECASE,
    )
    return _clean(match.group(1)) if match else None


def _parse_date_time(value: str, now: datetime) -> datetime | None:
    absolute = re.search(
        r"(?P<year>\d{4})\s*[年/-]\s*(?P<month>\d{1,2})\s*[月/-]\s*"
        r"(?P<day>\d{1,2})\s*日?"
        r"(?:\s*(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2}))?",
        value,
    )
    month_day = re.search(
        r"(?P<month>\d{1,2})\s*月\s*(?P<day>\d{1,2})\s*日"
        r"(?:\s*(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2}))?",
        value,
    )

    if absolute:
        year = int(absolute.group("year"))
        month = int(absolute.group("month"))
        day = int(absolute.group("day"))
        hour = int(absolute.group("hour") or 23)
        minute = int(absolute.group("minute") or 59)
    elif month_day:
        year = now.year
        month = int(month_day.group("month"))
        day = int(month_day.group("day"))
        hour = int(month_day.group("hour") or 23)
        minute = int(month_day.group("minute") or 59)
    else:
        weekday = re.search(
            r"(?P<scope>下个?|这个?|本)?(?:周|星期)"
            r"(?P<weekday>[一二三四五六日天])",
            value,
        )
        if weekday:
            target_weekday = WEEKDAYS[weekday.group("weekday")]
            scope = weekday.group("scope") or ""
            if scope in {"下", "下个"}:
                days_ahead = 7 - now.weekday() + target_weekday
            elif scope in {"这", "这个", "本"}:
                days_ahead = target_weekday - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7
            else:
                days_ahead = target_weekday - now.weekday()
                if days_ahead < 0:
                    days_ahead += 7
            target_date = now.date() + timedelta(days=days_ahead)
            clock = re.search(r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2})", value)
            hour = int(clock.group("hour")) if clock else 23
            minute = int(clock.group("minute")) if clock else 59
            return datetime.combine(target_date, time(hour, minute), SHANGHAI)

        offset = 0
        if re.search(r"后天", value):
            offset = 2
        elif re.search(r"明天|明日", value):
            offset = 1
        elif re.search(r"今天|今日", value):
            offset = 0
        else:
            return None
        target_date = now.date() + timedelta(days=offset)
        clock = re.search(r"(?P<hour>\d{1,2})\s*[:：]\s*(?P<minute>\d{2})", value)
        hour = int(clock.group("hour")) if clock else 23
        minute = int(clock.group("minute")) if clock else 59
        return datetime.combine(target_date, time(hour, minute), SHANGHAI)

    try:
        parsed = datetime.combine(date(year, month, day), time(hour, minute), SHANGHAI)
    except ValueError:
        return None

    if not absolute and parsed < now - timedelta(days=30):
        try:
            parsed = parsed.replace(year=year + 1)
        except ValueError:
            return None
    return parsed


def _parse_deadline(text: str, now: datetime) -> str | None:
    deadline_line = _line_field(
        text,
        "报名截止",
        "截止时间",
        "截止日期",
        "报名时间",
        "截止",
    )
    if deadline_line:
        parsed = _parse_date_time(deadline_line, now)
        if parsed:
            return parsed.isoformat()

    contextual = re.search(
        r"(?:请于|须在|需要在|截止到)\s*([^\n，。；;]+)",
        text,
    )
    if contextual:
        parsed = _parse_date_time(contextual.group(1), now)
        if parsed:
            return parsed.isoformat()

    # Many class notices put the date directly in the sentence instead of
    # using a "截止时间" label, for example: "下周五要开会".
    parsed = _parse_date_time(text, now)
    if parsed:
        return parsed.isoformat()
    return None


def _parse_title(text: str) -> str:
    labelled = _line_field(text, "活动名称", "事项名称", "活动主题", "主题", "标题")
    if labelled:
        return labelled

    for raw_line in text.splitlines():
        candidate = _clean(raw_line)
        if not candidate or candidate.startswith(("http://", "https://")):
            continue
        candidate = re.sub(r"^[#【\[]+|[】\]]+$", "", candidate).strip()
        if candidate and not re.match(r"^(报名|截止|地点|对象|材料|联系)", candidate):
            return candidate[:80]
    return "未命名事项"


def _parse_materials(text: str) -> list[str]:
    pattern = re.compile(
        r"(?:^|\n)\s*(?:报名材料|所需材料|材料要求|补充材料|材料补充|材料)"
        r"\s*[：:]\s*([^\n；;]+)"
    )
    materials: list[str] = []
    for match in pattern.finditer(text):
        materials.extend(
            item.strip()
            for item in re.split(r"[、,，；;/]+", match.group(1))
            if item.strip()
        )
    return list(dict.fromkeys(materials))


def _detect_change(text: str) -> str:
    if re.search(r"取消|终止|暂停", text):
        return "cancel"
    if re.search(r"延期|推迟|调整|补充|更正|改为|变更", text):
        return "update"
    return "new"


def normalise_key(title: str) -> str:
    return re.sub(r"[\W_]+", "", title, flags=re.UNICODE).lower()


def parse_notification(text: str, now: datetime | None = None) -> ParsedActivity:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    else:
        current = current.astimezone(SHANGHAI)

    title = _parse_title(text)
    deadline = _parse_deadline(text, current)
    url_match = URL_PATTERN.search(text)
    change_type = _detect_change(text)

    return ParsedActivity(
        title=title,
        audience=_line_field(text, "适用对象", "报名对象", "参与对象", "对象"),
        deadline=deadline,
        location=_line_field(text, "活动地点", "地点"),
        materials=_parse_materials(text),
        registration_url=url_match.group(0).rstrip("。，,；;") if url_match else None,
        contact=_line_field(text, "联系人", "咨询电话", "联系方式"),
        change_type=change_type,
        needs_review=deadline is None,
        dedupe_key=normalise_key(title) or "unnamed",
    )

