"""Server integration and security regression tests. No external services required."""
import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
import uuid
import zipfile

from fastapi.testclient import TestClient
from PIL import Image
import pytest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import create_app, is_correct, validate_mission, HTTPException
from seed import make_missions

PASSWORD = 'CityHuntAutomatedTestPassword!'

class Client:
    def __init__(self, app):
        self.client = TestClient(app)
        self.csrf = self.client.get('/api/bootstrap').json()['csrf']
    def post(self, path, data=None):
        return self.client.post('/api/'+path, json=data or {}, headers={'X-CSRF-Token': self.csrf})
    def get(self, path):
        return self.client.get('/api/'+path)
    def state(self):
        return self.get('state').json()
    def join(self, team=1, name='Test Player'):
        r=self.post('join', {'team':team,'name':name,'code':f'CITY0{team}'})
        assert r.status_code == 200, r.text
        return self

@pytest.fixture
def app(tmp_path,monkeypatch):
    monkeypatch.setenv('ADMIN_PASSWORD', PASSWORD)
    monkeypatch.delenv('APP_ENV',raising=False)
    return create_app(tmp_path, testing=True)

@pytest.fixture
def admin(app):
    c=Client(app)
    assert c.post('admin/login',{'password':PASSWORD}).status_code==200
    return c

@pytest.fixture
def live(app,admin):
    assert admin.post('admin/control',{'command':'start'}).status_code==200
    return app

@pytest.fixture
def photo():
    stream=io.BytesIO()
    Image.new('RGB',(100,100),(120,160,140)).save(stream,'JPEG')
    return 'data:image/jpeg;base64,'+base64.b64encode(stream.getvalue()).decode()

def send(c,answer=None,image=None,request_id=None):
    m=c.state()['current']
    return c.post('photo' if image else 'submit', {'missionId':m['id'],'stageId':m['stage']['id'],'answer':answer,'image':image,'requestId':request_id or uuid.uuid4().hex})

def test_rotation_all_eight_teams(live):
    for team in range(1,9):
        c=Client(live).join(team)
        assert c.state()['current']['id']==team
    assert live.state.store.route({'id':8}) == [8,1,2,3,4,5,6,7,9]

def test_wrong_code_and_csrf_rejected(app):
    c=Client(app)
    assert c.post('join',{'name':'Test','team':1,'code':'wrong'}).status_code==403
    assert c.client.post('/api/join',json={'name':'Test','team':1,'code':'CITY01'}).status_code==403
    assert c.client.post('/api/join',headers={'X-CSRF-Token':c.csrf,'Origin':'https://evil.invalid'},json={'name':'Test','team':1,'code':'CITY01'}).status_code==403

def test_admin_endpoints_not_available_to_players(live):
    c=Client(live).join()
    assert c.get('admin').status_code==401
    assert c.post('admin/points',{'team':1,'points':999,'reason':'Cheat','requestId':uuid.uuid4().hex}).status_code==401
    assert c.get('export').status_code==401
    assert c.get('backup').status_code==401

def test_future_content_and_answers_not_delivered(live,photo):
    c=Client(live).join()
    state=c.state()
    assert 'clue' not in state['current'] and 'stage' not in state['current']
    assert c.post('start',{'missionId':8}).status_code==409
    assert c.post('start',{'missionId':1}).status_code==200
    m=c.state()['current']
    assert m['stage']['type']=='photo'
    serialized=json.dumps(m)
    assert 'Merlion' not in serialized and 'accepted' not in serialized and 'correct' not in serialized
    assert all(h['text'] is None for h in m['hints'])
    assert c.post('submit',{'missionId':1,'stageId':'investigation','answer':'Merlion','requestId':uuid.uuid4().hex}).status_code==409
    assert send(c,image=photo).status_code==200
    m=c.state()['current']
    assert m['stage']['type']=='text'
    assert 'accepted' not in m['stage'] and 'correct' not in m['stage']
    assert 'Lines that lead somewhere' not in json.dumps(c.state())

