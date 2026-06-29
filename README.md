# claude-carbon-usage

Compare the estimated energy cost of your Claude Code sessions against the live carbon intensity of the Ireland electricity grid (zone `IE`).

## What it does

- Reads token usage from Claude Code session transcripts (`~/.claude/projects/`)
- Estimates server-side energy consumption using a configurable Wh/token model
- Fetches the live Ireland grid carbon intensity via the [Electricity Maps](https://www.electricitymaps.com/) API
- Reports estimated gCO₂ for the session

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Add your Electricity Maps API key to .env
```

Get a free API key at [electricitymaps.com](https://www.electricitymaps.com/free-tier-api). Note: free tier API keys only last 14 days.

## Usage

```bash
# Latest session in the current project
python scripts/carbon_now.py

# All sessions for this project (aggregated)
python scripts/carbon_now.py --all

# Specific session
python scripts/carbon_now.py --session <session-id>

# Different project path
python scripts/carbon_now.py --project ~/projects/my-other-project

# Manual token counts (if you have them from elsewhere)
python scripts/carbon_now.py --tokens 5000 2000
```

## Energy model

Energy estimates use these defaults (Wh per 1,000 tokens):

| Token type          | Default Wh/1k | Notes                                      |
|---------------------|---------------|--------------------------------------------|
| Output              | 3.0           | Autoregressive — one forward pass per token |
| Fresh input         | 1.0           | Single forward pass over context           |
| Cache write         | 1.25          | Slightly more than input (KV storage)      |
| Cache read          | 0.1           | Memory reads of pre-computed KV cache      |

These are rough order-of-magnitude estimates based on published LLM inference
research. Override them with environment variables:

```
CLAUDE_WH_PER_1K_OUTPUT=3.0
CLAUDE_WH_PER_1K_INPUT=1.0
CLAUDE_WH_PER_1K_CACHE_WRITE=1.25
CLAUDE_WH_PER_1K_CACHE_READ=0.1
```

## Example output

Running `project_total.py` against this repository itself:

```
$ python scripts/project_total.py

  ──────────────────────────────────────────────────────────
  Project Carbon Ledger — carbon_ledger.json
  ──────────────────────────────────────────────────────────

  Sessions tracked:  1
  Total tokens:      6,460,552
  Total energy:      996.31 Wh
  Total carbon:      259.04 gCO₂

  Per-session breakdown:
    5f1b774e…   6,460,552 tokens    259.04 gCO₂

  ──────────────────────────────────────────────────────────
  TOTAL                                 259.04 gCO₂
  ──────────────────────────────────────────────────────────
```

*Measured against the Ireland grid at 260 gCO₂/kWh on 2026-06-29.*

## Project structure

```
claude-carbon-usage/
├── src/
│   ├── claude_energy.py     # Wh/token energy model
│   ├── electricity_maps.py  # Electricity Maps API client
│   └── session_reader.py    # Read Claude Code session transcripts
├── scripts/
│   ├── carbon_now.py        # Report carbon footprint for a session
│   ├── compare_regions.py   # Compare footprint across grid regions
│   └── project_total.py     # Cumulative carbon ledger for the project
├── data/
│   └── carbon_ledger.json   # Persistent per-session carbon log
├── .env.example
└── requirements.txt
```
