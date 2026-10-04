"""Isolated Chrome acceptance. Uses a fake SAU and never starts platform workers."""
import copy
import json
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import uvicorn
from playwright.sync_api import sync_playwright, expect
from jm_workbench.web.app import create_app
from jm_workbench.adapters.chrome import endpoint


def main():
    output=ROOT/'outputs'/('publishing-acceptance-'+time.strftime('%Y%m%d-%H%M%S'))
    output.mkdir(parents=True)
    sample=output/'acceptance.mp4'
    subprocess.run([shutil.which('ffmpeg'),'-hide_banner','-loglevel','error','-f','lavfi','-i','color=c=0x24745b:s=320x240:d=2','-c:v','libx264','-pix_fmt','yuv420p',str(sample)],check=True,creationflags=subprocess.CREATE_NO_WINDOW)
    class Fake:
        fail=False
        sent=[]
        def catalog(self):
            return {'accounts':[{'id':f'sau:{i}','name':f'测试{label}账号','platform':platform,'status':'recorded','_key':f'qa-{i}','_file':f'qa-{i}.json'} for i,(platform,label) in enumerate([('ks','快手'),('dy','抖音'),('xhs','小红书'),('tencent','视频号')],1)],'materials':[]}
        def upload(self,path):return 'qa-only.mp4'
        def publish(self,account,media,content):
            self.sent.append(copy.deepcopy(content))
            if self.fail:raise TimeoutError('QA uncertain result')
            return {'status':'submitted','message':'模拟提交完成','visibility':'unverified'}
    bridge=Fake();app=create_app(output/'home',worker=False,publishing_bridge=bridge)
    publisher=app.state.publisher
    clock=[time.time()];publisher.clock=lambda:clock[0]
    sock=socket.socket();sock.bind(('127.0.0.1',0));sock.listen(16)
    port=sock.getsockname()[1]
    server=uvicorn.Server(uvicorn.Config(app,log_level='warning'))
    thread=threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True);thread.start()
    for _ in range(100):
        if server.started:break
        time.sleep(.05)
    checks=[];errors=[]
    def check(label,condition=True):
        assert condition,label
        checks.append(label)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(Path(r'D:\Codex\个人工作台\项目\Codex-Chrome\User Data')),timeout=30000)
        context=browser.new_context(accept_downloads=True)
        page=context.new_page();page.set_viewport_size({'width':1440,'height':1000});page.set_default_timeout(12000)
        page.on('pageerror',lambda error:errors.append(str(error)))
        def nav(route):
            page.goto(f'http://127.0.0.1:{port}/#{route}')
            expect(page.locator('#nav a')).to_have_count(6)
            expect(page.locator('#content')).not_to_contain_text('正在连接')
        def refresh():
            page.locator('[data-action="refresh"]').click()
            expect(page.locator('#toast')).to_contain_text('数据已刷新')
        try:
            for route,label in [('tasks','任务'),('publishing','内容发布'),('data','采集数据'),('accounts','账号'),('settings','设置'),('matrix','任务矩阵'),('platforms','平台能力'),('runs','运行记录')]:
                nav(route);expect(page.locator('#content h1')).to_be_visible();check('navigation '+route)
            nav('publishing')
            page.locator('[data-action="pub-new"]').first.click()
            expect(page.locator('#pub-form')).to_be_visible()
            check('four platforms selectable',page.locator('[name="account_ids"]').count()==4)
            page.locator('#pub-form [data-pub-upload]').set_input_files(str(sample))
            expect(page.locator('[name="material_ids"]')).to_have_count(1)
            check('upload auto selected',page.locator('[name="material_ids"]').is_checked())
            page.locator('[name="account_ids"][value="sau:1"]').check()
            page.locator('[name="account_ids"][value="sau:2"]').check()
            page.locator('[name="title"]').fill('浏览器验收：双平台定时发布')
            page.locator('[name="tags"]').fill('经营 分享')
            page.locator('[name="mode"]').select_option('scheduled')
            expect(page.locator('[name="schedule"]')).to_be_visible()
            page.locator('[name="submit_mode"][value="draft"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            expect(page.locator('.publication-table')).to_contain_text('本地草稿')
            check('save local draft without publication',not bridge.sent)
            page.reload();expect(page.locator('.publication-table')).to_contain_text('浏览器验收')
            check('draft persists through reload')
            page.locator('[data-action="pub-edit"]').click()
            expect(page.locator('[name="title"]')).to_have_value('浏览器验收：双平台定时发布')
            page.locator('[name="submit_mode"][value="launch"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            check('scheduled multi account jobs',len(publisher.batches()[0]['jobs'])==2)
            publisher.tick();check('does not send early',not bridge.sent)
            page.locator('[data-action="pub-pause"]').click()
            expect(page.locator('.publication-table')).to_contain_text('已暂停')
            publisher.tick();check('pause prevents execution',not bridge.sent)
            page.locator('[data-action="pub-resume"]').click()
            expect(page.locator('.publication-table')).to_contain_text('等待执行')
            clock[0]+=7200
            publisher.tick();publisher.tick();refresh()
            check('two platform fake submissions',len(bridge.sent)==2)
            expect(page.locator('.publication-table')).to_contain_text('已提交 · 未核验')
            page.locator('[data-action="pub-detail"]').first.click()
            expect(page.locator('.publish-job')).to_have_count(2)
            check('per account receipts visible')
            page.locator('[data-action="close-dialog"]').first.click()
            page.locator('[data-pub-filter]').select_option('unknown')
            expect(page.locator('.publication-table')).to_contain_text('没有这个状态的任务')
            page.locator('[data-pub-filter]').select_option('all');check('state filters')
            page.screenshot(path=str(output/'desktop-publishing.png'),full_page=True)
            page.locator('[data-action="pub-tab"][data-id="materials"]').click()
            page.locator('[data-action="pub-preview"]').click()
            expect(page.locator('video')).to_be_visible()
            page.wait_for_function('document.querySelector("video").readyState >= 1')
            check('real uploaded video preview')
            page.locator('[data-action="close-dialog"]').click()
            page.locator('[data-action="pub-use"]').click()
            page.locator('[name="account_ids"][value="sau:3"]').check()
            page.locator('[name="title"]').fill('异常回执验收')
            page.locator('[name="submit_mode"][value="launch"]').click()
            expect(page.locator('#dialog')).not_to_be_visible()
            bridge.fail=True;publisher.tick()
            page.locator('[data-action="pub-tab"][data-id="batches"]').click()
            expect(page.locator('.publication-table')).to_contain_text('结果不明')
            page.get_by_role('button',name='异常回执验收',exact=True).click()
            page.locator('[data-action="pub-resolve"]').click()
            page.locator('[name="note"]').fill('已在模拟平台作品管理核对并找到本次作品记录')
            page.get_by_role('button',name='记录结果',exact=True).click()
            expect(page.locator('#dialog')).not_to_be_visible()
            check('unknown outcome resolved without retry',len(bridge.sent)==3)
            check('risk remains after outcome record',bool(publisher.store.rows("SELECT * FROM risk WHERE platform='xhs'")))
            page.set_viewport_size({'width':390,'height':844})
            for route in ['tasks','publishing','accounts','settings','data']:
                nav(route)
                check('mobile no page overflow '+route,page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            nav('publishing');page.screenshot(path=str(output/'mobile-publishing.png'),full_page=True)
            page.locator('[data-action="pub-new"]').first.click()
            expect(page.locator('#pub-form')).to_be_visible()
            check('mobile dialog in viewport',page.locator('#dialog').evaluate('(el)=>el.getBoundingClientRect().right<=innerWidth&&el.getBoundingClientRect().left>=0'))
            page.screenshot(path=str(output/'mobile-compose.png'),full_page=True)
            page.locator('[data-action="close-dialog"]').first.click()
            check('no JavaScript errors',not errors)
            (output/'result.json').write_text(json.dumps({'passed':len(checks),'checks':checks,'page_errors':errors,'real_posts':0},ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'passed':len(checks),'output':str(output),'real_posts':0},ensure_ascii=False))
        except BaseException:
            page.screenshot(path=str(output/'failure.png'),full_page=True)
            print(json.dumps({'output':str(output),'completed':checks,'errors':errors},ensure_ascii=False))
            raise
        finally:
            context.close()
            server.should_exit=True;thread.join(5);sock.close()


if __name__=='__main__':main()
