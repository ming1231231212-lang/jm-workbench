import pytest
from jm_workbench.community.native_articles import same_article_text,semantic_value

@pytest.mark.parametrize('value',['fixture.example','http://fixture.example/','https://fixture.example/','https://fixture.example'])
def test_bare_hostname_may_become_its_own_root_link(value):
    assert same_article_text('网站是 '+value+'，保留来源。','网站是 fixture.example，保留来源。')

@pytest.mark.parametrize('value',[
    'https://other.example/','https://fixture.example.evil.com/',
    'https://fixture.example/path','https://fixture.example/?next=evil',
    'https://fixture.example/#other','https://user@fixture.example/',
    'https://fixture.example:444/','ftp://fixture.example/',
    'https://fixture.example/%2fother',
])
def test_autolink_does_not_accept_a_changed_destination(value):
    assert not same_article_text('网站是 '+value+'，保留来源。','网站是 fixture.example，保留来源。')

def test_authored_explicit_url_keeps_exact_protocol_and_path():
    assert not same_article_text('https://fixture.example/','http://fixture.example/')
    assert not same_article_text('http://fixture.example/','https://fixture.example/path')

def test_rich_editor_label_cannot_hide_an_unrelated_url():
    html='<!--StartFragment-->网站是 <a href="https://other.example/">fixture.example</a>，保留来源。<!--EndFragment-->'
    actual=semantic_value({'nodes':[]},'editor','网站是 fixture.example，保留来源。',html)
    assert not same_article_text(actual,'网站是 fixture.example，保留来源。')
