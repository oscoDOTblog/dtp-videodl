FROM python:3.11-slim

# ffmpeg for yt-dlp audio extraction; deno for YouTube JS challenge solving (yt-dlp EJS)
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl unzip \
    && curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY app ./app

ENV DATA_DIR=/data

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]

