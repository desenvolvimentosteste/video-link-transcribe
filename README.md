# video-link-transcribe

Baixa o vídeo de um link, extrai o áudio, transcreve e resume, apagando vídeo e áudio ao longo da esteira. Se o link for um post só de imagens, baixa as imagens e lê o texto delas com OCR, em vez de extrair áudio.

## Esteira

1. Baixa o vídeo do link (YouTube, Instagram ou TikTok) com `yt-dlp`, em qualidade até 720p.
2. Extrai um frame por segundo com `ffmpeg` e monta uma grade de contato, para ler na tela nomes de sites e ferramentas que o áudio não deixa claro. Os frames são apagados depois da leitura.
3. Extrai o áudio com `ffmpeg` (mono, 16 kHz, mp3) e apaga o vídeo original.
4. Transcreve o áudio em pedaços de 60 segundos com `faster-whisper` (modelo leve `whisper-tiny`) e apaga o áudio original.
5. Só fica o texto, que é resumido. Quando o vídeo descrever um método ou ferramenta sem dizer o nome, o agente infere o nome a partir da descrição, dos frames e da transcrição, e diz que é uma inferência.

Se o link não tiver vídeo, a esteira desvia para imagens: `scripts/download_images.py` baixa as imagens do post (a maior miniatura de cada item, via API Python do `yt-dlp`) e `scripts/ocr_images.sh` lê o texto de cada uma com `tesseract`, gerando `ocr.txt`. As imagens são apagadas depois da leitura e só fica o texto.

## Uso

```sh
scripts/pipeline.sh <link-do-vídeo> <pasta-de-trabalho> [idioma]
```

Exemplo:

```sh
scripts/pipeline.sh "https://www.instagram.com/reel/XXXX/" ~/workspace/video-pipeline/reel-1 pt
```

A transcrição fica em `<pasta-de-trabalho>/transcript/transcript.txt`. Para posts de imagem, o OCR fica em `<pasta-de-trabalho>/ocr/ocr.txt` e a legenda em `<pasta-de-trabalho>/images.json`.

## Preparar o ambiente

Crie um ambiente virtual e instale as dependências:

```sh
python3 -m venv ~/workspace/venvs/video-pipeline
~/workspace/venvs/video-pipeline/bin/pip install yt-dlp faster-whisper
```

Baixe o modelo leve:

```sh
~/workspace/venvs/video-pipeline/bin/python -c "from huggingface_hub import snapshot_download; snapshot_download('Systran/faster-whisper-tiny', local_dir='~/workspace/models/whisper-tiny')"
```

O `ffmpeg` precisa estar instalado no sistema, assim como o `tesseract` para o OCR das imagens:

```sh
sudo apt-get install -y tesseract-ocr tesseract-ocr-por tesseract-ocr-eng
```

## Limites

- YouTube costuma funcionar. Instagram e TikTok nem sempre deixam baixar e podem pedir login.
- Posts só de imagem funcionam quando são públicos; posts que exigem login não baixam.
- Comece com vídeos curtos e modelo leve, pois a transcrição pode ficar lenta ou falhar por falta de memória.
- Não use `/tmp` para os arquivos, pois ele tem pouco espaço.
