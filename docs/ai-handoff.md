# AI 接手须知（先读这一页）

> 面向：接手本仓库的任何 AI 编程助手。
> 维护者：成员 C（数据与解析评估）　最后更新：2026-11-01
> 人类读者可看 [阶段成果说明](阶段成果说明.md)；逐条改动记录见 [变更说明-成员C](变更说明-成员C.md)。

---

## 0. 30 秒状态

**已跑通**（云服务器上真实运行）：QQ 群消息（不 @）→ 机器人 → 后端 → 云端大模型抽取 → SQLite 落库 → 看板。
**没做**：提醒发送（到截止不会通知任何人）、待核对队列、HTTPS/域名、数据库备份、同名不同期活动拆卡。

**当前瓶颈不是"接入"，是"读懂"和"提醒"。** 改代码前先确认你要解决的是不是这两个。

---

## 1. 运行环境（生产）

| 项 | 值 |
| --- | --- |
| 主机 | Windows 云服务器，单机同时跑后端与机器人 |
| 安装目录 | `C:\banwutong` |
| 后端 | `uvicorn app.main:app --host 127.0.0.1 --port 8765` |
| 机器人 | `python -m scripts.run_qq_bot` |
| 数据库 | `C:\banwutong\data\class_notice.db`（SQLite 单文件） |
| 后端日志 | `logs\backend.log` / `logs\backend.err.log` |
| 机器人日志 | **`logs\bot.err.log`**（botpy 走 stderr；`bot.log` 只有脚本 print） |
| 开机自启 | schtasks 任务 `Banwutong-AutoStart`，SYSTEM 身份 |
| 部署步骤 | [cloud-deploy.md](cloud-deploy.md) |

## 2. 数据流

```
QQ 群消息（不 @ 也能收到，需群主开「接收全量消息」）
   ↓ GROUP_MESSAGE_CREATE / GROUP_AT_MESSAGE_CREATE / C2C_MESSAGE_CREATE
scripts/run_qq_bot.py     连接层：鉴权、WebSocket、心跳、重连
   ↓
app/qq_adapter.py         转换层：平台事件 → 后端消息（纯函数，无凭证）
   ↓ POST /api/messages
app/main.py               FastAPI 入口
   ↓
app/understanding.py      规则解析 或 云端大模型解析（取决于 model_provider 设置）
   ↓
app/repository.py         去重（dedupe_key）、合并、落库
   ↓
app/static/               看板
```

## 3. 硬约束（改之前先读，不然会踩回去）

### 3.1 一个 AppID 只能有一个实例

同一个 `QQBOT_APPID` 同时跑两个机器人进程（比如本地 + 服务器），会互相踢下线，表现为消息时有时无。
**任何"本地也跑一份试试"的操作都会破坏生产。**

### 3.2 这些代码是"故意这么写"的，别顺手简化

| 位置 | 不要动 | 删掉的后果 |
| --- | --- | --- |
| `app/parser.py` → `_DEDUPE_STOPWORDS` | 可加词，**不可删** | 同一活动换标题又变两张卡 |
| `app/parser.py` → `_detect_change` 里"取消"后的排除正则 `^(后\|不\|资格\|评优\|加分\|其)` | 不可删 | 「报名取消后不退费」会把整条通知标成已取消 |
| `scripts/run_qq_bot.py` → `_install_full_group_message_support` | 不可删 | botpy 1.2.1 没有 `GROUP_MESSAGE_CREATE` 解析器，群内全量消息会被当未知事件丢弃 |
| `tests/test_dedupe.py` → 三处 `xfail` | 不要为了"全绿"删标记 | 它们是已知缺陷的记录，修好后自动转通过 |
| `app/db.py:24` `dedupe_key ... UNIQUE` | 改动需迁移，先看 §5.1 | 直接改会导致同名活动插不进第二条 |

### 3.3 密钥与配置

- `.env` 已在 `.gitignore`，**任何情况下不要提交、不要写进代码、不要打印到日志**。
- 敏感项：`QQBOT_SECRET`、`BANWUTONG_LLM_API_KEY`。
- 调试日志里会出现 access_token，**不要贴到公开渠道**。

## 4. 怎么跑起来（本地）

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt          # 核心
pip install -r requirements-bot.txt      # 仅机器人需要

python -m pytest -q                      # 期望：53 passed, 3 xfailed
                                          # 若未装 rapidocr，会多 1 条 OCR 用例 failed（环境问题，不是代码缺陷）

