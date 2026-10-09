"""Build a chapter's reader page: rl/01-flappy.md -> dist/01-flappy/index.html (+ page.js, page.css, play widget).

page.js and settings.js are esbuild bundles of web/page.ts and web/settings.ts (`npm run build` in web/;
run `npm ci` there once).

    uv run build_page.py rl/01-flappy.md [dl/neural-nets.md ...] [--session-url http://localhost:8787]
    uv run build_page.py --all                 # every chapter under blogs/ (links.chapters())
    python3 -m http.server 8010 -d dist        # then open http://localhost:8010/01-flappy/

cell=X     -> <code-cell> editor prefilled with the stub, Run button, output pane
given      -> collapsed, read-only code (the reader calls into it, so they can read it)
solution=X, check=X, budget=X -> not in the page; the session runs them
<!-- ... --> on its own line -> a muted "todo" note
<!-- wip: ... --> on its own line -> a visible "under construction" banner (🚧 + the text), for readers
<X-play></X-play>, X a C cell -> <env-play cell=X>, the wasm play widget (reference env until X passes)
```K fence, web/embeds/K/ exists -> embed K (embeds.py: one folder per kind, e.g. carousel)
[[page]], [[page#Heading]] -> <page-link>: a link to ../page/#heading-slug plus its hover preview card (links.py)
# Heading -> <h1 id="heading">, GitHub-style slug ids (the targets of [[page#Heading]])
"""

from __future__ import annotations

import argparse
import html
import re
import shutil
import subprocess
import tempfile
from collections.abc import Sequence
from pathlib import Path
from typing import NamedTuple

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

import build_web
import embeds
import links
from check import HIDDEN, ROLES, cell_order, parse

HERE = Path(__file__).parent


def render_excerpt(chapter: Path, path: str, lang: str, body: str, line: int) -> str:
    """```c excerpt=../vendor/x.h fence -> a read-only, cell-styled view of those lines of a real file.

    The fence body is the code itself (so the author sees it in the chapter); the build fails unless it
    appears verbatim, as whole consecutive lines, in the named file. Split a snippet by splitting the fence.
    """
    source = chapter.parent / path
    assert source.is_file(), f"line {line}: excerpt={path} not found next to the chapter"
    want = body.rstrip("\n").split("\n")
    have = source.read_text().split("\n")
    starts = [i for i in range(len(have) - len(want) + 1) if have[i : i + len(want)] == want]
    assert starts, f"line {line}: this excerpt is not in {path} verbatim (lines changed upstream, or edited here?)"
    first = starts[0] + 1
    shown = source.resolve().relative_to(HERE.resolve())
    where = f"{shown}:{first}" if len(want) == 1 else f"{shown}:{first}–{first + len(want) - 1}"
    return (f'<figure class="excerpt" data-not-typeset><div class="cell-head"><span>{html.escape(source.name)} · {lang}</span>'
            f'<span class="excerpt-src">{html.escape(where)} · read-only</span></div>'
            f'<code-view data-lang="{lang}" data-first-line="{first}" data-label="{html.escape(where)} (read-only)">'
            f'<pre>{html.escape(body.rstrip(chr(10)))}</pre></code-view></figure>\n')


class Site(NamedTuple):
    """What every render needs: the chapters ([[page]] -> path), the embed kinds, and the heading index cache."""

    pages: dict[str, Path]
    kinds: dict[str, embeds.Embed]
    sources: dict[str, links.Source]


