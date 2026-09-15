"""Exercise comment configuration on a worker-disabled local test instance only."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from jm_workbench.adapters.chrome import endpoint
from jm_workbench.policies.comments import ADULT_CORE


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
            assert health['app_id'] == 'jm-workbench' and health['worker'] is False
            state = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            task = next(t for t in state['tasks'] if t['kind']=='adult_comments')
            page.locator(f'[data-action="edit-task"][data-id="{task["id"]}"]').click()
            form = page.locator('#task-form')
            form.locator('[name=adult_target]').select_option('keyword')
            form.locator('[name=comment_mode]').select_option('core_variants')
            form.locator('[name=comment_core]').fill(ADULT_CORE)
            assert not form.locator('[name=templates]').is_visible()
            checks.append('scope and core mode are editable; inactive templates are hidden')
            form.get_by_role('button',name='预览文案',exact=True).click()
            expect(form.locator('#comment-preview-result blockquote')).to_have_count(3)
            assert '无需店主身份或库存' in form.locator('#comment-preview-result').inner_text()
            current = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            for key in ['tasks','runs','attempt_counts']:
                assert state[key]==current[key]
            checks.append('preview shows actual generated samples without saving or sending')
            form.locator('[name=comment_core]').fill(ADULT_CORE+'微信12345678')
            assert not form.locator('#comment-preview-result blockquote').count()
            form.get_by_role('button',name='预览文案',exact=True).click()
            expect(page.locator('#toast')).to_contain_text('外联')
            assert not form.locator('#comment-preview-result blockquote').count()
            checks.append('changed core invalidates old preview and invalid wording is rejected')
            form.locator('[name=comment_core]').fill(ADULT_CORE)
            form.get_by_role('button',name='保存任务',exact=True).click()
            expect(page.locator('#dialog')).not_to_be_visible()
            saved = page.evaluate("async()=>await(await fetch('/api/state')).json()")
            new = next(t for t in saved['tasks'] if t['id']==task['id'])
            assert new['adult_target']=='keyword' and new['comment_mode']=='core_variants'
            assert new['comment_core']==ADULT_CORE
            for key in ['keywords','max_items','max_publish','start_hour','end_hour']:
                assert new[key]==task[key]
            assert [t for t in saved['tasks'] if t['id']!=task['id']]==[t for t in state['tasks'] if t['id']!=task['id']]
            assert saved['runs']==state['runs'] and saved['attempt_counts']==state['attempt_counts']
            checks.append('save changes only selected task and never starts execution')
            page.reload(wait_until='networkidle')
            page.locator(f'[data-action="edit-task"][data-id="{task["id"]}"]').click()
            expect(form.locator('[name=adult_target]')).to_have_value('keyword')
            expect(form.locator('[name=comment_mode]')).to_have_value('core_variants')
            expect(form.locator('[name=comment_core]')).to_have_value(ADULT_CORE)
            checks.append('saved scope and core survive reload')
            page.set_viewport_size({'width':390,'height':844})
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert form.evaluate('el=>el.scrollWidth<=el.clientWidth+1')
            checks.append('mobile configuration has no horizontal overflow')
            page.screenshot(path=str(Path('outputs')/'评论配置-手机.png'), full_page=True)
            form.locator('[name=comment_mode]').select_option('templates')
            assert form.locator('[name=templates]').is_visible()
            assert not form.locator('[name=comment_core]').is_visible()
            form.get_by_role('button',name='取消',exact=True).click()
            checks.append('switching modes changes fields; cancel does not save')
            page.goto(url+'/#data',wait_until='networkidle')
            card=page.locator('.template-card').filter(has_text=task['name'])
            expect(card).to_contain_text(ADULT_CORE)
            expect(card).to_contain_text('无需店主身份或库存')
            expect(card.locator('blockquote')).to_have_count(3)
            checks.append('data page uses saved scope and core generated examples')
            page.goto(url+'/#tasks',wait_until='networkidle')
            page.get_by_role('button',name='+ 新建任务',exact=True).click()
            form.locator('[name=kind]').select_option('peiwang_comments')
            assert not form.locator('[name=adult_target]').is_visible()
            assert not form.locator('[name=comment_core]').is_visible()
            assert '18岁以上' in form.locator('[name=templates]').input_value()
            form.locator('[name=kind]').select_option('crawler')
            assert not form.locator('[name=templates]').is_visible()
            assert not form.get_by_role('button',name='预览文案',exact=True).is_visible()
            checks.append('recruitment and crawler forms do not inherit adult comment mode')
            form.get_by_role('button',name='取消',exact=True).click()
            assert not errors
        finally:
            page.close()
    report={'passed':len(checks),'checks':checks,'console_errors':errors}
    Path('outputs/comment_ui_acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('profile')
    parser.add_argument('--port',type=int,default=8777)
    args=parser.parse_args()
    main(args.profile,args.port)
