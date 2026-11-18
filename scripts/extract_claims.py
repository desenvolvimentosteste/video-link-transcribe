#!/usr/bin/env python3
"""Extrai afirmações verificáveis de uma transcrição (ou OCR).

A checagem de veracidade em si é feita pelo agente, que tem acesso à
web: este script só separa o que vale a pena checar, para o agente não
precisar reler o texto inteiro caçando números e nomes.

O que é considerado verificável:
- números com unidade ou contexto (R$, %, kWh, kW, anos, meses, dias,
  minutos, segundos, mil, milhões, bilhões, vezes, GB, TB, km);
- nomes próprios e siglas (sequências de palavras capitalizadas e
  siglas em maiúsculas, ex.: Mega-Sena, CVM, mosca soldado-negra);
- afirmações absolutas ou causais ("sempre", "nunca", "nenhum", "só",
  "zero", "porque", "vira", "aquece", "armazena", "espanta").

Saída: claims.json com {id, texto, inicio_seg, tipo, sinais}.
Uso: extract_claims.py <transcript.txt|ocr.txt> <claims.json> [max]
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SEG_RE = re.compile(r"^\[(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\]\s*(.*)$")
NUM_RE = re.compile(
    r"(R\$\s*\d| \d+\s*(%|por cento|kWh|kW|W|anos?|meses?|semanas?|dias?|"
    r"minutos?|segundos?|mil|milh(?:ão|ões)|bilh(?:ão|ões)|vezes|GB|TB|km|"
    r"milímetros?|centímetros?|metros?|litros?|kg|g)\b|\d+[.,]\d+|"
    r"\b(um|uma|dois|duas|três|seis)\s+(semana|mês|meses|ano|anos|dia|dias)\b)",
    re.IGNORECASE)
ACRONYM_RE = re.compile(r"\b[A-Z]{2,}\b")
NAME_RE = re.compile(
    r"\b(?:[A-ZÀ-Ú][a-zà-ú]+(?:\s+(?:de|do|da|dos|das|e)\s+)?"
    r"[A-ZÀ-Ú][a-zà-ú]+|[A-ZÀ-Ú][a-zà-ú]+(?:\s+[A-ZÀ-Ú][a-zà-ú]+)+)\b")
ABSOLUTE_RE = re.compile(
    r"\b(sempre|nunca|nenhum|nenhuma|ninguém|somente|zero|pura|puro|"
    r"todo mundo|jamais)\b", re.IGNORECASE)
CAUSAL_RE = re.compile(
    r"\b(aquec\w*|armazen\w*|espant\w*|vir\w*|funcion\w*|garant\w*|"
    r"mat\w*|resolv\w*|cur\w*|porque|sem|grátis|gratuito|cem por cento|100%)\b",
    re.IGNORECASE)
METHOD_RE = re.compile(
    r"\b(instala|coloca|usa|troca|separa|joga|mantém|cria|monta|põe|"
    r"conecta|liga|desliga)\b", re.IGNORECASE)
SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
STOPWORDS = {
    "então", "mas", "agora", "depois", "assim", "quando", "se", "você",
    "parabéns", "comenta", "segue", "marca", "quer", "esse", "essa",
    "este", "esta", "aqui", "ali", "lá", "já", "ainda", "também",
}

MAX_CLAIMS = 12


def load_segments(path: Path) -> list:
    """Lê transcript.txt ([início - fim] texto) ou texto corrido."""
    segments = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        m = SEG_RE.match(line)
        if m:
            segments.append((float(m.group(1)), m.group(3)))
        else:
            segments.append((segments[-1][0] if segments else 0.0, line))
    return segments


def sentences(segments: list) -> list:
    out = []
    for start, text in segments:
        for s in SENT_SPLIT_RE.split(text):
            s = " ".join(s.split())
            if len(s) >= 20:
                out.append((start, s))
    return out


def signals(text: str) -> tuple:
    found = []
    if NUM_RE.search(text):
        found.append("numero")
    names = {n for n in NAME_RE.findall(text)
             if n.split()[0].lower() not in STOPWORDS}
    if ACRONYM_RE.search(text) or names:
        found.append("nome")
    if ABSOLUTE_RE.search(text):
        found.append("absoluto")
    if CAUSAL_RE.search(text):
        found.append("causal")
    if METHOD_RE.search(text):
        found.append("metodo")
    return tuple(found), sorted(names)


def main() -> int:
    src = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    max_claims = int(sys.argv[3]) if len(sys.argv) > 3 else MAX_CLAIMS

    sents = sentences(load_segments(src))
    claims, seen = [], set()
    for start, text in sents:
        kinds, names = signals(text)
        if not kinds:
            continue
        key = re.sub(r"\W+", "", text.lower())[:80]
        if key in seen:
            continue
        seen.add(key)
        kind = ("numero" if "numero" in kinds else
                "nome" if "nome" in kinds else
                "metodo" if "metodo" in kinds else kinds[0])
        claims.append({
            "id": len(claims) + 1,
            "texto": text,
            "inicio_seg": round(start, 1),
            "tipo": kind,
            "sinais": list(kinds),
            "nomes": names[:5],
        })
        if len(claims) >= max_claims:
            break

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(
        {"fonte": src.name, "total_frases": len(sents),
         "afirmacoes": claims},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"afirmações: {len(claims)} de {len(sents)} frases -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
