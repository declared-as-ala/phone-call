import secrets
import string

from ..security import hash_verification_code, verify_verification_code


def generate_six_digit_code() -> str:
    digits = string.digits
    return "".join(secrets.choice(digits) for _ in range(6))


def generate_eight_digit_code() -> str:
    """Backward-compatible name; delegates to student-card length."""
    return generate_student_card_demo_code()


def generate_student_card_demo_code(digit_count: int = 6) -> str:
    """Local dev demo keypad entry (default 6 digits; valid lengths are 4, 6, 8, or 10)."""
    digits = string.digits
    n = max(1, min(int(digit_count), 32))
    return "".join(secrets.choice(digits) for _ in range(n))


def hash_code_for_storage(plain_code: str) -> str:
    return hash_verification_code(plain_code)


def codes_match(plain_code: str, stored_hash: str) -> bool:
    return verify_verification_code(plain_code, stored_hash)
