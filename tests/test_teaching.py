import json
import uuid

import pytest

from app import core, llm, teaching
from test_app import client, model, register, SOURCE, next_question
from test_topics import organizer, upload_deck


def plan():
    return teaching.TeachingPlan(points=[
        teaching.OutlinePoint(keyword="建立连接的过程", expected="说明双方依次交换三条报文的过程。", evidence_ids=["p1-1"]),
        teaching.OutlinePoint(keyword="SYN / ACK 的作用", expected="说明确认的对象是双方各自的初始序列号。", evidence_ids=["p2-1"]),
    ])


def review(first="covered", second="missing", quote="u1-1", corrections=None):
    return teaching.TeachingReview(explanation="过程已经讲清，还可以补充两种标志的作用。", coverage=[
        teaching.Coverage(point_id="outline-1", status=first, note="说明了报文发送过程。", student_evidence_ids=[quote]),
        teaching.Coverage(point_id="outline-2", status=second, note="请展开两个标志的作用。", student_evidence_ids=[] if second=="missing" else ['u2-1']),
    ], corrections=corrections or [], suggestion="可以继续补充标志的作用，不必重复整个过程。")


def start_teaching(c, ident):
    response=c.post('/api/sessions',json={'course_id':ident,'topics':['topic-1'],'mode':'teach','request_key':str(uuid.uuid4())})
    assert response.status_code==200,response.text
    sid=response.json()['id']
    return sid,next_question(c,sid,mode='teach')


def test_teaching_has_private_cross_page_checkpoints_and_public_outline(client,organizer,monkeypatch):
    register(client);ident=upload_deck(client);client.post(f'/api/courses/{ident}/outline')
    async def fake(prompt,schema):
        assert schema is teaching.TeachingPlan
        assert 'p1-1' in prompt and 'p2-1' in prompt
        return plan()
    monkeypatch.setattr(llm,'structured',fake)
    sid,tid=start_teaching(client,ident)
    result=client.get('/api/sessions/'+sid).json()['turns'][0]
    assert result['teaching_brief']['title']=='握手与双方确认'
    assert [x['keyword'] for x in result['teaching_brief']['outline']]==['建立连接的过程','SYN / ACK 的作用']
    assert result['source_page_numbers']==[1,2]
    public=json.dumps(result,ensure_ascii=False)
    assert 'expected' not in public and 'reference_answer' not in public and 'checkpoints' not in public
    assert '说明双方依次交换三条报文的过程' not in public
    with core.db() as c:
        material=json.loads(c.execute('SELECT material FROM turns WHERE id=?',(tid,)).fetchone()[0])
    assert len(material['source_pages'])==2 and '第 2 页' in material['source_text']
    client.put(f'/api/courses/{ident}/pages/2',json={'title':'修改','text':SOURCE+'新增条件','confirmed':True})
    assert client.post(f'/api/turns/{tid}/answer',json={'answer':'客户端先发SYN','request_key':str(uuid.uuid4())}).status_code==409


def test_supplement_is_evaluated_with_original_teaching_and_dispute_history(client,organizer,monkeypatch):
    register(client);ident=upload_deck(client);client.post(f'/api/courses/{ident}/outline')
    prompts=[]
    async def fake(prompt,schema):
        if schema is teaching.TeachingPlan:return plan()
        prompts.append(prompt)
        return review(second='covered') if 'ACK确认双方序列号' in prompt else review()
    monkeypatch.setattr(llm,'structured',fake)
    sid,tid=start_teaching(client,ident)
    a=client.post(f'/api/turns/{tid}/answer',json={'answer':'客户端先发SYN','request_key':str(uuid.uuid4())}).json()
    assert a['feedback']['verdict']=='partial' and not a['feedback']['corrections']
    assert a['feedback']['coverage'][1]['status']=='missing'
    b=client.post(f'/api/turns/{tid}/answer',json={'answer':'补充：ACK确认双方序列号','request_key':str(uuid.uuid4())}).json()
    assert b['feedback']['verdict']=='correct' and b['independent'] is False
    assert b['feedback']['coverage'][0]['student_quote']=='客户端先发SYN'
    assert b['feedback']['coverage'][1]['student_quote']=='补充：ACK确认双方序列号'
    assert '客户端先发SYN' in prompts[-1] and 'ACK确认双方序列号' in prompts[-1]
    response=client.post(f"/api/attempts/{b['id']}/dispute",json={'reason':'请连同先前讲授一起核对'})
    assert response.status_code==200
    assert '客户端先发SYN' in prompts[-1] and '之前的讲授' in prompts[-1]


