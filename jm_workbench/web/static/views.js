import {
  escape as e,
  time,
  badge,
  field,
  area,
  select,
  empty,
  heading,
  button,
  names,
} from "./ui.js";
import { dataPage } from "./data-page.js";

export const pages = [
  ["overview", "◫", "工作概览"],
  ["matrix", "▦", "任务矩阵"],
  ["tasks", "☷", "任务配置"],
  ["accounts", "◎", "账号管理"],
  ["platforms", "⊞", "平台接入"],
  ["data", "▤", "数据中心"],
  ["runs", "◷", "运行记录"],
  ["settings", "⚙", "工作台设置"],
];
const active = (r) => ["running", "queued", "waiting"].includes(r.state);
const platformName = (s, id) =>
  s.platforms.find((p) => p.id === id)?.name || id;
const taskActions = (t) =>
  button("编辑", "edit-task", t.id) + button("执行", "launch", t.id);
function taskCards(s, limited = false) {
  const tasks = limited ? s.tasks.slice(0, 4) : s.tasks;
  return tasks.length
    ? `<div class="task-grid">${tasks
        .map((t) => {
          const run = s.runs.find((r) => r.task_id === t.id),
            bindings = s.bindings.filter(
              (b) => b.task_id === t.id && b.enabled,
            );
          return `<article class="task-card"><div class="card-top"><span class="task-icon ${t.kind === "adult_comments" ? "peach" : t.kind === "peiwang_comments" ? "purple" : "blue"}">${t.kind === "adult_comments" ? "货" : t.kind === "peiwang_comments" ? "伴" : "采"}</span>${badge(!t.enabled ? "已停用" : run?.state || "尚未执行")}</div><h3>${e(t.name)}</h3><p>${e(names[t.kind])} · ${e(platformName(s, t.platform))}</p><div class="keywords">${t.keywords
            .slice(0, 3)
            .map((k) => `<span>${e(k)}</span>`)
            .join(
              "",
            )}</div><div class="card-meta"><span>${bindings.length} 个账号已绑定</span><span>${t.kind === "crawler" ? `每词最多${t.max_items}条` : `${t.start_hour}:00–${t.end_hour}:00`}</span></div><div class="card-footer">${taskActions(t)}</div></article>`;
        })
        .join("")}</div>`
    : empty(
        "创建你的第一项任务",
        "先选择业务和平台，填好关键词，再绑定账号。",
        button("+ 新建任务", "new-task", "", "primary"),
      );
}

