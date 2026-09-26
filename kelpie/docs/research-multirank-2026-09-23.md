# Research: multi-rank control plane + seqax-shaped sharding (2026-09-23)

Research only. This is a design sketch for us to argue over, not a decision. Sources:
- seqax `shardlib/{shardtypes,shardops}.py` and `train.py` (shallow clone)
- `meta-pytorch/spmd_types` v0.3.0
- jaxtyping 0.3.11 (run locally)
- vLLM v1 and SGLang (shallow clones)
- the deleted `kelpie_engine/parallel.py`
- current `kelpie-core/include/kelpie.h`, `kelpie_models/shard/*`, `models/torch/gpt_oss.py`, `sdk/step.py`, `sdk/engine.py`

## 1. What seqax shardlib is, and where kelpie matches or differs

### seqax's identity

It is two files, with four ideas.

1. **Layout is a string, one token per dim.** `B/d L M/t` means B is split over mesh axis `d`, L is whole, and M is split over `t`. A dim split over several axes is written `M/t/d`, and the order matters. An integer dim such as `64` is a literal size check.
2. **Collectives are transitions between layouts.**
   - `all_gather("B/d L M/t -> B/d L M", x)` and `psum_scatter("B/d L M -> B/d L M/t", x)` check x against the left side, run `lax.*`, then check the result against the right side.
   - A gather may only drop trailing axes from a dim, and a scatter may only append them.
   - `einsum_unreduced` and `index_unreduced` are local-only ops that leave a partial sum behind.
3. **There is no mapping layer.** The names after `/` are the JAX mesh axis names themselves. `Mesh(devices, ("d", "t"))` is built once, and those strings go straight into `PartitionSpec` and `lax.psum(..., "t")`.
4. **Types carry the layout.**
   - A signature reads `def f(x: f32[b"B/d L M/t"]) -> ...`.
   - `@typed_shard_map` builds shard_map's in/out specs from those annotations, and typeguard checks arguments, return values and annotated locals.
   - Inside shard_map it checks that the local size times the axis sizes equals the global size. Dim names unify within a scope.
   - Every check runs on tracers, so it runs once per jit compile and never per step.

Gaps in seqax itself:
- It has **no notation for a partial sum.** "Unreduced" exists only in function names, and the model calls raw `lax.psum` and `lax.pmax`.
- It has no all_to_all.
- The check that the value's actual sharding matches its annotation is a `pass` behind a TODO.

### What kelpie `shard/` already matches

- The notation parser, including multi-axis dims and literal dims.
- Collectives as transitions, with the same prefix and append rules as seqax.
- Name unification in `check(names=)`.
- `shard_tensor` slicing at load time.

### Where kelpie goes beyond seqax

- The `{t}` unreduced set is part of the type. That is closer to spmd_types' `P` and DTensor's `Partial` than to seqax.
- It has typed `all_reduce` and `all_to_all`.
- At world 1 every collective is a no-op.

### Where kelpie differs from seqax

- **Roles (`mesh.py:_axis`).**
  - `preset(tp=2)` builds a physical axis named `axis_tp` and binds the role `tp` to it. So the layout says `/tp`, but the mesh axis is called something else. That is exactly the mapping layer complaint #4 rejects.
  - The one job roles really do is let an *unbound* conventional role have size 1, which is how world 1 works.
  - seqax gets world 1 for free, because a mesh can have axes of size 1.
  - Without roles, `Mesh.single()` would be a mesh whose axes all have size 1, e.g. `(("t",1),("e",1))`, and there would be no `_axis` fallback chain.
- **The layout is not attached to the value yet.**
  - gpt_oss still has `shard_specs()` keyed by field path, which is what brief-shard-layout-on-value.md addresses.
  - `local_kv_heads` reads `mesh.size("tp")` instead of reading the weight's layout.
- **Collectives do not check their input layout.** They check only `x.ndim`. seqax checks shapes on both sides.
- **Forwards carry no signature types.** Layouts appear only as `# T M {tp}` comments.
- **gpt_oss "EP" is not dispatch EP.** Tokens are replicated, experts are sliced `E/ep/tp`, and the partial sum is all_reduced over `{ep,tp}`. This is correct and graph-friendly, but no all_to_all ever runs.

## 2. Control-plane options

The facts that constrain every option:
- `KelpiePlan` is a set of raw pointers into Zig-owned buffers.
- The Zig step thread calls a Python launch callback.
- `submit`, `cancel`, `set` and `attach_grammar` arrive from other threads. Knobs go through an SPSC ring that is drained at the plan boundary.
- The scheduler's decisions look time-free:
  - Clock reads are only event timestamps.
  - The prefix hash seeds are constant.
  - The sampling key is `sample_seed(req_ids, seq_lens)`, a pure function of the plan.

### (a) Rank 0 plans and broadcasts the plan (the deleted parallel.py; vLLM's default)

