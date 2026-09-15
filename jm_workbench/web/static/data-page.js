import { escape as e, time, badge, heading, button, empty } from "./ui.js";

export function dataPage(
  s,
  result,
  q = "",
  decision = "",
  batch = "latest",
  category = "",
) {
  const summary = result.summary || {
    records: result.total,
    unique: result.total,
    duplicates: 0,
    content_matches: 0,
    categories: [],
  };
  const categoryButtons = [
    ["", "全部视频", summary.unique],
    ...summary.categories.map((c) => [c.id, c.label, c.count]),
  ];
  const templates = (result.comment_templates || [])
    .map(
      (t) =>
        `<article class="template-card"><div><b>${e(t.name)}</b><span>${t.enabled ? "已启用" : "已停用"} · ${t.start_hour}:00–${t.end_hour}:00</span></div><p class="template-condition">${t.kind === "adult_comments" ? "用于正文明确成人品类、自有经营与货品线索的视频。" : "用于正文明确成年且本人正在找陪玩工作的视频。"}</p>${t.templates.map((text) => `<blockquote>${e(text)}</blockquote>`).join("")}<small>模板来自当前任务配置；满足筛选、账号、去重和时段条件后才会使用。</small></article>`,
    )
    .join("");
  return (
    heading(
      "DATA / LEADS",
      "数据中心",
      "按业务看线索，再看是否符合评论条件。默认展示最新一批，相同视频合并显示。",
      '<a class="button" href="/api/export" download>↓ 导出全部记录（含分类）</a>',
    ) +
    `<div class="data-summary"><article><span>本批原始记录</span><b>${summary.records}<small>条</small></b></article><article><span>去重后内容</span><b>${summary.unique}<small>条</small></b></article><article><span>合并重复记录</span><b>${summary.duplicates}<small>条</small></b></article><article><span>正文初筛通过</span><b>${summary.content_matches}<small>条</small></b></article></div>
    <div class="data-explanation">${summary.content_matches === 0 ? "这批内容尚无通过评论正文规则的目标。" : "正文初筛通过仍需执行时核验准确详情和账号。"}“门店 / 品牌线索”只表示值得进一步了解，不能证明对方有尾货。</div>
    <details class="comment-templates" open><summary>满足条件后，会发哪些评论？</summary><div class="template-grid">${templates || '<p class="muted">尚未配置评论模板，请到任务配置中添加。</p>'}</div></details>
    <form id="data-filter" class="filter-bar data-filters"><select name="batch" aria-label="采集批次"><option value="latest" ${batch === "latest" ? "selected" : ""}>最新采集批次</option><option value="all" ${batch === "all" ? "selected" : ""}>全部批次（包含历史）</option>${(result.batches || []).map((b) => `<option value="${e(b.run_id)}" ${batch === b.run_id ? "selected" : ""}>${e(b.name)} · ${time(b.latest)} · ${b.records}条</option>`).join("")}</select><input name="q" value="${e(q)}" placeholder="搜索正文、作者或关键词" aria-label="搜索数据"><select name="decision" aria-label="筛选状态">${[
      ["", "全部执行状态"],
      ["collected", "只采集"],
      ["checking", "待详情核验"],
      ["eligible", "曾符合详情条件"],
      ["skipped", "执行时已跳过"],
      ["legacy", "历史迁入"],
    ]
      .map(
        ([v, n]) =>
          `<option value="${v}" ${v === decision ? "selected" : ""}>${n}</option>`,
      )
      .join("")}</select><button class="button primary">查询</button></form>
    <div class="category-filters" aria-label="业务分类">${categoryButtons.map(([id, label, count]) => `<button type="button" class="category-filter ${id === category ? "selected" : ""}" data-action="filter-category" data-id="${id}" aria-pressed="${id === category}">${e(label)} <b>${count}</b></button>`).join("")}</div>
    <div class="section-heading"><h2>当前分类结果 <span class="muted">${result.total} 条</span></h2><span>分类依据：已采集正文、标签与昵称；未核验视频画面</span></div><div class="panel">${
      result.items.length
        ? `<div class="data-list">${result.items
            .map((r) => {
              const d = r.data,
                p = r.comment_preview || {
                  label: "尚未判断",
                  reason: "",
                  templates: [],
                };
              const name =
                d.nickname || d.user_name || d.author_name || "作者信息未提供";
              return `<article data-evidence="${r.id}"><div class="data-meta"><span>${e(s.platforms.find((p) => p.id === r.platform)?.name || r.platform)}</span><span class="badge ${r.category === "inventory" || r.category === "jobseeker" ? "green" : r.category === "merchant" ? "amber" : "gray"}">${e(r.category_label || "待归类")}</span><span class="publish-label">${e(p.label)}</span><time>${time(r.created)}</time></div><div class="data-title"><h3>${e(name)}</h3>${r.video_url ? `<a class="text-link" href="${e(r.video_url)}" target="_blank" rel="noopener noreferrer">查看原视频 ↗</a>` : ""}</div><p>${e(d.caption || d.title || d.content || "没有可用于判断的正文")}</p><div class="data-reason"><span>为什么这样归类</span>${e(r.classification_reason || r.reason)}</div><div class="comment-result"><b>${e(p.label)}</b><p>${e(p.reason)}</p>${p.templates.map((t) => `<blockquote>${e(t)}</blockquote>`).join("")}${p.templates.length ? "<small>条件式文案预览，不代表本条已经进入发送队列。</small>" : ""}</div><div class="source-summary"><span>来源关键词：${(r.keywords || []).map(e).join("、") || "未记录"}</span><span>${r.occurrences || 1} 次采集记录已合并</span></div><details><summary>查看完整采集字段</summary><p>执行时的原判断：${e(r.reason)}</p><pre>${e(JSON.stringify(d, null, 2))}</pre></details></article>`;
            })
            .join("")}</div>`
        : empty(
            "没有符合条件的数据",
            "该分类没有匹配记录。可切换分类或批次查看其他内容。",
          )
    }</div><div class="pagination">${button("← 上一页", "data-prev", "", "quiet")}<span>第 ${result.page} / ${Math.max(1, Math.ceil(result.total / 30))} 页</span>${button("下一页 →", "data-next", "", "quiet")}</div>`
  );
}
