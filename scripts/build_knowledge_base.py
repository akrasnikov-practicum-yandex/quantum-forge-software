#!/usr/bin/env python3
"""
build_knowledge_base.py — сборка анонимизированной базы знаний для RAG-бота.

Вход:  data/source_sw/*.md   — исходные энциклопедические статьи (известная модели вселенная)
        terms_map.json        — словарь замен {оригинал: вымышленное}
Выход: knowledge_base/*.md    — те же статьи с заменёнными терминами и анонимизированными
                                именами файлов.

Логика замены:
  * ключи словаря сортируются по убыванию длины (longest-match-first), чтобы составной
    термин ("Darth Vader") срабатывал раньше своей части ("Vader");
  * компилируется ОДИН regex-альтернатива со \\b-границами и re.IGNORECASE;
  * замена выполняется за ОДИН проход (re.sub с callback) — это исключает каскадную
    повторную замену уже подставленных слов;
  * регистр сохраняется: для нижнего регистра оригинала replacement приводится к нижнему,
    для остального берётся каноническое написание из словаря.

После сборки выполняется самопроверка: knowledge_base/ сканируется по всем ключам словаря;
наличие любого оригинального термина означает ошибку покрытия.
"""

from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

# На Windows-консоли (cp1251) emoji/box-символы в print иначе падают с UnicodeEncodeError.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "data" / "source_sw"
OUT_DIR = ROOT / "knowledge_base"
TERMS_PATH = ROOT / "terms_map.json"

# Независимый от словаря deny-list ХАРАКТЕРНЫХ (неоднозначно-английских лучше избегать)
# терминов Star Wars, включая формы мн. числа и слова, которых может не быть в terms_map.
# Это ВТОРАЯ самопроверка: ловит утечки, невидимые для словарной (которая знает только
# свои ключи). Сюда НЕ включены generic-английские слова (force/empire/republic/clone/…),
# чтобы не падать на легитимной прозе — их покрывает словарная проверка.
SW_DENYLIST = re.compile(
    r"\b(?:jedi|sith|lightsabers?|skywalker|darth|vader|kenobi|obi-?wan|yoda|padawans?|"
    r"kyber|hyperdrives?|hyperspace|hyperlanes?|lightspeed|wookiees?|jawas?|ewoks?|"
    r"tusken|mandalor\w*|ahsoka|tano|palpatine|sidious|chewbacca|chewie|boba|jango|jabba|"
    r"tatooine|coruscant|dagobah|mustafar|alderaan|kashyyyk|kamino|naboo|endor|hoth|"
    r"death\s+star|x-wing|tie\s+fighters?|millennium\s+falcon|carbonite|stormtroopers?|"
    r"younglings?|astromech|star\s+wars)\b",
    re.IGNORECASE,
)


def load_terms() -> dict[str, str]:
    with TERMS_PATH.open(encoding="utf-8") as fh:
        terms = json.load(fh)
    if not isinstance(terms, dict) or not terms:
        raise ValueError("terms_map.json должен быть непустым объектом {оригинал: вымышленное}")
    return terms


def build_pattern(terms: dict[str, str]) -> re.Pattern[str]:
    # longest-match-first: длинные ключи раньше коротких
    keys = sorted(terms, key=len, reverse=True)
    alternation = "|".join(re.escape(k) for k in keys)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE)


def make_replacer(terms: dict[str, str]):
    lookup = {k.lower(): v for k, v in terms.items()}

    def repl(match: re.Match[str]) -> str:
        original = match.group(0)
        replacement = lookup[original.lower()]
        # согласуем регистр ПЕРВОГО символа с оригиналом, сохраняя внутренний
        # регистр канонического значения (имена собственные остаются с заглавной):
        # "The Force" -> "The Synth Flux", "the Force" -> "the Synth Flux",
        # "Kyber" -> "Reson", "clones" -> "vat-born".
        if original[:1].isupper():
            return replacement[:1].upper() + replacement[1:]
        return replacement[:1].lower() + replacement[1:]

    return repl


