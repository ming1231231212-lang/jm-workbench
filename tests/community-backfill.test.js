import test from 'node:test';
import assert from 'node:assert/strict';
import {backfillView,backfillDetail} from '../jm_workbench/web/static/community-backfill.js';
test('empty history keeps existing UI simple',()=>assert.equal(backfillView({}),''));
test('historical gaps are not shown as completed or assigned fake content',()=>{
 const data={platforms:[{id:'tieba',name:'贴吧'}],posts:[],backfill:{total:1,threads:0,replies:1,with_content:0,submitted:0,items:[{plan_id:'p',day:'2026-10-11',kind:'reply',slot:1,platform:'tieba',status:'missing_target',message:'<script>bad</script>',post_id:''}]}};
 assert.match(backfillView(data),/帖子 0 · 评论 1/);
 const html=backfillDetail(data,'p|2026-10-11');assert.match(html,/待匹配原帖/);assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
 assert.doesNotMatch(html,/data-action=".*launch/);
});
