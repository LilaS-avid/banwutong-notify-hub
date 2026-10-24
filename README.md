# 班务通

班级通知理解与报名提醒助手。当前仓库是角色 A 主导的第一版骨架，目标是先跑通一条可验证的纵向闭环，而不是一次接入所有平台。

## 已实现

- 接收标准化通知消息并保留原文
- 使用规则提取活动名称、截止时间、对象、地点、材料和链接
- 按来源消息 ID 幂等处理重复消息
- 同一活动收到延期或补充通知时更新原事项
- 本地 SQLite 持久化
- 响应式事项看板、完成状态和未来提醒查询
- 不依赖外部模型的离线解析基线
- 上传 TXT、Markdown、DOCX、PDF 和图片，原件保存在本地
- 图片和扫描 PDF 通过本机 RapidOCR 离线识别中英文，并继续生成事项
- 保存文档分页/段落结构，并允许一份文件整理出多个事项
- 支持可选的大模型结构化解析与原文证据定位
- 主页可切换云端模型和本地规则模式
- 主页底部 AI 对话入口，可打开独立对话页并结合当前事项问答
- 自动识别手机或窄屏设备，切换为触控优先的单列布局和底部导航
- 已完成事项可移入回收站，支持恢复或手动彻底删除；保留 7 天后自动清理

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

QQ、企业微信等真实机器人适配器还没有加入；正式接入必须使用平台允许的权限和公网 HTTPS 入口。个人微信非官方 Hook 不作为正式链路。

手机界面会按浏览器宽度和触控设备自动切换，不需要单独选择版本。当前桌面启动器默认只监听 `127.0.0.1`，所以同一局域网内的手机会面需要部署到云端，或自行把启动服务改为监听局域网地址并配置防火墙。

下一阶段按顺序增加：真实来源适配器、可靠提醒渠道、云端部署。具体执行方法见 [角色 A 执行手册](docs/role-a-playbook.md)。
