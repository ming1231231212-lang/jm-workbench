import test from 'node:test';
import assert from 'node:assert/strict';
import {escape,button} from '../jm_workbench/web/static/ui.js';
import * as views from '../jm_workbench/web/static/views.js';
const s={accounts:[],tasks:[],bindings:[],runs:[],counts:{},attempt_counts:{},history_count:0,risk:[],events:[],platforms:[{id:'ks',name:'快手',crawler:true,comment:true}],settings:{},defaults:{}};
test('untrusted data cannot produce executable HTML',()=>{
  assert.equal(escape('<img src=x onerror="alert(1)">'),'&lt;img src=x onerror=&quot;alert(1)&quot;&gt;');
  const html=views.tasks({...s,tasks:[{id:'x',name:'<script>alert(1)</script>',kind:'crawler',platform:'ks',enabled:true,keywords:['<img>'],max_items:1}]});
  assert.ok(!html.includes('<script>'));assert.ok(!html.includes('<img>'));
});
test('dialog action buttons never submit form implicitly',()=>assert.ok(button('取消','close-dialog').includes('type="button"')));
test('all eight modules provide meaningful empty states',()=>{
  for(const name of ['overview','tasks','accounts','matrix','platforms','runs','settings'])assert.ok(views[name](s).length>100);
  assert.ok(views.data(s,{items:[],total:0,page:1}).includes('没有符合条件的数据'));
});
test('matrix disables incompatible platform bindings',()=>{
  const html=views.matrix({...s,accounts:[{id:'a',name:'a',platform:'dy',enabled:true}],tasks:[{id:'t',name:'t',platform:'ks',enabled:true,kind:'crawler'}]});
  assert.ok(html.includes('平台不匹配'));assert.ok(!html.includes('data-binding="true"'));
});
