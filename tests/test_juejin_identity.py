from types import SimpleNamespace
import pytest
from jm_workbench.community.juejin import identity
from jm_workbench.community.adapters import PreflightStopped


@pytest.mark.parametrize('hrefs,expected',[
    (['/user/123','/user/123','/user/center/signin?avatar_menu'],'123'),
    (['/user/123/posts'],'123'),
    (['/user/123','/user/456'],None),
    (['https://evil.example/user/123'],None),
    ([],None),
])
def test_identity_requires_one_consistent_account_menu(hrefs,expected):
    links=SimpleNamespace(count=lambda:len(hrefs),evaluate_all=lambda _:hrefs,
        first=SimpleNamespace(wait_for=lambda **kw:None))
    avatar=SimpleNamespace(wait_for=lambda **kw:None,click=lambda **kw:None)
    page=SimpleNamespace(url='https://juejin.cn/',locator=lambda s:avatar if s=='header .avatar-wrapper' else links)
    if expected:assert identity(page)==expected
    else:
        with pytest.raises(PreflightStopped):identity(page)
