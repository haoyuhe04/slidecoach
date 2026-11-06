"""Turn a deck into a small, source-backed set of study topics."""
import hashlib

from pydantic import BaseModel, Field

from . import core, llm, sources


def readable(page):
    text = page["text"].strip()
    return len(text) >= 40 and text.count("\ufffd") / max(1, len(text)) < .03


def fingerprint(pages):
    return hashlib.sha256(core.dump([(p["number"], p["title"], p["text"]) for p in pages]).encode()).hexdigest()


def excerpts(pages):
    usable = [p for p in pages if readable(p)]
    budget = min(1800, 18000 // max(1, len(usable)))
    result = []
    for page in usable:
        text = page["text"][:budget]
        passages = sources.passages(text, page["number"])
        result.append({"number": page["number"], "title": page["title"], "text": text, "passages": passages})
    return result


class Topic(BaseModel):
    title: str = Field(min_length=2, max_length=60)
    objective: str = Field(min_length=5, max_length=180)
    pages: list[int] = Field(min_length=1, max_length=100)
    evidence_id: str = Field(min_length=4, max_length=30)


class Outline(BaseModel):
    topics: list[Topic] = Field(min_length=1, max_length=6)


def validated(result, snippets):
    sources = {p["number"]: p["text"] for p in snippets}
    catalog = {part["id"]: (p["number"], part["text"]) for p in snippets for part in p["passages"]}
    titles = set()
    output = []
    for topic in result.topics:
        if core.compact(topic.title) in titles:
            raise llm.ModelError("考点整理出现重复主题，请重试。")
        titles.add(core.compact(topic.title))
        pages = sorted(set(topic.pages))
        if any(n not in sources for n in pages):
            raise llm.ModelError("考点引用了不存在或无法读取的页面，已停止使用本次结果。")
        evidence = catalog.get(topic.evidence_id)
        if not evidence or evidence[0] not in pages:
            raise llm.ModelError("考点的依据未能在课件中找到，请重试整理。")
        output.append({"id": f"topic-{len(output)+1}", **topic.model_dump(), "pages": pages, "evidence_page": evidence[0], "evidence": evidence[1]})
    return output


async def organize(pages):
    snippets = excerpts(pages)
    if not snippets:
        raise llm.ModelError("这份课件暂时没有足够的可读文字。请上传带文本的 PDF，或在“修正识别内容”中补充材料。")
    maximum = 2 if len(snippets) <= 5 else 4 if len(snippets) <= 15 else 6
    prompt = f"""请把以下整份课件整理成少量核心复习考点，帮助学生直接开始复习，无需逐页选择。
本材料共有{len(snippets)}页可读内容，最多只能返回{maximum}个大考点，也可以更少。合并同一概念的相邻或跨页内容，不要按一页一个考点照抄标题，不要为了凑数量拆细。
同一机制的过程、作用、不同参与方视角应归入同一考点；只有可以独立练习的原理、计算规则或应用方法才分开。不同考点的学习目标不能高度重复。
按先基础、后辨析与应用的顺序排列。只根据课件推荐学习顺序，不预测老师命题概率，不声称必考。
忽略封面、目录、致谢和纯参考文献页。title简明说明考点；objective说明学生应能解释或运用什么，而不是题目答案。
pages列出该考点相关的原始页码；evidence_id必须选用下面已有的原文片段id，并且该片段所属页码必须在pages内。选择能够支持学习目标的实质内容，不要只选标题。
不要自行改写或输出引用原文，程序会按evidence_id填回原文。只输出JSON topics数组，每项包括title、objective、pages、evidence_id。
<逐页课件摘录>{core.dump([{k: v for k, v in p.items() if k != 'text'} for p in snippets])}</逐页课件摘录>"""
    result = await llm.structured(prompt, Outline)
    if len(result.topics) > maximum:
        raise llm.ModelError("考点划分过细，未作为推荐结果保存。请重新整理。")
    return {"topics": validated(result, snippets), "excluded_pages": [p["number"] for p in pages if not readable(p)]}
