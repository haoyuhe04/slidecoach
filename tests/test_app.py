import io
import json
import uuid
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from pptx import Presentation

from app import core, llm, materials
from app.main import app, locks, attempt_rates

SOURCE = "TCP 通过三次握手同步双方的初始序列号。第二次报文确认客户端的 SYN，并携带服务端的 SYN。第三次报文由客户端发送，用来确认服务端的初始序列号。SYN 占用一个序列号。"


def deck(text=SOURCE):
    p = Presentation()
    slide = p.slides.add_slide(p.slide_layouts[1])
    slide.shapes.title.text = "TCP 三次握手"
    slide.placeholders[1].text = text
    out = io.BytesIO()
    p.save(out)
    return out.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "DATA", tmp_path)
    monkeypatch.setattr(core, "DB", tmp_path / "test.sqlite3")
    locks.clear()
    attempt_rates.clear()
    llm.reservations.clear()
    with TestClient(app) as c:
        yield c


def register(c, name="testuser"):
    r = c.post("/api/register", json={"name": name, "password": "test-password-42"})
    assert r.status_code == 200, r.text
    return r.json()


def test_public_frontend_origin_and_secure_cookie(client, monkeypatch):
    monkeypatch.setenv("SLIDECOACH_ALLOWED_ORIGINS", "https://slidecoach.example/")
    result = client.post("/api/register", headers={"Origin": "https://slidecoach.example"}, json={"name": "public-user", "password": "test-password-42"})
    assert result.status_code == 200
    cookie = result.headers["set-cookie"].lower()
    assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "domain=" not in cookie


def test_untrusted_proxy_origins_are_rejected(client, monkeypatch):
    monkeypatch.setenv("SLIDECOACH_ALLOWED_ORIGINS", "https://slidecoach.example,http://untrusted.example,https://wrong.example/path")
    for origin in ("https://slidecoach.example.evil.test", "https://different.vercel.app", "http://untrusted.example", "https://wrong.example"):
        result = client.post("/api/register", headers={"Origin": origin}, json={"name": "blocked", "password": "test-password-42"})
        assert result.status_code == 403


def test_forwarded_host_does_not_bypass_origin_check(client, monkeypatch):
    monkeypatch.delenv("SLIDECOACH_ALLOWED_ORIGINS", raising=False)
    result = client.post("/api/register", headers={"Origin": "https://attacker.example", "X-Forwarded-Host": "attacker.example"}, json={"name": "blocked", "password": "test-password-42"})
    assert result.status_code == 403


def upload(c):
    r = c.post("/api/courses", files={"file": ("测试课件.pptx", deck())})
    assert r.status_code == 200, r.text
    ident = r.json()["id"]
    page = c.get("/api/courses/" + ident).json()["pages"][0]
    r = c.put(f"/api/courses/{ident}/pages/1", json={"title": page["title"], "text": page["text"], "confirmed": True})
    assert r.status_code == 200
    return ident


def session(c, course_id, persist=True):
    r = c.post("/api/sessions", json={"course_id": course_id, "pages": [1], "persist": persist, "request_key": str(uuid.uuid4())})
    assert r.status_code == 200, r.text
    return r.json()["id"]


@pytest.fixture
def model(monkeypatch):
    async def generate(page, mode, level, previous):
        return {"question": f"请解释第三次报文确认了什么？第{len(previous)+1}种角度", "reference_answer": "确认服务端的初始序列号。", "key_points": ["确认服务端"], "evidence": "第三次报文由客户端发送，用来确认服务端的初始序列号。", "hint1": "从服务端视角想一想。", "hint2": "比较两次确认的对象。"}
    async def evaluate(material, answer, history, mode, dispute=None):
        return {"verdict": "correct" if answer == "确认服务端" else "partial", "explanation": "这里的确认对象是服务端的初始序列号。", "next_question": "请说明依据。"}
    monkeypatch.setattr(llm, "generate", generate)
    monkeypatch.setattr(llm, "evaluate", evaluate)


def next_question(c, s, key=None, mode="quiz"):
    r = c.post(f"/api/sessions/{s}/next", json={"request_key": key or str(uuid.uuid4()), "mode": mode})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_full_learning_evidence_and_idempotency(client, model):
    register(client)
    course = upload(client)
    s = session(client, course)
    key = str(uuid.uuid4())
    t = next_question(client, s, key)
    assert next_question(client, s, key) == t
    public = client.get(f"/api/sessions/{s}").json()
    assert "reference_answer" not in json.dumps(public)
    assert "evidence" not in json.dumps(public)
    akey = str(uuid.uuid4())
    payload = {"answer": "确认服务端", "request_key": akey}
    a = client.post(f"/api/turns/{t}/answer", json=payload).json()
    assert a["independent"] is True
    assert client.post(f"/api/turns/{t}/answer", json=payload).json()["id"] == a["id"]
    rows = client.get(f"/api/sessions/{s}/summary").json()["rows"]
    assert rows[0]["independent_correct"] == 1
    assert rows[0]["attempts"] == 1
    t2 = next_question(client, s, mode="teach")
    help_response = client.post(f"/api/turns/{t2}/help", json={"kind": "source"})
    assert help_response.json()["page"] == 1
    helped = client.post(f"/api/turns/{t2}/answer", json={"answer": "确认服务端", "request_key": str(uuid.uuid4())}).json()
    assert helped["independent"] is False
    rows = client.get(f"/api/sessions/{s}/summary").json()["rows"]
    assert rows[0]["assisted_correct"] == 1
    assert rows[0]["independent_correct"] == 1


