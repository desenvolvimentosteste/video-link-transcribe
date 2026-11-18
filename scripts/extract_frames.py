#!/usr/bin/env python3
"""Extrai frames de um vídeo com orçamento fixo, no espírito do Watch.

Estratégia (adaptada de bradautomates/claude-video, scripts/frames.py):
- Amostragem uniforme com fps automático: fps = min(1.0, max_frames/duração),
  para vídeos curtos ~1 fps e vídeos longos com teto de max_frames.
- Detecção de cena: primeiro frame + mudanças de cena (threshold 0.20).
  Se houver menos de 8 cenas distintas o vídeo é quase estático e a
  amostragem uniforme já cobre tudo.
- Dedup: cada frame vira um thumbnail RGB 16x16; dois frames são
  quase-idênticos quando a diferença média por canal é <= 2.0 — o segundo
  é descartado. Isso tira slides parados e quadros repetidos.
- Teto de max_frames (padrão 100); se ainda passar, subamostra uniforme
  mantendo o primeiro e o último frame.

Saídas: frames/frame-%03d.jpg, frames.json [{file, t}] e contact.jpg
(mosaico 6 colunas, como a esteira já fazia).

Uso: extract_frames.py <video> <frames-dir> <workdir> [max_frames] [largura]
Requer ffmpeg/ffprobe no PATH e numpy (no venv da esteira).
"""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCENE_THRESHOLD = 0.20
SCENE_MIN_FRAMES = 8
DEDUP_THUMB = 16
DEDUP_THRESHOLD = 2.0


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def probe_duration(video: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "json", str(video)])
    if r.returncode != 0:
        raise SystemExit(f"ffprobe falhou: {r.stderr.strip()}")
    return float(json.loads(r.stdout)["format"]["duration"])


def thumb_bytes(path: Path) -> "object":
    """Thumbnail RGB 16x16 como array numpy (H, W, 3) uint8."""
    import numpy as np
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-vf",
         f"scale={DEDUP_THUMB}:{DEDUP_THUMB}", "-f", "rawvideo", "-pix_fmt",
         "rgb24", "-"], capture_output=True)
    if r.returncode != 0 or len(r.stdout) < DEDUP_THUMB * DEDUP_THUMB * 3:
        raise SystemExit(f"ffmpeg não conseguiu gerar thumbnail de {path}")
    return np.frombuffer(r.stdout, dtype=np.uint8).reshape(
        DEDUP_THUMB, DEDUP_THUMB, 3).astype(float)


def mean_diff(a, b) -> float:
    import numpy as np
    return float(np.abs(a - b).mean())


def uniform_frames(video: Path, out: Path, fps: float, width: int) -> list:
    out.mkdir(parents=True, exist_ok=True)
    r = run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vf",
             f"fps={fps:.4f},scale={width}:-1",
             str(out / "u-%04d.jpg")])
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg (uniforme) falhou: {r.stderr.strip()}")
    files = sorted(out.glob("u-*.jpg"))
    return [{"file": f, "t": i / fps} for i, f in enumerate(files)]


def scene_frames(video: Path, out: Path, width: int) -> list:
    out.mkdir(parents=True, exist_ok=True)
    r = run(["ffmpeg", "-y", "-v", "info", "-i", str(video), "-vf",
             f"select='eq(n\\,0)+gt(scene\\,{SCENE_THRESHOLD})',"
             f"scale={width}:-1,showinfo",
             "-vsync", "vfr", str(out / "s-%04d.jpg")])
    if r.returncode != 0:
        raise SystemExit(f"ffmpeg (cenas) falhou: {r.stderr.strip()}")
    times = [float(m) for m in
             re.findall(r"pts_time:([0-9.]+)", r.stderr)]
    files = sorted(out.glob("s-*.jpg"))
    # showinfo emite um pts_time por frame emitido; alinhar por ordem.
    out_list = []
    for i, f in enumerate(files):
        t = times[i] if i < len(times) else None
        out_list.append({"file": f, "t": t})
    # Sem timestamp confiável, espaçar uniformemente (ordem preservada).
    if any(x["t"] is None for x in out_list):
        for i, x in enumerate(out_list):
            if x["t"] is None:
                x["t"] = -1.0
        out_list.sort(key=lambda x: (x["t"] if x["t"] >= 0 else 1e9,
                                     str(x["file"])))
    return out_list


def main() -> int:
    video = Path(sys.argv[1])
    frames_dir = Path(sys.argv[2])
    workdir = Path(sys.argv[3])
    max_frames = int(sys.argv[4]) if len(sys.argv) > 4 else 100
    width = int(sys.argv[5]) if len(sys.argv) > 5 else 640

    duration = probe_duration(video)
    fps = min(1.0, max_frames / max(duration, 1.0))
    frames_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(dir=workdir) as tmp:
        tmp = Path(tmp)
        uni = uniform_frames(video, tmp / "uni", fps, width)
        sce = scene_frames(video, tmp / "sce", width)
        use_scene = len(sce) >= SCENE_MIN_FRAMES
        cands = sorted(uni + (sce if use_scene else []),
                       key=lambda x: (x["t"], str(x["file"])))

        kept = []
        last_thumb = None
        dropped_dup = 0
        for c in cands:
            try:
                th = thumb_bytes(c["file"])
            except SystemExit:
                continue
            if last_thumb is not None and mean_diff(th, last_thumb) <= DEDUP_THRESHOLD:
                dropped_dup += 1
                continue
            kept.append(c)
            last_thumb = th

        if len(kept) > max_frames:
            # Subamostra uniforme preservando primeiro e último.
            idx = sorted(set(
                round(i * (len(kept) - 1) / (max_frames - 1))
                for i in range(max_frames)))
            kept = [kept[i] for i in idx]

        # Escrever os frames finais com nomes sequenciais.
        for old in frames_dir.glob("frame-*.jpg"):
            old.unlink()
        meta = []
        for i, c in enumerate(kept, 1):
            name = f"frame-{i:03d}.jpg"
            dest = frames_dir / name
            c["file"].replace(dest)
            meta.append({"file": name, "t": round(float(c["t"]), 3)})

    (workdir / "frames.json").write_text(
        json.dumps({"duration": round(duration, 3), "fps_uniform": round(fps, 4),
                    "scene_frames_used": use_scene,
                    "candidates": len(cands), "dropped_duplicates": dropped_dup,
                    "frames": meta}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    # Mosaico de contato (6 colunas), como a esteira já fazia.
    count = len(meta)
    cols = 6
    rows = max(1, math.ceil(count / cols))
    r = run(["ffmpeg", "-y", "-framerate", "1", "-i",
             str(frames_dir / "frame-%03d.jpg"), "-filter_complex",
             f"tile={cols}x{rows}", "-frames:v", "1",
             str(workdir / "contact.jpg")])
    if r.returncode != 0:
        print(f"aviso: mosaico falhou: {r.stderr.strip()}", file=sys.stderr)

    print(f"frames: {count} (uniforme {len(uni)}, cena "
          f"{len(sce) if use_scene else 0}, duplicados removidos {dropped_dup}, "
          f"duração {duration:.1f}s, fps {fps:.3f})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
