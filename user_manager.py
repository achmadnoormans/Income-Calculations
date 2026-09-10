import sqlite3
import os
import re
from datetime import datetime
from typing import Optional, Dict, Any, List


def clean_phone_number(raw_phone: str) -> Optional[str]:
    """
    Membersihkan dan memvalidasi nomor telepon Indonesia / internasional.
    Menerima format seperti:
    - 081234567890 -> +6281234567890
    - 6281234567890 -> +6281234567890
    - +6281234567890 -> +6281234567890
    - 0812-3456-7890 -> +6281234567890
    Mengembalikan None jika format tidak valid.
    """
    if not raw_phone:
        return None

    # Hapus spasi, strip, tanda kurung, titik
    cleaned = re.sub(r"[\s\-\(\)\.]", "", str(raw_phone).strip())

    # Validasi hanya boleh ada digit dan opsional '+' di awal
    if not re.match(r"^\+?\d{8,16}$", cleaned):
        return None

    # Normalisasi awalan Indonesia
    if cleaned.startswith("+62"):
        normalized = cleaned
    elif cleaned.startswith("62"):
        normalized = "+" + cleaned
    elif cleaned.startswith("08"):
        normalized = "+62" + cleaned[1:]
    elif cleaned.startswith("0"):
        # Kasus nomor lokal lain dengan awalan 0
        normalized = "+62" + cleaned[1:]
    elif cleaned.startswith("+"):
        normalized = cleaned
    else:
        # Jika hanya angka diawali 8xx
        if cleaned.startswith("8"):
            normalized = "+62" + cleaned
        else:
            normalized = "+" + cleaned

    # Cek panjang digit setelah '+' (umumnya 10-15 digit)
    digits_only = re.sub(r"\D", "", normalized)
    if len(digits_only) < 9 or len(digits_only) > 16:
        return None

    return normalized


class UserManager:
    """Mengelola penyimpanan data pengguna bot Telegram menggunakan SQLite."""

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            self.db_path = os.path.join(base_dir, "users.db")
        else:
            self.db_path = db_path
        self.init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self):
        """Membuat tabel users jika belum tersedia."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    full_name TEXT NOT NULL,
                    phone_number TEXT NOT NULL,
                    username TEXT DEFAULT '',
                    registered_at TEXT NOT NULL,
                    last_active_at TEXT NOT NULL,
                    is_authenticated INTEGER DEFAULT 1
                )
            """)
            conn.commit()

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Mendapatkan data pengguna berdasarkan Telegram ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def is_authenticated(self, telegram_id: int) -> bool:
        """Memeriksa apakah pengguna telah terdaftar dan berstatus aktif login."""
        user = self.get_user(telegram_id)
        if user and user.get("is_authenticated") == 1:
            return True
        return False

    def register_or_update_user(self,
                                telegram_id: int,
                                full_name: str,
                                phone_number: str,
                                username: str = "") -> Dict[str, Any]:
        """Mendaftarkan atau memperbarui data akun pengguna dan mengaktifkan sesi login."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cleaned_phone = clean_phone_number(phone_number) or phone_number.strip()
        full_name_clean = full_name.strip()
        username_clean = (username or "").strip().lstrip("@")

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO users (telegram_id, full_name, phone_number, username, registered_at, last_active_at, is_authenticated)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    full_name = excluded.full_name,
                    phone_number = excluded.phone_number,
                    username = excluded.username,
                    last_active_at = excluded.last_active_at,
                    is_authenticated = 1
            """, (telegram_id, full_name_clean, cleaned_phone, username_clean, now_str, now_str))
            conn.commit()

        return self.get_user(telegram_id) or {}

    def update_last_active(self, telegram_id: int):
        """Memperbarui timestamp aktivitas terakhir."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET last_active_at = ? WHERE telegram_id = ?", (now_str, telegram_id))
            conn.commit()

    def logout_user(self, telegram_id: int) -> bool:
        """Menonaktifkan sesi login pengguna."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE users SET is_authenticated = 0 WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return cursor.rowcount > 0

    def login_user(self, telegram_id: int) -> bool:
        """Mengaktifkan kembali sesi login pengguna yang sudah terdaftar."""
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET is_authenticated = 1, last_active_at = ? WHERE telegram_id = ?",
                (now_str, telegram_id)
            )
            conn.commit()
            return cursor.rowcount > 0

    def delete_user(self, telegram_id: int) -> bool:
        """Menghapus akun pengguna dari database."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE telegram_id = ?", (telegram_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_all_users(self) -> List[Dict[str, Any]]:
        """Mendapatkan daftar semua pengguna terdaftar."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users ORDER BY registered_at DESC")
            rows = cursor.fetchall()
            return [dict(r) for r in rows]
