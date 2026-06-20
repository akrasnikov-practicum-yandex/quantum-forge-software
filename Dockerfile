# Минимальный образ RAG-бота QuantumForge (бот + встроенный FAISS-индекс).
# Python 3.11 — рекомендованная версия из методички спринта.
FROM python:3.11-slim

WORKDIR /app

# 1. Зависимости (запинены в requirements.txt для воспроизводимости)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 2. Предзагрузка embedding-модели в образ (чтобы рантайм не ходил в сеть)
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

# 3. Код + готовые FAISS-индексы + база знаний
COPY scripts/ ./scripts/
COPY knowledge_base/ ./knowledge_base/
COPY index/ ./index/
COPY index_security/ ./index_security/
COPY terms_map.json ./

# LLM — локальная Ollama (адрес переопределяется в compose)
ENV OLLAMA_BASE_URL=http://ollama:11434 \
    OLLAMA_MODEL=llama3.2:3b \
    PYTHONUNBUFFERED=1

# По умолчанию — прогон демо-запросов; для REPL: docker compose run bot python scripts/rag_bot.py
CMD ["python", "scripts/rag_bot.py", "--demo"]
