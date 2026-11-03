"""USD per million tokens, for the cost line. Read from the pricing pages saved in docs/refs on 2026-11-01
(DR-003). A model with no row here costs nothing in the line, and the runner says so rather than guessing.
Prompt-cache reads are priced at a tenth of the input rate and cache writes at 1.25 times it (the Anthropic
pricing page saved the same day); a tool turn resends the persona and the FAQ, so the cache is where the
money goes once the prompt is past the model's minimum cacheable size (the dry run of card 04)."""

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


CACHE_READ_FACTOR = 0.10
CACHE_WRITE_FACTOR = 1.25


def cost_usd(reply: Reply) -> float | None:
    rates = rate_for(reply.model)
    if rates is None:
        return None
    input_cost = (
        reply.input_tokens * rates[0]
        + reply.cached_input_tokens * rates[0] * CACHE_READ_FACTOR
        + reply.cache_write_input_tokens * rates[0] * CACHE_WRITE_FACTOR
    )
    return (input_cost + reply.output_tokens * rates[1]) / 1_000_000
