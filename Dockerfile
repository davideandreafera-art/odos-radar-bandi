# Usa Python di base
FROM python:3.10-slim

# Installa Google Chrome sul server per far girare Selenium
RUN apt-get update && apt-get install -y wget gnupg2 curl unzip
RUN wget -q -O - https://dl-ssl.google.com/linux/linux_signing_key.pub | apt-key add -
RUN echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" >> /etc/apt/sources.list.d/google.list
RUN apt-get update && apt-get install -y google-chrome-stable

# Copia i nostri file nel server
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .

# Accende il server web e lo mette in ascolto!
CMD gunicorn --bind 0.0.0.0:$PORT ricerca_bandi:app
