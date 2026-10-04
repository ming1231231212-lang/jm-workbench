import test from 'node:test';
import assert from 'node:assert/strict';
import {communityPayload,communityPage,CommunityUI} from '../jm_workbench/web/static/community.js';
import {dailyPage,dailyAction} from '../jm_workbench/web/static/community-daily.js';

test('daily overview distinguishes planned submitted waiting and shortage',()=>{
 const html=dailyPage({plans:[{id:'p',state:'enabled',payload:{name:'<script>name',hour:10,minute:0,board:'ai工具',topics:[],replies:[],reply_rules:[]},remaining_topics:2,remaining_replies:3,message:'合适目标不足',days:[{day:'2026-10-03',message:'计划已安排',counts:{thread:{submitted:1,waiting:0,failed:0},reply:{submitted:0,waiting:5,failed:0}}}]}]});
 assert.match(html,/已提交 1\/1/);assert.match(html,/已提交 0\/5/);assert.match(html,/等待 5/);assert.match(html,/合适目标不足/);assert.ok(!html.includes('<script>'));
});

test('daily pause targets the exact plan',async()=>{
 const calls=[];await dailyAction({data:{plans:[{id:'p'}]},request:async(...args)=>{calls.push(args);return {message:'paused'};},toast:()=>{},fresh:async()=>{}},'com-plan-pause','p');
 assert.equal(calls[0][0],'/api/community/plans/p/pause');
});

test('community targets retain destination and schedule',()=>{
 const fd=new FormData();
 for(const [k,v] of Object.entries({request_id:'request-123',title:'  测试标题  ',body:'正文',mode:'now',account_ids:'one',destination_one:'人工智能'}))fd.append(k,v);
 const value=communityPayload(fd);
 assert.deepEqual(value.targets,[{account_id:'one',destination:'人工智能'}]);
 assert.equal(value.title,'测试标题');assert.equal(value.schedule_at,0);
});

test('invalid account selection and scheduling rejected',()=>{
 const fd=new FormData();assert.throws(()=>communityPayload(fd),/账号/);
 fd.append('account_ids','one');fd.append('mode','scheduled');fd.append('schedule','bad');assert.throws(()=>communityPayload(fd),/未来/);
});

const platform={id:'tieba',name:'百度贴吧',categories:'AI 互联网',region:'国内',mode:'browser',mode_label:'浏览器发布',automatic:true,format:'主题帖',note:'需登录'};
test('replies have a separate view with original target and full escaped body',()=>{
 const data={platforms:[platform],accounts:[],risk:[],posts:[{id:'reply',created:1,state:'draft',payload:{kind:'reply',title:'评论说明',body:'内容<script>unsafe</script>',source_title:'原始问题',targets:[{destination:'https://tieba.baidu.com/p/123456'}]},jobs:[]}]};
 const html=communityPage(data,'replies');assert.match(html,/原始问题/);assert.match(html,/内容&lt;script&gt;/);
 assert.ok(!communityPage(data,'posts').includes('内容&lt;script&gt;'));
});
test('community rendering escapes untrusted titles and messages',()=>{
 const data={platforms:[platform],accounts:[],risk:[],posts:[{id:'p',state:'active',created:1,payload:{title:'<img src=x onerror=alert(1)>',targets:[{}]},jobs:[{id:'j',platform:'tieba',account_name:'<script>',destination:'AI',state:'unknown',message:'<iframe>',receipt:{}}]}]};
 const output=communityPage(data);
 assert.ok(!output.includes('<script>'));assert.ok(!output.includes('<iframe>'));assert.ok(output.includes('&lt;img'));
 assert.ok(output.includes('结果不明'));assert.ok(!output.includes('已发布'));
});
test('platform filtering preserves true capability labels',()=>{
 const data={platforms:[platform,{...platform,id:'hackernews',name:'Hacker News',region:'国外',mode:'manual',mode_label:'仅本人网页发布'}],accounts:[],risk:[],posts:[]};
 const output=communityPage(data,'platforms','国内','AI');assert.ok(output.includes('百度贴吧'));assert.ok(!output.includes('<b>Hacker News</b>'));
});

