FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=America/Sao_Paulo \
    FRONTEND_DIST=/app/frontend/dist
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY alembic.ini pyproject.toml ./
COPY migrations ./migrations
COPY app ./app
COPY scripts ./scripts
COPY tests/__init__.py ./tests/__init__.py
COPY tests/fixtures ./tests/fixtures
# o front já vai compilado (frontend/dist); para recompilar: cd frontend && npm install && npm run build
COPY frontend/dist ./frontend/dist
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
