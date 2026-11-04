from __future__ import annotations

from dataclasses import dataclass

from app.schemas import ReviewReasonOut


@dataclass(frozen=True, slots=True)
class ReasonInfo:
    label: str
    severity: str
    hint: str


# 原因码是数据契约，前端和后端都按码判断，不要改已有码的含义。
REASON_INFO: dict[str, ReasonInfo] = {
    "deadline_missing": ReasonInfo(
        label="缺少截止时间",
        severity="blocking",
        hint="原文没有可识别的截止时间，提醒不会触发。请补全截止时间后再确认。",
    ),
    "deadline_range": ReasonInfo(
        label="截止时间取自日期区间",
        severity="warning",
        hint="原文写的是日期区间，系统取到的截止点可能不是真正的截止时间。",
    ),
    "deadline_conflict": ReasonInfo(
        label="原文存在多个日期",
        severity="warning",
        hint="原文出现多个不同日期，系统按第一个可解析日期估算，请核对。",
    ),
    "title_missing": ReasonInfo(
        label="标题取自首行",
        severity="warning",
        hint="原文没有明确的标题字段，当前标题直接取自首行文本。",
    ),
    "ai_uncertain": ReasonInfo(
        label="AI 自己也不确定",
        severity="warning",
        hint="模型判断这条抽取存在歧义，请对照原文核对截止时间。",
    ),
    "deadline_mismatch": ReasonInfo(
        label="AI 与规则解析的截止时间不一致",
        severity="warning",
        hint="模型给出的截止时间和正则解析相差超过一天，两者必有一个读错了。",
    ),
    "material_conflict": ReasonInfo(
        label="材料说法相互矛盾",
        severity="warning",
        hint="原文一边说不需要提交任何文件，一边又要求上传截图之类的东西，需要人工确认到底要交什么。",
    ),
}

REASON_PRIORITY = tuple(REASON_INFO)


def sanitise_reasons(codes: list[str] | tuple[str, ...] | None) -> list[str]:
    """去重、丢弃未知码，并按固定优先级排序，保证前后端顺序一致。"""
    if not codes:
        return []
    unique = {code for code in codes if code in REASON_INFO}
    return [code for code in REASON_PRIORITY if code in unique]


def describe_reasons(codes: list[str]) -> list[ReviewReasonOut]:
    described: list[ReviewReasonOut] = []
    for code in sanitise_reasons(codes):
        info = REASON_INFO[code]
        described.append(
            ReviewReasonOut(
                code=code,
                label=info.label,
                severity=info.severity,
                hint=info.hint,
            )
        )
    return described


def has_blocking_reason(codes: list[str]) -> bool:
    return any(
        REASON_INFO[code].severity == "blocking"
        for code in sanitise_reasons(codes)
    )
