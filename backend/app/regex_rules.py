"""Basic open-source regex rules for common structured PII fields.

Community Edition provides standard format-level detection for 5 common types:
- PHONE: Chinese mobile numbers & standard landline numbers
- EMAIL: Email addresses
- ID_CARD: 18-digit Chinese Resident Identity Card (with GB 11643 checksum)
- BANK_ACCOUNT: 16–19 digit bank card numbers (with Luhn checksum)
- IP_ADDRESS: Standard IPv4 addresses (0–255 per octet)

Complex domain rules (case numbers, USCC, lawyer license, securities codes,
monetary amounts with Chinese numerals, policy numbers, context arbitration)
remain exclusive to the commercial Pro edition.
"""
from __future__ import annotations

import re

from .models import EntitySpan

_MOBILE_RE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE_RE = re.compile(r"(?<!\d)0\d{2,3}-\d{7,8}(?!\d)")
_EMAIL_RE = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])")
_ID_CARD_RE = re.compile(r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)")
_BANK_CARD_RE = re.compile(r"(?<!\d)(?:\d[ -]?){15,18}\d(?!\d)")
_IPV4_RE = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")

_ID_WEIGHTS = (7, 9, 10, 5, 8, 4, 2, 1, 6, 3, 7, 9, 10, 5, 8, 4, 2)
_ID_CHECKSUM = "10X98765432"


def _valid_id_card(value: str) -> bool:
    if len(value) != 18:
        return False
    try:
        total = sum(int(ch) * w for ch, w in zip(value[:17], _ID_WEIGHTS))
    except ValueError:
        return False
    expected = _ID_CHECKSUM[total % 11]
    return value[17].upper() == expected


def _valid_luhn(digits: str) -> bool:
    if not (16 <= len(digits) <= 19) or not digits.isdigit():
        return False
    if len(set(digits)) == 1:
        return False
    total = 0
    reverse = digits[::-1]
    for idx, ch in enumerate(reverse):
        n = int(ch)
        if idx % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _valid_ipv4(value: str) -> bool:
    parts = value.split(".")
    if len(parts) != 4:
        return False
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part.startswith("0")):
            return False
        if not 0 <= int(part) <= 255:
            return False
    return True


def detect_basic_regex(text: str) -> list[EntitySpan]:
    """Detect basic structured PII entities using standard format & checksum rules."""
    if not text:
        return []

    spans: list[EntitySpan] = []

    for m in _ID_CARD_RE.finditer(text):
        val = m.group(0)
        if _valid_id_card(val):
            spans.append(
                EntitySpan(
                    id="REGEX_0000",
                    start=m.start(),
                    end=m.end(),
                    original_text=val,
                    entity_type="ID_CARD",
                    confidence=0.99,
                    source="basic-regex",
                )
            )

    for m in _MOBILE_RE.finditer(text):
        spans.append(
            EntitySpan(
                id="REGEX_0000",
                start=m.start(),
                end=m.end(),
                original_text=m.group(0),
                entity_type="PHONE",
                confidence=0.98,
                source="basic-regex",
            )
        )

    for m in _LANDLINE_RE.finditer(text):
        spans.append(
            EntitySpan(
                id="REGEX_0000",
                start=m.start(),
                end=m.end(),
                original_text=m.group(0),
                entity_type="PHONE",
                confidence=0.96,
                source="basic-regex",
            )
        )

    for m in _EMAIL_RE.finditer(text):
        spans.append(
            EntitySpan(
                id="REGEX_0000",
                start=m.start(),
                end=m.end(),
                original_text=m.group(0),
                entity_type="EMAIL",
                confidence=0.99,
                source="basic-regex",
            )
        )

    for m in _BANK_CARD_RE.finditer(text):
        raw = m.group(0)
        digits = re.sub(r"[ -]", "", raw)
        if _valid_luhn(digits):
            spans.append(
                EntitySpan(
                    id="REGEX_0000",
                    start=m.start(),
                    end=m.end(),
                    original_text=raw,
                    entity_type="BANK_ACCOUNT",
                    confidence=0.95,
                    source="basic-regex",
                )
            )

    for m in _IPV4_RE.finditer(text):
        val = m.group(0)
        if _valid_ipv4(val):
            spans.append(
                EntitySpan(
                    id="REGEX_0000",
                    start=m.start(),
                    end=m.end(),
                    original_text=val,
                    entity_type="IP_ADDRESS",
                    confidence=0.97,
                    source="basic-regex",
                )
            )

    return spans
