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
    # 注意事项 / 补充说明这类不属于固定字段的内容
    extra: str | None = None
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

        # 「本周内」「这周末」没有具体星期几，语义是「到本周结束为止」：
        # 本周内 → 下周一 00:00；本周末 → 本周日 23:59。
        week_scope = re.search(
            r"(?P<prefix>下个?|这个?|本)\s*(?:周|星期)(?P<suffix>内|末)?"
            r"(?![一二三四五六日天])",
            value,
        )
        if week_scope:
            monday = now.date() - timedelta(days=now.weekday())
            if week_scope.group("prefix") in {"下", "下个"}:
                monday += timedelta(days=7)
            if week_scope.group("suffix") == "末":
                target_date = monday + timedelta(days=6)
                return datetime.combine(target_date, time(23, 59), SHANGHAI)
            return datetime.combine(monday + timedelta(days=7), time(0, 0), SHANGHAI)

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


# 卡片标题只留一眼能扫完的短句，整段话塞进去会把事项卡撑成三行。
TITLE_MAX_LENGTH = 30


def _shorten_title(candidate: str) -> str:
    if len(candidate) <= TITLE_MAX_LENGTH:
        return candidate
    # 长句子优先取第一个分句当标题：
    # “关于秋季研学的报名说明：请各位家长于……” → “关于秋季研学的报名说明”
    head = re.split(r"[：:。；;！!？?]", candidate, maxsplit=1)[0].strip()
    if 4 <= len(head) <= TITLE_MAX_LENGTH:
        return head
    return f"{candidate[:TITLE_MAX_LENGTH].rstrip('，,、。；;：: ')}…"


def _parse_title(text: str) -> str:
    labelled = _line_field(text, "活动名称", "事项名称", "活动主题", "主题", "标题")
    if labelled:
        return _shorten_title(labelled)

    for raw_line in text.splitlines():
        candidate = _clean(raw_line)
        if not candidate or candidate.startswith(("http://", "https://")):
            continue
        # 整段去掉【重要】【班级通知】这类前缀，否则标题会从半个括号开始。
        candidate = re.sub(r"^[【\[]\s*[^】\]]{1,12}\s*[】\]]\s*", "", candidate)
        candidate = re.sub(r"^[#【\[]+|[】\]]+$", "", candidate).strip()
        if candidate and not re.match(r"^(报名|截止|地点|对象|材料|联系)", candidate):
            return _shorten_title(candidate)
    return "未命名事项"


# 「材料：…」这种显式字段最好认，但很多通知只写「填在线文档」「上传到共享表格」，
# 通道本身就是报名材料，不抓就会漏成空白。
_MATERIAL_CARRIER = re.compile(
    r"(?:填|填写|填报|提交|上交|交|上传|传|发送|发)\s*(?:到|至|在|进)?\s*[^，,。；;\n]{0,4}?"
    r"(在线文档|在线表格|在线问卷|在线表单|共享文档|共享表格|电子表格"
    r"|腾讯文档|金山文档|石墨文档|问卷星|接龙"
    r"|Word\s*文档|Word|Excel|PDF|PPT|图片|照片|扫描件|压缩包)",
    re.IGNORECASE,
)


def _material_signature(item: str) -> str:
    return re.sub(r"[\s\W_]+", "", item, flags=re.UNICODE).lower()


def dedupe_materials(items: list[str]) -> list[str]:
    """「Word文档」和「思想汇报 Word 文档」是同一份材料，只留先出现的那条。"""
    kept: list[str] = []
    for item in items:
        signature = _material_signature(item)
        if not signature:
            continue
        if any(
            signature in _material_signature(existing)
            or _material_signature(existing) in signature
            for existing in kept
        ):
            continue
        kept.append(item)
    return kept


def _parse_materials(text: str) -> list[str]:
    pattern = re.compile(
        r"(?:^|\n)\s*(?:报名材料|所需材料|材料要求|补充材料|材料补充|提交材料|材料)"
        r"\s*[：:]\s*([^\n；;]+)"
    )
    materials: list[str] = []
    for match in pattern.finditer(text):
        materials.extend(
            item.strip()
            for item in re.split(r"[、,，；;/]+", match.group(1))
            if item.strip()
            and not re.match(r"^(?:文件)?命名", item.strip())
            and not _is_channel_item(item.strip())
            and not _is_packaging_item(item.strip())
        )
    for match in _MATERIAL_CARRIER.finditer(text):
        item = match.group(1).strip()
        if not _is_channel_item(item) and not _is_packaging_item(item):
            materials.append(item)
    # ①②③ 这种编号清单在通知里很常见，逐条认成材料。
    for match in CIRCLED_ITEM.finditer(text):
        item = match.group(1).strip(" 　，,、。；;")
        if not item or not _FILE_HINT.search(item):
            continue
        if (
            _is_channel_item(item)
            or _is_packaging_item(item)
            or re.match(r"^(?:文件)?命名", item)
        ):
            continue
        materials.append(item)
    return dedupe_materials(materials)


_EXTRA_NOTE_LABELS = ("附加信息", "注意事项", "备注", "补充说明", "注意")
_EXTRA_NAMING_LABELS = ("文件命名格式", "命名格式", "文件命名", "命名要求", "命名规则")
# 「需要提交材料：电子版表格，命名格式：姓名+学号」这种命名要求常跟材料写在同一行，
# 所以不能用行首锚定的 _line_field 去找。
NAMING_PATTERN = re.compile(
    r"(?:文件)?命名(?:(?:格式|要求|规则))?\s*[：:]\s*([^\n；;，,。]+)"
)

