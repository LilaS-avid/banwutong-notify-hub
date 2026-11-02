const API = "/api";
let currentStatus = "";
let currentView = "board";
let reviewItems = [];
let isGuest = false;
let lastSignature = "";

const elements = {
  form: document.querySelector("#message-form"),
  text: document.querySelector("#message-text"),
  submit: document.querySelector("#message-form button[type='submit']"),
  status: document.querySelector("#form-status"),
  list: document.querySelector("#activity-list"),
  sample: document.querySelector("#sample-button"),
  fileForm: document.querySelector("#file-form"),
  fileInput: document.querySelector("#file-input"),
  fileStatus: document.querySelector("#file-status"),
  modelSelect: document.querySelector("#model-provider"),
  modelNote: document.querySelector("#model-note"),
  pushButton: document.querySelector("#push-enable"),
  pushNote: document.querySelector("#push-note"),
  openChat: document.querySelector("#open-chat"),
  mobileNav: document.querySelector("#mobile-nav"),
  mobileButtons: [...document.querySelectorAll("[data-mobile-action]")],
  boardSection: document.querySelector("#board-section"),
  importSection: document.querySelector("#import-section"),
  modelSection: document.querySelector("#model-section"),
  chatDialog: document.querySelector("#chat-dialog"),
  chatFrame: document.querySelector("#chat-frame"),
  messageSection: document.querySelector("#message-section"),
  messageList: document.querySelector("#message-list"),
  messageToggle: document.querySelector("#message-toggle"),
  messageLabel: document.querySelector("#message-label"),
  messageCount: document.querySelector("#message-count"),
  guestBanner: document.querySelector("#guest-banner"),
  filters: [...document.querySelectorAll(".filter")],
  statusFilters: document.querySelector("#status-filters"),
  trashToggle: document.querySelector("#trash-toggle"),
  trashLabel: document.querySelector("#trash-label"),
  trashCount: document.querySelector("#trash-count"),
  trashHint: document.querySelector("#trash-hint"),
  viewTitle: document.querySelector("#view-title"),
  viewKicker: document.querySelector("#view-kicker"),
  reviewToolbar: document.querySelector("#review-toolbar"),
  batchConfirm: document.querySelector("#batch-confirm"),
  filterReviewCount: document.querySelector("#filter-review-count"),
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
报名链接：https://example.com/register
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

function updateDeviceLayout() {
  const mobileDevice =
    mobileViewport.matches || navigator.userAgentData?.mobile === true;
  document.body.classList.toggle("device-mobile", mobileDevice);
  document.documentElement.dataset.device = mobileDevice ? "mobile" : "desktop";
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

  return `
    <article class="activity">
      <div class="activity-top">
        <h3>${escapeHtml(activity.title)}</h3>
        <span class="badge ${badgeClass}">${statusLabels[effectiveStatus] || escapeHtml(effectiveStatus)}</span>
        ${reviewBadge}
      </div>
      <div class="meta-grid">
        <div><b>截止时间</b>${escapeHtml(formatDeadline(activity.deadline))}</div>
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
  elements.viewKicker.textContent = showingTrash
    ? "TRASH · 保留 7 天"
    : showingReview
      ? "REVIEW · 需人工确认"
      : "INBOX";
  elements.trashLabel.textContent = showingTrash ? "返回看板" : "回收站";
  elements.trashToggle.setAttribute("aria-expanded", String(showingTrash));
  elements.trashToggle.classList.toggle("active", showingTrash);
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

function renderBoard(all, trash, visible, messages, reviews = []) {
  reviewItems = reviews;
  lastSignature = signatureOf(all, trash, messages, reviews);
  elements.metrics.total.textContent = all.length;
  elements.metrics.open.textContent = all.filter((item) => item.status === "open").length;
  elements.metrics.review.textContent = reviews.length;
  elements.metrics.done.textContent = all.filter((item) => item.status === "completed").length;
  elements.filterReviewCount.textContent = reviews.length;
  elements.trashCount.textContent = trash.length;
  renderMessages(messages);
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
    ? visible.map(activityCard).join("")
    : `<div class="empty-state">${currentStatus ? "这个分类里还没有事项" : "导入一条通知，建立第一张事项卡"}</div>`;
}

async function refresh() {
  const { all, trash, visible, reviews, messages } = await fetchBoard();
  renderBoard(all, trash, visible, messages, reviews);
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
    syncIfChanged().catch(() => {});
  }, 15000);
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    syncIfChanged().catch(() => {});
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
    elements.pushButton.disabled = true;
    return;
  }
  const registration = await navigator.serviceWorker.getRegistration("/");
  const subscription = registration
    ? await registration.pushManager.getSubscription()
    : null;
  if (subscription && Notification.permission === "granted") {
    elements.pushNote.textContent = "已在当前设备开启，截止前会自动提醒。";
    elements.pushButton.textContent = "已开启";
    elements.pushButton.disabled = true;
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
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") {
      elements.pushNote.textContent = "没有拿到通知权限，提醒未开启。";
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
}

async function submitMessage(event) {
  event.preventDefault();
  elements.submit.disabled = true;
  elements.status.textContent = "正在解析并写入本地数据库……";
  try {
    const result = await request("/messages", {
      method: "POST",
      body: JSON.stringify({
        platform: "manual",
        external_id: `manual-${crypto.randomUUID()}`,
        text: elements.text.value,
      }),
    });
    elements.status.textContent =
      result.disposition === "duplicate"
        ? "这条消息已经处理过。"
        : result.disposition === "skipped"
          ? "已存入群消息流水（判定为闲聊，没有建卡）。"
          : "已保存并生成事项。";
    elements.text.value = "";
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
  } finally {
    elements.submit.disabled = false;
  }
}

elements.form.addEventListener("submit", submitMessage);
elements.pushButton.addEventListener("click", enablePush);
elements.sample.addEventListener("click", () => {
  elements.text.value = sample;
  elements.text.focus();
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
  } catch (error) {
    elements.modelNote.textContent = error.message;
    await loadModelSettings();
  } finally {
    elements.modelSelect.disabled = false;
  }
});

function openChatDialog() {
  if (!elements.chatFrame.getAttribute("src")) {
    elements.chatFrame.src = elements.chatFrame.dataset.src;
  }
  elements.chatDialog.showModal();
}

elements.openChat.addEventListener("click", openChatDialog);

elements.mobileButtons.forEach((button) => {
  button.addEventListener("click", () => {
    elements.mobileButtons.forEach((item) =>
      item.classList.toggle("active", item === button),
    );
    const action = button.dataset.mobileAction;
    if (action === "chat") {
      openChatDialog();
      return;
    }
    if (action === "import") {
      elements.importSection.scrollIntoView({ behavior: "smooth", block: "start" });
      window.setTimeout(() => elements.text.focus(), 260);
      return;
    }
    if (action === "settings") {
      elements.modelSection.scrollIntoView({ behavior: "smooth", block: "start" });
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
  elements.fileStatus.textContent = `正在上传 ${file.name}……`;
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
    elements.fileStatus.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});

elements.filters.forEach((button) => {
  button.addEventListener("click", () => {
    currentStatus = button.dataset.status;
    elements.filters.forEach((item) => item.classList.toggle("active", item === button));
    setView("board");
    refresh().catch((error) => {
      elements.list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });
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
  setView(currentView === "trash" ? "board" : "trash");
  refresh().catch((error) => {
    elements.list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
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
  .then(() => refresh())
  .then(() => startLiveSync())
  .catch((error) => {
    elements.list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
  });
loadModelSettings().catch((error) => {
  elements.modelNote.textContent = error.message;
});
registerServiceWorker()
  .then(() => refreshPushState())
  .catch(() => {});