_ARTICLE_RE = re.compile(r"\b(an?)(\s+)([A-Za-z])", re.IGNORECASE)


def fix_articles(text: str) -> str:
    """Согласует неопределённый артикль a/an после замены терминов.

    Замена меняет начальный звук слова ("a lightsaber" -> "a arc-glaive"),
    поэтому артикль нужно пересчитать по первой букве следующего слова.
    Простая эвристика по гласной букве; редкие случаи (silent h, "u"-as-you)
    в сгенерированном корпусе не встречаются.
    """

    def repl(m: re.Match[str]) -> str:
        article, space, first = m.group(1), m.group(2), m.group(3)
        new = "an" if first.lower() in "aeiou" else "a"
        if article[0].isupper():
            new = new.capitalize()
        return f"{new}{space}{first}"

    return _ARTICLE_RE.sub(repl, text)


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    return re.sub(r"[\s_-]+", "-", text) or "document"


def extract_title(text: str) -> str | None:
    # frontmatter title: ...
    m = re.search(r"(?m)^title:\s*(.+?)\s*$", text)
    if m:
        return m.group(1).strip().strip('"').strip("'")
    # первый H1
    m = re.search(r"(?m)^#\s+(.+?)\s*$", text)
    if m:
        return m.group(1).strip()
    return None


def clean_text(text: str) -> str:
    # нормализация: CRLF -> LF, схлопывание хвостовых пробелов, не более одной пустой строки подряд
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def main() -> int:
    if not SRC_DIR.exists():
        print(f"[ERROR] нет каталога с исходниками: {SRC_DIR}", file=sys.stderr)
        return 1

    terms = load_terms()
    pattern = build_pattern(terms)
    replacer = make_replacer(terms)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # очистка предыдущего результата, чтобы не копились старые файлы
    for old in OUT_DIR.glob("*.md"):
        old.unlink()

    sources = sorted(SRC_DIR.glob("*.md"))
    if not sources:
        print(f"[ERROR] в {SRC_DIR} нет .md файлов", file=sys.stderr)
        return 1

    used_slugs: dict[str, int] = {}
    written = 0
    for src in sources:
        raw = clean_text(src.read_text(encoding="utf-8"))
        renamed = pattern.sub(replacer, raw)
        renamed = fix_articles(renamed)

        title = extract_title(renamed) or src.stem
        slug = slugify(title)
        # защита от коллизий имён
        if slug in used_slugs:
            used_slugs[slug] += 1
            slug = f"{slug}-{used_slugs[slug]}"
        else:
            used_slugs[slug] = 0

        (OUT_DIR / f"{slug}.md").write_text(clean_text(renamed), encoding="utf-8")
        written += 1

    print(f"[OK] записано {written} документов в {OUT_DIR}")

    # --- самопроверка №1: остаточные термины ИЗ СЛОВАРЯ ---
    leftovers: list[str] = []
    # --- самопроверка №2: независимый deny-list (ловит мн.число и неучтённые SW-слова) ---
    denylist_hits: list[str] = []
    for out in sorted(OUT_DIR.glob("*.md")):
        text = out.read_text(encoding="utf-8")
        for m in pattern.finditer(text):
            leftovers.append(f"{out.name}: '{m.group(0)}'")
        for m in SW_DENYLIST.finditer(text):
            denylist_hits.append(f"{out.name}: '{m.group(0)}'")

    if leftovers or denylist_hits:
        if leftovers:
            print(f"[FAIL] остаточные термины из словаря: {len(leftovers)}", file=sys.stderr)
            for item in leftovers[:50]:
                print("   ", item, file=sys.stderr)
        if denylist_hits:
            print(f"[FAIL] deny-list поймал SW-термины (не покрыты словарём): {len(denylist_hits)}",
                  file=sys.stderr)
            for item in denylist_hits[:50]:
                print("   ", item, file=sys.stderr)
        return 2

    print(f"[OK] остаточных терминов: 0 (словарь {len(terms)} записей + независимый deny-list)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