export function overview(s) {
  const running = s.runs.filter(active).length,
    total = Object.values(s.counts).reduce((a, b) => a + b, 0),
    verified = s.accounts.filter((a) =>
      ["verified", "connected"].includes(a.connection),
    ).length;
  const risks = s.risk.length
    ? `<div class="alert red"><strong>有 ${s.risk.length} 个平台已暂停</strong><span>${e(s.risk.map((r) => r.reason).join("；"))}</span><a href="#runs">查看运行记录 →</a></div>`
    : "";
  const steps = [
    [s.tasks.length > 0, "01", "配置任务", "业务、关键词与执行范围", "tasks"],
    [verified > 0, "02", "连接账号", "独立浏览器，保留登录状态", "accounts"],
    [
      s.bindings.some((b) => b.enabled),
      "03",
      "建立矩阵",
      "指定哪个账号执行哪项任务",
      "matrix",
    ],
  ];
  return (
    heading(
      "WORKSPACE / JM",
      "工作概览",
      "先看任务进展，再跟进有价值的结果。",
    ) +
    risks +
    `<section class="welcome"><div><span class="pill">统一管理 · 按配置执行</span><h2>把找货、招募和采集，<br>放进同一个工作流程。</h2><p>任务与账号一一绑定。系统自动筛选，执行过程随时可见。</p><a class="text-link" href="#matrix">查看我的任务矩阵 <span>↗</span></a></div><div class="workflow-visual"><div class="flow-node"><b>任务</b><small>成人尾货 / 陪玩 / 采集</small></div><span class="flow-line">↓</span><div class="flow-node accent"><b>JM 工作台</b><small>账号矩阵 · 统一执行</small></div><span class="flow-line">↓</span><div class="flow-node"><b>结果</b><small>线索 / 发布记录 / 数据</small></div></div></section><div class="stats"><article><span>执行中的任务</span><strong>${running}<small>项</small></strong><a href="#runs">查看队列 ↗</a></article><article><span>已连接账号</span><strong>${verified}<small>/ ${s.accounts.length}</small></strong><a href="#accounts">管理账号 ↗</a></article><article><span>累计数据记录</span><strong>${total}<small>条</small></strong><a href="#data">筛选数据 ↗</a></article><article><span>评论已接收</span><strong>${s.attempt_counts.sent || 0}<small>条</small></strong><a href="#runs">查看平台回执 ↗</a></article></div><div class="section-heading"><h2>开始前的三步</h2><span>配置一次，按需执行</span></div><div class="setup-steps">${steps.map(([ok, n, t, d, to]) => `<a href="#${to}"><span class="step-number ${ok ? "done" : ""}">${ok ? "✓" : n}</span><div><b>${t}</b><small>${d}</small></div><span>→</span></a>`).join("")}</div><div class="section-heading"><h2>我的任务</h2><a href="#tasks">全部任务 →</a></div>${taskCards(s, true)}`
  );
}
export function tasks(s) {
  return (
    heading(
      "TASKS",
      "任务配置",
      "成人尾货、陪玩招募和爬虫各自配置，运行时不会串用关键词或模板。",
      button("+ 新建任务", "new-task", "", "primary"),
    ) + taskCards(s)
  );
}
export function accounts(s) {
  return (
    heading(
      "ACCOUNTS",
      "账号管理",
      "每个账号使用独立的浏览器资料目录。先打开浏览器登录，再检查连接。",
      button("+ 添加账号", "new-account", "", "primary"),
    ) +
    (s.accounts.length
      ? `<div class="account-grid">${s.accounts.map((a) => `<article class="panel account-card"><div class="card-top"><span class="avatar">${e(a.name.slice(0, 1))}</span>${badge(a.connection)}</div><h3>${e(a.name)}</h3><p>${e(platformName(s, a.platform))}${a.enabled ? "" : " · 已停用"}</p><dl><dt>身份核验</dt><dd>${a.identity ? "已绑定固定身份" : "运行时检查平台登录"}</dd><dt>上次检查</dt><dd>${time(a.checked_at)}</dd></dl><details><summary>浏览器资料目录</summary><code>${e(a.profile_dir)}</code></details><div class="card-footer">${button("打开浏览器", "open-account", a.id)}${button("检查连接", "check-account", a.id, "primary")}${button("编辑", "edit-account", a.id, "quiet")}</div></article>`).join("")}</div>`
      : empty(
          "先连接一个账号",
          "登录资料只保存在本机，不上传到GitHub。",
          button("+ 添加账号", "new-account", "", "primary"),
        ))
  );
}
export function matrix(s) {
  let body;
  if (!s.tasks.length || !s.accounts.length)
    body = empty(
      "任务矩阵还差一步",
      "需要至少一项任务和一个账号，然后在表格中勾选绑定。",
      `<a class="button" href="#tasks">配置任务</a> <a class="button" href="#accounts">配置账号</a>`,
    );
  else
    body = `<div class="panel"><div class="table-wrap"><table class="matrix-table"><thead><tr><th>平台 / 账号</th>${s.tasks.map((t) => `<th>${e(t.name)}<small>${platformName(s, t.platform)} · ${e(names[t.kind])}</small></th>`).join("")}</tr></thead><tbody>${s.accounts
      .map(
        (a) =>
          `<tr><th>${e(a.name)}<small>${platformName(s, a.platform)} · ${a.enabled ? "已启用" : "已停用"}</small></th>${s.tasks
            .map((t) => {
              const b = s.bindings.find(
                  (b) => b.account_id === a.id && b.task_id === t.id,
                ),
                enabled = a.enabled && t.enabled,
                same = a.platform === t.platform;
              return `<td>${same ? `<label class="matrix-cell"><input type="checkbox" data-binding="true" data-account="${a.id}" data-task="${t.id}" aria-label="${e(a.name + " 执行 " + t.name)}" ${b?.enabled ? "checked" : ""} ${enabled ? "" : "disabled"}><span>${enabled ? "执行此任务" : "配置已停用"}</span></label>` : '<span class="muted">平台不匹配</span>'}</td>`;
            })
            .join("")}</tr>`,
      )
      .join("")}</tbody></table></div></div>`;
  return (
    heading(
      "MATRIX",
      "任务矩阵",
      "行是账号，列是任务。勾选即可绑定；一键执行会检查并运行所有已启用的组合。",
      button("▷ 一键执行", "launch", "", "primary"),
    ) +
    body +
    `<div class="note">同一平台的账号共用频率与去重限制；平台出现限制时会一起暂停。修改绑定前，请先停止相关任务。</div>`
  );
}
export function platforms(s) {
  return (
    heading(
      "PLATFORMS",
      "平台接入",
      "快手支持两条评论业务。其他平台通过现有爬虫接入，评论能力按适配器逐步扩展。",
    ) +
    `<div class="panel"><div class="table-wrap"><table><thead><tr><th>平台</th><th>爬虫</th><th>评论发布</th><th>使用前检查</th></tr></thead><tbody>${s.platforms.map((p) => `<tr><td><b>${p.name}</b><small>${p.id}</small></td><td>${badge(p.crawler ? "适配器已连接" : "待配置运行依赖")}</td><td>${badge(p.comment ? "已接入" : "预留扩展")}</td><td class="muted">${p.id === "ks" ? "核验当前登录身份与视频详情" : "登录该平台后执行采集验证"}</td></tr>`).join("")}</tbody></table></div></div><div class="note">运行依赖已连接表示代码入口可用；不同平台的登录及接口状态，以各自任务的实际运行记录为准。</div><a class="button" href="#settings">配置爬虫运行路径 →</a>`
  );
}
export function runs(s, attempts = []) {
  const rows = s.runs;
  return (
    heading(
      "ACTIVITY",
      "运行记录",
      "搜索、筛选、等待与停止原因都保留记录；平台接收回执与评论可见性分别记录。",
    ) +
    s.risk
      .map(
        (r) =>
          `<div class="alert red"><strong>${platformName(s, r.platform)}已暂停</strong><span>${e(r.reason)}</span>${button("处理后解除", "clear-risk", r.platform)}</div>`,
      )
      .join("") +
    `<div class="panel"><div class="panel-title"><h2>执行队列</h2><span>${rows.length} 项最近任务</span></div>${rows.length ? `<div class="table-wrap"><table><thead><tr><th>任务 / 账号</th><th>状态</th><th>当前进展</th><th>下一步时间</th><th></th></tr></thead><tbody>${rows.map((r) => `<tr><td><b>${e(r.snapshot.task.name)}</b><small>${e(r.snapshot.account.name)} · ${time(r.created)}</small></td><td>${badge(r.state)}</td><td class="wrap">${e(r.message || "等待执行")}<small>采集 ${r.progress.collected || 0} · 发布 ${r.progress.sent || 0}</small></td><td>${active(r) && r.due ? time(r.due) : "—"}</td><td>${active(r) ? button("停止", "stop-run", r.id, "quiet") : ""}</td></tr>`).join("")}</tbody></table></div>` : empty("还没有执行记录", "完成配置后点击“一键执行”。")}</div><div class="panel spaced"><div class="panel-title"><h2>评论发送记录</h2><span>有回执才记为平台已接收</span></div>${attempts.length ? `<div class="table-wrap"><table><thead><tr><th>视频 / 时间</th><th>状态</th><th>评论内容</th><th>回执</th></tr></thead><tbody>${attempts.map((a) => `<tr><td>${e(a.video_id)}<small>${time(a.created)}</small></td><td>${badge(a.state)}</td><td class="wrap">${e(a.content)}</td><td class="wrap">${e(a.receipt.reason || "")}<small>${e(a.receipt.comment_id || "无评论ID")}</small></td></tr>`).join("")}</tbody></table></div>` : empty("本工作台还没有新发送记录", `已载入 ${s.history_count} 条历史接触记录用于去重。`)}</div><div class="panel spaced"><div class="panel-title"><h2>操作日志</h2></div><div class="event-list">${s.events.map((a) => `<div><span class="event-dot ${a.level === "risk" ? "danger" : ""}"></span><p>${e(a.message)}<small>${time(a.created)}</small></p></div>`).join("") || '<p class="muted">暂无操作记录</p>'}</div></div>`
  );
}
export function data(
  s,
  result,
  q = "",
  decision = "",
  batch = "latest",
  category = "",
) {
  return dataPage(s, result, q, decision, batch, category);
}
export function settings(s) {
  return (
    heading(
      "SETTINGS",
      "工作台设置",
      "运行目录和依赖保存在本机。修改后新任务使用新配置。",
    ) +
    `<form id="settings-form" class="panel form-panel">${field("Google Chrome程序路径", "chrome_path", s.settings.chrome_path, "text", "required")}${field("MediaCrawler项目目录", "crawler_root", s.settings.crawler_root, "text", "required")}${field("MediaCrawler的Python程序路径", "crawler_python", s.settings.crawler_python, "text", "required")}<div class="note">请选择已有运行环境的Python。工作台不会修改爬虫的共享配置，也不会把登录资料上传到GitHub。</div><button class="button primary">保存设置</button></form><div class="panel spaced"><div class="panel-title"><h2>执行保护</h2></div><div class="protection-grid"><div><b>读取</b><p>平台共享间隔 ≥ 5分钟，滚动24小时最多24批，08:00–23:00。</p></div><div><b>评论</b><p>平台共享间隔 ≥ 30分钟，滚动24小时最多5条，20:00–23:00内可缩短。</p></div><div><b>去重</b><p>同一视频不重复接触；同一作者和相同文本7天内不重复。</p></div><div><b>异常</b><p>账号不一致、平台限制、发送结果不确定均停发，不自动换号或重试。</p></div></div></div>`
  );
}

