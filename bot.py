#!/usr/bin/env python3
"""
Telegram Bot untuk Sistem Kalkulasi Gaji & Insentif Sales Agent (XL SATU).
Membaca data live dari Google Spreadsheet dan melakukan kalkulasi gaji,
insentif produk, multiplier, serta insentif pemasangan.
"""

import sys
import os
import json
import time
import urllib.request
import urllib.parse
import ssl
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import logging
import signal
import atexit
from typing import Dict, Any, List, Optional

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot.lock")

def acquire_lock():
    """Pastikan hanya 1 instance bot berjalan."""
    import fcntl
    try:
        lock_fp = open(LOCK_FILE, 'w')
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        try:
            with open(LOCK_FILE, 'r') as f:
                pid = int(f.read().strip() or 0)
        except Exception:
            pid = 0
        if pid > 0:
            try:
                os.kill(pid, 0)
                print(f"\n❌ Bot sudah berjalan (PID {pid}). Hentikan proses lama dulu.")
                print(f"   Jalankan: kill -9 {pid}\n")
                sys.exit(1)
            except OSError:
                pass  # Process dead, stale lock
        lock_fp = open(LOCK_FILE, 'w')
        try:
            fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except Exception:
            return None
    except Exception:
        return None

    try:
        lock_fp.write(str(os.getpid()))
        lock_fp.flush()
        atexit.register(lambda: os.unlink(LOCK_FILE) if os.path.exists(LOCK_FILE) else None)
    except Exception:
        pass
    return lock_fp


class HealthCheckHandler(BaseHTTPRequestHandler):
    """Lightweight HTTP server for Render.com Web Service health check."""
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        res = json.dumps({"status": "ok", "service": "XL Satu Telegram Bot"}).encode("utf-8")
        self.wfile.write(res)

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress routine health check logs


def start_health_server():
    """Start background HTTP server if PORT environment variable is set (Render/Cloud)."""
    port_str = os.getenv("PORT")
    if not port_str:
        return
    try:
        port = int(port_str)
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        logger.info("Health check server aktif di 0.0.0.0:%d (Render compatibility)", port)
    except Exception as e:
        logger.warning("Gagal memulai health check server: %s", e)


from config import TELEGRAM_BOT_TOKEN, SPREADSHEET_URL, PRODUCT_CATALOG, BASIC_SALARIES, INSTALLATION_TIERS
from calculator import SalaryCalculator, format_rupiah
from sheet_reader import GoogleSheetReader
from user_manager import UserManager, clean_phone_number

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("XL_SATU_BOT")

# In-memory user state for multi-step interactions
# session structure: { chat_id: {"state": "...", "data": {...}} }
USER_SESSIONS: Dict[int, Dict[str, Any]] = {}

# Debounce tracker untuk inline query: { user_id: last_query_text }
_INLINE_LAST_QUERY: Dict[int, str] = {}


def get_ssl_context():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


