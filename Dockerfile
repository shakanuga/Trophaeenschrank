FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DATA_DIR=/data \
    PORT=8766 \
    PUID=99 \
    PGID=100

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME ["/data"]
EXPOSE 8766

HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/healthz')" || exit 1

# Startet als root nur, um /data die Rechte zu geben – läuft danach als PUID:PGID.
# Ein Worker (wegen des eingebauten Zeitplans), 16 Threads für parallele Cover-Anfragen.
ENTRYPOINT ["/entrypoint.sh"]
