"""
deepswe-shaped task pipeline with fake agent trials (asyncio.sleep + random pass/fail; no harbor, no network).
  python 04_agent_trials.py                      cold run, rerun, invalidate T1, rerun (temp store, asserts)
  python 04_agent_trials.py STORE                one run against STORE
  python 04_agent_trials.py STORE --invalidate T1  archive T1's write_tests and everything downstream, then run
"""
import asyncio
import json
import random
import sys
import tempfile
from pathlib import Path

from tally import Handle, Ok, Pool, Step, StepCtx, effect_key, invalidate, keys, load, open_store, pool, reconcile, run, start

SPECS = {"T1": "parse ISO-8601 durations", "T2": "LRU cache with TTL", "T3": "stable toposort", "T4": "token bucket"}
PASS_RATE = {
    "easy_gate": {"T1": 0.15, "T2": 0.8, "T3": 0.2, "T4": 0.6},
    "difficulty_gate": {"T1": 0.4, "T2": 0.5, "T3": 0.3, "T4": 0.5},
}
EASY_RUNS, HARD_RUNS, EASY_MAX_PASSES = 10, 5, 3
LIMITS = {"docker": 6, "hy4": 4, "frontier": 2}
F2P_NAME = "fail_to_pass"


def harbor_result(key: str, out: Path) -> Ok[dict] | None:
    result = out / "result.json"
    return Ok(json.loads(result.read_text())) if result.is_file() else None


async def write_tests(ctx: StepCtx, task: str, spec: str, *, idem_key: str, out: Path) -> Ok[dict]:
    await asyncio.sleep(random.uniform(0.02, 0.06))
    test_ids = [f"tests/test_{task.lower()}.py::test_{index}" for index in range(random.randint(3, 6))]
    (out / "tests").mkdir()
    (out / "tests" / f"test_{task.lower()}.py").write_text("".join(f"def test_{i}():  # {spec}\n    ...\n" for i in range(len(test_ids))))
    before = {test_id: random.choice(["failed", "failed", "passed"]) for test_id in test_ids}
    (out / "report.json").write_text(json.dumps({"before": before, "after": dict.fromkeys(test_ids, "passed")}))
    result = {"tests": len(test_ids)}
    (out / "result.json").write_text(json.dumps(result))
    return Ok(result)


async def fail_to_pass(ctx: StepCtx, tests: Handle, *, out: Path) -> list[str]:
    report = json.loads((Path(tests.path) / "report.json").read_text())
    return sorted(test_id for test_id, status in report["before"].items() if status == "failed" and report["after"][test_id] == "passed")


F2P = Step(fail_to_pass, key=keys.bytes)


async def trial(ctx: StepCtx, task: str, rung: str, pass_rate: float, f2p_ids: list[str], *, idem_key: str, out: Path) -> Ok[dict]:
    await asyncio.sleep(random.uniform(0.02, 0.08))
    result = {"passed": random.random() < pass_rate, "rung": rung}
    (out / "trajectory.txt").write_text(f"{idem_key}: {rung} worked on {task} against {len(f2p_ids)} f2p tests\n")
    (out / "result.json").write_text(json.dumps(result))
    return Ok(result)


async def gate(ctx: StepCtx, slots: Pool, task: str, stage: str, rung: str, runs: int, f2p: Handle) -> list[Handle]:
    return await asyncio.gather(*(
        run(ctx, slots, f"{task}/{stage}/a{attempt}", trial, task, rung, PASS_RATE[stage][task], load(f2p),
            needs={"docker": 1, rung: 1}, inputs={"f2p": f2p, "rung": rung}, on_unknown=reconcile(harbor_result))
        for attempt in range(runs)
    ))


def write_tests_inputs(task: str) -> dict:
    return {"spec": SPECS[task]}


async def pipeline(ctx: StepCtx, slots: Pool, task: str) -> tuple[str, list[Handle]]:
    tests = await run(ctx, slots, f"{task}/write_tests/a0", write_tests, task, SPECS[task],
                      needs={"docker": 1, "frontier": 1}, inputs=write_tests_inputs(task), on_unknown=reconcile(harbor_result))
    f2p = await ctx.afetch(F2P, tests)
    easy = await gate(ctx, slots, task, "easy_gate", "hy4", EASY_RUNS, f2p)
    easy_passes = sum(load(handle)["passed"] for handle in easy)
    if easy_passes > EASY_MAX_PASSES: return f"too easy: easy {easy_passes}/{EASY_RUNS}", [tests, *easy]
    hard = await gate(ctx, slots, task, "difficulty_gate", "frontier", HARD_RUNS, f2p)
    hard_passes = sum(load(handle)["passed"] for handle in hard)
    return f"kept: easy {easy_passes}/{EASY_RUNS}, difficulty {hard_passes}/{HARD_RUNS}", [tests, *easy, *hard]


async def build(root: Path, label: str) -> tuple[list[str], dict[str, list[Handle]]]:
    ctx, slots = start(open_store(root)), pool(LIMITS)
    results = await asyncio.gather(*(pipeline(ctx, slots, task) for task in SPECS))
    ran = set(ctx.ran)
    print(f"\n{label}  ({ctx.ran.count(F2P_NAME)} {F2P_NAME} derivations ran)")
    for task, (verdict, handles) in zip(SPECS, results, strict=True):
        ran_count = sum(handle.key in ran for handle in handles)
        print(f"  {task}  {verdict:34s} effects ran {ran_count:2d}  reused {len(handles) - ran_count:2d}")
    return ctx.ran, {task: handles for task, (_, handles) in zip(SPECS, results, strict=True)}


def invalidate_write_tests(root: Path, task: str) -> Path:
    key = effect_key(f"{task}/write_tests/a0", write_tests_inputs(task))
    archive = invalidate(open_store(root), [key], downstream=True)
    manifest = json.loads((archive / "manifest.json").read_text())
    print(f"\ninvalidate {key} + downstream: {len(manifest['effects'])} effects, "
          f"{len(manifest['derivations'])} derivations -> {archive.relative_to(root)}/")
    return archive


async def demo(root: Path) -> None:
    cold_ran, cold = await build(root, "1 cold run")
    assert all(handle.key in cold_ran for handles in cold.values() for handle in handles)
    warm_ran, _ = await build(root, "2 rerun")
    assert warm_ran == []
    archive = invalidate_write_tests(root, "T1")
    assert all(not Path(handle.path).exists() for handle in cold["T1"])
    assert all(Path(handle.path).exists() for task in ("T2", "T3", "T4") for handle in cold[task])
    assert (archive / "effects" / cold["T1"][0].key / "effect.json").is_file()
    redo_ran, _ = await build(root, "3 rerun after invalidating T1")
    assert [name for name in redo_ran if "@" not in name] == [F2P_NAME]
    assert all(name.startswith("T1/") for name in redo_ran if "@" in name)
    print("\n04_agent_trials: all assertions passed")


def main() -> None:
    match sys.argv[1:]:
        case []:
            with tempfile.TemporaryDirectory() as tmp:
                asyncio.run(demo(Path(tmp)))
        case [store]:
            asyncio.run(build(Path(store), f"run against {store}"))
        case [store, "--invalidate", task]:
            invalidate_write_tests(Path(store), task)
            asyncio.run(build(Path(store), f"rerun against {store}"))
        case _:
            raise SystemExit(__doc__)


if __name__ == "__main__":
    main()
