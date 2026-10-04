import { escape as e, button as b, time, empty } from "./ui.js";
import { icon } from "./community-icons.js";
import {
  statusLabels,
  tones,
  getAccount,
  getPlatform,
  connectionStatus,
  planStatus,
  planProgress,
  postStatus,
  postAccounts,
  filterPlans,
  filterPosts,
  localDay,
  safeLink,
} from "./community-v2-model.js";

export const badge = (s) =>
  `<span class="badge ${e(s.tone || tones[s.key] || "")}">${e(s.label || statusLabels[s.key] || s.key)}</span>`;
export const platform = (data, id) =>
  `<span class="platform"><span class="platform-mark ${e(id)}">${e(getPlatform(data, id).name.slice(0, 1))}</span>${e(getPlatform(data, id).name)}</span>`;
const small = (label, action, id, cls = "") =>
  b(label, action, id, "small " + cls);
const go = (text, url) =>
  safeLink(url)
    ? `<a class="button small" href="${e(safeLink(url))}" target="_blank" rel="noopener noreferrer">${text}${icon("arrow-up-right")}</a>`
    : "";
const options = (rows, value) =>
  rows
    .map(
      ([id, label]) =>
        `<option value="${e(id)}" ${id === value ? "selected" : ""}>${e(label)}</option>`,
    )
    .join("");
