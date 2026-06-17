#!/usr/bin/env python3
"""
rag_bot.py — RAG-бот с Few-shot и Chain-of-Thought промптингом.

Пайплайн (явные шаги, без магии RetrievalQA):
  1. Загрузить FAISS-индекс и embedding-модель (all-MiniLM-L6-v2).
  2. Embed запроса → поиск топ-K чанков в FAISS.
  3. Guard: нет релевантных чанков → ответ «Я не знаю» без вызова LLM.
  4. Compose prompt: System (роль + CoT) + Few-shot примеры + Context + User.
  5. Вызов локальной LLM через Ollama (localhost:11434).
  6. Печать ответа + источников.

Интерфейс:
  python scripts/rag_bot.py             # REPL (диалоговый режим)
  python scripts/rag_bot.py --demo      # прогон встроенных демо-запросов без ввода

Переменные окружения:
  OLLAMA_MODEL   — имя модели (default: llama3.2:3b)
  OLLAMA_BASE_URL — адрес сервера (default: http://localhost:11434)
  RELEVANCE_THRESHOLD — порог релевантности FAISS (default: 1.3)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "index"

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
TOP_K = 4
# FAISS inner-product на нормализованных векторах: меньший score = ближе.
# Порог 1.3 откалиброван по данным Task-3: доменные запросы давали score 0.5–1.1,
# out-of-domain — 1.3+.
RELEVANCE_THRESHOLD = float(os.getenv("RELEVANCE_THRESHOLD", "1.3"))

# ---------------------------------------------------------------------------
# Промпт: System (CoT) + Few-shot примеры
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """\
You are an expert assistant for the Astral Strife knowledge base.
Your job is to answer questions using ONLY the information provided in the context below.

Rules:
1. Think step by step before answering (Chain-of-Thought):
   Step 1: Identify what the question is asking.
   Step 2: Find relevant facts in the provided context documents.
   Step 3: Synthesise the facts into a clear answer.
   Step 4: Cite the sources as [1], [2], etc. that correspond to the numbered documents.
2. If the context does not contain enough information to answer, reply EXACTLY:
   "I don't know — the knowledge base contains no supporting evidence for this question."
3. Never use knowledge outside the provided context.
4. Keep the answer concise (2–5 sentences) after the reasoning steps.
"""

# Few-shot примеры — grounded в реальных фактах из knowledge_base/
FEW_SHOT_EXAMPLES = """
--- Examples (follow this format) ---

Q: What is the power source of the arc-glaive?
A:
Step 1: The question asks about the energy source of the arc-glaive weapon.
Step 2: According to document context, a reson crystal is placed at the heart of every arc-glaive and focuses the Synth Flux energy into a blade.
Step 3: The arc-glaive is powered by a reson crystal.
Answer: The arc-glaive is powered by a reson crystal, a rare Synth Flux-attuned mineral that focuses energy into a coherent blade [1].

Q: What happened to the Aurelian Concord?
A:
Step 1: The question asks about the fate of the Aurelian Concord.
Step 2: The context states that Overlord Malkor transformed the Synod-led Concord into the Helion Dominion after the Vat Wars.
Step 3: The Aurelian Concord collapsed and was replaced by the Helion Dominion.
Answer: The Aurelian Concord collapsed following the Vat Wars and Directive Null; Overlord Malkor transformed it into the authoritarian Helion Dominion [1].

