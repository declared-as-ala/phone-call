"""Normalize dialed numbers per destination country (SIP UP)."""

from app.services.telephony.sip_up_ari_provider import normalize_phone_for_dial
from app.services.telephony.dial_plan import resolve_dial_plan


def _dial(phone: str) -> str:
    fmt, cc = resolve_dial_plan(
        phone,
        "sip_up",
        fallback_dial_format="national",
        fallback_country_code="216",
    )
    return normalize_phone_for_dial(
        phone,
        dial_format=fmt,
        default_country_code=cc,
    )


def test_sipup_tunisia_dials_national():
    assert _dial("+21656340093") == "56340093"


def test_sipup_us_dials_e164_no_plus():
    assert _dial("+15551234567") == "15551234567"


def test_sipup_us_local_mobile():
    assert _dial("+17373946144") == "17373946144"


def test_sipup_kuwait_dials_national():
    assert _dial("+96512345678") == "12345678"


def test_sipup_italy_dials_national():
    assert _dial("+393331234567") == "3331234567"


def test_sipup_france_dials_e164_no_plus():
    # Correct E.164 (no national trunk 0 after +33).
    assert _dial("+33745068750") == "33745068750"


def test_sipup_france_strips_erroneous_trunk_zero():
    # Users often paste +33 + 0745…; SIP UP needs 33745068750 (worked for DE as full intl).
    assert _dial("+330745068750") == "33745068750"


def test_sipup_germany_dials_e164_no_plus():
    assert _dial("+491631110924") == "491631110924"


def test_sipup_canada_dials_e164_no_plus():
    assert _dial("+14165551234") == "14165551234"