```
rank 0                                  rank k>0
  engine.plan() -> plan                   (no Engine)
+ bytes = kelpie_plan_pack(plan)
+ bcast(bytes)  ------------------------> bytes = bcast_recv()
                                        + plan = kelpie_plan_view(bytes)
  logits = step.forward(plan)             step.forward(plan)   # collectives pair up here
  tok = step.sample(logits, plan)         (drop logits)
  engine.commit(tok)
```

- **What the ABI needs.** One writer of the wire format, in Zig:
  - `kelpie_plan_pack(const KelpiePlan*, u8* buf, size_t cap) -> size_t`
  - `kelpie_plan_view(const u8*, size_t, KelpiePlan* out)`, which fills pointers into buf
  - The old `pack_plan` was a second, hand-written Python spelling of the plan (the many-writers problem again).
  - A padded plan's size is set by its bucket, so the header can just be `shape`.
- **Failure modes.** Ranks cannot diverge on the plan, because only one rank plans. A crashed or slow worker shows up as a hang inside the next collective, so a watchdog timeout is needed.
- **Does it read as training code?** No. Rank 0 is a server and the other ranks are RPC loops. That is complaint #3's anti-pattern.
- **Where the heinrich pattern fits.** It replaces gloo for the control channel: rank 0 forks the workers with a socketpair and a memfd ring for the plan bytes, like vLLM's shm MessageQueue but about 60 lines. NCCL stays for the forward.

### (b) Every rank runs the same deterministic Zig scheduler (SGLang; vLLM external_launcher)

```
every rank runs the same main()
+ ingress = Ingress(sock)                 # heinrich: parent process = tokenizer/HTTP/"dataloader"
  engine = Engine(cfg)                    # every rank; num_blocks agreed by all_reduce(MIN)
  while ingress.open or engine.has_work():
+   ops = ingress.agree(mesh)             # consume the same prefix of the op log on every rank
    for op in ops: engine.apply(op)       # submit / cancel / set / attach_grammar, in log order
    plan = engine.plan()                  # by hand; the Zig step thread is not used
+   agree_digest(plan.digest, mesh)       # 8B all_gather on gloo; mismatch -> dump both, raise
    logits = step.forward(plan)           # "R V": identical on every rank after the all_gather
    tok = step.sample(logits, plan)       # same key, same logits -> same tokens
    engine.commit(tok)
+   if rank == 0: ingress.emit(commits)
```

**How the ranks agree on which ops to apply** (the one new idea):
- The parent (ingress) writes one ordered log of ops to every child.
- Each step, every rank all_reduces MIN over "ops I have received", then applies exactly that prefix.
- No rank leads. This is the SGLang pattern without a special rank 0, and the ops really are "a dataloader streaming into an SPMD scheduler".

**What the ABI needs:**
- **A written determinism contract.** A plan must be a pure function of (config, the ordered op log, the commits). That rules out:
  - time in decisions
  - thread-timed knob application
  - pool sizes that depend on memory probing
- **All mutation through one sequenced path.** In this mode `kelpie_set` goes through the log, not the async ring.
- **`uint64_t digest` appended to `KelpiePlan`.** This is an additive ABI change: a Wyhash over the padded arrays.
- **grammar:** the xgrammar mask must also be deterministic. vLLM had to disable async grammar compile for this.

**Failure modes:**
- The plans diverge, which the digest catches on the same step, before the collectives mismatch.
- The sampled tokens diverge, which is SGLang's "rare" nondeterminism. An optional `all_reduce(MIN)` on the tokens fixes it, or the tokens can be folded into the next step's digest.
- vLLM and SGLang have **no** divergence detection, and there the symptom is a hang. The digest is cheap and turns a hang into an error.

**Does it read as training code?** Yes. It is one script and one loop, and each rank's "batch" is `engine.plan()`.

**Costs:**
- Every rank pays the Zig scheduling cost, which is microseconds.
- Loop overlap is lost: the loop is driven from Python by hand, not by the Zig thread with async launch.

**Where the heinrich pattern fits:** exactly. Parent = ingress and tokenizer. Children = N ranks, each with a socketpair holding JSON lines of ops in and commits out. The kernel refcounts the fds, so there is no watchdog process.

### (c) Rank 0 plans, and NCCL broadcasts the padded plan into the graph's input buffers

- rank 0 runs `to_device(plan, into=bufs)`.
- `dist.broadcast(bufs.packed, src=0)` then runs on the compute stream, into the same fixed-address buffers `Captured` replays against. There is no gloo and no host hop on the workers.
- **What the ABI needs:** nothing beyond (a)'s pack. The device layout is the wire.
- **Failure modes:** the same as (a).
- **Does it read as training code?** Somewhat. Every rank's loop body is `forward(bufs)`, and only rank 0 has an `engine.plan()` line before it.
- **Graph interplay:** the broadcast could even be captured into the graph. The shape header still has to go over the host, because it picks which graph runs.

### (a) against (b)

- (a) makes divergence impossible by construction, at the cost of asymmetric code.
- (b) gives symmetric, training-shaped code, at the cost of a determinism contract on the Zig core and a digest check.
- The core looks close to deterministic already, which makes (b) cheaper than it would be for vLLM.

