#!/bin/bash
# Esteira: link de vídeo -> áudio -> transcrição -> só texto.
# Uso: pipeline.sh <url> <pasta-de-trabalho> [idioma]
# A pasta de trabalho deve ficar em ~/workspace/video-pipeline/
# O vídeo é apagado após extrair o áudio. O áudio é apagado após transcrever.
set -eu
URL="${1:?Informe o link do vídeo}"
WORKDIR="${2:?Informe a pasta de trabalho}"
LANG="${3:-pt}"
mkdir -p "$WORKDIR"
VIDEO="$WORKDIR/video.mp4"
AUDIO="$WORKDIR/audio.mp3"
TRANSCRIPT_DIR="$WORKDIR/transcript"
MODEL="$HOME/workspace/models/whisper-tiny"

VENV="$HOME/workspace/venvs/video-pipeline"
YTDLP="$VENV/bin/yt-dlp"
VENV_PY="$VENV/bin/python"
[ -x "$YTDLP" ] || YTDLP="yt-dlp"
[ -x "$VENV_PY" ] || VENV_PY="python3"

command -v "$YTDLP" >/dev/null || { echo "yt-dlp não instalado. Rode: $VENV/bin/pip install yt-dlp" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg não instalado." >&2; exit 1; }
[ -d "$MODEL" ] || { echo "Modelo whisper-tiny não encontrado em $MODEL" >&2; exit 1; }

echo "Passo 1: baixando o vídeo..."
"$YTDLP" -f "bestvideo[height<=720]+bestaudio/best[height<=720]/best" --merge-output-format mp4 -o "$VIDEO" "$URL"

echo "Passo 1b: extraindo frames para leitura visual..."
FRAMES="$WORKDIR/frames"
mkdir -p "$FRAMES"
ffmpeg -y -i "$VIDEO" -vf "fps=1,scale=640:-1" "$FRAMES/frame-%03d.jpg" 2>/dev/null
COUNT=$(ls "$FRAMES"/frame-*.jpg 2>/dev/null | wc -l)
COLS=6
ROWS=$(( (COUNT + COLS - 1) / COLS ))
ffmpeg -y -framerate 1 -i "$FRAMES/frame-%03d.jpg" -filter_complex "tile=${COLS}x${ROWS}" -frames:v 1 "$WORKDIR/contact.jpg" 2>/dev/null
echo "Frames extraídos: $COUNT em $FRAMES (não apague antes de o agente ler as imagens)."

echo "Passo 2: extraindo o áudio e apagando o vídeo..."
ffmpeg -y -i "$VIDEO" -vn -ac 1 -ar 16000 -c:a libmp3lame -q:a 4 "$AUDIO"
rm -f "$VIDEO"
echo "Vídeo original apagado."

echo "Passo 3: transcrevendo o áudio..."
"$VENV_PY" /opt/muse/assets/audio/transcribe_chunks.py \
  --input "$AUDIO" \
  --model "$MODEL" \
  --output-dir "$TRANSCRIPT_DIR" \
  --language "$LANG"

rm -f "$AUDIO"
echo "Áudio original apagado."
echo "Transcrição pronta em: $TRANSCRIPT_DIR/transcript.txt"
echo "Frames em $FRAMES e contato em $WORKDIR/contact.jpg — apague-os após a revisão visual."
