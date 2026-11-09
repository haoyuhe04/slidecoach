"""Open teach-back: public keyword outline, private source-backed checkpoints."""
import hashlib

from pydantic import BaseModel, Field
from typing import Literal

from . import core, llm, sources


class OutlinePoint(BaseModel):
    keyword: str = Field(min_length=2, max_length=35)
    expected: str = Field(min_length=8, max_length=350)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class TeachingPlan(BaseModel):
    points: list[OutlinePoint] = Field(min_length=2, max_length=4)


class Coverage(BaseModel):
    point_id: str
    status: Literal["covered", "partial", "missing", "uncertain"]
    note: str = Field(min_length=2, max_length=260)
    student_evidence_ids: list[str] = Field(max_length=3)


class Correction(BaseModel):
    claim_id: str = Field(min_length=4, max_length=40)
    correction: str = Field(min_length=4, max_length=400)
    evidence_ids: list[str] = Field(min_length=1, max_length=3)


class TeachingReview(BaseModel):
    explanation: str = Field(min_length=4, max_length=700)
    coverage: list[Coverage] = Field(min_length=2, max_length=4)
    corrections: list[Correction] = Field(max_length=4)


def source_bundle(page):
    pages = page.get("related_pages") or [page]
    size = min(4000, 12000 // max(1, len(pages)))
    snapshots = [{"number": p["number"], "title": p["title"], "text": p["text"][:size],
                  "hash": hashlib.sha256(p["text"].encode()).hexdigest()} for p in pages]
    fragments = [{**part, "page": p["number"]} for p in snapshots
                 for part in sources.passages(p["text"], p["number"])]
    return snapshots, fragments


async def generate(page, level):
    snapshots, fragments = source_bundle(page)
    if not fragments:
        raise llm.ModelError("本主题没有足够的可读材料，请补充课件文字。")
    topic = page.get("topic") or {"title": page["title"]}
    prompt = f"""为学生自主讲授主题准备一个简短提纲，不要出一道问答题。
主题：{core.dump(topic)}。练习重点：{level}。
给出2至4个关键词式提纲，通常3个。覆盖整个主题的不同方面，学生自行决定组织顺序。
keyword只能是简短名词短语或方面，例如“建立连接的过程”“SYN / ACK的作用”“三次握手的必要性”。
不要问句、问号、具体数值题、填空题；不要在keyword里写结论、解释或标准答案。
expected是该方面最关键的1至2个理解点，只供后台核对，不展示给学生；必须能被所给课件片段支持。
各点职责独立，例如“过程”核对参与方、方向与顺序，“作用”核对标志的含义，“必要性”核对原因；不要在每点重复要求全部细节。
接受概括性讲解，不要求背诵完整课件、固定例子或具体数值；除非关键词本身是计算规则，否则数值例子不作为必要覆盖条件。
每点用evidence_ids选已有片段编号，可跨页。材料不支持的方面不要列入提纲。
只输出JSON points数组，每项包含keyword、expected、evidence_ids。
<课件片段>{core.dump(fragments)}</课件片段>"""
    result = await llm.structured(prompt, TeachingPlan)
    catalog = {f["id"]: f for f in fragments}
    keywords, checkpoints = set(), []
    for index, point in enumerate(result.points, 1):
        keyword = point.keyword.strip()
        if "?" in keyword or "？" in keyword or core.compact(keyword) in keywords:
            raise llm.ModelError("讲授提纲未能形成不同的关键词，请重试生成提纲。")
        keywords.add(core.compact(keyword))
        if not set(point.evidence_ids).issubset(catalog):
            raise llm.ModelError("讲授提纲含无效来源编号，请重新生成。")
        checkpoints.append({"id": f"outline-{index}", **point.model_dump(), "keyword": keyword})
    selected = {ident for point in checkpoints for ident in point["evidence_ids"]}
    parts = [f for f in fragments if f["id"] in selected]
    title = topic["title"]
    return {"teaching_version": 1, "question": f"讲授：{title}", "teaching_title": title,
            "outline": [{"id": p["id"], "keyword": p["keyword"]} for p in checkpoints],
            "checkpoints": checkpoints, "source_pages": snapshots, "source_fragments": fragments,
            "source_text": "\n\n".join(f"第 {p['number']} 页 · {p['title']}\n{p['text']}" for p in snapshots),
            "reference_answer": "\n\n".join(f"{p['keyword']}：{p['expected']}" for p in checkpoints),
            "key_points": [p["expected"] for p in checkpoints],
            "hint1": "先选一个你熟悉的关键词，用自己的话说明它，再讲清楚它与其他关键词的联系。顺序由你决定。",
            "hint2": "可以按“先描述过程，再解释作用，最后说明条件或原因”的方式组织；只需覆盖课件支持的内容。",
            "evidence_ids": [p["id"] for p in parts], "evidence_parts": parts,
            "evidence": "\n…\n".join(f"第 {p['page']} 页：{p['text']}" for p in parts)}


async def evaluate(material, answer, history, dispute=None):
    # Full prior explanations are needed to distinguish omissions from later additions.
    prior = [h["answer"] for h in history]
    cumulative = "\n\n".join([*prior, answer])
    if len(cumulative) > 18000:
        raise llm.ModelError("这轮讲授内容较长，请结束回顾后重新讲一轮，避免遗漏前面的说明。")
    student_parts = [{"id": f"u{index}-{offset//180+1}", "text": text[offset:offset+180],
                      "stage": "本次补充" if index == len(prior)+1 else "之前的讲授"}
                     for index, text in enumerate([*prior, answer], 1)
                     for offset in range(0, len(text), 180) if core.compact(text[offset:offset+180])]
    prompt = f"""你是听课的AI同学。学生已经自主组织了一段讲授，请对照课件检查覆盖情况，不按单道题的标准答案评分。
<私有核对依据>{core.dump(material['checkpoints'])}</私有核对依据>
<课件片段>{core.dump(material['source_fragments'])}</课件片段>
<之前的讲授与本次讲授或补充>{core.dump(student_parts)}</之前的讲授与本次讲授或补充>
综合之前所有讲授与本次补充逐项核对，不要求学生每次重新讲完整篇。明确修正的说法按修正后理解判断。
coverage恰好返回每个point_id一次：covered=该方面的核心意思已经清楚，允许省略次要细节；partial=涉及但核心意思不清；missing=尚未讲到；uncertain=表述或依据无法确定。
特别注意同义表达：已经讲过的意思即使没用expected里的措辞，也视为覆盖。不能一边引用学生明确说过的意思，一边因为“未明确说明”同一个意思判为遗漏。先检查全部先前讲解与补充，再判断真正缺少什么。
covered和partial的student_evidence_ids选用u开头的学生讲解片段编号，可引用之前讲授；不得自行抄写或改写学生原话，程序按编号填回。missing的student_evidence_ids为空数组。
note用一句话指出这一方面已经讲清或还需补充的方向；未讲到时只说明需补充的方面，不把完整正确答案先讲出。按各方面各自的关键点检查，不把其他方面的遗漏重复算到此项。
不要因未讲某个数值例子就判为遗漏（除非该提纲本身要求计算）。遗漏和错误必须区分。
corrections只列学生实际讲错且尚未纠正的说法；claim_id选其u开头的原话片段编号，correction说明具体哪里应如何修正，evidence_ids选择p开头的课件片段。没有明确错误则空数组，不能把未提到的内容说成讲错。
explanation用“你”直接和学生交流，最多两句话说明整体情况，不用“学生”第三人称。不要提出提纲以外的新要求，不在总结里新增具体题目或数值练习。
只输出JSON：explanation、coverage、corrections。"""
    if dispute:
        prompt += f"\n请独立复核原判断，不能默认原评价正确。<学生异议>{dispute}</学生异议>"
    result = await llm.structured(prompt, TeachingReview)
    expected = {p["id"]: p for p in material["checkpoints"]}
    rows = {row.point_id: row for row in result.coverage}
    if len(rows) != len(result.coverage) or rows.keys() != expected.keys():
        raise llm.ModelError("讲授反馈没有覆盖完整提纲，本次不更新记录，请重试。")
    student_catalog = {part["id"]: part["text"] for part in student_parts}
    for row in result.coverage:
        identifiers = row.student_evidence_ids
        if not set(identifiers).issubset(student_catalog) or (row.status in ("covered", "partial") and not identifiers):
            raise llm.ModelError("讲授反馈中的学生原话无法核对，本次不更新记录，请重试。")
        if row.status == "missing" and identifiers:
            raise llm.ModelError("讲授覆盖判断不一致，本次不更新记录，请重试。")
    catalog = {p["id"]: p for p in material["source_fragments"]}
    corrections = []
    for correction in result.corrections:
        if correction.claim_id not in student_catalog or not set(correction.evidence_ids).issubset(catalog):
            raise llm.ModelError("讲授纠错依据无法核对，本次不更新记录，请重试。")
        corrections.append({**correction.model_dump(), "claim": student_catalog[correction.claim_id], "sources": [catalog[i] for i in dict.fromkeys(correction.evidence_ids)]})
    statuses = {row.status for row in result.coverage}
    verdict = "incorrect" if corrections else "uncertain" if "uncertain" in statuses else "partial" if statuses != {"covered"} else "correct"
    remaining = [p["keyword"] for p in material["checkpoints"] if rows[p["id"]].status != "covered"]
    if corrections:
        suggestion = "可以先修正上面标出的理解，再按自己的顺序继续讲解。"
    elif remaining:
        suggestion = "可以继续补充或澄清“" + "”“".join(remaining[:2]) + "”这几部分，不必重复已经讲清的内容。"
    else:
        suggestion = "这份提纲已讲解到位。可以换个例子再讲一轮，或继续下一个主题。"
    return {"kind": "teaching_review", "verdict": verdict, "explanation": result.explanation,
            "next_question": "", "suggestion": suggestion, "corrections": corrections,
            "coverage": [{**rows[p["id"]].model_dump(), "keyword": p["keyword"],
                          "student_quote": "\n…\n".join(student_catalog[i] for i in dict.fromkeys(rows[p["id"]].student_evidence_ids))}
                         for p in material["checkpoints"]]}
