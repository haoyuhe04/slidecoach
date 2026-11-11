import asyncio
import hashlib
import json
import os
import re
import sqlite3
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from contextlib import suppress
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import chat as chat_engine
from . import core, llm, materials, topics

ROOT = Path(__file__).resolve().parent.parent
locks = defaultdict(asyncio.Lock)
attempt_rates = defaultdict(deque)


@asynccontextmanager
async def lifespan(app):
    core.init_db()
    async def expiration_loop():
        while True:
            await asyncio.sleep(60)
            try:
                core.clean_expired()
            except sqlite3.OperationalError:
                # Retry on the next sweep if another transaction temporarily owns the DB.
                pass
    cleanup = asyncio.create_task(expiration_loop())
    try:
        yield
    finally:
        cleanup.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup


app = FastAPI(title="SlideCoach", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def public_origins():
    """Only exact, explicitly configured HTTPS origins can cross the proxy."""
    origins = set()
    for value in os.environ.get("SLIDECOACH_ALLOWED_ORIGINS", "").split(","):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if parsed.scheme == "https" and parsed.netloc and not parsed.username and not parsed.password and not parsed.path and not parsed.query and not parsed.fragment:
            origins.add(value)
    return origins


@app.middleware("http")
async def boundaries(request: Request, call_next):
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        same_host = {"http://" + request.headers.get("host", ""), "https://" + request.headers.get("host", "")}
        if origin and origin not in same_host and origin not in public_origins():
            return JSONResponse({"detail": "请求来源不匹配，请从应用页面操作。"}, status_code=403)
        try:
            size = int(request.headers.get("content-length", "0"))
        except ValueError:
            return JSONResponse({"detail": "无效请求。"}, status_code=400)
        if size > materials.MAX_BYTES + 1024 * 1024:
            return JSONResponse({"detail": "文件不能超过 25 MB。"}, status_code=413)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(llm.ModelError)
async def model_error(request, exc):
    return JSONResponse({"detail": str(exc)}, status_code=503)


def current_user(request: Request):
    token = request.cookies.get("slidecoach_session", "")
    with core.db() as c:
        user = c.execute("SELECT users.id,users.name FROM users JOIN auth ON users.id=auth.user_id WHERE auth.token=? AND auth.expires>?", (hashlib.sha256(token.encode()).hexdigest(), core.now())).fetchone()
    if not user:
        raise HTTPException(401, "请先登录。")
    return dict(user)


def owned(table, ident, user):
    assert table in ("courses", "sessions")
    with core.db() as c:
        row = c.execute(f"SELECT * FROM {table} WHERE id=? AND user_id=?", (ident, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "内容不存在或不属于当前账号。")
    return dict(row)


def turn_owned(ident, user):
    with core.db() as c:
        row = c.execute("SELECT turns.* FROM turns JOIN sessions ON turns.session_id=sessions.id WHERE turns.id=? AND sessions.user_id=?", (ident, user["id"])).fetchone()
    if not row:
        raise HTTPException(404, "练习不存在。")
    return dict(row)


def limit_login(request, name):
    k = ((request.client.host if request.client else "local"), name)
    q = attempt_rates[k]
    while q and q[0] < core.now() - 60:
        q.popleft()
    if len(q) >= 10:
        raise HTTPException(429, "尝试过于频繁，请一分钟后再试。")
    q.append(core.now())


class Credentials(BaseModel):
    name: str = Field(min_length=2, max_length=32, pattern=r"^[\w\-\u4e00-\u9fff]+$")
    password: str = Field(min_length=8, max_length=128)


def set_login(response, user_id, request):
    token = core.uid() + core.uid()
    with core.db() as c:
        c.execute("INSERT INTO auth VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user_id, core.now() + 7 * 86400))
    secure = os.environ.get("SLIDECOACH_SECURE_COOKIE") == "1" or request.url.scheme == "https" or request.headers.get("origin", "") in public_origins()
    response.set_cookie("slidecoach_session", token, httponly=True, samesite="lax", secure=secure, max_age=7 * 86400)


@app.post("/api/register")
async def register(data: Credentials, request: Request, response: Response):
    limit_login(request, data.name)
    ident = core.uid()
    hashed = await asyncio.to_thread(core.password_hash, data.password)
    try:
        with core.db() as c:
            c.execute("INSERT INTO users VALUES(?,?,?,?)", (ident, data.name, hashed, core.now()))
    except sqlite3.IntegrityError:
        raise HTTPException(409, "这个用户名已被使用。")
    set_login(response, ident, request)
    return {"id": ident, "name": data.name}


@app.post("/api/login")
async def login(data: Credentials, request: Request, response: Response):
    limit_login(request, data.name)
    with core.db() as c:
        row = c.execute("SELECT * FROM users WHERE name=?", (data.name,)).fetchone()
    if not row or not await asyncio.to_thread(core.password_ok, data.password, row["password"]):
        raise HTTPException(401, "用户名或密码不正确。")
    set_login(response, row["id"], request)
    return {"id": row["id"], "name": row["name"]}


@app.post("/api/logout")
async def logout(request: Request, response: Response, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        with core.db() as c:
            c.execute("DELETE FROM auth WHERE token=?", (hashlib.sha256(request.cookies.get("slidecoach_session", "").encode()).hexdigest(),))
            c.execute("DELETE FROM sessions WHERE user_id=? AND persist=0", (user["id"],))
            c.execute("DELETE FROM operations WHERE user_id=?", (user["id"],))
    response.delete_cookie("slidecoach_session")
    return {"ok": True}


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


@app.get("/api/health")
def health():
    return {"status": "ok", "model_configured": core.model_configured(), "provider": core.PROVIDER, "model": core.MODEL or None}


@app.get("/api/courses")
def courses(user=Depends(current_user)):
    with core.db() as c:
        return [dict(r) for r in c.execute("SELECT c.id,c.title,c.kind,c.created,count(p.number) as pages FROM courses c LEFT JOIN pages p ON c.id=p.course_id WHERE c.user_id=? GROUP BY c.id ORDER BY c.created DESC", (user["id"],))]


@app.post("/api/courses")
async def upload(file: UploadFile, user=Depends(current_user)):
    blob = await file.read(materials.MAX_BYTES + 1)
    await file.close()
    filename = Path(file.filename or "课件").name[:160]
    sha = hashlib.sha256(blob).hexdigest()
    async with locks["upload:" + user["id"]]:
        with core.db() as c:
            existing = c.execute("SELECT id FROM courses WHERE user_id=? AND sha=?", (user["id"], sha)).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
            total = c.execute("SELECT COUNT(*) FROM courses WHERE user_id=?", (user["id"],)).fetchone()[0]
            if total >= 50:
                raise HTTPException(400, "每个账号最多保存 50 份课件，请先清理不需要的材料。")
        try:
            kind, pages = await asyncio.to_thread(materials.parse_material, blob, filename)
        except materials.MaterialError as exc:
            raise HTTPException(400, str(exc))
        ident = core.uid()
        target = core.DATA / "uploads" / (ident + "." + kind)
        target.write_bytes(blob)
        target.chmod(0o600)
        try:
            with core.db() as c:
                c.execute("INSERT INTO courses VALUES(?,?,?,?,?,?,?)", (ident, user["id"], Path(filename).stem, filename, kind, sha, core.now()))
                c.executemany("INSERT INTO pages VALUES(?,?,?,?,?,?)", [(ident, p["number"], p["title"], p["text"], p["warning"], 0) for p in pages])
        except BaseException:
            target.unlink(missing_ok=True)
            raise
    return {"id": ident, "duplicate": False}


@app.get("/api/courses/{ident}")
def course(ident: str, user=Depends(current_user)):
    row = owned("courses", ident, user)
    with core.db() as c:
        pages = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (ident,))]
        outline = c.execute("SELECT * FROM outlines WHERE course_id=?", (ident,)).fetchone()
    current = topics.fingerprint(pages)
    return {"id": ident, "title": row["title"], "kind": row["kind"], "pages": pages,
            "outline": json.loads(outline["data"]) if outline and outline["fingerprint"] == current else None}


@app.post("/api/courses/{ident}/outline")
async def organize_course(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        owned("courses", ident, user)
        with core.db() as c:
            pages = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (ident,))]
            old = c.execute("SELECT * FROM outlines WHERE course_id=?", (ident,)).fetchone()
        fp = topics.fingerprint(pages)
        if old and old["fingerprint"] == fp:
            return json.loads(old["data"])
        result = await topics.organize(pages)
        with core.db() as c:
            latest = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (ident,))]
            if topics.fingerprint(latest) != fp:
                raise HTTPException(409, "整理期间材料发生变化，请重新整理考点。")
            c.execute("INSERT OR REPLACE INTO outlines VALUES(?,?,?,?)", (ident, fp, core.dump(result), core.now()))
        return result


