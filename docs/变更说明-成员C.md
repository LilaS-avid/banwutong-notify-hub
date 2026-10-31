# 变更说明：成员 C 对班务通仓库的改动

> 写给**人**（队友、指导教师）和**AI 工具**（后续接手改代码的任何模型）各一半。
> 人看第一~五节，AI 直接看第六节。
> 作者：成员 C（数据与解析评估）　日期：2026-10-31
> 涉及提交：`894a430`（代码）、`5bd2308`（README）、`8783d15`（交接说明）

---

## 一、一页速览

| 项 | 内容 |
|---|---|
| 改了几处 | 3 处判定逻辑 + 1 个缺失依赖 + 1 份验收用例 + 1 次 README 重写 |
| 改动性质 | **纯字符串规则**，未改接口、未改数据结构、未改前端 |
| 改前测试 | 32 passed（另有 1 条 OCR 用例因本机未装 `rapidocr_onnxruntime` 失败） |
| 改后测试 | **42 passed, 3 xfailed**（同样 1 条 OCR 用例在本机失败，原因见下） |
| 已验证范围 | 12 条真实通知（脱敏）+ 接口手测；**未接真实 QQ 机器人** |
| 未修的问题 | 3 个（见第五节），都写明了原因 |

**一句话总结**：修掉了三个"会把正常通知判错"的 bug，补上了缺失的依赖和测试，
并让 README 的进度描述和实际情况对齐。

---

## 二、改动清单

### 1. 去重键剥离无效词（`app/parser.py` → `normalise_key`）

| 项 | 说明 |
|---|---|
| 原来 | 只去掉标点和空格，然后拿标题做精确比对 |
| 问题 | 「关于国家励志奖学金评定工作的通知」和「国家励志奖学金评定」被当成两件事，同一活动建两张卡片，用户收到两次提醒 |
| 现在 | 先去重前剥掉「关于 / 的通知 / 通知 / 报名 / 提醒 / 工作」，以及 `【】`、`1.` 这类前缀，再比对 |
| 影响面 | 只影响"两条通知算不算同一活动"，不影响字段抽取 |
| 验证 | `pytest tests/test_dedupe.py -k scholarship -v` |

### 2. 变更类型词表补「延长」「改到」（`app/parser.py` → `_detect_change`）

| 项 | 说明 |
|---|---|
| 原来 | 词表是「延期 / 推迟 / 调整 / 补充 / 更正 / 改为 / 变更」 |
| 问题 | 「报名截止时间**延长**至11月12日」不含上述任何词，被判成新通知 → 新建一张卡，**旧卡继续按旧日期提醒用户** |
| 现在 | 补入「延长」「改到」 |
| 影响面 | 只影响消息被归为 new 还是 update |
| 验证 | `pytest tests/test_dedupe.py -k extension -v` |

### 3.「取消」不再一律判为取消（`app/parser.py` → `_detect_change`）

| 项 | 说明 |
|---|---|
| 原来 | 只要正文出现「取消 / 终止 / 暂停」，整条消息判 cancel，活动状态直接置为已取消 |
| 问题 | 「报名**取消**后不退费」「一经查实**取消**评优及加分资格」这类规则说明，会让一条正常的报名通知变成灰色废弃卡片，用户完全看不到 |
| 现在 | 先看「取消」后面跟什么：跟「后 / 不 / 资格 / 评优 / 加分 / 其」的不判 cancel，按正常流程走 |
| 影响面 | 只影响取消判定 |
| 局限 | **启发式规则**，换个说法（如"经研究决定，取消本次讲座"）仍可能漏，见第五节 |
| 验证 | `pytest tests/test_dedupe.py -k cancel -v` |

### 4. 补缺失依赖（`requirements.txt`）

| 项 | 说明 |
|---|---|
| 问题 | `tests/test_documents.py` 用 `PIL`（Pillow）生成测试图片，但 Pillow 不在依赖清单里 |
| 后果 | 任何人 clone 后执行 `pip install -r requirements.txt && pytest`，会在**收集阶段**直接失败，容易被误判成"代码坏了" |
| 现在 | 补 `Pillow>=10` |

### 5. 重写 README 的进度描述（`README.md`）

| 项 | 说明 |
|---|---|
| 原来 | 一段「已实现」共 21 条，其中几条实际只做了一半（最典型：提醒只有查询接口，没有发送） |
| 风险 | 队友按 README 排期，会误以为 MVP 就差一点，实际差最关键的一块 |
| 现在 | 拆成「已完成 / 部分完成 / 已知问题」三段；「下一阶段」按"没有它 MVP 就不成立"排序 |

### 6. 新增验收用例（`tests/test_dedupe.py`）

- **13 条**用例，依据 SRS 8.2（同一性判定 L1–L5）与 8.3（变更类型判定）
- **10 条现已通过**，覆盖：消息级幂等、同一活动合并、不同活动不合并、延期仍更新原事项、取消误判、评优资格类文字
- **3 条标记 `xfail`**，是已知缺陷的显式记录（不是测试写错），原因逐条写在用例上
- 实测：`pytest tests/test_dedupe.py -q` → `10 passed, 3 xfailed`

---

## 三、行为对比（真实例子）

| 输入 | 改前 | 改后 |
|---|---|---|
| 「关于国家励志奖学金评定工作的通知」+「国家励志奖学金评定」 | 两条活动，两张卡 | **合并为一条** |
| 「报名截止时间延长至11月12日」（已有原活动） | 新建一张卡；旧卡按旧日期提醒 | **更新原活动** |
| 「本月活动报名取消后不退费」 | 整条标为**已取消**，用户看不到 | **正常创建** |
| 「...取消评优及加分资格」 | 整条标为已取消 | **正常创建** |
| 同一条消息投递两次 | 返回 `duplicate` | 不变（本来就对） |
| 同名不同期的两场讲座 | 合并成一条，第二场丢失 | **未修**（见表后说明） |