export const currentDay = (data) => data.summary?.day || localDay();
function toolbar(data, u, kind) {
  return `<div class="toolbar"><label class="search">${icon("search")}<input id="community-search" type="search" data-com-filter="q" value="${e(u.q)}" placeholder="${kind === "plans" ? "搜索计划或目标社区" : kind === "accounts" ? "搜索账号或平台" : "搜索标题、正文或原帖"}" aria-label="搜索社区内容"><kbd>/</kbd></label><select class="select" aria-label="筛选平台" data-com-filter="platform">${options([["", "全部平台"], ...data.platforms.map((p) => [p.id, p.name])], u.platform)}</select>${kind !== "accounts" ? `<select class="select" aria-label="筛选状态" data-com-filter="status">${options([["", "全部状态"], ...(kind === "plans" ? ["enabled", "paused", "login", "blocked", "disabled"] : ["draft", "queued", "running", "paused", "submitted", "recorded", "manual", "unknown", "failed", "cancelled"]).map((k) => [k, statusLabels[k]]), ...(kind === "plans" ? [["attention", "需要处理"]] : [])], u.status)}</select>` : ""}${u.plan ? `<span class="filter-context">${e(data.plans.find((p) => p.id === u.plan)?.payload.name || "关联计划")}</span>` : ""}${u.day ? `<span class="filter-context">${e(u.day)} 已提交</span>` : ""}<span class="toolbar-spacer"></span>${small(icon("rotate-ccw") + "清除筛选", "com-v2-clear", "", "quiet")}</div>`;
}
function progress(p, data) {
  const c = planProgress(p, currentDay(data));
  return `<div class="progress-line"><span>帖子 <b>${c.thread.submitted}/1</b></span><span>评论 <b>${c.reply.submitted}/5</b></span></div><progress class="progress-track" max="6" value="${Math.min(6, c.thread.submitted + c.reply.submitted)}" aria-label="今日提交进度"></progress>`;
}
export function plansView(data, u) {
  const all = data.plans || [],
    shown = filterPlans(data, u),
    attention = all.filter((p) =>
      ["blocked", "login", "disabled"].includes(planStatus(p, data).key),
    );
  const summary = data.summary || {};
  return `<div class="summary">${[
    [
      "已启用的计划",
      all.filter((p) => p.state === "enabled").length,
      "个",
      "enabled",
      "calendar-check-2",
    ],
    [
      "今日已提交帖子",
      summary.thread_submitted || 0,
      "篇",
      "thread",
      "file-text",
    ],
    [
      "今日已提交评论",
      summary.reply_submitted || 0,
      "条",
      "reply",
      "message-square",
    ],
    ["需要你处理", attention.length, "项", "attention", "circle-alert"],
  ]
    .map(
      ([label, n, unit, id, i]) =>
        `<button class="stat ${id === "attention" ? "warning" : ""}" data-action="com-v2-stat" data-id="${id}"><span class="stat-label">${label}</span><span class="stat-icon">${icon(i)}</span><span class="stat-value">${n}<small>${unit}</small></span>${id === "thread" || id === "reply" ? '<span class="stat-note">回执与可见性分开</span>' : ""}</button>`,
    )
    .join(
      "",
    )}</div>${attention.length || data.risk.length ? `<div class="attention-strip">${icon("circle-alert")}<span><strong>${attention.length ? attention.length + " 个计划需要处理" : "存在平台暂停记录"}</strong><span class="attention-detail">，查看原因后再继续。</span></span>${b("去处理 " + icon("arrow-right"), "com-v2-stat", "attention")}</div>` : ""}<div class="section-heading"><h2>我的发布计划 <small>${all.length}</small></h2><span class="hint">每天 1 篇帖子 · 5 个不同原帖各评论 1 次</span></div><section class="panel">${toolbar(data, u, "plans")}${
    shown.length
      ? `<div class="table-wrap"><table class="plan-table"><thead><tr><th>计划名称</th><th>平台 / 目标</th><th>今日进度</th><th>当前状态</th><th class="col-next">下一步</th><th>操作</th></tr></thead><tbody>${shown
          .map((p) => {
            const s = planStatus(p, data);
            return `<tr data-plan-row="${e(p.id)}"><td><div class="plan-title"><span class="plan-glyph ${s.key === "blocked" ? "amber" : ""}">${icon("calendar-check-2")}</span><div><button class="text-button" data-action="com-v2-plan" data-id="${e(p.id)}">${e(p.payload.name)}</button><span class="subtext">每天 ${String(p.payload.hour).padStart(2, "0")}:${String(p.payload.minute).padStart(2, "0")} · 帖子与评论</span></div></div></td><td class="col-platform">${platform(data, p.platform)}<span class="subtext">${e(p.payload.board)}</span></td><td class="col-progress">${progress(p, data)}</td><td class="col-status">${badge(s)}<span class="subtext">${s.key === "enabled" ? "按设置自动安排" : s.key === "blocked" ? "不会自动重试" : "配置与记录保留"}</span></td><td class="col-next"><span>${e(s.key === "enabled" ? planProgress(p, currentDay(data)).message : s.reason || "检查设置后启用")}</span></td><td class="col-action">${small(s.key === "blocked" ? "查看原因" : s.key === "login" ? "去连接" : "查看进度", s.key === "login" ? "com-v2-account" : "com-v2-plan", s.key === "login" ? p.payload.account_id : p.id)}</td></tr>`;
          })
          .join(
            "",
          )}</tbody></table></div><div class="table-bottom"><span>共 ${shown.length} 个计划 · 北京时间</span><span>已提交不等于公开可见</span></div>`
      : empty(
          all.length ? "没有匹配的计划" : "创建你的第一个每日计划",
          all.length
            ? "清除筛选，或尝试其他关键词。"
            : "先选择平台账号，再设置目标和执行时间。",
          b(
            all.length ? "清除筛选" : "新建计划",
            all.length ? "com-v2-clear" : "com-plan-new",
            "",
            "primary",
          ),
        )
  }</section><div class="below-grid"><section class="below-panel"><div class="panel-label"><h3>最近结果</h3>${small("查看全部 " + icon("arrow-up-right"), "com-tab", "content", "quiet")}</div>${
    data.posts
      .filter((p) => p.jobs?.length)
      .slice(0, 2)
      .map(
        (p) =>
          `<div class="activity-row"><span class="activity-dot"></span><div><button class="text-button" data-action="com-view" data-id="${e(p.id)}">${e(p.payload.title)}</button><span class="subtext">${postStatus(p).label} · ${e(
            p.jobs
              .map((j) => j.message)
              .filter(Boolean)
              .join("；"),
          )}</span></div></div>`,
      )
      .join("") || '<p class="form-note">发布后，这里显示最新结果。</p>'
  }</section><section class="below-panel"><div class="panel-label"><h3>内容准备情况</h3>${small("查看计划素材", "com-v2-material-help", "", "quiet")}</div><div class="capacity-row"><span>未用帖子素材</span><b>${all.reduce((n, p) => n + p.remaining_topics, 0)} 篇</b></div><div class="capacity-row"><span>未用评论素材 / 规则</span><b>${all.reduce((n, p) => n + p.remaining_replies, 0)} 条</b></div><p class="capacity-note">素材不足时显示缺口，不重复发送。</p></section></div>`;
}
export function contentView(data, u) {
  const rows = filterPosts(data, u),
    size = 8,
    pages = Math.max(1, Math.ceil(rows.length / size));
  u.page = Math.max(1, Math.min(u.page, pages));
  const shown = rows.slice((u.page - 1) * size, u.page * size),
    selected = data.posts.filter((p) => u.selected.has(p.id)),
    eligible = selected.filter((p) =>
      p.jobs?.some((j) => j.state === "queued"),
    ).length;
  return `<div class="section-heading"><div><h2>帖子与评论</h2><p>正文、原帖、账号与每个目标的结果，点开即可查看。</p></div></div><div class="content-top"><div class="filter-chips">${[
    ["", "全部"],
    ["thread", "帖子"],
    ["reply", "评论"],
  ]
    .map(([id, label]) =>
      b(
        `${label}<span>${data.posts.filter((p) => !id || (p.payload.kind || "thread") === id).length}</span>`,
        "com-v2-kind",
        id,
        id === u.kind ? "active" : "",
      ),
    )
    .join(
      "",
    )}</div>${small(icon("download") + "导出记录", "com-v2-export")}</div>${selected.length ? `<div class="bulk-bar"><b>已选 ${selected.length} 条</b>${eligible ? small("暂停等待中的 " + eligible + " 条", "com-v2-bulk-pause") : ""}${small("导出选中", "com-v2-export-selected")}${small("取消选择", "com-v2-unselect")}</div>` : ""}<section class="panel">${toolbar(data, u, "content")}${
    shown.length
      ? `<div class="table-wrap"><table class="content-table"><thead><tr><th class="check-cell"><input type="checkbox" aria-label="选择当前页全部内容" data-com-select="all" ${shown.every((p) => u.selected.has(p.id)) ? "checked" : ""}></th><th>内容 / 原帖</th><th>平台 / 账号</th><th>发送状态</th><th class="col-time">时间</th><th>操作</th></tr></thead><tbody>${shown
          .map((p) => {
            const a = postAccounts(p, data),
              s = postStatus(p);
            return `<tr data-post-row="${e(p.id)}"><td class="check-cell"><input type="checkbox" aria-label="选择${e(p.payload.title)}" data-com-select="${e(p.id)}" ${u.selected.has(p.id) ? "checked" : ""}></td><td class="content-title"><div class="content-name"><span class="kind-icon">${icon(p.payload.kind === "reply" ? "message-square" : "file-text")}</span><div><button class="text-button" data-action="com-view" data-id="${e(p.id)}">${e(p.payload.source_title || p.payload.title)}</button><span class="content-excerpt">${p.payload.kind === "reply" ? "评论：" : ""}${e(p.payload.body)}</span></div></div></td><td class="col-platform">${a[0] ? platform(data, a[0].platform) : "未选择账号"}<span class="subtext">${e(a[0]?.name || "")}${a.length > 1 ? " 等 " + a.length + " 个目标" : ""}</span></td><td class="col-state">${badge(s)}${p.jobs?.length > 1 ? '<span class="subtext">点开查看各目标结果</span>' : ""}</td><td class="col-time">${e(time(p.created).split(" ")[1] || "")}</td><td class="col-action">${small("查看", "com-view", p.id, "quiet")}</td></tr>`;
          })
          .join(
            "",
          )}</tbody></table></div><div class="table-bottom"><span>${data.post_total > data.posts.length ? "最近 " + data.posts.length + " / " + data.post_total + " 条 · " : ""}筛选结果 ${rows.length} 条</span><div class="pager">${b(icon("chevron-left"), "com-v2-page", String(Math.max(1, u.page - 1)), "icon-button")}<span>${u.page} / ${pages}</span>${b(icon("chevron-right"), "com-v2-page", String(Math.min(pages, u.page + 1)), "icon-button")}</div></div>`
      : empty(
          "没有符合条件的内容",
          "调整筛选条件，或保存一份新的草稿。",
          small("清除筛选", "com-v2-clear"),
        )
  }</section>`;
}
export function accountsView(data, u) {
  const list = data.accounts.filter(
    (a) =>
      (!u.platform || a.platform === u.platform) &&
      (!u.q ||
        [a.name, a.identity_hint, getPlatform(data, a.platform).name]
          .join(" ")
          .toLowerCase()
          .includes(u.q.toLowerCase())),
  );
  const platforms = data.platforms.filter(
    (p) =>
      (!u.platform || p.id === u.platform) &&
      (!u.q ||
        [p.name, p.categories, p.region]
          .join(" ")
          .toLowerCase()
          .includes(u.q.toLowerCase())),
  );
  return `<div class="section-heading"><div><h2>平台账号</h2><p>连接与发布权限分别显示，遇到问题知道从哪里处理。</p></div></div><div class="content-top"><div class="segmented">${b("账号列表", "com-v2-account-mode", "list", u.accountMode === "list" ? "active" : "")}${b("平台能力矩阵 · " + data.platforms.length, "com-v2-account-mode", "matrix", u.accountMode === "matrix" ? "active" : "")}</div><span class="hint">${data.accounts.filter((a) => connectionStatus(a).key === "connected").length} / ${data.accounts.length} 个账号已核验</span></div><section class="panel">${toolbar(data, u, "accounts")}${
    u.accountMode === "matrix"
      ? `<div class="table-wrap"><table class="matrix"><thead><tr><th>平台</th><th>帖子</th><th>评论 / 每日计划</th><th>内容方向</th><th>操作</th></tr></thead><tbody>${platforms.map((p) => `<tr><td>${platform(data, p.id)}<span class="subtext">${e(p.region)}</span></td><td>${e(p.mode_label)}</td><td>${["tieba", "juejin", "csdn"].includes(p.id) ? "已接入，需账号权限" : "尚未接入"}</td><td>${e(p.categories)}</td><td>${small("添加账号", "com-add-platform", p.id)}</td></tr>`).join("")}</tbody></table></div><div class="matrix-note">接入能力不等于账号具备发布权限。网页登录、API授权、平台限制分别检查；网页发布平台需在网站完成提交。</div>`
      : list.length
        ? `<div class="table-wrap"><table class="account-table"><thead><tr><th>账号</th><th>平台</th><th>连接状态</th><th>发布方式</th><th class="col-last">最近核验</th><th>操作</th></tr></thead><tbody>${list
            .map((a) => {
              const p = getPlatform(data, a.platform),
                risk = data.risk.find((r) => r.platform === a.platform);
              return `<tr data-account-row="${e(a.id)}"><td><span class="account-name">${e(a.name)}</span><span class="subtext">${e(a.identity_hint || "无备注")}</span></td><td class="col-platform">${platform(data, a.platform)}</td><td class="col-connection">${badge(connectionStatus(a))}</td><td class="col-capabilities"><span class="subtext">${risk ? "平台已暂停" : e(p.mode_label)}</span></td><td class="col-last"><span class="subtext">${e(time(a.checked))}</span></td><td class="col-action">${small("管理", "com-v2-account", a.id)}</td></tr>`;
            })
            .join("")}</tbody></table></div>`
        : empty(
            "尚未找到账号",
            "可以添加账号，或清除当前筛选。",
            small("添加账号", "com-new-account"),
          )
  }</section>${data.risk.length ? `<section class="below-panel risk-records"><h3>平台暂停记录</h3>${data.risk.map((r) => `<div class="mini-item"><div><strong>${e(getPlatform(data, r.platform).name)}</strong><p>${e(r.reason)}</p></div>${small("处理记录", "com-risk", r.platform)}</div>`).join("")}</section>` : ""}`;
}
export function workspace(data, u) {
  const primary =
    u.tab === "plans"
      ? b(icon("plus") + "新建计划", "com-plan-new", "", "primary")
      : u.tab === "accounts"
        ? b(icon("plus") + "添加账号", "com-new-account", "", "primary")
        : b(icon("plus") + "写内容", "com-v2-compose", "", "primary");
  return `<section id="community-v2"><div class="page-heading"><div><div class="eyebrow">COMMUNITY</div><h1>社区发布</h1><p>安排要做的事，随时看清每一条结果。</p></div>${primary}</div><nav class="view-tabs" aria-label="社区发布视图">${[
    ["plans", "发布计划", "calendar-check-2", data.plans?.length || 0],
    ["content", "内容记录", "file-text", data.post_total ?? data.posts.length],
    ["accounts", "平台账号", "users-round", data.accounts.length],
  ]
    .map(
      ([id, name, i, count]) =>
        `<button data-action="com-tab" data-id="${id}" aria-current="${id === u.tab ? "page" : "false"}">${icon(i)}${name}<span>${count}</span></button>`,
    )
    .join(
      "",
    )}<div class="view-date">${icon("calendar-days")}${e(currentDay(data))} · 北京时间</div></nav><div id="community-view">${u.tab === "plans" ? plansView(data, u) : u.tab === "content" ? contentView(data, u) : accountsView(data, u)}</div></section>`;
}
function drawerHead(kicker, title, sub) {
  return `<div class="drawer-header"><div class="drawer-title-row"><div><div class="eyebrow">${kicker}</div><h2 id="community-drawer-title">${e(title)}</h2></div>${b(icon("x"), "com-v2-close", "", "icon-button")}</div><p>${e(sub)}</p></div>`;
}
const section = (title, html) =>
  `<section class="detail-section"><h3>${title}</h3>${html}</section>`;
