"""Per-destination dial-string rules for the SIP UP trunk."""

from __future__ import annotations

from typing import Literal

ProviderKind = Literal["sip_up"]

# Longest-prefix first when matching E.164 country codes.
_COUNTRY_PREFIXES: tuple[tuple[str, str], ...] = (
    ("216", "TN"),
    ("965", "KW"),
    ("49", "DE"),
    ("39", "IT"),
    ("33", "FR"),
    ("1", "NANP"),
)

# Verified / expected trunk formats (override env defaults per destination).
SIPUP_DIAL_FORMAT_BY_CC: dict[str, str] = {
    "216": "national",  # 56340093 — SIP UP rejects 21656340093 (403)
    "965": "national",
    "1": "e164_no_plus",  # 7373946144 → 503; SIP UP wants 17373946144
    "39": "national",
    # SIP UP rejects FR national (0745…) / cause 21; DE succeeds as full intl digits.
    "33": "e164_no_plus",
    "49": "e164_no_plus",
}

# Countries whose national form uses a leading trunk ``0`` that must NOT appear in E.164.
# Users often paste ``+330745…`` instead of ``+33745…``; strip that trunk ``0`` after the CC.
_E164_TRUNK0_COUNTRY_CODES: tuple[str, ...] = ("33", "39")


def strip_national_trunk_zero(e164_digits: str) -> str:
    """Remove an erroneous national trunk ``0`` after the country code in E.164 digits."""
    core = _digits_only(e164_digits)
    for cc in _E164_TRUNK0_COUNTRY_CODES:
        # e.g. 330745068750 → 33745068750 (FR mobile with trunk 0 left in)
        if core.startswith(cc + "0") and len(core) > len(cc) + 1:
            nxt = core[len(cc) + 1]
            if nxt.isdigit() and nxt != "0":
                return cc + core[len(cc) + 1 :]
    return core


def _digits_only(value: str) -> str:
    return "".join(ch for ch in str(value or "") if ch.isdigit())


def infer_country_code(phone_number: str) -> str:
    """Return leading country code digits from +E.164 input, or empty if unknown."""
    raw = str(phone_number or "").strip()
    digits = _digits_only(raw)
    if raw.startswith("+"):
        core = digits
    elif digits.startswith("00") and len(digits) > 4:
        core = digits[2:]
    else:
        core = digits
    for cc, _label in _COUNTRY_PREFIXES:
        if core.startswith(cc):
            return cc
    return ""


def resolve_dial_plan(
    phone_number: str,
    provider: ProviderKind,
    *,
    fallback_dial_format: str,
    fallback_country_code: str,
) -> tuple[str, str]:
    """Return ``(dial_format, default_country_code)`` for this destination."""
    del provider  # SIP UP only
    cc = infer_country_code(phone_number)
    dial_format = SIPUP_DIAL_FORMAT_BY_CC.get(cc, fallback_dial_format)
    country_code = cc or fallback_country_code
    return dial_format, country_code
