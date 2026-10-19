#!/bin/bash
set -u
M=$(mktemp -d)
mutate() {
  local name=$1 old=$2 new=$3
  uv run python - "$M/$name.md" "$old" "$new" <<'PY'
import sys; from pathlib import Path
out, old, new = sys.argv[1:]
text = Path("rl/01-flappy.md").read_text()
start = text.index("```c solution=flappy"); end = text.index("```\n", start + 5)
sol = text[start:end]; assert sol.count(old) == 1, old
Path(out).write_text(text[:start] + sol.replace(old, new) + text[end:])
PY
}
run() { echo; echo "\$ check.py $*"; uv run check.py "$@" 2>&1 | grep -v -E '^    #([3-9]|[1-9][0-9]) ' | awk 'NR<=8 || /FAIL|PASS|steps\/s/'; }

echo "===== 1. out-of-bounds write: obs[2] = 0 in spawn_pipe"
mutate oob 'obs[BOTTOM] = env->flappy_env.pipe_row == BOTTOM;' 'obs[BOTTOM] = env->flappy_env.pipe_row == BOTTOM;
    obs[2] = 0;'
run $M/oob.md flappy
run $M/oob.md flappy --build prod

echo; echo "===== 1b. undefined behaviour: signed int overflow"
mutate ub '    flappy_env->tick += 1;' '    flappy_env->tick += 1;
    int big = 2147483647;
    big += flappy_env->tick;
    flappy_env->episode_length += big - big;'
run $M/ub.md flappy
run $M/ub.md flappy --build prod

echo; echo "===== 2. a wrong assert: assert(action == TOP)"
mutate assert 'assert(action == truncf(action));' 'assert(action == truncf(action));
    assert(action == TOP);'
run $M/assert.md flappy
run $M/assert.md flappy --build prod

echo; echo "===== 3a. -Wextra in the reader's cell: signed/unsigned compare"
mutate wextra '    // increment env by a tick' '    if (flappy_env->tick < sizeof(Log)) {}
    // increment env by a tick'
run $M/wextra.md flappy
run $M/wextra.md flappy --build prod

echo; echo "===== 3b. an assert that changes state: assert(action = truncf(action))"
mutate assign 'assert(action == truncf(action));' 'assert(action = truncf(action));'
run $M/assign.md flappy

echo; echo "===== 3c. vendor headers: the unchanged solution compiles silently under the check flags"
run rl/01-flappy.md flappy

echo; echo "===== 4. speed: the same vec_step loop on each build"
uv run python - "$M" <<'PY'
import sys; from pathlib import Path
text = Path("rl/01-flappy.md").read_text()
text = text.replace('assert sps > 50e6', 'print(f"    {sps / 1e6:.0f}M env steps/s"); assert sps > 1e6')
budget = text[text.index("```python budget=flappy"):]
budget = budget[:budget.index("```\n", 5) + 4]
check_start = text.index("```python check=flappy"); check_end = text.index("```\n", check_start + 5) + 4
# check=flappy := the budget loop, so it runs on the check build in the sanitized process
Path(sys.argv[1], "speed.md").write_text(text[:check_start] + budget.replace("budget=flappy", "check=flappy") + text[check_end:])
PY
echo "(first line: check build + sanitizer runtime; second: prod build, clean process)"
run $M/speed.md flappy
rm -rf "$M"
