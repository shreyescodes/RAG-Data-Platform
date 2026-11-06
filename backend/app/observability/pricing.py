"""LLM cost estimation from token counts.

Prices are USD per million tokens. Built-in prices cover hosted models only
and are overridable with `LLM_PRICING`; check them against your provider's
price list. A local endpoint (your own GPU) costs nothing unless you price
it explicitly, e.g. to account for hardware or power.
"""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import BaseModel, Field


class ModelPrice(BaseModel):
    input: float = Field(ge=0, description="USD per 1M prompt tokens.")
    output: float = Field(ge=0, description="USD per 1M completion tokens.")


# Groq list prices at the time of writing.
DEFAULT_PRICING: dict[str, ModelPrice] = {
    "openai/gpt-oss-120b": ModelPrice(input=0.15, output=0.60),
}


class PriceTable:
    def __init__(self, overrides: Mapping[str, ModelPrice], *, local_endpoint: bool) -> None:
        # Built-in prices are for hosted APIs; a local model is only priced on request.
        base = {} if local_endpoint else DEFAULT_PRICING
        self._prices = {**base, **overrides}

    def price(self, model: str) -> ModelPrice | None:
        return self._prices.get(model)

    def cost_usd(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        price = self.price(model)
        if price is None:
            return 0.0
        return (prompt_tokens * price.input + completion_tokens * price.output) / 1_000_000