## 3. Typing: making the forward describe its own sharding

These fit together in layers.

```
Layout = str                                        # "T M/t {e,t}"; axis names ARE mesh axes
class Sharded(NamedTuple): tensor: Tensor; layout: ShapeSpec   # brief option (b): weights
bf16: LayoutAlias                                   # bf16["T M/t"] -> Annotated[Tensor, ShapeSpec]
@sharded(check="first-per-bucket")                  # parse annotations once; check.names() per call
def attention(h: bf16["T M"], layer: GptOssLayer, ...) -> bf16["T M {t}"]: ...
def all_reduce(spec: str, x: Tensor, mesh) -> Tensor  # ~ now also check(x, before) and check(out, after)
```

- **jaxtyping cannot express `M/t`.** Its symbolic dims are Python-eval'd over dims that are already bound, so the only escape is `"m//{t}"` with `t` as a function argument, which is ugly. It is also about 34µs per checked call in eager mode. Keep kelpie's own parser. It already does the local-size-times-axes check and the name unification.
- **The decorator is a seqax port.** What differs is when checks run: in eager torch they run every call, so check once per bucket shape (ProgramKey) and skip after that. That is the eager equivalent of "once per trace". Under CUDA graph capture this happens for free.
- **spmd_types (Meta, Edward Yang, v0.3.0)** gives per-axis R/I/V/P/S(i) types that are propagated through a TorchFunctionMode, on a fake process group on CPU.
  - Mapping: `/t` becomes S(i), `{t}` becomes P, and an absent axis becomes R.
  - It **propagates** types, so it would catch a missing all_reduce between two annotated functions. seqax cannot do that.
  - It does not check shapes. It is a check mode, not a runtime.
  - One use: a `check_serve` row that runs tiny gpt_oss at world 2 on a fake process group, with layouts translated into spmd_types.

## 4. First vertical slice: gpt-oss-20b TP2 on Modal (2x H100), greedy, compared with 1 GPU

```
kelpie-models/kelpie_models/shard/
~   mesh.py            # axes named directly ("t","e"); single() = size-1 axes; roles deleted (IF we rule so)
~   ops.py             # collectives check(x, before) / check(out, after)
kelpie-models/kelpie_models/models/torch/
~   gpt_oss.py         # "/tp" -> "/t"; local_kv_heads from layout; load() slices by mesh
kelpie-models/kelpie_models/sdk/
+   spmd.py            # launch(fn, world): heinrich fork+socketpair; init_process_group; Ingress.agree
kelpie-core/
~   include/kelpie.h, src/c_api.zig   # KelpiePlan.digest (appended)  [only for option b]
scripts/
+   check_tp.py        # world1 run -> tokens; world2 run -> tokens; assert equal + per-step digests equal
research-2/box         # Modal gpu="H100:2" entry
```

- **The check.** Take 8 prompts and 64 greedy tokens.
  - The TP2 ranks must match each other bitwise.
  - Compared with world 1, the tokens must be equal. If they are not, report the first step where they diverge and the top-1/top-2 logit margin at that step.
- **Memory.** gpt-oss-20b with bf16-dequantized experts is about 40GB, so it fits one 80GB GPU as the oracle.
- **TP2 fits the model's shapes.** Its 64 q heads, 8 kv heads and 32 experts all divide by 2, and a vocab of 201088 divides by 2 and by 4.

## 5. Pushback

- **"Greedy equals single-GPU" may be false, and that would not be a bug.**
  - Why: TP changes the order of the bf16 all_reduce sums. The logits drift by ULPs, so greedy can flip where the top-2 margin is tiny.
  - What the slice needs: either do the reduces in fp32, or state the criterion as "equal until a near-tie, with the margin reported".
  - What is still exact: agreement between the TP ranks themselves, because every rank ends with the same all_gathered logits.
- **seqax leans on XLA.**
  - Its checks are free because they run at trace time. In torch eager they cost time every step, unless they are cached per bucket or run only under capture.
  - `shard_map` gives seqax a boundary between the global program and the per-shard view. kelpie is always in the per-shard view. That is simpler, but no compiler catches a layout mistake. Only runtime checks or spmd_types would.
- **Roles were kept by the 2026-09-10 ruling.** Dropping them reopens that ruling. The honest argument for keeping them is the unbound-role-means-size-1 behaviour. Named size-1 axes replace that, but only if a model's axes are declared somewhere, e.g. `Mesh.single(axes=("t","e"))`.
- **The heinrich pattern is fork-based.**
  - CUDA must not be initialised in the parent before `fork`, which rules out any torch.cuda call in the ingress process.
  - It is single-node only: socketpair and memfd do not cross hosts. Multi-node needs TCP, as Heinrich himself notes.
  - It replaces torchrun, and with it torchrun's elastic restart and its environment conventions.
