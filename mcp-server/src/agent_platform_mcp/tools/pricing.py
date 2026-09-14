"""Explicit price snapshots; never infer provider cache semantics or rates."""

from datetime import date
from decimal import Decimal, InvalidOperation
import re

COUNTS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")
RATES = ("input_per_mtok", "output_per_mtok", "cache_read_per_mtok", "cache_write_per_mtok")


def snapshot(configuration: dict | None, model: str | None) -> dict | None:
    if not configuration or model is None or model not in configuration.get("models", {}):
        return None
    for key in ("price_id", "currency", "as_of"):
        if not isinstance(configuration.get(key), str) or not configuration[key].strip():
            raise ValueError(f"pricing {key} required")
    date.fromisoformat(configuration["as_of"])
    if not re.fullmatch(r"[A-Z]{3}", configuration["currency"]):
        raise ValueError("pricing currency must be a three-letter uppercase code")
    model_rates = configuration["models"][model]
    if type(model_rates.get("input_includes_cache")) is not bool:
        raise ValueError("pricing requires explicit input_includes_cache")
    rates = {}
    for key in RATES:
        value = model_rates.get(key)
        if value is None:
            rates[key] = None
            continue
        try:
            amount = Decimal(str(value))
        except InvalidOperation as exc:
            raise ValueError("invalid price rate") from exc
        if not amount.is_finite() or amount < 0:
            raise ValueError("price rate must be finite and nonnegative")
        rates[key] = str(amount)
    return {key: configuration[key] for key in ("price_id", "currency", "as_of")} | {
        "model": model, "input_includes_cache": model_rates["input_includes_cache"], "rates": rates}


def estimate(usage: dict | None, price: dict | None) -> Decimal | None:
    if usage is None or price is None:
        return None
    counts = [usage.get(key) for key in COUNTS]
    if any(value is None for value in counts):
        return None
    if price["input_includes_cache"]:
        counts[0] -= counts[2] + counts[3]
        if counts[0] < 0:
            raise ValueError("cache counts exceed inclusive input count")
    amount = Decimal(0)
    for count, key in zip(counts, RATES):
        if count == 0:
            continue
        rate = price["rates"].get(key)
        if rate is None:
            return None
        amount += Decimal(count) * Decimal(rate) / Decimal(1_000_000)
    return amount


def validate_snapshot(price: dict) -> None:
    if not isinstance(price, dict) or set(price) != {"price_id", "currency", "as_of", "model", "input_includes_cache", "rates"}:
        raise ValueError("invalid price snapshot fields")
    if not isinstance(price["model"], str) or not isinstance(price["rates"], dict) or set(price["rates"]) != set(RATES):
        raise ValueError("invalid price snapshot rates/model")
    validated = snapshot({**price, "models": {price["model"]: {**price["rates"], "input_includes_cache": price["input_includes_cache"]}}}, price["model"])
    if validated != price:
        raise ValueError("price snapshot must use normalized rate strings")
