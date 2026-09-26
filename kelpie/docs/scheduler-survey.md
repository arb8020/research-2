# Scheduler survey: nano-vllm, mini-sglang, vLLM v1, SGLang, TokenSpeed

Read in this order. Each section is faithful pseudocode of the real code, not a summary.

## 0. The shared core (what every one of them has)

1. Two queues: `waiting` (needs prefill) and `running` (KV is resident).
   waiting -> running on admission; running -> waiting on preempt; running -> done on finish.
2. A token budget per step. A request needs `num_tokens - num_computed` tokens of work.
   If that exceeds the budget it either waits or gets a page-aligned *chunk*.
3. Per-request computed cursor (`num_computed_tokens`) + a slot map: token position -> KV slot.
   The forward pass needs exactly: new token ids, the cursor, the slot map, where to write new KV.
4. KV allocator = free list + refcounts. Prefix cache = content-addressed index over KV
   (hash chain over blocks, or radix tree over tokens). Hits are found *before* allocation
   and pinned (refcount++) for the request's lifetime.
5. Eviction is lazy + LRU: cached-but-unreferenced KV stays in the free pool, reclaimed only
   when an allocation needs it.
6. Admission reserves for decode (SGLang: max_new_tokens; TokenSpeed: explicit headroom;
   vLLM: watermark only, relies on preemption).
7. OOM recovery = preempt a running request: free its KV, requeue at head, recompute from prefix cache.
8. Result step: append sampled token(s), check stop, on finish release KV (and publish to prefix index).
   Sampling and (de)tokenization live OUTSIDE the scheduler in all of them.

## 1. nano-vllm (~300 lines for scheduler+blocks+seqs)

```
Sequence:
  status: WAITING | RUNNING | FINISHED
  token_ids[]            prompt + generated (full history)
  num_cached_tokens      tokens whose KV is already in cache
  num_scheduled_tokens   tokens to compute THIS step (chunk for prefill, 1 for decode)
  block_table[]          physical block ids, one per 256 tokens
  temperature, max_tokens

Block: block_id, ref_count, hash (-1 = unhashed), token_ids[] (for collision check)

BlockManager:
  blocks[num_blocks]
  hash_to_block_id: dict
  free_block_ids: deque      # FIFO => LRU eviction for free. Freed blocks KEEP hash+tokens
  used_block_ids: set        #   so they're still hittable until reused.

Scheduler: waiting: deque, running: deque, max_num_seqs=512, max_num_batched_tokens=16384
```

```
schedule() -> (seqs, is_prefill):       # a step is ALL prefill or ALL decode; prefill wins
  scheduled = []; batched = 0
  while waiting and len(scheduled) < max_num_seqs:
    seq = waiting[0]                     # peek; head-of-line blocks, no skipping
    remaining = max_batched - batched;  if remaining == 0: break
    if seq.block_table empty:
      cached = bm.can_allocate(seq)      # -1 if not enough free blocks -> break
      need = seq.num_tokens - cached*bs
    else: need = seq.num_tokens - seq.num_cached_tokens   # mid-chunk
    if remaining < need and scheduled: break               # only FIRST seq may chunk
    if seq.block_table empty: bm.allocate(seq, cached)
    seq.num_scheduled_tokens = min(need, remaining); batched += that
    if cached + scheduled == num_tokens: RUNNING; waiting.popleft(); running.append
    scheduled.append(seq)
  if scheduled: return scheduled, True

  while running and len(scheduled) < max_num_seqs:
    seq = running.popleft()
    while not bm.can_append(seq):        # needs a new block (len % bs == 1) and none free
      if running: preempt(running.pop()) # victim = YOUNGEST running
      else: preempt(seq); break
    else:
      seq.num_scheduled_tokens = 1; bm.may_append(seq); scheduled.append(seq)
  running.extendleft(reversed(scheduled))
  return scheduled, False

preempt(seq): WAITING; bm.deallocate(seq); waiting.appendleft(seq)   # recompute later

postprocess(seqs, tokens):
  for seq, tok: bm.hash_blocks(seq)       # hash blocks that became full
    seq.num_cached += num_scheduled; num_scheduled = 0
    if prefill and cached < num_tokens: continue   # partial chunk: token DISCARDED
    seq.append(tok); if eos or max_tokens: FINISHED; deallocate; running.remove
```

