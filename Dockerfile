FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DATA_DIR=/app/data SETUP_BIND=0.0.0.0
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home chat
COPY app.py auth.py setup_account.py set_api_key.py LICENSE ./
COPY templates ./templates
COPY static ./static
RUN mkdir data && chown chat:chat data
USER chat
EXPOSE 8080
CMD ["gunicorn", "--no-control-socket", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--timeout", "180", "app:create_app()"]
