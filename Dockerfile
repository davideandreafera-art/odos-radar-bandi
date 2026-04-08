# Usa Python 3.10
FROM python:3.10-slim

# Imposta variabili d'ambiente per evitare prompt interattivi di apt
ENV DEBIAN_FRONTEND=noninteractive

# Installa dipendenze, Chrome e font per mascherare il bot
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    unzip \
    fonts-liberation \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Sfrutta la cache di Docker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice
COPY . .

# Avvia con timeout esteso e fallback sicuro sulla porta 10000
CMD sh -c "gunicorn --bind 0.0.0.0:${PORT:-10000} --timeout 120 --workers 2 ricerca_bandi:app"
