import test from 'node:test';
import assert from 'node:assert/strict';
import {communityPayload,communityPage,CommunityUI} from '../jm_workbench/web/static/community.js';

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
