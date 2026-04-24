"""
Скрипт дампа БД CaucasHub через API.
Запускать вручную или по крону: python3 backup_db.py
"""
import json, requests, datetime, os

API = "https://api-production-f3ea.up.railway.app"
BACKUP_DIR = "/root/.openclaw/workspace/caucashub/backups"
os.makedirs(BACKUP_DIR, exist_ok=True)

today = datetime.datetime.utcnow().strftime("%Y-%m-%d_%H%M")

# Логинимся как admin
token = requests.post(f"{API}/api/auth/login", json={
    "email": "timuraz@caucashub.ge",  # заменить на реальный email
    "password": "YOUR_PASSWORD"
}).json().get("token", "")

backup = {
    "timestamp": today,
    "loads": requests.get(f"{API}/api/loads/?scope=local&limit=500").json(),
    "loads_intl": requests.get(f"{API}/api/loads/?scope=intl&limit=500").json(),
}

if token:
    backup["deals"] = requests.get(f"{API}/api/deals/my",
        headers={"Authorization": f"Bearer {token}"}).json()
    backup["export_csv"] = requests.get(f"{API}/api/deals/export?format=csv&status=all",
        headers={"Authorization": f"Bearer {token}"}).text

path = f"{BACKUP_DIR}/backup_{today}.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(backup, f, ensure_ascii=False, indent=2, default=str)
print(f"✅ Backup saved: {path}")
