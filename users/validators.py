import re

from django.core.exceptions import ValidationError


def validate_password_complexity(value):
    """Валидация сложности пароля"""
    errors = []

    if len(value) < 8:
        errors.append("Пароль должен содержать минимум 8 символов")

    if not re.search(r"[A-Z]", value):
        errors.append("Пароль должен содержать хотя бы одну заглавную букву")

    if not re.search(r"[a-z]", value):
        errors.append("Пароль должен содержать хотя бы одну строчную букву")

    if not re.search(r"\d", value):
        errors.append("Пароль должен содержать хотя бы одну цифру")

    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', value):
        errors.append("Пароль должен содержать хотя бы один специальный символ")

    if errors:
        raise ValidationError(errors)
