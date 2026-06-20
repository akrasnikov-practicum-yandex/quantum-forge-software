# QuantumForge RAG-бот (спринт 7)

RAG-бот по корпоративной базе знаний на анонимизированном корпусе (вселенная **Astral Strife**,
полученная переименованием Star Wars). Полностью локальный стек: эмбеддинги
`all-MiniLM-L6-v2`, индекс FAISS, LLM через Ollama — данные не покидают периметр (требование SOC 2).

## Структура

```
knowledge_base/      36 анонимизированных .md-документов (база знаний)
terms_map.json       словарь замен Star Wars → Astral Strife
data/source_sw/      исходные статьи (вход скрипта анонимизации)
data/malicious/      prompt-injection документ для Задания 5
index/               FAISS-индекс базы знаний (.faiss + .pkl + build_report.json)
index_security/      FAISS-индекс с добавленным malicious-документом
scripts/
  build_knowledge_base.py   анонимизация (замена терминов + 2 самопроверки)
  build_index.py            чанкинг + эмбеддинги + FAISS-индекс
  query_index.py            поиск по индексу (--index для index_security)
  rag_bot.py                RAG-бот: few-shot + CoT + 3 слоя защиты, REPL/--demo
  security.py               детектор и санитайзер prompt-injection
  security_demo.py          демонстрация INSECURE vs SECURE + батарея 10 тестов
solutions/           отчёты по заданиям 1–5
  logs/              реальные логи прогона Задания 5 (security_demo + rag_bot --demo)
Project_template.md  сводные ответы по всем заданиям
```

## Запуск локально

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/build_knowledge_base.py                # (опц.) пересобрать базу
python scripts/build_index.py                         # построить FAISS-индекс
python scripts/build_index.py --extra-dir data/malicious --out index_security  # индекс для Задания 5
python scripts/query_index.py "Who is Voda?"          # поиск по индексу

# Бот (нужен запущенный Ollama с моделью llama3.2:3b)
ollama pull llama3.2:3b
python scripts/rag_bot.py            # REPL
python scripts/rag_bot.py --demo     # демо-запросы
python scripts/security_demo.py      # демонстрация защиты от prompt-injection
```

## Запуск в Docker

```bash
docker compose build
docker compose up -d ollama
docker compose exec ollama ollama pull llama3.2:3b
docker compose run --rm bot          # прогон демо
```

## Задания

| # | Тема | Отчёт |
|---|---|---|
| 1 | Исследование моделей и инфраструктуры | [solutions/Task-1-research.md](solutions/Task-1-research.md) |
| 2 | Подготовка базы знаний | [solutions/Task-2-knowledge-base.md](solutions/Task-2-knowledge-base.md) |
| 3 | Векторный индекс | [solutions/Task-3-vector-index.md](solutions/Task-3-vector-index.md) |
| 4 | RAG-бот (few-shot, CoT) | [solutions/Task-4-rag-bot.md](solutions/Task-4-rag-bot.md) |
| 5 | Безопасность и демонстрация | [solutions/Task-5-security.md](solutions/Task-5-security.md) |

Сводные ответы — [Project_template.md](Project_template.md).
