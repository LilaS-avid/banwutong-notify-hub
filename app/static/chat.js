const STORAGE_KEY = "banwutong-chat-history-v1";

const elements = {
  messages: document.querySelector("#chat-messages"),
  welcome: document.querySelector("#chat-welcome"),
  context: document.querySelector("#chat-context"),
  form: document.querySelector("#chat-form"),
  input: document.querySelector("#chat-input"),
  send: document.querySelector("#chat-send"),
  clear: document.querySelector("#clear-chat"),
  close: document.querySelector("#close-chat"),
  provider: document.querySelector("#provider-label"),
  error: document.querySelector("#chat-error"),
};

let history = loadHistory();
let activeProvider = "codex";

const embedded = new URLSearchParams(window.location.search).get("embedded") === "1";
if (embedded) {
  document.body.classList.add("embedded");
  elements.close.classList.remove("hidden");
}

function loadHistory() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || "[]");
    return Array.isArray(value)
      ? value.filter(
          (item) =>
            item &&
            ["user", "assistant"].includes(item.role) &&
            typeof item.content === "string",
        )
      : [];
  } catch {
    return [];
  }
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function saveHistory() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(history.slice(-30)));
  elements.clear.disabled = history.length === 0;
}

function formatContextDeadline(value) {
  if (!value) return "截止时间待核对";
  const deadline = new Date(value);
  if (Number.isNaN(deadline.getTime())) return "截止时间待核对";
  return new Intl.DateTimeFormat("zh-CN", {
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(deadline);
}

async function loadContext() {
  const [activitiesResponse, reviewsResponse] = await Promise.all([
    fetch("/api/activities"),
    fetch("/api/reviews"),
  ]);
  if (!activitiesResponse.ok) throw new Error("无法读取当前事项");
  const activities = await activitiesResponse.json();
  const reviews = reviewsResponse.ok ? await reviewsResponse.json() : [];
  const open = activities.filter((activity) => activity.status === "open");
  if (!open.length) {
    elements.context.innerHTML = `
      <p class="context-summary">当前没有待处理事项，可以先回主页导入一条通知。</p>`;
    elements.context.classList.remove("hidden");
    return;
  }
  const today = new Date();
  const todayCount = open.filter((activity) => {
    if (!activity.deadline) return false;
    const deadline = new Date(activity.deadline);
    return (
      deadline.getFullYear() === today.getFullYear() &&
      deadline.getMonth() === today.getMonth() &&
      deadline.getDate() === today.getDate()
    );
  }).length;
  const upcoming = [...open]
    .sort((left, right) => {
      if (!left.deadline) return 1;
      if (!right.deadline) return -1;
      return new Date(left.deadline) - new Date(right.deadline);
    })
    .slice(0, 3);
  elements.context.innerHTML = `
    <p class="context-summary">
      <strong>${open.length}</strong> 项待处理
      ${reviews.length ? `· <strong>${reviews.length}</strong> 项待核对` : ""}
      ${todayCount ? `· 今天截止 <strong>${todayCount}</strong> 项` : ""}
    </p>
    <div class="context-items">
      ${upcoming
        .map(
          (activity) => `
            <span>
              <b>${escapeHtml(activity.title)}</b>
              <small>${escapeHtml(formatContextDeadline(activity.deadline))}</small>
            </span>`,
        )
        .join("")}
    </div>`;
  elements.context.classList.remove("hidden");
}

function appendMessage(role, content, options = {}) {
  const article = document.createElement("article");
  article.className = `chat-message ${role}${options.thinking ? " thinking" : ""}`;
  const bubble = document.createElement("div");
  bubble.className = "chat-bubble";
  bubble.innerHTML = escapeHtml(content);
  article.appendChild(bubble);
  elements.messages.appendChild(article);
  elements.welcome.classList.add("hidden");
  elements.messages.scrollTop = elements.messages.scrollHeight;
  return article;
}

function renderHistory() {
  elements.messages.querySelectorAll(".chat-message").forEach((item) => item.remove());
  elements.welcome.classList.toggle("hidden", history.length > 0);
  history.forEach((message) => appendMessage(message.role, message.content));
  saveHistory();
}

async function loadProvider() {
  const response = await fetch("/api/model-settings");
  if (!response.ok) throw new Error("无法读取模型设置");
  const settings = await response.json();
  activeProvider = settings.provider;
  const selected = settings.choices.find((item) => item.id === activeProvider);
  elements.provider.textContent = selected
    ? `模型：${selected.label}`
    : `模型：${activeProvider}`;
  if (activeProvider === "rules") {
    elements.input.disabled = true;
    elements.send.disabled = true;
    elements.error.textContent = "当前是本地规则模式，请回主页切换到云端模型。";
  }
}

async function sendMessage() {
  const content = elements.input.value.trim();
  if (!content || activeProvider === "rules") return;
  elements.error.textContent = "";
  elements.input.value = "";
  elements.input.style.height = "";
  history.push({ role: "user", content });
  appendMessage("user", content);
  saveHistory();
  elements.send.disabled = true;
  const thinking = appendMessage("assistant", "正在思考……", { thinking: true });
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        messages: history.slice(-30),
      }),
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(result.detail || "模型没有返回结果");
    }
    thinking.remove();
    history.push({ role: "assistant", content: result.reply });
    appendMessage("assistant", result.reply);
    saveHistory();
  } catch (error) {
    thinking.remove();
    elements.error.textContent = error.message;
  } finally {
    elements.send.disabled = false;
    elements.input.focus();
  }
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  sendMessage();
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendMessage();
  }
});

elements.input.addEventListener("input", () => {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 150)}px`;
});

elements.clear.addEventListener("click", () => {
  history = [];
  elements.error.textContent = "";
  renderHistory();
  elements.input.focus();
});

function closeChat() {
  if (window.parent !== window) {
    window.parent.postMessage(
      { type: "banwutong-close-chat" },
      window.location.origin,
    );
  } else {
    window.location.href = "/";
  }
}

elements.close.addEventListener("click", closeChat);

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeChat();
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.input.value = button.dataset.prompt;
    elements.input.focus();
  });
});

renderHistory();
loadContext().catch(() => {});
loadProvider().catch((error) => {
  elements.error.textContent = error.message;
});
