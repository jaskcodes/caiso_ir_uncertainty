"""
pull_data.py — CAISO data pipeline
====================================
Downloads CAISO data via gridstatus, computes net load forecast error.
Each dataset cached to CSV — re-runs skip completed downloads.

Usage:
    pip install -r requirements.txt
    python pull_data.py
"""

import logging
from pathlib import Path
import pandas as pd
import numpy as np
import gridstatus

DATA_DIR = Path("data")
DATA_DIR.mkdir(exist_ok=True)

START = "Jan 1, 2024"
END = "Dec 31, 2025"
LMP_HUBS = ["TH_NP15_GEN-APND", "TH_SP15_GEN-APND", "TH_ZP26_GEN-APND"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)
caiso = gridstatus.CAISO()


def cached(path):
    if path.exists():
        log.info(f"[cached] {path.name}")
        return pd.read_csv(path, parse_dates=[0])
    return None


def save(df, path):
    df.to_csv(path, index=False)
    log.info(f"[saved]  {path.name}  ({len(df):,} rows, {path.stat().st_size/1e6:.1f} MB)")


def find_col(df, *keywords):
    for col in df.columns:
        for kw in keywords:
            if kw.lower() in col.lower():
                return col
    return None


def pull_load_actual():
    p = DATA_DIR / "load_actual.csv"
    return cached(p) if cached(p) is not None else (lambda df: (save(df, p), df)[1])(
        caiso.get_load(start=START, end=END, verbose=False))


def pull_load_forecast():
    p = DATA_DIR / "load_forecast_dam.csv"
    if cached(p) is not None:
        return cached(p)
    df = caiso.get_load_forecast_day_ahead(date=START, end=END, sleep=5, verbose=False)
    df = df[df["TAC Area Name"] == "CA ISO-TAC"].drop(columns=["TAC Area Name"])
    save(df, p)
    return df


def pull_renewable_forecast():
    p = DATA_DIR / "renewable_forecast_dam.csv"
    if cached(p) is not None:
        return cached(p)
    df = caiso.get_renewables_forecast_dam(date=START, end=END, verbose=False)
    df = df[df["Location"] == "CAISO"].drop(columns=["Location"])
    save(df, p)
    return df


def pull_fuel_mix():
    p = DATA_DIR / "fuel_mix.csv"
    return cached(p) if cached(p) is not None else (lambda df: (save(df, p), df)[1])(
        caiso.get_fuel_mix(start=START, end=END, verbose=False))


def pull_dam_lmps():
    p = DATA_DIR / "dam_lmps.csv"
    return cached(p) if cached(p) is not None else (lambda df: (save(df, p), df)[1])(
        caiso.get_lmp(date=pd.Timestamp(START), end=pd.Timestamp(END),
                      market="DAY_AHEAD_HOURLY", locations=LMP_HUBS, sleep=5, verbose=False))


def pull_as_prices():
    p = DATA_DIR / "as_clearing_prices_dam.csv"
    return cached(p) if cached(p) is not None else (lambda df: (save(df, p), df)[1])(
        caiso.get_oasis_dataset(dataset="as_clearing_prices", date=START, end=END,
                                params={"market_run_id": "DAM", "anc_type": "ALL",
                                        "anc_region": "AS_CAISO_EXP"},
                                raw_data=False, sleep=5, verbose=False))


