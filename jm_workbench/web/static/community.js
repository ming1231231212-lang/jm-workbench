import {escape as e, time, field, select, button, heading, empty} from './ui.js';

export const communityStates={draft:'本地草稿',queued:'等待执行',running:'提交中',paused:'已暂停',submitted:'已提交 · 未核验',unknown:'结果不明',failed:'未提交',not_sent:'已核实未发布',cancelled:'已取消',manual:'待网页发布',recorded:'已登记链接 · 未核验'};
const badge=s=>`<span class="badge ${['unknown','failed'].includes(s)?'red':['submitted','recorded'].includes(s)?'green':['manual','queued','paused'].includes(s)?'amber':'gray'}">${e(communityStates[s]||s)}</span>`;
function accountStatus(a,p){
  if(!a.enabled)return '已停用';
  if(a.platform==='tieba'&&a.sync_status==='pending')return e(a.sync_message);
  if(a.identity)return a.platform==='tieba'?'已登录 · 已同步':'身份已核验';
  return p.automatic?'待配置 / 检查':'网页账号记录';
}
export function communityPayload(fd){
  const ids=fd.getAll('account_ids').map(String);
  if(!ids.length)throw Error('请至少选择一个发布账号');
  const scheduled=fd.get('mode')==='scheduled';
  const schedule=scheduled?new Date(fd.get('schedule')).getTime()/1000:0;
  if(scheduled&&(!Number.isFinite(schedule)||schedule<=Date.now()/1000))throw Error('请选择未来的发布时间');
  return {request_id:String(fd.get('request_id')),title:String(fd.get('title')||'').trim(),body:String(fd.get('body')||'').trim(),kind:String(fd.get('kind')||'thread'),source_title:String(fd.get('source_title')||''),source_excerpt:String(fd.get('source_excerpt')||''),tags:String(fd.get('tags')||'').split(/[\s,，]+/).filter(Boolean),schedule_at:schedule,
    targets:ids.map(id=>({account_id:id,destination:String(fd.get('destination_'+id)||'').trim()}))};
}

