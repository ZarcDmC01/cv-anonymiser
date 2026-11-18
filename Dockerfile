# Image unique : site ESN (:8000) + site Entreprises (:8001), deux serveurs FastAPI séparés par port.
# Ollama reste sur l'hôte (OLLAMA_URL). PDF via LibreOffice (Word n'existe pas sous Linux).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends libreoffice-writer fonts-liberation fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN sed -i 's/\r$//' start.sh && chmod +x start.sh
ENV HOST=0.0.0.0
EXPOSE 8000 8001
CMD ["./start.sh"]