def compute_net_load_error(load_actual, load_forecast, fuel_mix, ren_forecast):
    path = DATA_DIR / "net_load_uncertainty.csv"
    if path.exists():
        log.info(f"[cached] {path.name}")
        return

    log.info("Computing net load forecast error...")

    # Actuals → hourly
    la = load_actual.copy()
    tc = find_col(la, "time", "interval start") or la.columns[0]
    la[tc] = pd.to_datetime(la[tc], utc=True)
    lc = find_col(la, "load") or la.columns[1]
    load_h = la.set_index(tc)[[lc]].resample("h").mean().rename(columns={lc: "Load_Actual_MW"})

    # Actual renewables → hourly
    fm = fuel_mix.copy()
    ft = find_col(fm, "time") or fm.columns[0]
    fm[ft] = pd.to_datetime(fm[ft], utc=True)
    fm = fm.set_index(ft)
    sc, wc = find_col(fm, "solar"), find_col(fm, "wind")
    if sc and wc:
        ren_h = fm[[sc, wc]].resample("h").mean()
        ren_h.columns = ["Solar_Actual_MW", "Wind_Actual_MW"]
    else:
        ren_h = pd.DataFrame({"Solar_Actual_MW": 0, "Wind_Actual_MW": 0}, index=load_h.index)

    act = load_h.join(ren_h, how="inner")
    act["Net_Load_Actual_MW"] = act["Load_Actual_MW"] - act["Solar_Actual_MW"] - act["Wind_Actual_MW"]

    # DA forecasts
    lf = load_forecast.copy()
    lft = find_col(lf, "time", "interval start") or lf.columns[0]
    lf[lft] = pd.to_datetime(lf[lft], utc=True)
    lfv = find_col(lf, "load forecast", "forecast") or lf.columns[1]
    fcst = lf.set_index(lft)[[lfv]].rename(columns={lfv: "Load_Forecast_DAM_MW"})
    fcst = fcst[~fcst.index.duplicated(keep="first")]

    rf = ren_forecast.copy()
    if not rf.empty:
        rft = find_col(rf, "interval start", "time") or rf.columns[0]
        rf[rft] = pd.to_datetime(rf[rft], utc=True)
        rf = rf.set_index(rft)[~rf.set_index(find_col(rf, "interval start", "time") or rf.columns[0]).index.duplicated(keep="first")]
        rfs, rfw = find_col(rf, "solar"), find_col(rf, "wind")
        if rfs and rfw:
            ren_f = rf[[rfs, rfw]].copy()
            ren_f.columns = ["Solar_Forecast_DAM_MW", "Wind_Forecast_DAM_MW"]
        else:
            ren_f = pd.DataFrame({"Solar_Forecast_DAM_MW": 0, "Wind_Forecast_DAM_MW": 0}, index=fcst.index)
    else:
        ren_f = pd.DataFrame({"Solar_Forecast_DAM_MW": 0, "Wind_Forecast_DAM_MW": 0}, index=fcst.index)

    forecasts = fcst.join(ren_f, how="left").fillna(0)
    forecasts["Net_Load_Forecast_DAM_MW"] = (
        forecasts["Load_Forecast_DAM_MW"] - forecasts["Solar_Forecast_DAM_MW"] - forecasts["Wind_Forecast_DAM_MW"]
    )

    m = act.join(forecasts, how="inner")
    m["Net_Load_Error_MW"] = m["Net_Load_Actual_MW"] - m["Net_Load_Forecast_DAM_MW"]
    m = m.reset_index().rename(columns={m.index.name or "index": "Time"})
    m["Hour"] = m["Time"].dt.hour + 1
    m["Month"] = m["Time"].dt.month
    m["Season"] = m["Month"].map({
        12:"Winter",1:"Winter",2:"Winter",3:"Spring",4:"Spring",5:"Spring",
        6:"Summer",7:"Summer",8:"Summer",9:"Fall",10:"Fall",11:"Fall",
    })

    save(m, path)
    err = m["Net_Load_Error_MW"]
    log.info(f"  Mean={err.mean():+,.0f}  Std={err.std():,.0f}  P2.5={err.quantile(.025):+,.0f}  P97.5={err.quantile(.975):+,.0f}")


def main():
    log.info("CAISO IR Uncertainty — Data Pipeline")
    la = pull_load_actual()
    lf = pull_load_forecast()
    rf = pull_renewable_forecast()
    fm = pull_fuel_mix()
    pull_dam_lmps()
    pull_as_prices()
    compute_net_load_error(la, lf, fm, rf)
    log.info("\nDone.")
    for f in sorted(DATA_DIR.glob("*.csv")):
        log.info(f"  {f.name:<35s} {f.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
