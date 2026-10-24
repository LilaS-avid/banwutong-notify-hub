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

打开 <http://127.0.0.1:8000>。页面可直接填入示例通知，数据保存在 `data/class_notice.db`。

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
- `GET /api/activities`：事项列表
- `PATCH /api/activities/{id}`：修改完成或忽略状态
- `GET /api/reminders?days=7`：未来提醒
- `GET /health`：健康检查

## 目录

```text
app/
  main.py          FastAPI 入口
  parser.py        通知解析基线
  repository.py    SQLite 存取与去重更新
  schemas.py       对外数据契约
  static/          响应式前端
tests/             解析和 API 回归测试
docs/              角色 A 执行手册
```

## 当前边界

这个骨架先解决本地手工导入和单来源消息接入。QQ、企业微信等真实机器人适配器还没有加入；正式接入必须使用平台允许的权限和公网 HTTPS 入口。个人微信非官方 Hook 不作为正式链路。

下一阶段按顺序增加：真实来源适配器、相对日期增强、附件保存与 OCR、可靠提醒渠道、云端部署。具体执行方法见 [角色 A 执行手册](docs/role-a-playbook.md)。
