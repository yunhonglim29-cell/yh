FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    APP_ENV=production \
    HOST=0.0.0.0 \
    PORT=8000
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && groupadd --gid 10001 cityhunt \
    && useradd --uid 10001 --gid 10001 --no-create-home cityhunt
COPY app.py run.py seed.py docker_entrypoint.py ./
COPY static ./static
EXPOSE 8000
# The entrypoint fixes a newly mounted volume's permissions, then drops root.
# Set ADMIN_PASSWORD, PUBLIC_URL and a persistent /data volume at runtime.
ENTRYPOINT ["python", "/app/docker_entrypoint.py"]