- **NCCL and CUDA graphs.**
  - Collectives inside captured graphs are fine, provided every rank replays the same bucket in the same order. (a) and (c) get this by construction; (b) gets it from the digest.
  - gpt_oss `moe` does a host sync (`int(local.sum())`, `.tolist()`), which already blocks graph capture at world 1.
- **MoE all_to_all.** Real EP dispatch has token counts that depend on the data. That needs all_to_all with split sizes, which means either a host sync or padded capacity. kelpie's `all_to_all` assumes even splits, so it cannot express this. The replicate-and-all_reduce EP used today is fine for 20b on 2 to 4 GPUs. A 120b model or a larger EP needs the capacity-padded design, and seqax offers no template for it.
- **Modal.** `/dev/shm` inside a Modal container may be small, and NCCL's shm transport needs it. I have not verified this.

## Judgement calls, uncertainties, papercuts

- **Judgement calls:**
  - Option (b) is described with a leaderless MIN-cursor agreement instead of SGLang's rank-0 `broadcast_pyobj`. That is my construction, not taken from any existing system.
  - (b) drops the Zig step thread in favour of a Python-driven loop. That gives up overlap scheduling.
- **Uncertain:**
  - I did not trace xgrammar's determinism.
  - I did not measure whether `sample` is bitwise deterministic across two H100s.
  - I did not run the torch path of jaxtyping.
  - I read only about 10% of spmd_types' checker.
  - The torchtitan and DTensor notes come from memory.
- **Papercuts:**
  - `_ffi.py` would need a hand edit for `KelpiePlan.digest`. That is many-writers debt #1.

## Control planes in practice (2026-09-23)

Sources are shallow sparse clones taken on 2026-09-23 and deleted after reading:
- vLLM main @ `e0f03eb4`
- SGLang main @ `ffac53d`
- TokenSpeed HEAD (commit hash not recorded)

Each engine was read by its own subagent. I then checked kelpie-core by hand. Paths are relative to each repo's package root: `vllm/`, `python/sglang/srt/`, and `python/tokenspeed/runtime/`. Items marked UNVERIFIED were not traced to the end.

**Headline**

| Engine | Option | How it works |
|---|---|---|
| vLLM v1 (default) | (a) | One scheduler broadcasts the plan. |
| vLLM `external_launcher` | (b) | Experimental. |
| SGLang | (b) | Every rank runs its own scheduler. |
| TokenSpeed | (b) | Every rank runs its own scheduler. |

**Every engine samples on every rank, including vLLM under (a).** The two (b) engines then add agreement collectives on top:
- where rank-local timing or memory leaks into a decision (memory size, grammar readiness);
- wherever float nondeterminism could split the sampled tokens.

None of them verifies at runtime that the ranks agree, except SGLang's opt-in checker. When ranks diverge, the symptom is a hang.

### 1. Process topology and IPC

**vLLM (a)**
- **Processes.**
  - An API server process holds `AsyncLLM`, including `InputProcessor` (tokenize) and `OutputProcessor` (detokenize).
  - One `EngineCoreProc` process runs the scheduler (`v1/engine/utils.py:launch_core_engines`).
  - `MultiprocExecutor` starts one `WorkerProc` per GPU. The default start method is fork. It is forced to spawn if CUDA is already initialised, under Ray, or with NUMA binding (`utils/system_utils.py:_maybe_force_spawn`).
- **Client ↔ core.** ZMQ ROUTER/DEALER in, PUSH/PULL out, encoded as msgspec msgpack (`v1/serial_utils.py`). Pickle is used only behind `VLLM_ALLOW_INSECURE_SERIALIZATION`.
- **Core → workers.** One `MessageQueue` (`distributed/device_communicators/shm_broadcast.py`) carries a pickled `(method, args, kwargs, output_rank)`.
  - The transport is a shm ring buffer. Messages of 16 MiB or more overflow to ZMQ PUB, and remote-node readers get XPUB/SUB over TCP.
  - Readers spin with `sched_yield`.
- **Two RPCs per step:**
  1. `execute_model(SchedulerOutput)`
  2. `sample_tokens(GrammarOutput)`, which carries an int32 bitmask. The 24 MiB MQ default exists to fit 1024 bitmask rows.
- **`SchedulerOutput`** (`v1/core/sched/output.py`) is diff-based.
  - `NewRequestData` carries the full prompt, the params and the block ids.
  - `CachedRequestData` carries only new block ids and `num_computed_tokens`. `new_token_ids` is included only for PP.
  - Per step it is roughly ids plus block deltas: small in decode, prompt-sized when prompts arrive (not measured).
- **Replies.** Only `output_rank` replies (`MultiprocExecutor._get_output_rank`). That is the first TP rank of the last PP stage. When a KV connector is attached, all ranks reply and `KVOutputAggregator` merges the replies.

**SGLang (b)**
- **Processes.** `Engine._launch_subprocesses` starts:
  - the TokenizerManager in the main process;
  - one `mp.Process(run_scheduler_process)` per (pp, tp) rank, which is scheduler and worker in one;
  - a `run_detokenizer_process`.
  - With `dp_size > 1`, a `DataParallelController` spawns the schedulers instead.
