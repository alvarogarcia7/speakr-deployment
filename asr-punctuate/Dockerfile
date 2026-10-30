# Build context is the repo root (see docker-compose.yml)
FROM python:3.12-alpine
WORKDIR /app
COPY scripts/spoken_punctuation.py /app/spoken_punctuation.py
COPY asr-punctuate/proxy.py /app/proxy.py
EXPOSE 9000
CMD ["python", "proxy.py"]
