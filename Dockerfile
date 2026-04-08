# Usa Python 3.10
FROM python:3.10-slim

# Installa le dipendenze di sistema e Google Chrome (Metodo aggiornato 2026)
RUN apt-get update && apt-get install -y \
    wget \
    gnupg \
    curl \
    unzip \
    && wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | gpg --dearmor -o /usr/share/keyrings/google-chrome.gpg \
    && echo "deb [arch=amd64 signed-by=/usr/share/keyrings/google-chrome.gpg] http://dl.google.com/linux/chrome/deb/ stable main" > /etc/apt/sources.list.d/google-chrome.list \
    && apt-get update && apt-get install -y google-chrome-stable \
    && apt-get clean && rm -rf /var/lib/apt/lists/*

# Imposta la cartella di lavoro
WORKDIR /app

# Copia e installa i requisiti
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il resto del codice
COPY . .

# Comando per avviare il server
CMD sh -c "gunicorn --bind 0.0.0.0:$PORT --timeout 120 --workers 2 ricerca_bandi:app"
