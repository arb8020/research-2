from pathlib import Path
from types import SimpleNamespace

from box import cli, robots
from box.provider import VolumeEntry


class DictVolume:
    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = files

    def ls(self, path: str, *, recursive: bool = False) -> list[VolumeEntry]:
        return [VolumeEntry(p, 0.0, False) for p in self.files if p.startswith(f"{path}/")]

    def read(self, path: str) -> bytes:
        return self.files[path]


def test_pull_copies_the_boxs_dir_only(tmp_path: Path) -> None:
    vol = DictVolume({"sb-1/a.jsonl": b"a", "sb-1/sub/b.jsonl": b"b", "sb-2/c.jsonl": b"c"})
    provider = SimpleNamespace(volume=lambda name: vol)
    cli.pull(provider, ("robots-runs", "{box_id}", str(tmp_path / "runs")), SimpleNamespace(provider_id="sb-1"))
    got = {str(p.relative_to(tmp_path)): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert got == {"runs/a.jsonl": b"a", "runs/sub/b.jsonl": b"b"}


def test_recipe_links_runs_to_the_volume_and_runs_the_command_last(tmp_path: Path) -> None:
    r = robots.recipe(local_runs=tmp_path, volume="v", timeout=60, cmd="python x.py")
    assert r.volumes == {"v": robots.OUT}
    assert "ln -sfn /out/$BOX_ID runs" in r.cmd and r.cmd.endswith("&& python x.py")
    assert r.pull == ("v", "{box_id}", str(tmp_path))
    assert "**/runs" in r.mounts[f"{robots.REMOTE}/robots"].ignore
    assert Path(r.image).read_text().startswith("FROM python:")
