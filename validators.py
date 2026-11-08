"""Small input-validation helpers. All raise ValueError with a user-facing message."""
import re
from decimal import Decimal, InvalidOperation

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def text(raw, label, max_len, required=True):
    value = (raw or "").strip()
    if not value:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    if len(value) > max_len:
        raise ValueError(f"{label} must be at most {max_len} characters.")
    return value


def email(raw, label="Email"):
    value = text(raw, label, 100)
    if not EMAIL_RE.match(value):
        raise ValueError(f"{label} must be a valid email address.")
    return value.lower()


def integer(raw, label, minimum=None, maximum=None, required=True):
    value = (raw or "").strip()
    if not value:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        number = int(value)
    except ValueError:
        raise ValueError(f"{label} must be a whole number.")
    if minimum is not None and number < minimum:
        raise ValueError(f"{label} must be at least {minimum}.")
    if maximum is not None and number > maximum:
        raise ValueError(f"{label} must be at most {maximum}.")
    return number


def choice_id(raw, label):
    """A <select> that holds a database ID."""
    value = (raw or "").strip()
    if not value:
        raise ValueError(f"Select a {label.lower()}.")
    try:
        return int(value)
    except ValueError:
        raise ValueError(f"Select a valid {label.lower()}.")


def mark(raw, label="Mark", required=True):
    """A mark/percentage 0-100 with at most two decimals."""
    value = (raw or "").strip()
    if not value:
        if required:
            raise ValueError(f"{label} is required.")
        return None
    try:
        number = Decimal(value)
    except InvalidOperation:
        raise ValueError(f"{label} must be a number.")
    if not number.is_finite():
        raise ValueError(f"{label} must be a number.")
    if number < 0 or number > 100:
        raise ValueError(f"{label} must be between 0 and 100.")
    if number != number.quantize(Decimal("0.01")):
        raise ValueError(f"{label} can have at most two decimal places.")
    return number