def test_photo_duplicate_race_scores_once(live,photo):
    a=Client(live).join(1,'Player A');b=Client(live).join(1,'Player B')
    a.post('start',{'missionId':1})
    payload={'missionId':1,'stageId':'photo','image':photo,'requestId':uuid.uuid4().hex}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda c:c.post('photo',payload),[a,b]))
    assert sorted(r.status_code for r in results)==[200,409]
    assert a.state()['team']['score']==10==b.state()['team']['score']
    assert len(a.state()['submissions'])==1

def test_answers_duplicate_race_scores_once(live,photo):
    a=Client(live).join();b=Client(live).join()
    a.post('start',{'missionId':1});send(a,image=photo)
    def answer(c):return c.post('submit',{'missionId':1,'stageId':'investigation','answer':'merlion','points':100000,'requestId':uuid.uuid4().hex})
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(answer,[a,b]))
    assert sorted(r.status_code for r in results)==[200,409]
    assert a.state()['team']['score']==20

def test_photo_privacy_and_reencoding(live,photo):
    a=Client(live).join(1);b=Client(live).join(2)
    a.post('start',{'missionId':1});send(a,image=photo)
    path=a.state()['submissions'][0]['photo']
    assert a.client.get(path).status_code==200
    assert b.client.get(path).status_code==403
    assert TestClient(live).get(path).status_code==401
    image=Image.open(io.BytesIO(a.client.get(path).content))
    assert image.format=='JPEG' and not image.getexif()
    assert a.client.get('/uploads/anything.jpg').status_code==404

def test_invalid_photos_are_rejected(live):
    c=Client(live).join();c.post('start',{'missionId':1})
    invalid='data:image/jpeg;base64,'+base64.b64encode(b'not an image').decode()
    assert send(c,image=invalid).status_code==400
    assert c.state()['team']['score']==0
    assert c.state()['current']['stageIndex']==0

def test_photo_review_delta_is_idempotent(live,admin,photo):
    c=Client(live).join();c.post('start',{'missionId':1});send(c,image=photo)
    sub=c.state()['submissions'][0]
    for _ in range(2):assert admin.post('admin/review',{'id':sub['id'],'points':0,'comment':'Treasure not visible'}).status_code==200
    assert c.state()['team']['score']==0
    for _ in range(2):admin.post('admin/review',{'id':sub['id'],'points':10})
    assert c.state()['team']['score']==10
    assert admin.post('admin/review',{'id':sub['id'],'points':11}).status_code==400

def test_pending_photos_do_not_block_progress(live,admin,photo):
    admin.post('admin/settings',{'photoMode':'review'})
    c=Client(live).join();c.post('start',{'missionId':1})
    response=send(c,image=photo)
    assert response.json()['pending'] is True
    assert c.state()['team']['score']==0
    assert c.state()['current']['stage']['id']=='investigation'

def test_wrong_answers_and_request_retry(live,photo):
    c=Client(live).join();c.post('start',{'missionId':1});send(c,image=photo)
    rid=uuid.uuid4().hex
    r=send(c,answer='Not a landmark',request_id=rid)
    assert r.json()['retry'] is True
    send(c,answer='Not a landmark',request_id=rid)
    assert c.state()['current']['stage']['attemptsUsed']==1
    r=send(c,answer='Still not a landmark')
    assert not r.json()['correct']
    assert c.state()['current']['stage']['id']=='mini'
    assert c.state()['team']['score']==10

def test_bonus_idempotency_and_live_score(live,admin):
    c=Client(live).join()
    payload={'team':1,'points':10,'reason':'Best teamwork','category':'bonus','requestId':uuid.uuid4().hex}
    for _ in range(3):assert admin.post('admin/points',payload).status_code==200
    assert c.state()['team']['score']==10
    assert c.state()['leaderboard']['rows'][0]['id']==1
    assert c.state()['team']['scoreParts']['bonus']==10

