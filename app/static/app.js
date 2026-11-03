const API = "/api";
let currentStatus = "";
let currentView = "board";
let reviewItems = [];
let isGuest = false;
let lastSignature = "";
let chatAvailable = false;
let currentToastActivityId = null;
let chatReturnFocus = null;
let lastBoardData = null;
let previewController = null;
let previewTimer = null;
let bulkMode = false;
const selectedActivityIds = new Set();

const elements = {
  form: document.querySelector("#message-form"),
  text: document.querySelector("#message-text"),
  submit: document.querySelector("#message-form button[type='submit']"),
  status: document.querySelector("#form-status"),
  preview: document.querySelector("#extract-preview"),
  list: document.querySelector("#activity-list"),
  boardStatus: document.querySelector("#board-status"),
  sample: document.querySelector("#sample-button"),
  fileForm: document.querySelector("#file-form"),
  fileInput: document.querySelector("#file-input"),
  fileStatus: document.querySelector("#file-status"),
  modelSelect: document.querySelector("#model-provider"),
  modelNote: document.querySelector("#model-note"),
  modelSummary: document.querySelector("#model-summary"),
  reminderSummary: document.querySelector("#reminder-summary"),
  settingsArea: document.querySelector("#settings-area"),
  settingsToggle: document.querySelector("#settings-toggle"),
  settingsPanel: document.querySelector("#settings-panel"),
  settingsToggleAction: document.querySelector(".settings-toggle-action"),
  pushButton: document.querySelector("#push-enable"),
  pushNote: document.querySelector("#push-note"),
  openChat: document.querySelector("#open-chat"),
  mobileNav: document.querySelector("#mobile-nav"),
  mobileButtons: [...document.querySelectorAll("[data-mobile-action]")],
  boardSection: document.querySelector("#board-section"),
  importSection: document.querySelector("#import-section"),
  workspace: document.querySelector(".workspace"),
  modelSection: document.querySelector("#model-section"),
  chatDialog: document.querySelector("#chat-dialog"),
  chatFrame: document.querySelector("#chat-frame"),
  messageSection: document.querySelector("#message-section"),
  messageList: document.querySelector("#message-list"),
  messageToggle: document.querySelector("#message-toggle"),
  messageLabel: document.querySelector("#message-label"),
  messageCount: document.querySelector("#message-count"),
  guestBanner: document.querySelector("#guest-banner"),
  toastTitle: document.querySelector("#toast-title"),
  toastMessage: document.querySelector("#toast-message"),
  toastAction: document.querySelector(".toast-action"),
  filters: [...document.querySelectorAll(".filter")],
  statusFilters: document.querySelector("#status-filters"),
  trashToggle: document.querySelector("#trash-toggle"),
  trashLabel: document.querySelector("#trash-label"),
  trashCount: document.querySelector("#trash-count"),
  trashHint: document.querySelector("#trash-hint"),
  viewTitle: document.querySelector("#view-title"),
  boardFreshness: document.querySelector("#board-freshness"),
  reviewToolbar: document.querySelector("#review-toolbar"),
  batchConfirm: document.querySelector("#batch-confirm"),
  filterReviewCount: document.querySelector("#filter-review-count"),
  bulkToggle: document.querySelector("#bulk-toggle"),
  bulkBar: document.querySelector("#bulk-actions"),
  bulkCount: document.querySelector("#bulk-count"),
  bulkComplete: document.querySelector("#bulk-complete"),
  bulkCancel: document.querySelector("#bulk-cancel"),
  metrics: {
    total: document.querySelector("#metric-total"),
    open: document.querySelector("#metric-open"),
    review: document.querySelector("#metric-review"),
    done: document.querySelector("#metric-done"),
  },
};

const sample = `活动名称：校园智能体应用创新大赛
报名截止：2026-11-05 18:00
适用对象：全体在校学生
活动地点：线上提交
报名材料：报名表、学生证照片、作品说明
报名链接：https://www.hrbmu.edu.cn/
联系人：学生创新中心`;

const statusLabels = {
  open: "待处理",
  completed: "已完成",
  ignored: "已忽略",
  cancelled: "已取消",
};

// 与后端 review.py 的 REASON_INFO 对应，只取短标签用于卡片常显。
const reviewReasonLabels = {
  deadline_missing: "缺截止时间",
  deadline_range: "截止取自区间",
  deadline_conflict: "原文多个日期",
  title_missing: "标题取自首行",
  ai_uncertain: "AI 不确定",
  deadline_mismatch: "AI 与规则不一致",
};

const mobileViewport = window.matchMedia("(max-width: 760px)");

function setMobileSettingsOpen(open) {
  document.body.classList.toggle("show-mobile-settings", open);
  const settingsButton = elements.mobileButtons.find(
    (button) => button.dataset.mobileAction === "settings",
  );
  elements.settingsPanel.classList.toggle("hidden", !open);
  elements.settingsToggle.setAttribute("aria-expanded", String(open));
  elements.settingsToggleAction.textContent = open ? "收起" : "展开";
  settingsButton?.setAttribute("aria-expanded", String(open));
}

function updateDeviceLayout() {
  const mobileDevice =
    mobileViewport.matches || navigator.userAgentData?.mobile === true;
  document.body.classList.toggle("device-mobile", mobileDevice);
  document.documentElement.dataset.device = mobileDevice ? "mobile" : "desktop";
  if (!mobileDevice) setMobileSettingsOpen(false);
}

updateDeviceLayout();
mobileViewport.addEventListener("change", updateDeviceLayout);

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatDeadline(value) {
  if (!value) return "未识别，请核对原文";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function formatDateTimeLocal(value) {
  if (!value) return "";
  const date = new Date(value);
  const pad = (number) => String(number).padStart(2, "0");
  return [
    date.getFullYear(),
    "-",
    pad(date.getMonth() + 1),
    "-",
    pad(date.getDate()),
    "T",
    pad(date.getHours()),
    ":",
    pad(date.getMinutes()),
  ].join("");
}

function formatTrashTime(value) {
  if (!value) return "";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(value));
}

