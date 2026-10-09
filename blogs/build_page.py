"""Build a chapter's reader page: rl/01-flappy.md -> dist/01-flappy/index.html (+ page.js, page.css, play widget).

page.js and settings.js are esbuild bundles of web/page.ts and web/settings.ts (`npm run build` in web/;
run `npm ci` there once).

    uv run build_page.py rl/01-flappy.md [--session-url http://localhost:8787]
    python3 -m http.server 8010 -d dist        # then open http://localhost:8010/01-flappy/

cell=X     -> <code-cell> editor prefilled with the stub, Run button, output pane
given      -> collapsed, read-only code (the reader calls into it, so they can read it)
solution=X, check=X, budget=X -> not in the page; the session runs them
<!-- ... --> on its own line -> a muted "todo" note
<X-play></X-play>, X a C cell -> <env-play cell=X>, the wasm play widget (reference env until X passes)
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

from markdown_it import MarkdownIt
from markdown_it.token import Token
from markdown_it.utils import EnvType, OptionsDict

import build_web
from check import HIDDEN, ROLES, cell_order, parse

HERE = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("chapter", type=Path)
    ap.add_argument("--session-url", default="http://localhost:8787")
    args = ap.parse_args()

    text = args.chapter.read_text()
    blocks = parse(text)
    envs = [b for b in blocks if b.lang == "c" and b.role == "cell"]
    env_names = {b.name for b in envs}

    md = MarkdownIt("commonmark", {"html": True})
    rules = md.renderer.rules
    plain_fence = rules["fence"]

    def fence(tokens: Sequence[Token], idx: int, opts: OptionsDict, env: EnvType) -> str:
        lang, *info = tokens[idx].info.split()
        role, name = next(((k, v) for k, _, v in (i.partition("=") for i in info) if k in ROLES), ("", ""))
        src = html.escape(tokens[idx].content)
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
        if note := re.fullmatch(r"\s*<!--\s*(.*?)\s*-->\s*", content, re.DOTALL):
            return f'<div class="todo" role="note" data-not-typeset>{html.escape(note[1])}</div>\n'
        return content

    rules["fence"] = fence
    rules["html_block"] = html_block
    body = md.render(text)
    for name in env_names:
        body = re.sub(rf"(<p>)?<{name}-play>\s*</{name}-play>(</p>)?", f'<env-play cell="{name}" data-not-typeset></env-play>', body)

    rendered = re.findall(r'<code-cell name="(\w+)"', body)
    assert rendered == cell_order(blocks), f"markdown-it found cells {rendered}, check.py found {cell_order(blocks)}"
    for b in blocks:
        if b.role in HIDDEN:
            assert html.escape(b.source) not in body, f"{b.role}={b.name} (line {b.line}) leaked into the page"

    title = re.search(r"^# (.+)$", text, re.MULTILINE)
    out = HERE / "dist" / args.chapter.with_suffix("").name
    out.mkdir(parents=True, exist_ok=True)
    page = (HERE / "web" / "page.html").read_text()
    for key, value in {"TITLE": html.escape(title[1] if title else out.name), "SESSION": args.session_url, "BODY": body}.items():
        page = page.replace("{{" + key + "}}", value)
    (out / "index.html").write_text(page)
    subprocess.run(["npm", "run", "--silent", "build"], cwd=HERE / "web", check=True)
    for f in ("build/page.js", "build/settings.js", "page.css", "typeset.css", "play.html"):
        shutil.copy(HERE / "web" / f, out / Path(f).name)

    build_web.ensure_raylib()
    with tempfile.TemporaryDirectory() as tmp:
        for env in envs:
            build_web.build_play(next(b for b in blocks if b.role == "solution" and b.name == env.name), out, Path(tmp))
    print(f"wrote {out / 'index.html'}: cells {rendered}, play widgets {sorted(env_names)}")


if __name__ == "__main__":
    main()
