#!/usr/bin/env python3
"""
build_index.py — построение FAISS-индекса по анонимизированной базе знаний.

Вход:  knowledge_base/*.md       — документы с YAML-frontmatter (title, category, lang)
       --extra-dir DIR (опц.)    — доп. каталог с документами (напр. data/malicious/)
Выход: index/index.faiss         — бинарный FAISS-индекс        (или --out DIR)
       index/index.pkl           — сериализованные метаданные
       index/build_report.json   — статистика прогона

Использование:
  python scripts/build_index.py                               # стандартный индекс
  python scripts/build_index.py --extra-dir data/malicious --out index_security

Пайплайн:
  1. Прочитать документы, распарсить frontmatter, отделить тело.
  2. Нарезать текст на чанки: RecursiveCharacterTextSplitter(chunk_size=1500, chunk_overlap=200).
  3. Добавить метаданные на каждый чанк: source, title, category, lang, chunk_index, chunk_id.
  4. Сгенерировать эмбеддинги: sentence-transformers/all-MiniLM-L6-v2 (dim=384).
  5. Построить FAISS-индекс (L2 на нормализованных векторах ≈ cosine) через FAISS.save_local().
  6. Вывести статистику, записать build_report.json.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# На Windows-консоли (cp1251) emoji/box-символы в print иначе падают с UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
KB_DIR = ROOT / "knowledge_base"
INDEX_DIR = ROOT / "index"

EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
# Размер чанка в СИМВОЛАХ (length_function=len). На корпусе ≈6.4 симв/слово
# 1500 символов ≈ 230 слов — попадает в требуемый ТЗ диапазон 100–300 слов.
CHUNK_SIZE = 1500
CHUNK_OVERLAP = 200   # ~13% overlap — сохранение контекста на границах чанков


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Распарсить YAML-frontmatter (---...---) и вернуть (meta, body).

    Поддерживает только простые пары key: value (строковые/числовые).
    Возвращает пустой словарь и весь текст, если frontmatter отсутствует.
    """
    stripped = text.lstrip()
    if not stripped.startswith("---"):
        return {}, text

    end = stripped.find("\n---", 3)
    if end == -1:
        return {}, text

    fm_block = stripped[3:end].strip()
    body = stripped[end + 4:].lstrip("\n")

    meta: dict[str, str] = {}
    for line in fm_block.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            meta[k.strip()] = v.strip().strip('"').strip("'")
    return meta, body


def slugify(text: str) -> str:
    """Конвертировать строку в kebab-case ASCII slug."""
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[\s_-]+", "-", text).strip("-") or "chunk"


# ---------------------------------------------------------------------------
# Основной пайплайн
# ---------------------------------------------------------------------------


