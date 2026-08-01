"""Per-country dial plan for SIP UP."""

from app.services.telephony.dial_plan import infer_country_code, resolve_dial_plan


def test_infer_country_code_priority_countries():
    assert infer_country_code("+21656340093") == "216"
    assert infer_country_code("+96512345678") == "965"
    assert infer_country_code("+393331234567") == "39"
    assert infer_country_code("+33123456789") == "33"
    assert infer_country_code("+15551234567") == "1"


def test_sipup_tunisia_uses_national():
    fmt, cc = resolve_dial_plan(
        "+21656340093",
        "sip_up",
        fallback_dial_format="e164_no_plus",
        fallback_country_code="216",
    )
    assert fmt == "national"
    assert cc == "216"


def test_sipup_us_uses_e164_no_plus():
    fmt, _cc = resolve_dial_plan(
        "+15551234567",
        "sip_up",
        fallback_dial_format="national",
        fallback_country_code="216",
    )
    assert fmt == "e164_no_plus"


def test_sipup_kuwait_uses_national():
    fmt, cc = resolve_dial_plan(
        "+96512345678",
        "sip_up",
        fallback_dial_format="e164_no_plus",
        fallback_country_code="216",
    )
    assert fmt == "national"
    assert cc == "965"


def test_sipup_france_uses_e164_no_plus():
    fmt, cc = resolve_dial_plan(
        "+33745068750",
        "sip_up",
        fallback_dial_format="national",
        fallback_country_code="216",
    )
    assert fmt == "e164_no_plus"
    assert cc == "33"


def test_sipup_germany_uses_e164_no_plus():
    fmt, cc = resolve_dial_plan(
        "+491631110924",
        "sip_up",
        fallback_dial_format="national",
        fallback_country_code="216",
    )
    assert fmt == "e164_no_plus"
    assert cc == "49"