class TelegramBotClient:
    def __init__(self, token: str):
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN belum diset di file .env!")
        self.token = token
        self.base_url = f"https://api.telegram.org/bot{token}"
        self.ssl_ctx = get_ssl_context()
        self.last_update_id = 0

    def api_request(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 40, _retry: int = 0) -> Dict[str, Any]:
        """Send HTTP POST request to Telegram Bot API.
        
        Otomatis retry saat kena 429 Too Many Requests (max 3x).
        Timeout pada getUpdates (long-polling) diabaikan secara senyap.
        """
        url = f"{self.base_url}/{method}"
        data = None
        headers = {"User-Agent": "XL-Satu-Bot/1.0"}

        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"

        req = urllib.request.Request(url, data=data, headers=headers)
        try:
            with urllib.request.urlopen(req, context=self.ssl_ctx, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429 and _retry < 3:
                # Baca Retry-After dari header jika ada
                retry_after = int(e.headers.get("Retry-After", 5))
                logger.warning("429 Too Many Requests pada %s. Tunggu %ds... (percobaan %d)", method, retry_after, _retry + 1)
                time.sleep(retry_after)
                return self.api_request(method, payload, timeout, _retry + 1)
            logger.error("Error calling Telegram API %s: %s", method, e)
            return {"ok": False, "error": str(e)}
        except Exception as e:
            err_str = str(e)
            # Timeout pada long-polling adalah normal, tidak perlu log error
            if method == "getUpdates" and ("timed out" in err_str.lower() or "timeout" in err_str.lower()):
                return {"ok": True, "result": []}
            logger.error("Error calling Telegram API %s: %s", method, e)
            return {"ok": False, "error": err_str}

    def get_me(self) -> Dict[str, Any]:
        return self.api_request("getMe", timeout=10)

    def get_updates(self, offset: int, timeout: int = 25) -> List[Dict[str, Any]]:
        payload = {
            "offset": offset,
            "timeout": timeout,
            "allowed_updates": ["message", "callback_query", "inline_query"]
        }
        res = self.api_request("getUpdates", payload, timeout=timeout + 10)
        if res.get("ok"):
            return res.get("result", [])
        return []

    def answer_inline_query(self, inline_query_id: str, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Answer an inline query with a list of results."""
        payload = {
            "inline_query_id": inline_query_id,
            "results": results,
            "cache_time": 0
        }
        return self.api_request("answerInlineQuery", payload, timeout=10)

    def send_message(self,
                     chat_id: int,
                     text: str,
                     reply_markup: Optional[Dict[str, Any]] = None,
                     parse_mode: str = "Markdown") -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        
        res = self.api_request("sendMessage", payload)
        # Fallback if markdown parsing fails
        if not res.get("ok") and "can't parse entities" in str(res.get("error", "")).lower():
            payload.pop("parse_mode", None)
            res = self.api_request("sendMessage", payload)
        return res

    def answer_callback_query(self, callback_query_id: str, text: Optional[str] = None):
        payload: Dict[str, Any] = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        self.api_request("answerCallbackQuery", payload, timeout=5)

    def edit_message_text(self,
                          chat_id: int,
                          message_id: int,
                          text: str,
                          reply_markup: Optional[Dict[str, Any]] = None,
                          parse_mode: str = "Markdown") -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        return self.api_request("editMessageText", payload)

    def delete_message(self, chat_id: int, message_id: int) -> bool:
        """Hapus pesan dari chat (pesan bot atau pesan user di private chat)."""
        payload = {"chat_id": chat_id, "message_id": message_id}
        try:
            res = self.api_request("deleteMessage", payload, timeout=5)
            return bool(res.get("ok"))
        except Exception:
            return False


class SalaryBotApp:
    def __init__(self, bot_client: TelegramBotClient, db_path: Optional[str] = None):
        self.bot = bot_client
        self.reader = GoogleSheetReader(cache_ttl_seconds=180)
        self.calculator = SalaryCalculator()
        self.user_manager = UserManager(db_path=db_path)
        self.running = True

    # -------------------------------------------------------------
    # Keyboard Helpers
    # -------------------------------------------------------------
    @staticmethod
    def phone_request_keyboard() -> Dict[str, Any]:
        return {
            "keyboard": [
                [{"text": "📱 Bagikan Kontak Saya", "request_contact": True}],
                [{"text": "❌ Batal"}]
            ],
            "resize_keyboard": True,
            "one_time_keyboard": True
        }

    @staticmethod
    def remove_keyboard() -> Dict[str, Any]:
        return {"remove_keyboard": True}

    @staticmethod
    def main_menu_keyboard() -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [
                    {"text": "🧮 Simulasi Gaji", "callback_data": "menu_simulasi"}
                ],
                [
                    {"text": "📋 Skema Insentif & Gaji", "callback_data": "menu_info"}
                ]
            ]
        }

    @staticmethod
    def back_to_main_keyboard() -> Dict[str, Any]:
        return {
            "inline_keyboard": [
                [{"text": "🔙 Kembali ke Menu Utama", "callback_data": "menu_main"}]
            ]
        }

    # -------------------------------------------------------------
    # Command Handlers
    # -------------------------------------------------------------
    def handle_start(self, chat_id: int, user_first_name: str = "Rekan SA"):
        text = (
            f"Halo! Selamat Datang 👋\n\n"
            f"Selamat datang di *Bot Kalkulasi Gaji & Insentif XL SATU* 🚀\n\n"
            f"Pantau komisi penjualan, insentif produk, multiplier, serta simulasi pendapatan secara realtime.\n\n"
            f"👇 *Pilih menu yang Anda butuhkan:*"
        )
        self.bot.send_message(chat_id, text, reply_markup=self.main_menu_keyboard())

    def handle_auth_name_input(self, chat_id: int, text: str, username: str = ""):
        pass  # Auth dinonaktifkan

    def handle_auth_phone_input(self, chat_id: int, message: Dict[str, Any]):
        pass  # Auth dinonaktifkan

    def handle_cek_saya_auto(self, chat_id: int, message_id: Optional[int] = None):
        """Buka daftar agen langsung."""
        self.handle_agen(chat_id, message_id=message_id)

    def handle_help(self, chat_id: int):
        text = (
            f"📖 *PANDUAN PENGGUNAAN BOT XL SATU*\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📌 *Daftar Perintah (Commands):*\n"
            f"• `/start` - Menampilkan menu utama & navigasi tombol.\n"
            f"• `/profil` - Melihat profil akun & nomor HP terdaftar.\n"
            f"• `/logout` - Keluar dari akun saat ini.\n"
            f"• `/cek <nama>` - Cek data gaji dari sheet (contoh: `/cek Noorman`).\n"
            f"• `/hitung <posisi> <unit>` - Simulasi instan (contoh: `/hitung PRO 12`).\n"
            f"• `/simulasi` - Mode simulasi interaktif step-by-step.\n"
            f"• `/agen` - Menampilkan seluruh nama Sales Agent di sheet.\n"
            f"• `/info` - Rincian tarif insentif, multiplier & tiering pemasangan.\n"
            f"• `/refresh` - Memperbarui cache data dari Google Spreadsheet.\n"
            f"• `/help` - Menampilkan pesan bantuan ini.\n\n"
            f"💡 *Tips:* Anda juga bisa menekan tombol interaktif di bawah setiap pesan!"
        )
        self.bot.send_message(chat_id, text, reply_markup=self.back_to_main_keyboard())

    def handle_info(self, chat_id: int, message_id: Optional[int] = None):
        text = (
            "📋 *SKEMA INSENTIF & GAJI — XL SATU*\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

            "💰 *GAJI POKOK*\n"
            "```\n"
            "OJT    →  Rp 2.500.000\n"
            "PRO    →  Rp 3.500.000\n"
            "ELITE  →  Rp 4.000.000\n"
            "```\n\n"

            "📦 *INSENTIF PRODUK*\n"
            "```\n"
            "FTTH < 229k          →      Rp 0\n"
            "FTTH 229k – 299k     →  Rp 50.000\n"
            "FTTH 300k – 399k     → Rp 100.000\n"
            "FTTH 400k – 599k     → Rp 125.000\n"
            "FTTH ≥ 600k          → Rp 200.000\n"
            "FWA / Monthly ≥ 219k →  Rp 50.000\n"
            "FWA + FTTH 3–5 Bln   → Rp 125.000 + Spc Rp 125.000\n"
            "FWA + FTTH ≥ 6 Bln   → Rp 150.000 + Spc Rp 150.000\n"
            "```\n\n"

            "⚡ *MULTIPLIER INSENTIF (PRO & ELITE)*\n"
            "```\n"
            " 7 –  9 unit  →  1.50×\n"
            "10 – 13 unit  →  2.00×\n"
            "14 – 29 unit  →  4.00×\n"
            "30 – 39 unit  →  4.25×\n"
            "40 – 49 unit  →  4.50×\n"
            "≥ 50 unit     →  4.65×\n"
            "```\n"
            "_(OJT: tidak dapat multiplier)_\n\n"

            "🔧 *INSENTIF PEMASANGAN*\n"
            "```\n"
            "Unit  1 –  6  →  Rp  80.000 / unit\n"
            "Unit  7 –  9  →  Rp 100.000 / unit\n"
            "Unit 10 – 13  →  Rp 130.000 / unit\n"
            "Unit 14 – 29  →  Rp 150.000 / unit\n"
            "Unit 30 – 39  →  Rp 200.000 / unit\n"
            "Unit 40 – 49  →  Rp 250.000 / unit\n"
            "Unit ≥ 50     →  Rp 275.000 / unit\n"
            "```\n\n"

            "━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            "*Take Home Pay (THP)*\n"
            "```\n"
            "  Gaji Pokok\n"
            "+ Insentif Produk\n"
            "+ Spesial Insentif\n"
            "+ (Insentif Produk × Multiplier)\n"
            "+ Insentif Pemasangan\n"
            "```"
        )
        if message_id:
            self.bot.edit_message_text(chat_id, message_id, text, reply_markup=self.back_to_main_keyboard())
        else:
            self.bot.send_message(chat_id, text, reply_markup=self.back_to_main_keyboard())

    def handle_agen(self, chat_id: int, message_id: Optional[int] = None):
        try:
            records = self.reader.get_calculation_records()
        except Exception as e:
            text = f"❌ Gagal mengambil data spreadsheet: {e}"
            self.bot.send_message(chat_id, text, reply_markup=self.back_to_main_keyboard())
            return

        if not records:
            text = "⚠️ Belum ada data Sales Agent yang tercatat di sheet *CALCULATION*."
            keyboard = self.back_to_main_keyboard()
        else:
            text = (
                f"👤 *PILIH NAMA SALES AGENT*\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"Klik nama Anda di bawah ini untuk melihat slip gaji & rincian komisi:\n\n"
                f"💡 _Tips: Anda juga bisa langsung ketik nama di chat (contoh: `Noorman`)_"
            )
            buttons = []
            for r in records:
                buttons.append([{"text": f"👉 {r['name']} ({r['position']} • {r['total_units']} Unit)", "callback_data": f"cek_agent_{r['name']}"}])
            
            buttons.append([{"text": "🔙 Kembali ke Menu Utama", "callback_data": "menu_main"}])
            keyboard = {"inline_keyboard": buttons}

        if message_id:
            self.bot.edit_message_text(chat_id, message_id, text, reply_markup=keyboard)
        else:
            self.bot.send_message(chat_id, text, reply_markup=keyboard)

    def handle_cek(self, chat_id: int, query: str = ""):
        query = query.strip()
        if not query:
            # Show interactive agent selection
            self.handle_agen(chat_id)
            return

        try:
            agent = self.reader.find_agent(query)
        except Exception as e:
            self.bot.send_message(chat_id, f"❌ Terjadi kesalahan saat membaca sheet: {e}")
            return

        if not agent:
            text = (
                f"🔍 Sales Agent dengan nama *'{query}'* tidak ditemukan di sheet.\n\n"
                f"Silakan klik tombol di bawah untuk melihat daftar nama, atau coba ketik sebagian nama."
            )
            keyboard = {
                "inline_keyboard": [
                    [{"text": "👥 Lihat Daftar Nama", "callback_data": "menu_agen"}],
                    [{"text": "🔙 Kembali ke Menu Utama", "callback_data": "menu_main"}]
                ]
            }
            self.bot.send_message(chat_id, text, reply_markup=keyboard)
            return

        # Calculate breakdown for this agent using the exact calculation logic
        res = self.calculator.calculate(
            position=agent["position"],
            product_quantities=agent["product_quantities"],
            deductions=agent["deductions"],
            agent_name=agent["name"]
        )

        report = self.calculator.format_telegram_report(res)
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "🔄 Update Data Ini", "callback_data": f"cek_agent_{agent['name']}"},
                    {"text": "👥 Ganti Nama Agen", "callback_data": "menu_agen"}
                ],
                [
                    {"text": "🧮 Simulasi Hitung Target", "callback_data": "menu_simulasi"}
                ],
                [{"text": "🏠 Kembali ke Menu Utama", "callback_data": "menu_main"}]
            ]
        }
        self.bot.send_message(chat_id, report, reply_markup=keyboard)

    def handle_simulasi_start(self, chat_id: int, message_id: Optional[int] = None):
        """Show interactive simulation directly with position switch buttons."""
        session = USER_SESSIONS.get(chat_id)
        pos = session.get("data", {}).get("position", "PRO") if session else "PRO"
        self.handle_simulasi_select_position(chat_id, pos, message_id=message_id)

    def parse_product_quantities(self, text: str, current_quantities: Optional[List[int]] = None) -> Optional[List[int]]:
        """
        Parse user input into a list of product quantities.
        Supports:
        1. N space/comma separated numbers: '0 10 2 0 0 0 0 0'
        2. Key-value pairs: '2=10, 3=2' or '2:10 3:2' or 'p2=10, p3=2'
        3. Single number: '12' -> sets standard product (product 2) to 12
        4. Template format: '[1] - 0\n[2] - 10\n[3] - 2\n...'
        """
        import re
        n = len(PRODUCT_CATALOG)
        text = text.strip()

        # Format template: [1] - 5 [2] - 10 ... atau multiline [1] - 0 \n [2] - 10
        template_pairs = re.findall(r'\[(\d+)\]\s*[-–]\s*(\d*)', text)
        if template_pairs:
            # Jika semua angka kosong (user belum mengisi apa pun pada template)
            if not any(qty.strip() != "" for _, qty in template_pairs):
                return None
            is_full = len(template_pairs) >= n
            quantities = [0] * n if is_full else (list(current_quantities) if current_quantities else [0] * n)
            for idx_str, qty_str in template_pairs:
                idx = int(idx_str) - 1
                if 0 <= idx < n:
                    if is_full:
                        quantities[idx] = int(qty_str) if qty_str.strip() else 0
                    else:
                        if qty_str.strip():
                            quantities[idx] = int(qty_str)
            return quantities

        # Check N numbers (exact match)
        nums = re.findall(r'\b\d+\b', text)
        if len(nums) == n:
            return [int(x) for x in nums]
        # Juga terima 8 angka meski n berbeda (backward compat)
        if len(nums) == 8:
            return [int(x) for x in nums]

        # Check key=value or key:value
        pairs = re.findall(r'(?:p|prod|produk)?\s*([1-9]\d?)\s*[:=]\s*(\d+)', text, re.IGNORECASE)
        if pairs:
            quantities = list(current_quantities) if current_quantities else [0] * n
            for p_idx_str, qty_str in pairs:
                idx = int(p_idx_str) - 1
                if 0 <= idx < n:
                    quantities[idx] = int(qty_str)
            return quantities

        # Check single number
        if text.isdigit():
            qty = int(text)
            quantities = [0] * n
            if n >= 2:
                quantities[1] = qty  # default to Product 2 (FTTH 229k-299k)
            return quantities

        return None

    def render_simulation_builder_text(self, position: str, quantities: List[int], step: int = 1) -> str:
        """Render multi-product simulation builder in clean card-based layout matching /info."""
        res = self.calculator.calculate(position, quantities)
        total_u = res["total_units"]
        target_u = res["target_units"]
        ach_pct = res["achievement_pct"]
        mult = res["multiplier"]
        mult_val = res["total_insentif_multiplier"]
        tot_p = res["total_insentif_produk"]
        tot_spc = res["total_spesial_insentif"]
        tot_inst = res["total_insentif_pemasangan"]
        thp = res["take_home_pay"]
        b_sal_val = res["basic_salary"]

        def fmt_rp(n):
            return f"{int(n):,}".replace(",", ".")

        DIV = "───────────────────────────────"

        ftth_cfg = [
            ("[1] < 229k",        0),
            ("[2] 229-299k",  50000),
            ("[3] 300-399k", 100000),
            ("[4] 400-599k", 125000),
            ("[5] ≥ 600k",   200000),
        ]

        fwa_cfg = [
            ("[6] ≥ 219k",    50000),
            ("[7] 3-5 Bln",  125000),
            ("[8] ≥ 6 Bln",  150000)
        ]

        # 1. INSENTIF PRODUK
        prod_lines = ["• *FTTH:*"]
        for i, (name, rate) in enumerate(ftth_cfg):
            qty = quantities[i] if i < len(quantities) else 0
            sub_reg = qty * rate
            r_str = f"Rp {fmt_rp(rate)}" if rate > 0 else "Rp 0"
            prod_lines.append(f"*{name}* ({qty} u × {r_str})")
            prod_lines.append(f"  ↳ *Rp {fmt_rp(sub_reg)}*")

        prod_lines.append("\n• *FWA:*")
        for j, (name, rate) in enumerate(fwa_cfg):
            idx = j + 5
            qty = quantities[idx] if idx < len(quantities) else 0
            sub_reg = qty * rate
            r_str = f"Rp {fmt_rp(rate)}" if rate > 0 else "Rp 0"
            prod_lines.append(f"*{name}* ({qty} u × {r_str})")
            prod_lines.append(f"  ↳ *Rp {fmt_rp(sub_reg)}*")

        prod_lines.append(DIV)
        prod_lines.append(f"*Total Produk ({total_u} u) : Rp {fmt_rp(tot_p)}*")

        # 2. SPESIAL INSENTIF
        spc_cfg = [
            ("[7] 3-5 Bln",   quantities[6] if len(quantities) > 6 else 0, 125000),
            ("[8] ≥ 6 Bln",   quantities[7] if len(quantities) > 7 else 0, 150000)
        ]
        spc_lines = []
        tot_spc_u = 0
        for name, qty, spc_rate in spc_cfg:
            sub = qty * spc_rate
            tot_spc_u += qty
            spc_lines.append(f"*{name}* ({qty} u × Rp {fmt_rp(spc_rate)})")
            spc_lines.append(f"  ↳ *Rp {fmt_rp(sub)}*")

        spc_lines.append(DIV)
        spc_lines.append(f"*Total Spesial ({tot_spc_u} u) : Rp {fmt_rp(tot_spc)}*")

        # 3. MULTIPLIER INSENTIF
        mult_lines = []
        if position.upper() == "OJT":
            mult_lines.append("Posisi *OJT* tidak mendapatkan")
            mult_lines.append("multiplier insentif.")
            mult_lines.append(DIV)
            mult_lines.append("*Total Multiplier (0.00×) : Rp 0*")
        else:
            status_str = f"{mult:.2f}× (AKTIF)" if mult > 0 else f"0.00× (Butuh {max(0, 7-total_u)} u lagi)"
            mult_lines.append(f"Tier : *{total_u} Unit* → *{status_str}*\n")
            mult_lines.append("• *FTTH:*")
            for i, (name, rate) in enumerate(ftth_cfg):
                qty = quantities[i] if i < len(quantities) else 0
                sub_reg = qty * rate
                p_mult = sub_reg * mult
                sub_str = f"Rp {fmt_rp(sub_reg)}" if sub_reg > 0 else "Rp 0"
                mult_lines.append(f"*{name}* ({sub_str})")
                mult_lines.append(f"  ↳ × {mult:.2f}× = *Rp {fmt_rp(p_mult)}*")

            mult_lines.append("\n• *FWA:*")
            for j, (name, rate) in enumerate(fwa_cfg):
                idx = j + 5
                qty = quantities[idx] if idx < len(quantities) else 0
                sub_reg = qty * rate
                p_mult = sub_reg * mult
                sub_str = f"Rp {fmt_rp(sub_reg)}" if sub_reg > 0 else "Rp 0"
                mult_lines.append(f"*{name}* ({sub_str})")
                mult_lines.append(f"  ↳ × {mult:.2f}× = *Rp {fmt_rp(p_mult)}*")

            mult_lines.append(DIV)
            mult_lines.append(f"*Total Multiplier ({mult:.2f}×) : Rp {fmt_rp(mult_val)}*")

        # 4. INSENTIF PEMASANGAN (Semua Tier)
        inst_lines = []
        for t in res["pemasangan_tiers"]:
            u = t["units"]
            r = t["rate"]
            sub = t["subtotal"]
            lbl = t.get("label", "")
            if " s.d " in lbl:
                p1, p2 = lbl.split(" s.d ")
                v1, v2 = int(p1), int(p2)
                tier_lbl = f"Unit {v1:>2}–{v2:>2}"
            elif ">=" in lbl:
                p1 = lbl.replace(">=", "").strip()
                tier_lbl = f"Unit ≥ {int(p1):>2}"
            else:
                tier_lbl = f"Unit {lbl}"

            inst_lines.append(f"*{tier_lbl}* ({u} u × Rp {fmt_rp(r)})")
            inst_lines.append(f"  ↳ *Rp {fmt_rp(sub)}*")

        inst_lines.append(DIV)
        inst_lines.append(f"*Total Pasang ({total_u} u) : Rp {fmt_rp(tot_inst)}*")

        # 5. THP BREAKDOWN
        l_mult_name = f"Multiplier {mult:.2f}×" if mult > 0 else "Multiplier 0.00×"
        thp_lines = [
            f"• Gaji Pokok {position} : *Rp {fmt_rp(b_sal_val)}*",
            f"• Insentif Produk : *Rp {fmt_rp(tot_p)}*",
            f"• Spesial Insentif : *Rp {fmt_rp(tot_spc)}*",
            f"• {l_mult_name} : *Rp {fmt_rp(mult_val)}*",
            f"• Insentif Pasang : *Rp {fmt_rp(tot_inst)}*",
            DIV,
            f"💰 *TOTAL THP : Rp {fmt_rp(thp)}*"
        ]

        b_sal_str = format_rupiah(b_sal_val)

        lines = [
            f"🧮 *SIMULASI GAJI & INSENTIF — XL SATU*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"👤 *Posisi SA* : *{position}* (Gaji Pokok: *{b_sal_str}*)",
            f"📊 *Total Jual*: *{total_u} Unit*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n",
            f"💰 *GAJI POKOK*",
            f"• *{position}* : *Rp {fmt_rp(b_sal_val)}*\n",
            f"📦 *INSENTIF PRODUK*",
            "\n".join(prod_lines) + "\n",
            f"🎁 *SPESIAL INSENTIF*",
            "\n".join(spc_lines) + "\n",
            f"⚡ *MULTIPLIER INSENTIF*",
            "\n".join(mult_lines) + "\n",
            f"🔧 *INSENTIF PEMASANGAN (SLAB TIER)*",
            "\n".join(inst_lines) + "\n",
            f"💵 *ESTIMASI TAKE HOME PAY (THP)*",
            "\n".join(thp_lines)
        ]
        return "\n".join(lines)

    def simulation_builder_keyboard(self, position: str, step: int = 1) -> Dict[str, Any]:
        # Generate template multiline dinamis: [1] - \n[2] - \n...[n] - 
        template_lines = "\n".join(f"[{i+1}] - " for i in range(len(PRODUCT_CATALOG)))
        
        pos_list = [("OJT", "🔰 OJT"), ("PRO", "⭐ PRO"), ("ELITE", "👑 ELITE")]
        pos_buttons = []
        for code, label in pos_list:
            btn_text = f"✅ {code}" if code == position.upper() else label
            pos_buttons.append({"text": btn_text, "callback_data": f"sim_pos_{code}"})

        return {
            "inline_keyboard": [
                pos_buttons,
                [
                    {
                        "text": "📋 Template Input",
                        "switch_inline_query_current_chat": f"\n{template_lines}"
                    }
                ],
                [
                    {"text": "🏠 Menu Utama", "callback_data": "menu_main"}
                ]
            ]
        }

    def send_input_template(self, chat_id: int, position: str, quantities: List[int]):
        """Kirim pesan template siap salin & edit untuk input cepat.
        
        Baris [1] s/d [n] di-generate otomatis dari PRODUCT_CATALOG sehingga
        template selalu sinkron dengan jumlah produk yang terdaftar.
        """
        n = len(PRODUCT_CATALOG)
        # Pastikan quantities minimal sepanjang jumlah produk
        qty_list = list(quantities) + [0] * max(0, n - len(quantities))
        qty_str = " ".join(str(q) for q in qty_list[:n])

        lines = [
            f"📋 *TEMPLATE INPUT CEPAT*",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"Salin teks di bawah, *edit angkanya*, lalu kirim ke chat:",
            f"",
            f"```",
            f"{position} {qty_str}",
            f"```",
            f"",
            f"📌 *Urutan {n} angka (pisah spasi):*",
        ]

        # Generate baris [1] - [2] - ... [n] secara dinamis
        for i, item in enumerate(PRODUCT_CATALOG):
            idx = i + 1
            label = item.get("label", item.get("name", f"Produk {idx}"))
            star = "  ⭐ paling umum" if item.get("rate", 0) == 50000 and item.get("type") == "FTTH" else ""
            lines.append(f"`[{idx}]` {label}  →  angka ke-{idx}{star}")

        # Contoh: ambil index produk FTTH 229k (id=2) dan FTTH 300k (id=3)
        example_qty = ["0"] * n
        if n >= 2:
            example_qty[1] = "10"
        if n >= 3:
            example_qty[2] = "2"
        example_str = " ".join(example_qty)

        # Kode singkat contoh
        short_parts = []
        if n >= 2:
            short_parts.append("2=10")
        if n >= 3:
            short_parts.append("3=2")
        short_str = " ".join(short_parts)

        lines.extend([
            f"",
            f"💡 *Contoh* — 10 unit {PRODUCT_CATALOG[1]['label'] if n >= 2 else 'Produk 2'}, "
            f"2 unit {PRODUCT_CATALOG[2]['label'] if n >= 3 else 'Produk 3'}:",
            f"`{position} {example_str}`",
            f"",
            f"⚡ *Atau pakai kode singkat* (hanya yg terisi):",
            f"`{short_str}` → sama hasilnya",
        ])
        self.bot.send_message(chat_id, "\n".join(lines))

    def handle_simulasi_select_position(self, chat_id: int, position: str, message_id: Optional[int] = None):
        session = USER_SESSIONS.get(chat_id)
        if session and session.get("state") == "SIMULATION_BUILDER" and "quantities" in session.get("data", {}):
            quantities = session["data"]["quantities"]
        else:
            quantities = [0] * 8
        step = 1
        target_mid = message_id or (session.get("data", {}).get("message_id") if session else None)
        USER_SESSIONS[chat_id] = {
            "state": "SIMULATION_BUILDER",
            "data": {
                "position": position,
                "quantities": quantities,
                "step": step,
                "message_id": target_mid
            }
        }
        text = self.render_simulation_builder_text(position, quantities, step)
        keyboard = self.simulation_builder_keyboard(position, step)

        if target_mid:
            edit_res = self.bot.edit_message_text(chat_id, target_mid, text, reply_markup=keyboard)
            if edit_res.get("ok"):
                return
        res = self.bot.send_message(chat_id, text, reply_markup=keyboard)
        if res.get("ok"):
            USER_SESSIONS[chat_id]["data"]["message_id"] = res["result"]["message_id"]

    def execute_simulation(self, chat_id: int, position: str, quantities: List[int], message_id: Optional[int] = None):
        """Execute calculation with exact per-product unit distribution."""
        total_units = sum(quantities)
        res = self.calculator.calculate(
            position=position,
            product_quantities=quantities,
            agent_name=f"Simulasi {position} ({total_units} Unit)"
        )
        report = self.calculator.format_telegram_report(res)
        
        keyboard = {
            "inline_keyboard": [
                [
                    {"text": "✏️ Ubah Jumlah Unit", "callback_data": f"sim_edit_back"},
                    {"text": "🧮 Simulasi Baru", "callback_data": "menu_simulasi"}
                ],
                [
                    {"text": "👤 Cek Gaji Saya", "callback_data": "menu_cek"},
                    {"text": "🏠 Menu Utama", "callback_data": "menu_main"}
                ]
            ]
        }
        session = USER_SESSIONS.get(chat_id)
        target_mid = message_id or (session.get("data", {}).get("message_id") if session else None)

        if target_mid:
            edit_res = self.bot.edit_message_text(chat_id, target_mid, report, reply_markup=keyboard)
            if edit_res.get("ok"):
                return
            # Jika edit gagal (misal pesan terhapus), bersihkan pesan lama
            self.bot.delete_message(chat_id, target_mid)

        send_res = self.bot.send_message(chat_id, report, reply_markup=keyboard)
        if send_res.get("ok"):
            if session:
                if "data" not in session:
                    session["data"] = {}
                session["data"]["message_id"] = send_res["result"]["message_id"]

    def handle_quick_hitung_command(self, chat_id: int, args: List[str]):
        """
        Handles:
        - /hitung
        - /hitung PRO 12
        - /hitung PRO 2=10, 3=2
        - /hitung PRO 0 10 2 0 0 0 0 0
        """
        if not args:
            self.handle_simulasi_start(chat_id)
            return

        pos = "PRO"
        if args[0].upper() in ["OJT", "PRO", "ELITE"]:
            pos = args[0].upper()
            args = args[1:]

        if not args:
            self.handle_simulasi_select_position(chat_id, pos)
            return

        rest_text = " ".join(args)
        parsed = self.parse_product_quantities(rest_text)
        if parsed:
            self.execute_simulation(chat_id, pos, parsed)
        else:
            self.bot.send_message(
                chat_id,
                f"⚠️ Format tidak dikenali.\n\n"
                f"Contoh penggunaan:\n"
                f"• `/hitung PRO 12`\n"
                f"• `/hitung PRO 2=10, 3=2`\n"
                f"• `/hitung PRO 0 10 2 0 0 0 0 0`\n"
                f"Atau gunakan `/simulasi` untuk mode interaktif.",
                reply_markup=self.back_to_main_keyboard()
            )


    def handle_refresh(self, chat_id: int, message_id: Optional[int] = None):
        """Force refresh spreadsheet cache."""
        try:
            self.reader.refresh_all()
            text = (
                f"✅ *Data Berhasil Diperbarui!*\n\n"
                f"Cache Google Spreadsheet telah dibersihkan dan disinkronkan ulang dengan data terkini.\n"
                f"Gunakan menu di bawah untuk memeriksa data:"
            )
        except Exception as e:
            text = f"❌ Gagal menyinkronkan data: {e}"

        if message_id:
            self.bot.edit_message_text(chat_id, message_id, text, reply_markup=self.main_menu_keyboard())
        else:
            self.bot.send_message(chat_id, text, reply_markup=self.main_menu_keyboard())

    # -------------------------------------------------------------
    # Dispatchers
    # -------------------------------------------------------------
    def dispatch_message(self, message: Dict[str, Any]):
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if not chat_id:
            return

        text = message.get("text", "").strip()
        user_from = message.get("from", {})
        first_name = user_from.get("first_name", "Rekan SA")
        username = user_from.get("username", "")

        user_msg_id = message.get("message_id")

        import re
        # Bersihkan mention bot di awal pesan jika ada (misal dari inline query: @IncomeSim_bot)
        if text.startswith("@"):
            text = re.sub(r'^@\w+\s*', '', text).strip()

        # Tidak perlu autentikasi - langsung proses pesan

        # Handle pending user input state (contoh: SIMULATION_BUILDER)
        session = USER_SESSIONS.get(chat_id)
        if session and session.get("state") == "SIMULATION_BUILDER" and not text.startswith("/"):
            curr_q = session.get("data", {}).get("quantities", [0] * 8)
            pos = session.get("data", {}).get("position", "PRO")
            step = session.get("data", {}).get("step", 1)
            msg_id = session.get("data", {}).get("message_id")

            parsed = self.parse_product_quantities(text, current_quantities=curr_q)
            if parsed:
                # Hapus pesan input user agar chat bersih & tidak menumpuk
                if user_msg_id:
                    self.bot.delete_message(chat_id, user_msg_id)

                session["data"]["quantities"] = parsed
                # Re-render builder
                new_text = self.render_simulation_builder_text(pos, parsed, step)
                keyboard = self.simulation_builder_keyboard(pos, step)
                if msg_id:
                    edit_res = self.bot.edit_message_text(chat_id, msg_id, new_text, reply_markup=keyboard)
                    if not edit_res.get("ok"):
                        send_res = self.bot.send_message(chat_id, new_text, reply_markup=keyboard)
                        if send_res.get("ok"):
                            session["data"]["message_id"] = send_res["result"]["message_id"]
                else:
                    send_res = self.bot.send_message(chat_id, new_text, reply_markup=keyboard)
                    if send_res.get("ok"):
                        session["data"]["message_id"] = send_res["result"]["message_id"]
                return
            else:
                # Hapus pesan user yang keliru agar tidak menumpuk
                if user_msg_id:
                    self.bot.delete_message(chat_id, user_msg_id)
                self.bot.send_message(
                    chat_id,
                    "⚠️ Format tidak dikenali atau angka belum diisi.\nContoh pengisian:\n• `[1] - 0`\n• `[2] - 10`\n• `2=10, 3=2`"
                )
                return

        # Slash Commands
        parts = text.split()
        cmd = parts[0].lower() if parts else ""
        if "@" in cmd:
            cmd = cmd.split("@")[0]

        if cmd in ["/start"]:
            self.handle_start(chat_id, first_name)
        elif cmd in ["/help", "/bantuan"]:
            self.handle_help(chat_id)
        elif cmd in ["/info", "/tarif"]:
            self.handle_info(chat_id)
        elif cmd in ["/agen", "/list"]:
            self.handle_agen(chat_id)
        elif cmd in ["/refresh"]:
            self.handle_refresh(chat_id)
        elif cmd in ["/cek"]:
            query = " ".join(parts[1:])
            self.handle_cek(chat_id, query)
        elif cmd in ["/hitung", "/simulasi"]:
            if user_msg_id and not parts[1:]:
                self.bot.delete_message(chat_id, user_msg_id)
            self.handle_quick_hitung_command(chat_id, parts[1:])
        else:
            # Natural input: check if it's a template input or name search
            if not text.startswith("/"):
                # Cek jika user mengirim template [1] - ... secara langsung
                parsed = self.parse_product_quantities(text)
                if parsed and sum(parsed) > 0:
                    # Hapus pesan input user agar tidak menumpuk
                    if user_msg_id:
                        self.bot.delete_message(chat_id, user_msg_id)
                    session = USER_SESSIONS.get(chat_id)
                    pos = session.get("data", {}).get("position", "PRO") if session else "PRO"
                    if not session:
                        USER_SESSIONS[chat_id] = {
                            "state": "SIMULATION_BUILDER",
                            "data": {"position": pos, "quantities": parsed, "step": 1}
                        }
                    else:
                        session["state"] = "SIMULATION_BUILDER"
                        session["data"]["position"] = pos
                        session["data"]["quantities"] = parsed
                    
                    target_mid = session.get("data", {}).get("message_id") if session else None
                    new_text = self.render_simulation_builder_text(pos, parsed, 1)
                    keyboard = self.simulation_builder_keyboard(pos, 1)
                    if target_mid:
                        edit_res = self.bot.edit_message_text(chat_id, target_mid, new_text, reply_markup=keyboard)
                        if not edit_res.get("ok"):
                            res = self.bot.send_message(chat_id, new_text, reply_markup=keyboard)
                            if res.get("ok"):
                                USER_SESSIONS[chat_id]["data"]["message_id"] = res["result"]["message_id"]
                    else:
                        res = self.bot.send_message(chat_id, new_text, reply_markup=keyboard)
                        if res.get("ok"):
                            USER_SESSIONS[chat_id]["data"]["message_id"] = res["result"]["message_id"]
                    return

                agent = self.reader.find_agent(text)
                if agent:
                    self.handle_cek(chat_id, text)
                else:
                    self.bot.send_message(
                        chat_id,
                        f"🤖 Perintah atau nama *'{text}'* tidak dikenali.\n\n"
                        f"Gunakan menu di bawah ini untuk bantuan:",
                        reply_markup=self.main_menu_keyboard()
                    )

    def dispatch_callback_query(self, cb: Dict[str, Any]):
        cb_id = cb.get("id")
        data = cb.get("data", "")
        message = cb.get("message", {})
        chat_id = message.get("chat", {}).get("id")
        message_id = message.get("message_id")

        if not chat_id:
            return

        self.bot.answer_callback_query(cb_id)


        if data == "menu_main":
            self.bot.edit_message_text(
                chat_id,
                message_id,
                "🏠 *Menu Utama Bot Kalkulasi XL SATU*\n\nSilakan pilih menu di bawah ini: 👇",
                reply_markup=self.main_menu_keyboard()
            )
        elif data == "menu_cek":
            self.handle_cek_saya_auto(chat_id, message_id=message_id)
        elif data == "menu_simulasi":
            self.handle_simulasi_start(chat_id, message_id=message_id)
        elif data == "menu_agen":
            self.handle_agen(chat_id, message_id=message_id)
        elif data == "menu_info":
            self.handle_info(chat_id, message_id=message_id)
        elif data == "menu_refresh":
            self.handle_refresh(chat_id, message_id=message_id)
        elif data.startswith("cek_agent_"):
            agent_name = data.replace("cek_agent_", "")
            self.handle_cek(chat_id, agent_name)
        elif data.startswith("sim_pos_"):
            pos = data.replace("sim_pos_", "")
            self.handle_simulasi_select_position(chat_id, pos, message_id=message_id)
        elif data.startswith("sim_quick_"):
            # Format: sim_quick_PRO_12
            parts = data.split("_")
            pos = parts[2]
            units = int(parts[3])
            # Default to Product 2 (FTTH 229k-299k)
            quantities = [0] * 8
            quantities[1] = units
            self.execute_simulation(chat_id, pos, quantities, message_id=message_id)
        elif data.startswith("sim_add_"):
            # Format: sim_add_2
            prod_num = int(data.replace("sim_add_", ""))
            prod_idx = prod_num - 1
            session = USER_SESSIONS.get(chat_id)
            if not session or session.get("state") != "SIMULATION_BUILDER":
                session = {
                    "state": "SIMULATION_BUILDER",
                    "data": {"position": "PRO", "quantities": [0]*8, "step": 1, "message_id": message_id}
                }
                USER_SESSIONS[chat_id] = session

            step = session["data"].get("step", 1)
            quantities = session["data"]["quantities"]
            if 0 <= prod_idx < len(quantities):
                quantities[prod_idx] += step

            pos = session["data"]["position"]
            new_text = self.render_simulation_builder_text(pos, quantities, step)
            keyboard = self.simulation_builder_keyboard(pos, step)
            self.bot.edit_message_text(chat_id, message_id, new_text, reply_markup=keyboard)

        elif data == "sim_step_toggle":
            session = USER_SESSIONS.get(chat_id)
            if session and session.get("state") == "SIMULATION_BUILDER":
                current_step = session["data"].get("step", 1)
                next_step = 5 if current_step == 1 else (10 if current_step == 5 else 1)
                session["data"]["step"] = next_step
                pos = session["data"]["position"]
                quantities = session["data"]["quantities"]
                new_text = self.render_simulation_builder_text(pos, quantities, next_step)
                keyboard = self.simulation_builder_keyboard(pos, next_step)
                self.bot.edit_message_text(chat_id, message_id, new_text, reply_markup=keyboard)

        elif data == "sim_reset":
            session = USER_SESSIONS.get(chat_id)
            if session and session.get("state") == "SIMULATION_BUILDER":
                session["data"]["quantities"] = [0] * 8
                pos = session["data"]["position"]
                step = session["data"].get("step", 1)
                new_text = self.render_simulation_builder_text(pos, session["data"]["quantities"], step)
                keyboard = self.simulation_builder_keyboard(pos, step)
                self.bot.edit_message_text(chat_id, message_id, new_text, reply_markup=keyboard)

        elif data == "sim_copy_template":
            session = USER_SESSIONS.get(chat_id)
            if session and session.get("state") == "SIMULATION_BUILDER":
                pos = session["data"]["position"]
                quantities = session["data"]["quantities"]
                self.send_input_template(chat_id, pos, quantities)

        elif data == "sim_calculate":
            session = USER_SESSIONS.get(chat_id)
            if session and session.get("state") == "SIMULATION_BUILDER":
                pos = session["data"]["position"]
                quantities = session["data"]["quantities"]
                self.execute_simulation(chat_id, pos, quantities, message_id=message_id)

        elif data == "sim_edit_back":
            session = USER_SESSIONS.get(chat_id)
            if session:
                session["state"] = "SIMULATION_BUILDER"
                pos = session["data"]["position"]
                quantities = session["data"]["quantities"]
                step = session["data"].get("step", 1)
                new_text = self.render_simulation_builder_text(pos, quantities, step)
                keyboard = self.simulation_builder_keyboard(pos, step)
                self.bot.edit_message_text(chat_id, message_id, new_text, reply_markup=keyboard)

    # -------------------------------------------------------------
    # Inline Query Handler
    # -------------------------------------------------------------
    def handle_inline_query(self, inline_query: Dict[str, Any]):
        """
        Tangani inline query saat user mengetik @bot [1] - 5 [2] - 10 ...
        Tampilkan preview kalkulasi sebagai hasil inline secara realtime.
        """
        query_id = inline_query.get("id")
        query_text = inline_query.get("query", "").strip()
        from_user = inline_query.get("from", {})

        # Dapatkan posisi SA dari session user jika ada
        user_id = from_user.get("id")
        session = USER_SESSIONS.get(user_id) if user_id else None
        pos = "PRO"
        if session and session.get("data", {}).get("position"):
            pos = session["data"]["position"]

        import re
        # Coba parse posisi jika user mengetik posisi di depan query (opsional)
        pos_match = re.match(r'^(OJT|PRO|ELITE)\b\s*', query_text, re.IGNORECASE)
        if pos_match:
            pos = pos_match.group(1).upper()
            rest = query_text[pos_match.end():]
        else:
            rest = query_text

        # Coba parse quantities dari format [n] - value
        quantities = self.parse_product_quantities(rest)
        if not quantities:
            quantities = [0] * len(PRODUCT_CATALOG)

        total_units = sum(quantities)

        if total_units == 0:
            results = [{
                "type": "article",
                "id": "help",
                "title": f"📋 Ketik Angka Unit ({pos})",
                "description": "Ketik jumlah unit setelah tanda '-' pada produk yang terjual",
                "input_message_content": {
                    "message_text": (
                        f"📋 *Template Input Produk ({pos}):*\n\n"
                        f"Ketik angka setelah tanda `-` pada setiap produk yang terjual.\n\n"
                        f"*Contoh:*\n"
                        f"`[1] - 0`\n"
                        f"`[2] - 10`\n"
                        f"`[3] - 2`\n\n"
                        f"Gunakan menu /simulasi untuk kalkulator interaktif."
                    ),
                    "parse_mode": "Markdown"
                }
            }]
            self.bot.answer_inline_query(query_id, results)
            return

        # Hitung preview kalkulasi secara realtime
        try:
            res = self.calculator.calculate(
                position=pos,
                product_quantities=quantities,
                agent_name=f"Simulasi {pos}"
            )
            from calculator import format_rupiah
            preview_title = f"{pos} | {total_units} unit → THP: {format_rupiah(res['take_home_pay'])}"
            preview_desc = (
                f"Gaji Pokok: {format_rupiah(res['basic_salary'])} | "
                f"Insentif: {format_rupiah(res['total_insentif'])}"
            )
            message_text = self.calculator.format_telegram_report(res)
        except Exception:
            preview_title = f"{pos} | {total_units} unit (belum lengkap)"
            preview_desc = "Lengkapi angka pada semua produk"
            message_text = f"⚠️ Tidak dapat menghitung. Pastikan format benar: `PRO [1]-0 [2]-10 ...`"

        # Buat pesan yang akan dikirim ke chat jika user memilih hasil ini
        results = [{
            "type": "article",
            "id": "calc_result",
            "title": preview_title,
            "description": preview_desc,
            "input_message_content": {
                "message_text": message_text,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True
            }
        }]
        self.bot.answer_inline_query(query_id, results)

    # -------------------------------------------------------------
    # Main Polling Loop
    # -------------------------------------------------------------
    def run(self):
        logger.info("Memulai verifikasi bot token...")
        me_info = self.bot.get_me()
        if not me_info.get("ok"):
            logger.error("Gagal terhubung ke Telegram API: %s", me_info)
            sys.exit(1)

        bot_username = me_info.get("result", {}).get("username", "Unknown")
        bot_name = me_info.get("result", {}).get("first_name", "Bot")
        logger.info("Bot Aktif: %s (@%s)", bot_name, bot_username)
        logger.info("Mendengarkan pesan Telegram (Long Polling aktif)...")

        # Initial sheet warm up
        try:
            records = self.reader.get_calculation_records()
            logger.info("Koneksi Google Spreadsheet berhasil. Membaca %d agen aktif.", len(records))
        except Exception as e:
            logger.warning("Peringatan inisialisasi sheet: %s", e)

        offset = 0
        conflict_count = 0
        while self.running:
            try:
                updates = self.bot.get_updates(offset=offset, timeout=20)
                conflict_count = 0  # reset on success
                for update in updates:
                    offset = update["update_id"] + 1

                    if "message" in update:
                        self.dispatch_message(update["message"])
                    elif "callback_query" in update:
                        self.dispatch_callback_query(update["callback_query"])
                    elif "inline_query" in update:
                        self.handle_inline_query(update["inline_query"])

            except KeyboardInterrupt:
                logger.info("Bot dihentikan oleh user.")
                self.running = False
                break
            except Exception as e:
                err_str = str(e)
                if "409" in err_str or "Conflict" in err_str:
                    conflict_count += 1
                    wait = min(30, 5 * conflict_count)
                    logger.warning("409 Conflict: instance lain masih berjalan. Tunggu %ds... (percobaan %d)", wait, conflict_count)
                    if conflict_count >= 6:
                        logger.error("Terlalu banyak konflik. Hentikan semua instance lain lalu restart bot ini.")
                        self.running = False
                        break
                    time.sleep(wait)
                else:
                    logger.error("Polling error: %s", e)
                    time.sleep(2)


def main():
    acquire_lock()  # Cegah instance ganda
    start_health_server()  # Render Web Service health check
    bot_client = TelegramBotClient(TELEGRAM_BOT_TOKEN)
    app = SalaryBotApp(bot_client)

    def sig_handler(signum, frame):
        logger.info("Menerima sinyal terminasi (%s), keluar...", signum)
        app.running = False
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    app.run()


if __name__ == "__main__":
    main()
