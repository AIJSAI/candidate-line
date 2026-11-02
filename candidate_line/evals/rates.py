"""USD per million tokens, for the cost line. Read from the pricing pages saved in docs/refs on 2026-11-01
(DR-003). A model with no row here costs nothing in the line, and the runner says so rather than guessing."""

from __future__ import annotations

from candidate_line.brain import Reply

RATES_USD_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
}


def rate_for(model: str) -> tuple[float, float] | None:
    for key, rates in RATES_USD_PER_MTOK.items():
        if key in model:
            return rates
    return None


def cost_usd(reply: Reply) -> float | None:
    rates = rate_for(reply.model)
    if rates is None:
        return None
    return (reply.input_tokens * rates[0] + reply.output_tokens * rates[1]) / 1_000_000