def main() -> int:
    # --- CLI-аргументы -------------------------------------------------------
    parser = argparse.ArgumentParser(description="Построение FAISS-индекса базы знаний")
    parser.add_argument(
        "--kb-dir",
        type=Path,
        default=KB_DIR,
        help=f"Каталог с .md-документами базы знаний (default: {KB_DIR})",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=EMBEDDING_MODEL,
        help=f"Embedding-модель (default: {EMBEDDING_MODEL}); для не-английских корпусов "
             "используйте мультиязычную, напр. sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
    )
    parser.add_argument(
        "--extra-dir",
        type=Path,
        default=None,
        help="Доп. каталог с .md-документами для включения в индекс (напр. data/malicious)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=INDEX_DIR,
        help=f"Каталог для сохранения индекса (default: {INDEX_DIR})",
    )
    args = parser.parse_args()
    out_dir: Path = args.out if args.out.is_absolute() else ROOT / args.out
    kb_dir: Path = args.kb_dir if args.kb_dir.is_absolute() else ROOT / args.kb_dir

    # Отложенный импорт — пакеты могут отсутствовать при первой проверке кода
    try:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        from langchain_core.documents import Document
        from langchain_huggingface import HuggingFaceEmbeddings
        from langchain_community.vectorstores import FAISS
    except ImportError as exc:
        print(
            f"[ERROR] Не хватает зависимостей: {exc}\n"
            "Установите: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    # --- 1. Чтение документов -----------------------------------------------
    md_files = sorted(kb_dir.glob("*.md"))
    if args.extra_dir:
        extra_path = args.extra_dir if args.extra_dir.is_absolute() else ROOT / args.extra_dir
        md_files = md_files + sorted(extra_path.glob("*.md"))
        print(f"[INFO] Включаю доп. каталог: {extra_path} ({len(sorted(extra_path.glob('*.md')))} файлов)")
    if not md_files:
        print(f"[ERROR] В {kb_dir} нет .md-файлов.", file=sys.stderr)
        return 1

    splitter = RecursiveCharacterTextSplitter(
        separators=["\n\n", "\n", " ", ""],
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
    )

    all_docs: list[Document] = []
    for md_path in md_files:
        raw = md_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)

        title = meta.get("title", md_path.stem)
        category = meta.get("category", "unknown")
        lang = meta.get("lang", "en")
        # Реальный путь относительно корня репо (knowledge_base/… или data/malicious/…),
        # чтобы провенанс чанка не подменялся на knowledge_base/ для --extra-dir файлов.
        try:
            source_rel = md_path.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            source_rel = md_path.name
        slug = slugify(title)

        # Нарезка на чанки
        chunks = splitter.split_text(body)
        for idx, chunk_text in enumerate(chunks):
            chunk_id = f"{slug}-{idx}"
            doc = Document(
                page_content=chunk_text,
                metadata={
                    "source": source_rel,
                    "title": title,
                    "category": category,
                    "lang": lang,
                    "chunk_index": idx,
                    "chunk_id": chunk_id,
                },
            )
            all_docs.append(doc)

    total_chunks = len(all_docs)
    print(f"[INFO] Документов: {len(md_files)}, чанков: {total_chunks}")

    # --- 2. Генерация эмбеддингов и построение индекса ----------------------
    model_name: str = args.model
    print(f"[INFO] Загружаю embedding-модель: {model_name}")
    embeddings = HuggingFaceEmbeddings(
        model_name=model_name,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},  # нормализация → L2-ранжирование ≈ cosine
    )

    print("[INFO] Генерирую эмбеддинги и строю FAISS-индекс…")
    t_start = time.perf_counter()
    vectorstore = FAISS.from_documents(all_docs, embeddings)
    elapsed = time.perf_counter() - t_start
    print(f"[INFO] Индекс построен за {elapsed:.2f} с")

    # --- 3. Сохранение индекса ----------------------------------------------
    out_dir.mkdir(parents=True, exist_ok=True)
    vectorstore.save_local(str(out_dir))
    print(f"[OK] Индекс сохранён: {out_dir}/index.faiss + {out_dir}/index.pkl")

    # --- 4. build_report.json -----------------------------------------------
    report = {
        "model": model_name,
        "embedding_dim": int(vectorstore.index.d),  # из реального индекса, не хардкод
        "chunk_size": CHUNK_SIZE,
        "chunk_overlap": CHUNK_OVERLAP,
        "num_documents": len(md_files),
        "num_chunks": total_chunks,
        "elapsed_seconds": round(elapsed, 3),
        "built_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_base": str(kb_dir.relative_to(ROOT) if kb_dir.is_relative_to(ROOT) else kb_dir),
        "extra_dir": (str(args.extra_dir) if args.extra_dir else None),
        "index_path": str(out_dir.relative_to(ROOT) if out_dir.is_relative_to(ROOT) else out_dir),
    }
    report_path = out_dir / "build_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[OK] Отчёт сохранён: {report_path}")
    print(
        f"\n📊 Итог: {len(md_files)} документов → {total_chunks} чанков, "
        f"dim=384, {elapsed:.2f} с"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
