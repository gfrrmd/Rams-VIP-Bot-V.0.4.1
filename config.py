import os
import json

# ── ENV VARS ─────────────────────────────────────────────────────
BOT_TOKEN = os.environ["BOT_TOKEN"]
ADMIN_ID  = int(os.environ["ADMIN_ID"])

RESTRICTED_CHANNELS_RAW = os.environ.get("RESTRICTED_CHANNELS", "[]")
try:
    RESTRICTED_CHANNELS: list = json.loads(RESTRICTED_CHANNELS_RAW)
except Exception:
    RESTRICTED_CHANNELS = []

# ── DEVICE PROFILE ────────────────────────────────────────────────
DEVICE_MODEL     = "iPhone 17 Pro Max"
SYSTEM_VERSION   = "iOS 26.4"
APP_VERSION      = "11.4.1"
LANG_CODE        = "id"
SYSTEM_LANG_CODE = "id-ID"