function deadlineInfo(value) {
  if (!value) {
    return { state: "missing", text: "未识别截止时间", relative: "待核对" };
  }
  const deadline = new Date(value);
  if (Number.isNaN(deadline.getTime())) {
    return { state: "missing", text: String(value), relative: "待核对" };
  }
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const targetDay = new Date(
    deadline.getFullYear(),
    deadline.getMonth(),
    deadline.getDate(),
  );
  const dayDiff = Math.round((targetDay - today) / 86_400_000);
  const time = new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(deadline);
  const date = new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
  }).format(deadline);
  if (deadline < now) {
    return {
      state: "overdue",
      text: `${date} ${time}`,
      relative: dayDiff === 0 ? "今天已截止" : `已过 ${Math.abs(dayDiff)} 天`,
    };
  }
  if (dayDiff === 0) {
    return { state: "today", text: `${date} ${time}`, relative: "今天截止" };
  }
  if (dayDiff <= 3) {
    return {
      state: "soon",
      text: `${date} ${time}`,
      relative: dayDiff === 1 ? "明天截止" : `${dayDiff} 天后截止`,
    };
  }
  return { state: "later", text: `${date} ${time}`, relative: `${dayDiff} 天后` };
}

function setFormStatus(message, state = "") {
  elements.status.textContent = message;
  elements.status.dataset.state = state;
}

function renderExtractionPreview(data) {
  if (!data.activities.length || data.kind === "chat") {
    elements.preview.innerHTML = `
      <div class="preview-empty">
        <strong>这段内容更像闲聊</strong>
        <span>保存后会进入消息流水，不会创建事项卡。</span>
      </div>`;
    elements.preview.classList.remove("hidden");
    return;
  }
  const items = data.activities
    .map((activity) => {
      const due = deadlineInfo(activity.deadline);
      const tags = [
        activity.audience ? `对象：${activity.audience}` : "",
        activity.location ? `地点：${activity.location}` : "",
        activity.materials.length
          ? `材料：${activity.materials.slice(0, 3).join("、")}`
          : "",
      ].filter(Boolean);
      const review = activity.needs_review
        ? `<span class="preview-review">需要核对 ${activity.review_reasons.length || 1} 项</span>`
        : `<span class="preview-ready">可保存</span>`;
      return `
        <article class="preview-item">
          <div class="preview-item-top">
            <h3>${escapeHtml(activity.title || "未命名事项")}</h3>
            ${review}
          </div>
          <div class="preview-facts">
            <span class="preview-deadline ${due.state}">
              <b>${escapeHtml(due.relative)}</b>
              <small>${escapeHtml(due.text)}</small>
            </span>
            ${tags
              .map((tag) => `<span>${escapeHtml(tag)}</span>`)
              .join("")}
          </div>
        </article>`;
    })
    .join("");
  elements.preview.innerHTML = `
    <div class="preview-heading">
      <strong>识别预览</strong>
      <span>${data.activities.length} 个事项 · 本地规则</span>
    </div>
    ${items}
    <p class="preview-note">${escapeHtml(data.note || "")}</p>`;
  elements.preview.classList.remove("hidden");
}

function clearExtractionPreview() {
  window.clearTimeout(previewTimer);
  previewController?.abort();
  previewController = null;
  elements.preview.classList.add("hidden");
  elements.preview.classList.remove("converting");
  elements.preview.innerHTML = "";
}

function scheduleExtractionPreview() {
  window.clearTimeout(previewTimer);
  previewController?.abort();
  previewController = null;
  const text = elements.text.value.trim();
  if (text.length < 4) {
    elements.preview.classList.add("hidden");
    return;
  }
  previewTimer = window.setTimeout(async () => {
    const controller = new AbortController();
    previewController = controller;
    elements.preview.innerHTML =
      '<div class="preview-loading">正在提取截止时间、材料和下一步…</div>';
    elements.preview.classList.remove("hidden");
    try {
      const data = await request("/preview", {
        method: "POST",
        body: JSON.stringify({ text }),
        signal: controller.signal,
      });
      if (!controller.signal.aborted) renderExtractionPreview(data);
    } catch (error) {
      if (error.name === "AbortError") return;
      elements.preview.innerHTML = `
        <div class="preview-empty error">
          <strong>暂时无法预览</strong>
          <span>${escapeHtml(error.message)}。仍可直接保存。</span>
        </div>`;
      elements.preview.classList.remove("hidden");
    }
  }, 600);
}

function editForm(activity, options = {}) {
  const confirmMode = options.confirm === true;
  return `
    <form class="edit-form hidden" data-edit-id="${activity.id}" data-confirm="${confirmMode ? "1" : "0"}">
      <div class="edit-grid">
        <label class="edit-field wide">标题
          <input name="title" required maxlength="200" value="${escapeHtml(activity.title)}">
        </label>
        <label class="edit-field">截止时间
          <input name="deadline" type="datetime-local" value="${escapeHtml(formatDateTimeLocal(activity.deadline))}">
        </label>
        <label class="edit-field">适用对象
          <input name="audience" value="${escapeHtml(activity.audience || "")}">
        </label>
        <label class="edit-field">报名材料
          <input name="materials" value="${escapeHtml(activity.materials.join("、"))}" placeholder="用顿号或逗号分隔">
        </label>
        <label class="edit-field">地点
          <input name="location" value="${escapeHtml(activity.location || "")}">
        </label>
        <label class="edit-field">联系人
          <input name="contact" value="${escapeHtml(activity.contact || "")}">
        </label>
        <label class="edit-field">报名链接
          <input name="registration_url" type="url" value="${escapeHtml(activity.registration_url || "")}">
        </label>
      </div>
      <div class="edit-actions">
        <button type="button" data-action="cancel-edit">取消</button>
        <button class="save-edit" type="submit">${confirmMode ? "保存并确认" : "保存修改"}</button>
      </div>
    </form>`;
}

