import test from 'node:test';
import assert from 'node:assert/strict';
import { CommunityUI, communityPayload } from '../jm_workbench/web/static/community.js';
import { CommunityWorkspace } from '../jm_workbench/web/static/community-v2.js';
import { commentWorkflow } from '../jm_workbench/web/static/community-v2-model.js';
import { accountsView } from '../jm_workbench/web/static/community-v2-views.js';

const zhihu = {id:'zhihu',name:'知乎',mode:'web',mode_label:'网页发布',automatic:false,destination_hint:'',categories:'AI应用 互联网',region:'国内',capabilities:{comment_draft:true,web_comment:true,auto_comment:false,daily_plan:false}};
const data = {platforms:[zhihu,{id:'quora',name:'Quora',mode:'web',automatic:false}],accounts:[{id:'zh',platform:'zhihu',name:'知乎账号',enabled:true,automatic_execution:false},{id:'unknown',platform:'quora',name:'未接入评论',enabled:true}],posts:[],plans:[],risk:[]};

test('web comment composer includes Zhihu and its original-post field, rejects unknown capabilities', () => {
  let html;
  const ui = new CommunityUI({showForm:value=>{html=value;}});
  ui.data=data;
  ui.compose(null,'reply');
  assert.ok(html.includes('name="destination_zh"'));
  assert.ok(html.includes('原帖HTTPS链接'));
  assert.ok(html.includes('zhuanlan.zhihu.com/p/'));
  assert.ok(!html.includes('value="unknown"'));
});

test('article composer has no invented Zhihu board or automatic sending claim', () => {
  let html;
  const ui = new CommunityUI({showForm:value=>{html=value;}});ui.data=data;
  ui.compose(null,'thread');
  assert.ok(html.includes('value="zh"'));
  assert.ok(!html.includes('name="destination_zh"'));
  assert.ok(html.includes('网页发布需在网站完成最后提交'));
});

test('comment form preserves the specific answer URL and exact body', () => {
  const form=new FormData();
  for(const [key,value] of Object.entries({kind:'reply',request_id:'zhihu-ui-fixture',title:'原帖讨论',body:'针对这一条回答的具体讨论。',account_ids:'zh',destination_zh:'https://www.zhihu.com/question/123456/answer/654321',mode:'now'}))form.append(key,value);
  const payload=communityPayload(form);
  assert.equal(payload.kind,'reply');
  assert.equal(payload.body,'针对这一条回答的具体讨论。');
  assert.deepEqual(payload.targets,[{account_id:'zh',destination:'https://www.zhihu.com/question/123456/answer/654321'}]);
});

test('capability matrix separates webpage comments from unavailable daily automation', () => {
  assert.equal(commentWorkflow(zhihu),'评论：网页发布；每日计划：不可用');
  const html=accountsView(data,{accountMode:'matrix',platform:'',q:''});
  assert.ok(html.includes('添加知乎'));
  assert.ok(html.includes('评论：网页发布；每日计划：不可用'));
  assert.ok(!html.includes('已接入，需账号权限'));
});

test('viewing Zhihu account does not probe extensions or automatic execution', async () => {
  const calls=[];
  const ui=new CommunityWorkspace({request:async path=>{calls.push(path);assert.equal(path,'/api/community/state');return structuredClone(data);}});
  await ui.load();await ui.load();
  assert.deepEqual(calls,['/api/community/state','/api/community/state']);
});


test('native account records render homepage binding without launching a check', () => {
  const native={...zhihu,mode:'native',automatic:true,mode_label:'本机Chrome发布',capabilities:{...zhihu.capabilities,auto_comment:true,daily_plan:true}};
  assert.equal(commentWorkflow(native),'评论：自动发布；每日计划：需账号权限');
  const html=accountsView({...data,platforms:[native],accounts:[{...data.accounts[0],native_binding:{profile_url:'https://www.zhihu.com/people/fixture'},identity:'zhihu:fixture',checked:1}]},{accountMode:'matrix',platform:'',q:''});
  assert.ok(html.includes('本机Chrome发布'));assert.ok(html.includes('评论：自动发布'));
});
