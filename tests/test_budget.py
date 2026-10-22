"""Synthetic fixtures test calculation boundaries; they are not travel evidence."""
import copy
from decimal import Decimal
import unittest
from travel import build_report, commands, money, validate

REQUEST = {"origin": "上海", "destination": "三亚", "departure": "2026-11-07", "return": "2026-11-10", "adults": 2, "rooms": 1, "budget": 8000, "hotelMaxNight": 900, "estimates": {"food": 1200}}


def evidence():
    records = {}
    for key, price in (("outbound", "¥900.10"), ("return", "¥800.20"), ("hotel", "¥500.30")):
        item = {"name": "测试酒店", "price": price} if key == "hotel" else {"adultPrice": price}
        records[key] = {"argv": commands(REQUEST)[key], "exitCode": 0, "response": {"status": 0, "data": {"itemList": [item]}}}
    return records


class BudgetTests(unittest.TestCase):
    def test_currency_and_uncertain_prices(self):
        self.assertEqual(money("¥1,234.56"), Decimal("1234.56"))
        for price in (None, True, "面议", "¥500起", "400-600", "USD 99", "NaN", -1):
            self.assertIsNone(money(price))

    def test_people_and_nights_are_multiplied_once(self):
        report = build_report(REQUEST, evidence())
        self.assertEqual(report["knownListSubtotal"], "4901.50")
        self.assertEqual(report["referenceTotal"], "6101.50")
        self.assertIn("尚待核验", report["conclusion"])

    def test_failed_return_never_becomes_zero_or_within_budget(self):
        records = evidence()
        records["return"].update(exitCode=1, response=None)
        report = build_report(REQUEST, records)
        self.assertIsNone(report["referenceTotal"])
        self.assertIsNone(report["ledger"][1]["amount"])

    def test_observed_ticket_price_schema_keeps_unit_uncertain(self):
        records = evidence()
        records["outbound"]["response"]["data"]["itemList"] = [{"ticketPrice": "856.00"}]
        report = build_report(REQUEST, records)
        self.assertEqual(report["ledger"][0]["amount"], "1712.00")
        self.assertIn("去程 ticketPrice 的单人及人民币口径", report["unknown"])

    def test_business_error_and_different_request_are_not_quotes(self):
        records = evidence()
        records["outbound"]["response"]["status"] = 429
        records["hotel"]["argv"] = ["different", "dates"]
        report = build_report(REQUEST, records)
        self.assertEqual(report["groups"]["outbound"]["status"], "unavailable")
        self.assertEqual(report["groups"]["hotel"]["status"], "unavailable")

    def test_invalid_dates_and_headcounts(self):
        for changes in ({"return": "2026-11-06"}, {"adults": 0}, {"rooms": 1.5}):
            request = copy.deepcopy(REQUEST)
            request.update(changes)
            with self.assertRaises(ValueError):
                validate(request)


if __name__ == '__main__':
    unittest.main()