function activityCard(activity) {
  const effectiveStatus = activity.status;
  const due = deadlineInfo(activity.deadline);
  const badgeClass = effectiveStatus === "completed" ? "done" : "";
  const materials = activity.materials.length
    ? activity.materials.join("、")
    : "未从通知中识别";
  const link = activity.registration_url
    ? `<a href="${escapeHtml(activity.registration_url)}" target="_blank" rel="noreferrer">打开报名入口</a>`
    : "";
  const statusActions =
    effectiveStatus === "completed"
      ? `<button type="button" data-action="status" data-status="open" data-id="${activity.id}">重新打开</button>`
      : `<button type="button" data-action="status" data-status="completed" data-id="${activity.id}">标记完成</button>`;
  const deleteAction =
    effectiveStatus === "completed"
      ? `<button class="danger-action" type="button" data-action="delete" data-id="${activity.id}">删除</button>`
      : "";
  const reviewChips = (activity.review_reasons || [])
    .map(
      (code) =>
        `<span class="badge review-chip">${escapeHtml(reviewReasonLabels[code] || code)}</span>`,
    )
    .join("");
  const reviewBadge = activity.needs_review
    ? `<span class="badge review">待核对</span>${reviewChips}`
    : "";
  const bulkControl = bulkMode
    ? `<label class="bulk-check">
        <input type="checkbox" data-bulk-id="${activity.id}" ${selectedActivityIds.has(activity.id) ? "checked" : ""}>
        <span class="sr-only">选择 ${escapeHtml(activity.title)}</span>
      </label>`
    : "";
  const titleId = `activity-title-${activity.id}`;

  return `
    <article
      class="activity deadline-${due.state}${selectedActivityIds.has(activity.id) ? " selected" : ""}"
      data-activity-id="${activity.id}"
      tabindex="-1"
      aria-labelledby="${titleId}"
    >
      <div class="activity-top">
        ${bulkControl}
        <h3 id="${titleId}">${escapeHtml(activity.title)}</h3>
        <div class="activity-badges">
          <span class="badge ${badgeClass}">${statusLabels[effectiveStatus] || escapeHtml(effectiveStatus)}</span>
          ${reviewBadge}
        </div>
      </div>
      <div class="meta-grid">
        <div class="deadline-block ${due.state}">
          <b>截止时间</b>
          <strong>${escapeHtml(due.relative)}</strong>
          <small>${escapeHtml(due.text)}</small>
        </div>
        <div><b>适用对象</b>${escapeHtml(activity.audience || "未填写")}</div>
        <div><b>报名材料</b>${escapeHtml(materials)}</div>
        <div><b>地点 / 联系人</b>${escapeHtml([activity.location, activity.contact].filter(Boolean).join(" · ") || "未填写")}</div>
      </div>
      <div class="source-box hidden" data-source-id="${activity.id}"></div>
      ${editForm(activity)}
      <div class="card-actions">
        ${link}
        ${isGuest ? "" : `<button type="button" data-action="source" data-id="${activity.id}">查看原文</button>`}
        <button type="button" data-action="edit">编辑内容</button>
        ${statusActions}
        ${deleteAction}
      </div>
    </article>`;
}

function trashCard(activity) {
  return `
    <article class="activity trash-activity">
      <div class="activity-top">
        <h3>${escapeHtml(activity.title)}</h3>
        <span class="badge done">${statusLabels[activity.status] || "已删除"}</span>
      </div>
      <div class="meta-grid">
        <div><b>删除时间</b>${escapeHtml(formatTrashTime(activity.deleted_at))}</div>
        <div><b>自动彻底删除</b>${escapeHtml(formatTrashTime(activity.purge_after))}</div>
      </div>
      <div class="card-actions">
        <button type="button" data-action="restore" data-id="${activity.id}">恢复到看板</button>
        <button class="danger-action" type="button" data-action="purge" data-id="${activity.id}">彻底删除</button>
      </div>
    </article>`;
}

function reviewCard(item) {
  const activity = item.activity;
  const materials = activity.materials.length
    ? activity.materials.join("、")
    : "未从通知中识别";
  const reasons = item.reasons
    .map(
      (reason) => `
      <li class="review-reason ${escapeHtml(reason.severity)}">
        <b>${escapeHtml(reason.label)}</b>
        <span>${escapeHtml(reason.hint)}</span>
      </li>`,
    )
    .join("");
  const evidence = item.evidence
    .map(
      (entry) => `
      <b>${escapeHtml(entry.label)}</b>
      <pre>${escapeHtml(entry.text)}</pre>`,
    )
    .join("");

  return `
    <article class="activity review-card" data-activity-id="${activity.id}">
      <div class="activity-top">
        <h3>${escapeHtml(activity.title)}</h3>
        <div class="activity-badges">
          <span class="badge review">待核对</span>
          <span class="badge">${statusLabels[activity.status] || escapeHtml(activity.status)}</span>
        </div>
      </div>
      <ul class="review-reasons">${reasons}</ul>
      <div class="meta-grid">
        <div><b>当前截止时间</b>${escapeHtml(formatDeadline(activity.deadline))}</div>
        <div><b>适用对象</b>${escapeHtml(activity.audience || "未填写")}</div>
        <div><b>报名材料</b>${escapeHtml(materials)}</div>
        <div><b>地点 / 联系人</b>${escapeHtml([activity.location, activity.contact].filter(Boolean).join(" · ") || "未填写")}</div>
      </div>
      <details class="review-evidence">
        <summary>查看原文证据</summary>
        ${evidence || "<b>没有可追溯的原文</b>"}
      </details>
      ${editForm(activity, { confirm: true })}
      <div class="card-actions">
        <button type="button" data-action="review-edit">修正字段</button>
        <button class="save-edit" type="button" data-action="review-confirm" data-id="${activity.id}">确认无误</button>
        <button type="button" data-action="status" data-status="ignored" data-id="${activity.id}">暂时忽略</button>
      </div>
    </article>`;
}