def test_hints_deduct_once_and_lock_order(live):
    c=Client(live).join();c.post('start',{'missionId':1})
    assert c.post('hint',{'missionId':1,'index':2}).status_code==409
    c.post('hint',{'missionId':1,'index':0})
    for _ in range(3):c.post('hint',{'missionId':1,'index':1})
    assert c.state()['team']['score']==-2
    hints=c.state()['current']['hints']
    assert hints[0]['text'] and hints[1]['text'] and hints[2]['text'] is None

def test_pause_resume_and_team_pause(live,admin):
    c=Client(live).join()
    admin.post('admin/control',{'command':'pause'})
    assert c.post('start',{'missionId':1}).status_code==409
    admin.post('admin/control',{'command':'resume'})
    admin.post('admin/team',{'team':1,'paused':True})
    assert c.post('start',{'missionId':1}).status_code==409
    admin.post('admin/team',{'team':1,'paused':False})
    assert c.post('start',{'missionId':1}).status_code==200

def test_leaderboard_lock_is_server_side(live,admin):
    c=Client(live).join()
    admin.post('admin/control',{'command':'lock'})
    assert c.state()['leaderboard']=={'hidden':True,'rows':[]}
    assert len(admin.get('admin').json()['leaderboard']['rows'])==8
    admin.post('admin/control',{'command':'reveal'})
    assert len(c.state()['leaderboard']['rows'])==8

def test_automatic_leaderboard_lock(live,admin):
    c=Client(live).join()
    for _ in range(7):assert admin.post('admin/skip',{'team':1,'reason':'Test unavailable exhibit'}).status_code==200
    assert c.state()['leaderboard']=={'hidden':True,'rows':[]}
    assert c.state()['current']['id']==8

def test_reset_current_mission_preserves_other_teams(live,admin,photo):
    c=Client(live).join();other=Client(live).join(2)
    c.post('start',{'missionId':1});send(c,image=photo)
    c.post('hint',{'missionId':1,'index':0});c.post('hint',{'missionId':1,'index':1})
    assert c.state()['team']['score']==8
    assert admin.post('admin/reset-mission',{'team':1,'confirmation':'RESET MISSION','reason':'Restart broken photo task'}).status_code==200
    s=c.state()
    assert s['team']['score']==0 and s['team']['scoreParts']['mission']==0 and s['team']['scoreParts']['hint']==0
    assert s['current']['stageIndex']==0 and not s['current']['started']
    assert not s['submissions']
    assert other.state()['current']['id']==2
    c.post('start',{'missionId':1});assert send(c,image=photo).status_code==200
    assert c.state()['team']['score']==10

def test_editor_requires_pause_and_validates_answers(live,admin):
    m=make_missions()[0]
    assert admin.post('admin/mission',{'id':1,'mission':m}).status_code==409
    admin.post('admin/control',{'command':'pause'})
    m['title']='Edited treasure';m['verified']=True
    assert admin.post('admin/mission',{'id':1,'mission':m}).status_code==200
    assert admin.get('admin').json()['missions'][0]['title']=='Edited treasure'
    m['stages'][1]['accepted']=[];m['stages'][1]['keywords']=[]
    assert admin.post('admin/mission',{'id':1,'mission':m}).status_code==400

def test_real_event_requires_recce(admin):
    assert admin.post('admin/settings',{'rehearsal':False}).status_code==200
    assert admin.post('admin/control',{'command':'start'}).status_code==409

def test_removed_player_loses_access(live,admin):
    c=Client(live).join()
    pid=c.state()['player']['id']
    admin.post('admin/remove-player',{'id':pid})
    assert c.get('state').status_code==401

def test_sessions_persist_when_new_app_uses_same_data(app,monkeypatch):
    c=Client(app).join()
    cookies=c.client.cookies
    app2=create_app(app.state.store.directory,testing=True)
    client2=TestClient(app2);client2.cookies.update(cookies)
    assert client2.get('/api/state').status_code==200
    assert client2.get('/api/state').json()['player']['name']=='Test Player'

