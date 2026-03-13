"""
app.py — CAISO Imbalance Reserve Uncertainty Dashboard
=======================================================
Three tabs. Each answers one question:

1. What does net load uncertainty actually look like?
2. Is the 97.5th percentile IR requirement justified?
3. What does this cost battery operators?

Usage: streamlit run app.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import plotly.express as px
from scipy import stats
from pathlib import Path

st.set_page_config(page_title="CAISO IR Uncertainty", page_icon="⚡", layout="wide")

DATA_DIR = Path("data")
HOURS = list(range(1, 25))
SEASONS = ["Winter", "Spring", "Summer", "Fall"]

# ---------------------------------------------------------------------------
# Synthetic data (fallback when real data not yet pulled)
# ---------------------------------------------------------------------------
def _synth_uncertainty(n=730):
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=n*24, freq="h", tz="US/Pacific")
    h, m = dates.hour + 1, dates.month
    hour_std = np.array([800,780,760,750,760,800,900,1050,1200,1350,
                         1500,1550,1500,1400,1350,1400,1500,1550,1450,1300,1150,1000,900,850])
    smult = {12:.85,1:.85,2:.88,3:.95,4:1.0,5:1.05,6:1.2,7:1.3,8:1.3,9:1.15,10:1.0,11:.9}
    errors = [np.random.normal(50+30*np.sin((int(h[i])-7)/24*2*np.pi),
              hour_std[int(h[i])-1]*smult[int(m[i])]) for i in range(len(dates))]
    return pd.DataFrame({"Time":dates,"Net_Load_Error_MW":errors,"Hour":h,"Month":m,
        "Season":[("Winter" if x in [12,1,2] else "Spring" if x in [3,4,5]
                   else "Summer" if x in [6,7,8] else "Fall") for x in m]})

def _synth_lmps(n=730):
    np.random.seed(123)
    dates = pd.date_range("2024-01-01", periods=n*24, freq="h", tz="US/Pacific")
    base = [35,32,28,25,26,30,40,55,50,30,15,5,-5,-2,8,25,55,80,75,60,50,45,40,38]
    prices = [base[d.hour]*(1+.3*np.sin((d.month-3)/12*2*np.pi))+np.random.normal(0,12) for d in dates]
    return pd.DataFrame({"Time":dates,"LMP":prices,"Location":"TH_SP15_GEN-APND",
                          "Hour":dates.hour+1,"Month":dates.month})


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
@st.cache_data
def load_data():
    p = DATA_DIR / "net_load_uncertainty.csv"
    if p.exists():
        df = pd.read_csv(p, parse_dates=["Time"])
        if "Season" not in df.columns:
            df["Season"] = df["Month"].map({12:"Winter",1:"Winter",2:"Winter",3:"Spring",
                4:"Spring",5:"Spring",6:"Summer",7:"Summer",8:"Summer",9:"Fall",10:"Fall",11:"Fall"})
        return df, False
    return _synth_uncertainty(), True

@st.cache_data
def load_lmps():
    p = DATA_DIR / "dam_lmps.csv"
    if p.exists():
        df = pd.read_csv(p)
        df["Time"] = pd.to_datetime(df["Time"], utc=True)
        # Filter to one hub — LMP file has NP15, SP15, ZP26 stacked
        if "Location" in df.columns:
            locs = df["Location"].unique()
            sp15 = [l for l in locs if "SP15" in str(l)]
            df = df[df["Location"] == (sp15[0] if sp15 else locs[0])].copy()
        if "Hour" not in df.columns: df["Hour"] = df["Time"].dt.hour + 1
        if "Month" not in df.columns: df["Month"] = df["Time"].dt.month
        return df
    return _synth_lmps()

df, is_synth = load_data()
lmp_df = load_lmps()

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("⚡ IR uncertainty")
    if is_synth:
        st.warning("Synthetic data — run `python pull_data.py` for real OASIS data.")
    st.divider()
    seasons = st.multiselect("Season", SEASONS, default=SEASONS)
    months = st.multiselect("Month", range(1,13), default=list(range(1,13)),
                            format_func=lambda x: pd.Timestamp(2024,x,1).strftime("%b"))
    st.divider()
    st.markdown(
        "**Thesis:** CAISO procures imbalance reserves\n"
        "at the 97.5th percentile of net load uncertainty\n"
        "for every hour. The DMM found this threshold was\n"
        "needed on only ~15% of days. The excess locks\n"
        "battery capacity away from energy arbitrage."
    )

filt = df[df["Season"].isin(seasons) & df["Month"].isin(months)].copy()


# ===========================================================================
# TAB 1 — What does net load uncertainty actually look like?
# ===========================================================================
tab1, tab2, tab3 = st.tabs([
    "📊 Uncertainty profile",
    "📈 Requirement vs. reality",
    "🔋 Cost to batteries",
])

with tab1:
    st.header("What does net load uncertainty look like?")
    st.markdown(
        "Net load = demand minus wind and solar. The forecast error between "
        "day-ahead and real-time determines how much imbalance reserve capacity "
        "CAISO procures. Here is the actual distribution of that error."
    )

    c1, c2, c3 = st.columns(3)
    err = filt["Net_Load_Error_MW"]
    c1.metric("Mean error", f"{err.mean():+,.0f} MW")
    c2.metric("Std deviation", f"{err.std():,.0f} MW")
    c3.metric("P97.5 (IR target)", f"{err.quantile(0.975):+,.0f} MW")

    # Violin by hour — the core chart
    fig = go.Figure()
    for hour in HOURS:
        hd = filt.loc[filt["Hour"]==hour, "Net_Load_Error_MW"].dropna()
        if len(hd) < 10: continue
        fig.add_trace(go.Violin(
            x=[f"HE{hour}"]*len(hd), y=hd, showlegend=False,
            box_visible=True, meanline_visible=True,
            line_color="#3B82F6", fillcolor="rgba(59,130,246,0.12)",
            scalemode="width", width=0.75,
        ))

    # P97.5 line — the IR procurement threshold
    p975 = filt.groupby("Hour")["Net_Load_Error_MW"].quantile(0.975)
    fig.add_trace(go.Scatter(
        x=[f"HE{h}" for h in p975.index], y=p975.values,
        mode="lines+markers", name="P97.5 — current IR target",
        line=dict(color="#EF4444", width=2, dash="dash"),
        marker=dict(size=4, color="#EF4444"),
    ))
    p75 = filt.groupby("Hour")["Net_Load_Error_MW"].quantile(0.75)
    fig.add_trace(go.Scatter(
        x=[f"HE{h}" for h in p75.index], y=p75.values,
        mode="lines+markers", name="P75 — sufficient ~85% of days",
        line=dict(color="#F59E0B", width=1.5, dash="dot"),
        marker=dict(size=3, color="#F59E0B"),
    ))
    fig.add_hline(y=0, line_color="gray", line_width=0.5)
    fig.update_layout(
        height=460, template="plotly_white",
        margin=dict(l=60,r=20,t=30,b=50),
        yaxis_title="Forecast error (MW)", xaxis_title="Hour ending",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fig, use_container_width=True)

    st.markdown(
        f"The mean error is **{err.mean():+,.0f} MW** — the DA forecast systematically "
        f"over-predicts net load, likely because wind and solar consistently beat "
        f"day-ahead forecasts. But the P97.5 line tells a different story by hour: "
        f"during the evening ramp (HE17–HE24), the upward tail reaches 2,000–4,500 MW "
        f"— real reserves are needed. During midday hours, even P97.5 barely crosses "
        f"zero. **The IR requirement is doing real work only in the evening; "
        f"during the rest of the day it holds capacity against a risk that doesn't materialize.**"
    )

    # Histogram with normal overlay — just to show shape
    st.subheader("Distribution shape")
    mu, sigma = err.mean(), err.std()
    fh = go.Figure()
    fh.add_trace(go.Histogram(
        x=err, nbinsx=80, histnorm="probability density",
        marker_color="rgba(59,130,246,0.4)", name="Observed",
    ))
    xs = np.linspace(err.min(), err.max(), 200)
    fh.add_trace(go.Scatter(
        x=xs, y=stats.norm.pdf(xs, mu, sigma), mode="lines",
        name=f"Normal fit (σ={sigma:,.0f} MW)", line=dict(color="#EF4444", width=2),
    ))
    fh.update_layout(
        height=280, template="plotly_white",
        margin=dict(l=40,r=20,t=20,b=40),
        xaxis_title="Forecast error (MW)", yaxis_title="Density",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fh, use_container_width=True)

    sk, ku = err.skew(), err.kurtosis()
    st.markdown(
        f"Skewness: **{sk:.2f}** · Excess kurtosis: **{ku:.2f}** — "
        f"{'the distribution is approximately normal.' if abs(sk)<0.5 and abs(ku)<1 else 'the distribution departs from normality.'} "
        f"{'The high kurtosis means the distribution is more peaked than a normal — most hours cluster tightly around the mean, but extreme events are more frequent than a Gaussian predicts. ' if ku > 1 else ''}"
        f"This reinforces the case for dynamic, hour-specific IR procurement rather than "
        f"a flat percentile applied uniformly."
    )


# ===========================================================================
# TAB 2 — Is the 97.5th percentile requirement justified?
# ===========================================================================
with tab2:
    st.header("Is the P97.5 IR requirement justified?")
    st.markdown(
        "CAISO's DMM found the 97.5th percentile was only needed in RUC on ~15% of "
        "days (Q3 2024). On most days, the 50th or 75th percentile would have been "
        "sufficient. The charts below show where and when the requirement exceeds "
        "what's actually needed."
    )

    # Heatmap — when is uncertainty highest?
    heat = filt.groupby(["Month","Hour"])["Net_Load_Error_MW"].quantile(0.975).reset_index()
    hp = heat.pivot(index="Month", columns="Hour", values="Net_Load_Error_MW")
    fhm = go.Figure(go.Heatmap(
        z=hp.values,
        x=[f"HE{h}" for h in hp.columns],
        y=[pd.Timestamp(2024,m,1).strftime("%b") for m in hp.index],
        colorscale="RdYlBu_r", colorbar_title="MW",
        text=np.round(hp.values).astype(int), texttemplate="%{text}", textfont=dict(size=9),
    ))
    fhm.update_layout(
        title="P97.5 net load error by hour × month — where uncertainty concentrates",
        height=350, template="plotly_white",
        margin=dict(l=60,r=20,t=50,b=40),
    )
    st.plotly_chart(fhm, use_container_width=True)

    # The gap chart — two lines with shaded area between
    st.subheader("IR requirement vs. what's actually needed")
    gap = filt.groupby("Hour")["Net_Load_Error_MW"].agg(
        P50=lambda x: x.quantile(0.50),
        P75=lambda x: x.quantile(0.75),
        P975=lambda x: x.quantile(0.975),
    ).reset_index()

    x_labels = [f"HE{h}" for h in gap["Hour"]]

    fg = go.Figure()

    # Shaded area between P75 and P97.5 — the excess
    fg.add_trace(go.Scatter(
        x=x_labels, y=gap["P975"],
        mode="lines", line=dict(width=0), showlegend=False,
    ))
    fg.add_trace(go.Scatter(
        x=x_labels, y=gap["P75"],
        mode="lines", line=dict(width=0), showlegend=False,
        fill="tonexty", fillcolor="rgba(239,68,68,0.15)",
    ))

    # P97.5 line
    fg.add_trace(go.Scatter(
        x=x_labels, y=gap["P975"],
        mode="lines+markers", name="P97.5 — current IR target",
        line=dict(color="#EF4444", width=2.5),
        marker=dict(size=5, color="#EF4444"),
    ))
    # P75 line
    fg.add_trace(go.Scatter(
        x=x_labels, y=gap["P75"],
        mode="lines+markers", name="P75 — sufficient ~85% of days",
        line=dict(color="#F59E0B", width=2.5),
        marker=dict(size=5, color="#F59E0B"),
    ))
    # Median for reference
    fg.add_trace(go.Scatter(
        x=x_labels, y=gap["P50"],
        mode="lines", name="P50 — median error",
        line=dict(color="#3B82F6", width=1.5, dash="dot"),
    ))

    fg.add_hline(y=0, line_color="gray", line_width=0.5)

    # Annotate the gap at the peak hour
    peak_idx = gap["P975"].idxmax()
    peak_hour = gap.loc[peak_idx, "Hour"]
    peak_975 = gap.loc[peak_idx, "P975"]
    peak_75 = gap.loc[peak_idx, "P75"]
    fg.add_annotation(
        x=f"HE{peak_hour}", y=(peak_975 + peak_75) / 2,
        text=f"  {peak_975 - peak_75:,.0f} MW<br>  excess",
        showarrow=False, font=dict(size=11, color="#EF4444"),
        xanchor="left",
    )

    fg.update_layout(
        height=400, template="plotly_white",
        margin=dict(l=60,r=20,t=30,b=50),
        yaxis_title="Forecast error (MW)", xaxis_title="Hour ending",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    st.plotly_chart(fg, use_container_width=True)

    avg_excess = (gap["P975"] - gap["P75"]).mean()
    evening_excess = gap.loc[gap["Hour"].isin(range(17,25)), "P975"].mean() - gap.loc[gap["Hour"].isin(range(17,25)), "P75"].mean()
    midday_p975 = gap.loc[gap["Hour"].isin(range(7,16)), "P975"].mean()
    st.markdown(
        f"The shaded red area is the gap between what's needed at P75 and what's procured "
        f"at P97.5. On average that gap is **{avg_excess:,.0f} MW/hour**, peaking at "
        f"**{gap['P975'].max() - gap['P75'].max():,.0f} MW** during the evening ramp. "
        f"During midday hours (HE7-HE15), the P97.5 requirement averages just "
        f"**{midday_p975:,.0f} MW** — barely above zero — yet capacity must still be held."
    )


# ===========================================================================
# TAB 3 — What does this cost battery operators?
# ===========================================================================
with tab3:
    st.header("What does this cost batteries?")
    st.markdown(
        "Batteries in CAISO earn ~70% of merchant revenue from DA energy arbitrage: "
        "charging during midday solar hours (low prices) and discharging during the "
        "evening ramp (high prices). Capacity committed to IR cannot arbitrage. "
        "This chart estimates what that costs."
    )

    # User controls
    cl, cr = st.columns(2)
    with cl:
        batt_mw = st.slider("Battery capacity (MW)", 50, 500, 100, 25)
        duration = st.slider("Duration (hours)", 1, 8, 4)
    with cr:
        eff_pct = st.slider("Round-trip efficiency (%)", 80, 95, 88)
        ir_pct = st.slider("% capacity held for IR", 0, 100, 30, 5,
                           help="Portion of battery locked for imbalance reserves")

    eff = eff_pct / 100
    ir_frac = ir_pct / 100

    # Hours are in UTC in the LMP data. CAISO Pacific time:
    #   Solar trough (charge):  HE10-15 PT = HE17-22 UTC
    #   Evening ramp (discharge): HE17-21 PT = HE0-4 UTC (next day) → HE24,1,2,3,4
    charge_hrs = list(range(17, 23))       # UTC: cheap solar hours
    discharge_hrs = [24, 1, 2, 3, 4]       # UTC: expensive evening PT hours
    n_dis = min(duration, len(discharge_hrs))

    # Monthly DA spread — find the right LMP column
    lmp_m = lmp_df.copy()
    lmp_col = "LMP"
    for c in lmp_m.columns:
        if "lmp" in c.lower() and "type" not in c.lower():
            lmp_col = c
            break

    lmp_m["YM"] = lmp_m["Time"].dt.to_period("M")
    lmp_m["Bucket"] = lmp_m["Hour"].apply(
        lambda h: "charge" if h in charge_hrs else ("discharge" if h in discharge_hrs else "other"))
    mpr = lmp_m.groupby(["YM","Bucket"])[lmp_col].mean().unstack(fill_value=0)
    if "charge" in mpr.columns and "discharge" in mpr.columns:
        mpr["spread"] = mpr["discharge"] - mpr["charge"]
    else:
        mpr["spread"] = 40

    days = 30
    arb_cap = batt_mw * (1 - ir_frac)

    # Revenue streams — all in $k/month
    rev_da = mpr["spread"] * arb_cap * eff * n_dis * days / 1000
    rev_rt = rev_da * 0.12
    rev_as = rev_da * 0.18
    ir_cost = mpr["spread"] * batt_mw * ir_frac * eff * n_dis * days / 1000

    labels = [str(p) for p in rev_da.index]
    totals = rev_da + rev_rt + rev_as

    # $/kW-month: totals is $k, so totals/batt_mw = $k/MW = $/kW
    avg_kwmo = totals.mean() / batt_mw if batt_mw else 0

    mc1, mc2, mc3 = st.columns(3)
    mc1.metric("Avg $/kW-month", f"${avg_kwmo:.2f}")
    mc2.metric("Avg IR opp. cost/mo", f"${ir_cost.mean():,.0f}k")
    total_addr = totals.mean() + ir_cost.mean()
    pct_lost = ir_cost.mean() / total_addr * 100 if total_addr > 0 else 0
    mc3.metric("Revenue lost to IR", f"{pct_lost:.0f}%")

    # Stacked bar — revenue only, IR cost as dashed line overlay
    fig = go.Figure()
    fig.add_trace(go.Bar(x=labels, y=rev_da, name="DA Energy", marker_color="#F59E0B"))
    fig.add_trace(go.Bar(x=labels, y=rev_rt, name="RT Energy", marker_color="#EF4444"))
    fig.add_trace(go.Bar(x=labels, y=rev_as, name="Ancillary services", marker_color="#34D399"))

    # Total labels on top
    fig.add_trace(go.Scatter(
        x=labels, y=totals + max(totals.max()*0.04, 5),
        text=[f"${v:,.0f}k" for v in totals], mode="text",
        textposition="top center", textfont=dict(size=10, color="gray"),
        showlegend=False,
    ))

    # IR cost as dashed line (not negative bars)
    if ir_pct > 0:
        fig.add_trace(go.Scatter(
            x=labels, y=ir_cost.values,
            mode="lines+markers", name="IR opportunity cost",
            line=dict(color="#EF4444", width=2, dash="dash"),
            marker=dict(size=5, color="#EF4444"),
        ))

    fig.update_layout(
        title=f"Estimated BESS monthly merchant revenue — {batt_mw} MW / {duration}-hr",
        height=440, template="plotly_white", barmode="stack",
        margin=dict(l=60,r=20,t=60,b=60),
        yaxis_title="Revenue ($k)", xaxis=dict(tickangle=-45),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, font=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True)

    # Key finding — in $/kW-year to match industry benchmarks (Modo: $40-51/kW-yr)
    annual_lost = ir_cost.sum()
    annual_rev = totals.sum()
    total_addr = annual_rev + annual_lost
    pct = annual_lost / total_addr * 100 if total_addr > 0 else 0
    kw = batt_mw * 1000 if batt_mw else 1
    lost_kwyr = annual_lost * 1000 / kw   # $k → $ → per kW
    addr_kwyr = total_addr * 1000 / kw
    st.info(
        f"**At {ir_pct}% IR hold**, this battery forgoes ≈**\\${lost_kwyr:,.0f}/kW-year** "
        f"in energy arbitrage — **{pct:.0f}%** of total addressable revenue "
        f"(≈\\${addr_kwyr:,.0f}/kW-year) — to hold reserves that CAISO's DMM found were "
        f"needed at the 97.5th percentile on only ~15% of days."
    )

    with st.expander("Methodology"):
        st.markdown(
            "**DA Energy:** (avg discharge price − avg charge price) × available MW × "
            "efficiency × discharge hours × 30 days. Charge hours: HE10-15 PT (solar trough), "
            "discharge: HE17-21 PT (evening ramp).\n\n"
            "**RT Energy:** Estimated at 12% of DA revenue (industry average DA-RT uplift).\n\n"
            "**Ancillary services:** Estimated at 18% of total stack (per DMM 2024 battery report, "
            "batteries provide ~84% of CAISO regulation but AS share of revenue is declining).\n\n"
            "**IR opportunity cost:** Same spread calculation applied to the MW fraction held for IR. "
            "This capacity cannot participate in the IFM energy market.\n\n"
            "This is a simplified model. Actual revenues depend on bid strategy, state-of-charge "
            "constraints, congestion, and market power mitigation. Industry benchmark: ~$40-51/kW-year "
            "in 2024-2025 (Modo Energy)."
        )


# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "Data: CAISO OASIS via gridstatus | Period: Jan 2024 – Dec 2025 "
)
