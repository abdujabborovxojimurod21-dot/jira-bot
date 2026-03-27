"""
Bot sozlamalari — Railway environment variables orqali
"""
import os

# Telegram Bot Token
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8474428264:AAFTwr0h_TNB1i5lBsPBzY73R61Dks2aHRw")

# Jira server manzili
JIRA_BASE_URL = os.environ.get("JIRA_BASE_URL", "https://edoc.uztelecom.uz")

# Yangi topshiriqlarni tekshirish oralig'i (soniyalarda)
POLL_INTERVAL_SECONDS = int(os.environ.get("POLL_INTERVAL_SECONDS", "300"))
