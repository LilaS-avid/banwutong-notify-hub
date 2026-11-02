from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


SHANGHAI = ZoneInfo("Asia/Shanghai")
URL_PATTERN = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
WEEKDAYS = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}
DATE_TOKEN = re.compile(
    r"\d{4}\s*[年/-]\s*\d{1,2}\s*[月/-]\s*\d{1,2}\s*日?"
    r"|\d{1,2}\s*月\s*\d{1,2}\s*日"
)
DATE_RANGE = re.compile(
    rf"(?:{DATE_TOKEN.pattern})"
    r"\s*(?:至|到|~|～|—|－|-|–)\s*"
    rf"(?:{DATE_TOKEN.pattern})"
)


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
    # 待核对原因码；空列表表示关键字段没有可疑之处
    review_reasons: list[str] = field(default_factory=list)


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


def _parse_deadline_with_source(
    text: str,
    now: datetime,
) -> tuple[str | None, str | None]:
    """返回 (截止时间, 来源)。来源决定这段日期有多可信。

    label/contextual 表示原文明确写了截止点；fallback 表示只是把正文里
    第一个能解析的日期当成截止时间，这种情况下区间和多日期都要人工核对。
    """
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
            return parsed.isoformat(), "label"

    contextual = re.search(
        r"(?:请于|须在|需要在|截止到)\s*([^\n，。；;]+)",
        text,
    )
    if contextual:
        parsed = _parse_date_time(contextual.group(1), now)
        if parsed:
            return parsed.isoformat(), "contextual"

    # Many class notices put the date directly in the sentence instead of
    # using a "截止时间" label, for example: "下周五要开会".
    parsed = _parse_date_time(text, now)
    if parsed:
        return parsed.isoformat(), "fallback"
    return None, None


def _parse_deadline(text: str, now: datetime) -> str | None:
    return _parse_deadline_with_source(text, now)[0]


def _date_signature(token: str) -> tuple[int, int]:
    numbers = [int(item) for item in re.findall(r"\d+", token)]
    return (numbers[-2], numbers[-1])


def _deadline_review_reasons(
    text: str,
    source: str | None,
    deadline: str | None,
) -> list[str]:
    if deadline is None:
        return ["deadline_missing"]
    if source != "fallback":
        return []
    if DATE_RANGE.search(text):
        return ["deadline_range"]
    distinct_dates = {
        _date_signature(match.group(0)) for match in DATE_TOKEN.finditer(text)
    }
    if len(distinct_dates) >= 2:
        return ["deadline_conflict"]
    return []


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
    # “取消后不退费”“取消评优及加分资格”这类是规则说明，不是活动被取消，
    # 之前只要出现“取消”就判 cancel，会把正常的报名通知整条标成已取消。
    for match in re.finditer(r"取消|终止|暂停", text):
        tail = text[match.end():match.end() + 4]
        if not re.match(r"^(后|不|资格|评优|加分|其)", tail):
            return "cancel"
    if re.search(r"延期|推迟|延长|改到|调整|补充|更正|改为|变更", text):
        return "update"
    return "new"


# 标题里这些词不区分活动，剥掉后再比，否则“关于…的通知”一加就变成新活动
_DEDUPE_STOPWORDS = ("关于", "的通知", "通知", "报名", "提醒", "工作")


def normalise_key(title: str) -> str:
    text = title or ""
    text = re.sub(r"^\s*[【\[（(][^】\]）)]{0,12}[】\]）)]", "", text)   # 【重要】这类前缀
    text = re.sub(r"^\s*\d+\s*[.、)]\s*", "", text)                    # 1. （一）
    for word in _DEDUPE_STOPWORDS:
        text = text.replace(word, "")
    return re.sub(r"[\W_]+", "", text, flags=re.UNICODE).lower()


def parse_notification(text: str, now: datetime | None = None) -> ParsedActivity:
    current = now or datetime.now(SHANGHAI)
    if current.tzinfo is None:
        current = current.replace(tzinfo=SHANGHAI)
    else:
        current = current.astimezone(SHANGHAI)

    title = _parse_title(text)
    deadline, deadline_source = _parse_deadline_with_source(text, current)
    url_match = URL_PATTERN.search(text)
    change_type = _detect_change(text)
    review_reasons = _deadline_review_reasons(text, deadline_source, deadline)
    if title == "未命名事项" and "title_missing" not in review_reasons:
        review_reasons.append("title_missing")

    return ParsedActivity(
        title=title,
        audience=_line_field(text, "适用对象", "报名对象", "参与对象", "对象"),
        deadline=deadline,
        location=_line_field(text, "活动地点", "地点"),
        materials=_parse_materials(text),
        registration_url=url_match.group(0).rstrip("。，,；;") if url_match else None,
        contact=_line_field(text, "联系人", "咨询电话", "联系方式"),
        change_type=change_type,
        needs_review=bool(review_reasons),
        dedupe_key=normalise_key(title) or "unnamed",
        review_reasons=review_reasons,
    )

