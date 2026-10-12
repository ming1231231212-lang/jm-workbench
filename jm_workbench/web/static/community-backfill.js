import { escape as e, button as b } from './ui.js';
const labels = {draft:'正文已补录 · 待执行连接',missing_target:'待匹配原帖',missing_content:'待补充正文',needs_check:'原任务需处理',submitted:'平台已接收',recorded:'人工登记 · 待核验',queued:'已排队'};
export function backfillView(data, expanded = false) {
  const ledger = data.backfill;
  if (!ledger?.total) return '';
  const groups = new Map();
  for (const r of ledger.items) {
    const key = `${r.plan_id}|${r.day}`;
    if (!groups.has(key)) groups.set(key,{...r,key,thread:0,reply:0,ready:0,submitted:0});
    const g=groups.get(key);g[r.kind]++;g.ready+=Boolean(r.post_id);g.submitted+=r.status==='submitted';
  }
  return `<section class="panel spaced"><div class="section-heading"><div><h2>历史补发清单 <small>${ledger.total} 项</small></h2><p class="section-description">漏执行的日期与实际发送日期分别记录。补录不会标记为已发布。</p></div></div><div class="capacity-row"><span>已登记缺口</span><b>帖子 ${ledger.threads} · 评论 ${ledger.replies}</b></div><div class="capacity-row"><span>已关联正文 / 原任务</span><b>${ledger.with_content} 项 · 平台已接收 ${ledger.submitted} 项</b></div>${b(expanded ? "收起逐日清单" : "逐日查看内容与处理原因", "com-backfill-toggle", "", "small")}${expanded ? `<div class="table-wrap"><table><thead><tr><th>原计划日期</th><th>平台</th><th>帖子 / 评论缺口</th><th>已关联内容</th><th>操作</th></tr></thead><tbody>${[...groups.values()].map(g=>`<tr><td>${e(g.day)}</td><td>${e(data.platforms.find(p=>p.id===g.platform)?.name||g.platform)}</td><td>${g.thread} / ${g.reply}</td><td>${g.ready} 项</td><td>${b('查看补录','com-backfill-view',g.key,'small')}</td></tr>`).join('')}</tbody></table></div>` : ""}<p class="form-note">实际发布继续使用原账号、去重检查及每日额度。缺少连接、原帖或明确回执时会保留待处理状态。</p></section>`;
}
export function backfillDetail(data,key) {
  const [planId,day]=key.split('|');
  const items=(data.backfill?.items||[]).filter(r=>r.plan_id===planId&&r.day===day);
  return `<div class="dialog-header"><h2 id="dialog-title">${e(day)} 历史补录</h2>${b('×','close-dialog','','icon-button')}</div>${items.map(r=>{
    const post=data.posts.find(p=>p.id===r.post_id);
    return `<section class="spaced"><p><b>${r.kind==='thread'?'帖子':'评论'} ${r.slot}</b> · ${e(labels[r.status]||r.status)}</p><p class="form-note">${e(r.message)}</p>${post?`<h3>${e(post.payload.title)}</h3><pre class="result-message">${e(post.payload.body)}</pre>${post.payload.kind==='reply'?`<p>原帖：${e(post.payload.targets[0].destination)}</p>`:''}${b('查看原内容与回执','com-view',post.id,'small')}`:'<p class="muted">尚无完整内容；连接后只匹配相关原帖，不生成虚假目标或成功记录。</p>'}</section>`;
  }).join('')}<div class="dialog-footer">${b('关闭','close-dialog')}${b('核验连接 / 补充原帖','com-backfill-prepare',planId,'primary')}</div>`;
}
