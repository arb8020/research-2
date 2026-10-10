"""Build a chapter's reader page: rl/01-flappy.md -> dist/01-flappy/index.html (+ page.js, page.css, play widget).

page.js and settings.js are esbuild bundles of web/page.ts and web/settings.ts (`npm run build` in web/;
run `npm ci` there once).

    uv run build_page.py rl/01-flappy.md [dl/neural-nets.md ...] [--session-url http://localhost:8787]
                         [--gateway-url http://localhost:8790]
    uv run build_page.py --all                 # every chapter under blogs/ (links.chapters())
    python3 -m http.server 8010 -d dist        # then open http://localhost:8010/01-flappy/

cell=X     -> <code-cell> editor prefilled with the stub, Run button, output pane
given      -> collapsed, read-only code (the reader calls into it, so they can read it)
```K cell=X file=F, on a <!-- page: workspace=chNN --> page -> <ws-cell>: an editor over the reader's workspace
                      file F (workspace.py in their sandbox), scrolled to the cell's region (checks/chNN.json); cells
                      over one file share one document. The fence body is optional and, if there, must equal F at
                      chNN/start (ref.py). Run runs the cell's cmd from checks/chNN.json (no check= fence)
```K given file=F (workspace page) -> read-only view of F at chNN/start; output lines naming F link to it
```python scratch -> <scratch-cell>: editable, Run executes on the Connect session's kernel; no checks, no gating
<!-- page: connect --> on its own line -> this page has the header Connect control (gateway: --gateway-url);
                      a page with scratch cells or workspace cells must have it
<!-- page: workspace=chNN --> -> the page's file= cells are chapter chNN of the reference (engine/ref/chNN); the page
                      ships _blogs/ (workspace.py + the trusted check code + MANIFEST.sha256, ref.stage_trusted) and
                      the chapter's start bundle (ref.bundle) for the sandbox
solution=X, check=X, budget=X -> not in the page; the session runs them
workspace solutions (ref/chNN/files) -> only each region cell's own region, in a <template class="reference"> inside
                      that <ws-cell> (the cell's "reference" toggle shows it read-only); never the whole file
<!-- ... --> on its own line -> a muted "todo" note
<!-- wip: ... --> on its own line -> a visible "under construction" banner (🚧 + the text), for readers
<X-play></X-play>, X a C cell -> <env-play cell=X>, the wasm play widget (reference env until X passes)
```K fence, web/embeds/K/ exists -> embed K (embeds.py: one folder per kind, e.g. carousel)
[[page]], [[page#Heading]] -> <page-link>: a link to ../page/#heading-slug plus its hover preview card (links.py)
# Heading -> <h1 id="heading">, GitHub-style slug ids (the targets of [[page#Heading]])
"""

from __future__ import annotations

import argparse
import functools
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
import ref
from check import HIDDEN, ROLES, Block, cell_order, parse

HERE = Path(__file__).parent
PAGE_FLAG = re.compile(r"^<!--\s*page:\s*(\S+)\s*-->\s*$", re.MULTILINE)
PAGE_FLAGS = ("connect", "workspace")


class Workspace(NamedTuple):
    """A workspace chapter's reference: its start and solution trees and its cells (checks/chNN.json)."""

    chapter: str
    start: ref.Tree
    solution: ref.Tree
    cells: list[ref.Cell]


@functools.cache
def workspace_of(chapter: Path) -> Workspace | None:
    """The chapter's <!-- page: workspace=chNN --> reference, or None for an ordinary page."""
    text = chapter.read_text()
    flags = [f for f in PAGE_FLAG.findall(text) if f.startswith("workspace=")]
    if not flags:
        return None
    assert len(flags) == 1, f"{chapter}: more than one workspace flag {flags}"
    name = flags[0].removeprefix("workspace=")
    start = ref.materialize(name, "start")
    for b in parse(text):
        assert b.role != "check", f"line {b.line}: check={b.name}: a workspace cell's check is its cmd in checks/{name}.json, not a fence"
    return Workspace(name, start, ref.materialize(name, "solution"), ref.cells(start, name))


@functools.cache
def trusted_sha() -> str:
    """The sha256 of the MANIFEST.sha256 the page ships (what workspace.py check --trusted compares against)."""
    with tempfile.TemporaryDirectory() as tmp:
        return ref.stage_trusted(Path(tmp) / "_blogs")


