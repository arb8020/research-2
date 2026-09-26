# What kelpie is answering (verbatim complaints, collected by the user)

These are the problems, in the words of people who hit them. Every launch/config/plugin decision should be
checkable against them.

## 1. Every knob is a startup flag

> all of the software in the ai inference engine stack (vllm, sglang, dynamo, mooncake, hicache, etc.) is
> miserable to work with
>
> they're all built as immutable binaries. EVERY SINGLE KNOB IS A GODDAMN STARTUP FLAG!!!!!
>
> change completion deadline? REDEPLOY
> alter speculative depth? REDEPLOY
> mod queue size limit? REDEPLOY
>
> we've had to fork and move things into db based configs where possible so we can experiment. completely
> unrealistic to bounce the whole service every time you want to tweak something
>
> someone's going to solve this and become a billionaire i swear

## 2. An "inference engine engine": write code, don't configure 100 flags

> dumb idea: I wonder if it could be useful to have smaller LLM inference libraries: not a full "inference
> engine" but an "inference engine engine" of sorts
>
> It does scheduling, metadata planning, parallelism. But you write the forward pass, weight load, cuda graph,
> + control startup time.
>
> And for the high-level parts (tokenizer, multimodal, scheduler admission, retraction heuristics), feels like
> we should just let folks write code instead of configuring 100 CLI arguments

## 3. Inference code that looks like training code

> I feel a lot of inference engines are written like servers when researchers are accustomed to working with
> SPMD style PyTorch training programs. We already have patterns for training where we use a async
> multiprocess dataloader in our scripts. I think the same approach could be taken with inference where we
> have a data loader streaming to a distributed spmd scheduler/cache manager and just write inference code
> that looks very similar to training code.
>
> ++ "inference code that looks like training code"! Feels like when iterating on inference code, you (or
> claude) have to wait the entire engine startup to run the forward pass, and even then it's indirectly.
> Wondering if fwd pass can be easier to run
>
> I wonder how much of that is multiprocessing overhead vs cuda graphs and compile settings optimized for
> throughput not startup time

## 4. Name the axis, not the "parallelism" (seqax shardlib, https://github.com/MatX-inc/seqax)

> A bit polarizing comment: its too late but I kind of think whoever named TP DP EP combinations probably
> slowed down progress by inventing terminology thats borderline absurd to describe basic sharding
>
> You can just name the axis you're sharding along, and most people will understand without needing more
> explanation! d_ff sharding, batch sharding, expert sharding.
>
> "shardlib" in seqax embodies my current preference. It is:
> 1/ Sharding notation, e.g. "B/d L M/t" can be given a precise meaning, and should be how you tell the
>    computer what layout you want.
> 2/ You can do this for collectives too, e.g. AllGather can be specified by "B/d L M/t -> B/d L M".
> 3/ Contra common ML codebases, don't indirect through some "mapping" layer that assigns axes to a physical
>    mesh. The indirection is hard to read and unnecessary; work directly with named axes of the underlying
>    device mesh.

## What each one demands of the launch/build design

1. Knobs are live values with tiers (docs/decisions.md "Config tiers", "Live config"), not flags. A tier-0
   knob changes at a step boundary; tier-1 recaptures; tier-2 drains; only tier-3 (weights, kernels) is
   startup. The test: "change speculative depth / queue limit / deadline" must not restart the process.
2. The user writes `main()`. Kelpie is a library: scheduler + KV/prefix/groups + plan/commit + parallel
   runner. The forward, weight load, graph capture, tokenizer, admission policy are user code with defaults,
   not CLI arguments. `kelpie serve` is one short example script over the library, never the only door.
3. A forward runs standalone, in one process, in seconds, from a script that reads like a training step:
   `batch = plan(...); logits, kv, state = forward(w, cfg, batch, kv, state, ops)`. Eager first; graphs are
   an opt-in on the same code. The engine startup (HTTP, stepper) is not on the path to running a forward.
4. Points 1 and 2 are built (kelpie_models/shard: "T M {tp}", "R V/tp -> R V"). Point 3 is NOT: docs/decisions.md
   "Parallelism" chose a middle rung of roles (tp, ep, dpa, pp) bound to physical axes by config, and the
   sharded gpt-oss says `mesh.size("tp")`, `"E/ep/tp"`. That is exactly the mapping layer this quote rejects.
   Open: drop roles and name the mesh axes directly, or keep roles as the one indirection and defend it.
