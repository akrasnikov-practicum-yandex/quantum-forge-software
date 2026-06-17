#!/usr/bin/env python3
"""
query_index.py — поиск по FAISS-индексу базы знаний Astral Strife.

Использование:
    python scripts/query_index.py              # прогон встроенных демо-запросов
    python scripts/query_index.py "запрос"     # один произвольный запрос

Требует предварительного запуска build_index.py (index/index.faiss + index/index.pkl).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "index"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
TOP_K = 4  # число возвращаемых чанков

# Демо-запросы для встроенного теста качества поиска
DEMO_QUERIES = [
    "Who turned to the Umbral Tide and became a Drakkar Sovereign?",
    "What weapon uses a reson crystal as its power source?",
    "Which faction fought against the Helion Dominion?",
]


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def print_separator(title: str = "") -> None:
    line = "─" * 60
    if title:
        print(f"\n{line}")
        print(f"  {title}")
        print(line)
    else:
        print(line)


def show_results(query: str, results: list) -> None:
    """Вывести результаты поиска в читаемом формате."""
    print_separator(f'🔍 Query: "{query}"')
    if not results:
        print("  Ничего не найдено.")
        return

    for rank, (doc, score) in enumerate(results, start=1):
        meta = doc.metadata
        snippet = doc.page_content[:300].replace("\n", " ")
        if len(doc.page_content) > 300:
            snippet += "…"
        print(
            f"\n  [{rank}] score={score:.4f} | {meta.get('title', '?')} "
            f"(chunk {meta.get('chunk_index', '?')}) | {meta.get('source', '?')}"
        )
        print(f"      {snippet}")


# ---------------------------------------------------------------------------
# Основной пайплайн
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
    except ImportError as exc:
        print(
            f"[ERROR] Не хватает зависимостей: {exc}\n"
            "Установите: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    # Проверка наличия индекса
    if not (INDEX_DIR / "index.faiss").exists():
        print(
            f"[ERROR] Индекс не найден: {INDEX_DIR}/index.faiss\n"
            "Сначала запустите: python scripts/build_index.py",
            file=sys.stderr,
        )
        return 1

    # Загрузка embedding-модели и индекса
    print(f"[INFO] Загружаю модель: {EMBEDDING_MODEL}")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"[INFO] Загружаю индекс: {INDEX_DIR}")
    vectorstore = FAISS.load_local(
        str(INDEX_DIR),
        embeddings,
        allow_dangerous_deserialization=True,
    )
    print("[OK] Индекс загружен. Начинаю поиск.\n")

    # Определяем список запросов: из CLI или демо
    queries: list[str] = []
    if len(sys.argv) > 1:
        queries = [" ".join(sys.argv[1:])]
    else:
        print("Режим: встроенные демо-запросы")
        queries = DEMO_QUERIES

    # Поиск
    for query in queries:
        results = vectorstore.similarity_search_with_score(query, k=TOP_K)
        show_results(query, results)

    print_separator()
    print(f"[OK] Поиск завершён. Запросов: {len(queries)}, топ-K={TOP_K}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
