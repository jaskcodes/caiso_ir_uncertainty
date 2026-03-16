"""
app.py — CAISO Imbalance Reserve Uncertainty Dashboard
=======================================================
Three tabs. Each answers one question:

1. What does net load uncertainty actually look like?
2. Where does forecast uncertainty concentrate?
3. How does IR interact with battery operations?

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
        # Timestamps have mixed offsets (-08:00 PST, -07:00 PDT) - parse with utc then convert
        df["Time"] = pd.to_datetime(df["Time"], utc=True).dt.tz_convert("US/Pacific")
        # Filter to one hub
        if "Location" in df.columns:
            locs = df["Location"].unique()
            sp15 = [l for l in locs if "SP15" in str(l)]
            df = df[df["Location"] == (sp15[0] if sp15 else locs[0])].copy()
        df["Hour"] = df["Time"].dt.hour + 1  # HE1-HE24 Pacific
        df["Month"] = df["Time"].dt.month
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
        "**Thesis:** CAISO's new IR product will set\n"
        "the demand curve at P97.5 for all hours, all\n"
        "days. But under RUC, operators with discretion\n"
        "chose P97.5 on only 15% of days. This dashboard\n"
        "explores the underlying forecast error distribution\n"
        "and the cost to batteries."
    )

filt = df[df["Season"].isin(seasons) & df["Month"].isin(months)].copy()


# ===========================================================================
# TAB 1 — What does net load uncertainty actually look like?
# ===========================================================================
tab1, tab2, tab3 = st.tabs([
    "📊 Uncertainty profile",
    "📈 Requirement vs. reality",
    "🔋 IR vs. battery arbitrage",
])

with tab1:
    st.header("What does net load uncertainty look like?")
    st.markdown(
        "Net load = demand minus wind and solar. The forecast error between "
        "day-ahead and real-time is the uncertainty that the RUC process currently "
        "manages, and that the new IR product under EDAM is designed to cover. "
        "Here is the actual distribution of that error."
    )

    c1, c2, c3 = st.columns(3)
    err = filt["Net_Load_Error_MW"]
    c1.metric("Mean error", f"{err.mean():+,.0f} MW")
    c2.metric("Std deviation", f"{err.std():,.0f} MW")
    c3.metric("P97.5", f"{err.quantile(0.975):+,.0f} MW")

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

    # P97.5 and P75 lines — empirical percentiles of the historical distribution
    p975 = filt.groupby("Hour")["Net_Load_Error_MW"].quantile(0.975)
    fig.add_trace(go.Scatter(
        x=[f"HE{h}" for h in p975.index], y=p975.values,
        mode="lines+markers", name="P97.5 — top 2.5% of errors",
        line=dict(color="#EF4444", width=2, dash="dash"),
        marker=dict(size=4, color="#EF4444"),
    ))
    p75 = filt.groupby("Hour")["Net_Load_Error_MW"].quantile(0.75)
    fig.add_trace(go.Scatter(
        x=[f"HE{h}" for h in p75.index], y=p75.values,
        mode="lines+markers", name="P75 — top 25% of errors",
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
        f"day-ahead forecasts. The P97.5 line (red) shows the upper tail by hour: "
        f"during the solar transition hours (HE9–HE16), the upward tail reaches "
        f"2,000–4,500 MW — these are the hours with the most forecast uncertainty. "
        f"During overnight and evening hours, the distribution is tighter and the "
        f"upper tail stays near zero."
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
        f"{'The high kurtosis means the distribution is more peaked than a normal — most hours cluster tightly around the mean, but extreme events in the tails are more frequent than a Gaussian predicts. ' if ku > 1 else ''}"
        f"This matters because the IR demand curve targets the 97.5th percentile — "
        f"deep in the tail where the distribution's shape has the most impact."
    )


# ===========================================================================
# TAB 2 — Is the 97.5th percentile requirement justified?
# ===========================================================================
with tab2:
    st.header("Where does forecast uncertainty concentrate?")
    st.markdown(
        "Under the RUC process, operators had discretion to choose coverage levels — "
        "they applied P97.5 on only 15% of days, choosing P75 on 51% and P50 on 34% "
        "(DMM Q3 2024 Report, Section 10.3). The new IR product under EDAM will fix "
        "the demand curve at P97.5 for all hours of all days. The DMM's assessment: "
        "this 'may be much too high during most hours.' The charts below show the "
        "underlying forecast error distribution — the same uncertainty both RUC and "
        "IR are designed to cover."
    )

    # Heatmap — std dev of forecast error by hour × month
    heat = filt.groupby(["Month","Hour"])["Net_Load_Error_MW"].std().reset_index()
    hp = heat.pivot(index="Month", columns="Hour", values="Net_Load_Error_MW")
    fhm = go.Figure(go.Heatmap(
        z=hp.values,
        x=[f"HE{h}" for h in hp.columns],
        y=[pd.Timestamp(2024,m,1).strftime("%b") for m in hp.index],
        colorscale="YlOrRd", colorbar_title="MW",
        text=np.round(hp.values).astype(int), texttemplate="%{text}", textfont=dict(size=9),
    ))
    fhm.update_layout(
        title="Std deviation of forecast error by hour × month — where uncertainty is highest",
        height=350, template="plotly_white",
        margin=dict(l=60,r=20,t=50,b=40),
    )
    st.plotly_chart(fhm, use_container_width=True)

    st.markdown(
        "Higher values mean the forecast is more volatile at that hour — the system "
        "faces more uncertainty and reserves are more likely to be needed. Low values "
        "mean the forecast is consistently accurate.\n\n"
        "Under the RUC process, operators had discretion to choose how much capacity "
        "to hold based on conditions. They applied the 97.5th percentile on only 15% "
        "of days, choosing P75 on 51% and P50 on 34% (DMM Q3 2024, Section 10.3). "
        "The new IR product under EDAM will fix the demand curve at P97.5 for all "
        "hours of all days — including the low-volatility hours where this heatmap "
        "shows minimal uncertainty. The DMM's assessment: the demand curve 'may be "
        "much too high during most hours.'"
    )


# ===========================================================================
# TAB 3 — How does IR interact with battery operations?
# ===========================================================================
with tab3:
    st.header("How does IR interact with battery operations?")
    st.markdown(
        "Batteries arbitrage the DA price curve — charge when prices are low (solar "
        "trough midday), discharge when prices are high (evening ramp). The IR product "
        "holds capacity for hours with high forecast uncertainty. The question is: "
        "**do these two needs compete for the same hours?**"
    )

    # --- Chart 1: Price profile + uncertainty overlay ---
    # Avg DA price by hour
    lmp_col = "LMP"
    for c in lmp_df.columns:
        if "lmp" in c.lower() and "type" not in c.lower():
            lmp_col = c
            break

    price_by_hour = lmp_df.groupby("Hour")[lmp_col].mean()

    # Std dev of forecast error by hour (from Tab 2 data)
    std_by_hour = filt.groupby("Hour")["Net_Load_Error_MW"].std()

    x_labels = [f"HE{h}" for h in price_by_hour.index]

    from plotly.subplots import make_subplots
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Price bars
    fig.add_trace(go.Bar(
        x=x_labels, y=price_by_hour.values,
        name="Avg DA LMP ($/MWh)",
        marker_color="#F59E0B", opacity=0.7,
    ), secondary_y=False)

    # Uncertainty line on secondary axis
    fig.add_trace(go.Scatter(
        x=x_labels, y=std_by_hour.values,
        name="Forecast error std dev (MW)",
        mode="lines+markers",
        line=dict(color="#EF4444", width=2.5),
        marker=dict(size=5, color="#EF4444"),
    ), secondary_y=True)

    # Highlight the high-uncertainty zone
    fig.add_vrect(x0="HE9", x1="HE16", fillcolor="rgba(239,68,68,0.06)",
                  line_width=0, annotation_text="Peak uncertainty",
                  annotation_position="top left",
                  annotation_font=dict(size=10, color="gray"))

    fig.update_layout(
        title="DA price profile vs. forecast uncertainty by hour",
        height=420, template="plotly_white",
        margin=dict(l=60, r=60, t=50, b=50),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
    )
    fig.update_yaxes(title_text="DA LMP ($/MWh)", secondary_y=False)
    fig.update_yaxes(title_text="Forecast error std dev (MW)", secondary_y=True)
    st.plotly_chart(fig, use_container_width=True)

    # Insight blurb
    charge_price = price_by_hour.loc[10:15].mean()
    discharge_price = price_by_hour.loc[17:21].mean()
    charge_std = std_by_hour.loc[10:15].mean()
    discharge_std = std_by_hour.loc[17:21].mean()

    st.markdown(
        f"**Uncertainty peaks where solar drives the forecast error.** The hours with "
        f"the highest forecast uncertainty (HE9-16, peaking at ~2,100 MW std dev) "
        f"coincide with the solar ramp-up and ramp-down. These are also the hours "
        f"when prices are falling as solar floods the grid (HE10-15 average "
        f"**${charge_price:.0f}/MWh**). Batteries charge during these cheap hours. "
        f"IR capacity held for these high-uncertainty hours directly competes with "
        f"the charging opportunity.\n\n"
        f"**Evening and overnight hours have low uncertainty but higher prices.** "
        f"HE17-21 average **${discharge_price:.0f}/MWh** with only "
        f"**{discharge_std:,.0f} MW** std dev of forecast error. The early morning hours "
        f"(HE1-6) have the highest prices in this dataset. The IR requirement for these "
        f"low-uncertainty hours would be small, but under the new product it's still "
        f"set at P97.5.\n\n"
        f"**A battery that can't fully charge can't fully discharge.** If IR holds back "
        f"capacity during the cheap midday hours, the battery stores less energy. That "
        f"constraint cascades: less stored energy means less to sell during the high-price "
        f"hours. Under RUC, operators targeted coverage at specific hours and chose the "
        f"percentile based on conditions. They applied P97.5 to all hours on just one day "
        f"in Q3 2024 (August 6). The new IR product applies P97.5 to all hours of all days."
    )


# ---------------------------------------------------------------------------
st.divider()
st.caption(
    "Data: CAISO OASIS via gridstatus | Period: Jan 2024 – Dec 2025 "
)
