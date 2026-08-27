FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY packages ./packages
COPY backend/requirements-phase3-upstream.txt .
RUN pip install --no-cache-dir -r requirements-phase3-upstream.txt
COPY backend/requirements-runtime-hardening.txt .
COPY scripts/release/patch_selected_dbgpt_metadata.py /tmp/patch_selected_dbgpt_metadata.py
RUN pip install --no-cache-dir --upgrade -r requirements-runtime-hardening.txt \
    && python /tmp/patch_selected_dbgpt_metadata.py
RUN pip install --no-cache-dir \
    ./packages/rag-contracts \
    ./packages/rag-adapter \
    ./packages/agent-contracts \
    ./packages/agent-orchestrator \
    ./packages/prompt-registry \
    && pip check

# RapidOCR 3.9.2 installs the GUI OpenCV wheel. Keep these stable system
# dependencies before application COPY layers so ordinary source upgrades do
# not repeat a 220 MB apt installation.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libxcb1 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/alembic.ini ./
COPY backend/alembic ./alembic
COPY backend/app ./app
COPY backend/vendor ./vendor
COPY backend/config ./config
COPY backend/scripts ./scripts
COPY evaluation/golden/day2-golden-20.json ./evaluation/golden/day2-golden-20.json
COPY evaluation/golden/day4-golden-50.json ./evaluation/golden/day4-golden-50.json
COPY evaluation/golden/v2.1-multiple-ground-truth.json ./evaluation/golden/v2.1-multiple-ground-truth.json

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --timeout-keep-alive 30"]
