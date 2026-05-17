import os
import json
import sys
from pathlib import Path
import requests

# Asegurar que el proyecto esté en el PYTHONPATH
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.core.config import settings

url = settings.base44_webhook_url
token = settings.bot_webhook_token

headers = {
    "x-bot-token": token,
    "Content-Type": "application/json",
}

payload = {"test": "manual_ping"}

print("POST", url)
print("Headers:", headers)
print("Payload:", payload)

try:
    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    print("Status:", resp.status_code)
    print("Response headers:")
    for k, v in resp.headers.items():
        print(f"  {k}: {v}")
    print("\nResponse body:\n", resp.text[:2000])
    sys.exit(0 if resp.status_code == 200 else 2)
except Exception as e:
    print("Error:", e)
    sys.exit(3)
