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

Модель выбрана в Задании 1: компактная (~90 МБ), быстрая (CPU-inference), хорошее качество на
английском, данные не покидают инфраструктуру. Корпус базы знаний — английский, поэтому
`all-MiniLM-L6-v2` оптимальна. Эмбеддинги нормализованы (`normalize_embeddings=True`),
поэтому L2-расстояние индекса монотонно эквивалентно косинусному сходству
(меньший score = ближе).

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
| **`chunk_size`** | 1500 символов | ≈230 слов (при ~6.4 симв/слово) — в диапазоне 100–300 слов из ТЗ |
| **`chunk_overlap`** | 200 символов | ~13% — сохраняет контекст на границах чанков (курс: 10–20%) |

Документы «Astral Strife» — короткие энциклопедические статьи (171–215 слов каждая), поэтому
при `chunk_size=1500` каждая статья укладывается в один связный чанк (36 документов → 36 чанков),
и **все чанки попадают в требуемый диапазон 100–300 слов**. Overlap предотвращает потерю смысла
на границе, если статья окажется длиннее и будет разбита на несколько чанков.

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
| **Чанков в индексе** | 36 (каждый 171–215 слов) |
| **Размерность векторов** | 384 |
| **Время генерации** | **0.85 с** |
| **Размер `index.faiss`** | 54 KB |
| **Размер `index.pkl`** | 50 KB |
| **Окружение** | CPU (x86-64), Python 3.13, faiss-cpu |

Полный отчёт прогона: [`index/build_report.json`](../index/build_report.json)

---

## 5. Пример запросов и найденных чанков

Тест качества — 3 запроса по лору «Astral Strife» (запуск: `python scripts/query_index.py`).
Score — L2-расстояние на нормализованных векторах (меньше = ближе, эквивалент косинуса):

### Запрос 1: Who turned to the Umbral Tide and became a Drakkar Sovereign?

```
[1] score=0.7567 | Drakkar (chunk 0)     | knowledge_base/drakkar.md
[2] score=0.9837 | Malkor (chunk 0)      | knowledge_base/malkor.md
[4] score=1.0263 | Xarn Velgor (chunk 0) | knowledge_base/xarn-velgor.md
```

**Оценка:** релевантно — орден Drakkar, его лидер Malkor (Drakh Umbra) и конкретный
Drakkar Sovereign (Xarn Velgor, обратившийся к Umbral Tide) попадают в топ результатов.

---

### Запрос 2: What weapon uses a reson crystal as its power source?

```
[1] score=0.5697 | Reson crystal (chunk 0) | knowledge_base/reson-crystal.md
    A reson crystal … serves as the power source at the heart of an arc-glaive…
[2] score=1.0418 | Arc-glaive (chunk 0)     | knowledge_base/arc-glaive.md
    An arc-glaive is an energy weapon … blade of pure plasma…
```

**Оценка:** отличная релевантность — первый чанк (reson-crystal, score 0.57) содержит прямой
ответ; следом arc-glaive. Малый score = высокое сходство (L2 на нормализованных векторах ≈ cosine).

---

### Запрос 3: Which faction fought against the Helion Dominion?

```
[1] score=0.6697 | Helion Dominion (chunk 0)  | knowledge_base/helion-dominion.md
[2] score=1.0899 | Vat Wars (chunk 0)         | knowledge_base/vat-wars.md
[3] score=1.0930 | Aurelian Concord (chunk 0) | knowledge_base/aurelian-concord.md
```

**Оценка:** контекстно релевантно (Helion Dominion, Vat Wars, Aurelian Concord). Прямая статья
про Ember Coalition появилась бы в расширенном топ-K или при метафильтрации `category=faction`.

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
RecursiveCharacterTextSplitter  — chunk_size=1500, overlap=200
        │  36 чанков с метаданными (source, title, category, lang, chunk_index, chunk_id)
        ▼
HuggingFaceEmbeddings          — all-MiniLM-L6-v2, dim=384, normalize=True
        │
        ▼
FAISS.from_documents()         — IndexFlatL2 (нормализация → L2 ≈ cosine)
        │
        ▼
vectorstore.save_local("index/")
  ├── index/index.faiss   (54 KB)
  ├── index/index.pkl     (50 KB)
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
