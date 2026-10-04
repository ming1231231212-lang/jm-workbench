import {escape as e,time,field,select,button,empty} from './ui.js';

export function dailyPage(data){
  const plans=data.plans||[];
  return `<div class="section-heading"><h2>每日计划</h2>${button('新建计划','com-plan-new','','primary')}</div><p class="muted">每天 1 篇帖子、评论 5 个不同帖子。北京时间执行；同帖、同内容不重复，错过的日期不追补。</p>`+
    (plans.length?plans.map(p=>`<article class="panel community-post"><div class="section-heading"><div><h2>${e(p.payload.name)}</h2><p>${p.state==='enabled'?'已启用':'已暂停'} · 每天 ${String(p.payload.hour).padStart(2,'0')}:${String(p.payload.minute).padStart(2,'0')} · ${p.platform==='juejin'?'掘金 · 分类':'贴吧 · 板块'}：${e(p.payload.board)}</p></div><div class="actions">${button(p.state==='enabled'?'暂停计划':'启用计划','com-plan-'+(p.state==='enabled'?'pause':'enable'),p.id,p.state==='enabled'?'':'primary')}${button('立即安排今天','com-plan-today',p.id)}${button('设置','com-plan-edit',p.id)}</div></div><p>${e(p.message)}</p><p class="muted">未用主题素材 ${p.remaining_topics} 篇 · 未用评论素材 / 规则 ${p.remaining_replies} 条。素材与匹配目标不足时会留空并说明原因。</p><div class="actions">${button('补充帖子素材','com-plan-topic',p.id,'small')}${button('补充指定帖评论','com-plan-reply',p.id,'small')}${button('补充自动匹配规则','com-plan-rule',p.id,'small')}${button('查看帖子内容','com-tab','posts','small')}${button('查看评论内容','com-tab','replies','small')}</div>${p.days.length?`<div class="table-wrap"><table><thead><tr><th>日期</th><th>帖子</th><th>评论其他帖子</th><th>说明</th></tr></thead><tbody>${p.days.map(d=>`<tr><td>${e(d.day)}</td><td>已提交 ${d.counts.thread.submitted}/1<br><span class="muted">等待 ${d.counts.thread.waiting} · 异常 ${d.counts.thread.failed}</span></td><td>已提交 ${d.counts.reply.submitted}/5<br><span class="muted">等待 ${d.counts.reply.waiting} · 异常 ${d.counts.reply.failed}</span></td><td>${e(d.message)}</td></tr>`).join('')}</tbody></table></div>`:''}<details><summary>查看全部素材与匹配规则</summary>${p.payload.topics.map(t=>`<h3>${e(t.title)}</h3>${t.platform_tags?.length?`<p class="muted">标签：${e(t.platform_tags.join('、'))}</p>`:''}<p class="community-preview">${e(t.body)}</p>`).join('')}${p.payload.replies.map(r=>`<h3>评论：${e(r.title)}</h3><p>${e(r.url)}</p><p class="community-preview">${e(r.body)}</p>`).join('')}${p.payload.reply_rules.map(r=>`<h3>匹配：${e(r.name)}</h3><p class="muted">同时包含：${e(r.terms.join('、'))}${r.require_question?'；只匹配求助问题':''}</p><p>${e(r.body)}</p>`).join('')}</details></article>`).join(''):empty('还没有每日计划','配置账号、分类或吧名、素材与评论来源后启用。'));
}

export function dailyForm(ui,p){
  const d=p?.payload||{name:'每日社区内容计划',account_id:'',board:'ai工具',rules_note:'',hour:10,minute:0,source_boards:[]};
  ui.showForm(`<form id="com-plan-form" data-id="${e(p?.id||'')}"><div class="dialog-header"><h2 id="dialog-title">每日计划设置</h2>${button('×','close-dialog','','icon-button')}</div>${field('计划名称','name',d.name,'text','required maxlength="60"')}${select('发布账号','account_id',ui.data.accounts.filter(a=>['tieba','juejin'].includes(a.platform)&&a.enabled).map(a=>[a.id,a.name]),d.account_id)}${field('文章分类 / 贴吧吧名','board',d.board,'text','required')}${field('每天开始时间（北京时间）','start_time',`${String(d.hour).padStart(2,'0')}:${String(d.minute).padStart(2,'0')}`,'time','required max="20:59"')}<p>掘金分类可填“人工智能”；标签按每篇素材设置。贴吧填写吧名。每天发帖 1 篇，评论 5 个不同帖子；统一间隔至少 30 分钟，平台异常会停止。</p>${field('评论来源：掘金标签 / 贴吧吧名（最多3个）','source_boards',d.source_boards.join('，'),'text','placeholder="人工智能，AI编程，Agent"')}<label class="field"><span>发布位置与内容规则</span><textarea name="rules_note" required minlength="12" rows="3">${e(d.rules_note)}</textarea></label><p class="muted">保存不会启动。启用后自动选用未用素材；不足时记录缺口，不重复发送。需保持本机服务和账号Chrome可用。</p><div class="dialog-footer">${button('取消','close-dialog')}<button class="button primary">保存设置</button></div></form>`);
}

