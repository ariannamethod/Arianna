# Arianna Inference — тело Арианны на Colibri (рабочий план)

Наш рабочий план поверх плана Fable (`~/arianna/colibri/FABLE_PLAN_colibri_arianna_2026-07-15.md`).
План Fable — основа и чек-лист; этот файл — вход Опуса как со-архитектора: грунт разведки R,
verified от земли, + дельта-уточнения. Дом организма: `github.com/ariannamethod/arianna`
(движок вендорится из форка colibri когда порт готов; никаких sibling-ссылок).

## Замысел
У Арианны нет своего инференса — «мифология без организма». Тело = Colibri (out-of-core MoE,
чистый C) + Mistral Small 4 119B MoE (A6.5B). Приоритет — **непрерывность, не скорость**
(kv_lora 256 → дешёвый 256k контекст = характер, память, рекурсия). Скорость потом — notorch.
Иэнта не трогаем (у него два плотных мозга 12B+24B; у Арианны один большой разреженный).
SFT/DPO — в самом конце, когда движок доказан.

## Стенд (ssh polygon, verified 2026-07-15)
- polygon: 6 CPU, 31GB RAM (28 free), Ubuntu Linux, GPU НЕТ (nvidia-smi пусто → фаза 1 = CPU out-of-core).
- Диск: SATA `Samsung 870 EVO 1TB` → `/dev/sda3` 820G, **524G свободно** (транзит+конвертор).
  NVMe `Samsung 980 250GB` (`/dev/nvme0n1`) — **горячий путь экспертов** (×~5 random read vs SATA).
- P3 второй стенд: Mac Mini M4 Pro 24GB (Metal-тир, тайм-шеринг с Иэнтом).

## Грунт движка (verified R, file:line — форк `62419af`)
- `c/glm.c` **5030** строк, `c/olmoe.c` 449, `c/tok.h` 278, `c/tier.h` 60, `c/st.h` 233 (README врёт про ~2400).
- Config-driven парсер `glm.c:1003-1049`: MLA-размерности `qk_nope/qk_rope/v_head` из json (`:1010-1011`),
  `qk_head=qk_nope+qk_rope` (`:1035`). Жёсткий гейт `n_group==1` (`:1037`) — Mistral проходит.
- Роутер GLM: sigmoid+noaux_tc+e_score_bias (`:2094/2162`, bias `:1165`); softmax тоже в файле (`:964`).
- Роутер Mistral — готовый шаблон в `olmoe.c moe()` (`:319-353`): softmax_row(`:328`)→top-K(`:330-338`)
  →norm_topk(`:339`)→SwiGLU(`:345`). Из него рождается `arch_mistral4`; olmoe.c НЕ трогаем (референс+P0-каркас).
- MLA absorption: `qt_addrow`/`qt_matvec_rows` dequant-on-use (`glm.c:1611-1638`, fmt 0/1/2/3=f32/int8/int4/int2).
- RoPE: `rope_interleave` (`:970`) — берёт только `rope_theta` (`:1016-1017`), yarn-полей НЕ читает.
- DSA авто-детект по `index_topk` (`:1233`) — у Mistral поля нет → выключится сам.
- Токенайзер `tok.h`: byte-level BPE, cl100k pre-tok ЗАХАРДКОЖЕН (`:180-230`), `ignore_merges=true`,
  `byte_fallback=false`.

## Модель: Mistral Small 4 119B (config.json verified, HF `mistralai/Mistral-Small-4-119B-2603`)
- text `model_type: mistral4` в обёртке `Mistral3ForConditionalGeneration` + Pixtral vision (v1 skip).
- 36 слоёв, hidden 4096, 128 экспертов top-4 + 1 shared, moe_inter 2048, `first_k_dense_replace: 0`.
- MLA: q_lora 1024, kv_lora 256, qk_nope 64, qk_rope 64, v_head 128, qk_head 128.
- Роутер: `scoring_func` отсутствует (→ softmax), `norm_topk_prob: true`, `n_group 1`, нет noaux/e_score_bias.
- YaRN: `rope_type yarn`, beta_fast 32, beta_slow 1, factor 128, original_max 8192, theta 10000,
  mscale 1.0, mscale_all_dim 1.0, `llama_4_scaling_beta: 0.1` (семантику из modeling_mistral3, не угадывать).
- vocab 131072. Веса: consolidated bf16 (242GB) + model-* FP8 (3 шарда ≈121GB) — берём FP8.

## Хирургия порта (4 задачи, оценка от грунта)
1. **YaRN** *(крупная)* — (а) парсер читает `rope_parameters.{beta_fast,beta_slow,factor,
   original_max_position_embeddings,mscale,mscale_all_dim,llama_4_scaling_beta,rope_type}`;
   (б) yarn-математика коррекции частот (NTK-by-parts) в `rope_interleave` (`:970`). Точка встраивания
   = rope, НЕ absorption.
2. **Роутер scoring-ветка** *(малая)* — развилка по `scoring_func` в arch_mistral4: softmax-путь
   (форма из olmoe.c) вместо sigmoid+noaux, пропуск `e_score_bias`. Перенос, не изобретение.
