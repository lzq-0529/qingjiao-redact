from __future__ import annotations

import unittest

from app.regex_rules import detect_basic_regex


class BasicRegexRulesTests(unittest.TestCase):
    def test_detects_phone_email_id_bank_and_ip(self) -> None:
        # Synthetic valid checksum ID (110105199003070016 -> verify checksum dynamically)
        weights = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
        body17 = "11010519900307001"
        check = "10X98765432"[sum(int(c) * w for c, w in zip(body17, weights)) % 11]
        valid_id = body17 + check

        # Synthetic valid Luhn 16-digit card
        card_prefix = "622202000000000"
        digits = [int(c) for c in card_prefix]
        # compute check digit for 16 digits
        rev = digits[::-1]
        total = 0
        for idx, d in enumerate(rev):
            val = d * 2 if idx % 2 == 0 else d
            if val > 9:
                val -= 9
            total += val
        luhn_check = (10 - (total % 10)) % 10
        valid_card = card_prefix + str(luhn_check)

        text = (
            f"联系人电话 13900001234，座机 010-88886666，邮箱 demo@example.com，"
            f"证件号 {valid_id}，卡号 {valid_card}，内网主机 192.168.10.25。"
        )
        items = detect_basic_regex(text)
        by_type = {i.entity_type: i.original_text for i in items}
        self.assertEqual(by_type["EMAIL"], "demo@example.com")
        self.assertEqual(by_type["ID_CARD"], valid_id)
        self.assertEqual(by_type["BANK_ACCOUNT"], valid_card)
        self.assertEqual(by_type["IP_ADDRESS"], "192.168.10.25")
        phones = {i.original_text for i in items if i.entity_type == "PHONE"}
        self.assertEqual(phones, {"13900001234", "010-88886666"})

    def test_rejects_invalid_checksums_and_out_of_range_ip(self) -> None:
        text = "无效身份证 110105199003070010，无效IP 999.168.1.1，全同数字 1111111111111111。"
        items = detect_basic_regex(text)
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
