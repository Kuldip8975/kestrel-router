FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir scikit-learn==1.9.1

COPY router/ router/
COPY static/ static/
COPY models/router.joblib models/model_card.json models/
COPY server.py .

RUN useradd --create-home --uid 10001 app && mkdir -p /app/logs && chown -R app /app/logs
USER app

ENV PORT=8000 KESTREL_LOG_DIR=/app/logs
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health').status==200 else 1)"
CMD ["python", "server.py"]
