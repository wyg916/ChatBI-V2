FROM python:3.11.9-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin sandbox

COPY sandbox_runtime/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt \
    && rm -f /tmp/requirements.txt

COPY sandbox_runtime/sandbox_runner.py /opt/chatbi/sandbox_runner.py
COPY sandbox_runtime/docker_control_proxy.py /opt/chatbi/docker_control_proxy.py
COPY backend/app/__init__.py /opt/chatbi/app/__init__.py
COPY backend/app/sandbox /opt/chatbi/app/sandbox
RUN chmod 0555 /opt/chatbi/sandbox_runner.py \
    /opt/chatbi/docker_control_proxy.py \
    && find /opt/chatbi/app/sandbox -type f -name '*.py' -exec chmod 0444 {} \;

ENV PYTHONPATH=/opt/chatbi

USER 65532:65532
WORKDIR /workspace

CMD ["python", "-m", "app.sandbox.controller_server"]
