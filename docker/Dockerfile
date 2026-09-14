FROM python:3.12-slim AS base
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

FROM base AS runtime
# platformkit is a sibling path dependency in monorepo-style local builds
COPY platformkit /deps/platformkit
COPY agentforge /app
WORKDIR /app
RUN pip install --no-cache-dir "/deps/platformkit[postgres,redis]" \
    && pip install --no-cache-dir .
ENV AGENTFORGE_FIXTURES_ROOT=/app/fixtures
EXPOSE 8090
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
CMD ["agentforge", "serve", "--host", "0.0.0.0", "--port", "8090"]

FROM runtime AS test
RUN pip install --no-cache-dir ".[dev]"
CMD ["pytest", "tests/", "-v"]
