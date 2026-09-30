"""Bounded GPU smoke run through the repository's box SDK."""
import argparse
import subprocess
from pathlib import Path

from box.providers.modal import Modal
from box.provider import Mount


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pufferlib", required=True, type=Path)
    parser.add_argument("--evidence", required=True, type=Path)
    args = parser.parse_args()
    revision = subprocess.check_output(
        ["git", "-C", str(args.pufferlib), "rev-parse", "HEAD"], text=True
    ).strip()
    if revision != "6ffa5b10dbbbe4d1e8288367c7d9d3acd3bad4a2":
        raise ValueError(f"PufferLib revision {revision} differs from pinned Ocean contract")
    project = Path(__file__).resolve().parents[1]
    provider = Modal()
    image = provider.build_image(
        "nvidia/cuda:12.8.1-devel-ubuntu22.04", add_python="3.11",
        apt=["clang", "ccache", "git", "curl", "libomp-dev", "libgl1-mesa-dev", "libnccl-dev=2.25.1-1+cuda12.8"],
        mounts={
            "/pokemon": Mount(str(project), ignore=("verify", "engine", "harbor", "data", "regressions", "harness", "__pycache__")),
            "/pufferlib": Mount(str(args.pufferlib.resolve()), ignore=(".git", "resources", "tests", "__pycache__")),
        },
    )
    offering = next(x for x in provider.search(gpu_model="L4") if x.id == "L4")
    sandbox = provider.create(offering, image, timeout=900, labels={"task": "pokemon-training-smoke"})
    print(f"sandbox={sandbox.provider_id}", flush=True)
    args.evidence.mkdir(parents=True, exist_ok=True)
    try:
        result = sandbox.exec("bash /pokemon/ocean/training_smoke.sh", stream=True, timeout=780)
        (args.evidence / "stdout.log").write_text(result.stdout)
        (args.evidence / "stderr.log").write_text(result.stderr)
        if result.returncode:
            raise RuntimeError(f"training smoke exited {result.returncode}")
        sandbox.download("/tmp/pokemon-training-checkpoints.tar", str(args.evidence / "checkpoints.tar"))
    finally:
        sandbox.terminate()


if __name__ == "__main__":
    main()