export function taskForm(s, t = {}) {
  const kind = t.kind || "adult_comments",
    d = s.defaults[kind] || {},
    platform = t.platform || "ks";
  return `<form id="task-form" data-id="${t.id || ""}"><div class="dialog-header"><div><div class="eyebrow">TASK CONFIGURATION</div><h2 id="dialog-title">${t.id ? "编辑任务" : "新建任务"}</h2></div>${button("×", "close-dialog", "", "icon-button")}</div><div class="form-grid">${field("任务名称", "name", t.name || d.name || "新采集任务", "text", 'required maxlength="60"')}${select(
    "平台",
    "platform",
    s.platforms.map((p) => [p.id, p.name]),
    platform,
  )}${select("业务类型", "kind", Object.entries(names), kind)}${select(
    "任务状态",
    "enabled",
    [
      ["true", "启用"],
      ["false", "停用"],
    ],
    String(t.enabled ?? true),
  )}</div>${area("搜索关键词 · 每行一个", "keywords", (t.keywords || d.keywords || [""]).join("\n"), "最多10个关键词。关键词用于查找，正文与详情用于决定是否评论。")}<div class="form-grid">${field("每个关键词最多读取条数", "max_items", t.max_items || 10, "number", 'min="1" max="20" required')}${field("单次任务最多发布条数", "max_publish", t.max_publish || 1, "number", 'min="1" max="5" required')}${select(
    "爬虫是否采集评论",
    "collect_comments",
    [
      ["false", "只采集内容"],
      ["true", "同时采集评论"],
    ],
    String(t.collect_comments ?? false),
  )}${field("每条内容最多采集评论数", "comments_per_item", t.comments_per_item || 10, "number", 'min="1" max="20" required')}${field("评论开始时间（小时）", "start_hour", t.start_hour || 20, "number", 'min="20" max="22" required')}${field("评论结束时间（小时）", "end_hour", t.end_hour || 23, "number", 'min="21" max="23" required')}</div><label class="field"><span>评论模板 · 每行一条，爬虫任务可留空</span><textarea name="templates" rows="3">${e((t.templates || d.templates || []).join("\n"))}</textarea><small>使用与业务一致的条件式询问或18+招募文案。系统会校验模板。</small></label><div class="dialog-footer">${button("取消", "close-dialog")}<button class="button primary">保存任务</button></div></form>`;
}
export function accountForm(s, a = {}) {
  return `<form id="account-form" data-id="${a.id || ""}"><div class="dialog-header"><h2 id="dialog-title">${a.id ? "编辑账号" : "添加账号"}</h2>${button("×", "close-dialog", "", "icon-button")}</div>${field("账号备注名称", "name", a.name || "", "text", 'required maxlength="40"')}${select(
    "平台",
    "platform",
    s.platforms.map((p) => [p.id, p.name]),
    a.platform || "ks",
  )}${field("浏览器资料目录（新账号可留空自动创建）", "profile_dir", a.profile_dir || "")}${select(
    "账号状态",
    "enabled",
    [
      ["true", "启用"],
      ["false", "停用"],
    ],
    String(a.enabled ?? true),
  )}<p class="muted">保存后点击“打开浏览器”，在平台完成登录，再“检查连接”。</p><div class="dialog-footer">${button("取消", "close-dialog")}<button class="button primary">保存账号</button></div></form>`;
}