test('automatic Tieba sync is throttled and does not touch API or disabled accounts',async()=>{
 let now=100000,calls=[];
 const accounts=[{id:'one',platform:'tieba',enabled:true},{id:'two',platform:'dev',enabled:true},{id:'three',platform:'tieba',enabled:false}];
 const ui=new CommunityUI({clock:()=>now,request:async(path)=>{
   calls.push(path);
   return path.endsWith('/state')?{accounts:structuredClone(accounts)}:{status:'verified',account:{...accounts[0],identity:'123',checked:100},message:'已同步'};
 }});
 const first=await ui.load();assert.equal(first.accounts[0].identity,'123');
 await ui.load();assert.equal(calls.filter(p=>p.endsWith('/sync')).length,1);
 now+=30001;await ui.load();assert.equal(calls.filter(p=>p.endsWith('/sync')).length,2);
 assert.ok(!calls.some(p=>/two\/sync|three\/sync|launch|open/.test(p)));
});

test('pending sync stays visible without blocking the rest of the community page',async()=>{
 const ui=new CommunityUI({request:async(path)=>path.endsWith('/state')?{accounts:[{id:'one',platform:'tieba',enabled:true}]}:{status:'pending',message:'等待贴吧登录'}});
 const data=await ui.load();assert.equal(data.accounts[0].sync_status,'pending');assert.equal(data.accounts[0].sync_message,'等待贴吧登录');
 const output=communityPage({...data,platforms:[platform],risk:[],posts:[]},'accounts');
 assert.ok(output.includes('等待贴吧登录'));assert.ok(!output.includes('已登录 · 已同步'));
});

test('sync network failure preserves the account list and is not retried immediately',async()=>{
 let checks=0;
 const ui=new CommunityUI({request:async(path)=>{if(path.endsWith('/state'))return {accounts:[{id:'one',platform:'tieba',enabled:true}]};checks++;throw Error('connection failed');}});
 assert.equal((await ui.load()).accounts.length,1);await ui.load();assert.equal(checks,1);
});

test('same-name accounts have separate delete targets',()=>{
 const accounts=['one','two'].map(id=>({id,platform:'tieba',name:'同名账号',enabled:true}));
 const html=communityPage({platforms:[platform],accounts,posts:[],risk:[]},'accounts');
 assert.match(html,/data-action="com-delete-account" data-id="one"/);
 assert.match(html,/data-action="com-delete-account" data-id="two"/);
});

test('delete opens an escaped, versioned confirmation without sending a request',async()=>{
 let dialog='';const calls=[];
 const ui=new CommunityUI({request:async path=>calls.push(path),showForm:html=>dialog=html});
 ui.data={platforms:[platform],accounts:[{id:'two',version:4,platform:'tieba',name:'<script>bad</script>',identity_hint:'重复账号',identity:''}]};
 await ui.handle('com-delete-account','two');
 assert.equal(calls.length,0);assert.match(dialog,/com-delete-account-form/);assert.match(dialog,/data-version="4"/);
 assert.match(dialog,/重复账号/);assert.match(dialog,/尚未核验登录/);assert.ok(!dialog.includes('<script>'));
 assert.match(dialog,/close-dialog/);assert.match(dialog,/确认删除/);
});


test('Juejin compose keeps Chinese tags separate from DEV tags',()=>{
 const fd=new FormData();for(const [k,v] of Object.entries({request_id:'juejin-request',title:'掘金标题',body:'AI辅助整理',account_ids:'jj',destination_jj:'人工智能',platform_tags:'人工智能，AI编程',tags:'ai'}))fd.append(k,v);
 const result=communityPayload(fd);assert.deepEqual(result.platform_tags,['人工智能','AI编程']);assert.deepEqual(result.tags,['ai']);
});

test('Juejin daily cards show category and article tags without Tieba suffix',()=>{
 const html=dailyPage({plans:[{id:'p',platform:'juejin',state:'enabled',payload:{name:'掘金计划',hour:10,minute:0,board:'人工智能',topics:[{title:'主题',body:'正文',platform_tags:['AI编程']}],replies:[],reply_rules:[]},remaining_topics:1,remaining_replies:0,message:'缺口',days:[]}]});
 assert.match(html,/掘金 · 分类：人工智能/);assert.match(html,/标签：AI编程/);assert.ok(!html.includes('人工智能吧'));
});

test('Juejin account synchronization is limited to once per five minutes',async()=>{
 let now=1000000,checks=0;const ui=new CommunityUI({clock:()=>now,request:async path=>{if(path.endsWith('/state'))return {accounts:[{id:'jj',platform:'juejin',enabled:true,version:1}]};checks++;return {status:'verified'};}});
 await ui.load();now+=30001;await ui.load();assert.equal(checks,1);now+=300000;await ui.load();assert.equal(checks,2);
});
