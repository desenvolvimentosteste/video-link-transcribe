#!/usr/bin/env python3
"""Baixa as imagens de um post (ex.: carrossel do Instagram) via API Python do yt-dlp.

Uso: download_images.py <url> <pasta-de-imagens> <images.json>

O yt-dlp em linha de comando falha em posts só de imagem
("No video formats found"), porque não há formatos de vídeo. Mas o extrator
devolve cada item com `thumbnails` (image_versions2 do Instagram). Por isso
a captura é feita pela API: extract_info(download=False) e baixa-se a maior
miniatura de cada item, com o cabeçalho Referer do Instagram.

Em posts públicos o extrator costuma funcionar sem login. Se a verificação
do certificado falhar (proxy da VM), tenta de novo sem verificar o
certificado. Não contorna bloqueio nem login: se o post exigir login, falha.
"""
import json
import os
import sys
import urllib.request


def extract(url, nocheck=False):
    from yt_dlp import YoutubeDL
    opts = {'quiet': True, 'no_warnings': True, 'skip_download': True,
            'extract_flat': False, 'ignore_no_formats_error': True}
    if nocheck:
        opts['nocheckcertificate'] = True
    with YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)


def main():
    url, outdir, json_path = sys.argv[1], sys.argv[2], sys.argv[3]
    try:
        info = extract(url)
    except Exception as e:
        if 'CERTIFICATE_VERIFY_FAILED' in str(e):
            info = extract(url, nocheck=True)
        else:
            raise
    entries = info.get('entries') or ([info] if info.get('_type') != 'playlist' else [])
    entries = [e for e in entries if e]
    if not entries:
        print('Nenhuma imagem encontrada.', file=sys.stderr)
        return 1
    os.makedirs(outdir, exist_ok=True)
    out = []
    for i, e in enumerate(entries, 1):
        thumbs = e.get('thumbnails') or []
        if not thumbs and e.get('thumbnail'):
            thumbs = [{'url': e['thumbnail']}]
        if not thumbs:
            continue
        # O extrator devolve as miniaturas da maior para a menor; sem largura
        # informada, max() fica com a primeira, que é a maior.
        best = max(thumbs, key=lambda t: t.get('width') or 0)
        fname = f'image-{i:02d}.jpg'
        req = urllib.request.Request(
            best['url'],
            headers={'Referer': 'https://www.instagram.com/',
                     'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=60) as r, \
                open(os.path.join(outdir, fname), 'wb') as f:
            f.write(r.read())
        out.append({'index': i, 'id': e.get('id'), 'file': fname,
                    'description': e.get('description')})
    json.dump(out, open(json_path, 'w'), ensure_ascii=False, indent=1)
    print(f'{len(out)} imagens baixadas em {outdir}')
    return 0 if out else 1


if __name__ == '__main__':
    sys.exit(main())