class ChatInput(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    request_key: str = Field(min_length=12, max_length=100)


def chat_message_view(row):
    return {
        "id": row["id"],
        "role": row["role"],
        "content": row["content"],
        "citations": json.loads(row["citations"]),
        "insufficient": bool(row["insufficient"]),
        "created": row["created"],
    }


@app.get("/api/courses/{ident}/chat")
def get_chat(ident: str, user=Depends(current_user)):
    owned("courses", ident, user)
    with core.db() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT * FROM chat_messages WHERE course_id=? ORDER BY rowid DESC LIMIT 100", (ident,))]
    return {"messages": [chat_message_view(r) for r in reversed(rows)], "model_configured": core.model_configured()}


@app.post("/api/courses/{ident}/chat")
async def send_chat(ident: str, data: ChatInput, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        item = owned("courses", ident, user)
        cached = op_cached(user, data.request_key, "chat:" + ident)
        if cached:
            return cached
        question = data.message.strip()
        if not question:
            raise HTTPException(400, "请先写下你的问题。")
        with core.db() as c:
            count = c.execute("SELECT COUNT(*) FROM chat_messages WHERE course_id=?", (ident,)).fetchone()[0]
            if count >= 100:
                raise HTTPException(400, "这份课件的对话已较多，请清空后再继续。")
            pages = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (ident,))]
            outline = c.execute("SELECT data FROM outlines WHERE course_id=?", (ident,)).fetchone()
            history = [dict(r) for r in c.execute(
                "SELECT role,content FROM chat_messages WHERE course_id=? ORDER BY rowid DESC LIMIT ?",
                (ident, chat_engine.HISTORY_LIMIT))][::-1]
        result = await chat_engine.answer(item, pages, json.loads(outline["data"]) if outline else None, history, question)
        stamp = core.now()
        response = {
            "user": {"id": core.uid(), "role": "user", "content": question, "citations": [],
                     "insufficient": False, "created": stamp},
            "reply": {"id": core.uid(), "role": "assistant", "content": result["answer"],
                      "citations": result["citations"], "insufficient": result["insufficient"], "created": stamp},
        }
        with core.db() as c:
            c.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?,?)", (
                response["user"]["id"], ident, "user", question, "[]", 0, stamp))
            c.execute("INSERT INTO chat_messages VALUES(?,?,?,?,?,?,?)", (
                response["reply"]["id"], ident, "assistant", response["reply"]["content"],
                core.dump(result["citations"]), int(result["insufficient"]), stamp))
            op_save(c, user, data.request_key, "chat:" + ident, response)
        return response


