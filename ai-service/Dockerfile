FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY models ./models

ENV AI_SERVICE_CLASSIFIER=real \
    AI_MODEL_PATH=/srv/models/model.onnx

EXPOSE 8051

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8051"]