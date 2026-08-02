# Как загрузить новую базу данных

Инструкция по подготовке и загрузке новой базы знаний в RAG-бот QuantumForge.

> **Что здесь называется «базой данных».** У бота нет привычной СУБД. «База» — это
> **векторный индекс FAISS**, построенный над каталогом markdown-документов
> `knowledge_base/`. При старте бот (`scripts/rag_bot.py`) загружает индекс из каталога
> (по умолчанию `index/`) и отвечает только по нему. «Загрузить новую базу» =
> подготовить документы → пересобрать индекс → указать боту на этот индекс.

---

## TL;DR

```bash
# 1. Активировать окружение (Python 3.11)
source .venv/bin/activate            # Windows: .venv\Scripts\activate

# 2a. Уже есть готовые .md-документы → положить их в knowledge_base/ и всё.
# 2b. Есть исходники + словарь замен → анонимизировать в knowledge_base/:
python scripts/build_knowledge_base.py

# 3. Построить индекс (knowledge_base/ → index/)
python scripts/build_index.py

# 4. Проверить поиск
python scripts/query_index.py "Who uses a reson crystal?"

# 5. Запустить бота на новом индексе
python scripts/rag_bot.py --index index
```

---

## Из чего состоит база

| Каталог / файл          | Роль                                                                 |
|-------------------------|---------------------------------------------------------------------|
| `data/source_sw/*.md`   | Исходные статьи (вход анонимизации). **Опционально.**                |
| `terms_map.json`        | Словарь замен `{оригинал: вымышленное}` для анонимизации.            |
| `knowledge_base/*.md`   | **Готовые документы — вход индексации.** Это и есть контент базы.    |
| `index/`                | **FAISS-индекс** (`index.faiss` + `index.pkl` + `build_report.json`) — то, что грузит бот. |

Полный конвейер: `data/source_sw/` → (анонимизация) → `knowledge_base/` → (индексация) → `index/` → (загрузка) → бот.

Если у вас уже есть готовые к публикации `.md`-документы, шаг анонимизации не нужен —
кладите их сразу в `knowledge_base/` и переходите к построению индекса.

---

## Формат документа `knowledge_base/*.md`

Каждый документ — markdown с YAML-frontmatter. Индексатор читает поля `title`, `category`,
`lang`; при их отсутствии подставляются значения по умолчанию (`title` = имя файла,
`category` = `unknown`, `lang` = `en`), но лучше указывать явно — они попадают в метаданные
чанков и в вывод поиска.

```markdown
---
title: Arc-glaive
category: technology
lang: en
---

# Arc-glaive

An arc-glaive is an energy weapon most closely associated with…
```

- Имя файла — kebab-case ASCII, без пробелов (`arc-glaive.md`).
- Кодировка UTF-8.
- Одна статья = один файл.

---

## Шаг 1. Подготовить документы

### Вариант A — уже есть готовые документы

Просто поместите `.md`-файлы в `knowledge_base/` (в нужном формате, см. выше). Чтобы
собрать базу «с нуля», предварительно очистите каталог от старого содержимого:

```bash
rm knowledge_base/*.md      # Windows PowerShell: Remove-Item knowledge_base\*.md
# затем скопируйте свои документы в knowledge_base/
```

### Вариант B — анонимизировать исходники

Если исходники содержат термины, которые нужно заменить (как в этом проекте:
Star Wars → Astral Strife), заполните `terms_map.json` и запустите:

```bash
python scripts/build_knowledge_base.py
```

Скрипт: `data/source_sw/*.md` + `terms_map.json` → `knowledge_base/*.md`
(замена терминов с сохранением регистра, коррекция артиклей `a/an`, kebab-case имена файлов).

> ⚠️ **Внимание:** `build_knowledge_base.py` **полностью очищает** `knowledge_base/`
> перед записью (удаляет все `*.md`). Не держите там документы, собранные вручную, —
> они будут стёрты. Для ручной базы используйте Вариант A.

После сборки выполняются две самопроверки на утечку исходных терминов (по словарю и по
независимому deny-list). Ненулевой код возврата означает, что в базе остались
незаменённые термины — дополните `terms_map.json` и перезапустите.

---

## Шаг 2. Построить индекс

```bash
python scripts/build_index.py
```

Что происходит: документы из `knowledge_base/` парсятся → нарезаются на чанки
(`chunk_size=1500` символов, `overlap=200`) → кодируются моделью
`sentence-transformers/all-MiniLM-L6-v2` (dim = 384) → сохраняются в FAISS-индекс.

Результат в `index/`:
- `index.faiss` — бинарный индекс векторов;
- `index.pkl` — метаданные чанков (source, title, category, lang, chunk_id);
- `build_report.json` — статистика (модель, число документов/чанков, время сборки).

**Полезные флаги:**

