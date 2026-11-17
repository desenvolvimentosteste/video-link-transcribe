#!/bin/bash
# OCR das imagens baixadas com tesseract.
# Uso: ocr_images.sh <pasta-de-imagens> <pasta-de-saída> [idioma-tesseract]
# Gera um .txt por imagem e um ocr.txt com todos os textos juntos, na ordem.
# O idioma padrão cobre português e inglês, que é o mais comum nos posts.
set -eu
IMAGES_DIR="${1:?Informe a pasta de imagens}"
OUT_DIR="${2:?Informe a pasta de saída}"
LANG="${3:-por+eng}"
command -v tesseract >/dev/null || { echo "tesseract não instalado. Rode: sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng" >&2; exit 1; }
mkdir -p "$OUT_DIR"
: > "$OUT_DIR/ocr.txt"
for img in "$IMAGES_DIR"/image-*.jpg; do
  [ -e "$img" ] || continue
  name=$(basename "$img" .jpg)
  tesseract "$img" "$OUT_DIR/$name" -l "$LANG" --psm 6 2>/dev/null || true
  { echo "===== $name ====="; cat "$OUT_DIR/$name.txt"; echo; } >> "$OUT_DIR/ocr.txt"
done
echo "OCR pronto em: $OUT_DIR/ocr.txt"
