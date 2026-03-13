# CAISO Imbalance Reserve Uncertainty Analysis

**Is CAISO's 97.5th-percentile imbalance reserve requirement too high?**

This project analyzes two years of CAISO net load forecast error data to evaluate whether the imbalance reserve (IR) procurement requirement — set at the 97.5th percentile of historical uncertainty — is excessive relative to what is actually needed in real time.

## Problem statement

CAISO's Day-Ahead Market Enhancements (DAME) introduced an imbalance reserve product to manage net load forecast uncertainty between the day-ahead and real-time markets. The IR requirement is calculated using quantile regression on historical forecast errors, targeting the 97.5th percentile for upward reserves and the 2.5th percentile for downward reserves.

CAISO's own Department of Market Monitoring (DMM) has flagged concerns: in Q3 2024, the 97.5th percentile target was used in the residual unit commitment on only ~15% of days. On all other days, actual uncertainty only required coverage at the 50th or 75th percentile.

This matters for batteries. Battery storage in CAISO primarily earns revenue through energy arbitrage — charging during midday solar hours and discharging during the evening ramp. When battery capacity is committed to IR, it cannot participate in arbitrage. If IR procurement is systematically excessive, batteries face an unnecessary opportunity cost.

## What this tool does

A three-tab Streamlit dashboard:

1. **Uncertainty profile** — Hourly violin plots of net load forecast error distribution, with P97.5 and P75 overlaid. Histogram to assess distributional shape. Seasonal filtering.

2. **IR requirement vs. reality** — Heatmap of P97.5 by hour × month. Line chart showing the gap between P97.5 and P75 by hour, with the excess shaded.

3. **Battery implications** — Modo-style monthly BESS revenue stack (DA energy, RT energy, ancillary services) with interactive IR opportunity cost overlay.

## Quickstart

```bash
# Clone and set up
git clone <repo-url>
cd <repo>
pip install -r requirements.txt

# Pull real CAISO data (~15-30 min, rate-limited by OASIS)
python pull_data.py

# Launch dashboard
streamlit run app.py
```

The app works immediately with synthetic data if you skip the data pull step. Synthetic data mimics realistic CAISO patterns but is not real market data.

## Data sources

All data is publicly available from CAISO:

| Dataset | OASIS report | Description |
|---|---|---|
| Load actual | Today's Outlook | 5-min actual system load |
| Load forecast | `SLD_FCST` (DAM) | Hourly day-ahead load forecast |
| Renewable forecast | `SLD_REN_FCST` (DAM) | Hourly day-ahead wind + solar forecast |
| Fuel mix | Today's Outlook | 5-min actual generation by fuel type |
| DAM LMPs | `PRC_LMP` (DAM) | Hourly day-ahead prices at NP15, SP15, ZP26 |

Data is fetched via the [gridstatus](https://github.com/gridstatus/gridstatus) Python library, which wraps the CAISO OASIS API.

## Methodology

**Net load forecast error** = (Actual load − Actual wind − Actual solar) − (DA load forecast − DA wind forecast − DA solar forecast)

- Positive error → actual net load exceeded the DA forecast (under-forecast)
- Negative error → actual net load was below DA forecast (over-forecast)

5-minute actuals are resampled to hourly to align with DAM forecast granularity. The analysis covers January 2024 through December 2025.

## Key references

- CAISO DMM, *Q3 2024 Report on Market Issues and Performance* — documents the 97.5th percentile being used on only 15% of days
- CAISO DMM, *2024 Special Report on Battery Storage* — battery arbitrage patterns and ancillary service participation
- CAISO, *Day-Ahead Market Enhancements Issue Paper* — original IR product design
- CAISO DMM, *Review of Mosaic Quantile Regression* — uncertainty calculation methodology

## Repo structure

```
├── app.py              # Streamlit dashboard
├── pull_data.py        # CAISO data pipeline (gridstatus)
├── requirements.txt    # Python dependencies
├── data/               # CSV cache (gitignored, regenerate with pull_data.py)
│   └── .gitkeep
├── .gitignore
└── README.md
```

## Limitations

**Data coverage gaps.** The Today's Outlook historical endpoint (used for actual load and fuel mix) has limited retention. The current dataset covers Jan–Mar and Oct–Dec of 2024–2025, with Apr–Sep largely missing due to the actuals source dropping off. Summer months — where solar variability and load peaks would likely show even higher uncertainty — are not represented. The findings from winter and shoulder months should be considered conservative.

**Simplified battery revenue model.** The revenue stack assumes perfect arbitrage capture (charge at the trough, discharge at the peak). Real batteries achieve 60–80% of the theoretical spread due to state-of-charge constraints, bid strategy, market power mitigation, and the ancillary service state-of-charge constraint (ASSOC). RT energy and AS revenues are estimated at industry-average percentages (12% and 18% of the DA stack) rather than computed from actual dispatch data.

**IR requirement is modeled, not observed.** The actual IR procurement volumes under DAME/EDAM are not yet publicly available. This analysis uses the historical net load forecast error distribution as a proxy for what the IR requirement *would be* at the 97.5th percentile, rather than measuring actual IR awards.

**Single pricing node.** Battery revenues are estimated using SP15 hub prices. Individual battery nodes can see significantly different spreads due to local congestion, especially in constrained areas.

## Future work

**With actual EDAM imbalance reserve data:**
- Compare realized IR awards against the P97.5 uncertainty requirement — how often is the full award dispatched as energy in real time?
- Measure IR utilization rate: what percentage of awarded IR capacity is actually called upon, and at what hours?
- Quantify the IR cost allocation: who is paying for the excess procurement, and how does it flow through to LSE rates?
- Assess whether the WEIM diversity benefit post-EDAM go-live reduces the net uncertainty CAISO needs to cover internally, further shrinking the case for P97.5

**With more time:**
- Pull actuals from OASIS (`SLD_FCST` with `market_run_id=ACTUAL`) instead of Today's Outlook to fill the summer data gap
- Validate the revenue model against Modo Energy's published CAISO BESS benchmark ($40–51/kW-year in 2024–2025) and calibrate a capture rate
- Use 60-day disclosure data to observe actual battery dispatch schedules and compare against the model's assumed charge/discharge windows
- Incorporate the mosaic quantile regression methodology (the actual method CAISO uses) rather than simple historical percentiles, to test whether the regression approach itself produces excessive requirements
- Model alternative IR procurement levels (P75, P90) and simulate the reliability impact — how many hours would have been short, and by how much?


This project was built with significant AI assistance (Claude) for:
- Research on CAISO DMM findings
- Data pipeline architecture and OASIS API navigation
- Dashboard layout and visualization design
- Code generation and iteration

The analytical framing, domain knowledge, and problem selection are my own.