```bash
# Сохранить в другой каталог (не перезаписывая index/)
python scripts/build_index.py --out my_index

# Читать документы из другого каталога, а не из knowledge_base/
python scripts/build_index.py --kb-dir knowledge_base_arch --out index_arch

# Добавить документы из ещё одного каталога (напр. отдельный набор)
python scripts/build_index.py --extra-dir data/malicious --out index_security

# Другая embedding-модель (напр. для не-английской базы, см. раздел ниже)
python scripts/build_index.py --kb-dir knowledge_base_arch --out index_arch \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

`--kb-dir` **заменяет** `knowledge_base/` как основной источник (для полностью отдельной
базы). `--extra-dir`, в отличие от него, **добавляется** к основному каталогу, а не
заменяет его.

---

## Шаг 3. Проверить, что база загрузилась

```bash
python scripts/query_index.py "Who turned to the Umbral Tide?"
python scripts/query_index.py                                    # встроенные демо-запросы
python scripts/query_index.py --index index_arch "запрос"        # поиск в другом индексе
```

Скрипт по умолчанию ищет по `index/` (флаг `--index` меняет каталог) и печатает топ-K
чанков с оценками и провенансом (из какого документа взят фрагмент). Если результаты
релевантны — база подключена корректно.

> Если индекс собирался с флагом `--model` (нестандартная embedding-модель), передайте
> тот же `--model` в `query_index.py` — иначе поиск будет вести неверная модель и
> результаты будут бессмысленными (без ошибки, просто низкое качество).

---

## Шаг 4. Подключить базу к боту

Боту нужен запущенный Ollama с моделью:

```bash
ollama pull llama3.2:3b
```

Запуск на конкретном индексе:

```bash
python scripts/rag_bot.py --index index          # REPL на index/ (по умолчанию)
python scripts/rag_bot.py --index my_index --demo # демо на другой базе
```

Без `--index` бот берёт `index/`. Если по указанному пути нет `index.faiss`, бот
сообщит об ошибке и попросит сначала запустить `build_index.py`.

> Как и `query_index.py`, бот принимает `--model` — передавайте ту же модель, которой
> строился индекс.

---

## База на другом языке (не английском)

`all-MiniLM-L6-v2` (модель по умолчанию) обучена в основном на английском — на русском
и других языках она даёт слабый семантический поиск (низкая релевантность в топ-K даже
для явно подходящих чанков). Для не-английской базы замените модель на мультиязычную:

```bash
python scripts/build_index.py --kb-dir knowledge_base_arch --out index_arch \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2

python scripts/query_index.py --index index_arch \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 "русский запрос"

python scripts/rag_bot.py --index index_arch \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

`paraphrase-multilingual-MiniLM-L12-v2` — drop-in замена: та же размерность (dim = 384),
менять больше ничего не нужно. Для более высокого качества (но другой размерности,
индекс придётся пересобрать) — `intfloat/multilingual-e5-base` (dim 768).

Для самого бота (`rag_bot.py`) также нужна LLM в Ollama, понимающая русский.
`llama3.2:3b` (дефолт скрипта — **не менять**, на нём завязаны логи Задания 5)
отвечает по-русски, но со артефактами: смешивает алфавиты внутри слов
(`पततерн` вместо «паттерн») и без `stop`-последовательности продолжает
генерировать несуществующие вопросы после ответа (см. `stop=["\nQ:", "\n\nQ:"]`
в `ChatOllama(...)`, уже добавлено).

Переключение модели — через переменную окружения `OLLAMA_MODEL`, без правок кода:

```bash
OLLAMA_MODEL=gemma4:latest python scripts/rag_bot.py --index index_arch \
  --model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

**Проверено на реальном железе (16 ГБ RAM, RTX 5060 8 ГБ VRAM):**

| Модель | Требуемая RAM (по ошибке Ollama) | Результат |
|---|---|---|
| `llama3.2:3b` (3B) | — | Стабильно загружается, отвечает по-русски. |
| `gemma4:latest` (8B, мультимодальная) | ~8.1 ГиБ | Работает, полностью на GPU. **Требует Ollama ≥ 0.32.x.** На Ollama 0.24.0 падала с `GGML_ASSERT(ctx->mem_buffer != NULL)` — vision-энкодер (CLIP-подобный) у gemma4 запускается на КАЖДОМ запросе, включая чисто текстовые, и на старых версиях Ollama на Windows это гонка условий/CUDA OOM (известный баг, см. issues [#16147](https://github.com/ollama/ollama/issues/16147), [#16576](https://github.com/ollama/ollama/issues/16576)). После обновления Ollama до 0.32.5 воспроизвести не удалось. |
| `gpt-oss:20b` (MoE, 3.6B активных) | ~8 ГиБ | Работает, полностью на GPU (`use_mmap: true`, без `num_gpu` — см. ниже). |
| `qwen3.6:latest` (36B MoE) | ~19 ГиБ | Не годится на этом железе — не хватит даже при полностью свободной RAM. |

> `num_gpu` с явным числом слоёв ломает MoE-архитектуры (`qwen35moe`, `gpt-oss`) ошибкой
> `memory layout cannot be allocated` — им нужен авто-подбор Ollama (не передавать `num_gpu`
> вообще). `rag_bot.py` уже это учитывает: пробует `num_gpu=999`, при этой ошибке —
> автоматический retry без `num_gpu`.

Пример в этом репозитории: `knowledge_base_arch/` (22 документа по паттернам
проектирования на русском, refactoring.guru/ru — личный конспект с указанием
`source_url` в каждом файле) → `index_arch/`.

---

## Несколько баз одновременно

Индекс полностью определяется своим каталогом, поэтому можно держать несколько баз рядом
и переключаться флагом `--index`:

```bash
python scripts/build_index.py --out index_prod
python scripts/build_index.py --out index_experiment
python scripts/rag_bot.py --index index_prod
python scripts/rag_bot.py --index index_experiment
```

---

## Docker

В Docker индекс **вшивается в образ** на этапе сборки (см. `Dockerfile`: `COPY index/`,
`COPY knowledge_base/`). Поэтому после смены базы нужно **пересобрать образ**:

```bash
# сначала пересобрать index/ локально (Шаг 2), затем:
docker compose build
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.2:3b   # один раз
docker compose run --rm bot                          # прогон демо
```

Если добавили новый каталог индекса (например `index_prod/`), допишите для него строку
`COPY index_prod/ ./index_prod/` в `Dockerfile` и передайте боту `--index index_prod`.

---

## Параметры (где менять)

| Параметр          | Как менять                          | Значение по умолчанию                     | Примечание                                        |
|-------------------|--------------------------------------|--------------------------------------------|---------------------------------------------------|
| Embedding-модель  | флаг `--model` (все 3 скрипта)      | `sentence-transformers/all-MiniLM-L6-v2`  | dim = 384. При смене модели **пересоберите индекс** и передавайте тот же `--model` во все скрипты. |
| Каталог документов | флаг `--kb-dir` (`build_index.py`) | `knowledge_base/`                         | Полная замена источника (не сложение, в отличие от `--extra-dir`). |
| `CHUNK_SIZE`      | константа в `build_index.py`        | `1500` символов (≈ 230 слов)              | Размер чанка.                                     |
| `CHUNK_OVERLAP`   | константа в `build_index.py`        | `200` символов (≈ 13%)                    | Перекрытие для сохранения контекста на границах.  |

> Индекс и бот должны использовать **одну и ту же** embedding-модель. Если поменяли
> модель — старый индекс несовместим по размерности, пересоберите его заново.

Порог релевантности бота задаётся переменной окружения `RELEVANCE_THRESHOLD`
(по умолчанию `1.3`); адрес и имя модели Ollama — `OLLAMA_BASE_URL` и `OLLAMA_MODEL`.

---

## Частые проблемы

| Симптом                                             | Причина / решение                                                        |
|-----------------------------------------------------|--------------------------------------------------------------------------|
| `В knowledge_base нет .md-файлов`                   | Каталог пуст — выполните Шаг 1.                                           |
| `[FAIL] остаточные термины…`                        | Анонимизация неполная — дополните `terms_map.json` и перезапустите Шаг 1B. |
| `Index not found: …/index.faiss`                    | Индекс не построен по этому пути — запустите Шаг 2 (проверьте `--out`).    |
| Бот отвечает «не знаю» на очевидные вопросы         | База не та / индекс не пересобран после смены документов — повторите Шаг 2. |
| `Не хватает зависимостей`                           | `pip install -r requirements.txt` (Python 3.11).                          |
| Изменили документы, но ответы прежние (Docker)      | Индекс вшит в образ — пересоберите: `docker compose build`.               |
| Поиск находит нерелевантные чанки на не-английской базе | `EMBEDDING_MODEL` по умолчанию — английская. Пересоберите с `--model paraphrase-multilingual-MiniLM-L12-v2` (см. «База на другом языке»). |
| После смены `--model` результаты бессмысленные, без ошибки | Индекс и запрос используют разные модели — передайте одинаковый `--model` в `build_index.py` **и** `query_index.py`/`rag_bot.py`. |
| `model requires more system memory (X GiB) than is available (Y GiB)` | Для LLM (не embedding) не хватает RAM/VRAM. Закройте фоновые приложения или возьмите модель поменьше (`OLLAMA_MODEL=llama3.2:3b`) — `OLLAMA_CONTEXT_LENGTH` требование почти не снижает, оно определяется весами модели. |
| Бот отвечает не на заданный вопрос, а на несколько придуманных им же | Нет `stop`-последовательности — модель копирует формат few-shot и генерирует новые "Q: ... A: ..." пары. Исправлено в коде (`stop=["\nQ:", "\n\nQ:"]` в `ChatOllama`). |