@app.delete("/api/courses/{ident}/chat")
async def clear_chat(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        owned("courses", ident, user)
        with core.db() as c:
            c.execute("DELETE FROM chat_messages WHERE course_id=?", (ident,))
    return {"ok": True}


class PageEdit(BaseModel):
    title: str = Field(min_length=1, max_length=100)
    text: str = Field(max_length=30000)
    confirmed: bool


@app.put("/api/courses/{ident}/pages/{number}")
def edit_page(ident: str, number: int, data: PageEdit, user=Depends(current_user)):
    owned("courses", ident, user)
    if data.confirmed and len(data.text.strip()) < 40:
        raise HTTPException(400, "文字不足以支持出题，请先补充至少 40 字的完整内容。")
    with core.db() as c:
        count = c.execute("UPDATE pages SET title=?,text=?,confirmed=? WHERE course_id=? AND number=?", (data.title, data.text.strip(), data.confirmed, ident, number)).rowcount
        if count:
            # Old answers cite page text that may no longer exist.
            c.execute("DELETE FROM chat_messages WHERE course_id=?", (ident,))
    if not count:
        raise HTTPException(404, "页面不存在。")
    return {"ok": True}


@app.get("/api/courses/{ident}/preview/{number}")
async def preview(ident: str, number: int, user=Depends(current_user)):
    item = owned("courses", ident, user)
    if item["kind"] != "pdf":
        raise HTTPException(400, "PPTX 提供文本视图；需要原版式预览可上传 PDF。")
    try:
        png = await asyncio.to_thread(materials.preview_pdf, core.DATA / "uploads" / (ident + ".pdf"), number)
    except materials.MaterialError as exc:
        raise HTTPException(404, str(exc))
    return Response(png, media_type="image/png")


@app.get("/api/courses/{ident}/download")
def download(ident: str, user=Depends(current_user)):
    item = owned("courses", ident, user)
    return FileResponse(core.DATA / "uploads" / (ident + "." + item["kind"]), filename=item["filename"], media_type="application/octet-stream")


@app.delete("/api/courses/{ident}")
async def delete_course(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        item = owned("courses", ident, user)
        with core.db() as c:
            c.execute("DELETE FROM courses WHERE id=?", (ident,))
            c.execute("DELETE FROM operations WHERE user_id=?", (user["id"],))
        (core.DATA / "uploads" / (ident + "." + item["kind"])).unlink(missing_ok=True)
    return {"ok": True}


class NewSession(BaseModel):
    course_id: str
    pages: list[int] = Field(default_factory=list, max_length=12)
    topics: list[str] = Field(default_factory=list, max_length=6)
    recommended: bool = False
    mode: Literal["quiz", "teach"] = "quiz"
    level: Literal["基础理解", "辨析与应用"] = "基础理解"
    minutes: int = Field(default=10, ge=0, le=120)
    persist: bool = True
    request_key: str = Field(min_length=12, max_length=100)


def op_cached(user, key, route):
    with core.db() as c:
        r = c.execute("SELECT response FROM operations WHERE user_id=? AND key=? AND route=?", (user["id"], key, route)).fetchone()
        return json.loads(r[0]) if r else None


def op_save(c, user, key, route, response):
    c.execute("INSERT INTO operations VALUES(?,?,?,?,?)", (user["id"], key, route, core.dump(response), core.now()))


@app.post("/api/sessions")
async def new_session(data: NewSession, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        cached = op_cached(user, data.request_key, "session")
        if cached:
            return cached
        owned("courses", data.course_id, user)
        numbers = sorted(set(data.pages))
        plan = []
        with core.db() as c:
            pages = {r["number"]: dict(r) for r in c.execute("SELECT * FROM pages WHERE course_id=?", (data.course_id,))}
            outline = c.execute("SELECT * FROM outlines WHERE course_id=?", (data.course_id,)).fetchone()
        if data.topics or data.recommended:
            fp = topics.fingerprint(sorted(pages.values(), key=lambda p: p["number"]))
            if not outline or outline["fingerprint"] != fp:
                raise HTTPException(409, "请先完成课件考点整理；材料修改后需要重新整理。")
            available = json.loads(outline["data"])["topics"]
            if data.recommended:
                count = 2 if 0 < data.minutes <= 10 else 3 if data.minutes else len(available)
                plan = available[:count]
            else:
                selected = set(data.topics)
                if not selected.issubset({t["id"] for t in available}):
                    raise HTTPException(400, "考点已变更，请重新选择。")
                plan = [t for t in available if t["id"] in selected]
            plan = [{**t, "course_fingerprint": fp} for t in plan]
            numbers = sorted({n for t in plan for n in t["pages"]})
            if not numbers or any(n not in pages or not topics.readable(pages[n]) for n in numbers):
                raise HTTPException(400, "所选考点缺少可读依据，请重新整理材料。")
        elif not numbers or any(n not in pages or not pages[n]["confirmed"] or len(pages[n]["text"].strip()) < 40 for n in numbers):
            raise HTTPException(400, "请先核对并确认每个选中页面的内容。")
        ident = core.uid()
        response = {"id": ident}
        with core.db() as c:
            if plan:
                c.executemany("UPDATE pages SET confirmed=2 WHERE course_id=? AND number=? AND confirmed=0", [(data.course_id, n) for n in numbers])
            c.execute("INSERT INTO sessions(id,user_id,course_id,page_numbers,mode,level,minutes,persist,status,created,updated,topic_plan) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (ident, user["id"], data.course_id, core.dump(numbers), data.mode, data.level, data.minutes, data.persist, "active", core.now(), core.now(), core.dump(plan)))
            op_save(c, user, data.request_key, "session", response)
        return response


def session_view(ident, user):
    session = owned("sessions", ident, user)
    with core.db() as c:
        turns = [dict(t) for t in c.execute("SELECT * FROM turns WHERE session_id=? ORDER BY rowid", (ident,))]
        for t in turns:
            material = json.loads(t["material"])
            if material.get("teaching_version") == 1:
                t["teaching_brief"] = {"title": material["teaching_title"], "outline": material["outline"],
                                       "instruction": f"请根据这些关键词，用自己的话向 AI 同学讲解{material['teaching_title']}。你可以自行组织讲解顺序。"}
                t["source_page_numbers"] = [p["number"] for p in material["source_pages"]]
            t.pop("material")  # Never send reference answers before reveal.
            t["attempts"] = []
            for a in c.execute("SELECT * FROM attempts WHERE turn_id=? ORDER BY rowid", (t["id"],)):
                a = dict(a)
                a["feedback"] = json.loads(a["feedback"])
                a["review"] = json.loads(a["review"]) if a["review"] else None
                t["attempts"].append(a)
    session["page_numbers"] = json.loads(session["page_numbers"])
    session["topic_plan"] = json.loads(session["topic_plan"])
    by_id = {t["id"]: t for t in session["topic_plan"]}
    for turn in turns:
        turn["topic_title"] = by_id.get(turn["topic_id"], {}).get("title", "")
    session["turns"] = turns
    return session


@app.get("/api/sessions")
def sessions(user=Depends(current_user)):
    with core.db() as c:
        c.execute("DELETE FROM sessions WHERE user_id=? AND persist=0 AND updated<?", (user["id"], core.now() - 86400))
        return [dict(r) for r in c.execute("SELECT s.*,c.title FROM sessions s JOIN courses c ON s.course_id=c.id WHERE s.user_id=? ORDER BY s.updated DESC", (user["id"],))]


@app.get("/api/sessions/{ident}")
def get_session(ident: str, user=Depends(current_user)):
    return session_view(ident, user)


class NextTurn(BaseModel):
    request_key: str = Field(min_length=12, max_length=100)
    mode: Literal["quiz", "teach"]
    focus: Literal["adaptive", "same", "next"] = "adaptive"


@app.post("/api/sessions/{ident}/next")
async def next_turn(ident: str, data: NextTurn, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        session = owned("sessions", ident, user)
        if session["status"] == "ended":
            raise HTTPException(409, "这轮已结束，请从课程页面新建一轮。")
        cached = op_cached(user, data.request_key, "next:" + ident)
        if cached:
            return cached
        numbers = json.loads(session["page_numbers"])
        plan = json.loads(session["topic_plan"])
        active_topic = None
        with core.db() as c:
            turns = [dict(t) for t in c.execute("SELECT * FROM turns WHERE session_id=? ORDER BY rowid", (ident,))]
            if len(turns) >= 50:
                raise HTTPException(400, "本轮已达 50 题，请回顾后开启新一轮。")
            last = turns[-1] if turns else None
            latest = c.execute("SELECT * FROM attempts WHERE turn_id=? ORDER BY rowid DESC LIMIT 1", (last["id"],)).fetchone() if last else None
            stay = last and (data.focus == "same" or (data.focus != "next" and latest and not latest["disputed"] and json.loads(latest["review"] or latest["feedback"])["verdict"] in ("partial", "incorrect")))
            if plan:
                all_pages = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (session["course_id"],))]
                if topics.fingerprint(all_pages) != plan[0]["course_fingerprint"]:
                    raise HTTPException(409, "课件已更新，请重新整理考点并开启新一轮；旧记录仍保留。")
                if stay:
                    active_topic = next((t for t in plan if t["id"] == last["topic_id"]), None)
                if not active_topic:
                    choices = [t for t in plan if not (data.focus == "next" and last and t["id"] == last["topic_id"])] or plan
                    active_topic = min(choices, key=lambda topic: sum(t["topic_id"] == topic["id"] for t in turns))
                candidates = active_topic["pages"]
                number = min(candidates, key=lambda n: (sum(t["topic_id"] == active_topic["id"] and t["page_number"] == n for t in turns), n != active_topic["evidence_page"], n))
            elif stay:
                number = last["page_number"]
            else:
                counts = {n: sum(t["page_number"] == n for t in turns) for n in numbers}
                number = min(numbers, key=lambda n: (counts[n], n))
            row = c.execute("SELECT * FROM pages WHERE course_id=? AND number=?", (session["course_id"], number)).fetchone()
            page = dict(row) if row else None
        if not page or not page["confirmed"]:
            raise HTTPException(409, "来源页已变更或未确认，请先重新核对。")
        if active_topic:
            page["topic"] = {"title": active_topic["title"], "objective": active_topic["objective"]}
        if data.mode == "teach":
            related = active_topic["pages"] if active_topic else [number]
            with core.db() as c:
                page["related_pages"] = [dict(p) for p in c.execute("SELECT * FROM pages WHERE course_id=? ORDER BY number", (session["course_id"],)) if p["number"] in related and p["confirmed"]]
        question = await llm.generate(page, data.mode, session["level"], [t["question"] for t in turns if t["topic_id"] == active_topic["id"]] if active_topic else [t["question"] for t in turns if t["page_number"] == number])
        if question.get("teaching_version") != 1:
            question["source_text"] = page["text"][:6000]
        question["source_hash"] = hashlib.sha256(page["text"].encode()).hexdigest()
        # Recheck all source snapshots after generation; edits must not race the model call.
        if question.get("teaching_version") == 1:
            check_sources(session["course_id"], question["source_pages"])
        turn_id = core.uid()
        response = {"id": turn_id}
        with core.db() as c:
            c.execute("INSERT INTO turns(id,session_id,page_number,mode,question,material,created,topic_id) VALUES(?,?,?,?,?,?,?,?)", (turn_id, ident, number, data.mode, question["question"], core.dump(question), core.now(), active_topic["id"] if active_topic else ""))
            c.execute("UPDATE sessions SET status='active',mode=?,updated=? WHERE id=?", (data.mode, core.now(), ident))
            op_save(c, user, data.request_key, "next:" + ident, response)
        return response


def check_sources(course_id, snapshots):
    with core.db() as c:
        current = {p["number"]: dict(p) for p in c.execute("SELECT number,text,confirmed FROM pages WHERE course_id=?", (course_id,))}
    for source in snapshots:
        page = current.get(source["number"])
        if not page or not page["confirmed"] or hashlib.sha256(page["text"].encode()).hexdigest() != source["hash"]:
            raise HTTPException(409, "讲授准备后相关课件已修改，请重新生成讲授提纲；原记录仍保留。")


def ensure_current_source(turn, user):
    session = owned("sessions", turn["session_id"], user)
    material = json.loads(turn["material"])
    if material.get("teaching_version") == 1:
        check_sources(session["course_id"], material["source_pages"])
        return session, material
    with core.db() as c:
        page = c.execute("SELECT text,confirmed FROM pages WHERE course_id=? AND number=?", (session["course_id"], turn["page_number"])).fetchone()
    if not page or not page["confirmed"] or hashlib.sha256(page["text"].encode()).hexdigest() != material["source_hash"]:
        raise HTTPException(409, "出题后来源页已修改。请重新生成题目，旧记录保留供核对。")
    return session, material


class Answer(BaseModel):
    answer: str = Field(min_length=1, max_length=6000)
    request_key: str = Field(min_length=12, max_length=100)


@app.post("/api/turns/{ident}/answer")
async def answer(ident: str, data: Answer, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        turn = turn_owned(ident, user)
        cached = op_cached(user, data.request_key, "answer:" + ident)
        if cached:
            return cached
        session, material = ensure_current_source(turn, user)
        if session["status"] == "ended":
            raise HTTPException(409, "这轮已结束。")
        with core.db() as c:
            history = [dict(a) for a in c.execute("SELECT answer,feedback FROM attempts WHERE turn_id=? ORDER BY rowid", (ident,))]
        if not data.answer.strip():
            raise HTTPException(400, "请先写下你的想法，或使用提示。")
        result = await llm.evaluate(material, data.answer.strip(), history, turn["mode"])
        ensure_current_source(turn, user)
        independent = not (turn["hints"] or turn["revealed"] or turn["source_opened"] or history)
        attempt_id = core.uid()
        response = {"id": attempt_id, "feedback": result, "independent": independent}
        with core.db() as c:
            c.execute("INSERT INTO attempts(id,turn_id,answer,feedback,independent,created,request_key) VALUES(?,?,?,?,?,?,?)", (attempt_id, ident, data.answer.strip(), core.dump(result), independent, core.now(), user["id"] + ":" + data.request_key))
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (core.now(), turn["session_id"]))
            op_save(c, user, data.request_key, "answer:" + ident, response)
        return response


class Help(BaseModel):
    kind: Literal["hint1", "hint2", "reveal", "source"]


@app.post("/api/turns/{ident}/help")
async def help_turn(ident: str, data: Help, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        turn = turn_owned(ident, user)
        session, material = ensure_current_source(turn, user)
        with core.db() as c:
            if data.kind.startswith("hint"):
                c.execute("UPDATE turns SET hints=max(hints,?) WHERE id=?", (int(data.kind[-1]), ident))
                result = {"text": material[data.kind]}
            elif data.kind == "reveal":
                c.execute("UPDATE turns SET revealed=1 WHERE id=?", (ident,))
                result = {"text": material["reference_answer"], "key_points": material["key_points"], "evidence": material["evidence"]}
            else:
                c.execute("UPDATE turns SET source_opened=1 WHERE id=?", (ident,))
                result = {"text": material["source_text"], "evidence": material["evidence"], "course_id": session["course_id"], "page": turn["page_number"]}
                if material.get("teaching_version") == 1:
                    result["pages"] = [{"number": p["number"], "title": p["title"]} for p in material["source_pages"]]
            c.execute("UPDATE sessions SET updated=? WHERE id=?", (core.now(), session["id"]))
        return result


class Dispute(BaseModel):
    reason: str = Field(min_length=2, max_length=3000)


@app.post("/api/attempts/{ident}/dispute")
async def dispute(ident: str, data: Dispute, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        with core.db() as c:
            attempt = c.execute("SELECT * FROM attempts WHERE id=?", (ident,)).fetchone()
        if not attempt:
            raise HTTPException(404, "回答不存在。")
        turn = turn_owned(attempt["turn_id"], user)
        _, material = ensure_current_source(turn, user)
        # Persist the dispute before a network call: timeout must not restore a contested grade.
        with core.db() as c:
            c.execute("UPDATE attempts SET disputed=1,dispute_reason=?,review=NULL WHERE id=?", (data.reason, ident))
        with core.db() as c:
            history = [dict(a) for a in c.execute("SELECT answer,feedback FROM attempts WHERE turn_id=? AND rowid<(SELECT rowid FROM attempts WHERE id=?) ORDER BY rowid", (turn["id"], ident))]
        try:
            review = await llm.evaluate(material, attempt["answer"], history, turn["mode"], data.reason)
            ensure_current_source(turn, user)
        except llm.ModelError as exc:
            return {"pending": True, "message": str(exc), "review": None}
        with core.db() as c:
            c.execute("UPDATE attempts SET review=? WHERE id=?", (core.dump(review), ident))
        return {"pending": True, "message": "已生成复核意见，原评价与异议均保留。争议题暂不用于确认掌握，请用新题复测。", "review": review}


@app.post("/api/attempts/{ident}/accept-review")
async def accept_review(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        with core.db() as c:
            row = c.execute("SELECT * FROM attempts WHERE id=?", (ident,)).fetchone()
        if not row:
            raise HTTPException(404, "回答不存在。")
        turn = turn_owned(row["turn_id"], user)
        ensure_current_source(turn, user)
        if not row["review"] or json.loads(row["review"])["verdict"] == "uncertain":
            raise HTTPException(409, "没有可采用的确定复核意见，请先核对材料。")
        with core.db() as c:
            c.execute("UPDATE attempts SET disputed=0 WHERE id=?", (ident,))
    return {"ok": True}


def summary(ident, user):
    session = session_view(ident, user)
    rows = []
    groups = session["topic_plan"] or [{"pages": [n]} for n in session["page_numbers"]]
    for group in groups:
        number = group["pages"][0]
        turns = [t for t in session["turns"] if t["topic_id"] == group["id"]] if "id" in group else [t for t in session["turns"] if t["page_number"] == number]
        answers = [a for t in turns for a in t["attempts"]]
        effective = lambda a: (a["review"] or a["feedback"])["verdict"]
        independent = sum(a["independent"] and not a["disputed"] and effective(a) == "correct" for a in answers)
        assisted = sum(not a["independent"] and not a["disputed"] and effective(a) == "correct" for a in answers)
        disputed = any(a["disputed"] or effective(a) == "uncertain" for a in answers)
        latest = effective(answers[-1]) if answers else None
        if disputed:
            state, action = "待核实", "核对原页与争议记录，再用新题复测"
        elif latest in ("incorrect", "partial"):
            state, action = "仍需巩固", "回看反馈指出的条件，再解释一次"
        elif independent:
            state, action = f"独立答对 {independent} 次", "下次无提示换题再测"
        elif assisted:
            state, action = "帮助后完成", "关闭提示后再试一道新题"
        else:
            state, action = "尚未验证", "完成一次独立作答"
        with core.db() as c:
            page = c.execute("SELECT title FROM pages WHERE course_id=? AND number=?", (session["course_id"], number)).fetchone()
        rows.append({"page": number, "pages": group["pages"], "title": group.get("title") or (page["title"] if page else "来源已删除"), "state": state, "next": action, "independent_correct": independent, "assisted_correct": assisted, "attempts": len(answers)})
    return {"session": session, "rows": rows}


@app.get("/api/sessions/{ident}/summary")
def get_summary(ident: str, user=Depends(current_user)):
    return summary(ident, user)


@app.post("/api/sessions/{ident}/pause")
async def pause(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        owned("sessions", ident, user)
        with core.db() as c:
            c.execute("UPDATE sessions SET status='paused',updated=? WHERE id=?", (core.now(), ident))
    return {"ok": True}


@app.post("/api/sessions/{ident}/end")
async def end(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        result = summary(ident, user)
        with core.db() as c:
            if result["session"]["persist"]:
                c.execute("UPDATE sessions SET status='ended',updated=? WHERE id=?", (core.now(), ident))
            else:
                c.execute("DELETE FROM sessions WHERE id=?", (ident,))
                c.execute("DELETE FROM operations WHERE user_id=?", (user["id"],))
        result["deleted"] = not result["session"]["persist"]
    return result


@app.delete("/api/sessions/{ident}")
async def delete_session(ident: str, user=Depends(current_user)):
    async with locks["user:" + user["id"]]:
        owned("sessions", ident, user)
        with core.db() as c:
            c.execute("DELETE FROM sessions WHERE id=?", (ident,))
            c.execute("DELETE FROM operations WHERE user_id=?", (user["id"],))
    return {"ok": True}


@app.get("/api/demo")
def demo_file():
    return FileResponse(ROOT / "sample" / "TCP复习示例.pptx", filename="TCP复习示例.pptx")


app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})