export function communityPage(data,tab='posts',region='',query=''){
  const names=Object.fromEntries(data.platforms.map(p=>[p.id,p.name]));
  const tools=button('新建帖子','com-new','','primary')+button('评论帖子','com-new-reply');
  const tabs=`<div class="tabs community-tabs">${[['posts','帖子'],['replies','评论'],['accounts','账号'],['platforms','平台 · 20']].map(([id,label])=>button(label,'com-tab',id,tab===id?'active':'')).join('')}</div>`;
  let body='';
  if(tab==='posts'||tab==='replies'){
    const shown=data.posts.filter(p=>(p.payload.kind||'thread')===(tab==='replies'?'reply':'thread'));
    body=shown.length?`<div class="community-posts">${shown.map(post=>`<article class="panel community-post"><div class="section-heading"><div><h2>${e(post.payload.title)}</h2><p class="community-preview">${e(post.payload.body||'')}</p>${post.payload.source_title?`<p class="muted">原帖：${e(post.payload.source_title)}</p>`:''}<p class="muted">${time(post.created)} · ${post.payload.targets.length} 个发布目标${post.payload.schedule_at?' · 定时 '+time(post.payload.schedule_at):''}</p></div><div class="actions">${button('查看内容','com-view',post.id,'small')}${post.state==='draft'?button('编辑','com-edit',post.id,'small')+button('开始发布','com-launch',post.id,'primary small'):''}${post.jobs.some(j=>j.state==='queued'||j.state==='running')?button('暂停','com-pause',post.id,'small'):''}${post.jobs.some(j=>j.state==='paused')?button('继续','com-resume',post.id,'small'):''}${post.state==='draft'||post.jobs.some(j=>['queued','paused','manual'].includes(j.state))?button('取消','com-cancel',post.id,'small'):''}</div></div>${post.jobs.length?`<div class="table-wrap"><table class="community-jobs"><thead><tr><th>平台 / 账号</th><th>板块</th><th>状态</th><th>结果与操作</th></tr></thead><tbody>${post.jobs.map(j=>`<tr><td><b>${e(names[j.platform])}</b><div class="muted">${e(j.account_name)}</div></td><td>${e(j.destination||'个人主页')}</td><td>${badge(j.state)}${j.state==='queued'?`<div class="muted">${time(j.due)}</div>`:''}</td><td><div class="muted">${e(j.message)}</div><div class="actions">${button(j.receipt.url?'打开帖子':'打开网页','com-open-job',j.id,'small')}${j.state==='manual'?button('登记链接','com-record',j.id,'small'):''}${j.state==='unknown'?button('核实结果','com-resolve',j.id,'small'):''}</div></td></tr>`).join('')}</tbody></table></div>`:`<p>${badge(post.state)} · 保存草稿不会发布到任何平台</p>`}</article>`).join('')}</div>`:empty('从第一篇帖子开始','先添加贴吧账号，再选择吧名、填写标题和正文。',button('添加社区账号','com-new-account','','primary'));
  } else if(tab==='accounts'){
    body=`<div class="section-heading"><h2>社区账号 <span class="count-label">${data.accounts.length}</span></h2>${button('添加账号','com-new-account','','primary')}</div><p class="muted">贴吧在专属Chrome登录后，返回工作台自动同步；也可点“检查连接”。API密钥只在本机加密保存。</p>`;
    body+=data.accounts.length?`<div class="table-wrap"><table><thead><tr><th>账号</th><th>平台</th><th>连接方式</th><th>状态</th><th>操作</th></tr></thead><tbody>${data.accounts.map(a=>{const p=data.platforms.find(p=>p.id===a.platform);return `<tr><td><b>${e(a.name)}</b><div class="muted">${e(a.identity_hint)}</div></td><td>${e(p.name)}</td><td>${e(p.mode_label)}</td><td>${accountStatus(a,p)}${a.identity?`<div class="muted">账号 ID：${e(a.identity)}</div>`:''}</td><td><div class="actions">${button('登录 / 打开','com-open-account',a.id,'small')}${p.automatic?button('检查连接','com-check',a.id,'small'):''}${button('编辑','com-edit-account',a.id,'small')}${button('删除','com-delete-account',a.id,'small danger')}</div></td></tr>`;}).join('')}</tbody></table></div>`:empty('尚未添加社区账号','点击添加账号，默认优先百度贴吧。');
  } else {
    const filtered=data.platforms.filter(p=>(!region||p.region===region)&&(!query||`${p.name} ${p.categories}`.toLowerCase().includes(query.toLowerCase())));
    body=`<form id="com-filter" class="community-filter">${select('地区','region',[['','全部'],['国内','国内'],['国外','国外']],region)}${field('搜索平台 / 类型','query',query,'search','placeholder="贴吧、AI、互联网、编程…"')}<button class="button">筛选</button></form><p class="muted">20个平台统一管理。自动发布方式与网页登录方式分别标明；Hacker News只支持本人在网页撰写与提交。</p><div class="table-wrap"><table><thead><tr><th>平台</th><th>内容方向</th><th>支持形式</th><th>当前发布方式</th><th>操作</th></tr></thead><tbody>${filtered.map(p=>`<tr><td><b>${e(p.name)}</b><div class="muted">${e(p.region)}</div></td><td>${e(p.categories)}</td><td>${e(p.format)}</td><td>${e(p.mode_label)}<div class="muted">${e(p.note)}</div></td><td>${button('添加账号','com-add-platform',p.id,'small')}</td></tr>`).join('')}</tbody></table></div>`;
  }
  const risks=data.risk.length?`<div class="community-notice">${data.risk.map(r=>`<div><b>${e(names[r.platform])}已暂停：</b>${e(r.reason)} ${button('处理记录','com-risk',r.platform,'small')}</div>`).join('')}</div>`:'';
  return heading('COMMUNITY','社区发布','标题、正文、账号和板块，一处管理。',tools)+tabs+risks+body;
}

