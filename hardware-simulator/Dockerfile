FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /srv

# paho-mqtt is the only runtime dependency of the simulated ESP32.
RUN pip install --no-cache-dir paho-mqtt>=2.1

COPY . .

# The hyphenated directory can't be a Python package, so the entrypoint runs
# the top-level `simulator.py` with its own dir on sys.path.
CMD ["python", "simulator.py"]