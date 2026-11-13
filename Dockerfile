FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY incident_responder ./incident_responder
RUN useradd --create-home app
USER app
ENV PORT=8080
CMD ["sh", "-c", "uvicorn incident_responder.server:create_app --factory --host 0.0.0.0 --port ${PORT}"]
