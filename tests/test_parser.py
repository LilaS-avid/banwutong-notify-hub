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


def test_material_can_be_a_submission_channel() -> None:
    """「填在线文档」这种没写「材料」二字的，也要算报名材料。"""
    now = datetime(2026, 11, 3, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """通知】
1. 核酸信息统计表：截止11月4日中午12点，填在线文档。
注意：所有文件不要压缩打包。""",
        now,
    )

    assert parsed.materials == ["在线文档"]


def test_notice_note_lands_in_extra() -> None:
    """「注意：…」不属于固定字段，但要作为附加信息留下面。"""
    now = datetime(2026, 11, 3, 18, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """通知】
1. 核酸信息统计表：截止11月4日中午12点，填在线文档。
注意：所有文件不要压缩打包。""",
        now,
    )

    assert parsed.extra == "所有文件不要压缩打包"


def test_file_naming_rule_goes_to_extra_not_materials() -> None:
    """「文件命名格式：班级-姓名-学号」是要求，应该进附加信息。"""
    now = datetime(2026, 11, 3, 18, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """各位同学：
请于11月7日晚上21:00前提交《团员信息登记表》。
提交材料：Excel表格
文件命名格式：班级-姓名-学号""",
        now,
    )

    assert parsed.extra == "文件命名格式：班级-姓名-学号"
    assert all("命名" not in item for item in parsed.materials)


def test_naming_rule_inside_material_line_is_extracted() -> None:
    """命名格式跟材料写在同一行时也要认出来，并从材料里剔除。"""
    now = datetime(2026, 11, 3, 18, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """班级通知】
各位同学：
请大家在11月5日晚20:00前提交心理健康调查表。
需要提交材料：电子版表格，命名格式：姓名+学号。
提交渠道：发到群收集表。
逾期不再接收。""",
        now,
    )

    assert "文件命名格式：姓名+学号" in (parsed.extra or "")
    assert all("命名" not in item for item in parsed.materials)


def test_contradictory_material_instruction_is_flagged() -> None:
    """「不需要提交任何文件」和「提交一张截图」并存，必须标成待核对。"""
    now = datetime(2026, 11, 3, 19, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        "心理打卡截止时间：11月9日20:00，本次任务不需要提交任何文件，需要提交一张截图上传收集表。",
        now,
    )

    assert "material_conflict" in parsed.review_reasons
    assert parsed.needs_review is True


def test_simple_no_material_phrase_is_not_a_conflict() -> None:
    now = datetime(2026, 11, 3, 19, 45, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification("签到：11月9日20:00前在群里回复即可，不需要提交任何文件。", now)

    assert "material_conflict" not in parsed.review_reasons


def test_submission_channel_is_not_a_material() -> None:
    """收集表是「往哪儿交」，不能算材料；提交方式要写进附加信息。"""
    now = datetime(2026, 11, 3, 19, 58, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """提交党课学习心得，截止11月8日20:00。
材料：Word文档，命名：学号+姓名+党课心得，上传收集表。""",
        now,
    )

    assert parsed.materials == ["Word文档"]
    assert "文件命名格式：学号+姓名+党课心得" in (parsed.extra or "")
    assert "提交方式：将Word文档上传收集表" in (parsed.extra or "")


def test_zip_is_packaging_not_material() -> None:
    """压缩包是打包方式，材料只写包里装的文件。"""
    now = datetime(2026, 11, 3, 19, 50, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        """请提交社会实践全套材料，截止11月9日中午12点：
① 实践记录表（Word）
② 现场照片2张（jpg）
③ 简短心得（txt）
全部打包为一个zip压缩包上传
压缩包命名：姓名+学号+社会实践""",
        now,
    )

    assert parsed.materials == ["实践记录表（Word）", "现场照片2张（jpg）", "简短心得（txt）"]
    assert "打包要求：全部打包为一个zip压缩包上传" in (parsed.extra or "")
    assert "文件命名格式：姓名+学号+社会实践" in (parsed.extra or "")


def test_this_week_means_end_of_week() -> None:
    """「本周内」= 本周结束，即下周一 00:00，不是本周日 00:00。"""
    tuesday = datetime(2026, 11, 3, 20, 12, tzinfo=ZoneInfo("Asia/Shanghai"))

    parsed = parse_notification("请大家本周内提交阅读摘抄照片，jpg，命名姓名，上传收集表。", tuesday)
    assert parsed.deadline == "2026-11-09T00:00:00+08:00"

    weekend = parse_notification("本周末前交读书笔记", tuesday)
    assert weekend.deadline == "2026-11-08T23:59:00+08:00"

    friday = parse_notification("本周五交读书笔记", tuesday)
    assert friday.deadline == "2026-11-06T23:59:00+08:00"


def test_supplement_titles_share_dedupe_key() -> None:
    """「补充通知」不能另立门户，要和原通知算同一个事项。"""
    from app.parser import normalise_key

    assert normalise_key("上交读书笔记") == normalise_key("上交读书笔记（补充通知）")
    assert normalise_key("社会实践报告") == normalise_key("补充：社会实践报告更正通知")


def test_near_duplicate_materials_are_collapsed() -> None:
    """同一份「Word文档」换个说法不能再占一行。"""
    from app.parser import dedupe_materials

    assert dedupe_materials(["Word文档", "思想汇报 Word 文档"]) == ["Word文档"]
    assert dedupe_materials(["本人手写签字的照片（jpg）", "照片"]) == ["本人手写签字的照片（jpg）"]
    assert dedupe_materials(["Word文档", "图片"]) == ["Word文档", "图片"]


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



def test_long_single_line_notice_gets_short_title() -> None:
    # 一条通知如果只有一行，之前会把整段话（80 字）当标题，卡片标题要折三行。
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        "【班级通知】关于秋季研学的报名说明：请各位家长于2026年11月8日18:00前"
        "提交研学活动回执，报名材料为回执单和保险确认书，地点：学校东门集合。",
        now,
    )

    assert parsed.title == "关于秋季研学的报名说明"
    assert "【" not in parsed.title
    assert len(parsed.title) <= 30


def test_unpunctuated_long_title_is_clipped() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification(
        "请于2026年11月10日中午12点前上交社会实践表格并附家长签字确认页交至团委办公室",
        now,
    )

    assert parsed.title.endswith("…")
    assert len(parsed.title) <= 31


def test_short_title_is_left_alone() -> None:
    now = datetime(2026, 10, 24, 10, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
    parsed = parse_notification("【重要】校园歌手大赛报名", now)

    assert parsed.title == "校园歌手大赛报名"
