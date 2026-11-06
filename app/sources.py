"""Stable references to exact source substrings; model text is never a quote."""
from . import core


def passages(text, page_number, size=160):
    return [
        {"id": f"p{page_number}-{offset // size + 1}", "text": text[offset:offset + size]}
        for offset in range(0, len(text), size)
        if len(core.compact(text[offset:offset + size])) >= 8
    ]
