import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Fallback parser for .env if python-dotenv is not installed
    env_path = os.path.join(os.path.dirname(__file__), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Google Spreadsheet Configuration
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID", "1Y6ex2HGUcGcDm18PMTPNKJlEZUrn-8YNU3hBg8o1XCo")
SPREADSHEET_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}"

# Base GViz Export URL (Works for public/shared sheets without GCP service account credentials)
GVIZ_BASE_URL = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/gviz/tq?tqx=out:csv&sheet="

# Master Product Definitions
PRODUCT_CATALOG = [
    {
        "id": 1,
        "type": "FTTH",
        "name": "< 228.999",
        "rate": 0,
        "special_rate": 0,
        "label": "FTTH < 228.999"
    },
    {
        "id": 2,
        "type": "FTTH",
        "name": ">= 229.000 s.d < 299.999",
        "rate": 50000,
        "special_rate": 0,
        "label": "FTTH 229k - 299k"
    },
    {
        "id": 3,
        "type": "FTTH",
        "name": ">= 300.000 s.d < 399.999",
        "rate": 100000,
        "special_rate": 0,
        "label": "FTTH 300k - 399k"
    },
    {
        "id": 4,
        "type": "FTTH",
        "name": ">= 400.000 s.d < 599.999",
        "rate": 125000,
        "special_rate": 0,
        "label": "FTTH 400k - 599k"
    },
    {
        "id": 5,
        "type": "FTTH",
        "name": ">= 600.000 +",
        "rate": 200000,
        "special_rate": 0,
        "label": "FTTH >= 600k"
    },
    {
        "id": 6,
        "type": "FWA / MONTHLY",
        "name": ">= 219.000",
        "rate": 50000,
        "special_rate": 0,
        "label": "FWA >= 219k"
    },
    {
        "id": 7,
        "type": "FWA & FTTH : 3 - 5 MONTH",
        "name": "50 & 100 Mbps (1)",
        "rate": 125000,
        "special_rate": 125000,
        "label": "FWA/FTTH 3-5 Bln"
    },
    {
        "id": 8,
        "type": "FWA & FTTH : >= 6 MONTH",
        "name": "50 & 100 Mbps (2)",
        "rate": 150000,
        "special_rate": 150000,
        "label": "FWA/FTTH >= 6 Bln"
    }
]

# Basic Salaries per Position
BASIC_SALARIES = {
    "OJT": 2500000,
    "PRO": 3500000,
    "ELITE": 4000000
}

# Tier Insentif Pemasangan
INSTALLATION_TIERS = {
    "OJT": [
        {"min": 1, "max": 2, "rate": 80000, "multiplier": 0.0, "label": "1 s.d 2"},
        {"min": 3, "max": 4, "rate": 100000, "multiplier": 0.0, "label": "3 s.d 4"},
        {"min": 5, "max": 6, "rate": 130000, "multiplier": 0.0, "label": "5 s.d 6"},
        {"min": 7, "max": 9, "rate": 150000, "multiplier": 0.0, "label": "7 s.d 9"},
        {"min": 10, "max": 999999, "rate": 200000, "multiplier": 0.0, "label": ">= 10"},
    ],
    "PRO": [
        {"min": 1, "max": 6, "rate": 80000, "multiplier": 0.0, "label": "1 s.d 6"},
        {"min": 7, "max": 9, "rate": 100000, "multiplier": 1.50, "label": "7 s.d 9"},
        {"min": 10, "max": 13, "rate": 130000, "multiplier": 2.00, "label": "10 s.d 13"},
        {"min": 14, "max": 29, "rate": 150000, "multiplier": 4.00, "label": "14 s.d 29"},
        {"min": 30, "max": 39, "rate": 200000, "multiplier": 4.25, "label": "30 s.d 39"},
        {"min": 40, "max": 49, "rate": 250000, "multiplier": 4.50, "label": "40 s.d 49"},
        {"min": 50, "max": 999999, "rate": 275000, "multiplier": 4.65, "label": ">= 50"},
    ],
    "ELITE": [
        {"min": 1, "max": 6, "rate": 80000, "multiplier": 0.0, "label": "1 s.d 6"},
        {"min": 7, "max": 9, "rate": 100000, "multiplier": 1.50, "label": "7 s.d 9"},
        {"min": 10, "max": 13, "rate": 130000, "multiplier": 2.00, "label": "10 s.d 13"},
        {"min": 14, "max": 29, "rate": 150000, "multiplier": 4.00, "label": "14 s.d 29"},
        {"min": 30, "max": 39, "rate": 200000, "multiplier": 4.25, "label": "30 s.d 39"},
        {"min": 40, "max": 49, "rate": 250000, "multiplier": 4.50, "label": "40 s.d 49"},
        {"min": 50, "max": 999999, "rate": 275000, "multiplier": 4.65, "label": ">= 50"},
    ]
}

# Standard Target Units
STANDARD_TARGETS = {
    "OJT": 10,
    "PRO": 12,
    "ELITE": 12
}
