# QQ 机器人接入

> 负责人：成员 C + 光钰（B）　状态：账号已注册，适配器转换层已完成，等待真实报文校准
> 相关：`app/qq_adapter.py`（转换层）、`tests/test_qq_adapter.py`、`samples/qq_events.jsonl`

## 一、现在的进度

| 步骤 | 状态 | 说明 |
|---|---|---|
| 1. 注册机器人，拿 AppID / AppSecret | 已完成 | 个人主体目前只能有一个创建人，权限绑在他的 QQ 号上 |
| 2. 私聊验证链路 | **待做** | 用创建人 QQ 私聊机器人，确认能收到事件 |
| 3. 拉进群 + 开「接收全量消息」 | **待做** | 见下面第二节，这一步决定产品形态 |
| 4. 事件 → 后端消息 | **代码已完成** | `app/qq_adapter.py`，用样例事件测过，等真实报文校准 |

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
pip install -r requirements-bot.txt        # 只装机器人依赖，核心服务不需要
# .env 里填 QQBOT_APPID / QQBOT_SECRET
python -m scripts.run_qq_bot --dry-run     # 先只打印收到的消息
python -m scripts.run_qq_bot               # 再真正写入后端
```

> **踩过的坑**：官方 SDK（botpy 1.2.1）**没有群内全量消息的解析器**，只支持 @ 消息。
> `scripts/run_qq_bot.py` 在启动时补了一个解析器（`_install_full_group_message_support`），
> 否则群里不 @ 机器人的通知会被当作未知事件丢掉。这条有测试覆盖（`tests/test_qq_runner.py`）。


## 六、拿到真实报文后要做什么

1. 把真实事件原样存成 `samples/real_events.jsonl`（**注意脱敏：`group_openid`、`member_openid` 可保留，正文里的手机号/姓名要替换**）
2. `python -m app.qq_adapter --replay samples/real_events.jsonl --dry-run`，检查 6 个字段有没有取到
3. 若字段名和文档不一致（平台改过名字），在 `_get()` 的候选键里补一个即可
4. 把真实事件补进 `tests/test_qq_adapter.py` 的用例

## 七、后续（先不做，别忘）

- **图片/附件**：当前直接跳过。接了 OCR 之后才能处理，否则会生成一张叫「[图片]」的垃圾卡片。
- **主动提醒**：受第三节的配额限制，提醒渠道需要多一条（邮件/日历）。
- **多群支持**：现在 `group_id` 只存不区分，多班使用时需要按群分组。

## 八、安全

- `AppSecret` 只放本地 `.env`，**不要提交、不要截图发群**。
- 已经泄露过一次的话，去控制台重置，旧 Secret 立即失效。
- 转换层不含任何凭证，可以随意分享。
