# QQ 机器人接入

> 负责人：成员 C + 光钰（B）　状态：文字、图片、文件收发已跑通，机器人会回执
> 相关：`app/qq_adapter.py`（转换层）、`app/qq_media.py`（附件）、`app/qq_handler.py`（一条消息的完整处理）、`scripts/run_qq_bot.py`（连接层）、`samples/qq_events.jsonl`

## 一、现在的进度

| 步骤 | 状态 | 说明 |
|---|---|---|
| 1. 注册机器人，拿 AppID / AppSecret | 已完成 | 个人主体，创建人 QQ 号决定群权限 |
| 2. 私聊验证链路 | **已跑通**（2026-10-31） | `C2C_MESSAGE_CREATE` 事件收到，转换后 `201 created` |
| 3. 拉进群 + 开「接收全量消息」 | **已跑通**（2026-10-31） | 群里**不 @** 机器人也能收到 `GROUP_MESSAGE_CREATE`，这是本产品成立的前提 |
| 4. 事件 → 后端消息 | 已完成 | `app/qq_adapter.py`，已用真实报文验证 |
| 5. 图片 / 文件 → AI 解析 | **已跑通**（2026-11-02） | 群里发图或文件，机器人下载后转给 `/api/files`：OCR + 文档抽取 + 云端模型，解析结果入库 |
| 6. 机器人回消息 | **已跑通**（2026-11-02） | 被动回复（`msg_id` + `msg_seq`），5 分钟窗口内；一条消息只回一条 |
| 7. 字段抽取质量 | 取决于模型 | 云端模型可用时走 AI；不可用时退回规则解析，回执里不会假装是 AI 结果 |

> 结论：**文字、图片、文件三种入口都已打通**，瓶颈在"读懂通知"的准确率，不在接入。


## 二、拉群时必须勾的那个开关

QQ 官方 FAQ 写明：个人主体的机器人**只能进"创建人自己是群主/管理员"的群**，
且必须用**最新版手机 QQ** 添加（网页端不行）。

添加时点「设置权限」，有三个开关：

1. **接收全量消息** ← **必须打开**。不打开的话机器人只能收到 @ 它的消息，
   用户每次发通知都得 @ 一下，体验差很多。
2. 主动推送消息（提醒要用，见第三节）
3. 撤回成员消息（本项目不需要）

## 三、三个平台限制（会直接影响产品设计）

| 限制 | 数值 | 影响 |
|---|---|---|
| 主动消息配额 | 每群 60 条/分钟、**1000 条/群/天** | 提醒不能只靠机器人；而且用户可以关掉「允许主动发送」 |
| 被动回复窗口 | 群聊 5 分钟、每条最多回 5 次 | 收到消息后要及时回，过了窗口就不能主动回 |
| 消息重复推送 | 同一 `msg_id` 可能推多次 | 必须按 `external_id` 幂等（后端已支持） |

## 四、转换层的字段映射

平台事件 → 后端 `POST /api/messages`：

| 后端字段 | 从平台取 | 备注 |
|---|---|---|
| `platform` | 固定 `"qq"` | |
| `external_id` | `d.id`（消息 ID） | **去重靠它**；平台重推时保持稳定 |
| `group_id` | `d.group_openid` | 私聊事件为 `null` |
| `sender_id` | `d.author.member_openid` 或 `author.user_openid` | 群里是 member，私聊是 user |
| `sent_at` | `d.timestamp` | ISO8601 带 +08:00；缺失会让相对时间算错 |
| `text` | `d.content` | 会去掉 `<@!机器人ID>` 这种提及前缀 |

支持的事件类型：`GROUP_AT_MESSAGE_CREATE`、`GROUP_MESSAGE_CREATE`、
`C2C_MESSAGE_CREATE`、`AT_MESSAGE_CREATE`。其他事件（入群、撤回等）直接跳过。

## 四之二、图片和文件怎么进 AI

平台把图片/文件放在事件的 `d.attachments` 里（不是 `message_type`），每条带
`url`（**带签名的临时链接，会过期**）、`filename`（可能为空）、`content_type`、`size`。

机器人的处理链（`app/qq_handler.py` → `app/qq_media.py`）：

```
收到消息
  ├─ 有文字 → POST /api/messages        （闲聊会被后端判成 chat，不建卡）
  └─ 有附件 → 下载 → POST /api/files    （OCR + 文档抽取 + 云端模型解析）
                     ↓
              拼一条中文回执，用 msg_id + msg_seq 被动回复
```

| 项目 | 规则 |
|---|---|
| 支持格式 | PDF、Word(.doc/.docx)、Excel(.xlsx/.xlsm)、PPT(.pptx)、TXT/MD/CSV/JSON/HTML/RTF、PNG/JPG/WEBP；GIF 取首帧转 PNG |
| 大小上限 | 20MB（和后端 `/api/files` 一致，超了本地先挡，回一句提示） |
| 每条消息 | 最多处理 5 个附件，防止一次甩 50 张图把机器人拖死 |
| 去重 | 后端按 `sha256` 去重，同一张图再发一次回「之前已经处理过」 |
| 没有文件名 | 按 `content_type` 补扩展名（图片叫 `QQ图片.png`，文档叫 `QQ文件.pdf`） |
| 读不出文字 | 回「文件已存档，可到网页端手动补充」，不会生成空卡片 |

