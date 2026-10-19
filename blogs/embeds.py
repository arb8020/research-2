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


def install(eager: set[str], lazy: set[str], out: Path) -> str:
    tags = []
    for kind in sorted(eager | lazy):
        dest = out / "embeds" / kind
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(WEB / "build" / "embeds" / kind / "element.js", dest)
        if (css := WEB / "embeds" / kind / "element.css").exists():
            shutil.copy(css, dest)
            tags.append(f'<link rel="stylesheet" href="embeds/{kind}/element.css">')
        if kind in eager:
            tags.append(f'<script type="module" src="embeds/{kind}/element.js"></script>')
    return "\n".join(tags)