def test_dispute_survives_model_outage(client, model, monkeypatch):
    register(client)
    s = session(client, upload(client))
    t = next_question(client, s)
    a = client.post(f"/api/turns/{t}/answer", json={"answer": "确认服务端", "request_key": str(uuid.uuid4())}).json()
    async def unavailable(*args, **kwargs):
        raise llm.ModelError("测试超时")
    monkeypatch.setattr(llm, "evaluate", unavailable)
    r = client.post(f"/api/attempts/{a['id']}/dispute", json={"reason": "请核对课件条件"})
    assert r.status_code == 200 and r.json()["pending"]
    row = client.get(f"/api/sessions/{s}/summary").json()["rows"][0]
    assert row["state"] == "待核实" and row["independent_correct"] == 0


def test_material_edit_blocks_stale_grading(client, model):
    register(client)
    course = upload(client)
    s = session(client, course)
    t = next_question(client, s)
    client.put(f"/api/courses/{course}/pages/1", json={"title": "改正后的页", "text": SOURCE + "这里补充新的条件。", "confirmed": True})
    r = client.post(f"/api/turns/{t}/answer", json={"answer": "确认服务端", "request_key": str(uuid.uuid4())})
    assert r.status_code == 409
    assert not client.get(f"/api/sessions/{s}").json()["turns"][0]["attempts"]


def test_review_requires_explicit_acceptance_and_preserves_original(client, model, monkeypatch):
    register(client)
    s = session(client, upload(client))
    t = next_question(client, s)
    a = client.post(f'/api/turns/{t}/answer', json={'answer': '用自己的话解释确认对象', 'request_key': str(uuid.uuid4())}).json()
    async def corrected(*args, **kwargs):
        return {'verdict': 'correct', 'explanation': '原评价遗漏了等价表述，现予更正。', 'next_question': ''}
    monkeypatch.setattr(llm, 'evaluate', corrected)
    client.post(f"/api/attempts/{a['id']}/dispute", json={'reason': '我的表述与课件意思相同'})
    assert client.get(f'/api/sessions/{s}/summary').json()['rows'][0]['state'] == '待核实'
    assert client.post(f"/api/attempts/{a['id']}/accept-review").status_code == 200
    row = client.get(f'/api/sessions/{s}/summary').json()['rows'][0]
    assert row['independent_correct'] == 1
    original = client.get(f'/api/sessions/{s}').json()['turns'][0]['attempts'][0]
    assert original['feedback']['verdict'] == 'partial'
    assert original['review']['verdict'] == 'correct' and original['dispute_reason']


def test_account_isolation_and_csrf(client, model):
    register(client, "alice")
    course = upload(client)
    s = session(client, course)
    t = next_question(client, s)
    client.post("/api/logout")
    register(client, "bob")
    for url in (f"/api/courses/{course}", f"/api/courses/{course}/download", f"/api/courses/{course}/preview/1", f"/api/sessions/{s}"):
        assert client.get(url).status_code == 404
    assert client.post(f"/api/turns/{t}/help", json={"kind": "reveal"}).status_code == 404
    assert client.delete(f"/api/courses/{course}").status_code == 404
    assert client.post("/api/logout", headers={"Origin": "https://evil.example"}).status_code == 403


def test_temporary_session_purges_answers_and_operation_cache(client, model):
    user = register(client)
    s = session(client, upload(client), persist=False)
    t = next_question(client, s)
    client.post(f"/api/turns/{t}/answer", json={"answer": "确认服务端", "request_key": str(uuid.uuid4())})
    r = client.post(f"/api/sessions/{s}/end")
    assert r.json()["deleted"] is True
    assert client.get(f"/api/sessions/{s}").status_code == 404
    with core.db() as c:
        assert c.execute("SELECT count(*) FROM attempts").fetchone()[0] == 0
        assert c.execute("SELECT count(*) FROM operations WHERE user_id=?", (user["id"],)).fetchone()[0] == 0


def test_upload_validation_confirmation_duplicate(client):
    register(client)
    assert client.post("/api/courses", files={"file": ("fake.pdf", b"bad")}).status_code == 400
    r = client.post("/api/courses", files={"file": ("test.pptx", deck())})
    ident = r.json()["id"]
    assert client.post("/api/courses", files={"file": ("test.pptx", deck())}).json()["duplicate"] is True
    assert client.post("/api/sessions", json={"course_id": ident, "pages": [1], "request_key": str(uuid.uuid4())}).status_code == 400
    assert client.put(f"/api/courses/{ident}/pages/1", json={"title": "空", "text": "不够", "confirmed": True}).status_code == 400