- **I/O ownership.** Only `pp_rank==0 && attn_tp_rank==0 && attn_cp_rank==0` owns ZMQ (`managers/scheduler_components/ipc_channels.py`). The other ranks get `SenderWrapper(None)`.
- **Per step** (`managers/.../request_receiver.py:recv_requests`):
  1. Rank 0 drains ZMQ with `NOBLOCK`, capped by `max_recv_per_poll`.
  2. It runs `broadcast_pyobj` (`utils/common.py`), which pickles the input list and sends an int64 length plus the bytes over the **gloo** TP CPU group.
  - An empty step costs one 8-byte broadcast.
  - The list mixes `TokenizedGenerateReqInput` (ids, sampling params, mm) with control requests.

**TokenSpeed (b)**
- **Scheduler.** It is C++ (`tokenspeed-scheduler/csrc/`, about 10k lines, bound with nanobind) and runs inside each rank's process.
- **Launch.** `mp.set_start_method("spawn")`, one `mp.Process(run_event_loop)` per GPU (`entrypoints/engine.py:_launch_subprocesses`).
- **Threads per rank process.**
  - A control-plane thread runs `EventLoop.event_loop`, which calls `next_execution_plan()` then `advance_scheduler()`.
  - A data-plane `ForwardThread` owns all CUDA work, enforced by `maybe_control_plane_guard`.
- **Detokenizer.** Runs inline in the `AsyncLLM` process.
- **Per step.**
  - An async gloo broadcast of an int64 "has data" flag, pipelined into the next round (`utils/common.py:PipelinedPyobjBroadcaster`).
  - Only when requests exist, a `broadcast_pyobj` of the pickled requests.
- **Design rules** are written down in `docs/design/event-loop.md`:
  - control plane and data plane are separated;
  - correctness does not depend on the in-flight depth;
  - collectives sit at fixed, rank-identical positions ("Checklist for extending the loop").

### 2. What crosses ranks, and how tokens become identical

| | Per-step control | Logits | Token agreement |
|---|---|---|---|
| vLLM | The plan (`SchedulerOutput`) and the grammar bitmask. | Full vocab on every rank. `_gather_logits` uses all_gather by default (`platforms/interface.py:use_all_gather`). | **Every rank samples, with no sync.**<br>- The global torch RNG is seeded identically (`set_random_seed(model_config.seed)` in `Worker.init_device` and after warmup), and seeded requests use a per-rank `torch.Generator`.<br>- Each worker keeps its own `output_token_ids` and `prev_sampled_token_ids`, so the plan never carries tokens back.<br>- Explicit token broadcasts exist only for PP (`_pp_broadcast_prev_sampled_token_ids`). |
| SGLang | The pickled input list. | Full vocab on every rank. `LogitsProcessor._get_logits` all-gathers. | **Every rank samples.**<br>- The seed is broadcast from rank 0 (`tp_worker.py`).<br>- `Sampler._sync_token_ids_across_tp` does `all_reduce(MIN)` on the token ids, but only if env `SYNC_TOKEN_IDS_ACROSS_TP` is set or the batch has grammars. The comment says the kernels are deterministic except "rare instances"; the sync prevents a hang.<br>- Abort statuses are all_reduced with MAX. |
| TokenSpeed | Input flag plus the requests. | Full vocab on every rank. | **Rank 0 wins.** `SamplingBackend.maybe_broadcast` does an **in-graph NCCL broadcast** of the token tensor from TP rank 0, on by default (`--disable-sampling-tp-sync` turns it off).<br>- Comment in `greedy.py`: "All-gathered logits are not bit-identical across ranks, so per-rank argmax can diverge… deadlocks a downstream model all-reduce."<br>- The seed is `crc32(rid)`, and greedy uses seed 0. |

Why can all-gathered logits differ bitwise at all? My reading, not verified: the all_reduce before them can leave different bits on different ranks. A one-shot or custom all_reduce has each rank sum the peers in its own order.

**Spec decode:**
- vLLM runs `RejectionSampler` on every rank with the same RNG. Without async scheduling, drafts come from `output_rank` and are re-broadcast in the plan.
- SGLang's `eagle_sample` broadcasts `predict/accept_index/num_correct_drafts` from rank 0 on its sampling paths.
- TokenSpeed packs predict, accept_len and accept_idx into one int32 buffer and broadcasts it from rank 0 (`broadcast_verify_outputs`).

### 3. Determinism hazards

**KV pool size**
- vLLM: min across workers (`v1/core/kv_cache_utils.py:get_kv_cache_configs`). `external_launcher` does a gloo all_reduce(MIN).
- SGLang: `get_available_gpu_memory(distributed=True)` does all_reduce(MIN), and there is an optional imbalance check.
- TokenSpeed: all_reduce(MIN), and startup fails if memory is more than 10% imbalanced.