--- End of examples ---
"""


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def build_context_block(docs_with_scores: list) -> tuple[str, list[dict]]:
    """Сформировать нумерованный контекст из чанков и список источников."""
    context_lines: list[str] = []
    sources: list[dict] = []
    for i, (doc, _score) in enumerate(docs_with_scores, start=1):
        meta = doc.metadata
        context_lines.append(
            f"[{i}] {meta.get('title', '?')} (source: {meta.get('source', '?')}):\n"
            f"{doc.page_content.strip()}"
        )
        sources.append({"num": i, "title": meta.get("title", "?"), "source": meta.get("source", "?")})
    return "\n\n".join(context_lines), sources


def compose_prompt(query: str, context_block: str) -> list[dict]:
    """Собрать список сообщений (OpenAI/Ollama chat format)."""
    user_message = (
        f"{FEW_SHOT_EXAMPLES}\n"
        f"--- Context ---\n{context_block}\n--- End context ---\n\n"
        f"Q: {query}\nA:"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]


def print_separator(title: str = "") -> None:
    line = "═" * 64
    if title:
        print(f"\n{line}\n  {title}\n{line}")
    else:
        print(line)


def print_answer(query: str, answer: str, sources: list[dict]) -> None:
    print_separator(f"Q: {query}")
    print(f"\n{answer.strip()}")
    if sources:
        print("\n📚 Sources:")
        for s in sources:
            print(f"  [{s['num']}] {s['title']} — {s['source']}")
    print()


# ---------------------------------------------------------------------------
# Основная RAG-цепочка
# ---------------------------------------------------------------------------


def ask(query: str, vectorstore, llm) -> None:
    """Выполнить один RAG-запрос: retrieve → guard → prompt → generate → print."""

    # Шаг 2: Поиск
    results = vectorstore.similarity_search_with_score(query, k=TOP_K)

    # Шаг 3: Guard — нет результатов или все нерелевантны
    if not results or results[0][1] >= RELEVANCE_THRESHOLD:
        print_separator(f"Q: {query}")
        print(
            "\nI don't know — the knowledge base contains no supporting evidence "
            "for this question.\n"
        )
        return

    # Шаг 4: Формирование промпта
    context_block, sources = build_context_block(results)
    messages = compose_prompt(query, context_block)

    # Шаг 5: Вызов LLM
    from langchain_core.messages import HumanMessage, SystemMessage

    lc_messages = []
    for m in messages:
        if m["role"] == "system":
            lc_messages.append(SystemMessage(content=m["content"]))
        else:
            lc_messages.append(HumanMessage(content=m["content"]))

    response = llm.invoke(lc_messages)
    answer = response.content if hasattr(response, "content") else str(response)

    # Шаг 6: Вывод
    print_answer(query, answer, sources)


# ---------------------------------------------------------------------------
# Демо-запросы
# ---------------------------------------------------------------------------

DEMO_QUERIES_IN_DOMAIN = [
    "Who is Xarn Velgor and what is his origin?",
    "What is the Synth Flux and how do the Veyari use it?",
    "Describe the Void Core and its purpose.",
    "What is the role of the Ember Coalition in the Astral Strife?",
    "What planet served as the capital of the Helion Dominion?",
]

DEMO_QUERIES_OUT_OF_DOMAIN = [
    "What is the capital of France?",
    "Who invented the telephone?",
]


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
        from langchain_ollama import ChatOllama
    except ImportError as exc:
        print(
            f"[ERROR] Missing dependency: {exc}\n"
            "Run: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    # Проверка индекса
    if not (INDEX_DIR / "index.faiss").exists():
        print(
            f"[ERROR] Index not found: {INDEX_DIR}/index.faiss\n"
            "Run: python scripts/build_index.py",
            file=sys.stderr,
        )
        return 1

    # Загрузка embeddings и индекса
    print(f"[INFO] Loading embedding model: {EMBEDDING_MODEL}")
    embeddings = HuggingFaceEmbeddings(
        model_name=EMBEDDING_MODEL,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"[INFO] Loading FAISS index: {INDEX_DIR}")
    vectorstore = FAISS.load_local(
        str(INDEX_DIR),
        embeddings,
        allow_dangerous_deserialization=True,
    )

    # Инициализация LLM (Ollama)
    print(f"[INFO] Connecting to Ollama: {OLLAMA_BASE_URL}, model={OLLAMA_MODEL}")
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
        temperature=0,
    )

    demo_mode = "--demo" in sys.argv

    if demo_mode:
        # --- Демо-режим: прогон фиксированных запросов ---
        print("\n" + "═" * 64)
        print("  DEMO MODE — Astral Strife Knowledge Base RAG Bot")
        print("═" * 64)
        print(f"  Model: {OLLAMA_MODEL} | Threshold: {RELEVANCE_THRESHOLD}")
        print(f"  In-domain queries: {len(DEMO_QUERIES_IN_DOMAIN)}")
        print(f"  Out-of-domain queries: {len(DEMO_QUERIES_OUT_OF_DOMAIN)}")
        print("═" * 64 + "\n")

        print("── IN-DOMAIN QUERIES (bot should answer) ──\n")
        for q in DEMO_QUERIES_IN_DOMAIN:
            ask(q, vectorstore, llm)

        print("\n── OUT-OF-DOMAIN QUERIES (bot should say 'I don't know') ──\n")
        for q in DEMO_QUERIES_OUT_OF_DOMAIN:
            ask(q, vectorstore, llm)

        print("[OK] Demo complete.")
        return 0

    # --- REPL ---
    print("\n" + "═" * 64)
    print("  Astral Strife Knowledge Base RAG Bot")
    print(f"  Model: {OLLAMA_MODEL} | Type /exit to quit | /help for hints")
    print("═" * 64 + "\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n[Goodbye]")
            break

        if not query:
            continue
        if query.lower() in ("/exit", "/quit", "exit", "quit"):
            print("[Goodbye]")
            break
        if query.lower() == "/help":
            print("Ask any question about the Astral Strife universe.")
            print("Commands: /exit — quit, /help — this message\n")
            continue

        ask(query, vectorstore, llm)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
