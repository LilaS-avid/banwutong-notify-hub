# 云端部署（已实测跑通）

> 2026-11-01 实测：Windows 云服务器上跑通了「QQ 群消息 → 机器人 → 后端 → 数据库」全链路，
> 并注册了开机自启。本文档记录可复现的步骤。

## 一、为什么需要云端

机器人要 7×24 在线收群消息，后端要一直存数据。跑在个人电脑上，关机、断网、休眠都会中断。
放到云服务器后：本地关机不影响，手机/电脑也能访问看板。

## 二、环境要求

| 项 | 要求 | 说明 |
| --- | --- | --- |
| 操作系统 | Windows Server 2016 及以上 | 本文脚本按 Windows 写；Linux 需另写 |
| 公网访问 | 至少开放 3389（远程桌面） | 部署时用 |
| 出网 | 能访问 pypi 与 api.sgroup.qq.com | 装依赖、连 QQ 网关 |
| Python | 3.10+，无则脚本自动装 3.12 | deploy.ps1 会处理 |

> ChatGPT 式"一键部署"不适用于本项目，必须有一台能长期开机的 Windows 主机。

## 三、部署步骤

```powershell
# 1. 把仓库放到服务器（clone 或复制压缩包解压）到 C:\banwutong
# 2. 管理员 PowerShell
cd C:\banwutong
.\deploy\deploy.ps1          # 建虚拟环境、装依赖、生成 .env
```

`deploy.ps1` 做的事：

1. 找 Python（没有就用 winget 装 3.12）
2. 创建 `.venv`
3. 按 `requirements.txt` + `requirements-bot.txt` 装依赖（用清华镜像）
4. 从 `.env.template` 生成 `.env`（不覆盖已有的）

然后填 `.env` 里的两个密钥（`QQBOT_SECRET`、`BANWUTONG_LLM_API_KEY`），再启动：

```powershell
.\deploy\start-all.ps1       # 后台启动后端 + 机器人，日志在 logs\
.\deploy\register-autostart.ps1   # 注册开机自启（可选，建议做）
```

停止：`.\deploy\stop-all.ps1`

## 四、实测结果

```
=== 状态 ===
后端: ok
[INFO] 机器人「1906182332」启动成功
[INFO] 心跳维持启动

curl http://127.0.0.1:8765/api/activities
[{"id":1,"title":"英语四级报名","deadline":"2026-11-06T12:00:00+08:00",...}]

已注册开机自启：Banwutong-AutoStart
```

## 五、必须知道的几件事

1. **同一个 AppID 只能有一个实例在跑。**
   服务器启动后，本地就不要再运行 `scripts/run_qq_bot.py`，
   否则两边会互相踢下线（WebSocket 会话冲突），表现为消息时有时无。

2. **`.env` 不进仓库。**
   它已在 `.gitignore` 里。换机器部署需要重新填密钥。

3. **机器人日志在 `logs\bot.err.log`，不是 `bot.log`。**
   botpy 的日志走标准错误流，`bot.log` 里只有脚本自己 `print` 的内容。

4. **开机自启以 SYSTEM 身份运行**，窗口不会弹出来。
   排查时看 `logs\` 下的日志，别找窗口。

5. **云服务器的安全组只放行需要的最小端口。**
   如果只在服务器本机用（机器人 + 后端同机），8765 不需要对公网开放；
   要让手机访问看板，才需要放行，并建议加反向代理 + HTTPS。

## 六、还没做的

- HTTPS 与域名（手机 PWA 安装需要）
- 数据库备份（当前是本地 SQLite 文件，需定时拷贝）
- 多班支持（现在 `group_id` 只存不区分）
