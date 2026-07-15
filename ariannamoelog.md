# Arianna MoE — операционный лог

Журнал каждого действия по портированию Colibri → тело Арианны (Mistral Small 4 119B MoE).
План: [`PLAN.md`](./PLAN.md). Формат записи: **действие → результат → пруф** (tool / `file:line` / hash).
Разведка и решения — на грунте, не на памяти. Свой claim строже чужого.

---

## 2026-07-15

### R — разведка (ЗАКРЫТА, verified от земли)
- Грунт движка: `glm.c` 5030 / `olmoe.c` 449 / `tok.h` 278 / `tier.h` 60 / `st.h` 233 строк, форк `62419af`. — `wc -l`, `git log`
- Роутер/MLA/YaRN/токенайзер/конфиги сверены — детали и `file:line` в `PLAN.md` (§Грунт, §Модель, §Хирургия).
- polygon (ssh): 6 CPU, 31GB RAM (28 free), SATA `870 EVO 1TB` (524G free) + NVMe `980 250GB`, GPU нет → фаза 1 CPU.
- Mistral Small 4 `config.json` сверен 100% против плана Fable; YaRN раскрыт (beta 32/1, factor 128, `llama_4_scaling_beta 0.1`).
- Итог: 4 задачи хирургии — YaRN (крупн) / роутер (мал) / токенайзер pretok (средн, поднят vs Fable) / конвертор (Python).

### PLAN.md создан
- `~/arianna/arianna-inference/PLAN.md` — наш план на базе плана Fable, грунт + дельта-уточнения.

### P0 — старт
- Прочитаны образцы харнесса: `tools/make_glm_oracle.py`, `tools/make_glm_bench_model.py`, `c/ref_glm.json`.
- Механика: tiny-random модель реальной arch, seq < `index_topk` (DSA no-op → плотная MLA), greedy + teacher-forcing → `ref.json` (`prompt_ids`/`full_ids`/`tf_pred`).
- Python-разрешение: Олег дал явное «да» на Python для offline-tooling Colibri (Санта Муэрте + «пиши» 2026-07-15). Дневной ack-флаг `python-train-ack-20260715.flag` поставлен. **Граница: Python только в оракуле / конверторе / bench; движок инференса — чистый C, без исключений.**
- Среда polygon: голая (python3.12.3, нет torch/transformers). — `ssh polygon`
- Setup: venv `~/moe-venv`, `transformers 5.13.1` (релиз знает `mistral4` — dev не нужен), `torch 2.13.0+cpu`. `Mistral4ForCausalLM` text-only доступен. — `ssh polygon` tool output
- Config-поля `mistral4`: нет `index_topk`/`scoring_func` → DSA и router-bias отсутствуют (подтверждает разведку). GPU нет → torch CPU.
- Структура tiny-mistral4 снята (`ssh polygon` probe): роутер БЕЗ `e_score_correction_bias` (verified `has...bias: False`); эксперты 3D-пакованы `mlp.experts.gate_up_proj (E,2·moe_inter,D)` + `down_proj (E,D,I)` → распаковка конвертором; MLA-имена = GLM (`q_a/q_b/kv_a_proj_with_mqa/kv_b/o_proj`); shared_experts отдельные; `mlp.gate.weight (E,D)` softmax.
- Написан `colibri/c/tools/make_mistral4_oracle.py` (по образцу `make_glm_oracle.py`): tiny mistral4, YaRN (original_max=16, seq=32 → YaRN активна), softmax-роутер без bias, first_k_dense=0. Выход: `mistral4_tiny/` + `ref_mistral4.json` (prompt/full/tf_pred).
- Оракул запущен на polygon (venv): `mistral4_tiny/` + `ref_mistral4.json` записаны, структура тензоров верна.
- ⚠️ НАХОДКА: эталон внутренне НЕсогласован — greedy-свойство `tf_pred[i]==full[i+1]` (i≥11) нарушено: `tf_pred[11]=102` vs `full[12]=120`, `tf_pred[16]=102` vs `full[17]=228`. `generate` (cache) ≠ teacher-forcing (full fwd). C-движку не с чем матчиться однозначно → эталон непригоден как есть.
- ДИАГНОСТИКА (5 diff-прогонов, не теория): ties опровергнуты (gap 6.0@scale1.0 → всё равно mismatch); cache невиновен (`cache==nocache` идентичны байт-в-байт); full-forward causal-инвариантен (`max|dlogit|@pos11=1e-6`). **КОРЕНЬ: `model.generate()` ≠ raw arch-greedy** — обёртка флипает первый decode-токен (`argmax(logits[11])=102` в обоих forward-путях, generate выдал 120), при этом `generation_config` чистый (нет rep_penalty). Фикс: эталон = RAW greedy (ручной argmax). Verified: raw-greedy consistency **20/20** vs generate 8/20.
- 📌 Урок для всего P0-харнесса (+ намёк Fable по `make_glm_oracle.py`): эталон строить raw-greedy, не `model.generate()`.
- ✅ P0 golden эталон ГОТОВ (polygon `~/moe-p0/`): `ref_mistral4.json` + `mistral4_tiny/` (config+safetensors). Raw-greedy self-consistency **20/20** (tool). Эталон = чистый arch-greedy, C-движок его воспроизведёт.
- СЛЕДУЮЩЕЕ: C-фронтенд `arch_mistral4` (softmax-роутер + MLA config-driven + YaRN + pretok-ветка) → token-exact сверка с эталоном = гейт P0.
