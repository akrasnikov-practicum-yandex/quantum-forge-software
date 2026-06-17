# Задание 4. RAG-бот с техниками промптинга

**Проект:** RAG-бот для корпоративной базы знаний QuantumForge Software
**Дата:** 2026-06-17

---

## 1. Архитектура RAG-цепочки

```
User query
    │
    ▼
HuggingFaceEmbeddings            ← all-MiniLM-L6-v2, dim=384
    │  embed(query)
    ▼
FAISS.similarity_search_with_score(k=4)
    │
    ▼
Relevance Guard                  ← score ≥ 1.3 → «I don't know» (без вызова LLM)
    │ if relevant chunks found
    ▼
Prompt Composer
  ├── System (роль + CoT-инструкция + правило «только контекст»)
  ├── Few-shot примеры (2 Q/A из домена Astral Strife)
  ├── Context block (чанки [1]..[4] с источниками)
  └── User question
    │
    ▼
ChatOllama (llama3.2:3b, localhost:11434, temperature=0)
    │
    ▼
Answer + Sources
```

Реализация: [`scripts/rag_bot.py`](../scripts/rag_bot.py)

**Принцип**: явные шаги (не RetrievalQA-«чёрный ящик»), что позволяет отлаживать каждый этап.

---

## 2. LLM

| Параметр | Значение |
|---|---|
| **Движок** | Ollama (`localhost:11434`) |
| **Модель** | `llama3.2:3b` |
| **Temperature** | 0 (детерминизм) |
| **Расположение** | Полностью локально, данные не покидают машину |
| **Соответствие SOC 2** | ✅ (on-prem, как рекомендовано в Task-1) |

---

## 3. Структура промпта

### System (роль + CoT)

```
You are an expert assistant for the Astral Strife knowledge base.
Rules:
1. Think step by step before answering (Chain-of-Thought):
   Step 1: Identify what the question is asking.
   Step 2: Find relevant facts in the provided context documents.
   Step 3: Synthesise the facts into a clear answer.
   Step 4: Cite sources as [1], [2], etc.
2. If the context does not contain enough information, reply EXACTLY:
   "I don't know — the knowledge base contains no supporting evidence..."
3. Never use knowledge outside the provided context.
```

### Few-shot примеры (2 пары Q/A)

Примеры **grounded в реальных фактах** из `knowledge_base/` — не выдуманные:

```
Q: What is the power source of the arc-glaive?
A:
Step 1: The question asks about the energy source of the arc-glaive weapon.
Step 2: A reson crystal is placed at the heart of every arc-glaive...
Step 3: The arc-glaive is powered by a reson crystal.
Answer: The arc-glaive is powered by a reson crystal... [1]

Q: What happened to the Aurelian Concord?
A:
Step 1: The question asks about the fate of the Aurelian Concord.
Step 2: The context states that Overlord Malkor transformed the Synod-led Concord...
Answer: The Aurelian Concord collapsed following the Vat Wars... [1]
```

### Context block

Нумерованные чанки из FAISS с указанием источника:
```
[1] Xarn Velgor (source: knowledge_base/xarn-velgor.md):
    Xarn Velgor is a central figure...
[2] ...
```

---

## 4. Техники промптинга

### Chain-of-Thought (CoT)

System-инструкция обязывает модель явно писать `Step 1 / Step 2 / Step 3` перед финальным
ответом. Это снижает галлюцинации: модель вынуждена опираться на чанки, а не домысливать.
Пошаговое рассуждение проверяемо: в логах видно, какой источник был использован.

### Few-shot prompting

Два заранее заданных примера из того же домена (arc-glaive, Aurelian Concord) задают:
- **формат вывода** (Step 1/2/3 + Answer + цитаты `[n]`);
- **стиль** (краткий, фактический, с ссылками);
- **тон** (нейтральный, энциклопедический).

Примеры выбраны из реальных статей KB, что исключает ситуацию «пример противоречит контексту».

### Relevance Guard (порог без LLM)

Если `score` лучшего чанка ≥ `RELEVANCE_THRESHOLD=1.3` (FAISS inner-product на нормализованных
векторах: меньше = ближе), бот отвечает «I don't know» **без вызова LLM**. Порог
откалиброван по данным Task-3: доменные запросы давали score 0.51–1.07, out-of-domain — 1.4+.

---

## 5. Успешные диалоги (5 запросов)

### Q1: Who is Xarn Velgor and what is his origin?

```
Step 1: The question asks about the identity and origin of Xarn Velgor.
Step 2: According to document [1], Xarn Velgor was originally born as Anbar Skyrend,
        a gifted pilot and powerful user of the Synth Flux.
Step 3: He later became the Drakkar Sovereign after being manipulated by Overlord Malkor,
        taking on the name Xarn Velgor.
Answer: Xarn Velgor is a former Veyari Kethan who was born as Anbar Skyrend,
        and he gained his new identity after being manipulated by Overlord Malkor [1].

📚 Sources: [1][2] Xarn Velgor — knowledge_base/xarn-velgor.md
            [3] Oben-Var Renoth — knowledge_base/oben-var-renoth.md
            [4] Pyronis — knowledge_base/pyronis.md
```