def markdown(chapter: Path, kinds: dict[str, embeds.Embed], preview: bool) -> MarkdownIt:
    """The renderer for one chapter's Markdown: a page, or (preview=True) a link card showing part of it.

    The render env carries `line0` (the rendered text's first line - 1, so errors name chapter lines) and
    `used` (embed kinds rendered). A card differs from a page in three ways: cells render read-only (like
    `given`), headings render as styled paragraphs (no ids, outside the page outline), and [[links]] are plain.
    """
    md = MarkdownIt("commonmark", {"html": True})
    links.use(md)
    rules = md.renderer.rules
    plain_fence = rules["fence"]

    def fence(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        lang, *info = tokens[idx].info.split()
        span = tokens[idx].map
        assert span is not None, f"markdown-it gave the {lang} fence no line numbers"
        line = env["line0"] + span[0] + 1
        if (embed := kinds.get(lang)) is not None:
            env["used"].add(lang)
            files = [v for k, _, v in (i.partition("=") for i in info) if k == "file"]
            if not files:
                return embed.render(tokens[idx].content, line + 1)
            assert not tokens[idx].content.strip(), f"line {line}: a {lang} fence with file= must be empty"
            data = chapter.parent / files[0]
            assert data.is_file(), f"line {line}: {lang} file={files[0]} not found next to the chapter"
            try:
                return embed.render(data.read_text(), 1)
            except AssertionError as e:
                raise AssertionError(f"{data}: {e}") from e
        if excerpt := [v for k, _, v in (i.partition("=") for i in info) if k == "excerpt"]:
            return render_excerpt(chapter, excerpt[0], lang, tokens[idx].content, line)
        role, name = next(((k, v) for k, _, v in (i.partition("=") for i in info) if k in ROLES), ("", ""))
        src = html.escape(tokens[idx].content)
        if role == "cell" and preview:
            return (f'<figure class="excerpt" data-not-typeset><div class="cell-head"><span>{name} · {lang}</span>'
                    f'<span class="excerpt-src">cell · read-only</span></div>'
                    f'<code-view data-lang="{lang}" data-label="{name} cell (read-only)"><pre>{src}</pre></code-view></figure>\n')
        if role == "cell":
            return f'<code-cell name="{name}" data-lang="{lang}" data-not-typeset><pre>{src}</pre></code-cell>\n'
        if role == "given":
            return (f'<details class="given" data-not-typeset><summary>given code: runs before every cell</summary>'
                    f'<code-view data-lang="{lang}"><pre>{src}</pre></code-view></details>\n')
        if role in HIDDEN:
            return ""
        return plain_fence(tokens, idx, opts, env)

    def html_block(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        content = tokens[idx].content
        if wip := re.fullmatch(r"\s*<!--\s*wip:\s*(.*?)\s*-->\s*", content, re.DOTALL):
            span = tokens[idx].map
            assert span is not None, "markdown-it gave the wip comment no line numbers"
            assert wip[1], f"line {env['line0'] + span[0] + 1}: <!-- wip: --> needs text"
            return (f'<div class="wip" role="note" aria-label="under construction" data-not-typeset>'
                    f'<span aria-hidden="true">🚧</span> {html.escape(wip[1])}</div>\n')
        if note := re.fullmatch(r"\s*<!--\s*(.*?)\s*-->\s*", content, re.DOTALL):
            return f'<div class="todo" role="note" data-not-typeset>{html.escape(note[1])}</div>\n'
        return content

    def heading_open(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        if preview:
            return f'<p class="link-card-heading" data-level="{tokens[idx].tag[1:]}">'
        return f'<{tokens[idx].tag} id="{links.slug(links.heading_text(tokens[idx + 1]))}">'

    def heading_close(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        return "</p>\n" if preview else f"</{tokens[idx].tag}>\n"

    def wikilink(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        meta = tokens[idx].meta
        target: links.Target = meta["target"]
        a = f'<a href="{html.escape(target.href)}">{html.escape(target.shown)}</a>'
        if preview:
            return a
        return f'<page-link data-embeds="{" ".join(sorted(meta["embeds"]))}">{a}<template>{meta["card"]}</template></page-link>'

    rules["fence"] = fence
    rules["html_block"] = html_block
    rules["heading_open"] = heading_open
    rules["heading_close"] = heading_close
    rules["wikilink"] = wikilink
    return md


def render(site: Site, chapter: Path, text: str, line0: int, preview: bool) -> tuple[str, set[str]]:
    """Markdown -> (HTML, embed kinds used). Every [[link]] is resolved from source before anything renders."""
    md = markdown(chapter, site.kinds, preview)
    env: EnvType = {"line0": line0, "used": set()}
    tokens = md.parse(text, env)
    for token, line in links.wikilinks(tokens, line0):
        target = links.resolve(token.content, line, site.pages, md, site.sources)
        token.meta["target"] = target
        if not preview:
            token.meta["card"], token.meta["embeds"] = card(site, target, f"line {line}: [[{token.content}]]")
    return md.renderer.render(tokens, md.options, env), env["used"]


def card(site: Site, target: links.Target, where: str) -> tuple[str, set[str]]:
    """A link's preview card: the target page's title, then its section (or the page below its title), rendered."""
    first, text = links.section(target.source, target.heading)
    path = target.source.path
    try:
        body, used = render(site, path, text, first, preview=True)
    except AssertionError as e:
        raise AssertionError(f"{where}: its preview of {path.relative_to(HERE)} failed: {e}") from e
    # Play widgets need the target's wasm next to the page, so a card leaves them out.
    envs = {b.name for b in parse(path.read_text()) if b.lang == "c" and b.role == "cell"}
    for name in envs:
        body = re.sub(rf"(<p>)?<{name}-play>\s*</{name}-play>(</p>)?", "", body)
    return f'<div class="link-card-title">{html.escape(target.source.title)}</div>\n{body}', used


def build(site: Site, chapter: Path, session_url: str) -> None:
    assert site.pages.get(chapter.stem, Path()).resolve() == chapter.resolve(), (
        f"{chapter} is not a chapter under {HERE} (chapters: {', '.join(sorted(site.pages))})")
    text = chapter.read_text()
    blocks = parse(text)
    envs = [b for b in blocks if b.lang == "c" and b.role == "cell"]
    env_names = {b.name for b in envs}

    links.index(chapter, markdown(chapter, site.kinds, preview=False))  # duplicate heading ids fail here
    body, used = render(site, chapter, text, 0, preview=False)
    lazy = set().union(*(set(m.group(1).split()) for m in re.finditer(r'<page-link data-embeds="([^"]*)"', body))) - used
    for name in env_names:
        body = re.sub(rf"(<p>)?<{name}-play>\s*</{name}-play>(</p>)?", f'<env-play cell="{name}" data-not-typeset></env-play>', body)

    rendered = re.findall(r'<code-cell name="(\w+)"', body)
    assert rendered == cell_order(blocks), f"markdown-it found cells {rendered}, check.py found {cell_order(blocks)}"
    for b in blocks:
        if b.role in HIDDEN:
            assert html.escape(b.source) not in body, f"{b.role}={b.name} (line {b.line}) leaked into the page"

    title = re.search(r"^# (.+)$", text, re.MULTILINE)
    out = HERE / "dist" / chapter.with_suffix("").name
    out.mkdir(parents=True, exist_ok=True)
    page = (HERE / "web" / "page.html").read_text()
    head = embeds.install(used, lazy, out)
    for key, value in {"TITLE": html.escape(title[1] if title else out.name), "SESSION": session_url, "EMBEDS": head, "BODY": body}.items():
        page = page.replace("{{" + key + "}}", value)
    (out / "index.html").write_text(page)
    for f in ("build/page.js", "build/settings.js", "page.css", "typeset.css", "play.html"):
        shutil.copy(HERE / "web" / f, out / Path(f).name)

    if envs:
        build_web.ensure_raylib()
    with tempfile.TemporaryDirectory() as tmp:
        for env in envs:
            build_web.build_play(next(b for b in blocks if b.role == "solution" and b.name == env.name), out, Path(tmp))
    links_out = len(re.findall("<page-link", body))
    print(f"wrote {out / 'index.html'}: cells {rendered}, play widgets {sorted(env_names)}, embeds {sorted(used)}, "
          f"links {links_out} (preview-only embeds {sorted(lazy)})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapters", type=Path, nargs="*")
    ap.add_argument("--all", action="store_true", help="build every chapter under blogs/")
    ap.add_argument("--session-url", default="http://localhost:8787")
    args = ap.parse_args()

    site = Site(links.chapters(), embeds.discover(), {})
    todo = list(site.pages.values()) if args.all else args.chapters
    assert todo, "name a chapter (rl/01-flappy.md) or pass --all"
    subprocess.run(["npm", "run", "--silent", "build"], cwd=HERE / "web", check=True)
    for chapter in todo:
        build(site, chapter, args.session_url)


if __name__ == "__main__":
    main()
