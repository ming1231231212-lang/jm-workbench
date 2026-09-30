import {
  escape as e,
  time,
  field,
  select,
  button,
  empty,
  heading,
} from "./ui.js";

export const publishStates = {
  draft: "本地草稿",
  queued: "等待执行",
  running: "提交中",
  paused: "已暂停",
  submitted: "已提交 · 未核验",
  unknown: "结果不明",
  failed: "未提交",
  cancelled: "已取消",
};
const mark = (state) =>
  `<span class="badge ${state === "running" ? "green" : state === "unknown" ? "red" : ["queued", "submitted"].includes(state) ? "amber" : "gray"}">${e(publishStates[state] || state)}</span>`;
const size = (n) => (n ? `${(n / 1024 / 1024).toFixed(1)} MB` : "原文件不可用");
const names = { ks: "快手", dy: "抖音", xhs: "小红书", tencent: "视频号" };
const localDate = (stamp) => {
  const d = new Date(stamp ? stamp * 1000 : Date.now() + 3600000);
  return new Date(d - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};

export function publishPayload(formData) {
  const mode = formData.get("mode") || "now";
  const schedule =
    mode === "scheduled"
      ? new Date(formData.get("schedule")).getTime() / 1000
      : 0;
  if (
    mode === "scheduled" &&
    (!Number.isFinite(schedule) || schedule <= Date.now() / 1000)
  )
    throw Error("请选择未来的发布时间");
  const payload = {
    request_id: String(formData.get("request_id")),
    title: String(formData.get("title") || "").trim(),
    material_ids: formData.getAll("material_ids").map(String),
    account_ids: formData.getAll("account_ids").map(String),
    tags: String(formData.get("tags") || "")
      .split(/[\s,，]+/)
      .map((s) => s.replace(/^#+/, ""))
      .filter(Boolean),
    mode,
    schedule_at: schedule,
    platform_draft: formData.get("platform_draft") === "on",
    product_link: String(formData.get("product_link") || "").trim(),
    product_title: String(formData.get("product_title") || "").trim(),
  };
  if (!payload.material_ids.length) throw Error("请选择至少一个视频");
  if (!payload.account_ids.length) throw Error("请选择至少一个发布账号");
  if (!payload.title) throw Error("请填写标题");
  return payload;
}

export function publishingPage(data, tab = "batches", filter = "all") {
  const connection = data.connected
    ? '<span class="connection-good">发布服务已连接</span>'
    : `<span class="connection-off">发布服务未连接</span>${button("启动服务", "pub-start-service", "", "small")}`;
  let body;
  if (tab === "materials")
    body = `<div class="section-heading"><h2>视频素材<span class="count-label">${data.materials.length} 个</span></h2><label class="button primary upload-trigger">上传视频<input type="file" accept=".mp4,.mov,.m4v,.webm,.mkv,.avi" data-pub-upload hidden></label></div><p class="section-description">本地上传的视频先保存到 JM，执行发布时才交给 SAU。单个最多150MB。</p><div class="panel"><div class="table-wrap"><table><thead><tr><th>视频</th><th>大小</th><th>来源</th><th>状态</th><th>操作</th></tr></thead><tbody>${data.materials.map((m) => `<tr><td><b>${e(m.name)}</b>${m.duration ? `<small>${e(m.duration)}秒 · ${e(m.width)} × ${e(m.height)}</small>` : ""}</td><td>${size(m.size)}</td><td>${m.source === "local" ? "JM 素材库" : "SAU 素材库"}</td><td>${m.available ? "可用" : "原文件缺失"}</td><td><div class="row-actions">${m.source === "local" ? button("预览", "pub-preview", m.id, "quiet") + button("删除", "pub-delete", m.id, "quiet") : ""}${m.available ? button("用于发布", "pub-use", m.id, "small") : ""}</div></td></tr>`).join("") || `<tr><td colspan="5">${empty("添加第一条视频", "上传本地视频，或连接 SAU 使用已有素材。")}</td></tr>`}</tbody></table></div></div>`;
  else {
    const batches = data.batches.filter(
      (b) => filter === "all" || b.state === filter,
    );
    body = `<div class="section-heading"><h2>发布任务<span class="count-label">${data.batches.length} 项</span></h2><select aria-label="发布状态筛选" data-pub-filter><option value="all">全部状态</option>${Object.entries(
      publishStates,
    )
      .map(
        ([s, l]) =>
          `<option value="${s}" ${filter === s ? "selected" : ""}>${l}</option>`,
      )
      .join(
        "",
      )}</select></div><div class="panel"><div class="table-wrap"><table class="publication-table"><thead><tr><th>内容</th><th>发布范围</th><th>执行时间</th><th>状态</th><th>操作</th></tr></thead><tbody>${batches.map((b) => `<tr><td><button class="task-name" data-action="pub-detail" data-id="${b.id}">${e(b.payload.title)}</button><small>${b.payload.material_ids.length} 个视频 · ${b.payload.tags.map((t) => "#" + e(t)).join(" ") || "未添加话题"}</small></td><td>${b.payload.account_ids.length} 个账号<small>${[...new Set(b.jobs.map((j) => names[j.platform]))].map(e).join(" / ") || "执行前检查账号与平台"}</small></td><td>${b.payload.mode === "scheduled" ? time(b.payload.schedule_at) : "立即执行"}<small>${time(b.created)}</small></td><td>${mark(b.state)}<small>${b.jobs.filter((j) => j.state === "submitted").length} / ${b.jobs.length} 个组合已提交</small></td><td><div class="row-actions">${b.state === "draft" ? button("执行", "pub-launch", b.id, "small") + button("编辑", "pub-edit", b.id, "quiet") : ["queued", "running"].includes(b.state) ? button("停止后续", "pub-pause", b.id, "small") : b.state === "paused" ? button("继续", "pub-resume", b.id, "small") : ""}${button("详情", "pub-detail", b.id, "quiet")}</div></td></tr>`).join("") || `<tr><td colspan="5">${empty(filter === "all" ? "开始你的第一次内容发布" : "没有这个状态的任务", filter === "all" ? "选好视频和账号，填好内容即可执行。" : "可以切换到全部状态查看。", filter === "all" ? button("新建发布", "pub-new", "", "primary") : "")}</td></tr>`}</tbody></table></div></div><p class="section-description">“已提交”表示 SAU 已返回处理结果，作品是否可见需以平台记录为准。异常不会自动重发。</p>`;
  }
  return (
    heading(
      "PUBLISH",
      "内容发布",
      "视频、账号、内容，一处完成。",
      button("＋ 新建发布", "pub-new", "", "primary"),
    ) +
    `<div class="publish-toolbar"><div class="subnav"><button type="button" class="${tab === "batches" ? "active" : ""}" data-action="pub-tab" data-id="batches">发布任务</button><button type="button" class="${tab === "materials" ? "active" : ""}" data-action="pub-tab" data-id="materials">素材库</button></div><div class="service-indicator">${connection}</div></div>` +
    (!data.connected
      ? `<div class="alert amber"><strong>连接内容发布服务</strong><span>${e(data.message || "账号和 SAU 素材暂不可读取；本地草稿仍保留。")}</span><a href="#settings">检查设置 →</a></div>`
      : "") +
    body
  );
}

export function publishingAccounts(data) {
  return `<section class="spaced"><div class="section-heading"><div><h2>内容发布账号</h2><p class="section-description">沿用 SAU 的登录资料，与上方评论 / 采集账号分别管理。</p></div><a class="button" href="${e(data.settings.sau_web_url)}/#/account-management" target="_blank" rel="noopener">登录 / 管理发布账号 ↗</a></div><div class="panel"><div class="table-wrap"><table><thead><tr><th>账号</th><th>平台</th><th>登录记录</th><th>能力</th></tr></thead><tbody>${data.accounts.map((a) => `<tr><td>${e(a.name)}</td><td>${e(names[a.platform])}</td><td>${a.status === "recorded" ? "已有登录记录" : "需要重新登录"}<small>发布前仍由平台验证</small></td><td>视频发布${a.platform === "tencent" ? " / 平台草稿" : ""}</td></tr>`).join("") || `<tr><td colspan="4">${empty("暂无可用发布账号", data.connected ? "到 SAU 登录账号后，刷新此页即可识别。" : "先连接发布服务，再读取已有账号。")}</td></tr>`}</tbody></table></div></div></section>`;
}

export function publishingSettings(data) {
  const s = data.settings;
  return `<section class="panel spaced form-panel"><div class="section-heading"><h2>内容发布</h2>${button("检查 / 启动服务", "pub-start-service", "", "small")}</div><p class="section-description">${data.connected ? "SAU 本地服务已连接" : "SAU 本地服务未连接"}。逐个视频、逐个账号提交，结果分别保留。</p><form id="pub-settings-form"><div class="form-grid">${field("同平台发布间隔（分钟）", "publish_gap_minutes", s.publish_gap_minutes, "number", 'required min="1" max="1440"')}${field("同平台24小时最多提交", "publish_daily_limit", s.publish_daily_limit, "number", 'required min="1" max="20"')}</div><details><summary>服务接入配置</summary>${field("SAU 安装目录", "sau_root", s.sau_root, "text", "required")}${field("SAU 后端地址", "sau_url", s.sau_url, "url", "required")}${field("SAU 账号管理页面地址", "sau_web_url", s.sau_web_url, "url", "required")}</details><div class="form-actions"><button class="button primary">保存发布设置</button></div></form></section>`;
}

export class PublishingUI {
  constructor({ request, token, toast, render, showForm, dialog }) {
    Object.assign(this, { request, token, toast, render, showForm, dialog });
    this.tab = "batches";
    this.filter = "all";
    this.data = null;
  }
  async load() {
    this.data = await this.request("/api/publishing/state");
    return this.data;
  }
  async fresh() {
    await this.load();
    await this.render();
  }
  newDraft(material) {
    return {
      request_id: crypto.randomUUID(),
      title: "",
      material_ids: material ? [material] : [],
      account_ids: [],
      tags: [],
      mode: "now",
      schedule_at: 0,
      platform_draft: false,
      product_link: "",
      product_title: "",
    };
  }
  compose(draft = this.newDraft(), id = "") {
    const d = this.data;
    this.editingId = id;
    this.showForm(
      `<form id="pub-form" data-id="${e(id)}"><input type="hidden" name="request_id" value="${e(draft.request_id)}"><div class="dialog-header"><div><h2 id="dialog-title">${id ? "编辑发布草稿" : "新建内容发布"}</h2><p>配置完成即可执行，也可以先保存到本地草稿。</p></div>${button("×", "close-dialog", "", "icon-button")}</div><section class="compose-section"><div class="section-heading"><h3><span class="step-label">1</span>选择视频</h3><label class="button small upload-trigger">上传视频<input type="file" accept=".mp4,.mov,.m4v,.webm,.mkv,.avi" data-pub-upload hidden></label></div><div class="selection-list">${
        d.materials
          .filter((m) => m.available)
          .map(
            (m) =>
              `<label class="selection-row"><input type="checkbox" name="material_ids" value="${e(m.id)}" ${draft.material_ids.includes(m.id) ? "checked" : ""}><span><b>${e(m.name)}</b><small>${size(m.size)} · ${m.source === "local" ? "JM 素材库" : "SAU 素材库"}</small></span></label>`,
          )
          .join("") ||
        '<p class="muted">还没有视频，点击上方上传。单个最多150MB。</p>'
      }</div></section><section class="compose-section"><h3><span class="step-label">2</span>选择发布账号</h3><div class="account-options">${d.accounts.map((a) => `<label class="account-option ${a.status !== "recorded" ? "unavailable" : ""}"><input type="checkbox" name="account_ids" value="${e(a.id)}" ${draft.account_ids.includes(a.id) ? "checked" : ""} ${a.status === "recorded" ? "" : "disabled"}><span><b>${e(a.name)}</b><small>${e(names[a.platform])} · ${a.status === "recorded" ? "已有登录记录" : "需要重新登录"}</small></span></label>`).join("") || '<p class="muted">暂无发布账号，请先到账号页登录。</p>'}</div></section><section class="compose-section"><h3><span class="step-label">3</span>内容与时间</h3>${field("标题", "title", draft.title, "text", 'required maxlength="80" placeholder="给这条视频写一个清楚的标题"')}${field("话题", "tags", draft.tags.join(" "), "text", 'placeholder="用空格分隔，例如：店铺日常 经营分享"')}<div class="form-grid">${select(
        "发布时间",
        "mode",
        [
          ["now", "立即执行"],
          ["scheduled", "定时执行"],
        ],
        draft.mode,
      )}<label class="field" data-pub-schedule ${draft.mode !== "scheduled" ? "hidden" : ""}><span>本机时间</span><input type="datetime-local" name="schedule" value="${localDate(draft.schedule_at)}" ${draft.mode !== "scheduled" ? "disabled" : ""} required></label></div><details class="advanced-publish"><summary>更多选项</summary><label class="check-line"><input type="checkbox" name="platform_draft" ${draft.platform_draft ? "checked" : ""}>存入平台草稿（仅视频号）</label>${field("商品链接（仅抖音）", "product_link", draft.product_link, "url", 'placeholder="https://"')}${field("商品名称（仅抖音）", "product_title", draft.product_title)}</details></section><div class="note">平台限制、账号变化或回执不明时停止后续执行；不会自动换号。</div><div class="dialog-footer"><button class="button" name="submit_mode" value="draft">保存草稿</button><button class="button primary" name="submit_mode" value="launch">${draft.mode === "scheduled" ? "保存并定时执行" : "保存并执行"}</button></div></form>`,
    );
  }
  rawDraft(form) {
    const f = new FormData(form);
    return {
      request_id: String(f.get("request_id")),
      title: String(f.get("title") || ""),
      material_ids: f.getAll("material_ids"),
      account_ids: f.getAll("account_ids"),
      tags: String(f.get("tags") || "")
        .split(/[\s,，]+/)
        .filter(Boolean),
      mode: f.get("mode") || "now",
      schedule_at: new Date(f.get("schedule")).getTime() / 1000 || 0,
      platform_draft: f.get("platform_draft") === "on",
      product_link: String(f.get("product_link") || ""),
      product_title: String(f.get("product_title") || ""),
    };
  }
  async upload(files) {
    if (!files?.length) return;
    const file = files[0];
    if (file.size > 150 * 1024 * 1024) throw Error("单个视频最多150MB");
    const form = document.querySelector("#pub-form"),
      draft = form ? this.rawDraft(form) : null,
      id = form?.dataset.id || "";
    this.toast("正在上传并检查视频，请稍候…");
    const response = await fetch(
      "/api/publishing/materials/upload?name=" + encodeURIComponent(file.name),
      {
        method: "POST",
        headers: {
          "X-JM-Token": this.token(),
          "Content-Type": "application/octet-stream",
        },
        body: file,
      },
    );
    const result = await response.json();
    if (!response.ok) throw Error(result.error || "视频上传未完成");
    await this.load();
    if (draft) {
      draft.material_ids.push(result.id);
      this.compose(draft, id);
    } else await this.render();
    this.toast(result.message);
  }
  async handle(action, id) {
    if (action === "pub-new") {
      await this.load();
      return this.compose();
    }
    if (action === "pub-use") {
      return this.compose(this.newDraft(id));
    }
    if (action === "pub-tab") {
      this.tab = id;
      return this.render();
    }
    if (action === "pub-refresh") return this.fresh();
    if (action === "pub-start-service") {
      const r = await this.request("/api/publishing/service/start", {});
      this.toast(r.message);
      return this.fresh();
    }
    if (action === "pub-edit") {
      const b = this.data.batches.find((b) => b.id === id);
      return this.compose(b.payload, b.id);
    }
    if (action === "pub-launch") {
      const r = await this.request(`/api/publishing/batches/${id}/launch`, {});
      this.toast(r.message);
      return this.fresh();
    }
    if (["pub-pause", "pub-resume", "pub-cancel"].includes(action)) {
      const r = await this.request(
        `/api/publishing/batches/${id}/${action.slice(4)}`,
        {},
      );
      this.toast(r.message);
      this.dialog.close();
      return this.fresh();
    }
    if (action === "pub-preview") {
      const m = this.data.materials.find((m) => m.id === id);
      return this.showForm(
        `<div class="dialog-header"><h2 id="dialog-title">${e(m.name)}</h2>${button("×", "close-dialog", "", "icon-button")}</div><video class="material-player" src="/api/publishing/materials/${encodeURIComponent(id)}/file" controls preload="metadata"></video>`,
      );
    }
    if (action === "pub-delete") {
      const m = this.data.materials.find((m) => m.id === id);
      return this.showForm(
        `<div class="dialog-header"><h2 id="dialog-title">删除本地素材</h2>${button("×", "close-dialog", "", "icon-button")}</div><p>将删除 JM 素材库中的「${e(m.name)}」。发布记录和 SAU 原有素材会保留。</p><div class="dialog-footer">${button("取消", "close-dialog")}${button("确认删除", "pub-confirm-delete", id, "danger")}</div>`,
      );
    }
    if (action === "pub-confirm-delete") {
      const r = await this.request(
        `/api/publishing/materials/${encodeURIComponent(id)}`,
        {},
        "DELETE",
      );
      this.toast(r.message);
      this.dialog.close();
      return this.fresh();
    }
    if (action === "pub-resolve") {
      return this.showForm(
        `<form id="pub-resolve-form" data-id="${e(id)}"><div class="dialog-header"><h2 id="dialog-title">记录平台核对结果</h2>${button("×", "close-dialog", "", "icon-button")}</div><p class="section-description">请先到平台作品管理核对。这里只记录结果，不会重新发布。</p>${select(
          "核对结果",
          "outcome",
          [
            ["submitted", "已在平台确认提交"],
            ["not_sent", "已确认没有提交"],
          ],
          "submitted",
        )}<label class="field"><span>核对说明</span><textarea name="note" minlength="12" maxlength="300" required></textarea></label><div class="dialog-footer"><button class="button primary">记录结果</button></div></form>`,
      );
    }
    if (action === "pub-detail") {
      const b = this.data.batches.find((b) => b.id === id);
      return this.showForm(
        `<div class="dialog-header"><div><h2 id="dialog-title">${e(b.payload.title)}</h2><p>${b.payload.material_ids.length} 个视频 · ${b.payload.account_ids.length} 个账号</p></div>${button("×", "close-dialog", "", "icon-button")}</div><div class="detail-meta">${mark(b.state)}<span>${b.payload.mode === "scheduled" ? time(b.payload.schedule_at) : "立即执行"}</span></div>${b.jobs.length ? `<div class="publish-job-list">${b.jobs.map((j) => `<article class="publish-job"><div><b>${e(j.account_name)}</b><span>${e(names[j.platform])}</span>${mark(j.state)}</div><p>${e(j.material_name)}</p><p>${e(j.message || "已排队，等待执行")}</p>${j.state === "queued" ? `<small>最早执行时间：${time(j.due)}</small>` : ""}${j.receipt.visibility ? `<small>作品可见性：${j.receipt.visibility === "user_confirmed" ? "用户已核对" : "未核验"}</small>` : ""}${j.state === "unknown" ? button("记录平台核对结果", "pub-resolve", j.id, "small") : ""}</article>`).join("")}</div>` : '<div class="note">这是本地草稿，尚未提交发布。</div>'}<div class="dialog-footer">${["draft", "queued", "paused"].includes(b.state) ? button(b.state === "draft" ? "取消草稿" : "取消后续任务", "pub-cancel", id, "quiet") : ""}${button("关闭", "close-dialog")}</div>`,
      );
    }
  }
  async submit(form, submitter) {
    if (form.id === "pub-resolve-form") {
      const result = await this.request(
        `/api/publishing/jobs/${form.dataset.id}/resolve`,
        Object.fromEntries(new FormData(form)),
      );
      this.toast(result.message);
      this.dialog.close();
      await this.fresh();
      return;
    }
    if (form.id === "pub-settings-form") {
      const data = Object.fromEntries(new FormData(form));
      data.publish_gap_minutes = Number(data.publish_gap_minutes);
      data.publish_daily_limit = Number(data.publish_daily_limit);
      const result = await this.request(
        "/api/publishing/settings",
        data,
        "PUT",
      );
      this.toast(result.message);
      await this.fresh();
      return;
    }
    const payload = publishPayload(new FormData(form)),
      id = form.dataset.id;
    const result = await this.request(
      "/api/publishing/batches" + (id ? "/" + id : ""),
      payload,
      id ? "PUT" : "POST",
    );
    form.dataset.id = result.id;
    if (submitter?.value === "launch") {
      // Preserve the saved draft ID if preflight fails, so the user can fix it.
      const launch = await this.request(
        `/api/publishing/batches/${result.id}/launch`,
        {},
      );
      this.toast(launch.message);
    } else this.toast(result.message);
    this.dialog.close();
    await this.fresh();
  }
  change(el) {
    if (el.matches("[data-pub-filter]")) {
      this.filter = el.value;
      return this.render();
    }
    if (el.form?.id === "pub-form" && el.name === "mode") {
      const box = el.form.querySelector("[data-pub-schedule]");
      box.hidden = el.value !== "scheduled";
      box.querySelector("input").disabled = box.hidden;
      el.form.querySelector('[value="launch"]').textContent =
        el.value === "scheduled" ? "保存并定时执行" : "保存并执行";
    }
  }
}
