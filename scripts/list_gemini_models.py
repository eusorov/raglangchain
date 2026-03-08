#!/usr/bin/env python3
"""
List available Google Gemini models for generateContent.
Requires GOOGLE_API_KEY in .env or environment.
Usage: python scripts/list_gemini_models.py
"""
import os
import sys

from dotenv import dotenv_values

config = dotenv_values(".env")
api_key = os.getenv("GOOGLE_API_KEY") or config.get("GOOGLE_API_KEY")
if not api_key:
    print("Set GOOGLE_API_KEY in .env or environment.", file=sys.stderr)
    sys.exit(1)

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
try:
    import urllib.request

    with urllib.request.urlopen(url) as resp:
        data = resp.read().decode()
except Exception as e:
    print(f"Request failed: {e}", file=sys.stderr)
    sys.exit(1)

import json

payload = json.loads(data)
models = payload.get("models") or []
if not models:
    print("No models returned. Check API key and quota.")
    sys.exit(0)

print("Available models (use the short name for GEMINI_MODEL):")
print("-" * 60)
for m in models:
    name = m.get("name", "")
    # name is like "models/gemini-2.0-flash"
    short = name.replace("models/", "") if name.startswith("models/") else name
    display = m.get("displayName", "")
    supported = m.get("supportedGenerationMethods") or []
    gen = "generateContent" in supported
    mark = " ✓" if gen else ""
    print(f"  {short:<35} {display}{mark}")
