const API = "/api";
let currentStatus = "";

const elements = {
  form: document.querySelector("#message-form"),
  text: document.querySelector("#message-text"),
  submit: document.querySelector("#message-form button[type='submit']"),
  status: document.querySelector("#form-status"),
  list: document.querySelector("#activity-list"),
  sample: document.querySelector("#sample-button"),
  filters: [...document.querySelectorAll(".filter")],
  metrics: {
    total: document.querySelector("#metric-total"),
    open: document.querySelector("#metric-open"),
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

function editForm(activity) {
  return `
    <form class="edit-form hidden" data-edit-id="${activity.id}">
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
        <button class="save-edit" type="submit">保存修改</button>
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

  return `
    <article class="activity">
      <div class="activity-top">
        <h3>${escapeHtml(activity.title)}</h3>
        <span class="badge ${badgeClass}">${statusLabels[effectiveStatus] || escapeHtml(effectiveStatus)}</span>
      </div>
      <div class="meta-grid">
        <div><b>截止时间</b>${escapeHtml(formatDeadline(activity.deadline))}</div>
        <div><b>适用对象</b>${escapeHtml(activity.audience || "未填写")}</div>
        <div><b>报名材料</b>${escapeHtml(materials)}</div>
        <div><b>地点 / 联系人</b>${escapeHtml([activity.location, activity.contact].filter(Boolean).join(" · ") || "未填写")}</div>
      </div>
      ${editForm(activity)}
      <div class="card-actions">
        ${link}
        <button type="button" data-action="edit">编辑内容</button>
        ${statusActions}
      </div>
    </article>`;
}

async function request(path, options = {}) {
  const response = await fetch(`${API}${path}`, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => ({}));
    throw new Error(detail.detail || `请求失败：${response.status}`);
  }
  return response.json();
}

async function refresh() {
  const query = currentStatus ? `?status=${encodeURIComponent(currentStatus)}` : "";
  const [all, visible] = await Promise.all([
    request("/activities"),
    request(`/activities${query}`),
  ]);
  elements.metrics.total.textContent = all.length;
  elements.metrics.open.textContent = all.filter((item) => item.status === "open").length;
  elements.metrics.done.textContent = all.filter((item) => item.status === "completed").length;
  elements.list.innerHTML = visible.length
    ? visible.map(activityCard).join("")
    : `<div class="empty-state">${currentStatus ? "这个分类里还没有事项" : "导入一条通知，建立第一张事项卡"}</div>`;
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
      result.disposition === "duplicate" ? "这条消息已经处理过。" : "已保存并生成事项。";
    elements.text.value = "";
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
  } finally {
    elements.submit.disabled = false;
  }
}

elements.form.addEventListener("submit", submitMessage);
elements.sample.addEventListener("click", () => {
  elements.text.value = sample;
  elements.text.focus();
});

elements.filters.forEach((button) => {
  button.addEventListener("click", () => {
    currentStatus = button.dataset.status;
    elements.filters.forEach((item) => item.classList.toggle("active", item === button));
    refresh().catch((error) => {
      elements.list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
    });
  });
});

elements.list.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  if (button.dataset.action === "edit") {
    const card = button.closest(".activity");
    card.querySelector(".edit-form").classList.remove("hidden");
    card.querySelector("input[name='title']").focus();
    return;
  }
  if (button.dataset.action === "cancel-edit") {
    button.closest(".edit-form").classList.add("hidden");
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
    await request(`/activities/${form.dataset.editId}`, {
      method: "PUT",
      body: JSON.stringify({
        title: data.get("title"),
        deadline: data.get("deadline") || null,
        audience: data.get("audience") || null,
        materials,
        location: data.get("location") || null,
        contact: data.get("contact") || null,
        registration_url: data.get("registration_url") || null,
      }),
    });
    elements.status.textContent = "事项内容已更新。";
    await refresh();
  } catch (error) {
    elements.status.textContent = error.message;
    saveButton.disabled = false;
  }
});

refresh().catch((error) => {
  elements.list.innerHTML = `<div class="empty-state">${escapeHtml(error.message)}</div>`;
});