**Wall clock**
- vLLM: stats only. Ties break on `(priority, arrival_time)`, and arrival time is stamped by the frontend.
- SGLang:
  - Request timeouts are decided **on rank 0 only** and turned into synthetic `AbortReq`s that ride the broadcast (`_poll_timeout_aborts`: "every rank must drop the same requests in the same iteration").
  - Leftover per-rank-clock hazards: session reaping (`Session.is_timed_out`) and the prefill-delayer timeout. Whether these bite in practice is UNVERIFIED.
- TokenSpeed:
  - The C++ scheduler has no `chrono`, `time` or `rand`.
  - One leftover: `pending_aborts` has a per-rank 300 s monotonic TTL.

**Control messages (abort, flush, pause, weights)**
- vLLM: only one scheduler, so nothing to agree on.
- SGLang: in the broadcast list, so they apply at the same step. `flush_cache` runs only when fully idle, which is state-based.
- TokenSpeed: same as SGLang.

**Grammar**
- vLLM:
  - Compiled in the engine core on a thread pool, so readiness depends on timing.
  - The mask is computed in the core and shipped to the workers.
  - Under `external_launcher`, async compile is **disabled**: "deadlocks … a scheduler for each TP rank … breaking the determinism assumption" (`v1/structured_output/__init__.py`).
- SGLang:
  - Compiled on each rank.
  - `GrammarManager.get_ready_grammar_requests` does an `all_gather_object((ready, failed))`, admits the ready requests in the **intersection**, and marks the **union** of failed ones as failed.
  - Grammar batches also force the token MIN-sync.
- TokenSpeed: the same intersection/union all-gather, with the rank-0 token broadcast as a backstop.

**Prefix-cache eviction**
- vLLM: one scheduler, so not a cross-rank hazard.
- SGLang:
  - Radix nodes carry a per-rank `time.monotonic()`, but the relative order is the same on every rank.
  - **Ties** are a problem. `evict` heapifies an object-id-hashed `set`, so tie order depends on memory addresses (theoretical, UNVERIFIED as observed).
  - `unified_radix_cache.py` carries `@rank_consensus` checks.
- TokenSpeed: a logical clock. `EvictionOrder{last_access_epoch, lcm_block_id, slot_index}` sits in a `std::map`, so ties break stably.

**Ordering and hash iteration**
- vLLM: MRv2 iterates `sorted(finished_req_ids)` because Python set order differs across processes.
- SGLang: `_sort_randomly` uses `random.shuffle`, which is safe with the shared seed.
- TokenSpeed: requests live in a `vector` in submit order. The unordered_maps are used for lookup only (UNVERIFIED that none is iterated).

**Async overlap**
- vLLM: `max_concurrent_batches=2`. Deferred sampling is used with pending grammar.
- SGLang: `event_loop_overlap`. The overlap-disable decision uses globally synced flags under DP attention.
- TokenSpeed: `in_flight_depth` 0, 1 or pp. The C++ scheduler reserves decode KV for the overlap depth.

### 4. Divergence detection

- **vLLM:** none found.
- **TokenSpeed:** none. Correctness is by construction, and divergence would show up as a gloo or NCCL hang.
- **SGLang:** off by default.
  - `utils/rank_consensus_checker.py`, enabled with env `SGLANG_ENABLE_RANK_CONSENSUS_CHECKER`.
  - The `@rank_consensus` decorator queues events.
  - A background thread on its own gloo groups SHA1-hashes them and all_reduces MIN and MAX. On a mismatch it logs critical and calls `os._exit(1)`.
  - Only the unified radix cache is decorated.
  - **This is the only precedent for kelpie's per-step digest, and it is asynchronous.** It is not on the step's critical path.

### 5. Failure handling

**vLLM**
- A monitor thread does `multiprocessing.connection.wait(sentinels)` (`MultiprocExecutor.start_worker_monitor`). On a death it calls `_send_engine_dead`, and the client raises `EngineDeadError`.
- Workers watch a **death pipe**: EOF means the parent is gone (`WorkerProc.monitor_death_pipe`). There is no PDEATHSIG.
- The RPC deadline is `VLLM_EXECUTE_MODEL_TIMEOUT_SECONDS=300`.

**SGLang**
- `prctl(PR_SET_PDEATHSIG, SIGKILL)` (`kill_itself_when_parent_died`).
- A watchdog thread watches `forward_ct` while a batch is running. On a stall it dumps py-spy output and sends SIGQUIT to the parent.
- Scheduler exceptions also send SIGQUIT to the parent.
- `SubprocessWatchdog` polls whether children are alive, because an NCCL-timeout `terminate` skips Python handlers.

**TokenSpeed**
- Scheduler exceptions send SIGUSR1 to the parent. What the parent does with it is UNVERIFIED; there is no handler in `async_llm.py`.
- In headless mode the launcher polls `join(1)` and kills everyone on the first nonzero exit.
- There is no PDEATHSIG.
- `--distributed-timeout-seconds` is passed through to process groups.

### 6. Multi-node, PP and DP