回执长这样（一条消息一条回执，最多 900 字）：

```
《奖学金通知.png》已交给 AI 解析，识别到 1 项：
1）国家励志奖学金评定工作｜截止 11月12日 23:59｜材料 申请表、成绩单
```

文字通知的回执规则由 `QQBOT_REPLY_TEXT` 控制：`created`（默认，只在新建事项时回）、
`always`（每次都回）、`never`（只处理不回）。图片/文件的回执不受这个开关影响。

## 五、怎么在没有账号的情况下自测

```powershell
# 只看转换结果，不连后端
python -m app.qq_adapter --replay samples/qq_events.jsonl --dry-run

# 转换并投递到本地后端
python -m app.qq_adapter --replay samples/qq_events.jsonl --post http://127.0.0.1:8765
```

样例文件里放了 5 条事件：群 @ 消息、群普通消息、纯图片、私聊、以及一条无关事件（应被跳过）。
转换结果应为：**5 条读入，3 条转换，2 条跳过**。

## 五之二、有账号之后怎么跑真机器人

连接层已经写好：`scripts/run_qq_bot.py`。它负责鉴权、WebSocket、心跳和重连，
转换仍然交给 `app/qq_adapter.py`。

```powershell
python -m pytest tests/test_qq_media.py tests/test_qq_handler.py -q   # 附件与回执，全程离线
python -m app.qq_adapter --replay samples/qq_events.jsonl --dry-run
python -m scripts.run_qq_bot --dry-run                                # 只打印真实事件，不写库不回消息
```

题外：`samples/qq_events.jsonl` 里那条纯图片事件默认仍被 `to_message_in` 跳过；
连接层会带 `require_text=False` 再取一次，走附件通道。

## 五之二、有账号之后怎么跑真机器人

连接层已经写好：`scripts/run_qq_bot.py`。它负责鉴权、WebSocket、心跳、重连和回复，
转换交给 `app/qq_adapter.py`，附件交给 `app/qq_media.py`。

```powershell
pip install -r requirements-bot.txt        # 只装机器人依赖，核心服务不需要
# .env 里填 QQBOT_APPID / QQBOT_SECRET
python -m scripts.run_qq_bot --dry-run     # 先只打印收到的消息
python -m scripts.run_qq_bot               # 再真正写入后端并回执
```

> **踩过的坑（2026-11-02）**：图片 OCR 报
> `DLL load failed while importing onnxruntime_pybind11_state: 找不到指定的模块`。
> 原因是这台机器只装了 VC++ 2015/2017 运行库（`msvcp140.dll` 停在 14.00.24215），
> 新版 onnxruntime 需要 `vcruntime140_1.dll` / `msvcp140_1.dll` / `msvcp140_2.dll`。
> 解决：装一次 **VC++ 2015-2022 x64 运行库**（`vc_redist.x64.exe`，本次装到 14.44），
> 装完重启后端进程即可。装完用 `python -c "import onnxruntime; print(onnxruntime.__version__)"` 验证。

> **踩过的坑**：官方 SDK（botpy 1.2.1）**没有群内全量消息的解析器**，只支持 @ 消息。
> `scripts/run_qq_bot.py` 在启动时补了一个解析器（`_install_full_group_message_support`），
> 否则群里不 @ 机器人的通知会被当作未知事件丢掉。这条有测试覆盖（`tests/test_qq_runner.py`）。


## 六、拿到真实报文后要做什么

> **已完成（2026-10-31）**：真实事件已到手，字段名与文档一致（`d.id` / `d.content` /
> `d.group_openid` / `d.author.member_openid` / `d.author.user_openid` / `d.timestamp`），
> 转换层无需改动。真实报文样本待脱敏后补进 `samples/`。

## 七、后续（先不做，别忘）

- **主动提醒**：受第三节的配额限制，群聊主动消息还要群里开着「允许主动发送」。
  目前提醒只走 Web Push / 邮件 / Webhook，机器人只做被动回复。
- **机器人主动发文件/图片**：botpy 1.2.1 的 `post_group_file` 只接受 `url`，
  而平台已支持二进制直传（≤5MB）和分片上传；要用得自己拼 `/v2/groups/{id}/files` 请求。
- **多群支持**：现在 `group_id` 只存不区分，多班使用时需要按群分组。

## 八、安全

- `AppSecret` 只放本地 `.env`，**不要提交、不要截图发群**。
- 已经泄露过一次的话，去控制台重置，旧 Secret 立即失效。
- 转换层不含任何凭证，可以随意分享。