---

## 四、请不要动的地方

这几段看起来"可以简化"，但删掉会把 bug 放回来。**改动前先读原因。**

| 位置 | 不要动什么 | 删掉的后果 |
|---|---|---|
| `normalise_key` → `_DEDUPE_STOPWORDS` | 常量里的词 | 可以加词，**不要删**。删「的工作」等词，同一活动会重新变成两张卡 |
| `_detect_change` → 排除正则 `^(后\|不\|资格\|评优\|加分\|其)` | 这张排除表 | 「取消后不退费」会再次把整条通知标成已取消 |
| `tests/test_dedupe.py` → `xfail` 标记 | 不要为了"让测试全绿"而删除 | 那是已知缺陷的记录；修好对应功能后它们会自动转通过，届时再删标记 |

---

## 五、没修的问题（明确边界）

**1. 同名不同期的两场活动，仍会被并成一条**
- 原因：`app/db.py:24` 的 `dedupe_key TEXT NOT NULL UNIQUE` 是数据库级唯一约束，同名活动插不进第二条
- 我试过在应用层加时间护栏，结果撞上这个约束（`sqlite3.IntegrityError`），已回退
- 要修必须**改表结构 + 迁移已有数据**，属于架构决策，留给 A

**2.「图书馆闭馆」与「图书馆电力检修闭馆」不会合并**
- 原因：SRS 8.2 的 L1（链接优先）与 L3（相似度 ≥0.85）都没实现
- 这两者相似度只有 0.71，按阈值判不出来
- 规则方案已想好（较短方 ≥4 字 + 按顺序包含 → 判同一），但**阈值要用真实样本调**，不宜拍脑袋定

**3. 截止时间会取到时间区间的开头**
- 例：「10月19日至10月24日…请于11月1日前反映」会被抽成 `10月19日`，早了 13 天
- 这要重构日期解析，风险高于本次三处改动，**没有动**

---

## 六、给 AI 的摘要（结构化）

```yaml
repo: LilaS-avid/banwutong-notify-hub
author_of_changes: 成员C（数据与解析评估）
commits: [894a430, 5bd2308, 8783d15]
baseline_commit: 8be1aba

changed_files:
  - path: app/parser.py
    functions: [normalise_key, _detect_change]
    kind: behavior_change（纯字符串规则）
    invariants:
      - 函数签名未变，调用方无需调整
      - 返回值类型未变
  - path: requirements.txt
    change: 追加 Pillow>=10
  - path: README.md
    change: 重写"已实现/当前边界"两节，未改技术内容
  - path: tests/test_dedupe.py
    change: 新增文件，13 条用例，其中 3 条 xfail
  - path: docs/ai-handoff.md
    change: 新增文件
  - path: docs/变更说明-成员C.md
    change: 新增文件（本文件）

do_not_change:
  - _DEDUPE_STOPWORDS 中的词（可追加，不可删除）
  - _detect_change 中 "取消" 后的排除正则
  - tests/test_dedupe.py 中的 xfail 标记（除非对应功能已实现）

known_failing_by_design:
  - test_same_activity_with_about_prefix      # 需要 L1/L3
  - test_same_activity_with_extra_reason      # 需要 L1/L3
  - test_same_title_different_period_creates_two_activities  # 需要改表结构

verification:
  - run: python -m pytest -q
    expect: "42 passed, 3 xfailed"
    note: 若未安装 rapidocr_onnxruntime，会另有一条 tests/test_documents.py 的 OCR 用例 failed，属环境缺依赖，非代码缺陷
  - run: python -m pytest tests/test_dedupe.py -q
    expect: "10 passed, 3 xfailed"

open_decisions_for_A:
  - activities.dedupe_key 的 UNIQUE 约束是否解除（需迁移）
  - 是否实现 SRS 8.2 L1(链接) / L3(相似度)，阈值取多少
  - 截止时间区间取端点是否重构
  - 提醒发送与定时任务（当前完全缺失，MVP 硬缺口）

not_verified:
  - 未接入真实 QQ 机器人，未见过真实群消息报文
  - 真实样本仅 12 条（脱敏）
```

### AI 接手时的建议顺序

1. 先跑 `python -m pytest -q`，确认基线是 `42 passed, 3 xfailed`
2. 读本文档第四、五节，确认哪些不能动、哪些不用重复做
3. 若要做"提醒发送"（第六节 open_decisions 第 4 条），**不需要碰** `parser.py` 与 `repository.py`，可独立开新模块
4. 若一定要改 `dedupe_key` 约束，先开分支，别直接改 main

---

## 七、证据与可复现

| 材料 | 位置 |
|---|---|
| 12 条真实通知样本（脱敏）与标准答案 | 成员 C 工作区 `bangwutong-c/data/corpus.jsonl`（N051–N062） |
| 去重行为核验脚本 | `bangwutong-c/src/audit_team_repo.py` |
| 缺陷核验报告 | `bangwutong-c/out/A实现核验报告.md` |
| 标注口径与争议裁定 | `bangwutong-c/docs/标注规范.md` |

> 说明：以上文件在成员 C 的本地工作区，未放入本仓库，避免测试数据与产品代码混在一起。
> 需要时可直接向 C 索取。