def workspace_file(ws: Workspace | None, b: Block, body: str) -> str:
    """F's text at chNN/start; a non-empty fence body must equal it (the author sees the code; the build keeps it true)."""
    assert ws is not None, f"line {b.line}: file={b.file} needs <!-- page: workspace=chNN -->"
    assert b.file in ws.start, f"line {b.line}: {b.file} is not in {ws.chapter}/start (files: {sorted(ws.start)})"
    text = ws.start[b.file].data.decode()
    if body.strip():
        assert body == text, f"line {b.line}: this fence's body differs from {b.file} at {ws.chapter}/start; empty it, or fix ref/"
    if b.role == "cell":
        owned = {c.name: c.file for c in ws.cells}
        assert owned.get(b.name) == b.file, f"line {b.line}: cell={b.name} file={b.file}, but checks/{ws.chapter}.json says {owned.get(b.name)}"
    return text


def region_text(tree: ref.Tree, file: str, region: str) -> str | None:
    """The lines strictly between `# region: <region>` and its `# endregion` in file, or None if a marker is missing."""
    text = tree[file].data.decode()
    span = ref.region_span(text, region)
    return None if span is None else "\n".join(text.split("\n")[span[0] : span[1] - 1])


def solution_region(ws: Workspace, c: ref.Cell) -> str:
    """Cell c's region of the solution: what its "reference" toggle shows."""
    assert c.region is not None, f"cell {c.name} has no region"
    assert c.file in ws.solution, f"cell {c.name}: {c.file} is not in {ws.chapter}/solution"
    found = region_text(ws.solution, c.file, c.region)
    assert found is not None, (f"cell {c.name}: {ws.chapter}/solution's {c.file} has no `# region: {c.region}` ... `# endregion` "
                               f"(the reference toggle shows that region); add the markers in engine/ref/{ws.chapter}/files/{c.file}")
    return found


def render_workspace_fence(chapter: Path, b: Block, preview: bool) -> str:
    """```K cell=X file=F -> <ws-cell>; ```K given file=F -> a read-only view of F. Both show F at chNN/start."""
    assert b.role in ("cell", "given"), f"line {b.line}: file= goes on cell=X or given fences, not {b.role or 'a plain one'}"
    ws = workspace_of(chapter)
    text = html.escape(workspace_file(ws, b, b.source))
    assert ws is not None  # workspace_file asserted it
    file = html.escape(b.file)
    if b.role == "cell" and not preview:
        c = next(c for c in ws.cells if c.name == b.name)
        region = f' data-region="{html.escape(c.region)}"' if c.region else ""
        # The cell's "reference" toggle: its region of the solution, in a <template> (inert, not shown until asked).
        reference = f'<template class="reference">{html.escape(solution_region(ws, c))}</template>' if c.region else ""
        return (f'<ws-cell name="{b.name}" data-file="{file}" data-lang="{b.lang}" data-chapter="{ws.chapter}"{region} '
                f'data-ops="{html.escape(" ".join(c.ops))}" data-trusted="{trusted_sha()}" data-not-typeset>'
                f'<pre>{text}</pre>{reference}</ws-cell>\n')
    what = f"{b.name} cell · read-only here" if b.role == "cell" else "given · read-only"
    # A link card (preview) must not claim the file: output links would jump into the card instead of the page.
    claim = "" if preview else f' data-file="{file}"'
    return (f'<figure class="excerpt" data-not-typeset><div class="cell-head"><span>{file} · {b.lang}</span>'
            f'<span class="excerpt-src">{what}</span></div>'
            f'<code-view data-lang="{b.lang}"{claim} data-label="{file} ({what})"><pre>{text}</pre></code-view></figure>\n')


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
    md = MarkdownIt("commonmark", {"html": True}).enable("table")  # GFM pipe tables (typeset.css styles them)
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
        file = next((v for k, _, v in (i.partition("=") for i in info) if k == "file"), "")
        if file:
            return render_workspace_fence(chapter, Block(lang, role, name, tokens[idx].content, line, file), preview)
        src = html.escape(tokens[idx].content)
        if "scratch" in info:
            assert not role, f"line {line}: a scratch block can't also be {role}={name}"
            assert lang == "python", f"line {line}: scratch cells run in a Python kernel, not {lang}"
            if preview:
                return (f'<figure class="excerpt" data-not-typeset><div class="cell-head"><span>scratch · {lang}</span>'
                        f'<span class="excerpt-src">read-only here</span></div>'
                        f'<code-view data-lang="{lang}" data-label="scratch cell (read-only)"><pre>{src}</pre></code-view></figure>\n')
            return f'<scratch-cell data-lang="{lang}" data-not-typeset><pre>{src}</pre></scratch-cell>\n'
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
        if flag := PAGE_FLAG.fullmatch(content.strip()):
            assert flag[1].partition("=")[0] in PAGE_FLAGS, f"<!-- page: {flag[1]} -->: page flags are {PAGE_FLAGS}"
            return ""
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