def test_unconfigured_model_does_not_fake_a_question(client, monkeypatch):
    register(client)
    s = session(client, upload(client))
    monkeypatch.setattr(core, "MODEL", "")
    r = client.post(f"/api/sessions/{s}/next", json={"mode": "quiz", "request_key": str(uuid.uuid4())})
    assert r.status_code == 503 and "尚未配置" in r.json()["detail"]
    assert client.get(f"/api/sessions/{s}").json()["turns"] == []


@pytest.mark.asyncio
async def test_source_quote_validation(monkeypatch):
    async def wrong(*args):
        return llm.Question(question="这个问题需要引用依据吗？", reference_answer="这是一个足够长度的参考回答。", key_points=["一"], evidence_ids=["p1-999"], hint1="请先看课件", hint2="再想一想条件")
    monkeypatch.setattr(llm, "structured", wrong)
    with pytest.raises(llm.ModelError, match="无效的来源编号"):
        await llm.generate({"number": 1, "title": "测试", "text": SOURCE}, "quiz", "基础理解", [])


@pytest.mark.asyncio
async def test_question_quotes_are_copied_by_server_not_model(monkeypatch):
    text = '原始课件：\nAPI  → Router\nbooks.id = borrows.book_id\n' + '保持中文标点、空格与换行。' * 30
    async def generated(prompt, schema):
        assert 'evidence_ids' in prompt and 'p7-1' in prompt
        return llm.Question(question='请说明这份课件中各层之间如何协作？',reference_answer='这是模型用自己的话概括的答案，不充当原文引用。',key_points=['职责划分'],evidence_ids=['p7-3','p7-1','p7-1'],hint1='先观察请求方向',hint2='再分析各层职责')
    monkeypatch.setattr(llm,'structured',generated)
    result=await llm.generate({'number':7,'title':'含代码与换行的课件','text':text},'quiz','基础理解',[])
    assert result['evidence']==text[:160]+'\n…\n'+text[320:480]
    assert [p['id'] for p in result['evidence_parts']]==['p7-1','p7-3']
    assert result['reference_answer'] not in result['evidence']


@pytest.mark.asyncio
async def test_empty_question_source_does_not_call_model(monkeypatch):
    async def never(*args):
        pytest.fail('Empty material should not reach the model')
    monkeypatch.setattr(llm,'structured',never)
    with pytest.raises(llm.ModelError,match='可读材料'):
        await llm.generate({'number':1,'title':'空白页','text':'  '},'quiz','基础理解',[])


@pytest.mark.asyncio
async def test_compatible_api_contract(monkeypatch, client):
    monkeypatch.setattr(core, "MODEL", "configured-model")
    monkeypatch.setattr(core, "MODEL_URL", "https://provider.example/v1")
    monkeypatch.setattr(core, "PROVIDER", "openai-compatible")
    monkeypatch.setenv("SLIDECOACH_API_KEY", "synthetic-test-key")
    payload = {"verdict": "partial", "explanation": "请补充确认对象。", "next_question": "谁收到谁的确认？"}
    def handler(request):
        assert str(request.url) == "https://provider.example/v1/chat/completions"
        body = json.loads(request.content)
        assert body["model"] == "configured-model" and body["response_format"] == {"type": "json_object"}
        assert request.headers["authorization"] == "Bearer synthetic-test-key"
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    result = await llm.structured("评估测试回答", llm.Feedback)
    assert result.verdict == "partial"


def test_rate_budget_is_enforced(client):
    for _ in range(10):
        llm.reserve_budget(500)
    with pytest.raises(llm.ModelError, match="额度"):
        llm.reserve_budget(500)
    llm.reservations.clear()
    llm.reserve_budget(200000)
    with pytest.raises(llm.ModelError, match="额度"):
        llm.reserve_budget(100001)


def test_pdf_preview_and_scanned_page_guard(client):
    import pymupdf
    register(client)
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "A SYN consumes one sequence number. An acknowledgement identifies the next expected sequence number.")
    doc.new_page()
    r = client.post('/api/courses', files={'file': ('sample.pdf', doc.tobytes())})
    assert r.status_code == 200
    ident = r.json()['id']
    pages = client.get('/api/courses/' + ident).json()['pages']
    assert len(pages) == 2 and '扫描件' in pages[1]['warning']
    preview = client.get(f'/api/courses/{ident}/preview/1')
    assert preview.status_code == 200 and preview.content.startswith(b'\x89PNG')
    assert client.get(f'/api/courses/{ident}/preview/3').status_code == 404


def test_expiry_cleans_temporary_records_but_keeps_saved_sessions(client):
    register(client)
    course = upload(client)
    temp = session(client, course, persist=False)
    saved = session(client, course, persist=True)
    with core.db() as c:
        c.execute('UPDATE sessions SET updated=?', (core.now() - 90000,))
        c.execute('UPDATE operations SET created=?', (core.now() - 90000,))
    core.clean_expired()
    assert client.get('/api/sessions/' + temp).status_code == 404
    assert client.get('/api/sessions/' + saved).status_code == 200
    with core.db() as c:
        assert c.execute('SELECT COUNT(*) FROM operations').fetchone()[0] == 0
