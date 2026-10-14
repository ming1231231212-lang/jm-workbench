import test from 'node:test';
import assert from 'node:assert/strict';
import {parseRoute,navigation,overview} from '../jm_workbench/web/static/novice.js';
import {pages} from '../jm_workbench/web/static/views.js';
import {routeIcons} from '../jm_workbench/web/static/workspace.js';
import {fetchWithDeadline} from '../jm_workbench/web/static/network.js';
test('first visit and old community links land on today; existing tool links survive',()=>{
  assert.deepEqual(parseRoute('',pages),{page:'community',tab:'overview'});
  assert.equal(parseRoute('#community/content',pages).tab,'content');
  assert.equal(parseRoute('#community/bogus',pages).tab,'overview');
  for(const p of pages) assert.equal(parseRoute('#'+p[0],pages).page,p[0]);
});
test('one active navigation item; tools remain discoverable',()=>{
  const html=navigation('community','accounts',pages,routeIcons);
  assert.equal((html.match(/aria-current="page"/g)||[]).length,1);
  assert.ok(html.includes('更多工具')&&html.includes('#publishing')&&html.includes('#data'));
});
test('today uses complete server counts; history missing targets are actionable and escaped',()=>{
  const html=overview({summary:{day:'2026-10-12',thread_submitted:2},queue_counts:{queued:15,unknown:1},
    executor:{status:'ready',message:'后台就绪'},posts:[],plans:[],risk:[{platform:'tieba',reason:'<script>bad</script>'}],
    backfill:{total:78,submitted:2,items:[{status:'missing_target'}]}});
  assert.ok(html.includes('15<small>项')&&html.includes('2 / 78'));
  assert.ok(html.includes('1条历史评论缺少合适原帖'));
  assert.ok(!html.includes('<script>bad'));
  assert.ok(html.includes('com-backfill-toggle')&&html.includes('公开可见性'));
});
test('stopped worker never claims automatic execution is ready',()=>{
  const html=overview({executor:{status:'stopped',message:'后台未启动'},posts:[],plans:[]});
  assert.ok(html.includes('后台未启动')&&html.includes('网页能打开不代表'));
});

test('today distinguishes web registrations from receipts and automatic supply from manual shortage',()=>{
  const html=overview({summary:{day:'2026-10-14',platform_results:{zhihu:{thread_recorded:1,reply_recorded:5}}},
    accounts:[{id:'a',enabled:true,identity:'owner',checked:1}],platforms:[{id:'zhihu',name:'知乎',automatic:true}],risk:[],posts:[],
    plans:[{id:'p',platform:'zhihu',state:'enabled',remaining_topics:0,payload:{name:'每日安排',account_id:'a',auto_prepare:true},preparations:[{message:'等待相关原帖'}]}]});
  assert.ok(html.includes('网页结果已登记：帖子 1 篇 · 评论 5 条'));
  assert.ok(html.includes('自动准备已开启')&&!html.includes('需要补充帖子'));
  assert.ok(html.includes('今日帖子 <b>1</b>')&&html.includes('已接收 / 网页已登记')); // The subtype remains explicit.
});
test('read and write timeouts explain uncertainty differently without retries',async()=>{
  let calls=0;
  const hanging=async (path,opts)=>{calls++;return new Promise((resolve,reject)=>opts.signal.addEventListener('abort',()=>reject(Error('aborted'))));};
  await assert.rejects(fetchWithDeadline('/state',{},hanging,10),/读取状态超时/);
  await assert.rejects(fetchWithDeadline('/publish',{method:'POST'},hanging,10),/不要重复提交/);
  assert.equal(calls,2);
});
