# claude-carbon-usage

Compare the estimated energy cost of your Claude Code sessions against the live carbon intensity of your local electricity grid. Defaults to Ireland (zone `IE`); set your own region with `ELECTRICITY_MAPS_ZONE` or `--zone`.

## What it does

- Reads token usage from Claude Code session transcripts (`~/.claude/projects/`)
- Estimates server-side energy consumption using a configurable Wh/token model
- Fetches your grid's live carbon intensity via the [Electricity Maps](https://www.electricitymaps.com/) API
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

## Choosing your grid region

By default the tool prices energy against the Ireland grid (`IE`). To use your own region, set the [Electricity Maps zone code](https://api.electricitymap.org/v3/zones) — either persistently in `.env`:

```
ELECTRICITY_MAPS_ZONE=US-CAL-CISO
```

or per-run with the `--zone` flag:

```bash
python scripts/carbon_now.py --zone GB
```

Common zones: `GB` (Great Britain), `FR` (France), `DE` (Germany), `US-CAL-CISO` (California), `US-NY-NYIS` (New York). The `--zone` flag overrides `ELECTRICITY_MAPS_ZONE`.

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

  Sessions tracked:  3
  Total tokens:      13,428,678
  Total energy:      2,483.90 Wh
  Total carbon:      690.44 gCO₂

  Per-session breakdown:
    6819691e…   4,568,606 tokens    218.36 gCO₂
    fae3e244…   2,399,520 tokens    213.04 gCO₂
    5f1b774e…   6,460,552 tokens    259.04 gCO₂

  ──────────────────────────────────────────────────────────
  TOTAL                                 690.44 gCO₂
  ──────────────────────────────────────────────────────────
```

*Measured against the Ireland grid (290–260 gCO₂/kWh) across sessions on 2026-06-26 and 2026-06-29.*

## Machine-wide tracking

`project_total.py` tracks a single project. To accumulate the carbon cost of
*every* Claude Code session across *all* your projects, use `carbon_track.py`,
which records each session into one central SQLite database at
`~/.claude/carbon/usage.db`.

It runs automatically when a session ends, via a Claude Code
[**SessionEnd hook**](https://docs.claude.com/en/docs/claude-code/hooks) — a
command Claude Code invokes for you at a lifecycle event. You set it up once.

### Setting up the hook

1. **Finish the [Setup](#setup) above** — `carbon_track.py` runs through this
   project's virtualenv and reads its `.env` (for the API key and zone), so
   the venv and `.env` must exist.

2. **Note two absolute paths** (the hook can't use relative paths, because it
   runs from whatever project you're in, not from this repo):
   - your Python interpreter: `<repo>/.venv/bin/python`
   - the tracker script: `<repo>/scripts/carbon_track.py`

   Print them with:

   ```bash
   echo "$(pwd)/.venv/bin/python"
   echo "$(pwd)/scripts/carbon_track.py"
   ```

3. **Add the hook to `~/.claude/settings.json`** (create the file if it doesn't
   exist), substituting the two paths from step 2:

   ```json
   {
     "hooks": {
       "SessionEnd": [
         {
           "hooks": [
             {
               "type": "command",
               "command": "/abs/path/to/.venv/bin/python /abs/path/to/scripts/carbon_track.py >> ~/.claude/carbon/track.log 2>&1",
               "async": true
             }
           ]
         }
       ]
     }
   }
   ```

   `async: true` keeps it off the critical path so ending a session is never
   delayed. The `>> …track.log` redirect captures output, since a hook has no
   console to print to.

4. **Reload** — open a fresh Claude Code session (or run `/hooks` once) so the
   new configuration is picked up.

That's it. From now on every session you run — in any project — appends its
estimated carbon to the central database when it ends.

### Reading the totals

```bash
python scripts/carbon_track.py --report
```

```
  Machine-wide Claude Code Carbon — all projects

  Sessions tracked:  1
  Total tokens:      9,229,533
  Total energy:      1.563 kWh
  Total carbon:      529.77 gCO₂

  By project:
    claude-carbon-usage    1 sess     9,229,533 tok   529.77 gCO₂
```

If the hook ever seems quiet, check `~/.claude/carbon/track.log` for errors.
You can also record a transcript by hand (useful for backfilling):

```bash
python scripts/carbon_track.py --transcript ~/.claude/projects/<dir>/<session>.jsonl
```

Records are keyed by session id (upserted), so re-running is safe. If the grid
API is unavailable, energy is still recorded and carbon is left blank.

This repository keeps its own per-project ledger (`data/carbon_ledger.json`,
committed) *as well as* feeding the machine-wide database — so the carbon cost
of building this project stays transparent in the repo.

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
│   ├── project_total.py     # Cumulative carbon ledger for the project
│   └── carbon_track.py      # Machine-wide tracker (central SQLite db)
├── data/
│   └── carbon_ledger.json   # Persistent per-session carbon log
├── .env.example
└── requirements.txt
```
