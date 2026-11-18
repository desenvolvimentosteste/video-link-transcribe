#!/bin/bash
# Esteira: link de vídeo -> áudio -> transcrição -> só texto.
# Se o link for um post só de imagens (ex.: carrossel do Instagram),
# baixa as imagens e lê o texto delas com OCR, em vez de extrair áudio.
# Uso: pipeline.sh <url> <pasta-de-trabalho> [idioma]
# A pasta de trabalho deve ficar em ~/workspace/video-pipeline/
# O vídeo é apagado após extrair o áudio (ou após os frames, quando há
# legendas). O áudio é apagado após transcrever.
#
# Melhorias vindas do estudo da skill Watch (bradautomates/claude-video):
# - Legendas primeiro: se o vídeo tem legenda nativa, ela vira a
#   transcrição e o Whisper nem roda (fetch_captions.py).
# - Frames com orçamento: fps automático com teto de 100 frames, mais
#   frames de mudança de cena e remoção de duplicados (extract_frames.py).
# - report.json com duração, origem da transcrição e contagem de frames.
# - Checagem de veracidade: o último passo extrai as afirmações
#   verificáveis da transcrição (extract_claims.py -> claims.json) para
#   o agente conferir na web antes de entregar o resumo.
set -eu
URL="${1:?Informe o link do vídeo}"
WORKDIR="${2:?Informe a pasta de trabalho}"
LANG="${3:-pt}"
mkdir -p "$WORKDIR"
VIDEO="$WORKDIR/video.mp4"
AUDIO="$WORKDIR/audio.mp3"
TRANSCRIPT_DIR="$WORKDIR/transcript"
# Modelo padrão: small (464 MB, ~1 GB de RAM em int8). Teste A/B em
# 2026-11-18 no reel da pirâmide (98 s): o small acertou nomes e números
# que o tiny errava — Mega-Sena, CVM/xerife, PF, 127 mil pessoas (o tiny
# escreveu "1207 mil") — sem estourar a RAM da VM (7,7 GB). O tiny fica
# em ~/workspace/models/whisper-tiny como reserva.
MODEL="$HOME/workspace/models/whisper-small"

VENV="$HOME/workspace/venvs/video-pipeline"
YTDLP="$VENV/bin/yt-dlp"
VENV_PY="$VENV/bin/python"
[ -x "$YTDLP" ] || YTDLP="yt-dlp"
[ -x "$VENV_PY" ] || VENV_PY="python3"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

command -v "$YTDLP" >/dev/null || { echo "yt-dlp não instalado. Rode: $VENV/bin/pip install yt-dlp" >&2; exit 1; }
command -v ffmpeg >/dev/null || { echo "ffmpeg não instalado." >&2; exit 1; }
[ -d "$MODEL" ] || { echo "Modelo whisper não encontrado em $MODEL" >&2; exit 1; }

echo "Passo 1: baixando o vídeo..."
# O proxy de saída da VM apresenta certificado autoassinado que o Python nem
# sempre valida; sem --no-check-certificates o download falha de forma
# intermitente com CERTIFICATE_VERIFY_FAILED.
YTDLP_LOG="$WORKDIR/ytdlp.log"
if "$YTDLP" --no-check-certificates -f "bestvideo[height<=720]+bestaudio/best[height<=720]/best" --merge-output-format mp4 -o "$VIDEO" "$URL" >"$YTDLP_LOG" 2>&1 && [ -s "$VIDEO" ]; then
  :
elif grep -qE "No video formats found|There is no video in this post" "$YTDLP_LOG" 2>/dev/null; then
  echo "Sem vídeo no link — tentando baixar como imagens..."
  IMAGES_DIR="$WORKDIR/images"
  OCR_DIR="$WORKDIR/ocr"
  if "$VENV_PY" "$SCRIPT_DIR/download_images.py" "$URL" "$IMAGES_DIR" "$WORKDIR/images.json"; then
    "$SCRIPT_DIR/ocr_images.sh" "$IMAGES_DIR" "$OCR_DIR" "por+eng"
    echo "Imagens em $IMAGES_DIR e OCR em $OCR_DIR/ocr.txt — apague as imagens após a revisão."
    echo "Passo 5: extraindo afirmações verificáveis do OCR..."
    "$VENV_PY" "$SCRIPT_DIR/extract_claims.py" "$OCR_DIR/ocr.txt" "$WORKDIR/claims.json" 2>/dev/null || true
    exit 0
  fi
  echo "Não foi possível baixar nem vídeo nem imagens deste link." >&2
  exit 1