def build(site: Site, chapter: Path, session_url: str, gateway_url: str) -> None:
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

    ws = workspace_of(chapter)
    rendered = re.findall(r'<code-cell name="(\w+)"', body)
    session_cells = [b.name for b in blocks if b.role == "cell" and not b.file]
    assert rendered == session_cells, f"markdown-it found cells {rendered}, check.py found {cell_order(blocks)}"
    ws_cells = re.findall(r'<ws-cell name="(\w+)"', body)
    if ws is not None:
        assert ws_cells == [c.name for c in ws.cells], f"{chapter}: the page's workspace cells {ws_cells} differ from checks/{ws.chapter}.json {[c.name for c in ws.cells]}"
        # The solution is never in the page, except each cell's own region of it inside that cell's reference payload.
        payloads = re.findall(r'<ws-cell name="(\w+)"[^>]*>(?:(?!</ws-cell>).)*?<template class="reference">(.*?)</template>', body, re.DOTALL)
        outside = re.sub(r'<template class="reference">.*?</template>', "", body, flags=re.DOTALL)
        for c in ws.cells:
            assert html.escape(ws.solution[c.file].data.decode()) not in body, f"the solution of {c.file} leaked into the page"
            if c.region is None:
                continue
            want = html.escape(solution_region(ws, c))
            assert payloads.count((c.name, want)) == 1, f"cell {c.name}: its reference payload is not its solution region"
            if want != html.escape(region_text(ws.start, c.file, c.region) or ""):  # a region the reader starts with solved is no secret
                assert want not in outside, f"cell {c.name}: its solution region leaked into the page outside its reference"
                assert sum(want in p for _, p in payloads) == 1, f"cell {c.name}: its solution region is in another cell's reference"
    for b in blocks:
        if b.role in HIDDEN:
            assert html.escape(b.source) not in body, f"{b.role}={b.name} (line {b.line}) leaked into the page"

    flags = PAGE_FLAG.findall(text)
    connect = "connect" in flags
    scratch = body.count("<scratch-cell")
    assert connect or not scratch, f"{chapter}: scratch cells need <!-- page: connect --> (nothing else can run them)"
    assert connect or ws is None, f"{chapter}: workspace cells need <!-- page: connect --> (the workspace lives in the sandbox)"
    corner = f'<connect-pill data-gateway="{html.escape(gateway_url)}"></connect-pill>' if connect else ""

    title = re.search(r"^# (.+)$", text, re.MULTILINE)
    out = HERE / "dist" / chapter.with_suffix("").name
    out.mkdir(parents=True, exist_ok=True)
    page = (HERE / "web" / "page.html").read_text()
    head = embeds.install(used, lazy, out)
    for key, value in {"TITLE": html.escape(title[1] if title else out.name), "SESSION": session_url, "EMBEDS": head, "CORNER": corner, "BODY": body}.items():
        page = page.replace("{{" + key + "}}", value)
    (out / "index.html").write_text(page)
    for f in ("build/page.js", "build/settings.js", "page.css", "typeset.css", "play.html"):
        shutil.copy(HERE / "web" / f, out / Path(f).name)
    if ws is not None:
        # The page uploads _blogs/ and ref.bundle into the sandbox (web/workspace.ts); cells carry the manifest's sha256.
        shutil.rmtree(out / "_blogs", ignore_errors=True)
        assert ref.stage_trusted(out / "_blogs") == trusted_sha(), "the trusted code changed during the build"
        ref.reader_bundle(ws.chapter, out / "ref.bundle")

    if envs:
        build_web.ensure_raylib()
    with tempfile.TemporaryDirectory() as tmp:
        for env in envs:
            build_web.build_play(next(b for b in blocks if b.role == "solution" and b.name == env.name), out, Path(tmp))
    links_out = len(re.findall("<page-link", body))
    print(f"wrote {out / 'index.html'}: cells {rendered}, workspace {ws.chapter if ws else None} cells {ws_cells}, scratch {scratch}, connect {connect}, play widgets {sorted(env_names)}, embeds {sorted(used)}, "
          f"links {links_out} (preview-only embeds {sorted(lazy)})")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapters", type=Path, nargs="*")
    ap.add_argument("--all", action="store_true", help="build every chapter under blogs/")
    ap.add_argument("--session-url", default="http://localhost:8787")
    ap.add_argument("--gateway-url", default="http://localhost:8790", help="the Connect gateway (box/CONTRACT-gateway.md)")
    args = ap.parse_args()

    site = Site(links.chapters(), embeds.discover(), {})
    todo = list(site.pages.values()) if args.all else args.chapters
    assert todo, "name a chapter (rl/01-flappy.md) or pass --all"
    subprocess.run(["npm", "run", "--silent", "build"], cwd=HERE / "web", check=True)
    for chapter in todo:
        build(site, chapter, args.session_url, args.gateway_url)


if __name__ == "__main__":
    main()
