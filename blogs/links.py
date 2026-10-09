"""Links between chapters: [[page]] and [[page#Heading text]] in prose (optionally [[page#Heading|shown text]]).

`page` is a chapter's file stem (01-flappy, neural-nets), unique across every chapter under blogs/.
`#Heading text` names a heading of that chapter; it becomes the heading's GitHub-style slug, which is the
id build_page.py gives that heading. Only double brackets are links: `[make an excalidraw to put here]` stays text.

Everything resolves from Markdown source, without building the target: index(path) reads a chapter's headings,
and section() cuts out the source a hover preview shows (from the heading to the next heading of the same or a
higher level; the whole page below its title when there is no #heading). A missing page or heading, a duplicate
stem, or two headings with one slug fails the build with the line.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token

HERE = Path(__file__).parent
# Directories under blogs/ that hold Markdown that isn't a chapter (as are hidden ones: .venv, .session, .evidence).
NOT_CHAPTERS = frozenset({"notes", "vendor", "dist", "web", "include", "node_modules"})
WIKILINK = re.compile(r"\[\[([^\[\]\n]+)\]\]")


def chapters() -> dict[str, Path]:
    """stem -> chapter path, for every .md in a subdirectory of blogs/ (top-level .md files are notes, e.g. HANDOFF.md)."""
    found: dict[str, Path] = {}
    for path in sorted(HERE.glob("*/**/*.md")):
        rel = path.relative_to(HERE)
        if any(d in NOT_CHAPTERS or d.startswith(".") for d in rel.parts[:-1]):
            continue
        assert path.stem not in found, f"two chapters are both called {path.stem}: {found[path.stem].relative_to(HERE)} and {rel} (stems name pages and dist/ folders, so they must be unique)"
        found[path.stem] = path
    return found


def slug(text: str) -> str:
    """GitHub's heading anchor: lowercase, drop punctuation other than - and _, spaces to hyphens."""
    return re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")


def heading_text(inline: Token) -> str:
    """A heading's visible text (`code` keeps its text, a link keeps its label, markup characters go)."""
    assert inline.type == "inline" and inline.children is not None, f"expected an inline token, got {inline.type}"
    return "".join(c.content for c in inline.children if c.type in ("text", "code_inline"))


class Heading(NamedTuple):
    level: int
    text: str
    slug: str
    line: int  # 1-based


class Source(NamedTuple):
    path: Path
    title: str
    headings: list[Heading]
    lines: list[str]


def index(path: Path, md: MarkdownIt) -> Source:
    """Read a chapter's headings from its source (markdown-it's own parse, so a # inside a fence is not a heading)."""
    text = path.read_text()
    shown = path.resolve().relative_to(HERE.resolve())
    tokens = md.parse(text, {})
    headings = []
    seen: dict[str, int] = {}
    for i, tok in enumerate(tokens):
        if tok.type != "heading_open":
            continue
        assert tok.map is not None, f"{shown}: markdown-it gave a heading no line numbers"
        text_ = heading_text(tokens[i + 1])
        heading = Heading(int(tok.tag[1:]), text_, slug(text_), tok.map[0] + 1)
        assert heading.slug, f"{shown}: line {heading.line}: heading {text_!r} has no letters or digits to make an id from"
        assert heading.slug not in seen, f"{shown}: line {heading.line}: heading {text_!r} has the id #{heading.slug}, like line {seen[heading.slug]}; rename one"
        seen[heading.slug] = heading.line
        headings.append(heading)
    title = headings[0].text if headings and headings[0].level == 1 else path.stem
    return Source(path, title, headings, text.split("\n"))


def section(src: Source, heading: Heading | None) -> tuple[int, str]:
    """(0-based first line, source) of a heading's section, or of the whole page below its title."""
    if heading is None:
        title = src.headings[0] if src.headings and src.headings[0].level == 1 else None
        first = title.line if title is not None else 0
        return first, "\n".join(src.lines[first:])
    after = [h.line for h in src.headings if h.line > heading.line and h.level <= heading.level]
    end = after[0] - 1 if after else len(src.lines)
    return heading.line - 1, "\n".join(src.lines[heading.line - 1 : end])


class Target(NamedTuple):
    source: Source
    heading: Heading | None
    shown: str

    @property
    def href(self) -> str:
        page = f"../{self.source.path.stem}/"
        return page if self.heading is None else f"{page}#{self.heading.slug}"


def resolve(raw: str, line: int, pages: dict[str, Path], md: MarkdownIt, cache: dict[str, Source]) -> Target:
    """`page#Heading|shown` (inside the brackets) -> the chapter and heading it names; `line` is for the error."""
    ref, _, shown = raw.partition("|")
    stem, hashed, wanted = ref.partition("#")
    stem, wanted = stem.strip(), wanted.strip()
    assert stem, f"line {line}: [[{raw}]] names no page"
    assert not hashed or wanted, f"line {line}: [[{raw}]] has a # but no heading"
    assert stem in pages, f"line {line}: [[{raw}]]: no chapter called {stem} (chapters: {', '.join(sorted(pages))})"
    if stem not in cache:
        cache[stem] = index(pages[stem], md)
    src = cache[stem]
    if not wanted:
        return Target(src, None, shown.strip() or src.title)
    found = [h for h in src.headings if h.slug == slug(wanted)]
    assert found, (f"line {line}: [[{raw}]]: {stem} has no heading {wanted!r} (#{slug(wanted)}); "
                   f"its headings: {', '.join(repr(h.text) for h in src.headings)}")
    return Target(src, found[0], shown.strip() or wanted)


def wikilink_rule(state: StateInline, silent: bool) -> bool:
    """Inline rule: [[...]] -> one `wikilink` token holding the raw inner text and its offset in the block."""
    m = WIKILINK.match(state.src, state.pos, state.posMax)
    if m is None:
        return False
    if not silent:
        token = state.push("wikilink", "", 0)
        token.content = m[1]
        token.meta = {"offset": state.pos}
    state.pos = m.end()
    return True


def use(md: MarkdownIt) -> None:
    """Teach md the [[...]] syntax; the renderer needs a `wikilink` rule (build_page.py's renders the target)."""
    md.inline.ruler.before("link", "wikilink", wikilink_rule)


def wikilinks(tokens: Sequence[Token], line0: int) -> list[tuple[Token, int]]:
    """Every wikilink token in a parsed document with its 1-based line (line0 = the document's first line - 1)."""
    found = []
    for block in tokens:
        if block.type != "inline" or not block.children:
            continue
        assert block.map is not None, "markdown-it gave an inline block no line numbers"
        for child in block.children:
            if child.type == "wikilink":
                line = line0 + block.map[0] + 1 + block.content.count("\n", 0, child.meta["offset"])
                found.append((child, line))
    return found
