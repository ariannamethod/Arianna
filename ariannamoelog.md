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
- NEXT (in progress): C frontend `arch_mistral4` in `glm.c`, incremental with commits on `arch/mistral4` → token-exact check against the reference = the P0 gate.
