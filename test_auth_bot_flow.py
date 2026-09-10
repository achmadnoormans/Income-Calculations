import os
import unittest
from bot import SalaryBotApp, USER_SESSIONS
from user_manager import UserManager


class MockBotClient:
    def __init__(self):
        self.sent_messages = []
        self.edited_messages = []
        self.answered_callbacks = []

    def send_message(self, chat_id, text, reply_markup=None, parse_mode="Markdown"):
        msg = {
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "parse_mode": parse_mode
        }
        self.sent_messages.append(msg)
        return {"ok": True, "result": {"message_id": len(self.sent_messages)}}

    def edit_message_text(self, chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
        msg = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
            "reply_markup": reply_markup
        }
        self.edited_messages.append(msg)
        return {"ok": True, "result": msg}

    def answer_callback_query(self, callback_query_id, text=None):
        self.answered_callbacks.append({"id": callback_query_id, "text": text})


class TestBotAuthFlow(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_bot_users.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        USER_SESSIONS.clear()
        self.mock_client = MockBotClient()
        self.app = SalaryBotApp(self.mock_client, db_path=self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        USER_SESSIONS.clear()

    def test_complete_registration_and_usage_flow(self):
        chat_id = 999111
        user_from = {"first_name": "Noorman", "username": "noorman_sa"}

        # 1. Unregistered user sends /start
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "/start"
        })

        self.assertFalse(self.app.user_manager.is_authenticated(chat_id))
        self.assertEqual(USER_SESSIONS.get(chat_id, {}).get("state"), "AUTH_WAITING_NAME")
        last_msg = self.mock_client.sent_messages[-1]
        self.assertIn("Langkah 1/2", last_msg["text"])
        self.assertIn("Nama Lengkap", last_msg["text"])

        # 2. Unregistered user tries sending other commands (e.g. /simulasi or /cek)
        # It should still prompt them to finish entering name
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "N"  # Too short
        })
        self.assertIn("terlalu pendek", self.mock_client.sent_messages[-1]["text"])

        # 3. User sends valid name
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "Noorman Pratama"
        })
        self.assertEqual(USER_SESSIONS.get(chat_id, {}).get("state"), "AUTH_WAITING_PHONE")
        last_msg = self.mock_client.sent_messages[-1]
        self.assertIn("Langkah 2/2", last_msg["text"])
        self.assertIn("Nomor HP", last_msg["text"])
        # Verify reply markup has contact request button
        self.assertIn("keyboard", last_msg["reply_markup"])
        self.assertTrue(last_msg["reply_markup"]["keyboard"][0][0]["request_contact"])

        # 4. User inputs invalid phone number
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "bukan_nomor"
        })
        self.assertIn("tidak valid", self.mock_client.sent_messages[-1]["text"])
        self.assertFalse(self.app.user_manager.is_authenticated(chat_id))

        # 5. User sends valid phone number manually
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "081234567890"
        })
        self.assertTrue(self.app.user_manager.is_authenticated(chat_id))
        user = self.app.user_manager.get_user(chat_id)
        self.assertEqual(user["full_name"], "Noorman Pratama")
        self.assertEqual(user["phone_number"], "+6281234567890")

        # Verify success message and main menu
        success_msg = self.mock_client.sent_messages[-2]
        self.assertIn("Login & Verifikasi Berhasil", success_msg["text"])
        menu_msg = self.mock_client.sent_messages[-1]
        self.assertIn("Noorman Pratama", menu_msg["text"])
        self.assertIn("+6281234567890", menu_msg["text"])

        # 6. User opens profile
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "/profil"
        })
        profile_msg = self.mock_client.sent_messages[-1]
        self.assertIn("PROFIL PENGGUNA TERDAFTAR", profile_msg["text"])
        self.assertIn("Noorman Pratama", profile_msg["text"])

        # 7. Auto check salary for logged-in user ("Noorman Pratama" matches "Noorman" in sheet)
        self.app.dispatch_callback_query({
            "id": "cb_cek_1",
            "message": {"chat": {"id": chat_id}, "message_id": 10},
            "data": "menu_cek"
        })
        cek_msg = self.mock_client.sent_messages[-1]
        self.assertIn("SLIP ESTIMASI GAJI & INSENTIF", cek_msg["text"])
        self.assertIn("Noorman", cek_msg["text"])

        # 8. User logs out
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "/logout"
        })
        self.assertFalse(self.app.user_manager.is_authenticated(chat_id))
        logout_msg = self.mock_client.sent_messages[-1]
        self.assertIn("Logout", logout_msg["text"])

        # 9. Next interaction prompts re-login
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "/start"
        })
        relogin_prompt = self.mock_client.sent_messages[-1]
        self.assertIn("Masuk sebagai Noorman Pratama", str(relogin_prompt["reply_markup"]))

    def test_contact_sharing_flow(self):
        chat_id = 888222
        user_from = {"first_name": "Budi", "username": "budi_xl"}

        # Start auth
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "/start"
        })

        # Name
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "text": "Budi Santoso"
        })

        # Contact sharing via Telegram contact payload
        self.app.dispatch_message({
            "chat": {"id": chat_id},
            "from": user_from,
            "contact": {
                "phone_number": "+6281987654321",
                "first_name": "Budi",
                "last_name": "Santoso"
            }
        })

        self.assertTrue(self.app.user_manager.is_authenticated(chat_id))
        user = self.app.user_manager.get_user(chat_id)
        self.assertEqual(user["full_name"], "Budi Santoso")
        self.assertEqual(user["phone_number"], "+6281987654321")


if __name__ == "__main__":
    unittest.main()