export class CommunityUI {
  constructor({request,toast,render,showForm,dialog,clock=Date.now}){Object.assign(this,{request,toast,render,showForm,dialog,clock});this.tab='posts';this.region='';this.query='';this.syncChecks=new Map();}
  async load(){
    if(this.loading)return this.loading;
    this.loading=this.loadAndSync();
    try{return await this.loading;}finally{this.loading=null;}
  }
  async loadAndSync(){
    const data=await this.request('/api/community/state');
    for(const a of data.accounts){
      if(a.platform!=='tieba'||!a.enabled)continue;
      let check=this.syncChecks.get(a.id);
      if(!check||check.version!==a.version||this.clock()-check.at>=30000){
        check={at:this.clock(),version:a.version};this.syncChecks.set(a.id,check);
        try{
          const result=await this.request(`/api/community/accounts/${a.id}/sync`,{});
          check.status=result.status;check.message=result.message;
          if(result.account)Object.assign(a,result.account);
        }catch{
          check.status='pending';check.message='同步未完成，可点击“检查连接”重试';
        }
      }
      a.sync_status=check.status;a.sync_message=check.message;
    }
    this.data=data;return data;
  }
  async fresh(){await this.load();await this.render();}
  compose(post,kind='thread'){
    if(!this.data.accounts.length){this.accountForm();return;}
    const value=post?.payload||{kind,request_id:crypto.randomUUID(),title:'',body:'',tags:[],targets:[],schedule_at:0};
    const date=value.schedule_at?new Date(value.schedule_at*1000):new Date(Date.now()+3600000);
    const local=new Date(date.getTime()-date.getTimezoneOffset()*60000).toISOString().slice(0,16);
    this.showForm(`<form id="com-post-form" data-id="${e(post?.id||'')}"><input type="hidden" name="kind" value="${e(value.kind||'thread')}"><input type="hidden" name="source_title" value="${e(value.source_title||'')}"><input type="hidden" name="source_excerpt" value="${e(value.source_excerpt||'')}"><input type="hidden" name="request_id" value="${e(value.request_id)}"><div class="dialog-header"><div><h2 id="dialog-title">${value.kind==='reply'?'评论其他帖子':post?'编辑帖子':'新建帖子'}</h2><p>选账号与板块，保存后可一键执行。</p></div>${button('×','close-dialog','','icon-button')}</div><div class="community-compose"><section>${field(value.kind==='reply'?'评论备注（仅工作台显示）':'标题','title',value.title,'text','required maxlength="120"')}<label class="field"><span>正文</span><textarea name="body" rows="13" maxlength="12000" required placeholder="填写要发布的内容；请遵守目标社区规则。">${e(value.body)}</textarea></label>${field('话题（可选，DEV使用）','tags',value.tags.join(' '),'text','placeholder="最多4个英文或数字标签，用空格分隔"')}</section><aside><h3>发布到</h3><div class="community-targets">${this.data.accounts.filter(a=>a.enabled&&(value.kind!=='reply'||a.platform==='tieba')).map(a=>{const p=this.data.platforms.find(p=>p.id===a.platform),t=value.targets.find(t=>t.account_id===a.id);return `<div class="community-target"><label><input type="checkbox" name="account_ids" value="${e(a.id)}" ${t?'checked':''}><b>${e(a.name)}</b></label><div class="muted">${e(p.name)} · ${e(p.mode_label)}</div>${p.destination_hint?field(p.id==='tieba'?(value.kind==='reply'?'目标帖子HTTPS链接':'发布到哪个吧'):p.id==='reddit'?'Subreddit':'板块 / 项目','destination_'+a.id,t?.destination||'','text',`placeholder="${e(value.kind==='reply'?'https://tieba.baidu.com/p/…':p.destination_hint)}"`):''}${p.id==='hackernews'?'<p class="community-warning">仅本人原创文字；本平台禁止自动发帖与AI生成/改写内容。</p>':''}</div>`;}).join('')}</div>${select('发布时间','mode',[['now','立即'],['scheduled','定时']],value.schedule_at?'scheduled':'now')}<label class="field"><span>定时时间（选定时后生效）</span><input type="datetime-local" name="schedule" value="${local}"></label><p class="muted">直接发布按平台共享间隔执行；网页发布需在网站完成最后提交。</p></aside></div><div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button" name="submit_mode" value="draft">保存草稿</button><button class="button primary" name="submit_mode" value="launch">保存并开始</button></div></form>`);
  }
  accountForm(account,platformId='tieba'){
    this.showForm(`<form id="com-account-form" data-id="${e(account?.id||'')}"><div class="dialog-header"><h2 id="dialog-title">${account?'编辑':'添加'}社区账号</h2>${button('×','close-dialog','','icon-button')}</div>${select('平台','platform',this.data.platforms.map(p=>[p.id,p.name+' · '+p.mode_label]),account?.platform||platformId)}${field('账号名称','name',account?.name||'','text','required maxlength="60" placeholder="例如：贴吧主账号"')}${field('账号备注（可选）','identity_hint',account?.identity_hint||'','text','maxlength="100" placeholder="便于你区分账号"')}<div class="com-api-secret">${field('API密钥 / OAuth访问令牌','secret','','password',`autocomplete="new-password" maxlength="4096" placeholder="${account?.secret_configured?'已配置；留空保留原密钥':'仅API平台需要'}"`)}<p class="muted">DEV使用API Key；X/Reddit使用已获授权的用户访问令牌；Hugging Face使用写权限Token。不要填写账号密码。</p></div><div class="com-browser-help"><p>保存后点“登录 / 打开”，在专属Chrome中完成登录。贴吧返回工作台后自动同步，也可点“检查连接”。工作台不会索取登录密码。</p></div>${select('状态','enabled',[['true','启用'],['false','停用']],String(account?.enabled??true))}<div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button primary">保存账号</button></div></form>`);
    const f=document.querySelector('#com-account-form');
    if(account)f.elements.platform.disabled=true;
    this.syncAccount(f);
  }
  syncAccount(f){const p=this.data.platforms.find(p=>p.id===f.elements.platform.value);f.querySelector('.com-api-secret').hidden=p.mode!=='api';f.querySelector('.com-browser-help').hidden=p.mode==='api';}
  deleteAccountForm(id){
    const a=this.data.accounts.find(a=>a.id===id);
    if(!a)throw Error('账号已不存在，请刷新列表');
    const p=this.data.platforms.find(p=>p.id===a.platform);
    this.showForm(`<form id="com-delete-account-form" data-id="${e(a.id)}" data-version="${e(a.version)}"><div class="dialog-header"><h2 id="dialog-title">删除社区账号</h2>${button('×','close-dialog','','icon-button')}</div><p>确认删除 <b>${e(a.name)}</b>？</p><p class="muted">${e(p.name)} · ${e(a.identity_hint||'无备注')}<br>${a.identity?'已核验账号 ID：'+e(a.identity):'尚未核验登录'}</p><p>仅移除工作台账号配置，平台账号和浏览器登录资料保留。有帖子或任务引用时会提示处理方式。</p><div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button danger">确认删除</button></div></form>`);
  }
  async handle(action,id){
    if(action==='com-tab'){this.tab=id;return this.render();}
    if(action==='com-new-reply'){await this.load();return this.compose(null,'reply');}
    if(action==='com-new'){await this.load();return this.compose();}
    if(action==='com-new-account'||action==='com-add-platform'){await this.load();return this.accountForm(null,id||'tieba');}
    if(action==='com-edit-account')return this.accountForm(this.data.accounts.find(a=>a.id===id));
    if(action==='com-delete-account')return this.deleteAccountForm(id);
    if(action==='com-edit')return this.compose(this.data.posts.find(p=>p.id===id));
    if(action==='com-view'){
      const post=this.data.posts.find(p=>p.id===id);
      this.showForm(`<div><div class="dialog-header"><h2 id="dialog-title">${post.payload.kind==='reply'?'评论内容':'帖子内容'}</h2>${button('×','close-dialog','','icon-button')}</div><label class="field"><span>标题</span><input id="com-copy-title" readonly value="${e(post.payload.title)}"></label>${button('复制标题','com-copy','title','small')}<label class="field"><span>正文</span><textarea id="com-copy-body" rows="12" readonly>${e(post.payload.body)}</textarea></label>${button('复制正文','com-copy','body','small')}${post.payload.kind==='reply'?`<p>目标帖子：${e(post.payload.targets[0].destination)}</p><p class="muted">${e(post.payload.source_title||'')}<br>${e(post.payload.source_excerpt||'')}</p>`:''}<p class="muted">这里保存实际提交的内容快照；回执与公开可见性分别记录。</p></div>`);return;
    }
    if(action==='com-copy'){await navigator.clipboard.writeText(document.querySelector('#com-copy-'+id).value);this.toast('已复制');return;}
    if(action==='com-record'){this.showForm(`<form id="com-record-form" data-id="${e(id)}"><h2 id="dialog-title">登记帖子链接</h2><p>在网站发布完成后粘贴链接；记录标为用户登记，不代表工作台已验证公开可见。</p>${field('帖子HTTPS链接','url','','url','required')}<div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button primary">保存链接</button></div></form>`);return;}
    if(action==='com-resolve'){this.showForm(`<form id="com-resolve-form" data-id="${e(id)}"><h2 id="dialog-title">核实不确定的发布结果</h2><p>先在平台检查，填写真实结果。此操作只登记，不会重发。</p>${select('核实结果','outcome',[['submitted','已经发布，登记帖子链接'],['not_sent','确认没有发布']], 'submitted')}${field('帖子链接（已经发布时必填）','url','','url')}<label class="field"><span>核实说明（至少12字）</span><textarea name="note" minlength="12" required></textarea></label><div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button primary">登记核实结果</button></div></form>`);return;}
    if(action==='com-risk'){this.showForm(`<form id="com-risk-form" data-id="${e(id)}"><h2 id="dialog-title">处理平台暂停</h2><p>先到网站核实结果。存在结果不明记录时，需要逐条填写核实结果后再解除；解除不会自动启动任务。</p><label class="field"><span>处理说明（至少12字）</span><textarea name="note" minlength="12" required></textarea></label><div class="dialog-footer"><button type="button" class="button" data-action="close-dialog">取消</button><button class="button primary">记录并检查解除</button></div></form>`);return;}
    let result;
    if(action==='com-open-account'){result=await this.request(`/api/community/accounts/${id}/open`,{});this.syncChecks.delete(id);}
    else if(action==='com-check'){
      this.toast('正在检查账号身份…');result=await this.request(`/api/community/accounts/${id}/check`,{});
      this.syncChecks.set(id,{at:this.clock(),version:result.account.version,status:'verified',message:result.message});
    }
    else if(action==='com-open-job')result=await this.request(`/api/community/jobs/${id}/open`,{});
    else if(['com-launch','com-pause','com-resume','com-cancel'].includes(action))result=await this.request(`/api/community/posts/${id}/${action.slice(4)}`,{});
    if(result){this.toast(result.message);await this.fresh();}
  }
  async submit(form,submitter){
    const fd=new FormData(form),id=form.dataset.id;let result;
    if(form.id==='com-filter'){this.region=String(fd.get('region')||'');this.query=String(fd.get('query')||'');await this.render();return;}
    if(form.id==='com-account-form'){
      const body=Object.fromEntries(fd);body.platform=form.elements.platform.value;body.enabled=body.enabled==='true';
      result=await this.request('/api/community/accounts'+(id?'/'+id:''),body,id?'PUT':'POST');this.tab='accounts';
    } else if(form.id==='com-delete-account-form'){
      result=await this.request(`/api/community/accounts/${id}?version=${encodeURIComponent(form.dataset.version)}`,{},'DELETE');
      this.syncChecks.delete(id);this.tab='accounts';
    } else if(form.id==='com-post-form'){
      result=await this.request('/api/community/posts'+(id?'/'+id:''),communityPayload(fd),id?'PUT':'POST');
      // Persist returned ID before launch; launch failure must not create a second draft.
      form.dataset.id=result.id;
      if(submitter?.value==='launch')result=await this.request(`/api/community/posts/${result.id}/launch`,{});
      this.tab=fd.get('kind')==='reply'?'replies':'posts';
    } else if(form.id==='com-record-form')result=await this.request(`/api/community/jobs/${id}/record`,{url:fd.get('url')});
    else if(form.id==='com-resolve-form')result=await this.request(`/api/community/jobs/${id}/resolve`,Object.fromEntries(fd));
    else if(form.id==='com-risk-form')result=await this.request(`/api/community/risk/${id}/clear`,{note:fd.get('note')});
    this.dialog.close();this.toast(result?.message||'社区账号已保存');await this.fresh();
  }
}
