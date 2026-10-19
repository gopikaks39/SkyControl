# SkyControl container: FastAPI backend + static 3D frontend on one port.
#   docker build -t skycontrol .                      -> runtime image (default, last stage)
#   docker build --target test -t skycontrol-test .   -> lint + test image used by Jenkins

FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY backend backend
COPY frontend frontend
COPY scripts scripts
COPY data/reference data/reference
COPY data/london_amsterdam_opensky.json.gz data/opensky_india_snapshot.json data/opensky_india_provenance.json \
     data/historical_airport_traffic_2011_feb.csv data/
COPY run.py setup_accounts.py ./

# ---- lint and tests (Jenkins runs this target, so the agent only needs Docker)
FROM base AS test
COPY requirements-dev.txt pytest.ini ruff.toml ./
RUN pip install -r requirements-dev.txt
COPY tests tests
CMD ["sh", "-c", "mkdir -p reports && ruff check . && python -m pytest --junitxml=reports/junit.xml --cov=backend --cov-report=xml:reports/coverage.xml --cov-report=term"]

# ---- runtime image
FROM base AS runtime
# Pre-compute the real-data analysis (about a minute) so the container starts instantly.
ENV SKYCONTROL_CACHE_DIR=/app/cache
RUN python scripts/build_analysis.py
# Run as an unprivileged user; the database lives on a volume.
RUN useradd --create-home --uid 10001 skycontrol \
    && mkdir -p /app/data/db \
    && chown -R skycontrol /app/data /app/cache
USER skycontrol
ENV SKYCONTROL_HOST=0.0.0.0 \
    SKYCONTROL_PORT=5000 \
    SKYCONTROL_DB=/app/data/db/skycontrol.sqlite3
EXPOSE 5000
VOLUME ["/app/data/db"]
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:5000/api/health', timeout=4)"
CMD ["python", "run.py"]
