# 班务通 UI 工作流增强交接

> 本轮目标（实时预览 / 真实通知 / 到期分组 / 状态反馈 / 设置收纳 / 键盘与无障碍 /
> 聊天上下文 / 批量处理）已在浏览器端逐项验证并修复缺陷，代码合入 `main`。
> 本文记录验证结论、本轮修复、环境限制和后续可选项。

## 当前分支与基线

- 项目目录：`C:\Users\zhou\Documents\ChatGPT\办务通`
- 检查点分支：`codex/ui-workflow-checkpoint-20261103`（第一轮 WIP + 第二轮验证修复）。
  origin 上仍是第一轮的 `0a00f40`，第二轮那条本地提交没有单独推上去。
- 基线 `main`：`3bf1cbc feat(ui): apply taste-led workspace redesign`
- 第二轮已通过 squash 合并进 `main` 并上传到 origin：
  - `3507f07 feat(ui): guided notification workflow with live preview and real notifications`
  - `e8fbd5d docs: note that the main push is still blocked locally`（本文档的推送说明）
- **推送方式注意**：本机 `github.com:443` 直连超时、走本地代理返回
  `CONNECT tunnel failed, response 502`，`git push` 用不了；只有 `api.github.com`
  可达。本轮是用 GitHub Git Data API 建 blob/tree/commit 再移动 `refs/heads/main`
  上传的（建完 tree 会与本地 tree sha 比对，确保逐字节一致）。
  网络上能直连 `github.com` 之后，`git push` 会恢复正常，不需要改任何东西。

## 本轮目标

把 UI 从“设计规整的空状态工作台”继续推进为完整工作流：

1. 输入通知时实时显示识别预览。
2. 保存后让新事项卡有明确出现反馈。
3. 使用真实消息驱动通知，不再使用硬编码通知。
4. 有数据时按截止紧急度组织看板。
5. 增加加载、失败、重试和数据新鲜度提示。
6. 把模型/提醒设置收纳为摘要入口。
7. 完善键盘操作、焦点返回和辅助说明。
8. 在 AI 对话中展示当前事项上下文。
9. 支持多选事项并批量标记完成。

## 已实现

### 后端

- 新增 `POST /api/preview`，只使用本地确定性规则解析，不写数据库、不调用云端模型。
- 新增 Pydantic 模型：
  - `PreviewIn`
  - `PreviewActivityOut`
  - `PreviewOut`
- 访客 POST 白名单新增 `/api/preview`。
- 新增 `tests/test_preview.py`，覆盖预览提取和空文本拒绝。
- 标题提取改为短标题：整段去掉 `【重要】【班级通知】` 这类前缀；超长句子取第一个分句；
  仍超长则截断到 30 字并加省略号（`app/parser.py` 的 `_shorten_title`）。

### 前端主页面

- 文本框输入后防抖 600ms 调用 `/api/preview`，显示：
  - 标题
  - 截止时间与相对时间
  - 适用对象
  - 地点
  - 材料
  - 是否需要核对
- 保存成功时，预览区域执行收拢动画；刷新后定位并高亮新事项卡。
- 保存过程显示“读取原文 → 提取字段 → 生成事项卡”阶段状态。
- 文件上传显示“上传 → 读取 → 提取”阶段状态。
- 看板按以下分组：
  - 已过截止时间
  - 今天截止
  - 3 天内截止
  - 之后截止
  - 待补充截止时间
  - 已完成或已关闭
- 事项卡突出截止状态，并加入新卡出现动画。
- 看板增加：
  - 数据新鲜度时间
  - 区块内错误提示
  - 重试按钮
  - 初始加载骨架
- 批量模式：
  - 多选事项
  - 批量标记完成
  - 显示成功/失败数量（写在看板区，6 秒后自动收起）
  - 退出批量
- 模型与提醒设置收纳为 `处理设置` 摘要面板；桌面按钮和手机底部“设置”
  共用同一个展开状态，手机端再点一次“设置”可收起。
