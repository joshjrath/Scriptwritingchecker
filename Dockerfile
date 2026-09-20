FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scriptcheck ./scriptcheck
COPY scriptcheck.config.example.json ./

# Config and overrides are mounted or baked in by the host; the token and
# webhook arrive as environment variables and are never in the image.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=60s --timeout=10s --start-period=40s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=5).status == 200 else 1)"

CMD ["python", "-m", "scriptcheck", "serve"]