**vLLM**
- TP and PP can span nodes. The leader node writes the MQ and remote readers subscribe over TCP.
- Each DP rank is a full EngineCore with its own scheduler.
- For MoE, `DPEngineCoreProc` does:
  - `execute_dummy_batch` when a rank is idle;
  - an all_reduce of `[has_unfinished, pending_pause]` every `dp_sync_interval` steps;
  - `DPCoordinator` for request waves.

**SGLang**
- Node 0 hosts the tokenizer and HTTP server. The other nodes run only schedulers. The gloo `broadcast_pyobj` spans nodes.
- PP passes requests stage to stage (`point_to_point_pyobj`).
- **DP attention:** one scheduler per DP rank, each with its own queue, broadcast within its attn-TP/CP group.
  - Every step `prepare_mlp_sync_batch_raw` all-gathers 8 ints: num_tokens, graph votes, is_extend, forward_mode and so on.
  - Idle ranks run `get_idle_batch()`.

**TokenSpeed**
- Topology comes from Slurm (`utils/launcher.py:detect_topology`).
- PP is allowed only for prefill-disaggregation. It forces eager mode, and the last stage broadcasts tokens over gloo.
- DP attention: one scheduler per replica, with `_dp_sync_and_check` all-gathering 3 ints per round, and idle forwards.

### 7. torchrun and SPMD-native modes

**vLLM `ExecutorWithExternalLauncher`** is the only one of the three.
- Setup: one engine per torchrun rank, in-process. `VLLM_ENABLE_V1_MULTIPROCESSING=0` is asserted.
- Docstring: "When scheduling is deterministic, all the engines will generate the same outputs."
- **Constraints on the user:**
  - identical prompts, params and order on every rank;
  - an explicit seed (`examples/.../torchrun_example_offline.py`);
  - abort and arrival timing are the user's problem.
- **What vLLM changed for it:**
  - MIN memory;
  - synchronous grammar compile;
  - a logits broadcast for PP;
  - a dummy run to keep DP coordination in step.
- It is labelled experimental.

**SGLang** has no torchrun or SPMD mode on main. VerlEngine is gone, and only `HttpServerEngineAdapter` remains.

**TokenSpeed** has none either. torchrun appears only in docs, for tests.

### 8. CUDA graphs across ranks

- **Pure TP, all three engines.** Every rank derives the bucket locally from identical state, with no collective:
  - vLLM from the same plan (`_determine_batch_execution_and_padding`);
  - SGLang and TokenSpeed from identical scheduler state (TokenSpeed: `bisect(capture_bs, bs)`).
- **With DP or DP attention, all three do one small collective:**
  - vLLM: `coordinate_batch_across_dp` all_reduces a `[4,dp]` tensor. It pads to the max tokens, and cudagraph mode is the min (so any rank running eager makes all run eager).
  - SGLang: pads to `max(global_num_tokens)`, with graph eligibility as the MIN vote.
  - TokenSpeed: `_global_graph_bs` takes the max. It also has prefill graphs, bucketed from the replicated global state.

### Comparison

| | vLLM v1 | vLLM external_launcher | SGLang | TokenSpeed |
|---|---|---|---|---|
| Option | (a) | (b), experimental | (b) | (b) |
| Who reads requests | The engine core (single) | The user, on every rank | TP rank 0: ZMQ, then a gloo pickle broadcast | TP rank 0: a pipelined gloo flag, then a pickle broadcast |
| Per-step cross-rank control | Pickled plan plus bitmask over a shm ring | Nothing | Input list: 8 B when idle | Input flag: 8 B when idle |
| Token agreement | Same seed, each rank samples | Same seed | Each rank samples; MIN all_reduce only with grammar or env | **In-graph NCCL broadcast from rank 0** |
| KV size | Min over workers | gloo MIN | gloo MIN | gloo MIN plus a 10% balance check |
| Grammar | Core-side mask, async compile | Sync compile | Intersection all-gather | Intersection all-gather |
| Wall-clock decisions | Only one decider | The user's problem | Rank 0 turns them into abort messages; a few leftovers | None in C++; one TTL leftover |
| Divergence check | None | None | Opt-in async SHA1 consensus | None |
| Cost paid | Plan serialization and an MQ hop per step; workers keep a mirror of token state | Everything is on the user | The broadcast plus agreement collectives at every rank-local decision | The same, plus one token broadcast per step |

### Implications for kelpie

**What a (b) design must include.** These are ranked by how many engines needed each one.
1. **One ordered input stream, applied at the plan boundary.**
   - All three (b) engines have rank 0 broadcast the inputs. None uses my leaderless MIN cursor.
   - A per-step gloo broadcast costs the same as a per-step MIN all_reduce, so rank-0 broadcast is simply the proven choice.
   - **In kelpie this is a real hazard.** `kelpie_submit`, `kelpie_cancel` and `kelpie_attach_grammar` each take `loop.mutex` and mutate the scheduler right away (`c_api.zig`), so where they land relative to `kelpie_plan` depends on thread timing.
   - Knobs already carry `KelpieSetResult.apply_step`, which is the right shape. Submit, cancel and attach need the same thing: a queue drained at a named step. The alternative is to drive the loop by hand in Python and apply ops between plans.
