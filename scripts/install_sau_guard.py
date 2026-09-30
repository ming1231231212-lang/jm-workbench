"""Preview/install narrow JM guards into an existing SAU. Never starts a service.

Default is read-only. --apply backs up every changed file before replacing it.
Unknown upstream source shapes fail closed; never overwrite unrelated changes.
"""
import argparse
import ast
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

IMPORT='import jm_publish_guard as jm_guard\n'


def replace_once(text, old, new):
    if text.count(old)!=1:
        raise ValueError('SAU source shape changed; guard anchor is missing or ambiguous: '+old[:70])
    return text.replace(old,new,1)


def method(text, classname, name, transform):
    tree=ast.parse(text)
    cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name==classname)
    func=next(n for n in cls.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name)
    lines=text.splitlines(keepends=True)
    lines[func.lineno-1:func.end_lineno]=[transform(''.join(lines[func.lineno-1:func.end_lineno]))]
    return ''.join(lines)


def make_patches(root):
    paths=['sau_backend.py','myUtils/postVideo.py','uploader/ks_uploader/main.py',
           'uploader/douyin_uploader/main.py','uploader/xiaohongshu_uploader/main.py','uploader/tencent_uploader/main.py']
    texts={p:(root/p).read_text(encoding='utf-8-sig') for p in paths}
    guarded_files=[p for p,t in texts.items() if IMPORT in t]
    helper=(ROOT/'jm_workbench/publishing/sau_guard.py').read_text(encoding='utf-8')
    if guarded_files:
        if len(guarded_files)!=len(paths) or not (root/'jm_publish_guard.py').is_file() or (root/'jm_publish_guard.py').read_text(encoding='utf-8')!=helper:
            raise ValueError('Partial or different guard installation; inspect backups before proceeding')
        return {}
    backend=texts['sau_backend.py']
    start=backend.index('        match type:',backend.index('def postVideo():'))
    end=backend.index('        # 返回响应给客户端',start)
    block=backend[start:end]
    backend=backend[:start]+'        with jm_guard.guarded(data.get("jmGuarded") is True):\n'+''.join('    '+line if line.strip() else line for line in block.splitlines(keepends=True))+backend[end:]
    backend=replace_once(backend,"@app.route('/postVideo', methods=['POST'])",'@app.route("/jmGuard", methods=["GET"])\ndef jm_guard_health():\n    return jsonify(jm_guard.guard_status())\n\n\n'+"@app.route('/postVideo', methods=['POST'])")
    texts['sau_backend.py']=backend
    helpers=texts['myUtils/postVideo.py']
    if helpers.count('asyncio.run(')!=4:raise ValueError('Unexpected SAU dispatcher calls')
    texts['myUtils/postVideo.py']=helpers.replace('asyncio.run(','jm_guard.run(')
    def ks(t):
        t=replace_once(t,'                        await publish_button.click()','                        jm_guard.before_submit()\n                        await publish_button.click()')
        t=replace_once(t,'                        await confirm_button.click()','                        jm_guard.before_submit("confirm")\n                        await confirm_button.click()')
        return replace_once(t,'                except Exception as exc:\n                    kuaishou_logger.info','                except Exception as exc:\n                    jm_guard.stop_retry()\n                    kuaishou_logger.info')
    texts['uploader/ks_uploader/main.py']=method(texts['uploader/ks_uploader/main.py'],'KSVideo','upload',ks)
    def dy(t):
        t=replace_once(t,'                    await publish_button.click(force=True)','                    jm_guard.before_submit()\n                    await publish_button.click(force=True)')
        t=replace_once(t,'                if await sms_input.count() and await sms_input.is_visible():','                if await sms_input.count() and await sms_input.is_visible():\n                    jm_guard.reject_verification()')
        return replace_once(t,'            except Exception:\n                await self.handle_auto_video_cover(page)','            except Exception:\n                jm_guard.stop_retry()\n                jm_guard.reject_verification()\n                await self.handle_auto_video_cover(page)')
    texts['uploader/douyin_uploader/main.py']=method(texts['uploader/douyin_uploader/main.py'],'DouYinVideo','upload',dy)
    def xhs(t):
        t=replace_once(t,'                if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED:','                jm_guard.before_submit()\n                if self.publish_strategy == XIAOHONGSHU_PUBLISH_STRATEGY_SCHEDULED:')
        return replace_once(t,'            except Exception:\n                xiaohongshu_logger.info','            except Exception:\n                jm_guard.stop_retry()\n                xiaohongshu_logger.info')
    texts['uploader/xiaohongshu_uploader/main.py']=method(texts['uploader/xiaohongshu_uploader/main.py'],'XiaoHongShuVideo','upload_video_content',xhs)
    def tencent(t):
        t=replace_once(t,'                        await publish_btn.click(timeout=4000)','                        jm_guard.before_submit()\n                        await publish_btn.click(timeout=4000)')
        t=replace_once(t,'                    except Exception:\n                        await publish_btn.evaluate','                    except Exception:\n                        jm_guard.stop_retry()\n                        await publish_btn.evaluate')
        return replace_once(t,'            except Exception as exc:\n                current_url = page.url','            except Exception as exc:\n                jm_guard.stop_retry()\n                current_url = page.url')
    texts['uploader/tencent_uploader/main.py']=method(texts['uploader/tencent_uploader/main.py'],'TencentBaseUploader','submit_publish',tencent)
    result={}
    for path,text in texts.items():
        # Insert after __future__ if present; preserve shebang/encoding/docstrings.
        tree=ast.parse(text);index=0
        for n in tree.body:
            if (isinstance(n,ast.ImportFrom) and n.module=='__future__') or (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)):
                index=n.end_lineno
            else:break
        lines=text.splitlines(keepends=True);lines.insert(index,IMPORT);patched=''.join(lines)
        compile(patched,str(root/path),'exec');result[path]=patched
    result['jm_publish_guard.py']=helper
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,default=Path(r'D:\SocialAutoUpload'))
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args();root=args.root.resolve();patches=make_patches(root)
    print(json.dumps({'mode':'apply' if args.apply else 'preview','changed_files':list(patches)},ensure_ascii=False))
    if not args.apply or not patches:return
    backup=ROOT/'outputs'/('sau-guard-backup-'+time.strftime('%Y%m%d-%H%M%S'));backup.mkdir(parents=True)
    manifest={}
    for relative in patches:
        target=root/relative
        if target.is_file():
            destination=backup/relative;destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(target,destination)
            manifest[relative]=hashlib.sha256(target.read_bytes()).hexdigest()
        else:manifest[relative]=None
    (backup/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    for relative,text in patches.items():
        target=root/relative
        current=hashlib.sha256(target.read_bytes()).hexdigest() if target.exists() else None
        if current!=manifest[relative]:raise ValueError('Source changed during backup; stopped: '+relative)
    for relative,text in patches.items():
        target=root/relative;temp=target.with_suffix('.jm-tmp');temp.write_text(text,encoding='utf-8');temp.replace(target)
    assert not make_patches(root),'Installation must be idempotent'
    print(json.dumps({'backup':str(backup),'installed':len(patches)},ensure_ascii=False))


if __name__=='__main__':main()
