# ch00: a toy scheduler, in your own workspace

<!-- page: connect -->

<!-- page: workspace=ch00 -->

<!-- wip: the workspace-cells slice: a toy chapter that exists to prove cells over a real repo, not to teach yet -->

Every cell on this page is a real file in your workspace: a git repo in your sandbox. Connect, and the editors load
your files; every edit is saved back. **Run** builds the latest passing version of the whole project with only this
cell's file swapped in, then runs its checks. A pass is committed and tagged; the next cell unlocks.

The ring is a fixed-capacity queue of request ids. Its interface:

```cpp given file=ring.h
```

Fill in the ring. The check pushes, pops and wraps it around.

```cpp cell=ring file=ring.cpp
```

```sh check=ring
run_checks ch00 ring
```

One step of the scheduler takes requests from the front of the queue while they fit the step's token budget:

```cpp given file=loop.h
```

```cpp cell=loop file=loop.cpp
```

```sh check=loop
run_checks ch00 loop
```

A long prompt shouldn't take a whole step. Split its prefill into chunks (this one is Python, to show both kinds):

```python cell=budget file=budget.py
```

```sh check=budget
run_checks ch00 budget
```

A scratch cell runs on the same kernel, even while a check is running:

```python scratch
import subprocess
print(subprocess.run(["git", "-C", "workspace", "log", "--oneline", "--decorate", "-5"], capture_output=True, text=True).stdout)
```