async function request(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  const response = await fetch(`${API}${path}`, {
    headers,
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  if (response.status === 204) return null;
  return response.json();
}

function setView(view) {
  currentView = view;
  const showingTrash = currentView === "trash";
  const showingReview = !showingTrash && currentStatus === "review";
  elements.statusFilters.classList.toggle("hidden", showingTrash);
  elements.trashHint.classList.toggle("hidden", !showingTrash);
  elements.reviewToolbar.classList.toggle("hidden", !showingReview);
  elements.viewTitle.textContent = showingTrash
    ? "事项回收站"
    : showingReview
      ? "待核对工作台"
      : "事项看板";
  elements.trashLabel.textContent = showingTrash ? "返回看板" : "回收站";
  elements.trashToggle.setAttribute("aria-expanded", String(showingTrash));
  elements.trashToggle.classList.toggle("active", showingTrash);
}

function updateBulkUi() {
  elements.bulkToggle.classList.toggle("active", bulkMode);
  elements.bulkToggle.setAttribute("aria-pressed", String(bulkMode));
  elements.bulkToggle.textContent = bulkMode ? "退出批量" : "批量处理";
  elements.bulkBar.classList.toggle("hidden", !bulkMode);
  elements.bulkCount.textContent = `已选择 ${selectedActivityIds.size} 项`;
  elements.bulkComplete.disabled = selectedActivityIds.size === 0;
}

function setBulkMode(open) {
  bulkMode = open;
  if (!open) selectedActivityIds.clear();
  updateBulkUi();
}

function signatureOf(activities, trash, messages, reviews = []) {
  const rows = activities.map((item) => `${item.id}:${item.status}:${item.updated_at}`);
  const removed = trash.map((item) => `${item.id}:${item.updated_at}`);
  const stream = messages.map((item) => `${item.id}:${item.kind}:${item.activity_id}`);
  const review = reviews.map(
    (item) => `${item.activity.id}:${item.activity.updated_at}`,
  );
  return `${rows.join(",")}#${removed.join(",")}#${stream.join(",")}#${review.join(",")}`;
}

async function fetchBoard() {
  const query =
    currentStatus && currentStatus !== "review"
      ? `?status=${encodeURIComponent(currentStatus)}`
      : "";
  const calls = [
    request("/activities"),
    request("/trash"),
    request(`/activities${query}`),
    request("/reviews"),
  ];
  // 访客看不到群消息流水，连请求都不发。
  if (!isGuest) calls.push(request("/messages?limit=50"));
  const [all, trash, visible, reviews, messages = []] = await Promise.all(calls);
  return { all, trash, visible, reviews, messages };
}

function messageRow(message) {
  const isChat = message.kind === "chat";
  const action = isChat
    ? `<button type="button" class="text-button" data-action="promote" data-id="${message.id}">提取成卡片</button>`
    : message.activity_id
      ? `<button type="button" class="text-button" data-action="locate">看事项卡</button>`
      : "";
  return `
    <article class="message-row ${isChat ? "chat" : "notice"}">
      <div class="message-meta">
        <span class="message-badge ${isChat ? "chat" : "notice"}">${isChat ? "闲聊" : "通知"}</span>
        <time>${escapeHtml(formatTrashTime(message.sent_at))}</time>
      </div>
      <p class="message-text">${escapeHtml(message.text)}</p>
      <div class="message-action">${action}</div>
    </article>`;
}

function renderMessages(messages) {
  elements.messageCount.textContent = messages.length;
  if (elements.messageList.classList.contains("hidden")) return;
  elements.messageList.innerHTML = messages.length
    ? messages.map(messageRow).join("")
    : `<div class="empty-state">还没有收到任何消息</div>`;
}

function activityGroup(activity) {
  if (["completed", "ignored", "cancelled"].includes(activity.status)) {
    return "completed";
  }
  return deadlineInfo(activity.deadline).state;
}

function renderActivityGroups(activities) {
  const definitions = [
    ["overdue", "已过截止时间"],
    ["today", "今天截止"],
    ["soon", "3 天内截止"],
    ["later", "之后截止"],
    ["missing", "待补充截止时间"],
    ["completed", "已完成或已关闭"],
  ];
  return definitions
    .map(([key, label]) => {
      const items = activities.filter((item) => activityGroup(item) === key);
      if (!items.length) return "";
      return `
        <section class="board-group" aria-labelledby="group-${key}">
          <div class="board-group-heading">
            <h3 id="group-${key}">${label}</h3>
            <span>${items.length} 项</span>
          </div>
          <div class="board-group-list">${items.map(activityCard).join("")}</div>
        </section>`;
    })
    .join("");
}

function renderBoard(all, trash, visible, messages, reviews = []) {
  reviewItems = reviews;
  lastSignature = signatureOf(all, trash, messages, reviews);
  lastBoardData = { all, trash, visible, messages, reviews };
  elements.workspace.classList.toggle(
    "is-empty",
    all.length === 0 && trash.length === 0,
  );
  elements.metrics.total.textContent = all.length;
  elements.metrics.open.textContent = all.filter((item) => item.status === "open").length;
  elements.metrics.review.textContent = reviews.length;
  elements.metrics.done.textContent = all.filter((item) => item.status === "completed").length;
  elements.filterReviewCount.textContent = reviews.length;
  elements.trashCount.textContent = trash.length;
  renderMessages(messages);
  maybeShowMessageNotification(all, messages);
  if (currentView === "trash") {
    elements.list.innerHTML = trash.length
      ? trash.map(trashCard).join("")
      : `<div class="empty-state">回收站是空的</div>`;
    return;
  }
  if (currentStatus === "review") {
    elements.list.innerHTML = reviews.length
      ? reviews.map(reviewCard).join("")
      : `<div class="empty-state">没有待核对事项，解析结果可以直接使用。</div>`;
    return;
  }
  elements.list.innerHTML = visible.length
    ? currentStatus
      ? visible.map(activityCard).join("")
      : renderActivityGroups(visible)
    : `<div class="empty-state">${currentStatus ? "这个分类里还没有事项" : "导入一条通知，建立第一张事项卡"}</div>`;
}

function focusActivity(activityId, isNew = false) {
  const card = elements.list.querySelector(
    `[data-activity-id="${CSS.escape(String(activityId))}"]`,
  );
  if (!card) return false;
  if (isNew) {
    card.classList.add("activity-new");
    window.setTimeout(() => card.classList.remove("activity-new"), 1800);
  }
  card.scrollIntoView({ behavior: "smooth", block: "center" });
  window.setTimeout(() => card.focus({ preventScroll: true }), 260);
  return true;
}

function setBoardStatus(message = "", state = "") {
  elements.boardStatus.classList.toggle("hidden", !message);
  elements.boardStatus.dataset.state = state;
  elements.boardStatus.innerHTML = message;
}

function setBoardFreshness(message, state = "") {
  elements.boardFreshness.textContent = message;
  elements.boardFreshness.dataset.state = state;
}

function renderBoardLoading() {
  if (lastBoardData) return;
  elements.list.innerHTML = `
    <div class="loading-list" aria-label="正在读取事项">
      <div class="skeleton-row"></div>
      <div class="skeleton-row"></div>
      <div class="skeleton-row"></div>
    </div>`;
}

async function refresh(options = {}) {
  if (options.loading) {
    elements.workspace.classList.remove("is-empty");
    elements.list.setAttribute("aria-busy", "true");
    renderBoardLoading();
  }
  try {
    const { all, trash, visible, reviews, messages } = await fetchBoard();
    renderBoard(all, trash, visible, messages, reviews);
    setBoardStatus();
    setBoardFreshness(
      `更新于 ${new Intl.DateTimeFormat("zh-CN", {
        hour: "2-digit",
        minute: "2-digit",
        hour12: false,
      }).format(new Date())}`,
      "ok",
    );
  } catch (error) {
    elements.workspace.classList.remove("is-empty");
    setBoardStatus(
      `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
      "error",
    );
    setBoardFreshness("数据未能刷新", "error");
    throw error;
  } finally {
    elements.list.removeAttribute("aria-busy");
  }
}

// 群消息由后端接收，前端轮询感知变化后再重绘，避免打断正在编辑的卡片。
function isBusyEditing() {
  if (elements.chatDialog?.open) return true;
  const active = document.activeElement;
  return Boolean(active && elements.list.contains(active) && active.closest("form"));
}

async function syncIfChanged() {
  if (document.hidden || isBusyEditing()) return;
  const data = await fetchBoard();
  if (signatureOf(data.all, data.trash, data.messages, data.reviews) === lastSignature) return;
  renderBoard(data.all, data.trash, data.visible, data.messages, data.reviews);
  elements.status.textContent = "收到新消息，看板已更新。";
}

function startLiveSync() {
  window.setInterval(() => {
    syncIfChanged().catch((error) =>
      setBoardStatus(
        `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
        "error",
      ),
    );
  }, 15000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    syncIfChanged().catch((error) =>
      setBoardStatus(
        `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
        "error",
      ),
    );
  });
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(base64);
  const bytes = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) {
    bytes[index] = raw.charCodeAt(index);
  }
  return bytes;
}

async function registerServiceWorker() {
  if (!("serviceWorker" in navigator)) return null;
  try {
    return await navigator.serviceWorker.register("/sw.js", { scope: "/" });
  } catch (error) {
    return null;
  }
}

async function refreshPushState() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    elements.pushNote.textContent =
      "当前浏览器不支持推送：Android 用 Chrome / Edge，iOS 需 16.4+ 且先「添加到主屏幕」。";
    elements.reminderSummary.textContent = "提醒不可用";
    elements.pushButton.disabled = true;
    return;
  }
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = registration
    ? await registration.pushManager.getSubscription()
    : null;
  if (subscription && Notification.permission === "granted") {
    elements.pushNote.textContent = "已在当前设备开启，截止前会自动提醒。";
    elements.reminderSummary.textContent = "提醒已开启";
    elements.pushButton.textContent = "已开启";
    elements.pushButton.disabled = true;
  } else {
    elements.reminderSummary.textContent = "提醒未开启";
  }
}

async function enablePush() {
  elements.pushButton.disabled = true;
  try {
    const registration = await registerServiceWorker();
    if (!registration) {
      throw new Error("Service Worker 注册失败，推送需要 HTTPS 或 localhost");
    }
    if (Notification.permission === "denied") {
      elements.pushNote.textContent = "通知权限已被拒绝，请到浏览器站点设置里重新允许。";
      elements.reminderSummary.textContent = "提醒被浏览器阻止";
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      elements.pushNote.textContent = "没有拿到通知权限，提醒未开启。";
      elements.reminderSummary.textContent = "提醒未开启";
      return;
    }
    const { publicKey } = await request("/push/public-key");
    if (!publicKey) throw new Error("服务端还没配置 VAPID 公钥");
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(publicKey),
    });
    const result = await request("/push/subscribe", {
      method: "POST",
      body: JSON.stringify(subscription),
    });
    elements.pushNote.textContent = `已开启，${result.count} 台设备会收到提醒。`;
    elements.reminderSummary.textContent = "提醒已开启";
    elements.pushButton.textContent = "已开启";
  } catch (error) {
    elements.pushNote.textContent = error.message;
    elements.pushButton.disabled = false;
  }
}

async function loadSession() {
  try {
    const session = await request("/session");
    isGuest = !session.authenticated;
    document.body.classList.toggle("guest", isGuest);
    elements.guestBanner.classList.toggle("hidden", !isGuest);
    return session;
  } catch (error) {
    isGuest = false;
    return { authenticated: true, guest: false };
  }
}

async function loadModelSettings() {
  const settings = await request("/model-settings");
  elements.modelSelect.innerHTML = settings.choices
    .map(
      (choice) =>
        `<option value="${escapeHtml(choice.id)}" ${choice.available ? "" : "disabled"}>${escapeHtml(choice.label)}${choice.available ? "" : "（不可用）"}</option>`,
    )
    .join("");
  elements.modelSelect.value = settings.provider;
  const selected = settings.choices.find((choice) => choice.id === settings.provider);
  elements.modelNote.textContent = selected?.note || "";
  elements.modelSummary.textContent = selected?.label || "模型未配置";
  updateChatAvailability(settings);
}

function updateChatAvailability(settings) {
  const selected = settings.choices.find((choice) => choice.id === settings.provider);
  chatAvailable = settings.provider !== "rules" && Boolean(selected?.available);
  const mobileChatButton = elements.mobileButtons.find(
    (button) => button.dataset.mobileAction === "chat",
  );
  elements.openChat.classList.toggle("hidden", !chatAvailable);
  mobileChatButton?.classList.toggle("hidden", !chatAvailable);
  elements.mobileNav.classList.toggle("chat-unavailable", !chatAvailable);
  if (!chatAvailable && elements.chatDialog.open) {
    elements.chatDialog.close();
  }
}

async function submitMessage(event) {
  event.preventDefault();
  const text = elements.text.value.trim();
  if (!text) return;
  elements.submit.disabled = true;
  elements.form.setAttribute("aria-busy", "true");
  const stages = [
    "正在读取通知原文…",
    "正在提取截止时间与材料…",
    "正在生成事项卡…",
  ];
  let stageIndex = 0;
  setFormStatus(stages[stageIndex], "working");
  const stageTimer = window.setInterval(() => {
    stageIndex = Math.min(stageIndex + 1, stages.length - 1);
    setFormStatus(stages[stageIndex], "working");
  }, 900);
  try {
    const result = await request("/messages", {
      method: "POST",
      body: JSON.stringify({
        platform: "manual",
        external_id: `manual-${crypto.randomUUID()}`,
        text,
      }),
    });
    setFormStatus(
      result.disposition === "duplicate"
        ? "这条消息已经处理过。"
        : result.disposition === "skipped"
          ? "已存入群消息流水（判定为闲聊，没有建卡）。"
          : "已保存，事项卡已生成。",
      "success",
    );
    if (result.activity?.source_message_id) {
      rememberNotificationSeen(result.activity.source_message_id);
    }
    elements.preview.classList.add("converting");
    elements.text.value = "";
    await refresh();
    window.setTimeout(clearExtractionPreview, 280);
    if (result.activity) {
      window.setTimeout(
        () => focusActivity(result.activity.id, result.disposition !== "duplicate"),
        180,
      );
    }
  } catch (error) {
    setFormStatus(`${error.message}。请检查内容后重试。`, "error");
  } finally {
    window.clearInterval(stageTimer);
    elements.form.removeAttribute("aria-busy");
    elements.submit.disabled = false;
  }
}

elements.form.addEventListener("submit", submitMessage);
elements.settingsToggle.addEventListener("click", () => {
  setMobileSettingsOpen(elements.settingsPanel.classList.contains("hidden"));
});
elements.text.addEventListener("input", scheduleExtractionPreview);
elements.text.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
    event.preventDefault();
    elements.form.requestSubmit();
  }
});
elements.pushButton.addEventListener("click", enablePush);
elements.sample.addEventListener("click", () => {
  elements.text.value = sample;
  elements.text.focus();
  scheduleExtractionPreview();
});

elements.messageToggle.addEventListener("click", async () => {
  const next = elements.messageToggle.getAttribute("aria-expanded") !== "true";
  elements.messageToggle.setAttribute("aria-expanded", String(next));
  elements.messageToggle.classList.toggle("active", next);
  elements.messageLabel.textContent = next ? "收起" : "展开";
  elements.messageList.classList.toggle("hidden", !next);
  if (!next) return;
  try {
    renderMessages(await request("/messages?limit=50"));
  } catch (error) {
    elements.messageList.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  }
});

elements.messageList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  if (button.dataset.action === "locate") {
    elements.boardSection.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "提取中…";
  try {
    await request(`/messages/${button.dataset.id}/promote`, { method: "POST" });
    await refresh();
  } catch (error) {
    button.textContent = error.message;
    window.setTimeout(() => {
      button.textContent = original;
      button.disabled = false;
    }, 2500);
  }
});

elements.modelSelect.addEventListener("change", async () => {
  elements.modelSelect.disabled = true;
  try {
    const settings = await request("/model-settings", {
      method: "PUT",
      body: JSON.stringify({ provider: elements.modelSelect.value }),
    });
    const selected = settings.choices.find(
      (choice) => choice.id === settings.provider,
    );
    elements.modelNote.textContent = selected?.note || "模型已切换。";
    elements.modelSummary.textContent = selected?.label || "模型已切换";
    updateChatAvailability(settings);
  } catch (error) {
    elements.modelNote.textContent = error.message;
    await loadModelSettings();
  } finally {
    elements.modelSelect.disabled = false;
  }
});

function openChatDialog() {
  if (!chatAvailable) {
    elements.modelSection.scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  if (!elements.chatFrame.getAttribute("src")) {
    elements.chatFrame.src = elements.chatFrame.dataset.src;
  }
  chatReturnFocus =
    document.activeElement instanceof HTMLElement ? document.activeElement : null;
  elements.chatDialog.showModal();
}

elements.openChat.addEventListener("click", openChatDialog);
elements.chatDialog.addEventListener("close", () => {
  if (chatReturnFocus?.isConnected) {
    window.setTimeout(() => chatReturnFocus.focus({ preventScroll: true }), 0);
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && elements.chatDialog.open) {
    elements.chatDialog.close();
  }
});

elements.mobileButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.mobileAction;
    if (action === "chat") {
      openChatDialog();
      return;
    }
    setMobileSettingsOpen(action === "settings");
    elements.mobileButtons.forEach((item) =>
      item.classList.toggle("active", item === button),
    );
    if (action === "import") {
      elements.importSection.scrollIntoView({ behavior: "smooth", block: "start" });
      window.setTimeout(() => elements.text.focus(), 260);
      return;
    }
    if (action === "settings") {
      elements.settingsArea.scrollIntoView({ behavior: "smooth", block: "start" });
      window.setTimeout(() => elements.modelSelect.focus(), 260);
      return;
    }
    elements.boardSection.scrollIntoView({ behavior: "smooth", block: "start" });
  });
});

window.addEventListener("message", (event) => {
  if (
    event.origin === window.location.origin &&
    event.data?.type === "banwutong-close-chat"
  ) {
    elements.chatDialog.close();
  }
});

elements.fileForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const file = elements.fileInput.files[0];
  if (!file) return;
  const button = elements.fileForm.querySelector("button[type='submit']");
  button.disabled = true;
  elements.fileForm.setAttribute("aria-busy", "true");
  const stages = [
    `正在上传 ${file.name}…`,
    "正在读取文档内容…",
    "正在提取事项与截止时间…",
  ];
  let stageIndex = 0;
  elements.fileStatus.textContent = stages[stageIndex];
  const stageTimer = window.setInterval(() => {
    stageIndex = Math.min(stageIndex + 1, stages.length - 1);
    elements.fileStatus.textContent = stages[stageIndex];
  }, 1100);
  try {
    const formData = new FormData();
    formData.append("file", file);
    const result = await request("/files", {
      method: "POST",
      body: formData,
    });
    if (result.disposition === "duplicate") {
      elements.fileStatus.textContent = "这个文件已经上传过。";
    } else if (result.activities.length) {
      elements.fileStatus.textContent =
        `文件已保存，并整理了 ${result.activities.length} 个事项。`;
    } else if (result.document.extract_status === "failed") {
      elements.fileStatus.textContent =
        "文件已保存，但没能读出文字。换一张更清楚的图片，或到事项里手动补充。";
    } else {
      elements.fileStatus.textContent = "文件已保存，没有识别出新的待办事项。";
    }
    elements.fileForm.reset();
    await refresh();
  } catch (error) {
    elements.fileStatus.textContent = `${error.message}。请重试。`;
  } finally {
    window.clearInterval(stageTimer);
    elements.fileForm.removeAttribute("aria-busy");
    button.disabled = false;
  }
});

elements.filters.forEach((button) => {
  button.addEventListener("click", () => {
    setBulkMode(false);
    currentStatus = button.dataset.status;
    elements.filters.forEach((item) => item.classList.toggle("active", item === button));
    setView("board");
    refresh().catch((error) => {
      setBoardStatus(
        `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
        "error",
      );
    });
  });
});

