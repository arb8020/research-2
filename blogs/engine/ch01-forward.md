# ch01: the GPT-2 forward pass

<!-- page: connect -->

<!-- page: workspace=ch01 -->

<!-- wip: chapter 1 slice: the cells, checks and workspace are real; the prose is placeholder (TODO: the author writes it) -->

<!-- TODO prose (placeholder): Click Connect now: the first connect builds your sandbox, which takes about
3 minutes. Keep reading while it does; your edits are kept and Run waits for it. -->

<!-- TODO prose: what this chapter builds (GPT-2 small, one sequence, greedy decode) and how cells work: every cell
below is a view of the same gpt2.py in your workspace; Run checks the ops of that cell against the whole file as it is. -->

Every cell on this page shows one region of `gpt2.py` (the file in your sandbox). Edit anywhere; Run checks this
cell's ops.

## Linear

<!-- TODO prose: x @ w + b as einsum("T D, D F -> T F"); GPT-2 stores linears [in, out] (Conv1D), so no transpose;
the shape-suffix names (x_TD, w_DF) and the letters. -->

```python cell=linear file=gpt2.py
```

## GELU

<!-- TODO prose: the tanh approximation GPT-2 was trained with (gelu_new), and why "exact" GELU is a bug here. -->

```python cell=gelu file=gpt2.py
```

## Layer norm

<!-- TODO prose: mean / biased variance over the last dim, eps inside the sqrt, then scale and shift. -->

```python cell=layer_norm file=gpt2.py
```

## Attention

<!-- TODO prose: "T N H, S N H -> N T S" scores / sqrt(H), the causal mask (key s <= query t), softmax over S, then
"N T S, S N H -> T N H"; self_attention: load() gave w_qkv_D3NH (c_attn unfused) and w_o_NHD. -->

```python cell=attention file=gpt2.py
```

## The block

<!-- TODO prose: pre-norm residual block: attention then MLP (4x up, GELU, down). -->

```python cell=block file=gpt2.py
```

## Forward

<!-- TODO prose: token + position embeddings, 12 blocks, final norm, the tied lm head. -->

```python cell=forward file=gpt2.py
```

## Generate

<!-- TODO prose: greedy decode by recomputing the whole prefix every step (the KV cache comes later). -->

```python cell=generate file=gpt2.py
```
