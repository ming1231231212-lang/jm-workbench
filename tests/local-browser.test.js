import test from 'node:test';
import assert from 'node:assert/strict';
import { installLocalBrowserLinks } from '../jm_workbench/web/static/local-browser.js';

function harness(request) {
  const handlers={}, messages=[], calls=[];
  const root={baseURI:'http://127.0.0.1:8776/',addEventListener:(name,fn)=>handlers[name]=fn};
  installLocalBrowserLinks(root,request || (async(...args)=>{calls.push(args);return {message:'opened'};}),(...args)=>messages.push(args));
  async function click(href,target='_blank',type='click',button=0,download=false){
    let prevented=false;
    const link={target,getAttribute:()=>href,hasAttribute:()=>download};
    await handlers[type]({type,button,target:{closest:()=>link},preventDefault:()=>prevented=true});
    return prevented;
  }
  return {click,calls,messages};
}
test('external links, localhost SAU, nested targets and middle clicks route through backend',async()=>{
  const h=harness();
  assert.equal(await h.click('https://juejin.cn/post/123'),true);
  assert.equal(await h.click('http://127.0.0.1:5409/#/account-management'),true);
  assert.equal(await h.click('https://tieba.baidu.com/','','auxclick',1),true);
  assert.equal(h.calls.length,3);assert.equal(h.calls[0][0],'/api/browser/open');
});
test('internal navigation, downloads and right clicks stay native',async()=>{
  const h=harness();
  assert.equal(await h.click('#community'),false);
  assert.equal(await h.click('/api/export',''),false);
  assert.equal(await h.click('https://example.com','','auxclick',2),false);
  assert.equal(await h.click('/download','_blank','click',0,true),false);
  assert.equal(h.calls.length,0);
});
test('failed launch is visible with no browser fallback',async()=>{
  const h=harness(async()=>{throw Error('Chrome unavailable');});
  assert.equal(await h.click('https://tieba.baidu.com/'),true);
  assert.deepEqual(h.messages,[['Chrome unavailable',true]]);
});
