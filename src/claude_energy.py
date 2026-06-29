"""
claude_energy.py
----------------
Estimate energy consumption from Claude API token usage.

Different token types have different compute costs:

  - Output tokens: most expensive (autoregressive, one forward pass per token)
  - Fresh input tokens: cheaper (single forward pass over the whole context)
  - Cache-write tokens: slightly more than input (writing KV cache to memory)
  - Cache-read tokens: very cheap (reading pre-computed KV cache)

Override defaults via environment variables:
  CLAUDE_WH_PER_1K_OUTPUT, CLAUDE_WH_PER_1K_INPUT,
  CLAUDE_WH_PER_1K_CACHE_WRITE, CLAUDE_WH_PER_1K_CACHE_READ
"""

from __future__ import annotations

import os

# Wh per 1,000 tokens — rough order-of-magnitude estimates for unoptimised /
# reference conditions. Published measurements put optimised deployments at
# 0.0001–0.002 Wh/token; these defaults sit at the higher end of that range.
#
# Sources:
#   Luccioni et al. (2025) "Beyond Test-Time Compute Strategies: Advocating
#   Energy-per-Token in LLM Inference", EuroMLSys 2025.
#   https://arxiv.org/abs/2603.20224
#
#   Luccioni et al. (2023) "Power Hungry Processing: Watts Driving the Cost
#   of AI Deployment?", arXiv:2311.16863.
#   https://arxiv.org/abs/2311.16863
#
#   IEA (2025) "Energy and AI", World Energy Outlook Special Report.
#   https://www.iea.org/reports/energy-and-ai
#   (~2.9 Wh per ChatGPT query vs. 0.3 Wh for a web search)
#
# The cache_read rate (~10× cheaper than input) mirrors Anthropic's published
# pricing ratio for cached vs. non-cached input tokens.
_DEFAULT_WH_PER_1K = {
    "output": 3.0,
    "input": 1.0,
    "cache_write": 1.25,
    "cache_read": 0.1,
}


def _wh_rates() -> dict[str, float]:
    return {
        "output": float(os.environ.get("CLAUDE_WH_PER_1K_OUTPUT", _DEFAULT_WH_PER_1K["output"])),
        "input": float(os.environ.get("CLAUDE_WH_PER_1K_INPUT", _DEFAULT_WH_PER_1K["input"])),
        "cache_write": float(os.environ.get("CLAUDE_WH_PER_1K_CACHE_WRITE", _DEFAULT_WH_PER_1K["cache_write"])),
        "cache_read": float(os.environ.get("CLAUDE_WH_PER_1K_CACHE_READ", _DEFAULT_WH_PER_1K["cache_read"])),
    }


def usage_to_wh(usage: dict) -> float:
    """
    Convert a Claude API usage dict to estimated watt-hours.

    Accepts the `usage` field from a Claude API response message, with keys:
        input_tokens, output_tokens,
        cache_creation_input_tokens (optional),
        cache_read_input_tokens (optional)
    """
    rates = _wh_rates()
    output = usage.get("output_tokens", 0)
    fresh_input = usage.get("input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)

    return (
        output * rates["output"] / 1000
        + fresh_input * rates["input"] / 1000
        + cache_write * rates["cache_write"] / 1000
        + cache_read * rates["cache_read"] / 1000
    )


def wh_to_gco2(wh: float, carbon_intensity_g_per_kwh: float) -> float:
    """Convert watt-hours to grams of CO₂ using grid carbon intensity."""
    return wh / 1000 * carbon_intensity_g_per_kwh


def summarise_usage(usage: dict) -> dict:
    """Return a breakdown of token counts and energy estimate for a usage dict."""
    wh = usage_to_wh(usage)
    return {
        "output_tokens": usage.get("output_tokens", 0),
        "input_tokens": usage.get("input_tokens", 0),
        "cache_write_tokens": usage.get("cache_creation_input_tokens", 0),
        "cache_read_tokens": usage.get("cache_read_input_tokens", 0),
        "estimated_wh": wh,
    }
