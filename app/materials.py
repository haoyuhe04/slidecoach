import io
import zipfile
from pathlib import Path

import pymupdf
from pptx import Presentation

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 100


class MaterialError(ValueError):
    pass


def title_of(text, fallback):
    return next((x.strip()[:100] for x in text.splitlines() if x.strip()), fallback)


def shape_text(shape):
    if shape.shape_type == 6:  # GroupShape
        return "\n".join(shape_text(s) for s in shape.shapes)
    if shape.has_table:
        return "\n".join(" | ".join(cell.text for cell in row.cells) for row in shape.table.rows)
    return shape.text if shape.has_text_frame else ""


def parse_material(blob, filename):
    if not blob or len(blob) > MAX_BYTES:
        raise MaterialError("请上传不超过 25 MB 的 PPTX 或 PDF。")
    kind = Path(filename).suffix.lower().lstrip(".")
    try:
        if kind == "pptx":
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                if len(z.infolist()) > 5000 or sum(i.file_size for i in z.infolist()) > 150 * 1024 * 1024:
                    raise MaterialError("课件解压后过大，请拆分后上传。")
                if "ppt/presentation.xml" not in z.namelist():
                    raise MaterialError("这不是有效的 PPTX 文件。")
            slides = Presentation(io.BytesIO(blob)).slides
            if len(slides) > MAX_PAGES:
                raise MaterialError("每份课件最多 100 页，请按章节拆分。")
            pages = []
            for n, slide in enumerate(slides, 1):
                text = "\n".join(filter(None, (shape_text(s) for s in slide.shapes))).strip()
                title = slide.shapes.title.text if slide.shapes.title and slide.shapes.title.has_text_frame else title_of(text, f"第 {n} 页")
                warning = "PPTX 文本视图；图表、公式或动画可能未完整识别，请核对原文件。"
                if len(text.strip()) < 40:
                    warning = "可提取文字不足，可能是图片页。请补充文字或上传带文本的 PDF。"
                pages.append({"number": n, "title": title[:100], "text": text[:30000], "warning": warning, "confirmed": 0})
        elif kind == "pdf":
            with pymupdf.open(stream=blob, filetype="pdf") as doc:
                if doc.needs_pass:
                    raise MaterialError("请先解除 PDF 密码保护，再上传。")
                if len(doc) > MAX_PAGES:
                    raise MaterialError("每份课件最多 100 页，请按章节拆分。")
                pages = []
                for n, page in enumerate(doc, 1):
                    text = page.get_text(sort=True).strip()
                    warning = "可提取文字不足，扫描件暂不自动 OCR；请补充文字后确认。" if len(text) < 40 else "请对照原页核对公式、图表与文字顺序。"
                    pages.append({"number": n, "title": title_of(text, f"第 {n} 页"), "text": text[:30000], "warning": warning, "confirmed": 0})
        else:
            raise MaterialError("支持 .pptx 和 .pdf；旧版 .ppt 请先另存为 .pptx。")
    except MaterialError:
        raise
    except Exception as exc:
        raise MaterialError("文件无法解析，请检查是否损坏，或改用 PDF。") from exc
    if not pages:
        raise MaterialError("文件没有可读取的页面。")
    return kind, pages


def preview_pdf(path, number):
    with pymupdf.open(path) as doc:
        if number < 1 or number > len(doc):
            raise MaterialError("页码不存在。")
        page = doc[number - 1]
        scale = min(1.5, 1400 / max(page.rect.width, page.rect.height))
        return page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False).tobytes("png")