# 收集表 / 邮箱 是「往哪儿交」，不是「交什么」，不能算报名材料。
# 注意「问卷」不算渠道：填问卷本身就是任务，问卷本身就是材料。
CHANNEL_WORDS = ("收集表", "邮箱", "群文件", "接龙", "班长", "学委")
SUBMIT_CLAUSE = re.compile(
    r"(?:上传|提交到|提交至|提交|发送到|发送至|发送|发到|发给|交到|交给|交)"
    r"[^，,。；;\n]{0,6}?(?:群)?(?:收集表|问卷|邮箱|群文件|接龙|链接|班长|学委)"
)


def _is_channel_item(item: str) -> bool:
    return any(word in item for word in CHANNEL_WORDS)


# 压缩包是「怎么打包」，不是「交什么」：材料是里面的文件，压缩包本身进附加信息。
PACKAGING_WORDS = ("压缩包", "压缩文件", "打包", "zip", "rar", "7z")
PACKAGING_CLAUSE = re.compile(
    r"[^，,。；;\n]*?(?:打包|压缩包|zip|rar|7z)[^，,。；;\n]*", re.IGNORECASE
)
CIRCLED_ITEM = re.compile(r"(?m)^\s*[①-⑳]\s*([^\n]+)$")
_FILE_HINT = re.compile(
    r"文档|表格|表|照片|图片|截图|txt|docx?|pdf|jpg|jpeg|png|word|excel|ppt|视频|音频|证书|心得|报告|简历|证明",
    re.IGNORECASE,
)


def _is_packaging_item(item: str) -> bool:
    lowered = item.lower()
    return any(word in lowered for word in PACKAGING_WORDS)


def _packaging_clause(text: str, note: str | None = None) -> str | None:
    for match in PACKAGING_CLAUSE.finditer(text):
        clause = match.group(0).strip(" ，,、")
        # 「压缩包命名：…」是命名要求，交给命名规则处理，不重复算打包说明。
        if "命名" in clause:
            continue
        # 「所有文件不要压缩打包」是禁止项，属于注意事项，不是打包要求。
        if re.search(r"不要|禁止|无需|不用|不必|不允许", clause):
            continue
        if note and (clause in note or note in clause):
            continue
        return clause
    return None


def _submit_clause(text: str) -> str | None:
    labelled = _line_field(text, "提交渠道", "提交方式", "提交途径", "提交", "渠道")
    if labelled:
        return labelled.rstrip("。")
    match = SUBMIT_CLAUSE.search(text)
    return match.group(0).strip() if match else None


def _parse_extra(text: str, materials: list[str] | None = None) -> str | None:
    """附加信息：命名格式 + 提交方式 + 注意事项（这些都不是「材料」）。"""
    parts: list[str] = []
    naming = NAMING_PATTERN.search(text)
    if naming:
        parts.append(f"文件命名格式：{naming.group(1).strip()}")
    clause = _submit_clause(text)
    if clause:
        # 「将 Word 文档上传收集表」比单写一个「收集表」清楚。
        target = next((m for m in (materials or []) if not _is_channel_item(m)), None)
        parts.append(
            f"提交方式：将{target}{clause}" if target else f"提交方式：{clause}"
        )
    note = _line_field(text, *_EXTRA_NOTE_LABELS)
    if note:
        parts.append(note.rstrip("。"))
    packaging = _packaging_clause(text, note)
    if packaging:
        parts.append(f"打包要求：{packaging}")
    return "；".join(dict.fromkeys(parts)) or None


# 一句「不需要提交任何文件」加一句「提交一张截图」，原文自己就打架，
# 这种不能靠模型自评，规则直接标出来让人看一眼。
_NO_SUBMIT_ANYTHING = re.compile(
    r"(?:不需要|无需|不用|不必|不需)\s*(?:提交|上传|上交|交|提供)?\s*任何\s*(?:文件|材料|东西|资料)"
)
_SUBMIT_SOMETHING = re.compile(
    r"(?:提交|上传|上交|交|发送|发)\s*[^。；;\n]{0,12}"
    r"(?:截图|照片|图片|文档|表格|文件|材料|问卷|收集表|接龙)"
    r"|(?:截图|照片|图片)\s*[^。；;\n]{0,12}(?:上传|提交|发到|发给)"
)


def _material_conflict(text: str) -> bool:
    spans = [match.span() for match in _NO_SUBMIT_ANYTHING.finditer(text)]
    if not spans:
        return False
    for match in _SUBMIT_SOMETHING.finditer(text):
        # 「不需要提交任何文件」这句本身也会命中“提交…文件”，要排掉。
        if any(start <= match.start() < end for start, end in spans):
            continue
        return True
    return False


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
_DEDUPE_STOPWORDS = (
    "关于", "的通知", "通知", "报名", "提醒", "工作",
    "补充", "更正", "变更", "修改", "调整",
)


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
    if _material_conflict(text):
        review_reasons.append("material_conflict")

    materials = _parse_materials(text)
    return ParsedActivity(
        title=title,
        audience=_line_field(text, "适用对象", "报名对象", "参与对象", "对象"),
        deadline=deadline,
        location=_line_field(text, "活动地点", "地点"),
        materials=materials,
        registration_url=url_match.group(0).rstrip("。，,；;") if url_match else None,
        contact=_line_field(text, "联系人", "咨询电话", "联系方式"),
        extra=_parse_extra(text, materials),
        change_type=change_type,
        needs_review=bool(review_reasons),
        dedupe_key=normalise_key(title) or "unnamed",
        review_reasons=review_reasons,
    )

