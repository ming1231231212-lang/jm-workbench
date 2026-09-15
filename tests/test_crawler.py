import pytest
from jm_workbench.adapters.crawler import Crawler, parameters
from jm_workbench.adapters.crawler_child import response_risk
from jm_workbench.core.config import Config

@pytest.mark.parametrize('platform',['ks','dy','xhs','bili','wb','tieba','zhihu'])
def test_each_platform_passes_only_bounded_parameters(tmp_path,monkeypatch,platform):
    cfg=Config(tmp_path)
    cfg.save({'crawler_root':'external','crawler_python':'python'})
    monkeypatch.setattr('jm_workbench.adapters.crawler.endpoint',lambda _:'ws://127.0.0.1:4567/devtools/browser/test')
    run={'id':'run1','snapshot':{'task':{'platform':platform,'max_items':3,'collect_comments':True,'comments_per_item':5},'account':{'profile_dir':'chosen-profile'}}}
    p=parameters(cfg,run,'指定关键词')
    assert p['keyword']=='指定关键词' and p['max_items']==3 and p['comments_per_item']==5
    assert p['output']==str(tmp_path/'runs'/'run1')
    assert 'proxy' not in p and 'cookies' not in p

def test_kuaishou_normal_search_adapter(tmp_path,monkeypatch):
    class Browser:
        def __init__(self,a): assert a['profile_dir']=='chosen-profile'
        def __enter__(self): return self
        def __exit__(self,*args): pass
        def account(self): return {'id':'expected'}
        def search(self,q): return [{'caption':q},{'caption':'second'}]
    monkeypatch.setattr('jm_workbench.adapters.crawler.Browser',Browser)
    run={'id':'run1','snapshot':{'task':{'platform':'ks','max_items':1,'collect_comments':False},'account':{'profile_dir':'chosen-profile','identity':'expected'}}}
    assert Crawler(Config(tmp_path)).run(run,'精确关键词')==[{'caption':'精确关键词','record_type':'contents'}]

def test_legacy_rate_limit_code_stops_before_internal_retry():
    assert response_risk(200,{'result':2})
    assert response_risk(200,{'result':50})
