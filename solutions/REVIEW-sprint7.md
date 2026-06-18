# Ревью спринта 7 и применённые исправления

**Дата:** 2026-06-18
**Ветка исправлений:** `rag-review-fixes` (от `rag`)

Документ фиксирует результат проверки всех 5 заданий + сквозных требований
(`description.md`/`submit.md`) и перечень внесённых исправлений. Проверка проведена двойным
проходом (ревью → состязательная верификация по реальному коду и артефактам, `py_compile`
всех скриптов). Решение прогонялось в локальном `.venv` (Python 3.13, зависимости из
`requirements.txt`); индексы пересобраны, демонстрации с LLM требуют запущенного Ollama.

## Сводка вердиктов

| Задание | Было | Стало |
|---|---|---|
| 1. Исследование | pass-with-issues | ✅ согласовано с реализацией |
| 2. База знаний | реальные утечки (ложноотрицательная самопроверка) | ✅ 0 утечек, deny-list |
| 3. Векторный индекс | размер чанка вне ТЗ | ✅ 100% чанков 171–215 слов |
| 4. RAG-бот | 2 бага (мутация docstore, порог) | ✅ баги устранены |
| 5. Безопасность | демо не показывало утечку | ✅ INSECURE→утечка, SECURE→блок |
| Сквозные | нет Docker / Project_template | ✅ добавлены |

---

## Исправлено в этой ветке

### 🔴 Critical
- **C1. Docker.** Добавлены [`Dockerfile`](../Dockerfile) (python:3.11-slim, предзагрузка
  embedding-модели, встроенные FAISS-индексы) и [`docker-compose.yml`](../docker-compose.yml)
  (сервисы `bot` + `ollama`). Запуск: `docker compose build && docker compose run --rm bot`.

### 🟠 Major
- **M1. Утечки анонимизации (Задание 2).** В `knowledge_base/` оставались SW-термины
  `Padawans`, `hyperdrives`/`Hyperdrives`, `hyperlane` — словарная самопроверка их не видела
  (проверяла только ключи `terms_map.json`). Добавлены недостающие формы в
  [`terms_map.json`](../terms_map.json) (132 записи) и **независимый deny-list** в
  [`build_knowledge_base.py`](../scripts/build_knowledge_base.py) (вторая самопроверка, фейлит
  сборку при любом характерном SW-слове). Пересобрано → **0 остаточных** (проверено grep'ом).
- **M2. Размер чанка (Задание 3).** Было `chunk_size=800` символов → медиана 67 слов, 81%
  чанков < 100 слов (вне ТЗ 100–300 слов). Стало `1500/200` → **все 36 чанков 171–215 слов**,
  100% в диапазоне. Индексы `index/` и `index_security/` пересобраны; `build_report.json`
  обновлён (`embedding_dim` теперь берётся из индекса, а не хардкод).
- **M3. Баг мутации docstore (Задания 4/5).** `sanitize()` переписывал `page_content` прямо в
  Document'ах FAISS-docstore (возвращаются по ссылке) → порча чанков между запросами в REPL.
  Исправлено: санитизация на **копии** `Document`.
- **M4. Порог «Я не знаю» (Задание 4).** Комментарий/док заявляли калибровку по out-of-domain,
  которой в Task-3 нет. Формулировки приведены к честным: порог — **эвристика** (отсечка 1.3 по
  наблюдаемым in-domain 0.5–1.1); метрика исправлена на L2 (а не inner product).
- **M5. Демонстрация безопасности (Задание 5).** Раньше relevance-guard блокировал malicious-чанк
  в обоих режимах → утечка не демонстрировалась. Теперь:
  - INSECURE (`security_demo.py`) отключает guard → malicious-чанк доходит до LLM (утечка);
  - в `ask()` слой 2 `is_malicious` отбрасывает вредоносный чанк **до** guard → SECURE наглядно
    блокирует (проверено: чанк top-1, `is_malicious=True`, dropped=1).
- **M7. Согласование Task-1 ↔ реализация.** Отчёт рекомендовал облачный GPT-4o-mini (Вариант D),
  а бот использует локальную Ollama. В Task-1 и Task-4 добавлены пояснения: выбран локальный
  путь (ближе к Варианту C) ради конфиденциальности/SOC 2.
- **M8. Project_template.md.** Создан [`Project_template.md`](../Project_template.md) — сводные
  ответы по всем заданиям со ссылками на `solutions/` (требование `description.md`/`submit.md`).

### 🟡 Minor (исправлено)
- Метрика индекса: код/доки говорили `IndexFlatIP`/inner product, фактически L2 — поправлено в
  `build_index.py`, `rag_bot.py`, Task-3, Task-4 (на нормализованных векторах L2 ≈ cosine).
- `embedding_dim` в `build_report.json` теперь вычисляется из `vectorstore.index.d`.
- `query_index.py`: добавлен флаг `--index` (можно искать по `index_security/`).
- Провенанс источника (F5): `source` теперь реальный путь (`data/malicious/leaked-credentials.md`
  вместо `knowledge_base/...`).
- `security.py`: ужесточён паттерн `act as a` (ловил прозу «act as a coordinator») — привязан к
  началу строки; целевой malicious-файл по-прежнему детектируется.
- **UnicodeEncodeError на Windows.** Скрипты падали при печати emoji/box-символов в cp1251-консоль.
  Во все runtime-скрипты добавлен `sys.stdout.reconfigure(encoding="utf-8")`.
- `requirements.txt` запинен по версиям (воспроизводимость, важно для Docker).
- Добавлен `README.md` (точка входа, структура, запуск).

---

## Осталось сделать вручную (нельзя в этой среде)

- **M6. Воспроизводимые логи Задания 5.** Текущие логи в `Task-5-security.md` — самозаписаны.
  Нужно запустить `python scripts/security_demo.py` с поднятым Ollama (`ollama pull llama3.2:3b`)
  и сохранить реальный stdout в `solutions/logs/security_demo.txt`. Механизм (утечка vs блок) уже
  исправлен в коде; не хватает только захвата фактического вывода LLM.
- **M9. Сдача.** Перед отправкой убедиться на GitHub, что: репозиторий **публичный** и открыт
  **PR `rag` → `main`** в собственном репозитории (`gh` в среде недоступен — не проверяется
  локально). При желании влить `rag-review-fixes` в `rag` до PR.
- (Опц.) 5 «обычных» out-of-domain отказов в Task-4 одним блоком (сейчас 2 в Task-4 + полный 5+5
  набор в Task-5/`security_demo.py`).

---

## Верификация (выполнено в этой ветке)

```
build_knowledge_base.py → 36 док, 0 остаточных (словарь 132 + deny-list)
grep по SW-терминам в knowledge_base/ → 0 совпадений (вкл. Padawans/hyperdrives/hyperlane)
build_index.py → 36 док → 36 чанков; распределение слов: min 171 / median 190 / max 215; 0 вне [100;300]
index_security retrieval: malicious top-1 score≈1.405, source=data/malicious/…, is_malicious=True, dropped=1
py_compile всех 6 скриптов → OK (Python 3.13)
venv smoke-import всех модулей → OK
security self-test: malicious=True, ложное 'act as a'=False
```

Полный разбор находок с состязательными вердиктами — в выводе workflow проверки
(`reviews` по task1…task5 + cross).
