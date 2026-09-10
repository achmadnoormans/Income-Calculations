import unittest
import os
from user_manager import UserManager, clean_phone_number


class TestUserManager(unittest.TestCase):
    def setUp(self):
        self.test_db = "test_users.db"
        if os.path.exists(self.test_db):
            os.remove(self.test_db)
        self.manager = UserManager(db_path=self.test_db)

    def tearDown(self):
        if os.path.exists(self.test_db):
            os.remove(self.test_db)

    def test_phone_number_cleaning(self):
        # Format umum Indonesia
        self.assertEqual(clean_phone_number("08123456789"), "+628123456789")
        self.assertEqual(clean_phone_number("6281234567890"), "+6281234567890")
        self.assertEqual(clean_phone_number("+6281234567890"), "+6281234567890")
        self.assertEqual(clean_phone_number("0812-3456-7890"), "+6281234567890")
        self.assertEqual(clean_phone_number("0812 3456 7890"), "+6281234567890")
        self.assertEqual(clean_phone_number("(+62) 812-3456-7890"), "+6281234567890")

        # Format tidak valid
        self.assertIsNone(clean_phone_number("abcde"))
        self.assertIsNone(clean_phone_number("123"))  # terlalu pendek
        self.assertIsNone(clean_phone_number("08123456789012345678"))  # terlalu panjang
        self.assertIsNone(clean_phone_number(""))

    def test_registration_and_authentication(self):
        telegram_id = 987654321
        full_name = "Ahmad Noorman"
        phone = "081234567890"
        username = "ahmad_noorman"

        # Belum terdaftar
        self.assertFalse(self.manager.is_authenticated(telegram_id))
        self.assertIsNone(self.manager.get_user(telegram_id))

        # Registrasi
        user = self.manager.register_or_update_user(telegram_id, full_name, phone, username)
        self.assertIsNotNone(user)
        self.assertEqual(user["telegram_id"], telegram_id)
        self.assertEqual(user["full_name"], "Ahmad Noorman")
        self.assertEqual(user["phone_number"], "+6281234567890")
        self.assertEqual(user["username"], "ahmad_noorman")
        self.assertEqual(user["is_authenticated"], 1)

        # Status terotentikasi
        self.assertTrue(self.manager.is_authenticated(telegram_id))

        # Logout
        self.assertTrue(self.manager.logout_user(telegram_id))
        self.assertFalse(self.manager.is_authenticated(telegram_id))

        # Login kembali
        self.assertTrue(self.manager.login_user(telegram_id))
        self.assertTrue(self.manager.is_authenticated(telegram_id))

    def test_update_existing_user(self):
        telegram_id = 111222333
        self.manager.register_or_update_user(telegram_id, "User Lama", "08111111111")
        
        # Update dengan nama dan nomor baru
        updated = self.manager.register_or_update_user(telegram_id, "User Baru", "08222222222")
        self.assertEqual(updated["full_name"], "User Baru")
        self.assertEqual(updated["phone_number"], "+628222222222")
        self.assertTrue(self.manager.is_authenticated(telegram_id))


if __name__ == "__main__":
    unittest.main()
