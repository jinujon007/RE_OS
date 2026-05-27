import requests, os
from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

def send_alert(message: str, level: str = "INFO") -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False
    prefix = {"INFO": "ℹ️", "WARN": "⚠️", "ALERT": "🔴"}.get(level, "")
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": f"{prefix} RE_OS\n{message}"})
    return resp.ok