export function materialForm(ui,p,kind){
  if(p.state==='enabled')throw Error('请先暂停计划，再补充素材；原记录会保留');
  const area=(label,name,rows=5)=>`<label class="field"><span>${label}</span><textarea name="${name}" rows="${rows}" required></textarea></label>`;
  const fields=kind==='topic'?field(p.platform==='juejin'?'文章标题（5–100字）':'帖子标题（5–31字）','title','','text',p.platform==='juejin'?'required minlength="5" maxlength="100"':'required minlength="5" maxlength="31"')+area('帖子正文','body',8)+field('核心长尾词（可选）','keyword','')+(p.platform==='juejin'?field('文章相关标签（逗号分隔，最多3个）','platform_tags','','text','required placeholder="人工智能，AI编程"'):''):
    kind==='reply'?field('目标帖子HTTPS链接','url','','url','required')+field('原帖标题','title','','text','required')+area('原帖正文（用于提交前核对）','excerpt',4)+area('准备发送的评论','body',6)+field('核心长尾词（可选）','keyword',''):
    field('规则名称','name','','text','required')+field('原帖必须同时包含的词（逗号分隔）','terms','','text','required placeholder="Skill，使用"')+select('目标类型','require_question',[['true','只回复求助问题'],['false','相关讨论也可回复']],'true')+area('有实质帮助的回复内容','body',7)+'<p class="muted">自动匹配规则不带网址或联系方式；每条内容只使用一次，原帖须同时匹配全部词。</p>';
  ui.showForm(`<form id="com-plan-material-form" data-id="${e(p.id)}" data-kind="${kind}"><div class="dialog-header"><h2 id="dialog-title">补充${{topic:'帖子素材',reply:'指定帖评论',rule:'自动匹配规则'}[kind]}</h2>${button('×','close-dialog','','icon-button')}</div>${fields}<div class="dialog-footer">${button('取消','close-dialog')}<button class="button primary">保存素材</button></div></form>`);
}

export async function dailyAction(ui,action,id){
  const p=(ui.data.plans||[]).find(p=>p.id===id);
  if(action==='com-plan-new')return dailyForm(ui);
  if(!p)throw Error('每日计划不存在，请刷新');
  if(action==='com-plan-edit'){
    if(p.state==='enabled')throw Error('请先暂停计划再修改设置');
    return dailyForm(ui,p);
  }
  if(['com-plan-topic','com-plan-reply','com-plan-rule'].includes(action))return materialForm(ui,p,action.slice(9));
  const result=await ui.request(`/api/community/plans/${id}/${action.slice(9)}`,{});
  await ui.fresh();ui.toast(result.message);
}

export async function dailySubmit(ui,form){
  const fd=new FormData(form),id=form.dataset.id;
  const existing=(ui.data.plans||[]).find(p=>p.id===id)?.payload;
  let d=structuredClone(existing||{topics:[],replies:[],reply_rules:[]});
  if(form.id==='com-plan-form'){
    const [hour,minute]=String(fd.get('start_time')).split(':').map(Number);
    d={...d,name:fd.get('name'),account_id:fd.get('account_id'),board:fd.get('board'),rules_note:fd.get('rules_note'),hour,minute,source_boards:String(fd.get('source_boards')||'').split(/[,，]/).map(s=>s.trim()).filter(Boolean)};
  }else{
    const v=Object.fromEntries(fd);const key={topic:'topics',reply:'replies',rule:'reply_rules'}[form.dataset.kind];
    if(key==='reply_rules'){v.terms=v.terms.split(/[,，]/).map(s=>s.trim()).filter(Boolean);v.require_question=v.require_question==='true';}
    if(key==='topics'&&v.platform_tags)v.platform_tags=v.platform_tags.split(/[,，]/).map(s=>s.trim()).filter(Boolean);
    d[key].push(v);
  }
  const result=await ui.request('/api/community/plans'+(id?'/'+id:''),d,id?'PUT':'POST');
  ui.tab='plans';await ui.fresh();ui.dialog.close();ui.toast(result.message);
}
