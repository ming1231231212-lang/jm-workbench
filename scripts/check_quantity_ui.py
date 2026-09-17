"""Validate per-video settings and continuation on a worker-disabled DB copy."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from jm_workbench.adapters.chrome import endpoint


def main(profile, port):
    url = f'http://127.0.0.1:{port}'
    checks, errors = [], []
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(endpoint(profile), timeout=30000)
        page = browser.contexts[0].new_page()
        page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(url+'/') else route.abort())
        page.on('pageerror', lambda ex: errors.append(str(ex)))
        try:
            page.set_viewport_size({'width':1440, 'height':1100})
            page.goto(url+'/#tasks', wait_until='networkidle')
            health = page.evaluate("async()=>await(await fetch('/api/health')).json()")
            assert health['app_id']=='jm-workbench' and health['worker'] is False
            state = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            source = next(r for r in state['runs'] if r['state']=='completed' and r['progress'].get('pending') and not r.get('continuation_id'))
            task = next(t for t in state['tasks'] if t['id']==source['task_id'])
            page.locator(f'[data-action="edit-task"][data-id="{task["id"]}"]').click()
            form = page.locator('#task-form')
            expect(form.locator('[name=comments_per_video]')).to_have_value('1')
            assert form.locator('[name=comments_per_video]').get_attribute('readonly') is not None
            form.locator('[name=publish_scope]').select_option('limited')
            expect(form.locator('[name=max_publish]')).to_be_visible()
            form.locator('[name=publish_scope]').select_option('all_matches')
            expect(form.locator('[name=max_publish]')).not_to_be_visible()
            assert form.locator('[name=max_publish]').is_disabled()
            checks.append('per-video 1 and optional task total are distinct; total hides for all matches')
            page.set_viewport_size({'width':390,'height':844})
            assert form.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
            checks.append('mobile configuration has no horizontal overflow')
            form.get_by_role('button', name='保存任务', exact=True).click()
            expect(page.locator('#dialog')).not_to_be_visible()
            saved = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            updated = next(t for t in saved['tasks'] if t['id']==task['id'])
            assert updated['comments_per_video']==1 and updated['publish_scope']=='all_matches'
            assert saved['runs']==state['runs'] and saved['attempt_counts']==state['attempt_counts']
            checks.append('saving scope does not launch a run or send')
            page.set_viewport_size({'width':1440,'height':1100})
            page.goto(url+'/#runs',wait_until='networkidle')
            with page.expect_response(lambda r:r.url.endswith(f'/api/runs/{source["id"]}/continue')) as response:
                page.locator(f'[data-action="continue-run"][data-id="{source["id"]}"]').click()
            result = response.value.json()
            assert response.value.status==200 and result['created'] and result['queued']>0
            expect(page.locator(f'[data-action="continue-run"][data-id="{source["id"]}"]')).to_have_count(0)
            expect(page.locator(f'[data-action="stop-run"][data-id="{result["run_id"]}"]')).to_be_visible()
            queue = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            child = next(r for r in queue['runs'] if r['id']==result['run_id'])
            assert child['progress']['selected_count']==len(source['progress']['pending'])
            assert len(child['progress']['pending'])+len(result['skipped'])==len(source['progress']['pending'])
            assert child['snapshot']['task']['publish_scope']=='all_matches'
            assert queue['attempt_counts']==state['attempt_counts']
            checks.append('continue button only queues original remaining videos, filters history and records counts')
            again = page.evaluate('''async ({id,token})=>await(await fetch(`/api/runs/${id}/continue`,{method:'POST',headers:{'X-JM-Token':token,'Content-Type':'application/json'},body:'{}'})).json()''', {'id':source['id'],'token':queue['token']})
            assert again['created'] is False and again['run_id']==result['run_id']
            checks.append('repeat continuation is idempotent')
            page.reload(wait_until='networkidle')
            child_row = page.locator('tr').filter(has=page.locator(f'[data-action="stop-run"][data-id="{result["run_id"]}"]'))
            expect(child_row).to_contain_text('每个视频1条')
            child_row.locator('summary').click()
            expect(child_row).to_contain_text('已有接触记录')
            checks.append('reload retains pending counts and per-target waiting or skip reasons')
            page.screenshot(path=str(Path('outputs')/'每视频一条-补发队列.png'),full_page=True)
            assert not errors
        finally:
            page.close()
    report={'passed':len(checks),'checks':checks,'console_errors':errors}
    Path('outputs/quantity_ui_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('profile')
    parser.add_argument('--port',type=int,default=8777)
    args=parser.parse_args()
    main(args.profile,args.port)