uvicorn app.main:app --reload            # 后端
python -m scripts.run_qq_bot --dry-run   # 机器人（只打印不落库）
```

## 5. 已知缺陷（带证据，别重复排查）

### 5.1 同名不同期的两场活动会被并成一条

- 现象：两场都叫「学术讲座」、隔一周，会被合并，第二场消失
- 根因：`app/db.py:24` 的 `dedupe_key TEXT NOT NULL UNIQUE` 是库级唯一约束；应用层加时间护栏会撞 `sqlite3.IntegrityError`
- 修法：**需要改表结构 + 迁移数据**（拆成非唯一索引 + 应用层 L2 判定），属架构决策
- 对应测试：`tests/test_dedupe.py::test_same_title_different_period_creates_two_activities`（xfail）

### 5.2 链接优先（L1）与相似度（L3）匹配未实现

- 现象：「图书馆闭馆」与「图书馆电力检修闭馆」不会合并（相似度 0.71 < 0.85 阈值）
- 修法：加"规范化后按顺序包含且短名 ≥4 字 → 判同一"规则 + 链接规范化比对
- 对应测试：`test_same_activity_with_extra_reason`、`test_same_activity_with_about_prefix`（xfail）

### 5.3 截止时间会取到时间区间的开头

- 现象：「10月19日至10月24日…请于11月1日前反映」被抽成 `10月19日`
- 影响：提醒时间可能早 13 天
- 修法：日期解析重构（属高风险改动，尚未动）

### 5.4 提醒完全不发送

- 现象：`GET /api/reminders` 只能查询；没有发送实现、没有调度器
- 影响：**MVP 硬指标不达标**——到截止时间不会通知任何人
- 建议：新增独立模块（`app/reminders/`），**不需要改 parser.py 与 repository.py**

### 5.5 更新无版本历史

- 现象：延期/补充直接覆盖原记录，看不到"改之前是几号"
- 影响：T04「旧提醒失效」无法验证

## 6. 待办优先级（按"没有它 MVP 不成立"排）

| # | 事项 | 验收标准 |
| --- | --- | --- |
| 1 | 提醒发送 + 定时任务 | 截止前 24h 能收到提醒；活动延期后旧提醒不再触发 |
| 2 | 待核对队列（界面 + 确认） | 置信度低的事项能人工确认后转可办 |
| 3 | 云端 HTTPS + 域名 | 手机能访问并安装 PWA |
| 4 | 数据库定时备份 | 删除数据库后能从备份恢复 |
| 5 | 同名不同期拆卡（§5.1） | 两场同名不同期活动保持独立 |
| 6 | L1/L3 匹配（§5.2） | SRS 8.2 的 15 组用例自动合并 ≥90%、误合并 0 |

## 7. 改完怎么自证

```powershell
python -m pytest -q           # 不允许比改动前更差
curl http://127.0.0.1:8765/health                       # {"status":"ok"}
curl http://127.0.0.1:8765/api/model-settings           # provider 是否 cloud
python -m app.qq_adapter --replay samples/qq_events.jsonl --dry-run   # 期望 5 读入 / 3 转换 / 2 跳过
```

**提交前必须**：`git pull` 一次（团队可能有人在你之前改过同一文件）。

## 8. 关键决策记录（为什么长这样）

| 决策 | 原因 |
| --- | --- |
| 去重键先剥停用词 | 「关于…的通知」这类前后缀会让同一活动变两张卡（实测 4/5 用例不符 SRS） |
| `_detect_change` 排除"取消后/取消资格" | 「取消后不退费」「取消评优资格」是规则说明，不是活动取消 |
| 群内全量消息要打补丁 | 官方 botpy 1.2.1 只解析 `GROUP_AT_MESSAGE_CREATE`；不打补丁会丢非 @ 消息 |
| 云端模型而非纯规则 | 真实群消息是自由文本，规则版只认「报名截止：…」；实测真实集仅 46 分 |
| 纯图片消息直接跳过 | 未接 OCR，转成文字只会生成一张叫「[图片]」的垃圾卡片 |
| `registration_method` 无报名环节时置 null | 「按班级整队入场」「找学习部反映」不是报名方式 |

## 9. 术语与口径

| 术语 | 含义 |
| --- | --- |
| 事项 / 活动 | 一条通知整理出的一张卡片（`activities` 表一行） |
| 去重键 `dedupe_key` | 标题规范化后的字符串，用于判断是否同一活动 |
| 幂等 | 同一条消息重复投递只落一条（按 `external_id`） |
| 待核对 `needs_review` | 关键字段缺失或校验失败，需人工确认 |
| 规则版 / 云端 | `model_provider` 的两种取值：本地正则 vs 大模型 |

## 10. 与需求文档的关系

- 需求规格说明书是唯一验收依据（SRS 8.2 同一性判定、8.3 变更类型、附录 A 字段）
- **附录 A 要求每字段带 `confidence`，目前未实现**；本文提到的 `duplicate` 类型、`related_activity_id` 不在附录 A 里（属实现层扩展）
- 对齐附录 A 是一次独立的返工任务，不要顺手改一半