- 手机端设置摘要会显示当前模型和提醒状态。
- 真实通知：
  - 从 `/api/messages` 的最新 `notice` 消息生成通知内容。
  - 点击后定位到对应事项。
  - 已展示消息 ID 存在 `localStorage`，避免刷新后重复弹出。
  - 自身刚保存的消息会预先标记为已见，避免刚保存又弹通知。
- 通知区域是页内流式提示，不覆盖标题和表单。
- `Ctrl/Cmd + Enter` 直接提交通知。
- 文件限制通过 `aria-describedby` 关联到文件说明。
- 新事项获得焦点，并显示 1.8 秒描边，便于键盘用户继续操作。

### AI 对话

- 对话页新增当前事项上下文：
  - 待处理数量
  - 待核对数量
  - 今天截止数量
  - 最近三个事项及截止时间
- 对话 iframe 内按 `Esc` 会通知父页面关闭弹层。
- 父页面关闭弹层后把焦点还给触发按钮。

## 第二轮验证结论（2026-11-03）

用 Playwright（Chromium 1247，视口 1440×950 / 768×1024 / 390×844）对临时库
`output/taste-workspace-test.db`（6 条真实感事项）逐项回归：

| 项目 | 结论 |
| --- | --- |
| 600ms 后出现预览 | 通过，输入到预览约 796ms |
| 预览字段完整 | 通过，标题/截止/相对时间/状态齐全，高度 129px，不超出首屏 |
| 保存后预览收拢 | 通过，收拢后高度 0 |
| 新卡高亮 + 获得焦点 | 通过，`activity-arrive` 动画执行，1.8 秒后移除，焦点落在新卡 |
| 到期分组 | 通过，5 个分组按 已过期/今天/3 天内/之后/待补充 排列，计数正确 |
| 空状态 | 通过，`导入一条通知，建立第一张事项卡`，指标全 0，无通知弹出 |
| 加载失败 + 重试 | 通过，500 时显示“模拟失败 重试”，新鲜度转为“数据未能刷新”，点击重试后 8 张卡恢复 |
| 设置摘要展开/收起 | 通过，桌面按钮与手机“设置”同步 `aria-expanded`，手机二次点击可收起 |
| 批量选择/完成 | 通过，勾选 2 项 → “已将 2 项标记为完成。”显示在看板区，指标 `已完成` 变 2 |
| 真实消息通知只出现一次 | 通过，首次加载弹出，刷新后不再弹出，标题为短标题（1 行） |
| 通知点击定位 | 通过，关闭 toast 并把焦点移到对应事项卡 |
| `Ctrl + Enter` 提交 | 通过，卡片数 7 → 8 |
| 横向溢出 | 通过，1440 / 768 / 390 均无横向滚动（`scrollWidth == innerWidth`） |
| 控制台错误 | 无 |
| 页面标题行换行 | 通过，“填入示例”在双栏窄列下不再折成两行 |

### 本轮修复的缺陷

1. **卡片标题塞进整段通知**：80 字上限导致标题折三行，通知条也被撑高。
   改为整段剥离 `【…】` 前缀 + 取首个分句 + 30 字上限。
2. **手机“设置”只能开不能关**：底部导航每次都调用 `setMobileSettingsOpen(true)`，
   `aria-expanded` 与实际面板状态不符。改为按当前状态切换，并在收起时不再滚动聚焦面板。
3. **批量完成反馈写到导入框**：提示落在左侧 `#form-status`，看板上看不到。
   改为同时写入看板状态区，并在 6 秒后自动收起。
4. **新卡焦点无可见描边**：程序化聚焦时 `:focus-visible` 不生效，鼠标流程下看不出落点。
   给 `.activity-new` 补同款描边。

### 仍需注意 / 未覆盖

1. **Taste inspector 无法在本机启动 Chrome**：`design-taste-frontend` 的
   `inspect.mjs` 用 `--headless=new` + `--remote-debugging-port` 启动 Chrome，
   在本机 Chromium 141 上进程立刻以 code 0 退出（`--headless` 同样，交给 Playwright
   的 `--remote-debugging-pipe` 才正常）。本轮改用 Playwright 直接量取布局、溢出、
   焦点与三种视口截图，等价覆盖了视觉评审，但**没有产出 `.taste-skill/workflow`
   的报告文件**。若需要该报告，需在能正常起 CDP 端口的机器上重跑：
   ```powershell
   node 'C:\Users\zhou\.agents\skills\design-taste-frontend\scripts\inspect.mjs' http://127.0.0.1:8766/ --app --out .taste-skill/workflow
   ```
