FROM python:3.11-slim

# ffmpeg es necesario para que yt-dlp pueda mergear video+audio y convertir a mp3
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Railway inyecta la variable PORT en runtime
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