else
  echo "Falha ao baixar o vídeo. Último erro:" >&2
  tail -5 "$YTDLP_LOG" >&2
  exit 1
fi

echo "Passo 1b: extraindo frames para leitura visual..."
FRAMES="$WORKDIR/frames"
mkdir -p "$FRAMES"
if ! "$VENV_PY" "$SCRIPT_DIR/extract_frames.py" "$VIDEO" "$FRAMES" "$WORKDIR" 100 640; then
  echo "extract_frames.py falhou — voltando ao modo antigo (1 fps)..." >&2
  ffmpeg -y -i "$VIDEO" -vf "fps=1,scale=640:-1" "$FRAMES/frame-%03d.jpg" 2>/dev/null
  COUNT=$(ls "$FRAMES"/frame-*.jpg 2>/dev/null | wc -l)
  COLS=6
  ROWS=$(( (COUNT + COLS - 1) / COLS ))
  ffmpeg -y -framerate 1 -i "$FRAMES/frame-%03d.jpg" -filter_complex "tile=${COLS}x${ROWS}" -frames:v 1 "$WORKDIR/contact.jpg" 2>/dev/null
  echo "Frames extraídos: $COUNT em $FRAMES (não apague antes de o agente ler as imagens)."
fi

echo "Passo 1c: tentando legendas nativas antes de transcrever..."
mkdir -p "$TRANSCRIPT_DIR"
CAPTIONS_OK=0
if "$VENV_PY" "$SCRIPT_DIR/fetch_captions.py" "$URL" "$TRANSCRIPT_DIR/transcript.txt" "pt,en,es" "$YTDLP" 2>/dev/null; then
  CAPTIONS_OK=1
  echo "Legendas nativas encontradas — pulando a transcrição por Whisper."
fi

TRANSCRIPT_SOURCE="whisper"
if [ "$CAPTIONS_OK" = 1 ]; then
  TRANSCRIPT_SOURCE="captions"
  echo "Passo 2: apagando o vídeo (legendas já cobrem o áudio)..."
  rm -f "$VIDEO"
  echo "Vídeo original apagado."
else
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
fi

echo "Passo 4: relatório da execução..."
"$VENV_PY" - "$WORKDIR" "$TRANSCRIPT_SOURCE" <<'EOF'
import json, sys
from pathlib import Path
workdir, source = Path(sys.argv[1]), sys.argv[2]
frames_meta = {}
fj = workdir / "frames.json"
if fj.exists():
    frames_meta = json.loads(fj.read_text(encoding="utf-8"))
report = {
    "duration_seconds": frames_meta.get("duration"),
    "transcript_source": source,
    "frames": len(frames_meta.get("frames", [])),
    "frame_candidates": frames_meta.get("candidates"),
    "dropped_duplicates": frames_meta.get("dropped_duplicates"),
    "video_deleted": not (workdir / "video.mp4").exists(),
    "audio_deleted": not (workdir / "audio.mp4").exists() and not (workdir / "audio.mp3").exists(),
    "transcript": "transcript/transcript.txt",
}
(workdir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"relatório em {workdir / 'report.json'}")
EOF
echo "Passo 5: extraindo afirmações verificáveis para checagem..."
"$VENV_PY" "$SCRIPT_DIR/extract_claims.py" "$TRANSCRIPT_DIR/transcript.txt" "$WORKDIR/claims.json" 2>/dev/null || echo "aviso: não foi possível extrair afirmações" >&2
echo "Frames em $FRAMES e contato em $WORKDIR/contact.jpg — apague-os após a revisão visual."
