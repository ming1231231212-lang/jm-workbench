"""Real Chrome UI acceptance against an explicitly disabled-worker instance."""
import json
import sys
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from jm_workbench.adapters.chrome import endpoint

def main():
    root=Path(__file__).resolve().parents[1]
    base='http://127.0.0.1:8777'
    profile=sys.argv[1]
    result={'checks':[], 'console_errors':[]}
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for attempt in range(20):
        try:
            with opener.open(base+'/api/health',timeout=1) as response:
                assert json.load(response)['worker'] is False
            break
        except OSError:
            if attempt==19:raise
            time.sleep(.5)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(profile),timeout=30000)
        context=browser.contexts[0]
        page=context.new_page()
        page.on('pageerror',lambda err:result['console_errors'].append(str(err)))
        page.set_viewport_size({'width':1440,'height':1100})
        page.goto(base,wait_until='networkidle')
        assert page.evaluate("async()=> (await (await fetch('/api/health')).json()).worker") is False
        before=page.evaluate("async()=> (await (await fetch('/api/attempts')).json()).length")
        page.get_by_role('heading',name='工作概览',exact=True).wait_for()
        result['checks'].append('overview brand and API loaded')
        for slug,title in [('matrix','任务矩阵'),('tasks','任务配置'),('accounts','账号管理'),('platforms','平台接入'),('data','数据中心'),('runs','运行记录'),('settings','工作台设置')]:
            page.locator(f'#nav a[href="#{slug}"]').click()
            page.get_by_role('heading',name=title,exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            result['checks'].append(slug+' desktop no overflow')
        page.locator('#nav a[href="#accounts"]').click()
        page.get_by_role('button',name='+ 添加账号',exact=True).click()
        page.locator('#account-form [name="name"]').fill('验收抖音账号')
        page.locator('#account-form [name="platform"]').select_option('dy')
        page.get_by_role('button',name='保存账号',exact=True).click()
        page.get_by_role('heading',name='验收抖音账号').wait_for()
        result['checks'].append('account create persisted from dialog')
        page.locator('#nav a[href="#tasks"]').click()
        page.get_by_role('button',name='+ 新建任务',exact=True).click()
        page.locator('#task-form [name="kind"]').select_option('crawler')
        page.locator('#task-form [name="name"]').fill('验收抖音采集')
        page.locator('#task-form [name="platform"]').select_option('dy')
        page.locator('#task-form [name="keywords"]').fill('收尾货')
        page.get_by_role('button',name='保存任务',exact=True).click()
        page.get_by_role('heading',name='验收抖音采集').wait_for()
        result['checks'].append('crawler task create persisted')
        page.locator('#nav a[href="#matrix"]').click()
        cell=page.get_by_role('checkbox',name='验收抖音账号 执行 验收抖音采集',exact=True)
        cell.check()
        page.wait_for_timeout(500)
        assert cell.is_checked()
        result['checks'].append('matrix binding persisted')
        cell.uncheck()
        page.wait_for_timeout(500)
        page.locator('#nav a[href="#tasks"]').click()
        card=page.locator('.task-card').filter(has=page.get_by_role('heading',name='验收抖音采集',exact=True))
        card.get_by_role('button',name='编辑',exact=True).click()
        page.locator('#task-form [name="keywords"]').fill('测试修改关键词')
        page.get_by_role('button',name='保存任务',exact=True).click()
        page.get_by_text('测试修改关键词',exact=True).wait_for()
        result['checks'].append('task edit roundtrip')
        page.locator('#nav a[href="#accounts"]').click()
        main=page.locator('.account-card').filter(has=page.get_by_role('heading',name='快手主账号',exact=True))
        main.get_by_role('button',name='检查连接',exact=True).click()
        page.get_by_text('登录已核验',exact=True).wait_for(timeout=45000)
        # An already verified account has the same badge before this request.
        # Wait for the asynchronous check AND refresh to release the action button.
        expect(main.get_by_role('button',name='检查连接',exact=True)).to_be_enabled(timeout=45000)
        result['checks'].append('actual selected Chrome account check via fetch without deadlock')
        page.locator('.topbar [data-action="launch"]').click()
        page.get_by_role('status').filter(has_text='已加入').wait_for(timeout=15000)
        page.locator('#nav a[href="#runs"]').click()
        page.get_by_text('排队中',exact=True).first.wait_for()
        result['checks'].append('one-click queues configured comment bindings without real execution')
        page.locator('.topbar [data-action="stop"]').click()
        page.get_by_role('status').filter(has_text='已停止任务').wait_for()
        page.get_by_text('已停止',exact=True).first.wait_for()
        result['checks'].append('stop all persists')
        page.locator('#nav a[href="#data"]').click()
        page.locator('[name="q"]').fill('成人用品')
        page.get_by_role('button',name='查询',exact=True).click()
        page.wait_for_timeout(400)
        assert page.locator('.data-list article').count()>0
        page.get_by_text('查看完整采集字段',exact=True).first.click()
        assert page.locator('details[open] pre').first.is_visible()
        result['checks'].append('search data and inspect evidence')
        with page.expect_download() as download:
            page.get_by_role('link',name='↓ 导出CSV').click()
        download.value.save_as(root/'outputs'/'ui-export.csv')
        result['checks'].append('CSV downloaded')
        page.locator('#nav a[href="#overview"]').click()
        page.get_by_role('heading',name='工作概览',exact=True).wait_for()
        page.locator('#toast').evaluate('(el)=>el.hidden=true')
        page.screenshot(path=str(root/'outputs'/'JM桌面验收.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        for slug,title in [('overview','工作概览'),('matrix','任务矩阵'),('tasks','任务配置'),('accounts','账号管理'),('platforms','平台接入'),('data','数据中心'),('runs','运行记录'),('settings','工作台设置')]:
            page.locator(f'#nav a[href="#{slug}"]').click()
            page.get_by_role('heading',name=title,exact=True).wait_for()
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),slug
            result['checks'].append(slug+' mobile no overflow')
        page.locator('#nav a[href="#overview"]').click()
        page.get_by_role('heading',name='工作概览',exact=True).wait_for()
        page.screenshot(path=str(root/'outputs'/'JM手机验收.png'),full_page=True)
        after=page.evaluate("async()=> (await (await fetch('/api/attempts')).json()).length")
        assert after==before==0
        result['checks'].append('zero real comment attempts throughout UI test')
        assert not result['console_errors'],result['console_errors']
        page.close()
    result['passed']=len(result['checks'])
    (root/'outputs'/'ui_acceptance.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