@pytest.mark.asyncio
async def test_missing_and_incorrect_are_separate_and_corrections_are_grounded(monkeypatch):
    page={'number':1,'title':'TCP','text':SOURCE,'related_pages':[{'number':1,'title':'TCP','text':SOURCE},{'number':2,'title':'作用','text':SOURCE}]}
    async def make_plan(*args):return plan()
    monkeypatch.setattr(llm,'structured',make_plan)
    material=await llm.generate(page,'teach','基础理解',[])
    async def correct(*args):return review(corrections=[teaching.Correction(claim_id='u1-1',correction='第三次用于确认服务端的初始序列号。',evidence_ids=['p1-1'])])
    monkeypatch.setattr(llm,'structured',correct)
    result=await llm.evaluate(material,'客户端先发SYN，但第三次可以省略',[],'teach')
    assert result['verdict']=='incorrect' and result['coverage'][1]['status']=='missing'
    assert result['corrections'][0]['sources'][0]['page']==1


@pytest.mark.asyncio
async def test_invented_student_quotes_or_missing_coverage_do_not_update_judgment(monkeypatch):
    async def make_plan(*args):return plan()
    monkeypatch.setattr(llm,'structured',make_plan)
    material=await teaching.generate({'number':1,'title':'TCP','text':SOURCE,'related_pages':[{'number':1,'title':'TCP','text':SOURCE},{'number':2,'title':'TCP','text':SOURCE}]},'基础理解')
    async def fabricated(*args):return review(quote='u999-1')
    monkeypatch.setattr(llm,'structured',fabricated)
    with pytest.raises(llm.ModelError,match='原话'):
        await teaching.evaluate(material,'客户端先发SYN',[])
    async def incomplete(*args):
        result=review();result.coverage[1].point_id='outline-99';return result
    monkeypatch.setattr(llm,'structured',incomplete)
    with pytest.raises(llm.ModelError,match='完整提纲'):
        await teaching.evaluate(material,'客户端先发SYN',[])


@pytest.mark.asyncio
async def test_specific_question_cannot_become_a_teaching_outline(monkeypatch):
    async def specific(*args):
        result=plan();result.points[0].keyword='第三次ACK是多少？';return result
    monkeypatch.setattr(llm,'structured',specific)
    with pytest.raises(llm.ModelError,match='关键词'):
        await teaching.generate({'number':1,'title':'TCP','text':SOURCE},'基础理解')


def test_old_question_style_teaching_records_remain_readable(client,monkeypatch):
    from test_app import upload,session
    register(client);sid=session(client,upload(client))
    async def old(*args):
        return {'question':'第三次确认的对象是什么？','reference_answer':'确认服务端初始序列号。','key_points':['服务端'],'evidence':SOURCE[:30],'hint1':'思考服务端','hint2':'回看报文'}
    monkeypatch.setattr(llm,'generate',old)
    tid=next_question(client,sid,mode='teach')
    turn=client.get('/api/sessions/'+sid).json()['turns'][0]
    assert turn['id']==tid and 'teaching_brief' not in turn and turn['mode']=='teach'


def test_next_topic_can_move_on_after_partial_explanation(client,organizer,model):
    register(client);ident=upload_deck(client);client.post(f'/api/courses/{ident}/outline')
    sid=client.post('/api/sessions',json={'course_id':ident,'recommended':True,'mode':'teach','request_key':str(uuid.uuid4())}).json()['id']
    tid=next_question(client,sid,mode='teach')
    client.post(f'/api/turns/{tid}/answer',json={'answer':'还不完整','request_key':str(uuid.uuid4())})
    response=client.post(f'/api/sessions/{sid}/next',json={'mode':'teach','focus':'next','request_key':str(uuid.uuid4())})
    assert response.status_code==200
    turns=client.get('/api/sessions/'+sid).json()['turns']
    assert turns[0]['topic_id']=='topic-1' and turns[1]['topic_id']=='topic-2'
