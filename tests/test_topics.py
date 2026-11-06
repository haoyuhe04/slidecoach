import io
import uuid

import pytest
from pptx import Presentation

from app import core, llm, topics
from test_app import client, model, register, next_question, SOURCE


def upload_deck(c):
    ppt = Presentation()
    for title in ["双方确认", "报文方向", "初始序列号", "致谢"]:
        slide = ppt.slides.add_slide(ppt.slide_layouts[1])
        slide.shapes.title.text = title
        slide.placeholders[1].text = SOURCE if title != "致谢" else "谢谢"
    out = io.BytesIO(); ppt.save(out)
    r = c.post('/api/courses', files={'file': ('deck.pptx', out.getvalue())})
    assert r.status_code == 200
    return r.json()['id']


@pytest.fixture
def organizer(monkeypatch):
    calls = []
    async def organized(pages):
        calls.append(pages)
        return {"topics": [
            {"id": "topic-1", "title": "握手与双方确认", "objective": "解释两个确认各自的作用", "pages": [1, 2], "evidence_page": 1, "evidence": SOURCE[:30]},
            {"id": "topic-2", "title": "初始序列号", "objective": "判断确认号的含义", "pages": [3], "evidence_page": 3, "evidence": SOURCE[:30]},
        ], "excluded_pages": [4]}
    monkeypatch.setattr(topics, 'organize', organized)
    return calls


def start(c, ident, **kwargs):
    return c.post('/api/sessions', json={"course_id": ident, "request_key": str(uuid.uuid4()), **kwargs})


def test_upload_to_recommended_session_without_page_confirmation(client, organizer, model):
    register(client)
    ident = upload_deck(client)
    assert all(p['confirmed'] == 0 for p in client.get('/api/courses/' + ident).json()['pages'])
    assert client.post(f'/api/courses/{ident}/outline').status_code == 200
    response = start(client, ident, recommended=True)
    assert response.status_code == 200, response.text
    sid = response.json()['id']
    session = client.get('/api/sessions/' + sid).json()
    assert len(session['topic_plan']) == 2
    assert session['page_numbers'] == [1, 2, 3] and 4 not in session['page_numbers']
    tid = next_question(client, sid)
    turn = client.get('/api/sessions/' + sid).json()['turns'][0]
    assert turn['topic_title'] == '握手与双方确认'
    client.post(f'/api/turns/{tid}/answer', json={'answer': '还没理解', 'request_key': str(uuid.uuid4())})
    next_question(client, sid)
    turn2 = client.get('/api/sessions/' + sid).json()['turns'][1]
    assert turn2['topic_id'] == turn['topic_id'] and turn2['page_number'] != turn['page_number']
    summary = client.get('/api/sessions/' + sid + '/summary').json()['rows']
    assert len(summary) == 2 and summary[0]['pages'] == [1, 2]


def test_custom_topic_scope_and_unknown_ids(client, organizer, model):
    register(client)
    ident = upload_deck(client)
    client.post(f'/api/courses/{ident}/outline')
    assert start(client, ident, topics=['not-real']).status_code == 400
    sid = start(client, ident, topics=['topic-2']).json()['id']
    next_question(client, sid)
    session = client.get('/api/sessions/' + sid).json()
    assert session['page_numbers'] == [3] and session['turns'][0]['topic_title'] == '初始序列号'


def test_outline_cache_and_source_invalidation(client, organizer, model):
    register(client)
    ident = upload_deck(client)
    client.post(f'/api/courses/{ident}/outline')
    client.post(f'/api/courses/{ident}/outline')
    assert len(organizer) == 1
    sid = start(client, ident, recommended=True).json()['id']
    client.put(f'/api/courses/{ident}/pages/1', json={'title': '更新', 'text': SOURCE + '这是新增条件。', 'confirmed': True})
    assert client.get('/api/courses/' + ident).json()['outline'] is None
    assert start(client, ident, recommended=True).status_code == 409
    assert client.post(f'/api/sessions/{sid}/next', json={'mode': 'quiz', 'request_key': str(uuid.uuid4())}).status_code == 409
    client.post(f'/api/courses/{ident}/outline')
    assert len(organizer) == 2


def test_outline_access_is_account_isolated(client, organizer):
    register(client, 'alice')
    ident = upload_deck(client)
    client.post('/api/logout');register(client, 'bob')
    assert client.post(f'/api/courses/{ident}/outline').status_code == 404
    assert not organizer


def test_outline_rejects_fabricated_sources():
    raw={'title':'双方确认','objective':'解释确认的对象','pages':[1,2],'evidence_id':'p1-1'}
    snippets=topics.excerpts([{'number':1,'title':'TCP','text':SOURCE}])
    with pytest.raises(llm.ModelError,match='页面'):
        topics.validated(topics.Outline(topics=[topics.Topic(**raw)]),snippets)
    raw['pages']=[1];raw['evidence_id']='p1-99'
    with pytest.raises(llm.ModelError,match='依据'):
        topics.validated(topics.Outline(topics=[topics.Topic(**raw)]),snippets)
    raw['evidence_id']='p1-1'
    result=topics.validated(topics.Outline(topics=[topics.Topic(**raw)]),snippets)[0]
    assert result['pages']==[1] and result['evidence']==SOURCE[:160]


def test_existing_sessions_survive_schema_upgrade(client, model):
    from test_app import upload, session
    register(client)
    sid=session(client,upload(client));tid=next_question(client,sid)
    with core.db() as c:
        c.execute('ALTER TABLE sessions DROP COLUMN topic_plan')
        c.execute('ALTER TABLE turns DROP COLUMN topic_id')
    core.init_db();core.init_db()
    result=client.get('/api/sessions/'+sid).json()
    assert result['id']==sid and result['turns'][0]['id']==tid and result['topic_plan']==[]


@pytest.mark.asyncio
async def test_short_deck_does_not_expand_into_many_small_topics(monkeypatch):
    async def over_split(*args):
        return topics.Outline(topics=[topics.Topic(title=f'确认视角{i}', objective='解释双方确认的作用', pages=[1], evidence_id='p1-1') for i in range(3)])
    monkeypatch.setattr(llm, 'structured', over_split)
    with pytest.raises(llm.ModelError,match='划分过细'):
        await topics.organize([{'number':1,'title':'TCP','text':SOURCE}])