2. **Token agreement by construction.** Use an NCCL broadcast of the B int32 token ids from rank 0, as TokenSpeed does. It is cheap and graph-capturable.
   - Kelpie's `sample_seed` is already a pure function of the plan, so equal logits would give equal tokens.
   - But bit-equal logits across ranks is exactly what TokenSpeed says fails.
   - Treat this as **real**, especially once a custom or one-shot all_reduce is used. Fold the broadcast into the forward.
3. **MIN over anything a rank measures.** Kelpie's `num_blocks` is an explicit config value (`sdk/engine.py` `kv_blocks`), so this is **theoretical** today. It becomes real the moment the pool is auto-sized from free memory.
4. **Grammar readiness agreement.** The mask itself is filled in Zig at plan time (`c_api.zig`, `matcherFill`), which is deterministic given the same accepts. But compile happens in Python (`grammar.py`), so `attach_grammar` timing is the hazard.
   - Option 1: rank 0 compiles and broadcasts the attach only once it is ready. Each rank still needs its own compiled handle, so each rank compiles synchronously when the op arrives.
   - Option 2: the SGLang/TokenSpeed intersection all-gather.
   - **Real**, but it can be left out of the MVP.
5. **Wall-clock decisions made only on rank 0 and turned into ops.**
   - The Zig core reads the clock only for event timestamps (`events.zig`, `scheduler.zig`: arrival, first sched, tokens, finish).
   - kelpie-core has no HashMap at all (grep), and the prefix and slab LRU order is a pure function of the op order.
   - So the core is **theoretical-clean**. The real risk is Python-side timeouts, e.g. in kelpie-http, which must become `cancel` ops.
6. **The digest is still worth it.** No engine checks on the critical path, and all of them hang when ranks diverge.
   - An 8-byte `all_gather` of `plan.digest` on gloo each step is cheap. Alternatively, copy SGLang and run it asynchronously in a side thread.
   - With (2) in place, the digest mostly catches op-ordering bugs, which is exactly the kelpie-specific hazard from item 1.
7. **Failure handling.** heinrich's socketpair-EOF approach is vLLM's death pipe. Add `PR_SET_PDEATHSIG` as SGLang does, and a watchdog on the step counter. An NCCL timeout alone kills the process without running any Python handlers (SGLang issue #18421).

**Buckets.** Buckets are already safe under (b) for pure TP. `KelpiePlan.shape` is "a deterministic function of this plan alone", so equal plans give equal graphs. A DP or DP-attention layout would add a MAX/MIN all-gather, as all three engines do.

**Minimum viable version (gpt-oss-20b, TP2, 2×H100 on Modal, greedy):**
```
parent: ingress (no CUDA) ── socketpair ──> rank0 only           # rank 0 is I/O owner, like SGLang/TokenSpeed
rank r (spawned, PDEATHSIG, init_process_group nccl + gloo):
  engine = Engine(cfg with explicit kv_blocks)                   # no memory probing -> no MIN needed
  loop:
    ops = broadcast_pyobj(rank0.drain() if r==0 else None, gloo) # 8 B when idle
    for op in ops: engine.apply(op)                              # submit/cancel/set, log order
    plan = engine.plan()                                         # Python-driven; no Zig step thread
    agree(plan.digest)  [debug flag]                             # 8 B gloo all_gather
    logits = step.forward(plan)                                  # all_gather'd, "R V"
    tok = step.sample(logits, plan); nccl.broadcast(tok, src=0)  # TokenSpeed rule
    engine.commit(tok); if r==0: emit(commits)
```
- **Out of scope for the MVP:** grammar (reject it at world > 1), spec decode (it would need a rank-0 broadcast of the accept indices), overlap, and auto-sized KV.
- **The check** is as in §4 above, plus a per-step assert that the digests are equal.

### Judgement calls, uncertainties and papercuts for this section
- **Judgement calls:**
  - I rank "rank-0 token broadcast" as required, not optional, because of TokenSpeed's comment and SGLang's "rare instances" comment. I have not reproduced non-bit-identical all-gathered logits myself.
  - I recommend rank-0 input broadcast over the leaderless MIN cursor from §2, because no engine uses the cursor and it saves nothing.
- **UNVERIFIED:**
  - TokenSpeed commit hash, and its SIGUSR1 handling in the parent.
  - Whether SGLang reads `SGLANG_SYNC_TOKEN_IDS_ACROSS_TP` or only the unprefixed env var.
  - Whether SGLang's prefill-delayer and session clock hazards bite in practice.
  - vLLM `SchedulerOutput` byte sizes (not measured).
  - Whether Modal `/dev/shm` is adequate (carried over from §5).
- **Papercut:** subagent research was not cross-reviewed by a second agent. Claims are file- and function-anchored so they can be spot-checked.
