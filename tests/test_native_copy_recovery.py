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


def test_real_powershell_empty_control_rule_rejects_text_and_embedded_content():
    script=Path('scripts/native_chrome.ps1').resolve()
    shell=shutil.which('pwsh') or shutil.which('powershell')
    if not shell:pytest.skip('Windows PowerShell unavailable')
    command=r'''
    $tokens=$null;$errors=$null
    $ast=[Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$tokens,[ref]$errors)
    if($errors.Count){throw 'PowerShell parse failed'}
    $fn=$ast.Find({param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Test-JmEmptyControl'},$true)
    if(!$fn){throw 'empty control classifier missing'}
    . ([scriptblock]::Create($fn.Extent.Text))
    @(
      (Test-JmEmptyControl $true '' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true "`n" "`n" $false),
      (Test-JmEmptyControl $false '' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true 'typed content' ([string][char]0xfffc) $false),
      (Test-JmEmptyControl $true '' 'typed content' $false),
      (Test-JmEmptyControl $true '' ([string][char]0xfffc) $true),
      (Test-JmEmptyControl $true '' 'placeholder words' $false)
    ) | ConvertTo-Json -Compress
    '''
    # File path is passed as a process argument, never interpolated as shell code.
    runner=script.parent.parent/'tests'/'.empty-control-check.ps1'
    runner.write_text(command,encoding='utf-8-sig')
    try:
        r=subprocess.run([shell,'-NoProfile','-File',str(runner),str(script)],capture_output=True,timeout=30)
        assert r.returncode==0,r.stderr.decode('utf-8',errors='replace')
        assert json.loads(r.stdout)==[True,True,False,False,False,False,False]
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
