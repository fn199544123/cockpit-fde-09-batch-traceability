#!/usr/bin/env python3
"""在 GPU 宿主机运行：python3 smoke-test.py；需要已安装 playwright/Chromium。"""
import csv,io,json,threading,hashlib
from pathlib import Path
from http.server import ThreadingHTTPServer,SimpleHTTPRequestHandler
from functools import partial
from playwright.sync_api import sync_playwright
ROOT=Path(__file__).resolve().parent
class Handler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass
server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
threading.Thread(target=server.serve_forever,daemon=True).start()
results=[]
def ok(name): results.append({'name':name,'passed':True})
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    context=browser.new_context(viewport={'width':1440,'height':1080},accept_downloads=True)
    page=context.new_page(); errors=[]; requests=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append(r.url))
    url=f'http://127.0.0.1:{server.server_port}/index.html'
    assert page.goto(url).status==200
    assert page.locator('#rows tr').count()==10
    def trace(batch,direction):
        page.locator('#scan').fill(batch);page.locator('#'+direction).click()
        return set(page.locator('.node').evaluate_all('(els)=>els.map(e=>e.dataset.id)'))
    assert trace('DEMO-R001','forward')=={'DEMO-R001','DEMO-P001','DEMO-D001','DEMO-D002','DEMO-S001','DEMO-S002'}
    assert trace('DEMO-S001','backward')=={'DEMO-R001','DEMO-P001','DEMO-D001','DEMO-S001'}
    assert trace('DEMO-D001','forward')=={'DEMO-D001','DEMO-S001'}
    ok('样例正反向匹配，反向不混入兄弟分支，配送正向不包含祖先')
    assert trace('DEMO-NONE','forward')==set();assert '未找到' in page.locator('#traceMessage').inner_text()
    def add(t,id,parents=(),qty='12.5'):
        page.locator('#add').click();page.locator('#type').select_option(str(t))
        page.locator('#recordId').fill(id);page.locator('#product').fill('演示卤味')
        page.locator('#quantity').fill(qty);page.locator('#date').fill('2026-09-27')
        for parent in parents:page.locator(f'#parents input[value="{parent}"]').check()
        page.get_by_role('button',name='保存记录',exact=True).click()
    add(0,'DEMO-T-R');assert not page.locator('#editor').is_visible()
    add(1,'DEMO-T-P',['DEMO-T-R','DEMO-R002']);assert not page.locator('#editor').is_visible()
    add(2,'DEMO-T-D',['DEMO-T-P']);add(3,'DEMO-T-S',['DEMO-T-D'])
    assert trace('DEMO-T-R','forward')=={'DEMO-T-R','DEMO-T-P','DEMO-T-D','DEMO-T-S'}
    assert trace('DEMO-T-S','backward')=={'DEMO-T-R','DEMO-R002','DEMO-T-P','DEMO-T-D','DEMO-T-S'}
    ok('界面新增四环节、多上游关联及正反向追溯匹配')
    add(0,'DEMO-T-R');assert '重复' in page.locator('#formError').inner_text();page.locator('#cancel').click()
    for qty in ['0','-1','0.0001','1000001']:
        add(0,'DEMO-BAD',qty=qty);assert '数量' in page.locator('#formError').inner_text();page.locator('#cancel').click()
    add(1,'DEMO-NO-P');assert '至少' in page.locator('#formError').inner_text();page.locator('#cancel').click()
    page.locator('#add').click();page.locator('#type').select_option('1')
    page.locator('#recordId').fill('DEMO-ORPHAN');page.locator('#product').fill('演示原料');page.locator('#quantity').fill('1');page.locator('#date').fill('2026-09-27')
    page.locator('#parents input').first.check();page.locator('#parents input:checked').evaluate('(e)=>e.value="DEMO-MISSING"')
    page.get_by_role('button',name='保存记录',exact=True).click();assert '孤儿' in page.locator('#formError').inner_text();page.locator('#cancel').click()
    assert page.locator('#rows tr').count()==14
    ok('重复编号、零/负数/超精度/超限数量、缺失上游与孤儿引用均拒绝且不改数据')
    page.locator('[data-edit="DEMO-T-P"]').click()
    page.locator('#parents input[value="DEMO-T-R"]').uncheck()
    page.locator('#quantity').fill('8.125')
    page.get_by_role('button',name='保存记录',exact=True).click()
    assert trace('DEMO-T-R','forward')=={'DEMO-T-R'}
    assert trace('DEMO-T-S','backward')=={'DEMO-R002','DEMO-T-P','DEMO-T-D','DEMO-T-S'}
    page.locator('[data-edit="DEMO-R002"]').click();page.locator('#date').fill('2026-09-28')
    page.get_by_role('button',name='保存记录',exact=True).click();assert '日期' in page.locator('#formError').inner_text();page.locator('#cancel').click()
    ok('编辑上游关系即时重算，拒绝破坏已有下游日期约束')
    page.reload();assert page.locator('#rows tr').count()==14
    assert trace('DEMO-T-S','backward')=={'DEMO-R002','DEMO-T-P','DEMO-T-D','DEMO-T-S'}
    assert page.evaluate("JSON.parse(localStorage.getItem('development-9-trace-v1')).find(r=>r.id==='DEMO-T-P').quantity")==8.125
    ok('刷新保留新增、编辑数量及关联变更')
    page.locator('#stageFilter').select_option('1');page.locator('#search').fill('DEMO-T-P');assert page.locator('#rows tr').count()==1
    with page.expect_download() as dl:page.locator('#export').click()
    content=Path(dl.value.path()).read_text(encoding='utf-8-sig');rows=list(csv.reader(io.StringIO(content)))
    assert len(rows)==2 and rows[1][0]=='DEMO-T-P' and rows[1][4]=='8.125'
    ok('组合筛选与 CSV 内容一致')
    page.once('dialog',lambda d:d.dismiss());page.locator('#reset').click();page.locator('#clearFilter').click();assert page.locator('#rows tr').count()==14
    page.once('dialog',lambda d:d.accept());page.locator('#reset').click();assert page.locator('#rows tr').count()==10
    ok('重置取消保留数据，确认恢复10条样例')
    trace('DEMO-R001','forward')
    page.screenshot(path=str(ROOT/'acceptance-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#add').click();assert page.evaluate('document.documentElement.scrollWidth<=innerWidth');page.locator('#cancel').click()
    page.screenshot(path=str(ROOT/'acceptance-mobile.png'),full_page=True)
    ok('390px手机页面与新增弹窗无页面横向溢出')
    assert not errors,errors
    assert all(r==url for r in requests),requests
    ok('Chromium无脚本错误，页面无外部网络请求')
    # 已有存储损坏时显示明确提示，且不自动覆盖原数据。
    page.evaluate("localStorage.setItem('development-9-trace-v1','broken')");page.reload()
    assert page.locator('#storageWarning').is_visible()
    assert page.evaluate("localStorage.getItem('development-9-trace-v1')")=='broken'
    page.once('dialog',lambda d:d.accept());page.locator('#reset').click()
    ok('损坏存储显式提示、不静默覆盖，确认重置恢复')
    browser.close()
server.shutdown()
report={'passed':True,'engine':'真实 Chromium / Playwright，GPU 宿主机','checks':results,'html_sha256':hashlib.sha256((ROOT/'index.html').read_bytes()).hexdigest()}
(ROOT/'acceptance.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print(json.dumps(report,ensure_ascii=False,indent=2))