Prefix cache: hash(block_i) = xxh64(hash(block_{i-1}) || tokens). Only full blocks hashed.
`can_allocate` walks blocks 0..n-2 looking up hashes; stops at first miss.
Model call: prefill -> flash_attn_varlen with slot_mapping; decode -> flash_attn_with_kvcache with block_tables.
Sampler: 12 lines, temperature softmax, on rank 0. Tokenizer: HF, in LLMEngine.
Missing: mixed batches, SWA, spec decode, streaming, cancel, greedy/top-p.

## 2. mini-sglang (~1000 lines scheduler+cache+radix)

```
Req:
  input_ids (cpu, grows by 1 per decode)
  table_idx          row in page_table
  cached_len         tokens whose KV exists
  device_len         = len(input_ids); tokens that must have KV after this step
  max_device_len     = input_len + max_tokens
  cache_handle       locked radix node for [0, cached_len)
  extend_len = device_len - cached_len
ChunkedReq(Req): a partial prefill chunk; can't decode

page_table[max_req+1, max_seq_len]   # TOKEN-granular: row=req, col=pos, value=flat KV slot
                                     # paging = slots allocated in aligned runs; attention
                                     # backend strides page_table[:, ::page_size]//page_size
token_pool[max_req+1, max_seq_len]   # GPU copy of every req's token ids (enables overlap)
free_slots: GPU tensor of page-start slots
RadixTreeNode { key: cpu tokens, value: gpu KV slots (same len), children, parent, ref_count, timestamp }
```

```
overlap_loop(last):
  recv msgs -> pending_list
  batch = prefill_manager.schedule(budget) or decode_manager.schedule()   # prefill first
  launch forward(batch) async on engine stream
  process_last_data(last)          # sync PREVIOUS step, emit tokens
  return (batch, output)

PrefillAdder.try_add(p):           # strict FIFO, stop at first failure
  handle = radix.match(input_ids[:-1])        # never match last token: need >=1 q token
  est = (input_len - handle.cached_len) + output_len
  if est + reserved > available: None         # reserved = sum(remain_len) of running decodes
  lock(handle); table_idx = alloc; copy matched slots into page_table row
  chunk = min(budget, remain)
  return ChunkedReq if chunk < remain else Req

DecodeManager.schedule: Batch(all running_reqs)   # no budget check, no retraction ever
                                                  # (admission reserved max_tokens pessimistically)
forward(batch):
  input_ids = token_pool[mapping]   # gathered on GPU
  logits -> sample -> next_tokens_gpu; token_pool[req, seq_len] = next_tokens_gpu
process_last_data: append token on host; finished -> free table row, insert into radix
```

Radix: match walks by first-page key, splits node at partial match, returns (prefix_len, node).
lock/unlock = walk to root ±ref_count. evict = heap of ref_count==0 leaves by timestamp.
Sampler: flashinfer top_k/top_p on GPU. Tokenizer: separate process via ZMQ.
Missing: retraction, mixed batches, priority policies, spec decode, stop strings.

## 3. vLLM v1 (~4k lines essential)

```
Request:
  status WAITING|RUNNING|PREEMPTED|FINISHED_*
  _all_token_ids (prompt ++ outputs), num_computed_tokens, num_in_flight_tokens
  spec_token_ids[], block_hashes[] (extended as tokens append)

KVCacheBlock: block_id, ref_cnt, block_hash|None, prev/next_free (intrusive DLL)
BlockPool:
  free_block_queue: DLL in LRU order. Freed hashed blocks -> tail (evict last), unhashed -> head
  cached_block_hash_to_block: {hash -> block}
  get_new_blocks(n): pop from head; if block still hashed, drop from map (lazy eviction)
  touch(blocks): ref++; unlink from free queue
  free_blocks: ref--; if 0 push to free queue
KVCacheManager:
  get_computed_blocks(req): walk req.block_hashes, stop at first miss (max hit = n-1)
  allocate_slots(req, n_new, computed_blocks) -> blocks | None; also hashes new full blocks
  free(req): free reversed(blocks)  # tail freed first => evicted first
```

