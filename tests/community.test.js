import test from 'node:test';
import assert from 'node:assert/strict';
import {communityPayload,communityPage} from '../jm_workbench/web/static/community.js';

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
