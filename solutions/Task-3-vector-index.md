# Задание 3. Создание векторного индекса базы знаний

**Проект:** RAG-бот для корпоративной базы знаний QuantumForge Software
**Дата:** 2026-06-17

---

## 1. Выбор embedding-модели

| Параметр | Значение |
|---|---|
| **Модель** | `sentence-transformers/all-MiniLM-L6-v2` |
| **Репозиторий** | https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2 |
| **Размер эмбеддинга** | 384 |
| **Тип** | Локальная (Sentence-Transformers) |

Модель выбрана в Задании 1: компактная (~22 МБ), быстрая (CPU-inference), хорошее качество на
английском, данные не покидают инфраструктуру. Корпус базы знаний — английский, поэтому
`all-MiniLM-L6-v2` оптимальна. Эмбеддинги нормализованы (`normalize_embeddings=True`),
что позволяет использовать `IndexFlatIP` (inner product) как косинусное сходство.

---

## 2. База знаний

| Параметр | Значение |
|---|---|
| **Источник** | `knowledge_base/` (результат Задания 2) |
| **Документов** | 36 `.md`-файлов |
| **Язык** | English |
| **Вселенная** | Astral Strife (анонимизированный Star Wars) |
| **Контент** | Персонажи, планеты, фракции, технологии, концепции и события |

Каждый документ имеет YAML-frontmatter (`title`, `category`, `lang`) и тело-статью.
Скрипт `build_index.py` парсит frontmatter и индексирует только тело.

---

## 3. Параметры чанкинга

| Параметр | Значение | Обоснование |
|---|---|---|
| **Splitter** | `RecursiveCharacterTextSplitter` | Рекурсивное разбиение по `\n\n → \n → пробел` сохраняет логические границы |
| **`chunk_size`** | 800 символов | ≈200 слов — укладывается в лимит 100–300 слов из ТЗ |
| **`chunk_overlap`** | 120 символов | ~15% — сохраняет контекст на границах чанков (рекомендация из курса: 10–20%) |

Документы «Astral Strife» сравнительно короткие (400–1 500 символов), поэтому большинство
статей даёт 1–3 чанка. Overlap предотвращает потерю смысла на границе: если ответ начинается
в конце одного чанка, он «виден» и в начале следующего.

### Метаданные чанка

На каждый чанк сохраняется:

| Поле | Пример | Назначение |
|---|---|---|
| `source` | `knowledge_base/xarn-velgor.md` | Ссылка на источник для цитирования |
| `title` | `Xarn Velgor` | Заголовок документа |
| `category` | `character` | Тематическая фильтрация |
| `lang` | `en` | Языковая фильтрация |
| `chunk_index` | `0` | Порядок в документе |
| `chunk_id` | `xarn-velgor-0` | Уникальный идентификатор чанка |

---

## 4. Статистика прогона

| Параметр | Значение |
|---|---|
| **Документов** | 36 |
| **Чанков в индексе** | 91 |
| **Размерность векторов** | 384 |
| **Время генерации** | **0.80 с** |
| **Размер `index.faiss`** | 137 KB |
| **Размер `index.pkl`** | 58 KB |
| **Окружение** | CPU (x86-64), Python 3.14, faiss-cpu |

Полный отчёт прогона: [`index/build_report.json`](../index/build_report.json)

---

## 5. Пример запросов и найденных чанков

Тест качества — 3 запроса по лору «Astral Strife» (запуск: `python scripts/query_index.py`):

### Запрос 1: Who turned to the Umbral Tide and became a Drakkar Sovereign?

```
[1] score=0.6941 | Drakkar (chunk 1) | knowledge_base/drakkar.md
    For much of their later history, the Drakkar maintained a strict structure of only
    two members at a time: a master and an apprentice...

[2] score=0.7146 | Drakkar (chunk 0) | knowledge_base/drakkar.md
    The Drakkar were an ancient order of Synth Flux-wielders who embraced the Umbral Tide
    and stood as the great rivals of the Veyari...
```

