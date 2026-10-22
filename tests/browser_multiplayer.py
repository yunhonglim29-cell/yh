from pathlib import Path
from tempfile import TemporaryDirectory
import os,sys,base64,io,json
from fastapi.testclient import TestClient
from PIL import Image
from playwright.sync_api import sync_playwright
PROJECT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PROJECT))
from app import create_app
ROOT=PROJECT
(PROJECT/'test-output').mkdir(exist_ok=True)
os.environ['ADMIN_PASSWORD']='AutomatedBrowserTestPassword!'
os.environ.pop('APP_ENV',None)
image=io.BytesIO();Image.new('RGB',(80,80),'green').save(image,'JPEG');encoded='data:image/jpeg;base64,'+base64.b64encode(image.getvalue()).decode()
css=(ROOT/'static/styles.css').read_text();js=(ROOT/'static/app.js').read_text();city='data:image/svg+xml;base64,'+base64.b64encode((ROOT/'static/city.svg').read_bytes()).decode();js=js.replace('/static/city.svg',city)
shim='''window.__testStorage={};Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.__testStorage[k]??null,setItem:(k,v)=>window.__testStorage[k]=v,removeItem:k=>delete window.__testStorage[k]}});window.fetch=async (path, options={})=>{const r=await window.__apiCall(path,options);return {ok:r.status>=200&&r.status<300,status:r.status,json:async()=>r.body}};'''
html=f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><style>{css}</style></head><body><div id="app"></div><div id="toast" role="status"></div><div id="modal-root"></div><script>{shim}</script><script>{js}</script></body></html>'''
with TemporaryDirectory() as d, sync_playwright() as p:
 app=create_app(Path(d),testing=True)
 admin=TestClient(app);csrf=admin.get('/api/bootstrap').json()['csrf']
 def post_admin(action,data):
  r=admin.post('/api/admin/'+action,json=data,headers={'X-CSRF-Token':csrf});assert r.status_code==200,r.text;return r
 post_admin('login',{'password':os.environ['ADMIN_PASSWORD']});post_admin('control',{'command':'start'})
 clients=[TestClient(app),TestClient(app)]
 def callback(client):
  def call(path,options):
   response=client.request(options.get('method','GET'),path,headers=options.get('headers',{}),content=options.get('body'))
   return {'status':response.status_code,'body':response.json()}
  return call
 browser=p.chromium.launch(headless=True,executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox']);errors=[];pages=[]
 for i,client in enumerate(clients):
  page=browser.new_page(viewport={'width':390,'height':844});page.set_default_timeout(10000);page.emulate_media(reduced_motion='reduce');page.on('pageerror',lambda e:errors.append(str(e)))
  page.expose_function('__apiCall',callback(client));page.set_content(html,wait_until='load');page.wait_for_selector('.landing');page.get_by_role('button',name='JOIN THE GAME').click();page.get_by_label('YOUR NAME',exact=True).fill('Player '+str(i+1));page.get_by_label('TEAM CODE',exact=True).fill('CITY01');page.locator('[name="consent"]').check();page.get_by_role('button',name='ENTER CITY HUNT').click();page.wait_for_selector('.home-grid');pages.append(page)
 pages[0].bring_to_front();pages[0].get_by_role('button',name='START MISSION',exact=True).click();pages[0].wait_for_selector('.clue-card')
 clients[0].post('/api/photo',json={'missionId':1,'stageId':'photo','image':encoded,'requestId':'photo-test'},headers={'X-CSRF-Token':clients[0].get('/api/bootstrap').json()['csrf']})
 pages[0].wait_for_selector('form[data-form="answer"]');assert pages[0].evaluate('S.team.score')==10
 pages[0].locator('form[data-form="answer"] [name="answer"]').fill('Merlion');pages[0].locator('form[data-form="answer"] button[type="submit"]').click();pages[0].wait_for_selector('select[name="match-park"]');assert pages[0].evaluate('S.team.score')==20
 pages[1].bring_to_front();pages[1].wait_for_function('S.team.score===20');pages[1].get_by_role('button',name='CONTINUE MISSION',exact=True).click();pages[1].wait_for_selector('select[name="match-park"]')
 post_admin('points',{'team':1,'points':10,'reason':'Browser sync check','category':'bonus','requestId':'browser-bonus'})
 pages[1].wait_for_function('S.team.score===30');pages[0].bring_to_front();pages[0].wait_for_function('S.team.score===30')
 assert not errors,errors
 (PROJECT/'test-output/city-hunt-real-browser-test.json').write_text(json.dumps({'status':'passed','transport':'FastAPI TestClient bridge to two isolated Chromium page sessions','checks':['real join and CSRF session','server mission start','server photo submission unlocks question','answer submission through actual UI','second player sees same stage and score','admin bonus propagates to both players'],'errors':errors},indent=2))
 print('REAL BACKEND + TWO BROWSER SESSIONS: PASSED. Both shared scores 30, no JavaScript errors.')
 browser.close()
