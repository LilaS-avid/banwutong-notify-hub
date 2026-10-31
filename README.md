# 班务通

班级通知理解与报名提醒助手。当前仓库是角色 A 主导的第一版骨架，目标是先跑通一条可验证的纵向闭环，而不是一次接入所有平台。

## 已完成（已实测可用）

- 接收标准化通知消息并保留原文（`POST /api/messages`，返回 `created` / `updated` / `duplicate`）
- 使用规则提取活动名称、截止时间、对象、地点、材料和链接
- 按来源消息 ID 幂等：同一条消息重复投递不会重复建卡
- 本地 SQLite 持久化
- 响应式事项看板与完成状态
- 不依赖外部模型的离线解析基线
- 上传 TXT、Markdown、DOCX、PDF 和图片，原件保存在本地
- 图片和扫描 PDF 通过本机 RapidOCR 离线识别中英文，并继续生成事项
- 保存文档分页/段落结构，并允许一份文件整理出多个事项
- 支持可选的大模型结构化解析与原文证据定位
- 主页可切换云端模型和本地规则模式
- 主页底部 AI 对话入口，可打开独立对话页并结合当前事项问答
- 自动识别手机或窄屏设备，切换为触控优先的单列布局和底部导航
- 已完成事项可移入回收站，支持恢复或手动彻底删除；保留 7 天后自动清理

## 部分完成（能看，但还不能真正用）

| 功能 | 现在的样子 | 还缺什么 |
|---|---|---|
| **提醒** | `GET /api/reminders` 只能**查看**哪些事项快到期 | **没有任何发送实现，也没有定时任务**——到截止时间不会主动通知任何人 |
| 同一活动去重 | 只按标题匹配（已剥离“关于/的通知”等停用词） | 未实现 SRS 8.2 的 L1（链接优先）与 L3（相似度/包含） |
| 延期 / 补充 | 标题完全一致时才会更新原事项 | 同名不同期的两场活动无法拆开：`activities.dedupe_key` 带 UNIQUE 约束，要改表结构并迁移数据 |
| 待核对 | 只有 `needs_review` 标记 | 没有队列、没有界面、没有催办，标了也没人处理 |
| 版本历史 | 更新时直接覆盖 | 没有字段级对比，用户看不到“改之前是几号” |

## 已知问题

详见 `tests/test_dedupe.py`（按 SRS 8.2 / 8.3 写的验收用例，未通过的用 `xfail` 标注了原因）。当前 3 条已知不通过：

1. 「图书馆闭馆」与「图书馆电力检修闭馆」不会合并（L3 未实现）
2. 同名不同期的两场活动会被并成一条（受 `dedupe_key` UNIQUE 约束限制）
3. 延期通知的旧提醒不会失效（缺版本历史）


## 启动

双击桌面快捷方式“班务通”即可使用。若在其他电脑上首次使用，先双击项目里的
`安装班务通.cmd`；安装完成后桌面会自动生成快捷方式。

也可以在本项目中双击 `启动班务通.cmd`。

开发时使用命令行：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
uvicorn app.main:app --reload
```

打开 <http://127.0.0.1:8765>。页面可直接填入示例通知或上传文件，数据保存在 `data/class_notice.db`。

运行测试：

```powershell
pytest -q
```

## 标准消息

```json
{
  "platform": "manual",
  "external_id": "message-001",
  "group_id": "class-01",
  "sender_id": "teacher",
  "sent_at": "2026-10-24T16:00:00+08:00",
  "text": "活动名称：创新大赛\n报名截止：2026-11-05 18:00"
}
```

接口：

- `POST /api/messages`：导入消息，返回 `created`、`updated` 或 `duplicate`
- `POST /api/files`：上传文件并自动提取、整理事项
- `GET /api/files`：已上传文件列表
- `GET /api/files/{id}/blocks`：文档页、段落和表格结构
- `GET /api/files/{id}/download`：下载原始文件
- `GET /api/activities`：事项列表
- `POST /api/chat`：使用当前选择的模型直接对话
- `PATCH /api/activities/{id}`：修改完成或忽略状态
- `DELETE /api/activities/{id}`：将已完成事项移入回收站
- `GET /api/trash`：回收站事项列表
- `POST /api/activities/{id}/restore`：从回收站恢复事项
- `DELETE /api/trash/{id}`：立即彻底删除回收站事项
- `GET /api/reminders?days=7`：未来提醒
- `GET /health`：健康检查

## 目录

```text
app/
  main.py          FastAPI 入口
  parser.py        通知解析基线
  documents.py     文档文本与结构提取
  understanding.py 规则/大模型语义解析
  repository.py    SQLite 存取与去重更新
  schemas.py       对外数据契约
  static/          响应式前端
tests/             解析和 API 回归测试
docs/              角色 A 执行手册
```

## 当前边界

这个骨架先解决本地手工导入和单来源消息接入。PNG、JPG、JPEG、WEBP 图片会通过本机 RapidOCR 离线识别。PDF 按页处理：有文字层的页面直接读取，没有有效文字层的扫描页渲染为图片后再 OCR。DOCX 会提取段落和表格文字，但复杂版式仍可能丢失。

主页的“当前模型”可切换为云端模型或本地规则，选择保存在本地数据库中。云端未配置或调用失败时，文档提取自动回退到规则模式。

云端模式需要复制 `.env.example` 为 `.env`，并配置兼容 Chat Completions 的服务：

```text
BANWUTONG_LLM_BASE_URL=https://example.com/v1
BANWUTONG_LLM_MODEL=your-model
BANWUTONG_LLM_API_KEY=your-key
```

模型只接收文档文本和块定位符，返回严格 JSON；日期、URL 和重复活动仍由程序校验。文档被当作不可信数据，模型被要求忽略其中的指令。密钥不会提交到仓库。

QQ 机器人适配器正在做（账号已注册，AppID 已拿到；群消息权限与事件订阅尚未接通）。企业微信暂不做。正式接入必须使用平台允许的权限和公网 HTTPS 入口；个人微信非官方 Hook 不作为正式链路。

手机界面会按浏览器宽度和触控设备自动切换，不需要单独选择版本。当前桌面启动器默认只监听 `127.0.0.1`，所以同一局域网内的手机会面需要部署到云端，或自行把启动服务改为监听局域网地址并配置防火墙。

下一阶段的先后顺序（按“没有它 MVP 就不成立”排序）：

1. **提醒发送 + 定时任务**——现在只有查询接口，这一条不补，“截止前收到提醒”这个 MVP 指标就是 0
2. **真实来源适配器**（QQ 机器人，进行中）
3. **待核对队列**——只有标记、没有人工确认入口，等于没有
4. 云端部署（公网 HTTPS 入口，机器人回调与手机访问都依赖它）

具体执行方法见 [角色 A 执行手册](docs/role-a-playbook.md)。

## 本地开发

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m pytest -q      # 当前：42 passed, 3 xfailed
```

Windows 上 `tzdata` 是必需的（`ZoneInfo("Asia/Shanghai")` 依赖它），已在 requirements 中。
`Pillow` 也是测试必需（`tests/test_documents.py` 用它生成测试图片），已补进 requirements。
OCR 相关的两条测试需要 `rapidocr_onnxruntime`，装不上时可用 `-k "not ocr"` 跳过。
