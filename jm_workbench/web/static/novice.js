import { escape as e, button as b, time } from './ui.js';
import { icon } from './community-icons.js';
import { planStatus, getPlatform, postStatus } from './community-v2-model.js';

export const communityTabs = [
  ['overview','今日工作','layout-dashboard'], ['content','内容与记录','file-text'],
  ['plans','发布安排','calendar-check-2'], ['accounts','平台账号','users-round'],
];
export function parseRoute(hash, pages) {
  const [raw, tab] = hash.replace(/^#/, '').split('/');
  const page = pages.some(p => p[0] === raw) ? raw : 'community';
  return {page, tab:communityTabs.some(t => t[0] === tab) ? tab : 'overview'};
}
export function navigation(page, tab, pages, icons) {
  const link=(url,label,glyph,active)=>`<a href="#${url}" ${active?'class="active" aria-current="page"':''}><span>${icon(glyph)}</span>${e(label)}</a>`;
  return communityTabs.map(([id,label,glyph])=>link('community/'+id,label,glyph,page==='community'&&tab===id)).join('')+
    `<details class="more-tools" ${page!=='community'?'open':''}><summary>${icon('grid-2x2')}更多工具${icon('chevron-down')}</summary><div>${pages.filter(p=>!p[3]&&p[0]!=='community').map(([id,_,label])=>link(id,({tasks:'采集与评论',publishing:'视频与素材',data:'采集数据',accounts:'采集账号',settings:'高级设置'})[id]||label,icons[id],page===id)).join('')}</div></details>`;
}
export function overview(data) {
  const counts=data.queue_counts||{}, summary=data.summary||{}, runtime=data.executor||{status:'stopped',message:'后台状态尚未确认'}, ledger=data.backfill;
  const running=(data.posts||[]).find(p=>p.jobs?.some(j=>j.state==='running'));
  const issues=[];
  for(const risk of data.risk||[]) issues.push(`<article class="todo-item"><div><strong>${e(getPlatform(data,risk.platform).name)}已暂停</strong><p>${e(risk.reason)}</p></div>${b('查看原因','com-risk',risk.platform,'small')}</article>`);
  for(const plan of data.plans||[]) {
    if(planStatus(plan,data).key==='enabled'&&plan.remaining_topics===0&&!plan.payload.auto_prepare) issues.push(`<article class="todo-item"><div><strong>${e(plan.payload.name)}需要补充帖子</strong><p>当前没有未使用的帖子正文，准备好内容后才能继续发帖。</p></div>${b('补充内容','com-plan-topic',plan.id,'small')}</article>`);
  }
  if(ledger?.items?.some(i=>i.status==='missing_target')) issues.push(`<article class="todo-item"><div><strong>${ledger.items.filter(i=>i.status==='missing_target').length}条历史评论缺少合适原帖</strong><p>暂时不会发送；先匹配相关原帖，再安排评论。</p></div>${b('查看清单','com-backfill-toggle','','small')}</article>`);
  const cards=[['平台已接收帖子',summary.thread_submitted||0,'篇','thread'],['平台已接收评论',summary.reply_submitted||0,'条','reply'],['排队等待',counts.queued||0,'项','queued'],['结果需要核实',counts.unknown||0,'项','unknown']];
  return `${data.browser_execution==="web"?`<div class="detail-alert" role="status"><strong>社区浏览器发布已改为网页操作</strong>不再需要扩展配对。工作台保存正文和记录；复制或导出内容，在网站提交后回来登记链接。贴吧、掘金和 CSDN 的每日自动发帖与评论已停用。${b("查看内容","com-tab","content","small")}</div>`:""}<div class="novice-status ${runtime.status==='stopped'||runtime.status==='attention'?'warning':''}" role="status"><span class="runtime-mark ${e(runtime.status)}">${icon(runtime.status==='working'?'loader-circle':runtime.status==='ready'?'circle-check':'circle-alert')}</span><div><strong>${e(data.browser_execution==="web" && runtime.status==="ready" ? "后台服务正常 · 社区内容在网站提交" : runtime.message)}</strong><p>${running?e(running.payload.title)+' · ':''}${runtime.operations?.length?'本次操作最迟 '+time(runtime.operations[0].deadline_at)+' 结束；超时会停止，不会一直卡住。':runtime.status==='ready'?(data.browser_execution==='web'?'后台服务正常；社区浏览器发布需在网站完成，自动计划不会发送。':'保持电脑开机、网络可用，后台会按安排执行。'):'请检查后台服务，网页能打开不代表发布任务正在运行。'}</p></div>${running?b('查看任务','com-view',running.id,'small'):b('查看安排','com-tab','plans','small')}</div>
    <div class="novice-metrics">${cards.map(([label,n,unit,id])=>`<button data-action="com-v2-status" data-id="${id}"><span>${label}</span><strong>${n}<small>${unit}</small></strong></button>`).join('')}</div><p class="receipt-note">今天 ${e(summary.day||'')} · 接收回执与公开可见性分别记录，点开内容查看真实结果。</p>
    <section class="novice-section"><div class="section-heading"><div><h2>今天的发布安排</h2><p>每个平台分开看，暂停原因和下一步都在这里。</p></div>${b('管理安排','com-tab','plans','small quiet')}</div>${data.plans?.length?`<div class="today-plans">${data.plans.map(plan=>{
      const state=planStatus(plan,data), actual=summary.platforms?.[plan.platform]||{}, recorded=summary.platform_results?.[plan.platform]||{}, prep=plan.preparations?.[0];
      return `<article class="today-plan"><div class="today-plan-title"><span class="platform-mark ${e(plan.platform)}">${e(getPlatform(data,plan.platform).name.slice(0,1))}</span><div><h3>${e(getPlatform(data,plan.platform).name)}</h3><p>${e(plan.payload.name)}</p></div><span class="badge ${e(state.tone)}">${e(state.label)}</span></div><div class="today-numbers"><span>今日帖子 <b>${(actual.thread||0)+(recorded.thread_recorded||0)}</b></span><span>今日评论 <b>${(actual.reply||0)+(recorded.reply_recorded||0)}</b></span><small>已接收 / 网页已登记</small></div>${(recorded.thread_recorded||recorded.reply_recorded)?`<p class="receipt-note">网页结果已登记：帖子 ${recorded.thread_recorded||0} 篇 · 评论 ${recorded.reply_recorded||0} 条（点开内容查看链接）</p>`:""}${plan.payload.auto_prepare?`<p class="receipt-note">自动准备已开启 · ${e(prep?.message||"每天提前一小时检查素材并补充")}</p>`:""}<p class="plan-explanation">${e(state.key==='enabled'?plan.message||'按设置准备内容':state.reason||'已暂停，保留全部记录')}</p><div class="plan-next">${state.key==='enabled'&&plan.next_action_at?'下次 '+time(plan.next_action_at)+' · '+e(plan.next_action||'检查安排'):'暂停期间不会发送'}</div>${b('查看详情','com-v2-plan',plan.id,'small')}</article>`;
    }).join('')}</div>`:`<div class="novice-empty"><h3>从一个平台开始</h3><p>添加账号，写好内容，再设置发布时间。</p>${b('添加账号','com-new-account','','primary')}${b('写内容','com-v2-compose')}</div>`}</section>
    ${issues.length?`<section class="novice-section"><div class="section-heading"><h2>需要处理 <small>${issues.length}</small></h2></div><div class="todo-list">${issues.join('')}</div></section>`:''}
    ${ledger?.total?`<details class="history-summary" ${data._backfillOpen?'open':''}><summary>历史补发 · ${ledger.submitted} / ${ledger.total} 项已接收<span>缺口、正文与原帖逐日查看</span></summary><div id="novice-history"></div></details>`:''}
    <section class="novice-section"><div class="section-heading"><h2>最近内容</h2>${b('全部记录','com-tab','content','small quiet')}</div><div class="recent-list">${(data.posts||[]).slice(0,4).map(p=>`<button class="recent-content" data-action="com-view" data-id="${e(p.id)}"><span>${icon(p.payload.kind==='reply'?'message-square':'file-text')}<span><strong>${e(p.payload.source_title||p.payload.title)}</strong><small>${e(p.payload.body.slice(0,85))}</small></span></span><span class="badge ${e(postStatus(p).tone)}">${e(postStatus(p).label)}</span></button>`).join('')||'<p class="form-note">保存第一份草稿后，会在这里看到内容。</p>'}</div></section>`;
}
