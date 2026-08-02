#!/usr/bin/env python3
"""
rag_bot.py — RAG-бот с Few-shot и Chain-of-Thought промптингом.

Пайплайн (явные шаги, без магии RetrievalQA):
  1. Загрузить FAISS-индекс и embedding-модель (all-MiniLM-L6-v2).
  2. Embed запроса → поиск топ-K чанков в FAISS.
  3. (defense) Слой 2: отбросить вредоносные чанки; затем Guard: нет релевантных → «Я не знаю».
  4. (defense) Слой 3: sanitize оставшихся чанков (на копии). Compose prompt:
     System (роль + CoT) + Few-shot примеры + Context + User.
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

# На Windows-консоли (cp1251) emoji/box-символы в print иначе падают с UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
INDEX_DIR = ROOT / "index"

# Подключаем модуль безопасности (может быть None если импорт недоступен)
try:
    sys.path.insert(0, str(ROOT / "scripts"))
    from security import is_malicious, sanitize, SECURITY_RULES as _SECURITY_RULES
    _SECURITY_AVAILABLE = True
except ImportError:
    _SECURITY_AVAILABLE = False
    _SECURITY_RULES = ""

# ---------------------------------------------------------------------------
# Конфигурация
# ---------------------------------------------------------------------------

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
TOP_K = 4
# FAISS строит L2-индекс; на нормализованных векторах L2-расстояние монотонно
# эквивалентно косинусу (меньший score = ближе, не inner product).
# Порог — ЭВРИСТИКА: наблюдаемые in-domain score в Task-3 были 0.5–1.1, поэтому 1.3
# взят как консервативная отсечка. Полноценную калибровку по реальным out-of-domain
# запросам нужно измерять отдельно (см. solutions/REVIEW-sprint7.md).
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


def compose_prompt(query: str, context_block: str, defense: bool = True) -> list[dict]:
    """Собрать список сообщений (OpenAI/Ollama chat format).

    При defense=True добавляет SECURITY_RULES в system-промпт (слой 1: pre-prompt).
    """
    system = SYSTEM_PROMPT
    if defense and _SECURITY_AVAILABLE:
        system = SYSTEM_PROMPT + _SECURITY_RULES

    user_message = (
        f"{FEW_SHOT_EXAMPLES}\n"
        f"--- Context ---\n{context_block}\n--- End context ---\n\n"
        f"Q: {query}\nA:"
    )
    return [
        {"role": "system", "content": system},
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


def ask(query: str, vectorstore, llm, defense: bool = True) -> None:
    """Выполнить один RAG-запрос: retrieve → guard → (defense) → prompt → generate → print.

    defense=True (default): применять все 3 слоя защиты от prompt injection.
    defense=False: режим INSECURE для демонстрации уязвимости.
    """

    # Шаг 2: Поиск
    results = vectorstore.similarity_search_with_score(query, k=TOP_K)

    # Слой 2 (defense): Post-check — отбросить вредоносные чанки ДО решения о релевантности,
    # чтобы инъекция не попала в промпт, даже если её score прошёл бы порог.
    if defense and _SECURITY_AVAILABLE and results:
        clean_results = [(doc, sc) for doc, sc in results if not is_malicious(doc.page_content)]
        filtered_count = len(results) - len(clean_results)
        if filtered_count:
            print(f"  [SECURITY] Отфильтровано вредоносных чанков: {filtered_count}")
        results = clean_results

    # Шаг 3: Guard — нет (безопасных) результатов или лучший нерелевантен → «Я не знаю»
    if not results or results[0][1] >= RELEVANCE_THRESHOLD:
        print_separator(f"Q: {query}")
        print(
            "\nI don't know — the knowledge base contains no supporting evidence "
            "for this question.\n"
        )
        return

    # Слой 3 (defense): Sanitize — вырезать управляющие конструкции из ОСТАВШИХСЯ чанков.
    # Работаем на КОПИИ Document, чтобы НЕ мутировать общий docstore FAISS: объекты
    # возвращаются по ссылке и переиспользуются между запросами (in-place правка их портит).
    if defense and _SECURITY_AVAILABLE:
        from langchain_core.documents import Document
        results = [
            (Document(page_content=sanitize(doc.page_content), metadata=dict(doc.metadata)), sc)
            for doc, sc in results
        ]

    # Шаг 4: Формирование промпта
    context_block, sources = build_context_block(results)
    messages = compose_prompt(query, context_block, defense=defense)

    # Шаг 5: Вызов LLM
    from langchain_core.messages import HumanMessage, SystemMessage

    lc_messages = []
    for m in messages:
        if m["role"] == "system":
            lc_messages.append(SystemMessage(content=m["content"]))
        else:
            lc_messages.append(HumanMessage(content=m["content"]))

    base_options = {
        "temperature": 0,
        # Без stop-последовательности маленькие модели копируют формат few-shot
        # примеров и генерируют новые "Q: ... A: ..." пары вместо остановки после ответа.
        "stop": ["\nQ:", "\n\nQ:"],
        # use_mmap=false (дефолт Ollama при частичном GPU-оффлоаде) заставляет читать
        # весь файл модели в системную RAM перед копированием в VRAM — из-за этого
        # gemma4 (~9 ГиБ) не грузилась при нехватке RAM, хотя VRAM хватало с запасом.
        "use_mmap": True,
    }
    try:
        # num_gpu=999 форсирует полный оффлоад на GPU (нужно для части моделей —
        # см. gemma4 выше). Некоторые архитектуры (MoE: qwen35moe, gpt-oss) отвергают
        # любое явное значение num_gpu ошибкой "memory layout cannot be allocated" —
        # для них нужно доверять авто-подбору Ollama (без num_gpu).
        response = llm.invoke(lc_messages, options={**base_options, "num_gpu": 999})
    except Exception as exc:
        if "memory layout cannot be allocated" not in str(exc):
            raise
        response = llm.invoke(lc_messages, options=base_options)
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
    import argparse as _argparse
    parser = _argparse.ArgumentParser(description="RAG-бот Astral Strife")
    parser.add_argument("--demo", action="store_true", help="Прогон встроенных демо-запросов")
    parser.add_argument(
        "--no-defense", action="store_true",
        help="Отключить защиту от prompt injection (INSECURE — только для демонстрации)"
    )
    parser.add_argument(
        "--index", type=Path, default=None,
        help="Путь к каталогу FAISS-индекса (default: index/)"
    )
    parser.add_argument(
        "--model", type=str, default=EMBEDDING_MODEL,
        help=f"Embedding-модель (default: {EMBEDDING_MODEL}); должна совпадать с моделью, "
             "которой строился индекс (см. build_report.json в каталоге индекса)",
    )
    args = parser.parse_args()

    defense = not args.no_defense
    index_path = (ROOT / args.index if args.index and not Path(args.index).is_absolute()
                  else Path(args.index) if args.index else INDEX_DIR)

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
    if not (index_path / "index.faiss").exists():
        print(
            f"[ERROR] Index not found: {index_path}/index.faiss\n"
            "Run: python scripts/build_index.py",
            file=sys.stderr,
        )
        return 1

    # Загрузка embeddings и индекса
    print(f"[INFO] Loading embedding model: {args.model}")
    embeddings = HuggingFaceEmbeddings(
        model_name=args.model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )

    print(f"[INFO] Loading FAISS index: {index_path}")
    vectorstore = FAISS.load_local(
        str(index_path),
        embeddings,
        allow_dangerous_deserialization=True,
    )

    # Инициализация LLM (Ollama)
    print(f"[INFO] Connecting to Ollama: {OLLAMA_BASE_URL}, model={OLLAMA_MODEL}")
    llm = ChatOllama(
        model=OLLAMA_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    defense_label = "SECURE (defense ON)" if defense else "⚠️  INSECURE (defense OFF)"

    if args.demo:
        # --- Демо-режим: прогон фиксированных запросов ---
        print("\n" + "═" * 64)
        print("  DEMO MODE — Astral Strife Knowledge Base RAG Bot")
        print("═" * 64)
        print(f"  Model: {OLLAMA_MODEL} | Threshold: {RELEVANCE_THRESHOLD}")
        print(f"  Mode: {defense_label}")
        print(f"  Index: {index_path}")
        print("═" * 64 + "\n")

        print("── IN-DOMAIN QUERIES (bot should answer) ──\n")
        for q in DEMO_QUERIES_IN_DOMAIN:
            ask(q, vectorstore, llm, defense=defense)

        print("\n── OUT-OF-DOMAIN QUERIES (bot should say 'I don't know') ──\n")
        for q in DEMO_QUERIES_OUT_OF_DOMAIN:
            ask(q, vectorstore, llm, defense=defense)

        print("[OK] Demo complete.")
        return 0

    # --- REPL ---
    print("\n" + "═" * 64)
    print("  Astral Strife Knowledge Base RAG Bot")
    print(f"  Model: {OLLAMA_MODEL} | {defense_label}")
    print(f"  Type /exit to quit | /help for hints")
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

        ask(query, vectorstore, llm, defense=defense)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
