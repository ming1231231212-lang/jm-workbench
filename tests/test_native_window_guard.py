"""Exercise the real PowerShell refusal boundary without reading or operating pages."""
import json
import os
import shutil
import subprocess
import pytest
from jm_workbench.core.config import ROOT

@pytest.mark.skipif(os.name!='nt',reason='Windows native boundary')
@pytest.mark.parametrize('arguments,message',[
    (['-Window','2147483647'],'缺少日常Chrome原进程绑定'),
    (['-Window','2147483647','-ExpectedProcessId','2147483647','-ExpectedProcessStarted','never'],'原日常Chrome窗口已关闭'),
])
def test_invalid_window_refused_before_any_ui_action(arguments,message):
    shell=shutil.which('pwsh') or shutil.which('powershell')
    result=subprocess.run([shell,'-NoProfile','-STA','-File',str(ROOT/'scripts/native_chrome.ps1'),*arguments],
        input=json.dumps({'action':'new'}),capture_output=True,encoding='utf-8',timeout=25,
        creationflags=subprocess.CREATE_NO_WINDOW)
    assert result.returncode!=0 and not result.stdout.strip()
    assert message in result.stderr
