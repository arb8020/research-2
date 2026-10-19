from __future__ import annotations

import re
from html import escape
from urllib.parse import quote

REQUIRED = ("title", "caption", "source", "org", "year", "link", "license")
OPTIONAL = ("youtube", "start", "image", "alt")


def render(src: str, line: int) -> str:
    slides = [parse_slide(chunk, line + offset) for offset, chunk in paragraphs(src)]
    assert slides, f"line {line}: carousel has no slides"
    n = len(slides)
    figures = "\n".join(slide_html(s, i, n) for i, s in enumerate(slides))
    return (
        '<embed-carousel data-not-typeset>'
        '<section class="carousel" aria-roledescription="carousel" aria-label="things reinforcement learning has done">\n'
        f'<div class="carousel-track">\n{figures}\n</div></section></embed-carousel>\n'
    )


def paragraphs(src: str) -> list[tuple[int, str]]:
    return [(src.count("\n", 0, m.start()), m[0]) for m in re.finditer(r"(?:^[^\n]*\S[^\n]*(?:\n|$))+", src, re.MULTILINE)]


def parse_slide(chunk: str, line: int) -> dict[str, str]:
    slide: dict[str, str] = {}
    for i, raw in enumerate(chunk.strip().splitlines()):
        key, sep, value = raw.partition(":")
        key, value = key.strip(), value.strip()
        where = f"line {line + i}"
        assert sep and value, f"{where}: expected `key: value`, got {raw!r}"
        assert key in REQUIRED + OPTIONAL, f"{where}: unknown key {key!r} (known: {', '.join(REQUIRED + OPTIONAL)})"
        assert key not in slide, f"{where}: {key} given twice"
        slide[key] = value
    missing = [k for k in REQUIRED if k not in slide]
    assert not missing, f"line {line}: slide {slide.get('title', '?')!r} is missing {', '.join(missing)}"
    assert ("youtube" in slide) != ("image" in slide), f"line {line}: a slide has exactly one of youtube / image"
    assert "image" not in slide or "alt" in slide, f"line {line}: image needs alt"
    assert "start" not in slide or ("youtube" in slide and slide["start"].isdigit()), f"line {line}: start is whole seconds, youtube only"
    assert re.fullmatch(r"https://\S+", slide["link"]), f"line {line}: link must be an https URL"
    return slide


def slide_html(s: dict[str, str], i: int, n: int) -> str:
    title = escape(s["title"])
    return (
        f'<figure class="slide" role="group" aria-roledescription="slide" aria-label="{i + 1} of {n}: {title}">'
        f'<div class="slide-media">{media_html(s)}</div>'
        f'<figcaption><p class="slide-title">{title}</p><p class="slide-caption">{escape(s["caption"])}</p>'
        f'<p class="slide-cite">Source: <a href="{escape(s["link"])}">{escape(s["source"])}</a>, '
        f'{escape(s["org"])}, {escape(s["year"])}. {escape(s["license"])}</p>'
        "</figcaption></figure>"
    )


def media_html(s: dict[str, str]) -> str:
    if "image" in s:
        return f'<img src="{escape(s["image"])}" alt="{escape(s["alt"])}" loading="lazy" decoding="async">'
    vid, start = quote(s["youtube"], safe=""), s.get("start", "")
    watch = f"https://www.youtube.com/watch?v={vid}" + (f"&t={start}s" if start else "")
    return (
        f'<a class="facade" href="{escape(watch)}" data-youtube="{vid}" data-start="{start}" data-title="{escape(s["title"])}" '
        f'aria-label="Play video: {escape(s["title"])} (loads YouTube)">'
        f'<img src="https://i.ytimg.com/vi/{vid}/hqdefault.jpg" alt="" loading="lazy" decoding="async">'
        '<span class="play" aria-hidden="true"></span></a>'
    )