def test_announcements_target_own_team(live,admin):
    a=Client(live).join(1);b=Client(live).join(2)
    admin.post('admin/announce',{'team':1,'message':'Team 1 private notice'})
    assert a.state()['announcements'][0]['message']=='Team 1 private notice'
    assert not b.state()['announcements']
    assert 'Team 1 private notice' not in json.dumps(b.state()['config'])

def test_backup_csv_and_qr(app,admin):
    backup=admin.get('backup')
    assert backup.status_code==200
    z=zipfile.ZipFile(io.BytesIO(backup.content))
    assert 'city-hunt.sqlite3' in z.namelist()
    assert admin.get('qr').headers['content-type']=='image/png'
    r=admin.get('export?kind=scores')
    assert r.status_code==200 and 'Team,Score' in r.text
    assert admin.get('export?kind=nonsense').status_code==400

def test_strong_reset_confirmation_and_backup(live,admin,photo):
    c=Client(live).join();c.post('start',{'missionId':1});send(c,image=photo)
    assert admin.post('admin/reset',{'confirmation':'wrong'}).status_code==400
    assert admin.post('admin/reset',{'confirmation':'RESET CITY HUNT'}).status_code==409
    admin.post('admin/control',{'command':'pause'})
    assert admin.post('admin/reset',{'confirmation':'RESET CITY HUNT'}).status_code==200
    assert c.get('state').status_code==401
    assert admin.get('admin').json()['config']['status']=='lobby'
    assert len(list(live.state.store.backups.glob('*.zip')))==1

def test_full_eight_team_game_max_370(live,admin,photo):
    missions={m['id']:m for m in make_missions()}
    for team_id in range(1,9):
        c=Client(live).join(team_id)
        visited=[]
        for sequence in range(9):
            mid=c.state()['current']['id'];visited.append(mid)
            assert c.post('start',{'missionId':mid}).status_code==200
            for stage in missions[mid]['stages']:
                if stage['type'] in {'photo','team'}:r=send(c,image=photo)
                elif stage.get('grading')=='manual':r=send(c,answer='A thoughtful observation linked to our chosen display.')
                elif stage['type'] in {'text','puzzle','observation'}:r=send(c,answer=stage['accepted'][0])
                else:r=send(c,answer=stage['correct'])
                assert r.status_code==200, r.text
            assert r.json()['missionComplete']
        assert visited==live.state.store.route({'id':team_id})
        s=c.state();assert s['team']['finished'] and s['team']['completed']==8 and s['current'] is None
        for sub in s['submissions']:
            assert admin.post('admin/review',{'id':sub['id'],'points':sub['maxPoints']}).status_code==200
        assert c.state()['team']['score']==370
        assert c.state()['team']['scoreParts']['mission']==320
        assert c.state()['team']['scoreParts']['final']==50
    rows=admin.get('admin').json()['leaderboard']['rows']
    assert [r['score'] for r in rows]==[370]*8
    assert [r['id'] for r in rows]==list(range(1,9))

@pytest.mark.parametrize('stage,answer,result',[
    ({'type':'text','accepted':['The Merlion']},'  THE   MERLION!! ',True),
    ({'type':'text','accepted':[],'keywords':['park']},'parking',False),
    ({'type':'text','accepted':[],'keywords':['green space'],'matchMode':'all_keywords'},'A green space for everyone',True),
    ({'type':'number','correct':6,'tolerance':.1},'6.05',True),
    ({'type':'number','correct':6},'NaN',False),
    ({'type':'number','minAnswer':4,'maxAnswer':6},'5',True),
    ({'type':'choice','correct':'A'},'B',False),
    ({'type':'multi','correct':['A','B']},['B','A'],True),
    ({'type':'multi','correct':['A','B']},['A','B','C'],False),
    ({'type':'matching','correct':{'a':'Housing','b':'Transport'}},{'a':'Housing','b':'Transport'},True),
    ({'type':'ordering','correct':['b','a']},['a','b'],False),
    ({'type':'puzzle','accepted':['GREEN']},'green',True),
])
def test_question_engine(stage,answer,result):
    assert is_correct(stage,answer)==result