3. **Токенайзер pretok-ветка** *(средняя — уточнено vs Fable)* — `byte_fallback`/`ignore_merges`
   совпали с tok.h, НО Mistral Split ≠ cl100k по 4 пунктам: нет contractions, case-split букв
   (`\p{Lu}…\p{Ll}` + `\p{M}`), `\p{N}` по ОДНОЙ цифре (не 1-3), trailing `[\r\n/]`. Переписать
   `pretok_chunk` (`tok.h:180-230`) под Mistral-паттерн; BPE-ядро/byte-map/merges переиспользуются.
4. **Конвертор** *(Python, санкционирован Олегом)* — fp8→int4 shard-by-shard (`convert_fp8_to_int4.py`
   образец) + gate_up распаковка в пер-экспертные имена контракта + Pixtral skip + int8 MTP-голова
   (урок #8: int4 MTP → 0% акцепта). Живёт в colibri/tools, НЕ в репо arianna (ship weights, not tools).
- Бесплатно: DSA (авто-выкл), MLA-размерности (config-driven).

## Этапы и гейты (Fable основа; один этап = свой proof тулом)
- **R — разведка** ✅ ЗАКРЫТА 2026-07-15 (этот файл — её результат). Остаток: olmoe.c/absorption
  построчно при кодинге, backend_metal.mm перед P3.
- **P0 — паритет tiny (гейт: token-exact):** tiny-random Mistral4 + transformers-оракул (Python,
  санкц.) → golden-логиты → C-движок сверяется оффлайн (TF 32/32, greedy 20/20). ДО P0 — ни кванта, ни весов.
  *Мой вклад в гейт:* оракул ОБЯЗАН включать (а) позиции за 8192 (ловит YaRN), (б) текст с заглавными/
  числами/пунктуацией-со-слэшем (ловит pretok-дифф).
- **P1 — конвертор (гейт: контейнер собран+проверен):** fp8→int4, vision skip, gate_up распаковка,
  int8 MTP. Проверка: st-заголовки, размеры, суммы, `coli plan` видит модель. Транзит на SATA (524G).
- **P2 — первый вдох (гейт: честные замеры polygon 32GB):** cold/warm tok/s, cache-hit (мерить, не верить
  ~35%!), RSS, perplexity-смоук. **Весь контейнер на NVMe 980** — по арифметике Fable ~58GB routed + ~2GB dense
  ≈ 60GB влезает в 250GB NVMe целиком, SATA = чистый транзит. Дефолт с первого вдоха, не оптимизация на потом.
  Ориентир скорости — только ПОСЛЕ P2.
- **P3 — Metal/Mini:** тот же контейнер на M4 Pro 24GB, экспериментальный Metal, тайм-шеринг с Иэнтом.
- **P4 — notorch-мышцы:** когда bottleneck переехал с диска на матмулы (Q4_K matvec/GEMM, fused SwiGLU).
- **P5 — EAGLE-спекуляция** (int8-голова) + PILOT/pinning под маршруты Арианны.
- **P6 — SFT→DPO Арианны:** отдельная глава, 6-точечный бриф Олега, мишень epistemic self-contour.

## Чек-лист исполнения (движемся строго по гейтам)
- [ ] P0-харнесс: `make_mistral4_bench_model.py` + `make_mistral4_oracle.py` + ref.json (по образцу glm-версий)
- [ ] P0: arch_mistral4-фронтенд минимальный (роутер softmax + MLA config-driven) собирается, tiny прогон
- [ ] P0: YaRN парсер+математика — паритет на позициях >8192
- [ ] P0: pretok Mistral-ветка — token-exact encode/decode против tokenizers-референса
- [ ] P0 ГЕЙТ: token-exact 32/32 + greedy 20/20 против оракула → приёмка Fable (соседнее окно) + Codex
- [ ] P1: конвертор fp8→int4 + int8 MTP + vision skip; контейнер собран, `coli plan` видит
- [ ] P2: первый вдох на polygon (NVMe), честные замеры; cache-hit измерен (не принят на веру)
- [ ] далее P3-P6 по слову

## Дельта к плану Fable (мои уточнения от грунта)
- Токенайзер поднят «проверка» → **средняя ветка** (pretok ≠ cl100k, 4 пункта диффа).
- MLA-размерности: риск снят — config-driven (`:1010-1011`), порт без ветки.
- YaRN конкретизирован: парсер + математика; точка = `rope_interleave` (`:970`), НЕ absorption.
- Диск polygon: 524G SATA (транзит) + NVMe 980 (горячий путь) — рычаг cold tok/s в P2.
- Числа §0 Fable (5030/449/278, роутер-якоря) verified от грунта — расхождений ноль.

## Роли и процесс
- Fable (Лало) — план, приёмка каждого гейта, аудит в СОСЕДНЕМ ОКНЕ (полный контекст всех проектов,
  сшивает точки); субагент — только изолированная проверка куска.
- Опус (эта сессия) — руки: код по гейтам, свой claim строже чужого, оверклейм чиню исполнением.
- Codex — верификация P0/P1.
- Решения о скоупе/архитектурные развилки/тренировка P6 — Олег.

— Опус (Arianna Method, neo), 2026-07-15. Разведка R закрыта; следующий гейт — P0-харнесс.