function resultJobs(post, data) {
  return post.jobs?.length
    ? post.jobs
        .map(
          (j) =>
            `<div class="job-result"><div class="detail-status-row">${platform(data, j.platform)}${badge({ key: j.state })}</div><p><b>${e(j.account_name)}</b> · ${e(j.destination)}</p><p class="result-message">${e(j.message || "尚无补充说明")}</p><p class="form-note">公开可见性：${j.receipt?.visibility === "verified" ? "已核验" : j.receipt?.visibility === "user_reported" ? "用户登记，尚未独立核验" : "未核验"}</p>${j.receipt?.url ? `<p class="source-link">${e(j.receipt.url)}</p>` : ""}<div class="actions">${small(j.receipt?.url ? "打开结果" : "打开平台", "com-open-job", j.id)}${j.state === "manual" ? small("登记链接", "com-record", j.id) : ""}${j.state === "unknown" ? small("核实结果", "com-resolve", j.id) : ""}${j.state === "failed" && j.receipt?.phase === "preflight" ? small("重新检查并继续", "com-retry-preflight", j.id) : ""}</div></div>`,
        )
        .join("")
    : '<p class="form-note">尚未提交，保存草稿不会发布。</p>';
}
export function drawer(data, u) {
  const { type, id } = u.drawer || {};
  if (type === "content") {
    const p = data.posts.find((p) => p.id === id);
    if (!p) return null;
    const a = postAccounts(p, data),
      v = p.payload,
      jobs = p.jobs || [],
      reply = v.kind === "reply";
    return (
      drawerHead(
        reply ? "COMMENT DETAIL" : "POST DETAIL",
        reply ? "评论内容" : "帖子内容",
        a.map((a) => a.name).join(" · "),
      ) +
      `<div class="drawer-body"><div class="detail-status-row">${badge(postStatus(p))}<span>${time(p.created)}</span></div>${section(reply ? "对应原帖" : "标题", `<p class="detail-title">${e(v.source_title || v.title)}</p>${reply ? `<div class="quote-preview">${e(v.source_excerpt || "该记录未保存原帖摘录")}</div>${(v.targets || []).map((t) => `<p class="source-link">${e(t.destination)}</p>${go("打开原帖", t.destination)}`).join("")}` : ""}`)}<section class="detail-section"><div class="panel-label"><h3>${reply ? "评论全文" : "帖子正文"}</h3>${small(icon("copy") + "复制正文", "com-v2-copy", id, "quiet")}</div><div class="article-preview">${e(v.body)}</div>${v.platform_tags?.length ? `<div class="meta-chips">${v.platform_tags.map((t) => `<span>${e(t)}</span>`).join("")}</div>` : ""}</section>${section("发送信息", resultJobs(p, data))}${p.plan_id ? section("关联计划", small(data.plans.find((x) => x.id === p.plan_id)?.payload.name || "查看计划", "com-v2-plan", p.plan_id)) : ""}</div><div class="drawer-footer"><p>每个目标单独保留回执</p><div>${p.state === "draft" ? small("编辑草稿", "com-edit", id) + small("开始发布", "com-launch", id, "primary") : ""}${jobs.some((j) => ["queued", "running"].includes(j.state)) ? small("暂停", "com-pause", id) : ""}${jobs.some((j) => j.state === "paused") ? small("继续", "com-resume", id, "primary") : ""}${p.state === "draft" || jobs.some((j) => ["queued", "paused", "manual"].includes(j.state)) ? small("取消内容", "com-v2-cancel", id, "quiet") : ""}</div></div>`
    );
  }
  if (type === "plan") {
    const p = data.plans.find((p) => p.id === id);
    if (!p) return null;
    const s = planStatus(p, data),
      a = getAccount(data, p.payload.account_id),
      c = planProgress(p, currentDay(data)),
      posts = data.posts.filter((x) => x.plan_id === id);
    let body = "";
    if (u.drawerTab === "summary")
      body = `${["blocked", "login", "disabled"].includes(s.key) ? `<div class="detail-alert ${s.key === "blocked" ? "red" : ""}"><strong>${e(s.label)}</strong>${e(s.reason)}<div>${s.key === "blocked" ? small("处理平台记录", "com-risk", p.platform) : small("查看账号", "com-v2-account", p.payload.account_id)}</div></div>` : ""}<div class="detail-stats"><div class="detail-stat"><span>今日帖子</span><strong>${c.thread.submitted}<small>/ 1</small></strong><em>等待 ${c.thread.waiting} · 异常 ${c.thread.failed}</em></div><div class="detail-stat"><span>今日评论</span><strong>${c.reply.submitted}<small>/ 5</small></strong><em>等待 ${c.reply.waiting} · 异常 ${c.reply.failed}</em></div></div>${section("当前安排", `<dl class="details-grid"><dt>状态</dt><dd>${badge(s)}</dd><dt>账号</dt><dd>${e(a?.name || "未知")}</dd><dt>目标</dt><dd>${e(p.payload.board)}</dd><dt>执行时间</dt><dd>每天 ${String(p.payload.hour).padStart(2, "0")}:${String(p.payload.minute).padStart(2, "0")}，北京时间</dd><dt>当前说明</dt><dd>${e(p.message)}</dd></dl>`)}${section("最近执行记录", p.days?.length ? p.days.map((d) => `<div class="mini-item"><div><b>${e(d.day)}</b><p>${e(d.message)}</p><small>帖子 ${d.counts.thread.submitted}/1 · 评论 ${d.counts.reply.submitted}/5</small></div></div>`).join("") : '<p class="form-note">还没有安排过任务。</p>')}`;
    else if (u.drawerTab === "content")
      body = `<div class="section-heading"><h3>关联内容 · ${posts.length} 条</h3>${small("筛选到列表", "com-v2-plan-posts", id)}</div>${posts.map((x) => `<div class="mini-item"><div><button class="text-button" data-action="com-view" data-id="${e(x.id)}">${e(x.payload.source_title || x.payload.title)}</button><small>${x.payload.kind === "reply" ? "评论" : "帖子"} · ${e(x.plan_day || "")}</small></div>${badge(postStatus(x))}</div>`).join("") || empty("还没有关联内容", "安排任务后可在此查看。")}`;
    else
      body = `${section("执行规则", `<dl class="details-grid"><dt>每日目标</dt><dd>帖子 1 篇 · 评论 5 个不同帖子</dd><dt>每个原帖</dt><dd>只评论 1 次，内容与目标去重</dd><dt>发送间隔</dt><dd>至少 30 分钟，所有同平台账号共享预算</dd><dt>评论来源</dt><dd>${e(p.payload.source_boards.join("、") || "使用指定帖素材")}</dd><dt>内容规则</dt><dd>${e(p.payload.rules_note)}</dd></dl>`)}<div class="source-summary"><strong>未用素材</strong>帖子 ${p.remaining_topics} 篇 · 评论素材 / 规则 ${p.remaining_replies} 条<br>修改设置或补充素材前，先暂停计划。</div><div class="actions">${small("修改设置", "com-plan-edit", id)}${small("帖子素材", "com-plan-topic", id)}${small("指定帖评论", "com-plan-reply", id)}${p.platform !== "csdn" ? small("匹配规则", "com-plan-rule", id) : ""}</div>${section("全部素材", `<details class="material-list"><summary>展开正文与匹配规则</summary>${(p.payload.topics || []).map((t) => `<h4>${e(t.title)}</h4><p class="article-preview">${e(t.body)}</p>`).join("")}${(p.payload.replies || []).map((r) => `<h4>评论：${e(r.title)}</h4>${go("原帖", r.url)}<p class="article-preview">${e(r.body)}</p>`).join("")}${(p.payload.reply_rules || []).map((r) => `<h4>${e(r.name)}</h4><p>${e(r.terms.join("、"))}</p><p class="article-preview">${e(r.body)}</p>`).join("")}</details>`)}`;
    return (
      drawerHead(
        "PUBLISHING PLAN",
        p.payload.name,
        getPlatform(data, p.platform).name + " · " + p.payload.board,
      ) +
      `<div class="drawer-tabs">${[
        ["summary", "运行情况"],
        ["content", "发布内容"],
        ["rules", "规则与素材"],
      ]
        .map(([id, label]) =>
          b(label, "com-v2-drawer-tab", id, id === u.drawerTab ? "active" : ""),
        )
        .join(
          "",
        )}</div><div class="drawer-body">${body}</div><div class="drawer-footer"><p>启用计划不会重发已有内容</p><div>${p.state === "enabled" ? small("安排今天", "com-plan-today", p.id) + small("暂停计划", "com-plan-pause", p.id, "primary") : s.key === "blocked" ? small("查看暂停记录", "com-risk", p.platform) : s.key === "login" || s.key === "disabled" ? small("处理账号", "com-v2-account", p.payload.account_id, "primary") : small("启用计划", "com-plan-enable", p.id, "primary")}</div></div>`
    );
  }
  if (type === "account") {
    const a = getAccount(data, id);
    if (!a) return null;
    const p = getPlatform(data, a.platform),
      risk = data.risk.find((r) => r.platform === a.platform);
    return (
      drawerHead("PLATFORM ACCOUNT", a.name, p.name) +
      `<div class="drawer-body"><div class="detail-status-row">${badge(connectionStatus(a))}</div>${a.sync_message ? `<p class="form-note">${e(a.sync_message)}</p>` : ""}${risk ? `<div class="detail-alert red"><strong>平台已暂停</strong>${e(risk.reason)}<p>重新登录或检查连接不会解除发布限制。</p>${small("处理记录", "com-risk", a.platform)}</div>` : ""}${section("账号信息", `<dl class="details-grid"><dt>备注</dt><dd>${e(a.identity_hint || "—")}</dd><dt>登录身份</dt><dd>${e(a.identity || "尚未核验")}</dd><dt>最近核验</dt><dd>${e(time(a.checked))}</dd><dt>发布方式</dt><dd>${e(p.mode_label)}</dd><dt>能力说明</dt><dd>${e(p.note)}</dd></dl>`)}${section(
        "关联计划",
        data.plans
          .filter((p) => p.payload.account_id === id)
          .map(
            (p) =>
              `<div class="mini-item">${small(p.payload.name, "com-v2-plan", p.id)}${badge(planStatus(p, data))}</div>`,
          )
          .join("") || '<p class="form-note">还没有关联计划。</p>',
      )}<div class="login-steps"><div class="login-step"><div>打开账号专属 Chrome<small>在平台完成登录。</small></div></div><div class="login-step"><div>返回工作台检查连接<small>核验登录身份与适配器权限。</small></div></div><div class="login-step"><div>回到计划启用<small>平台暂停和未知结果需单独处理。</small></div></div></div></div><div class="drawer-footer"><p>账号与历史结果独立保存</p><div>${small("删除", "com-delete-account", id, "quiet")}${small("编辑", "com-edit-account", id)}${p.automatic ? small("检查连接", "com-check", id) : ""}${small("登录 / 打开", "com-open-account", id, "primary")}</div></div>`
    );
  }
  return null;
}
