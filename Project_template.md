# Проектная работа 7 спринта — RAG-бот QuantumForge Software

Сводные ответы по заданиям. Подробные отчёты — в каталоге [`solutions/`](solutions/).

---

## Задание 1. Исследование моделей и инфраструктуры

Сравнены LLM (локальные HuggingFace vs облачные OpenAI/YandexGPT), модели эмбеддингов
(Sentence-Transformers vs OpenAI), векторные БД (FAISS vs ChromaDB vs Qdrant), конфигурации
сервера. Представлены 4 варианта инфраструктуры (A–D) с обоснованием.

**Выбор:** векторная БД — **FAISS** (прототип) → Qdrant (production); эмбеддинги —
`all-MiniLM-L6-v2`; «красная нить» — конфиденциальность/SOC 2 (данные не покидают периметр).
LLM прототипа фактически реализована **локально (Ollama llama3.2:3b)** — это усиливает
конфиденциальность относительно облачного GPT-4o-mini.

→ [solutions/Task-1-research.md](solutions/Task-1-research.md)

## Задание 2. Подготовка базы знаний

Взята вселенная **Star Wars**, переименована в самостоятельную **Astral Strife** скриптом
[`build_knowledge_base.py`](scripts/build_knowledge_base.py) по словарю
[`terms_map.json`](terms_map.json) (132 записи). Результат — **36** анонимизированных
`.md`-документов в [`knowledge_base/`](knowledge_base/) (один файл = одна сущность).
Две самопроверки (словарная + независимый deny-list) подтверждают **0 остаточных** SW-терминов.

→ [solutions/Task-2-knowledge-base.md](solutions/Task-2-knowledge-base.md)

## Задание 3. Векторный индекс

[`build_index.py`](scripts/build_index.py): чанкинг `RecursiveCharacterTextSplitter`
(chunk_size=1500 символов ≈ 230 слов, overlap=200) — все чанки в диапазоне **100–300 слов**;
эмбеддинги `all-MiniLM-L6-v2` (dim=384, нормализованы); индекс **FAISS** (L2 ≈ cosine).
Метаданные чанка: `source`, `title`, `category`, `lang`, `chunk_index`, `chunk_id`.
Результат: **36 документов → 36 чанков**, отчёт в [`index/build_report.json`](index/build_report.json).

→ [solutions/Task-3-vector-index.md](solutions/Task-3-vector-index.md)

## Задание 4. RAG-бот с few-shot и CoT

[`rag_bot.py`](scripts/rag_bot.py): query → embed (тот же энкодер) → поиск FAISS → промпт
(System с CoT + 2 few-shot примера, основанных на реальных фактах базы) → LLM (Ollama) → ответ.
«Я не знаю» — через порог релевантности (до вызова LLM). Интерфейс — REPL + `--demo`.
5 успешных диалогов + случаи честного отказа.

→ [solutions/Task-4-rag-bot.md](solutions/Task-4-rag-bot.md)

## Задание 5. Безопасность и демонстрация

Вредоносный документ [`data/malicious/leaked-credentials.md`](data/malicious/leaked-credentials.md)
проиндексирован в [`index_security/`](index_security/) (37 док / 37 чанков). Три слоя защиты
([`security.py`](scripts/security.py)): pre-prompt, post-проверка (`is_malicious` отбрасывает
вредоносные чанки ДО релевантного guard'а), sanitize (на копии чанка). Демонстрация INSECURE
(утечка) vs SECURE (блок) — [`security_demo.py`](scripts/security_demo.py), батарея 10 тестов
(5 ответов + 5 отказов/фильтр). Реальные захваченные логи прогона —
[`solutions/logs/`](solutions/logs/).

→ [solutions/Task-5-security.md](solutions/Task-5-security.md)

---

## Как запустить

См. [README.md](README.md). Кратко: `pip install -r requirements.txt` →
`python scripts/build_index.py` → `python scripts/rag_bot.py` (нужен Ollama `llama3.2:3b`).
Docker: `docker compose build && docker compose run --rm bot`.

## Сдача

- Решение целиком в ветке `rag` (правки по ревью влиты).
- Репозиторий **публичный**; открыт **PR `rag` → `develop`** в своём репозитории.
  Ветка `main` не используется: у неё с `rag` нет общего предка, поэтому PR в `main` не создаётся.