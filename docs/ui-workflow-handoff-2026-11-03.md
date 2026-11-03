# 班务通 UI 工作流增强交接

> 给下一个继续工作的 Codex 对话：先读本文，再执行 `git status` 和
> `git log -3 --oneline`。本轮工作尚未完成最终浏览器回归，也尚未合入 `main`。

## 当前分支与基线

- 项目目录：`C:\Users\zhou\Documents\ChatGPT\办务通`
- 检查点分支：`codex/ui-workflow-checkpoint-20261103`
- 基线 `main`：`3bf1cbc feat(ui): apply taste-led workspace redesign`
- 当前分支用于保存“实时预览 / 真实通知 / 到期分组 / 状态反馈 / 设置收纳 /
  键盘与无障碍 / 聊天上下文 / 批量处理”的未完成实现。
- 没有删除或覆盖 `main`；完成后通过测试再合并并推送。

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
  - 显示成功/失败数量
  - 退出批量
- 模型与提醒设置收纳为 `处理设置` 摘要面板；桌面按钮和手机底部“设置”
  共用同一个展开状态。
- 手机端设置摘要会显示当前模型和提醒状态。
- 真实通知：
  - 从 `/api/messages` 的最新 `notice` 消息生成通知内容。
  - 点击后定位到对应事项。
  - 已展示消息 ID 存在 `localStorage`，避免刷新后重复弹出。
  - 自身刚保存的消息会预先标记为已见，避免刚保存又弹通知。
- 通知区域是页内流式提示，不覆盖标题和表单。
- `Ctrl/Cmd + Enter` 直接提交通知。
- 文件限制通过 `aria-describedby` 关联到文件说明。
- 新事项获得焦点，便于键盘用户继续操作。

### AI 对话

- 对话页新增当前事项上下文：
  - 待处理数量
  - 待核对数量
  - 今天截止数量
  - 最近三个事项及截止时间
- 对话 iframe 内按 `Esc` 会通知父页面关闭弹层。
- 父页面关闭弹层后把焦点还给触发按钮。

## 需要继续验证

1. 启动最新后端后，在浏览器里逐项验证：
   - 输入样例是否在 600ms 后出现预览。
   - 保存后预览是否收拢、新卡是否高亮并获得焦点。
   - 数据为空、加载失败、周期刷新失败时是否出现正确状态。
   - 设置摘要展开/收起，桌面与手机是否一致。
   - 批量勾选和批量完成是否正确。
   - 真实消息通知是否只出现一次，并能定位对应事项。
   - AI 对话 `Esc`、焦点返回、上下文摘要是否正常。
2. 运行 Taste gates：
   ```powershell
   node 'C:\Users\zhou\.agents\skills\design-taste-frontend\scripts\lint.mjs' --app app/static
   node 'C:\Users\zhou\.agents\skills\design-taste-frontend\scripts\inspect.mjs' http://127.0.0.1:8766/ --app --out .taste-skill/workflow
   ```
3. 检查 1440、768、390 三种截图；尤其注意：
   - 有数据时卡片密度。
   - 批量工具条在手机端是否过宽。
   - 设置摘要是否换行拥挤。
   - 预览区域是否让首屏过高。
4. 运行完整测试：
   ```powershell
   & '.\.venv\Scripts\python.exe' -m pytest -q -k 'not test_push_endpoints'
   node --check app/static/app.js
   git -c core.whitespace=cr-at-eol diff --check
   ```
5. 修复后提交、合并到 `main`、推送远端。

## 测试用临时环境

当前已创建独立测试数据库和 6 条真实感事项：

- 数据库：`output\taste-workspace-test.db`
- 上传目录：`output\taste-workspace-uploads`
- 临时服务端口：`8766`
- Playwright 页面：`http://127.0.0.1:8766/`
- 截图文件：`output\workflow-seeded-desktop.png`（尚未完成最终视觉评审）
- 临时服务标准输出/错误：
  - `output\taste-workspace-test.out.log`
  - `output\taste-workspace-test.err.log`

这些文件都在已忽略的 `output/` 中，不会提交。

重新启动临时测试服务：

```powershell
$env:BANWUTONG_DATABASE_PATH = 'C:\Users\zhou\Documents\ChatGPT\办务通\output\taste-workspace-test.db'
$env:BANWUTONG_UPLOAD_DIR = 'C:\Users\zhou\Documents\ChatGPT\办务通\output\taste-workspace-uploads'
$env:BANWUTONG_REMINDERS_DISABLED = '1'
Start-Process -FilePath '.\.venv\Scripts\python.exe' `
  -ArgumentList '-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8766' `
  -WorkingDirectory (Get-Location) -WindowStyle Hidden
```

## 当前测试结果

- `node --check app/static/app.js`：通过。
- `pytest -q tests/test_preview.py`：`2 passed`。
- 尚未在最终版本上执行完整 Taste inspector 和完整测试套件。
- 正在使用的 8765 服务可能仍加载旧后端代码；浏览器验证应使用重启后的
  8765，或使用临时 8766。

## 已知风险与实现说明

- 通知来自真实消息流，而不是单独新增通知表；已展示状态保存在当前浏览器
  `localStorage`，不同浏览器之间不共享。
- `/api/preview` 固定使用本地规则，避免输入过程中反复产生云端模型费用；
  正式保存仍按当前模型重新解析。
- 批量完成通过逐项调用现有 `PATCH /api/activities/{id}` 完成，后端没有新增
  批量接口；失败项会保留并报告。
- 看板分组是前端表现层逻辑；后端仍按截止时间排序。
- 当前 `output/`、`.taste-skill/` 和测试数据库不属于源码，不应提交。
- 不要删除 `.taste-skill` 目录，它包含本轮和上轮的 before/after 截图与报告。

## 推荐继续顺序

1. 先完成浏览器端到端验证并修复 UI。
2. 增加前端行为测试（若项目没有 JS 测试框架，可先用 Playwright CLI 验证）。
3. 跑 Taste lint/inspect 和完整 Python 测试。
4. 提交到检查点分支。
5. 合并 `main` 并推送。
