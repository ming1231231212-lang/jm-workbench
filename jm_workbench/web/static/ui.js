export const escape = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const time = (value) =>
  value
    ? new Date(value * 1000).toLocaleString("zh-CN", { hour12: false })
    : "—";
export const states = {
  queued: "排队中",
  running: "执行中",
  waiting: "等待时段",
  completed: "已完成",
  paused: "已停止",
  failed: "执行异常",
  verified: "登录已核验",
  connected: "浏览器已连接",
  unverified: "待连接",
  collected: "已采集",
  checking: "待详情核验",
  eligible: "符合条件",
  skipped: "已跳过",
  sent: "平台已接收",
  unknown: "结果不确定",
  not_sent: "未发送",
  reserved: "发送中",
  legacy: "历史数据",
};
export const badge = (status) =>
  `<span class="badge ${["running", "verified", "completed", "sent", "eligible"].includes(status) ? "green" : ["failed", "unknown"].includes(status) ? "red" : ["waiting", "unverified", "checking"].includes(status) ? "amber" : "gray"}">${escape(states[status] || status)}</span>`;
export const field = (label, name, value = "", type = "text", extra = "") =>
  `<label class="field"><span>${label}</span><input name="${name}" type="${type}" value="${escape(value)}" ${extra}></label>`;
export const area = (label, name, value = "", hint = "") =>
  `<label class="field"><span>${label}</span><textarea name="${name}" rows="3" required>${escape(value)}</textarea>${hint ? `<small>${hint}</small>` : ""}</label>`;
export const select = (label, name, options, value) =>
  `<label class="field"><span>${label}</span><select name="${name}">${options.map(([id, name]) => `<option value="${escape(id)}" ${id === value ? "selected" : ""}>${escape(name)}</option>`).join("")}</select></label>`;
export const empty = (title, text, action = "") =>
  `<div class="empty"><div class="empty-symbol">◇</div><h3>${title}</h3><p>${text}</p>${action}</div>`;
export const heading = (kicker, title, desc, action = "") =>
  `<div class="page-heading"><div><div class="eyebrow">${kicker}</div><h1>${title}</h1><p>${desc}</p></div>${action}</div>`;
export const button = (label, action, id = "", cls = "") =>
  `<button type="button" class="button ${cls}" data-action="${action}" data-id="${escape(id)}">${label}</button>`;
export const names = {
  crawler: "内容与评论采集",
  adult_comments: "成人尾货收购",
  peiwang_comments: "陪玩18+招募",
};
