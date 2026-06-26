#!/usr/bin/env python3
"""Imprime las claves y motivos de comparacion_redespacho.json para diagnóstico en CI."""
import json
from pathlib import Path

f = Path("processed/comparacion_redespacho.json")
if not f.exists():
    print("ERROR: processed/comparacion_redespacho.json NO EXISTE")
    exit(1)

d = json.loads(f.read_text())
print(f"Claves en comparacion_redespacho.json: {sorted(d.keys())}")
for k, v in sorted(d.items()):
    print(f"  sem {k}: motivos={v.get('motivos')}, balance_items={len(v.get('balance', {}))}")
