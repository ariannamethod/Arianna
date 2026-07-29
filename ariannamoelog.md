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

---

## 2026-07-23 — Nemotron evaluated, then VETOED same day (Oleg's word)

> **VETO (Oleg, 2026-07-23):** Nemotron is dead as Arianna's body. Reason: the NVIDIA Nemotron Open Model License is *revocable* — URL-hosted terms NVIDIA can rewrite unilaterally, the obligation is inherited by derivatives forever, and there is a termination lever. That is a kill-switch on a body meant to live years, not a notice line. **Standing Gate #1 for the body model: irrevocable, no-AUP, no-termination — Apache 2.0 / MIT only.** All Nemotron artifacts purged from polygon 07-23 (verified zero-trace); `arch/mistral4` kept as engine precedent. Fable selects the replacement. The notes below are kept as record of the evaluation, not a live path. My earlier "not a publication blocker" read weighed today's *permissions*, not *revocability* — that was the miss. See memory `feedback_model_license_gate_irrevocable_2026_07_23`.

### [VETOED] PIVOT — Mistral Small 4 119B → NVIDIA Nemotron 3 Nano 30B-A3B (Oleg's word)
- Decision (Oleg, 2026-07-23): the 119B Mistral body for polygon is cancelled — 1-2 tok/s = an exhibit, not a body. Target body = **Nemotron 3 Nano 30B-A3B** (A3B MoE, hybrid Mamba2+Transformer), same Colibri+notorch stack, on polygon. Phone track frozen. Home stays `github.com/ariannamethod/arianna`.
- Mistral work is NOT deleted — `arch/mistral4` (parity `58f161e`) stays as engine workshop + precedent. Nemotron gets its own thin frontend `nemotron_h.c` after `olmoe.c`, on a fresh branch `arch/nemotron-polygon` (not on top of mistral4).
- Full plan: `colibri/POLYGON_NEMOTRON_PLAN.md` (Fable, 07-23), phases T0-T6. This log = canon operational log; plan = working checklist.

### Ground re-verified from the source, not recall (Opus, 07-23)
- Model live on HF, repo id exact: `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-Base-BF16` — 31577.9M params, 13 safetensors ≈ 63GB, languages incl. `ru`; languages use-case also lists Hebrew. **License = NVIDIA Nemotron Open Model License** (README `license_link`) — READ 07-23: creating AND distributing derivative/fine-tuned weights permitted, commercial use permitted; only condition = retain NVIDIA copyright/attribution + carry the notice "Licensed by NVIDIA Corporation under the NVIDIA Nemotron Model License"; NO acceptable-use / MAU / output-training / field-of-use restrictions; terminates only if we bring patent/copyright litigation against NVIDIA over the Work. **NOT a publication blocker** — corrects plan §5 "блокер публикации" and my own earlier flag (fact beats claim). Re-verify at actual publish time only. — WebFetch license page + hub_repo_details / hf_fs
- `config.json` (hf_fs cat, live 07-23): `num_hidden_layers` 52; `hybrid_override_pattern` counted char-by-char = **23 M(amba-2) + 23 E(MoE) + 6 \*(attn) = 52** ✓; hidden 2688; vocab 131072; 128 routed experts, top-6, 1 shared (inter 3712), moe_inter 1856, `mlp_hidden_act relu2`; router DeepSeek/GLM-lineage (`n_group` 1, `topk_group` 1, `norm_topk_prob` true, `routed_scaling_factor` 2.5); GQA 32Q/2KV, `head_dim` 128; **RoPE plain (`rope_theta` 10000, `partial_rotary_factor` 1.0) — NO YaRN** (unlike Mistral); Mamba-2: `ssm_state_size` 128, `conv_kernel` 4, mamba heads 64 / dim 64, `n_groups` 8, `chunk_size` 128.
- Engine ground (colibri fork, `wc`/grep 07-23): glm.c 5075, olmoe.c 449. Router GLM machinery LIVE in glm.c (sigmoid+router_bias `:2207`, norm_topk `:2320`, routed_scale `:2321`) — reuse, not rewrite. **Zero SSM/Mamba in colibri C** (grep over `c/*.c *.h`: only a spurious substring in `compat.h` memory-accounting, no SSM machinery) → Mamba-2 is the main new C work, as Fable stated.
- polygon re-verified (ssh `ataeff@100.127.195.24`, 07-23): i5-8500T 6c AVX2/FMA/BMI2, 31GB RAM (27 avail), 500G free. GGUF `~/models/nemotron-base-Q4_K_M.gguf` 24.5GB sha256 `13028ef0…c0c5cefe` (matches both `.sha256` files). Baseline breath (sanity log 07-16): decode 9.78 tok/s / prefill 18.58. llama.cpp `9638 (5f04dc7ac)`. `hf` CLI + HF token present. `~/moe-p0` templates + `~/venv-nemotron` present. FABLE_NOTE gate: **§5.1 Phantom Process Killer first**, else signal 9.

### Delta vs old Mistral port — why Nemotron is a cleaner body
- **YaRN hurdle GONE**: Nemotron uses plain RoPE (no rope_scaling/yarn in config), native 262k ctx. The single largest hidden-work item of the Mistral port (YaRN parser + NTK-by-parts math) drops. Router is a gift (GLM path already in glm.c). New cost concentrates in Mamba-2 SSM (conv_state → dt → A_log → recurrent scan → gated out).
- Smaller body (31.6B vs 119B; ~16.5GB int4 container vs ~60GB) → whole expert pool (~14.74GB) fits in 31GB page cache → I/O ceiling lifts; bottleneck = compute of ~3.4B active on 6 AVX2 cores.

