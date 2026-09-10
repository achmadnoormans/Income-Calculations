from bot import TelegramBotClient
from config import TELEGRAM_BOT_TOKEN
from sheet_reader import GoogleSheetReader
from calculator import SalaryCalculator

def test_integration():
    client = TelegramBotClient(TELEGRAM_BOT_TOKEN)
    me = client.get_me()
    print("Bot getMe:", me)
    assert me.get("ok") is True, f"getMe failed: {me}"
    print(f"Bot connected: @{me['result']['username']} ({me['result']['first_name']})")

    reader = GoogleSheetReader()
    records = reader.get_calculation_records()
    print(f"Sheet records loaded: {len(records)}")
    assert len(records) > 0, "No records found in sheet"

    calc = SalaryCalculator()
    res = calc.calculate(
        position=records[0]["position"],
        product_quantities=records[0]["product_quantities"],
        agent_name=records[0]["name"]
    )
    print("Calculation verified:")
    print("Agent:", res["name"])
    print("Total Units:", res["total_units"])
    print("THP:", res["take_home_pay"])
    assert res["take_home_pay"] == 6470000.0, f"THP mismatch: {res['take_home_pay']}"
    print("ALL TESTS PASSED!")

if __name__ == "__main__":
    test_integration()