elements.bulkToggle.addEventListener("click", () => {
  setBulkMode(!bulkMode);
  setView("board");
  refresh().catch((error) => setFormStatus(error.message, "error"));
});

elements.boardStatus.addEventListener("click", (event) => {
  if (!event.target.closest("[data-action='retry-board']")) return;
  refresh({ loading: !lastBoardData }).catch(() => {});
});

elements.bulkCancel.addEventListener("click", () => {
  setBulkMode(false);
  refresh().catch((error) => setFormStatus(error.message, "error"));
});

elements.list.addEventListener("change", (event) => {
  const checkbox = event.target.closest("input[data-bulk-id]");
  if (!checkbox) return;
  const id = Number(checkbox.dataset.bulkId);
  if (checkbox.checked) selectedActivityIds.add(id);
  else selectedActivityIds.delete(id);
  checkbox.closest(".activity")?.classList.toggle("selected", checkbox.checked);
  updateBulkUi();
});

elements.bulkComplete.addEventListener("click", async () => {
  const ids = [...selectedActivityIds];
  if (!ids.length) return;
  elements.bulkComplete.disabled = true;
  try {
    const results = await Promise.allSettled(
      ids.map((id) =>
        request(`/activities/${id}`, {
          method: "PATCH",
          body: JSON.stringify({ status: "completed" }),
        }),
      ),
    );
    const completed = results.filter((result) => result.status === "fulfilled").length;
    const failed = results.length - completed;
    setFormStatus(
      failed
        ? `已完成 ${completed} 项，${failed} 项未能更新。`
        : `已将 ${completed} 项标记为完成。`,
      failed ? "error" : "success",
    );
    setBulkMode(false);
    await refresh();
  } catch (error) {
    setFormStatus(error.message, "error");
    elements.bulkComplete.disabled = false;
  }
});

