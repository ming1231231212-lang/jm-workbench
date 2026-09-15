import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const ctx = {module:{exports:{}},URL};
vm.runInNewContext(fs.readFileSync(new URL('../jm_workbench/adapters/extract.js',import.meta.url),'utf8'),ctx);
const extract=ctx.module.exports;
const vid = '3xvideo000001', author = '3xauthor00001';
const feed = {photo:{id:vid,caption:'成人用品库存清仓'},author:{id:author,name:'某店'},canAddComment:true};
// Captured from the actual 2026-09-15 page; do not generate fixture keys using production logic.
const key = 'tusjoh.0sftu0w0tfbsdi0gffe-pckfdu.lfzxpse.uvtkpi\\u002F戒亼甪哃局贩.qbhf.uvtkpi\\u002Fugctej.qdvstps.uvtkpi\\u002F.xfcQbhfBsfb.uvtkpi\\u002F';
const url='https://www.kuaishou.com/search/video?searchKey='+encodeURIComponent('成人用品尾货');
const detailKey='visionVideoDetail({"page":"detail","photoId":"'+vid+'"})';
const detailState = () => ({defaultClient:{ROOT_QUERY:{[detailKey]:{type:'id',id:'detail'}},detail:{status:1,photo:{type:'id',id:'photo'},author:{type:'id',id:'author'},commentLimit:{type:'id',id:'limit'}},photo:feed.photo,author:feed.author,limit:{canAddComment:0},unrelated:{id:'3xwrongauthor'}}});
test('only matching search response, no recommendations',()=>{
 const r=extract.search({[key]:{result:1,feeds:[feed]},recommendations:[{photo:{id:'wrong'}}]}, {},url,'成人用品尾货');
 assert.equal(r.rows.length,1);assert.equal(r.rows[0].video_id,vid);
});
test('second real keyword cache key',()=>{
 const k='tusjoh.0sftu0w0tfbsdi0gffe-pckfdu.lfzxpse.uvtkpi\\u002F戒亼甪哃底孚夆琈.qbhf.uvtkpi\\u002Fugctej';
 assert.equal(extract.search({[k]:{result:1,feeds:[feed]}},{},'https://www.kuaishou.com/search/video?searchKey='+encodeURIComponent('成人用品库存处理'),'成人用品库存处理').rows.length,1);
});
test('wrong search page cannot label items with new keyword',()=>assert.throws(()=>extract.search({[key]:{result:1,feeds:[feed]}},{},url,'成人用品店')));
test('wrong domain rejected',()=>assert.throws(()=>extract.search({}, {},url.replace('www.kuaishou.com','www.kuaishou.com.attacker.test'),'成人用品尾货')));
test('query state mismatch rejected',()=>assert.throws(()=>extract.search({recommendations:[feed]}, {},url,'成人用品尾货')));
test('failed search is not empty success',()=>assert.throws(()=>extract.search({[key]:{result:50,feeds:[]}}, {},url,'成人用品尾货')));
test('author follows exact video detail references',()=>{
 const r=extract.detail(detailState(),'https://www.kuaishou.com/short-video/'+vid,vid);
 assert.equal(r.author_id,author);assert.equal(r.video_id,vid);assert.equal(r.can_comment,true);
});
test('different returned photo must reject',()=>{
 const s=detailState();s.defaultClient.photo={id:'wrong'};
 assert.throws(()=>extract.detail(s,'https://www.kuaishou.com/short-video/'+vid,vid));
});
test('automatic next-video navigation invalidates the target',()=>assert.throws(()=>extract.detail(detailState(),'https://www.kuaishou.com/short-video/3xanother0001',vid)));
test('missing comment permission does not default true',()=>{
 const s=detailState();s.defaultClient.limit={};assert.equal(extract.detail(s,'https://www.kuaishou.com/short-video/'+vid,vid).can_comment,false);
});
test('official friends-only enum 1 is blocked, not truthy allowed',()=>{
 const s=detailState();s.defaultClient.limit={canAddComment:1};assert.equal(extract.detail(s,'https://www.kuaishou.com/short-video/'+vid,vid).can_comment,false);
});
test('unknown permission enums and booleans fail closed',()=>{
 for(const v of [2,-1,true,'0']){const s=detailState();s.defaultClient.limit={canAddComment:v};assert.equal(extract.detail(s,'https://www.kuaishou.com/short-video/'+vid,vid).can_comment,false);}
});
test('unrelated author id cannot be login id',()=>assert.throws(()=>extract.account({},detailState())));
test('current profile ID only',()=>assert.equal(extract.account({'tusjoh.0sftu0w0qspgjmf0hfu-pckfdu.':{result:1,eid:'self-account',userName:'self'}},{}).id,'self-account'));
