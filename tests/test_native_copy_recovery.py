import json
import shutil
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_community_replies import ctx
from jm_workbench.community.adapters import PreflightStopped,RetryablePreflight
from jm_workbench.community.native import NativeStopped,NativeUnknown
from jm_workbench.community.native_channel import NativeChromeChannel
from jm_workbench.community.native_runtime import NativeRuntime
from jm_workbench.community.models import DailyPlan
from test_community_daily import setup_plan


def test_powershell_loading_control_is_classified_as_transient(tmp_path):
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:pytest.skip('Windows PowerShell unavailable')
    runner=tmp_path/'control-type.ps1'
    runner.write_text(r'''
    $ErrorActionPreference='Stop';$tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'parse failed'}
    $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Get-JmControlType'},$true)
    if(!$fn){throw 'control type classifier missing'}
    . ([scriptblock]::Create($fn.Extent.Text))
    $results=@()
    foreach($item in @($null,[pscustomobject]@{ControlType=$null},[pscustomobject]@{ControlType=[pscustomobject]@{ProgrammaticName=$null}})){
      try{Get-JmControlType $item;throw 'unexpected success'}catch{
        if($_.Exception.Message -notlike '*[[]JM_DESKTOP_WAIT]*'){throw}
        $results+='transient'
      }
    }
    $results+=(Get-JmControlType ([pscustomobject]@{ControlType=[pscustomobject]@{ProgrammaticName='ControlType.Edit'}}))
    $results|ConvertTo-Json -Compress
    ''',encoding='utf-8-sig')
    r=subprocess.run([shell,'-NoProfile','-File',str(runner),str(Path('scripts/native_chrome.ps1').resolve())],capture_output=True,timeout=30)
    assert r.returncode==0,r.stderr.decode('utf-8',errors='replace')
    assert json.loads(r.stdout)==['transient','transient','transient','Edit']


def test_real_powershell_empty_control_rule_rejects_text_and_embedded_content():
    script=Path('scripts/native_chrome.ps1').resolve()
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:pytest.skip('Windows PowerShell unavailable')
    command=r'''
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'PowerShell parse failed'}
    foreach($name in @('Test-JmEmptyControl','Test-JmEmptyTiebaControl')){
      $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq $name},$true)
      if(!$fn){throw 'empty control classifier missing'}
      . ([scriptblock]::Create($fn.Extent.Text))
    }
    @(
      (Test-JmEmptyControl $true '' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true "`n" "`n" $false),
      (Test-JmEmptyControl $false '' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true 'typed content' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true '' 'typed content' $false),
      (Test-JmEmptyControl $true '' ([string][char]0xfffc) $true),
      (Test-JmEmptyControl $true '' 'placeholder words' $false),
      (Test-JmEmptyTiebaControl 'tb-editor-title' '必填，请输入贴子标题(5-31个字)' "`n" 1 $false),
      (Test-JmEmptyTiebaControl 'tb-editor-content' '请输入正文（建议200-2000字）' '' 1 $false),
      (Test-JmEmptyTiebaControl 'other' '必填，请输入贴子标题(5-31个字)' '' 1 $false),
      (Test-JmEmptyTiebaControl 'tb-editor-title' '必填，请输入贴子标题(5-31个字)' '必填，请输入贴子标题(5-31个字)' 1 $false),
      (Test-JmEmptyTiebaControl 'tb-editor-title' '必填，请输入贴子标题(5-31个字)' '' 1 $true),
      (Test-JmEmptyTiebaControl 'tb-editor-title' '必填，请输入贴子标题(5-31个字)' '' 0 $false)
    ) | ConvertTo-Json -Compress
    '''
    # File path is passed as a process argument, never interpolated as shell code.
    runner=script.parent.parent/'tests'/'.empty-control-check.ps1'
    runner.write_text(command,encoding='utf-8-sig')
    try:
        r=subprocess.run([shell,'-NoProfile','-File',str(runner),str(script)],capture_output=True,timeout=30)
        assert r.returncode==0,r.stderr.decode('utf-8',errors='replace')
        assert json.loads(r.stdout)==[True,True,False,False,False,False,False,True,True,False,False,False,False]
    finally:runner.unlink(missing_ok=True)


@pytest.mark.parametrize('marker',['JM_COPY_PENDING','JM_DESKTOP_WAIT'])
@pytest.mark.parametrize('entered',[False,True])
def test_temporary_local_failure_retries_only_before_submit(ctx,monkeypatch,tmp_path,marker,entered):
    s,_,a,_=ctx
    ui=NativeChromeChannel(tmp_path/'state.json',runner=lambda *a,**kw:SimpleNamespace(returncode=1,stderr='Exception: ['+marker+'] temporarily unavailable',stdout=''))
    runtime=NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock',lambda _:nullcontext())
    class Publisher:
        before_submit=staticmethod(lambda:None)
        def publish(self,*_):
            if entered:self.before_submit()
            return ui.raw('focus-copy')
    monkeypatch.setattr(runtime,'publisher',lambda *_:Publisher())
    with pytest.raises(NativeUnknown if entered else RetryablePreflight):
        runtime.publish({**s.account(a),'native_binding':{}},{},'')


def test_content_mismatch_is_not_made_retryable(ctx,monkeypatch):
    s,_,a,_=ctx;runtime=NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock',lambda _:nullcontext())
    class Publisher:
        before_submit=staticmethod(lambda:None)
        def publish(self,*_):raise NativeStopped('文章编辑器已有内容，已保留原稿，未提交')
    monkeypatch.setattr(runtime,'publisher',lambda *_:Publisher())
    with pytest.raises(PreflightStopped):runtime.publish({**s.account(a),'native_binding':{}},{},'')


@pytest.mark.parametrize('marker',['JM_COPY_PENDING','JM_DESKTOP_WAIT'])
def test_transient_failure_keeps_daily_plan_and_recovers_same_job(ctx,monkeypatch,tmp_path,marker):
    s,f,a,n=ctx;p=setup_plan(ctx)
    s.daily.control(p,'pause');data=s.daily.get(p)['payload'];data['replies_per_day']=0
    s.daily.save(DailyPlan(**data),p);s.daily.control(p,'enable');s.daily.prepare(p)
    ui=NativeChromeChannel(tmp_path/'tab.json',runner=lambda *a,**kw:SimpleNamespace(returncode=1,stderr='['+marker+'] temporary',stdout=''))
    runtime=NativeRuntime(s.cfg.config)
    monkeypatch.setattr('jm_workbench.community.native_runtime.desktop_lock',lambda _:nullcontext())
    class Publisher:
        before_submit=staticmethod(lambda:None)
        def publish(self,*_):return ui.raw('focus-copy')
    monkeypatch.setattr(runtime,'publisher',lambda *_:Publisher())
    original=f.publish
    f.publish=lambda account,secret,payload,target:runtime.publish({**account,'native_binding':{}},payload,target)
    s.tick();jobs=s.store.rows('SELECT * FROM community_jobs')
    assert len(jobs)==1 and jobs[0]['state']=='queued' and jobs[0]['started']==0
    assert jobs[0]['due']>=n[0]+300 and s.daily.get(p)['state']=='enabled'
    assert not s.state()['risk'] and not f.sent
    s.recover();f.publish=original;n[0]=jobs[0]['due'];s.tick()
    after=s.store.rows('SELECT * FROM community_jobs')
    assert len(after)==1 and after[0]['id']==jobs[0]['id'] and after[0]['state']=='submitted'
    assert len(f.sent)==1 and s.daily.get(p)['state']=='enabled'
