from pathlib import Path
import os
from playwright.sync_api import sync_playwright
from PIL import Image, ImageDraw
import json

PROJECT=Path(__file__).resolve().parents[1]
ROOT=PROJECT/'test-output'
ROOT.mkdir(exist_ok=True)
photo=Image.new('RGB',(900,700),'#174355');d=ImageDraw.Draw(photo);d.rectangle((100,180,550,550),fill='#d9b781');d.ellipse((630,200,750,320),fill='#ffc86a');d.rectangle((650,320,730,550),fill='#6edbcb');photo.save(ROOT/'test-team-photo.jpg')
html=(PROJECT/'CITY_HUNT_DEMO.html').read_text()
shim="""<script>window.__testStorage=window.__testStorage||{};Object.defineProperty(window,'localStorage',{value:{getItem:k=>window.__testStorage[k]??null,setItem:(k,v)=>window.__testStorage[k]=v,removeItem:k=>delete window.__testStorage[k]}});</script>"""
html=html.replace('<head>','<head>'+shim)
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,executable_path=os.getenv('CHROMIUM_PATH') or None,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1440,'height':1000})
 page.set_default_timeout(8000)
 page.emulate_media(reduced_motion='reduce')
 errors=[]; page.on('pageerror',lambda e: errors.append(str(e)))
 page.set_content(html,wait_until='load');page.wait_for_selector('.landing');page.wait_for_timeout(400)
 page.screenshot(path=str(ROOT/'city-hunt-desktop.png'),full_page=True)
 page.get_by_role('button',name='JOIN THE GAME').click()
 page.get_by_label('YOUR NAME',exact=True).fill('Yun Hong')
 page.get_by_label('TEAM CODE',exact=True).fill('CITY01')
 page.locator('[name="consent"]').check()
 page.get_by_role('button',name='ENTER CITY HUNT').click()
 page.wait_for_selector('.home-grid');page.wait_for_timeout(400);page.locator('#toast').evaluate('(el)=>el.innerHTML=""')
 page.screenshot(path=str(ROOT/'city-hunt-home-desktop.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(ROOT/'city-hunt-home-mobile.png'),full_page=True)
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow home'
 page.get_by_role('button',name='START MISSION',exact=True).click();page.wait_for_selector('.clue-card');page.wait_for_timeout(400)
 page.screenshot(path=str(ROOT/'city-hunt-clue-mobile.png'),full_page=True)
 page.get_by_role('button',name='WE FOUND IT').click()
 page.locator('#gallery-input').set_input_files(str(ROOT/'test-team-photo.jpg'))
 page.wait_for_selector('.photo-preview');page.wait_for_timeout(500)
 page.get_by_role('button',name='SUBMIT PHOTO').click()
 page.wait_for_selector('form[data-form="answer"]')
 print('After photo:',page.locator('form[data-form="answer"]').inner_text())
 page.locator('form[data-form="answer"] [name="answer"]').fill('Merlion')
 page.locator('form[data-form="answer"] button[type="submit"]').click()
 page.wait_for_selector('select[name^="match-"]')
 print('Matching controls rendered.')
 for key,val in {'park':'Green space','rail':'Transport','homes':'Housing'}.items():
  page.locator(f'select[name="match-{key}"]').select_option(val)
 page.locator('form[data-form="answer"] button[type="submit"]').click()
 page.wait_for_timeout(500)
 page.locator('form[data-form="answer"] [name="answer"]').fill('There are miniature trees between the buildings.')
 page.locator('form[data-form="answer"] button[type="submit"]').click()
 page.wait_for_selector('#gallery-input',state='attached')
 page.locator('#gallery-input').set_input_files(str(ROOT/'test-team-photo.jpg'))
 page.wait_for_selector('.photo-preview');page.wait_for_timeout(300)
 page.get_by_role('button',name='SUBMIT PHOTO').click()
 page.wait_for_selector('.celebration');page.wait_for_timeout(300)
 assert '1 / 8' in page.locator('.celebration').inner_text()
 assert page.evaluate('S.team.score') == 30
 print('Mission completed, score',page.evaluate('S.team.score'))
 page.screenshot(path=str(ROOT/'city-hunt-mission-complete-mobile.png'),full_page=True)
 page.get_by_role('button',name='CONTINUE THE HUNT').click()
 page.locator('[data-page="more"]').click()
 page.get_by_role('button',name='Organiser dashboard').click()
 page.get_by_role('button',name='OPEN DEMO CONTROL CENTRE').click()
 page.wait_for_selector('.admin-layout');page.set_viewport_size({'width':1440,'height':1000});page.wait_for_timeout(400);page.locator('#toast').evaluate('(el)=>el.innerHTML=""')
 page.screenshot(path=str(ROOT/'city-hunt-admin-desktop.png'),full_page=True)
 page.locator('[data-tab="reviews"]').first.click();page.wait_for_selector('[data-review-id]')
 print('Review cards:',page.locator('[data-review-id]').count())
 for _ in range(5):
  if page.locator('[data-action="review-full"]').count():
   page.locator('[data-action="review-full"]').first.click();page.wait_for_timeout(250)
 assert page.evaluate('A.teams.find(x=>x.id===1).score') == 40
 print('Admin review score:',page.evaluate('A.teams.find(x=>x.id===1).score'))
 page.locator('[data-tab="points"]').first.click()
 form=page.locator('form[data-form="points"]');form.locator('[name="team"]').select_option('1');form.locator('[name="points"]').fill('10');form.locator('[name="reason"]').fill('Best teamwork');form.locator('button[type="submit"]').click()
 page.wait_for_timeout(400);assert page.evaluate('A.teams.find(x=>x.id===1).score') == 50
 page.locator('[data-tab="missions"]').first.click();page.wait_for_timeout(300)
 page.screenshot(path=str(ROOT/'city-hunt-editor-desktop.png'),full_page=True)
 page.locator('[data-action="edit-mission"]').first.click();page.wait_for_selector('form[data-form="mission-editor"]');page.wait_for_timeout(300)
 assert page.locator('.editor-stage').count()==5
 page.screenshot(path=str(ROOT/'city-hunt-mission-editor.png'),full_page=True)
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), 'Mobile overflow admin editor'
 print('Browser page errors:',errors)
 assert not errors
 (ROOT/'city-hunt-browser-test.json').write_text(json.dumps({'status':'passed','tested':['landing','join','390px responsive layout','photo selection and compression','investigation answer','matching answers','manual bonus answer','creative photo','mission receipt','organiser login','review points','bonus award','mission editor rendering'],'errors':errors},indent=2))
 b.close()
