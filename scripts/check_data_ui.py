"""Read-only Chrome acceptance for classified data and current comment previews."""
import argparse
import json
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from jm_workbench.adapters.chrome import endpoint


def main(profile, port=8777):
    root=Path(__file__).resolve().parents[1]
    url=f'http://127.0.0.1:{port}'
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    for i in range(20):
        try:
            with opener.open(url+'/api/health',timeout=1) as response:
                assert json.load(response)['app_id']=='jm-workbench'
            break
        except OSError:
            if i==19:raise
            time.sleep(.5)
    checks,errors=[],[]
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp(endpoint(profile),timeout=30000)
        context=browser.contexts[0]
        page=context.new_page()
        page.on('pageerror',lambda ex:errors.append(str(ex)))
        page.set_viewport_size({'width':1440,'height':1100})
        page.goto(url+'/#data',wait_until='networkidle')
        page.get_by_role('heading',name='数据中心',exact=True).wait_for()
        initial=page.evaluate("async()=>await(await fetch('/api/state')).json()")
        latest=page.evaluate("async()=>await(await fetch('/api/data?batch=latest')).json()")
        merchants=page.evaluate("async()=>await(await fetch('/api/data?batch=latest&category=merchant')).json()")
        sample_name=merchants['items'][0]['data']['nickname']
        sample_result=page.evaluate("async name=>await(await fetch('/api/data?batch=latest&q='+encodeURIComponent(name))).json()",sample_name)
        summary=latest['summary']
        assert page.locator('[name=batch]').input_value()=='latest'
        checks.append('latest batch is the default')
        assert [int(v.split('条')[0]) for v in page.locator('.data-summary article b').all_text_contents()]==[summary[k] for k in ['records','unique','duplicates','content_matches']]
        checks.append('raw, unique, duplicate and content counts are distinct')
        for cfg in latest['comment_templates']:
            for text in cfg['templates']:
                expect(page.locator('.template-card blockquote').filter(has_text=text)).to_be_visible()
        checks.append('both comments come from current task configuration')
        for category in ['merchant','discussion','other','insufficient','inventory']:
            page.locator(f'[data-action="filter-category"][data-id="{category}"]').click()
            expect(page.locator(f'[data-action="filter-category"][data-id="{category}"]')).to_have_attribute('aria-pressed','true')
            count=next(c['count'] for c in summary['categories'] if c['id']==category)
            assert page.locator('.data-list article').count()==min(count,30)
            if count:
                assert page.locator('.comment-result').count()==min(count,30)
            checks.append(category+' filter and reasons match')
        page.locator('[data-id="merchant"][data-action="filter-category"]').click()
        expect(page.locator('[data-id="merchant"][data-action="filter-category"]')).to_have_attribute('aria-pressed','true')
        assert not page.locator('#content [data-action="launch"]').count()
        for link in page.locator('.data-title a').all():
            assert link.get_attribute('href').startswith('https://www.kuaishou.com/short-video/')
        checks.append('exact video links, no publish action in discovery results')
        page.get_by_text('查看完整采集字段',exact=True).first.click()
        assert page.locator('.data-list details[open] pre').first.is_visible()
        checks.append('raw evidence retained under details')
        page.screenshot(path=str(root/'outputs'/'数据分类-桌面.png'),full_page=True)
        page.locator('[data-action="filter-category"][data-id=""]').click()
        page.locator('[name=batch]').select_option('legacy')
        page.get_by_role('button',name='查询',exact=True).click()
        legacy_count=next(b['records'] for b in latest['batches'] if b['run_id']=='legacy')
        expect(page.locator('.data-summary article b').first).to_have_text(str(legacy_count)+'条')
        checks.append('history is explicitly selected instead of mixed into latest results')
        page.locator('[name=batch]').select_option('latest')
        page.get_by_role('button',name='查询',exact=True).click()
        expect(page.locator('.data-summary article b').first).to_have_text(str(summary['records'])+'条')
        page.locator('[name=q]').fill(sample_name)
        page.get_by_role('button',name='查询',exact=True).click()
        expect(page.locator('.data-list article')).to_have_count(min(sample_result['total'],30))
        checks.append('search works with classified deduplicated latest batch')
        with page.expect_download() as download:
            page.locator('a[href="/api/export"]').click()
        target=root/'outputs'/'classified-data-export.csv'
        download.value.save_as(target)
        assert '业务分类' in target.read_text(encoding='utf-8-sig').splitlines()[0]
        checks.append('CSV includes business classification')
        page.set_viewport_size({'width':390,'height':844})
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(root/'outputs'/'数据分类-手机.png'),full_page=True)
        checks.append('mobile layout has no horizontal overflow')
        final=page.evaluate("async()=>await(await fetch('/api/state')).json()")
        for key in ['tasks','bindings','attempt_counts','runs']:
            assert initial[key]==final[key],key
        assert not errors
        checks.append('viewing and filtering never alter tasks, queues or attempts')
        page.close()
    report={'passed':len(checks),'checks':checks,'console_errors':errors,'summary':summary,'port':port}
    (root/'outputs'/f'data_ui_acceptance_{port}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('profile')
    parser.add_argument('--port',type=int,default=8777)
    args=parser.parse_args()
    main(args.profile,args.port)
