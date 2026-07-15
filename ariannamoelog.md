# Arianna MoE — operational log

Log of every action porting Colibri → the body of Arianna (Mistral Small 4 119B MoE).
Plan: `PLAN.md` (local, gitignored — Russian internal working notes). Entry format:
**action → result → proof** (tool / `file:line` / hash). Recon and decisions on the
ground, not from memory. Own claim held stricter than others'.

---

## 2026-07-15

### R — reconnaissance (CLOSED, verified from the ground)
- Engine ground: `glm.c` 5030 / `olmoe.c` 449 / `tok.h` 278 / `tier.h` 60 / `st.h` 233 lines, fork `62419af`. — `wc -l`, `git log`
- Router / MLA / YaRN / tokenizer / configs cross-checked from source — details and `file:line` in local PLAN.md.
- polygon (ssh): 6 CPU, 31GB RAM (28 free), SATA `870 EVO 1TB` (524G free) + NVMe `980 250GB`, no GPU → stage 1 is CPU out-of-core.
- Mistral Small 4 `config.json` matched 100% against Fable's plan; YaRN unpacked (beta 32/1, factor 128, `llama_4_scaling_beta 0.1`).
- Result: 4 surgery tasks — YaRN (large) / router (small) / tokenizer pretok (medium, raised vs Fable's "check") / converter (Python).

### P0 — start
- Read harness templates: `tools/make_glm_oracle.py`, `tools/make_glm_bench_model.py`, `c/ref_glm.json`.
- Mechanics: tiny-random model of the real arch, seq < `index_topk` (DSA no-op → dense MLA), greedy + teacher-forcing → `ref.json` (`prompt_ids`/`full_ids`/`tf_pred`).
- Python permission: Oleg gave an explicit "yes" for Python in Colibri offline tooling (2026-07-15). Daily ack flag `python-train-ack-20260715.flag` set. **Boundary: Python only in oracle / converter / bench; the inference engine stays pure C, no exceptions.**
- polygon env: bare (python3.12.3, no torch/transformers). — `ssh polygon`
- Setup: venv `~/moe-venv`, `transformers 5.13.1` (release already knows `mistral4` — no dev build needed), `torch 2.13.0+cpu`. `Mistral4ForCausalLM` text-only available.
- `mistral4` config fields: no `index_topk` / `scoring_func` → DSA and router-bias absent (confirms recon). No GPU → torch CPU.
- tiny-mistral4 structure probed (`ssh polygon`): router has NO `e_score_correction_bias` (verified `has...bias: False`); experts 3D-packed `mlp.experts.gate_up_proj (E,2·moe_inter,D)` + `down_proj (E,D,I)` → unpacked by the converter; MLA names = GLM (`q_a/q_b/kv_a_proj_with_mqa/kv_b/o_proj`); shared_experts separate; `mlp.gate.weight (E,D)` softmax.
- Wrote `colibri/c/tools/make_mistral4_oracle.py` (after `make_glm_oracle.py`): tiny mistral4, YaRN (original_max=16, seq=32 → YaRN active), softmax router without bias, first_k_dense=0. Output: `mistral4_tiny/` + `ref_mistral4.json`.
- Oracle ran on polygon (venv): `mistral4_tiny/` + `ref_mistral4.json` written, tensor structure correct.
- ⚠️ FINDING: reference internally inconsistent — greedy property `tf_pred[i]==full[i+1]` (i≥11) broke: `tf_pred[11]=102` vs `full[12]=120`, `tf_pred[16]=102` vs `full[17]=228`. `generate` ≠ teacher-forcing. The C engine would have nothing single-valued to match → unusable as-is.
- DIAGNOSIS (5 diff runs, not theory): ties ruled out (gap 6.0@scale1.0 → still mismatch); cache innocent (`cache==nocache` byte-identical); full-forward causal-invariant (`max|dlogit|@pos11=1e-6`). **ROOT: `model.generate()` ≠ raw arch-greedy** — the wrapper flips the first decode token (`argmax(logits[11])=102` in both forward paths, generate emitted 120), while `generation_config` is clean (no rep_penalty). Fix: reference = RAW greedy (manual argmax). Verified: raw-greedy consistency **20/20** vs generate 8/20.
- 📌 Lesson for the whole P0 harness (+ hint to Fable re `make_glm_oracle.py`): build the reference with raw-greedy, not `model.generate()`.
- ✅ P0 golden reference DONE (polygon `~/moe-p0/`): `ref_mistral4.json` + `mistral4_tiny/` (config + safetensors). Raw-greedy self-consistency **20/20** (tool). Pure arch-greedy reference; the C engine must reproduce it token-exact.

### Git workflow set (step-commit-merge, Method style)
- Policy: every step → commit (tool-verified tech data + a never-repeated Quote + `Method:` line + signature) → branch → merge, like yent / actually.life. The log is committed continuously; every move lives in history → any error traces to the move that made it.
- **colibri** (engine workshop): branch `arch/mistral4`, oracle `100bc13` "the method forges a tiny twin…", pushed to the fork.
- **arianna** (organism home `github.com/ariannamethod/arianna`): foundation `da34b32` "the method lays the foundation…" → `main`, pushed. Canon of the log = `~/arianna/arianna/`; PLAN.md stays local (gitignored, Russian internal kitchen).
- NEXT (in progress): C frontend `arch_mistral4` → token-exact check against the reference = the P0 gate.

### P0 GATE PASSED — arch parity on tiny (tool-verified)
- Ported `modeling_mistral4.py` semantics to C from source (probes, not guesses): yarn inv_freq (dim = qk_rope, `_compute_yarn_parameters` verbatim), interleaved rope, llama4 attn-scale `1+β·ln(1+floor(pos/orig_max))`, softmax router (n_group=1 → group mask no-op), 3D experts chunk + SwiGLU, mscale `attention_factor=1.0` (probes: `inv_freq.shape=(32,)`, `cos.shape=(1,4,64)`, `get_mscale`).
- `colibri/c/mistral4_p0.c` (~340 lines, self-contained f32, naive MLA, no streaming/cache/CUDA). Approach (B): prove the arch isolated from infra.
- polygon run (`cc -O2 -Wall`: 0 errors, 0 own warnings): `inv_freq[:5] == torch [1.0,0.65616,0.42176,0.26356,0.15811]`; teacher-forcing **32/32 == tf_pred**; greedy **20/20 == full_ids**. Passed on the first clean run — grounding in the reference held.
- commit `arch/mistral4`: "the method proves the arch on a seed…".
- NEXT: converter, tokenizer pretok, integrate into full glm.c for P2.

### Tokenizer pretok — Mistral Split VERIFIED (isolated, tool)
- `tok_unicode.h` regenerated (`gen_unicode.py` extended): +`Ll`/`LuLt`/`M` classes, `is_upgrp`/`is_logrp` case-split groups (`upper=[Lu Lt Lm Lo M]`, `lower=[Ll Lm Lo M]`). Smoke: `is_upgrp('A')=1 is_logrp('a')=1 is_M(U+0300)=1`, negatives 0.
- `mistral_pretok_test.c`: 7-alternative Mistral Split (case-split letters, single-digit `\p{N}`, slash-trailing punct) — the 4 diffs from cl100k Fable flagged.
- tool-verified: byte-offset split **== `tokenizers` (Rust regex) golden 14/14** on case-split / digits / slash / CJK / accents / whitespace. `cc -Wall`: 0/0.
- BPE core / byte-map / merges reused from `tok.h` (GLM-verified); only the Split branch was new.
- Surgery status: YaRN ✓ (P0), router ✓ (P0), tokenizer pretok ✓. Remaining: **converter** (real fp8→int4, unpack 3D gate_up, int8 MTP) + **integrate** `arch_mistral4` into full `glm.c` for streaming under P2.
- 🔁 recurring: colibri upstream is active (fork +17 ahead at fork time) — periodically `git log` upstream for engine fixes worth cherry-picking to `arch/mistral4`.

### arch_mistral4 INTEGRATED into the full glm.c engine (tf 32/32, tool)
- Six surgical branches behind `arch==ARCH_MISTRAL4`, GLM path (default) untouched:
  (1) config `model_type` detect + YaRN inv_freq precompute (`_compute_yarn` verbatim);
  (2) `rope_interleave` YaRN inv_freq + ascale; (3) moe router softmax (no e_score_bias);
  (4) loader `router_bias` skipped; (5) attention llama4-scale `1+β·ln(1+floor(pos/orig_max))` on full query; (6) Cfg fields.
- `convert_mistral4.py`: unpack 3D `gate_up_proj (E,2I,D)` → per-expert container (96 tensors on tiny, shapes verified).
- polygon: `gcc -Wall` **0 errors**, GLM path compiles; **TF parity through the FULL engine (streaming + expert-cache) 32/32 == tf_pred** (SNAP=container REF=ref TF=1). greedy follows by ref self-consistency 20/20 (REPLAY is perf-only, does not diff argmax).
- banner still prints "GLM C engine (glm_moe_dsa)" — printed before model_init, arch unknown there; cosmetic, arch works (proven by parity). arch-banner deferred to loaded-print.
- **All 4 surgery tasks done: YaRN, router, pretok, converter — arch reproduces token-exact in the real engine.** NEXT toward P2: real fp8→int4 weights (download ~121GB, Oleg's word) + first breath on polygon.