**Оценка:** топ-2 релевантны — возвращает статьи про Drakkar (орден, принявший Umbral Tide).
Ответ на вопрос о конкретном персонаже (Xarn Velgor) нашёлся бы при более конкретном запросе
«Who is Xarn Velgor?».

---

### Запрос 2: What weapon uses a reson crystal as its power source?

```
[1] score=0.5151 | Reson crystal (chunk 0) | knowledge_base/reson-crystal.md
    A reson crystal is a rare, Synth Flux-attuned mineral that serves as the power source
    at the heart of an arc-glaive...

[2] score=0.7351 | Reson crystal (chunk 2) | knowledge_base/reson-crystal.md
    Beyond their use in personal weapons, reson crystals possess immense raw energy when
    gathered in large quantities. The Helion Dominion harvested vast amounts of reson to
    power the superlaser of the Void Core...

[4] score=1.0709 | Arc-glaive (chunk 1) | knowledge_base/arc-glaive.md
    At the heart of every arc-glaive lies a reson crystal, which focuses the energy that
    forms the blade...
```

**Оценка:** отличная релевантность — первый же чанк содержит прямой ответ. Score < 1.0
у первых двух результатов означает высокое семантическое сходство (нормализованный IP = cosine).

---

### Запрос 3: Which faction fought against the Helion Dominion?

```
[1] score=0.6597 | Helion Dominion (chunk 0) | knowledge_base/helion-dominion.md
    The Helion Dominion was an authoritarian regime that ruled much of the Expanse following
    the collapse of the Aurelian Concord...

[2] score=0.8847 | Drakkar (chunk 2) | knowledge_base/drakkar.md
    The Drakkar pursued a long campaign to undermine the Veyari Conclave and the Aurelian
    Concord. Through patience, deception, and political intrigue, they engineered the rise
    of the Helion Dominion...
```

**Оценка:** контекстно релевантно. Прямая статья про Ember Coalition появилась бы в
расширенном топ-K. Для production RAG здесь помогла бы метафильтрация по `category=faction`.

---

## 6. Как запустить

```bash
# 1. Клонировать репозиторий и перейти в ветку rag
git clone https://github.com/akrasnikov-practicum-yandex/quantum-forge-software.git
cd quantum-forge-software
git checkout rag

# 2. Создать окружение и установить зависимости
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. (Опционально) Пересобрать базу знаний из исходников
python scripts/build_knowledge_base.py

# 4. Построить FAISS-индекс
python scripts/build_index.py
# → index/index.faiss, index/index.pkl, index/build_report.json

# 5. Поиск: демо-запросы
python scripts/query_index.py

# 6. Поиск: произвольный запрос
python scripts/query_index.py "Who is Voda and what is his role?"
```

---

## 7. Архитектура пайплайна

```
knowledge_base/*.md
        │
        ▼
parse_frontmatter()        — извлечение title/category/lang, отделение тела
        │
        ▼
RecursiveCharacterTextSplitter  — chunk_size=800, overlap=120
        │  91 чанков с метаданными (source, title, category, lang, chunk_index, chunk_id)
        ▼
HuggingFaceEmbeddings          — all-MiniLM-L6-v2, dim=384, normalize=True
        │
        ▼
FAISS.from_documents()         — IndexFlatIP (cosine через inner product)
        │
        ▼
vectorstore.save_local("index/")
  ├── index/index.faiss   (137 KB)
  ├── index/index.pkl     (58 KB)
  └── index/build_report.json
```

---

## 8. Известные ограничения

- **Нет нативной фильтрации по метаданным в FAISS.** При необходимости фильтровать по
  `category` или `lang` нужна постфильтрация: достать topK×N чанков, отфильтровать по
  метаданным, вернуть topK. Для production с метафильтрацией → миграция на Qdrant
  (как запланировано в Задании 1).
- **Персистентность — ручная.** `index.faiss` и `index.pkl` требуют синхронизации при
  обновлении базы знаний. Решение — пересборка при изменении `knowledge_base/`.
- **Score у FAISS — не вероятность.** Меньший score означает большее сходство
  (расстояние); интерпретировать нужно относительно, не абсолютно.