2. **Taste lint**：`0 FAIL, 7 WARN`（零填充 1 处、box-shadow 6 处，均为既有弹窗/吸底栏，
   属允许的浮层阴影）。
3. **AI 对话弹层只做了 iframe 级验证**：本机只配置了“本地规则”模型，`chatAvailable`
   为 false，主页对话入口按设计隐藏。已单独验证 `/chat?embedded=1` 的上下文摘要
   （`7 项待处理 · 1 项待核对` + 最近三条及截止）和 `Esc` 会向父页面发送
   `{type:"banwutong-close-chat"}`。**弹层开合与焦点返回未在真实云端模型下跑过**。
4. 项目没有 JS 测试框架，前端行为仍靠 Playwright 脚本验证，未落成仓库内测试。
5. 768px 单列布局下导入框占满首屏，看板需要下滑才能看到；这是既有布局选择，本轮未改。

## 测试结果

```text
pytest -q -k 'not test_push_endpoints'
127 passed, 3 skipped, 1 deselected, 3 xfailed

node --check app/static/app.js      通过
git diff --check                     通过
Taste lint                           0 FAIL, 7 WARN
```

`tests/test_parser.py` 新增 3 条标题回归用例：
`test_long_single_line_notice_gets_short_title`、
`test_unpunctuated_long_title_is_clipped`、`test_short_title_is_left_alone`。

## 测试用临时环境

- 数据库：`output\taste-workspace-test.db`（6 条种子事项，按 2026-11-03 当日重建）
- 上传目录：`output\taste-workspace-uploads`
- 临时服务端口：`8766`（验证结束后已关闭）
- 截图目录：`output\validate\`（`final-1440/768/390-*`、`f-desktop-*`、`e1-empty`、`e2-error`）
- 以上都在已忽略的 `output/` 中，不会提交。

重新启动临时测试服务：

```powershell
$env:BANWUTONG_DATABASE_PATH = 'C:\Users\zhou\Documents\ChatGPT\办务通\output\taste-workspace-test.db'
$env:BANWUTONG_UPLOAD_DIR = 'C:\Users\zhou\Documents\ChatGPT\办务通\output\taste-workspace-uploads'
$env:BANWUTONG_REMINDERS_DISABLED = '1'
Start-Process -FilePath '.\.venv\Scripts\python.exe' `
  -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8766' `
  -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

灌数据的 6 条通知见 `output\validate\report3.json` 同目录的验证脚本，
或用 `POST /api/messages`（需要 `platform`、`external_id`、`text`）逐条写入。

## 已知风险与实现说明

- 通知来自真实消息流，而不是单独新增通知表；已展示状态保存在当前浏览器
  `localStorage`，不同浏览器之间不共享。
- `/api/preview` 固定使用本地规则，避免输入过程中反复产生云端模型费用；
  正式保存仍按当前模型重新解析。
- 批量完成通过逐项调用现有 `PATCH /api/activities/{id}` 完成，后端没有新增
  批量接口；失败项会保留并报告。
- 看板分组是前端表现层逻辑；后端仍按截止时间排序。
- 标题变短会改变 `dedupe_key`；只有超过 30 字的长行才受影响，短标题行为不变。
- 当前 `output/`、`.taste-skill/` 和测试数据库不属于源码，不应提交。
- 不要删除 `.taste-skill` 目录，它包含上几轮的 before/after 截图与报告。

## 后续可选项

1. 在有云端模型 key 的环境里跑一次对话弹层的开合、`Esc` 与焦点返回。
2. 在能正常起 CDP 的机器上补跑 Taste inspector，生成 `.taste-skill/workflow`。
3. 把本轮 Playwright 验证脚本收进仓库（例如 `tests/e2e/`），用 `npm` 或
   `playwright test` 固定下来，避免下次仍靠临时脚本。
4. 768px 单列时缩短导入框高度，让看板能在首屏露出第一张卡。