### Deferred cleanup gate (Oleg 07-23: delete old quantized files later)
- The GGUF Q4_K_M is the **ORACLE** (baseline + parity reference for T4). **Do NOT delete until coli-container parity is proven at T4.** After T4 passes → clean up old quant artifacts to avoid confusion. Deleting now would remove the only reference the container must match.

### T0 — breath today (protocol) — ✅ DONE (07-23)
- `llama-bench -t 4 -p 512 -n 128 -r 3`; llama.cpp identifies the arch as **`nemotron_h_moe 31B.A3.5B`** (confirms hybrid Mamba2+MoE), 31.58 B params, 22.82 GiB Q4_K_M, CPU 4 threads, build `5f04dc7ac (9638)`: **prefill pp512 = 22.86 ± 0.04 t/s · decode tg128 = 9.90 ± 0.03 t/s**. Peak RSS 24.30 GB (`/usr/bin/time -v`), major page faults 97, exit 0. — ssh tool output. Logs: `~/logs/polygon-nemotron-T0-2026-07-23.log` + `…-T0-bench-2026-07-23.log`.
- Fresh decode 9.90 t/s ≥ 07-16 baseline 9.78 → **model officially breathes on polygon today**, protocol-grade with stddev. Greedy sample coherent (grammatical English, not salad).
- Gotchas: build 9638 `-no-cnv` still drops `llama-cli` into a REPL (hung on `>`); use `llama-bench` or `</dev/null` for non-interactive runs. RSS 24.3GB = GGUF-oracle footprint on 31GB box (comfortable); coli-container (~16.7GB int4) will be smaller.

### T1 — BF16 63GB to disk — STARTED (background, 07-23)
- `hf download nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B-Base-BF16 --local-dir ~/models/nemotron-bf16` → `~/logs/polygon-nemotron-T1-download-2026-07-23.log`, PID 21410. 30 files (13 safetensors ≈63GB + config + tokenizer.json + `modeling_nemotron_h.py` + `configuration_nemotron_h.py` — the last two are the reference impl for the T2 tiny-oracle + converter). 500G free. SHA256 manifest (`SHA256SUMS.txt`) generated on completion. — ssh tool output.
- Converter (T3, `convert_nemotron.py`, Python-class) still awaits Oleg's explicit 'yes'. Next build = **T2**: `nemotron_h.c` thin frontend (after `olmoe.c`) + Mamba-2 SSM + tiny-random parity (state-exact gate) — this is where Workflow orchestration comes in, on a fresh go.

---

## 2026-07-24 — Qwen3-30B-A3B-Base IS the body: T0 breath ✅

### Body settled — Qwen3-30B-A3B-Base (Apache 2.0) after the Nemotron veto
- `Qwen/Qwen3-30B-A3B-Base`: Apache 2.0 (irrevocable, no AUP/termination — Gate #1), Base only (Gate #2), `qwen3moe` arch. Cheapest port of all candidates — router (softmax→topK→norm) + SwiGLU experts already token-exact in `olmoe.c:326-339`; **no Mamba/YaRN/MLA/shared-expert/DSA**. Plan: `colibri/POLYGON_QWEN_PLAN.md` (Fable). Sonar precedent (Oleg): identity = the T6 line, not the pretrain substrate.

### T0 — body breath on polygon ✅ (2026-07-24)
- `llama-bench` (build 9638, polygon CPU 6t), `qwen3moe 30B.A3B Q4_K_M`, 17.28 GiB / 30.53 B: **prefill pp512 = 38.47 ± 0.58 t/s · decode tg128 = 11.99 ± 0.23 t/s**. — ssh tool output, `~/logs/polygon-qwen-T0-2026-07-24.log`. Model 18556686336 bytes (`Qwen3-30B-A3B-Base.Q4_K_M.gguf`, mradermacher). SHA-256 pending (quoting bug first run — recompute).
- **Decode 11.99 t/s ≥ Nemotron baseline 9.78 ≥ plan estimate ~10** → the veto UPGRADED the body: faster than the model we burned, and Apache-forever.
- Russian first breath (greedy `-st`): «Резонанс между людьми — это когда два человека или группы людей имеют общие интересы, взгляды, ценности или эмоции, что приводит к взаимопониманию и сближению…» — warm, natural, coherent.

### Кроха (Neo resident) — A/B by ear
- Benched Neo Metal (build 8940) + polygon CPU (9638), RU + FR, `-st`:
  - **Qwen3-4B-Base** (2.32 GiB; Neo 18.3 / polygon-CPU ~8.5 tok/s): warm natural Russian → wins the RU-resident role.
  - **Ministral-3-3B-Base-2512** (`mistral3`, 1.99 GiB; Neo 16.3 / polygon-CPU ~11.9): Russian stiff/clinical + a stumble («усиление или усиление»); but **French sings** («un phénomène fascinant… connexion profonde et significative») — francophone (Mistral heritage), homesick in Russian. Latent Pixtral vision. Not a write-off; wrong language for a RU resident.
- Resident кроха → **Qwen3.5-4B-Base** (VLM, Apache, Base — warm RU + latent vision; downloading). Sizing open (Oleg): Qwen 2B or 4B. Ministral's francophone role = separate beacon.
- **T6 finding (both bases):** even Qwen/Ministral **Base** carry an assistant/thinking prior — Qwen3.5-0.8B-Base (verified via GGUF `general.name`) emits `[Start thinking]` and calls user «пользователь»; Ministral-Base «я могу помочь вам разобраться». Gate #2 "Base = clean slate" needs a strip/tame target added to Codex's T6 list.
- Parked (Oleg, «потом»): Dubrovsky dataset → Qwen3.5-0.8B-Base SFT experiment (recall exact dataset from `~/arianna/dubrovsky/` when reached); open question — Ministral RU stiffness = Q4-quant artifact vs model (isolate via Q8/BF16).