---

### Q2: What is the Synth Flux and how do the Veyari use it?

```
Step 1: The question asks about the nature of the Synth Flux and its application by the Veyari.
Step 2: According to [1],[2],[4], the Synth Flux is a mysterious energy field that binds
        the Expanse together, granting practitioners heightened intuition, telekinesis,
        influence over weaker minds, and a deep connection to the living universe.
Step 3: The Veyari utilize it through dedicated study and mastery of its principles.
Answer: The Synth Flux is a mysterious energy field that binds the Expanse together,
        allowing practitioners like the Veyari to tap into its power. Through dedicated
        study and training, they can harness extraordinary abilities [1], [2], and [4].

📚 Sources: [1][2][3] The Synth Flux — knowledge_base/the-synth-flux.md
            [4] Veyari Conclave — knowledge_base/veyari-conclave.md
```

---

### Q3: Describe the Void Core and its purpose.

```
Step 1: The question asks about the description and purpose of the Void Core.
Step 2: The Void Core was a colossal space station and superweapon constructed by the
        Helion Dominion, roughly the size of a small moon.
Step 3: It featured a planet-destroying superlaser capable of channeling enormous energy
        into a single beam powerful enough to obliterate an entire world.
Answer: The Void Core was a colossal space station and superweapon constructed by the
        Helion Dominion, serving as both a mobile battle platform and a symbol of their
        dominance. It featured a planet-destroying superlaser [1].

📚 Sources: [1][2] Void Core — knowledge_base/void-core.md
            [3] Ember Coalition — knowledge_base/ember-coalition.md
            [4] Reson crystal — knowledge_base/reson-crystal.md
```

---

### Q4: What is the role of the Ember Coalition in the Astral Strife?

```
Step 1: The question asks about the role of the Ember Coalition.
Step 2: The Ember Coalition was a coalition of worlds, soldiers, and sympathizers united
        in armed resistance against the Helion Dominion.
Step 3: It sought to overthrow Dominion tyranny and restore the values of the Aurelian Concord.
Answer: The Ember Coalition served as a primary opposition force against the Helion Dominion
        in the Astral Strife, seeking to restore democracy and challenge Dominion rule [1].

📚 Sources: [1] Ember Coalition — knowledge_base/ember-coalition.md
            [2] Glaciax — knowledge_base/glaciax.md
            [3] Helion Dominion — knowledge_base/helion-dominion.md
            [4] Verdara — knowledge_base/verdara.md
```

---

### Q5: What planet served as the capital of the Helion Dominion?

```
Step 1: The question asks about the capital planet of the Helion Dominion.
Step 2: According to [2], Centra Prime became the capital after the Vat Wars and Directive Null.
Step 3: Centra Prime served as the capital of the Helion Dominion.
Answer: Centra Prime served as the capital of the Helion Dominion, a position it held
        following the transformation of the Aurelian Concord [2].

📚 Sources: [1][3] Centra Prime — knowledge_base/centra-prime.md
            [2] Helion Dominion — knowledge_base/helion-dominion.md
            [4] Drakkar — knowledge_base/drakkar.md
```

---

## 6. Диалоги «Я не знаю» (2 запроса)

Оба вопроса вне домена базы знаний — guard срабатывает до вызова LLM:

### Q6: What is the capital of France?
```
I don't know — the knowledge base contains no supporting evidence for this question.
```
*(FAISS score ≥ 1.3; LLM не вызывалась)*

### Q7: Who invented the telephone?
```
I don't know — the knowledge base contains no supporting evidence for this question.
```
*(FAISS score ≥ 1.3; LLM не вызывалась)*

---

## 7. Как запустить

```bash
# 1. Убедиться, что Ollama запущен
ollama list          # должна быть llama3.2:3b
# (если нет) ollama pull llama3.2:3b

# 2. Активировать venv
cd quantum-forge-software
source .venv/bin/activate   # Windows: .venv\Scripts\activate

# 3. Убедиться, что индекс построен
python scripts/build_index.py   # если index/ пустой

# 4. REPL (диалог)
python scripts/rag_bot.py

# 5. Демо-режим (прогон 7 фиксированных запросов)
python scripts/rag_bot.py --demo

# 6. Кастомная модель
OLLAMA_MODEL=qwen2.5:3b python scripts/rag_bot.py
```

---

## 8. Известные ограничения

- **CoT увеличивает токены.** Локальная 3B-модель с полным CoT генерирует ~200–300 токенов
  на ответ; на CPU без GPU-ускорения Ollama — 5–15 сек/запрос.
- **Качество уступает GPT-4.** `llama3.2:3b` может упрощать рассуждения или не замечать
  тонкие детали в чанках. Для production — upgrade до `llama3.1:8b` или облачной LLM с DPA.
- **Guard по порогу — эвристика.** При частичном семантическом совпадении (запрос про
  «французских рыцарей» может попасть чуть выше порога из-за слова «knight» в корпусе).
  Точная калибровка требует аннотированного тест-сета.
- **Prompt injection** — защита базовая (rule «используй только контекст»). Полный
  многоуровневый guard с тестами — Задание 5.
