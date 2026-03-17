# CAISO Imbalance Reserve: Is the 97.5th Percentile Input Too High?

## The question

CAISO's new imbalance reserve (IR) product under EDAM will procure capacity to cover net load forecast uncertainty between the day-ahead and real-time markets. The demand curve that tells the co-optimization how much IR to buy targets the **97.5th percentile** of historical forecast error for every hour of every day.

But this is more conservative than what operators have historically chosen. Under the RUC process, operators had discretion to set the coverage level based on real-time conditions. The DMM found that in Q3 2024, operators chose to apply the 97.5th percentile on only **15% of days**. On 51% of days they chose the 75th percentile. On 34% they chose the 50th. The new IR product removes that discretion and fixes P97.5 for all hours of all days.

The DMM's assessment: the IR demand curve "may be much too high during most hours" ([Q3 2024 Report](https://www.caiso.com/documents/2024-third-quarter-report-on-market-issues-and-performance-dec-23-2024.pdf), Section 10.3.1).

This is an input problem. The co-optimization works. The question is whether the input feeding it is set too conservatively.

## What this tool does

This dashboard explores the underlying forecast error distribution that feeds the IR requirement, and shows how it interacts with battery operations. It does **not** replicate CAISO's daily mosaic quantile regression, which requires non-public data and produces a fresh conditional requirement each day. Instead, it characterizes the unconditional distribution of historical DA-to-RT forecast errors using publicly available OASIS data.

Three tabs:

1. **Uncertainty profile** - Violin plots of net load forecast error by hour (Pacific time), with P97.5 and P75 overlaid. Histogram showing distributional shape. Shows where the forecast is accurate and where it struggles.

2. **Where uncertainty concentrates** - Heatmap of forecast error volatility (std dev) by hour and month. Reveals that uncertainty is driven by solar transition hours, not uniformly distributed.

3. **IR vs. battery arbitrage** - Overlays the DA price profile with the uncertainty profile by hour. Shows that the hours with highest uncertainty (solar transition, HE9-16) overlap with the hours batteries charge (cheap midday prices), while the hours with highest arbitrage value (evening ramp) have low uncertainty. IR and battery arbitrage compete for the same capacity during the same hours.

## Quickstart

```bash
git clone https://github.com/jaskcodes/caiso_ir_uncertainty.git
cd caiso_ir_uncertainty
pip install -r requirements.txt

# Pull real CAISO data (approximately 20 min, OASIS rate-limited)
python pull_data.py

# Launch dashboard
streamlit run app.py
```

The app runs immediately with synthetic data if you skip the data pull.

## Data sources

All publicly available from CAISO OASIS via [gridstatus](https://github.com/gridstatus/gridstatus):

| Dataset | Source | Used for |
|---|---|---|
| Actual load (5-min) | Today's Outlook | Computing actual net load |
| DA load forecast (hourly) | SLD_FCST | Computing forecasted net load |
| DA wind+solar forecast (hourly) | SLD_REN_FCST | Computing forecasted net load |
| Actual fuel mix (5-min) | Today's Outlook | Actual wind + solar generation |
| DA LMPs (hourly) | PRC_LMP | DA price profile (SP15) |

**Net load forecast error** = (actual load - actual wind - actual solar) - (DA load forecast - DA wind forecast - DA solar forecast). Positive = under-forecast (reserves would be needed). 5-minute actuals resampled to hourly. All hours in Pacific time.

## Limitations

- **Data coverage:** Jan through Mar and Oct through Dec of 2024-2025. Summer months (Apr through Sep) are mostly missing due to Today's Outlook retention limits. Summer would likely show higher uncertainty from solar variability. These findings are conservative.

- **Mean bias (-1,100 MW):** Larger than expected. Could reflect genuine forecast conservatism (solar/wind beating expectations) or a data alignment issue. CAISO's FAQ notes that Today's Outlook (telemetry-based) and OASIS (market-based) data don't directly match.

- **Unconditional percentiles, not conditional.** CAISO computes a fresh IR requirement daily using mosaic quantile regression conditioned on that day's forecasts. This analysis pools all days by hour. The percentiles shown don't correspond to any single day's requirement. However, the DMM found the mosaic regression at P97.5 had zero percent statistical significance due to small sample sizes (4-5 observations per hour), so the conditional approach may not improve on unconditional percentiles at this coverage level.

- **IR product has not launched yet.** The analysis uses the RUC experience as a proxy. The DMM draws the same comparison in their quarterly reports, but actual IR market outcomes may differ.

## What I'd build next

**With EDAM IR data (once publicly available):**
- IR utilization rate: what percent of awarded capacity is dispatched as energy in real time?
- Net IR economics: capacity payment received versus arbitrage foregone
- Compare actual daily IR requirements from the mosaic regression against the unconditional percentiles shown here

**With more time:**
- Fill summer gap using OASIS SLD_FCST actuals instead of Today's Outlook
- Investigate the -1,100 MW mean bias: is it real or a data join artifact?
- Model reliability impact of lowering coverage to P75 or P90
- Quantify the EDAM diversity benefit: how much does uncertainty shrink as more BAAs join?

**Longer-term question:** The historical error distribution was estimated when California had roughly 5 GW of battery storage. Today it has over 12 GW. Batteries charging midday absorb solar surplus; batteries discharging evening reduce the ramp. The distribution itself may have changed. Does the P97.5 requirement reflect the grid as it is today, or the grid as it was?

## Key references

- CAISO DMM, [Q3 2024 Report on Market Issues and Performance](https://www.caiso.com/documents/2024-third-quarter-report-on-market-issues-and-performance-dec-23-2024.pdf) - Section 10.3: operators chose P97.5 on 15% of days; DMM flags demand curve "may be much too high"
- CAISO DMM, [Review of Mosaic Quantile Regression](https://www.caiso.com/Documents/Review-of-the-Mosaic-Quantile-Regression-Nov-20-2023.pdf) - how the uncertainty calculation works
- CAISO DMM, [2024 Special Report on Battery Storage](https://www.caiso.com/documents/2024-special-report-on-battery-storage-may-29-2025.pdf) - batteries provide 84% of CAISO regulation; arbitrage patterns
- CAISO, [DAME Issue Paper/Straw Proposal](https://www.caiso.com/Documents/IssuePaper-StrawProposal-DayAheadMarketEnhancements.pdf) - original IR product design
- ESIG, [Imbalance Reserve Webinar Q&A](https://www.esig.energy/wp-content/uploads/2024/02/Friedrich-Webinar-QA_JF.pdf) - CAISO engineer explains IR in plain language

## Repo structure

```
app.py              # Streamlit dashboard (3 tabs)
pull_data.py        # CAISO data pipeline via gridstatus
requirements.txt
data/               # CSV cache (gitignored)
README.md
```

## Tools and AI usage

Built with AI assistance (Claude) for: OASIS API research, data pipeline code and iteration. The problem selection, market context, dashboard design and analytical framing are my own.