```
schedule():                     # NO prefill/decode distinction. Every req = "N new tokens"
  budget = max_num_batched_tokens
  for req in running:           # phase 1: running first, so decodes never starve
    n = req.num_tokens_with_spec - req.num_computed_tokens
    n = min(n, budget, long_prefill_threshold, max_model_len - computed)
    loop:
      blocks = kv.allocate_slots(req, n); if blocks: break
      victim = running.pop() (FCFS) or lowest priority; free; PREEMPTED; computed=0; waiting.prepend
      if victim is req: break
    if none: break
    record(req, n, blocks); budget -= n
  if not preempted:             # phase 2: waiting fills leftover budget
    while waiting and budget > 0 and len(running) < max_num_seqs:
      req = waiting.peek()
      computed_blocks, n_hit = kv.get_computed_blocks(req) if fresh else (0)
      n = min(req.num_tokens - n_hit, budget)          # chunking falls out of min()
      blocks = kv.allocate_slots(req, n, computed_blocks); if none: break   # no preempt here
      waiting.pop(); running.append; RUNNING; num_computed = n_hit; record; budget -= n
  for req, n in scheduled: num_computed += n; in_flight += n   # advance BEFORE model runs

SchedulerOutput: new reqs (full prompt + block_ids) + cached reqs (DELTA: new tokens, new blocks)
ModelRunnerOutput: sampled_token_ids per req (list, >1 with spec)
update_from_output: in_flight -= n; spec rejects -> computed -= k; append; stop check; free on finish
```
Sampling on GPU worker. Tokenize/detokenize in frontend process.

## 4. SGLang (~5k lines essential)

```
Req: origin_input_ids, output_ids, prefix_indices (KV slots already computed), last_node (radix),
     extend_range [start,end), kv{req_pool_idx, committed_len, allocated_len}, is_retracted
ReqToTokenPool: req_to_token[max_reqs, max_context_len] int32   # token-granular block table
TokenToKVPoolAllocator: free_slots tensor; alloc(n); free(idx)   # paged variant groups by page
RadixCache: TreeNode{children by first-page key, key tokens, value slots, lock_ref, last_access}
  match_prefix, insert, inc/dec_lock_ref (walk to root), evict(n) via LRU heap of leaves
```

```
event_loop: recv -> waiting_queue; batch = get_next_batch_to_run(); run; process_result
get_next_batch_to_run:
  if last was EXTEND: merge it into running_batch (prefill done -> decoding)
  new = get_new_batch_prefill(); if new: return new       # PREFILL PRIORITY
  if running: return update_running_batch()               # DECODE

get_new_batch_prefill:
  policy.calc_priority(waiting)     # FCFS | LPM (sort by longest prefix match) | LOF | priority
  adder = PrefillAdder(rem_total = kv_free + radix_evictable - reserved_for_running,
                       rem_input = max_prefill_tokens, rem_chunk = chunked_prefill_size)
  if chunked_req: adder.add_chunked_req(chunked_req)   # exactly one in flight, continued first
  for req in waiting:
    req.prefix_indices, last_node = radix.match_prefix(fill_ids)
    extend = len(fill_ids) - len(prefix); max_new = min(max_new_tokens - len(out), 4096)
    if extend + max_new + page_size >= rem_total: NO_TOKEN -> break   # DECODE RESERVE
    lock(last_node)
    if extend <= rem_chunk: full; else truncate page-aligned; chunked_req = req
  prepare_for_extend: input_ids = concat new ranges; out_cache_loc = allocator.alloc(n)
                      (evict radix first if short); req_to_token[row, prefix:seq] = out_cache_loc

update_running_batch:
  filter finished
  if not check_decode_mem():        # evict radix, then free >= batch_size?
    retract_decode()                # victims sorted by (len(output_ids), -len(input)): fewest outputs
                                    # each: cache_unfinished, free row, back to waiting (is_retracted)
    new_token_ratio grows           # more conservative reserve after a retract, decays otherwise
  prepare_for_decode: out_cache_loc = alloc(bs); seq_lens += 1; req_to_token[rows, seq_len] = loc

result: append token; check_finished; if finished: radix.insert(fill_ids, req_to_token[row,:len]),
        free duplicate slots, dec_lock_ref, free row.
        after a prefill chunk: cache_unfinished_req inserts what's computed so far, re-locks.

ForwardBatch: forward_mode EXTEND|DECODE|MIXED, input_ids[total], req_pool_indices[b], seq_lens[b],
              out_cache_loc[total], extend_prefix_lens[b], extend_seq_lens[b], sampling_info
```
Sampling in TP worker. Tokenize in TokenizerManager process (ZMQ).

