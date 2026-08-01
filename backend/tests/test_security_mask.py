from app.security import mask_digits_in_text


def test_mask_digits_keeps_only_last_two_of_each_run():
    assert mask_digits_in_text("code 123456 done") == "code ****56 done"
    assert mask_digits_in_text("+21656340093") == "+*********93"
    assert mask_digits_in_text("12") == "12"
    assert mask_digits_in_text("1") == "1"
    assert mask_digits_in_text("") == ""
    assert mask_digits_in_text(None) == ""


def test_mask_digits_handles_multiple_runs_independently():
    assert mask_digits_in_text("from 555111 to 999888") == "from ****11 to ****88"


def test_mask_digits_leaves_non_digit_text_untouched():
    assert mask_digits_in_text("Verification declined. Goodbye.") == "Verification declined. Goodbye."