elements.batchConfirm.addEventListener("click", async () => {
  const ids = reviewItems
    .filter((item) => !item.reasons.some((reason) => reason.severity === "blocking"))
    .map((item) => item.activity.id);
  if (!ids.length) {
    elements.status.textContent = "没有可以批量确认的低风险事项，请逐条核对。";
    return;
  }
  elements.batchConfirm.disabled = true;
  try {
    const result = await request("/reviews/batch-confirm", {
      method: "POST",
      body: JSON.stringify({ activity_ids: ids }),
    });
    elements.status.textContent = result.skipped.length
      ? `已确认 ${result.confirmed.length} 项，还有 ${result.skipped.length} 项需要逐条核对。`
      : `已确认 ${result.confirmed.length} 项。`;
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
  } finally {
    elements.batchConfirm.disabled = false;
  }
});

elements.trashToggle.addEventListener("click", () => {
  setBulkMode(false);
  setView(currentView === "trash" ? "board" : "trash");
  refresh().catch((error) => {
    setBoardStatus(
      `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
      "error",
    );
  });
});

elements.list.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  if (button.dataset.action === "edit" || button.dataset.action === "review-edit") {
    const card = button.closest(".activity");
    card.querySelector(".edit-form").classList.remove("hidden");
    card.querySelector("input[name='title']").focus();
    return;
  }
  if (button.dataset.action === "source") {
    const card = button.closest(".activity");
    const box = card.querySelector(".source-box");
    if (!box.classList.contains("hidden")) {
      box.classList.add("hidden");
      button.textContent = "查看原文";
      return;
    }
    if (!box.dataset.loaded) {
      try {
        const source = await request(`/activities/${button.dataset.id}/source`);
        box.textContent = source.text;
        box.dataset.loaded = "1";
      } catch (error) {
        box.textContent = error.message;
      }
    }
    box.classList.remove("hidden");
    button.textContent = "收起原文";
    return;
  }
  if (button.dataset.action === "review-confirm") {
    button.disabled = true;
    try {
      await request(`/activities/${button.dataset.id}/confirm`, {
        method: "POST",
        body: JSON.stringify({}),
      });
      elements.status.textContent = "已确认，提醒会按当前截止时间发送。";
      await refresh();
    } catch (error) {
      elements.status.textContent = error.message;
      button.disabled = false;
    }
    return;
  }
  if (button.dataset.action === "cancel-edit") {
    button.closest(".edit-form").classList.add("hidden");
    return;
  }
  if (button.dataset.action === "delete") {
    if (!window.confirm("确定删除这个已完成事项吗？它会在回收站保留 7 天。")) return;
    button.disabled = true;
    try {
      await request(`/activities/${button.dataset.id}`, { method: "DELETE" });
      elements.status.textContent = "事项已移入回收站，将在 7 天后自动彻底删除。";
      await refresh();
    } catch (error) {
      elements.status.textContent = error.message;
      button.disabled = false;
    }
    return;
  }
  if (button.dataset.action === "restore") {
    button.disabled = true;
    try {
      await request(`/activities/${button.dataset.id}/restore`, { method: "POST" });
      elements.status.textContent = "事项已恢复到看板。";
      await refresh();
    } catch (error) {
      elements.status.textContent = error.message;
      button.disabled = false;
    }
    return;
  }
  if (button.dataset.action === "purge") {
    if (!window.confirm("彻底删除后无法恢复，确定继续吗？")) return;
    button.disabled = true;
    try {
      await request(`/trash/${button.dataset.id}`, { method: "DELETE" });
      await refresh();
    } catch (error) {
      elements.status.textContent = error.message;
      button.disabled = false;
    }
    return;
  }
  button.disabled = true;
  try {
    const status = button.dataset.status;
    await request(`/activities/${button.dataset.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
    button.disabled = false;
  }
});

elements.list.addEventListener("submit", async (event) => {
  const form = event.target.closest(".edit-form");
  if (!form) return;
  event.preventDefault();
  const data = new FormData(form);
  const saveButton = form.querySelector("button[type='submit']");
  saveButton.disabled = true;
  try {
    const materials = String(data.get("materials") || "")
      .split(/[、,，;；\n]+/)
      .map((item) => item.trim())
      .filter(Boolean);
    const payload = {
      title: data.get("title"),
      deadline: data.get("deadline") || null,
      audience: data.get("audience") || null,
      materials,
      location: data.get("location") || null,
      contact: data.get("contact") || null,
      registration_url: data.get("registration_url") || null,
    };
    if (form.dataset.confirm === "1") {
      await request(`/activities/${form.dataset.editId}/confirm`, {
        method: "POST",
        body: JSON.stringify({ edits: payload }),
      });
      elements.status.textContent = "已保存修正并确认，提醒会按新截止时间发送。";
    } else {
      await request(`/activities/${form.dataset.editId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
      elements.status.textContent = "事项内容已更新。";
    }
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
    saveButton.disabled = false;
  }
});

loadSession()
  .then(() => refresh({ loading: true }))
  .then(() => startLiveSync())
  .catch((error) => {
    setBoardStatus(
      `${escapeHtml(error.message)} <button class="text-button" type="button" data-action="retry-board">重试</button>`,
      "error",
    );
  });
loadModelSettings().catch((error) => {
  elements.modelNote.textContent = error.message;
  elements.modelSummary.textContent = "模型状态不可用";
});
registerServiceWorker()
  .then(() => refreshPushState())
  .catch(() => {
    elements.reminderSummary.textContent = "提醒状态不可用";
  });

const NOTIFICATION_SEEN_KEY = "banwutong-seen-notifications-v1";
const toast = document.getElementById("update-toast");
let notificationTimer = null;

function setUpdateToastVisible(visible) {
  if (!toast) return;
  toast.classList.toggle("show", visible);
  toast.setAttribute("aria-hidden", String(!visible));
  toast.toggleAttribute("inert", !visible);
}

function seenNotificationIds() {
  try {
    const value = JSON.parse(localStorage.getItem(NOTIFICATION_SEEN_KEY) || "[]");
    return new Set(Array.isArray(value) ? value.map(Number) : []);
  } catch {
    return new Set();
  }
}

function rememberNotificationSeen(messageId) {
  try {
    const ids = [...seenNotificationIds(), Number(messageId)].slice(-100);
    localStorage.setItem(NOTIFICATION_SEEN_KEY, JSON.stringify(ids));
  } catch {
    // Notifications still work when storage is unavailable.
  }
}

function showMessageNotification(activityId, title, message) {
  currentToastActivityId = activityId;
  elements.toastTitle.textContent = title || "收到新通知";
  elements.toastMessage.textContent = message;
  elements.toastAction.textContent = activityId ? "查看事项" : "去导入";
  setUpdateToastVisible(true);
}

function maybeShowMessageNotification(activities, messages) {
  if (!toast || document.hidden) return;
  const latest = messages.find(
    (message) => message.kind === "notice" && message.activity_id,
  );
  if (!latest) return;
  const seen = seenNotificationIds();
  if (seen.has(Number(latest.id))) return;
  rememberNotificationSeen(latest.id);
  const activity = activities.find((item) => item.id === latest.activity_id);
  const summary = latest.text.replace(/\s+/g, " ").trim();
  window.clearTimeout(notificationTimer);
  notificationTimer = window.setTimeout(
    () =>
      showMessageNotification(
        latest.activity_id,
        activity?.title || "收到新通知",
        summary.length > 72 ? `${summary.slice(0, 72)}…` : summary,
      ),
    700,
  );
}

window.closeToast = function () {
  setUpdateToastVisible(false);
};

window.viewUpdateToast = function () {
  window.closeToast();
  if (!currentToastActivityId) {
    elements.importSection.scrollIntoView({ behavior: "smooth", block: "start" });
    window.setTimeout(() => elements.text.focus(), 260);
    return;
  }
  const cardExists = focusActivity(currentToastActivityId);
  if (cardExists) return;
  currentStatus = "";
  elements.filters.forEach((button) =>
    button.classList.toggle("active", button.dataset.status === ""),
  );
  setView("board");
  refresh()
    .then(() => focusActivity(currentToastActivityId))
    .catch((error) => setFormStatus(error.message, "error"));
};