## 5. TokenSpeed (C++ scheduler, ~8.6k lines; docs/design/scheduler.md is worth reading)

- Explicit request FSM: Submitted -> Prefilling -> PrefillDone -> Decoding -> Finished, + Retracted.
  A request with a forward in flight is never retracted.
- Admission is per CHUNK never per prompt; completing chunk reserves decode headroom.
- Head-of-line: an incomplete chunked prefill seals the queue behind it.
- Retraction only when no prefill made progress AND admission failed for capacity.
  Victims: incomplete prefills first (largest), then decodes by most-freeable.
  Retry the blocked admission in the same round. Headroom escalates with retraction_count.
- Phase order per round (mixed): decodes, readmissions, resident chunks, new prompts, retraction.
- ForwardBatch is SoA vectors.

## 6. Where they differ

| | vLLM v1 | SGLang |
|---|---|---|
| Prefill vs decode | Uniform "N tokens"; running first, waiting fills leftover | Explicit; prefill batch first, decode only if none |
| Granularity | 16-token blocks; block table | tokens; req_to_token row; optional pages |
| Prefix cache | hash chain over blocks, flat dict, inserted at schedule time | radix tree over tokens, inserted at finish/chunk, nodes locked |
| Cache-aware order | none | LPM |
| Decode reserve | watermark only; rely on preempt | max_new_tokens at admission; adaptive ratio |
| Victim | last running / lowest priority; recompute from 0 | fewest outputs; keeps radix prefix |
| In-flight chunks | any number | exactly one |
| Step output | delta | full tensors |

Recommendation for kelpie: vLLM's uniform-token-count shape + block hash map + DLL free list is the
smallest regular core. Steal from SGLang: decode reserve at admission, retract-by-fewest-outputs, LPM later.
Steal from TokenSpeed: explicit FSM, chunk-level admission, head-of-line sealing.

## 7. TensorRT-LLM (C++ scheduler + PyTorch backend)

Two-stage per iteration: CapacityScheduler (who gets KV) then MicroBatchScheduler (who runs under max_batch_size /
max_num_tokens). Requests walked in arrival order.
- GUARANTEED_NO_EVICT (default): gen requests always admitted (reserved to completion at admission: prompt+max_new,
  capped by window+chunk, minus reusable prefix); context requests admitted only if blocks_to_completion fits in every
  window pool; head-of-line stop. Never preempts. == reserve_ratio 1.0.
- MAX_UTILIZATION: simulate on a snapshot; need = blocks for the next 1-2 steps; if it doesn't fit, pause the last
  started (youngest) request, retry. Pause folds generated tokens into the prompt and recomputes from the prefix cache.
- MicroBatch: ctx and gen interleaved in arrival order; chunk sizes recomputed every iteration in block multiples
  (FCFS greedy / EQUAL_PROGRESS round-robin / FORCE_CHUNK at Mamba snapshots).
- KV: pool per (window, kv_heads, head_dim, dtype); prefix cache = radix tree of blocks keyed by exact tokens
  (+ lora id, multimodal hashes, cache_salt); inserted on release / context completion; partial in-block reuse;
  per-priority LRU free queues with expiry; host offload before eviction.
- Model contract: forward(attn_metadata, input_ids, position_ids); packed [num_tokens, hidden], contexts first then
  generations; KV never passed as a tensor: pool pointers + per-batch block offsets [pool, seqs, 2, max_blocks]
  filled once per step; layers index metadata by layer_idx.
- CUDA graphs: generation-only, bucketed batch sizes, padded by appending a real dummy request that holds KV,
  preallocated at warmup.
- Hybrid: per-window managers with a static memory split; SWA out-of-window blocks detached; Mamba as a sentinel
  window in the same manager (snapshot points drive chunking); spec drafts via layer_mask + extra kv tokens or a
  separate draft manager.
- Runtime knobs: none live in the PyTorch backend (DynamicBatchConfig is TRT-backend only). Per-request overrides:
  sampling, guided decoding, lora, kv retention priority, cache_salt, priority.
