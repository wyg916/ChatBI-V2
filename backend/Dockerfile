FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
RUN pip install --no-cache-dir \
    ./packages/rag-contracts \
    ./packages/rag-adapter \
    ./packages/agent-contracts \
    ./packages/agent-orchestrator \
    ./packages/prompt-registry
COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/scripts ./scripts
COPY evaluation/golden/day2-golden-20.json ./evaluation/golden/day2-golden-20.json
COPY evaluation/golden/day4-golden-50.json ./evaluation/golden/day4-golden-50.json

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
