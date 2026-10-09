"""Embeds: interactive or media blocks a chapter places with a fence whose language names the kind.

    ```carousel
    ...the embed's own text format...
    ```

or, to keep the data out of the prose, an empty fence naming a file next to the chapter:

    ```carousel file=01-flappy-highlights.carousel
    ```

Each kind is one folder, web/embeds/<kind>/, found by build_page.py at build time (no registry):
    embed.py     render(src: str, line: int) -> str: the fence body or file= contents (its first line is
                 line `line` of the chapter, or 1 for a file) -> the HTML that replaces the fence. Bad input fails the build with a line.
    element.ts   the custom element(s) that HTML uses; `npm run build` bundles it to
                 web/build/embeds/<kind>/element.js, and pages that use the kind load it.
    element.css  optional styles, linked only on pages that use the kind.
A new embed is a new folder; nothing here or in build_page.py changes.
"""

from __future__ import annotations

import importlib.util
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

WEB = Path(__file__).parent / "web"


class Embed(NamedTuple):
    kind: str
    render: Callable[[str, int], str]


def discover() -> dict[str, Embed]:
    found = {}
    for py in sorted((WEB / "embeds").glob("*/embed.py")):
        kind = py.parent.name
        spec = importlib.util.spec_from_file_location(f"embeds.{kind}", py)
        assert spec is not None and spec.loader is not None, f"can't load {py}"
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert callable(getattr(module, "render", None)), f"{py} must define render(src, line) -> str"
        assert (py.parent / "element.ts").exists(), f"{py.parent} has embed.py but no element.ts"
        found[kind] = Embed(kind, module.render)
    return found


def install(kinds: set[str], out: Path) -> str:
    """Copy the used kinds' built files into the page dir; return the <head> tags that load them."""
    tags = []
    for kind in sorted(kinds):
        dest = out / "embeds" / kind
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(WEB / "build" / "embeds" / kind / "element.js", dest)
        if (css := WEB / "embeds" / kind / "element.css").exists():
            shutil.copy(css, dest)
            tags.append(f'<link rel="stylesheet" href="embeds/{kind}/element.css">')
        tags.append(f'<script type="module" src="embeds/{kind}/element.js"></script>')
    return "\n".join(tags)
