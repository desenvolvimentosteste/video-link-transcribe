#!/usr/bin/env python3
"""Legendas primeiro, transcrição só se não houver legenda.

Adaptado de bradautomates/claude-video (scripts/download.py e
transcribe.py): o yt-dlp lista as faixas de legenda do vídeo, escolhe a
melhor (manual antes de automática, idiomas preferidos primeiro) e baixa
só aquela em VTT. O VTT é convertido para o formato de transcrição da
esteira: "[<início> - <fim>]  <texto>".

Uso: fetch_captions.py <url> <saída-transcript.txt> [idiomas] [yt-dlp]
  idiomas: lista separada por vírgula, padrão "pt,en,es".
  Sai com 0 e escreve o arquivo quando há legenda com conteúdo;
  sai com 1 quando não há legenda — a esteira cai para o Whisper.
"""
from __future__ import annotations

import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TIME = r"(?:[0-9]{2,}:)?[0-5][0-9]:[0-5][0-9][.,][0-9]{3}"
TIMING_RE = re.compile(rf"^\s*({TIME})\s+-->\s+({TIME})(?:\s+.*)?$")
TAG_RE = re.compile(r"<[^>]*>")


def _seconds(stamp: str) -> float:
    return sum(float(p) * 60 ** i for i, p in
               enumerate(reversed(stamp.replace(",", ".").split(":"))))


def parse_vtt(path: Path) -> list:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    segments, i = [], 0
    while i < len(lines):
        line = lines[i]
        if re.match(r"^(NOTE(?:\s|$)|STYLE$|REGION$)", line):
            i += 1
            while i < len(lines) and lines[i] != "":
                i += 1
            continue
        m = TIMING_RE.match(line)
        if not m:
            i += 1
            continue
        start, end = map(_seconds, m.groups())
        i += 1
        payload = []
        while i < len(lines) and lines[i] != "":
            if TIMING_RE.match(lines[i]):
                break
            payload.append(lines[i])
            i += 1
        text = " ".join(html.unescape(TAG_RE.sub("", p)).strip()
                        for p in payload).strip()
        if text and end >= start:
            segments.append({"start": start, "end": end, "text": text})
    # Deduplicar cues sobrepostas com o mesmo texto (eco do VTT automático).
    out = []
    for s in segments:
        if (out and s["start"] < out[-1]["end"]
                and (s["text"] == out[-1]["text"]
                     or s["text"].startswith(out[-1]["text"] + " "))):
            out[-1]["text"] = s["text"]
            out[-1]["end"] = max(out[-1]["end"], s["end"])
            continue
        out.append(s)
    return out


def select_track(info: dict, prefs: list) -> dict | None:
    manual = {k: v for k, v in (info.get("subtitles") or {}).items()
              if v and k != "live_chat"}
    auto = {k: v for k, v in (info.get("automatic_captions") or {}).items()
            if v and k != "live_chat"}

    def norm(lang: str) -> str:
        return lang.split("-")[0].lower()

    for kind, pool in (("manual", manual), ("automatic", auto)):
        for pref in prefs:
            for key in pool:
                if norm(key) == pref:
                    return {"key": key, "kind": kind}
        for key in pool:  # qualquer idioma, se nenhum preferido existir
            return {"key": key, "kind": kind}
    return None


def main() -> int:
    url = sys.argv[1]
    out_txt = Path(sys.argv[2])
    prefs = sys.argv[3].split(",") if len(sys.argv) > 3 else ["pt", "en", "es"]
    ytdlp = sys.argv[4] if len(sys.argv) > 4 else "yt-dlp"

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        info_path = tmp / "info.json"
        r = subprocess.run(
            [ytdlp, "--no-check-certificates", "--skip-download",
             "--write-info-json", "--no-write-subs", "--no-write-auto-subs",
             "-o", str(tmp / "info.%(ext)s"), "--", url],
            capture_output=True, text=True)
        # O info.json sai como info.info.json com esse -o.
        cands = list(tmp.glob("*.info.json")) or ([info_path]
                                                  if info_path.exists() else [])
        if r.returncode != 0 or not cands:
            print("sem info de legendas", file=sys.stderr)
            return 1
        info = json.loads(cands[0].read_text(encoding="utf-8"))
        track = select_track(info, prefs)
        if not track:
            print("sem faixa de legenda", file=sys.stderr)
            return 1
        args = [ytdlp, "--no-check-certificates", "--skip-download",
                "--no-write-info-json",
                "--write-subs" if track["kind"] == "manual"
                else "--no-write-subs",
                "--write-auto-subs" if track["kind"] == "automatic"
                else "--no-write-auto-subs",
                "--sub-langs", "-all,^" + re.escape(track["key"]) + "$",
                "--sub-format", "vtt/best", "--convert-subs", "vtt",
                "-o", str(tmp / "video.%(ext)s"), "--", url]
        r = subprocess.run(args, capture_output=True, text=True)
        vtt = tmp / f"video.{track['key']}.vtt"
        if r.returncode != 0 or not vtt.is_file() or vtt.stat().st_size == 0:
            print("falha ao baixar a legenda", file=sys.stderr)
            return 1
        segments = parse_vtt(vtt)
        if not segments:
            print("legenda vazia", file=sys.stderr)
            return 1
        out_txt.parent.mkdir(parents=True, exist_ok=True)
        out_txt.write_text(
            "\n".join(f"[{s['start']:.3f} - {s['end']:.3f}]  {s['text']}"
                      for s in segments) + "\n", encoding="utf-8")
        print(f"legendas: {track['key']} ({track['kind']}), "
              f"{len(segments)} segmentos")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
