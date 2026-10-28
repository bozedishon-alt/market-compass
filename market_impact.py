"""
market_impact.py - Market Impact Engine (starter)
يقرأ: COT + Macro (FRED) + Fed + أخبار جيوسياسية
ويطلع لكل أصل: Score من -1 إلى +1 وإشارة (Bullish / Neutral / Bearish)

التثبيت:  pip install pandas numpy pandas_datareader cot_reports openpyxl requests
التشغيل:  python market_impact.py --demo          (بيانات تجريبية بدون إنترنت)
          python market_impact.py --newsapi KEY    (بيانات حية)
"""
import argparse
import re
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

# ───────────────────────── 1) الإعدادات ─────────────────────────
# حساسية كل أصل لكل عامل (افتراضات أولية، لازم تنضبط بالـ Backtest)
EXPOSURE = {
    #          inflation growth tightening risk_off
    "GOLD": {"inflation": 0.3, "growth": -0.1, "tightening": -0.6, "risk_off": 0.6},
    "USD":  {"inflation": 0.2, "growth": 0.3,  "tightening": 0.6,  "risk_off": 0.3},
    "SPX":  {"inflation": -0.2, "growth": 0.5, "tightening": -0.5, "risk_off": -0.6},
}
COT_MARKET = {  # جزء من اسم العقد في تقرير COT
    "GOLD": "GOLD - COMMODITY EXCHANGE",
    "USD": "USD INDEX",
    "SPX": "E-MINI S&P 500",
}
WEIGHTS = {"cot": 0.25, "macro": 0.30, "fed": 0.20, "news": 0.25}
THRESHOLD = 0.20  # بين -0.2 و +0.2 = Neutral

HAWKISH = ["inflation remains elevated", "further tightening", "restrictive",
           "higher for longer", "additional firming", "upside risks", "rate hike"]
DOVISH = ["rate cut", "easing", "accommodative", "labor market has cooled",
          "downside risks", "patient", "softening", "lower rates"]

RISK_ON_CUES = ["war", "invasion", "missile", "attack", "sanctions", "escalat",
                "tensions", "strike on", "conflict", "blockade"]
DEESCALATION = ["ceasefire", "truce", "de-escalat", "peace talks", "peace deal",
                "sanctions lifted", "agreement reached"]


# ───────────────────────── 2) أدوات مساعدة ─────────────────────────
def squash(x):
    return float(np.tanh(x / 2))


def zlast(s, win=60):
    """Z-score لآخر قيمة مقابل آخر win قيمة."""
    s = s.dropna()
    if len(s) < max(10, win // 2):
        return 0.0
    tail = s.iloc[-win:]
    sd = tail.std()
    return 0.0 if sd == 0 else float((s.iloc[-1] - tail.mean()) / sd)


def has(text, phrase):
    return re.search(r"\b" + re.escape(phrase), text.lower()) is not None


# ───────────────────────── 3) جلب البيانات ─────────────────────────
def fetch_fred(start="2018-01-01"):
    from pandas_datareader import data as pdr
    ids = ["CPIAUCSL", "UNRATE", "FEDFUNDS", "T10Y2Y", "DFII10"]
    return {i: pdr.DataReader(i, "fred", start)[i] for i in ids}


def fetch_cot(years=4):
    import cot_reports as cot
    y = datetime.now().year
    frames = [cot.cot_year(yr, cot_report_type="legacy_fut")
              for yr in range(y - years + 1, y + 1)]
    return pd.concat(frames, ignore_index=True)


def fetch_headlines(api_key, query="war OR sanctions OR ceasefire OR Fed OR inflation"):
    import requests
    r = requests.get("https://newsapi.org/v2/everything", timeout=20, params={
        "q": query, "language": "en", "sortBy": "publishedAt",
        "pageSize": 100, "apiKey": api_key})
    r.raise_for_status()
    out = []
    for a in r.json().get("articles", []):
        ts = datetime.fromisoformat(a["publishedAt"].replace("Z", "+00:00"))
        out.append((ts, a["title"] or ""))
    return out


# ───────────────────────── 4) حساب العوامل والـ Scores ─────────────────────────
def macro_factors(fred):
    """يحول البيانات الاقتصادية إلى عوامل محايدة بين -1 و +1."""
    cpi_yoy = fred["CPIAUCSL"].pct_change(12) * 100
    inflation = squash(zlast(cpi_yoy.diff(3)))               # + = تضخم يسخن

    labor = squash(-zlast(fred["UNRATE"].diff(3)))           # + = سوق عمل أقوى
    curve = float(np.clip(fred["T10Y2Y"].dropna().iloc[-1], -1, 1))  # سالب = مقلوب
    growth = 0.7 * labor + 0.3 * curve

    real_yield = squash(zlast(fred["DFII10"].diff(20)))      # + = عوائد حقيقية ترتفع
    return {"inflation": inflation, "growth": growth, "tight_real": real_yield}


def fed_factor(fred, fed_text=""):
    """التشدد النقدي: اتجاه الفائدة + نبرة البيان (Hawkish/Dovish)."""
    ff_change = float(fred["FEDFUNDS"].diff(6).dropna().iloc[-1])
    ff_score = float(np.clip(ff_change / 0.5, -1, 1))
    h = sum(has(fed_text, p) for p in HAWKISH)
    d = sum(has(fed_text, p) for p in DOVISH)
    text_score = 0.0 if h + d == 0 else (h - d) / (h + d)
    return 0.5 * ff_score + 0.5 * text_score if fed_text else ff_score


def news_risk_off(headlines, half_life_h=24):
    """Risk-off من -1 إلى +1 مع Decay أسي حسب عمر الخبر."""
    now = datetime.now(timezone.utc)
    total = 0.0
    for ts, title in headlines:
        age_h = max((now - ts).total_seconds() / 3600, 0)
        w = 0.5 ** (age_h / half_life_h)
        up = any(has(title, k) for k in RISK_ON_CUES)
        down = any(has(title, k) for k in DEESCALATION)
        total += w * (1 if up else 0) - w * (1 if down else 0)
    return squash(total / 3)


def cot_score(cot_df, market_key, window=156):
    m = cot_df[cot_df["Market and Exchange Names"].str.contains(market_key, regex=False)]
    if m.empty:
        return 0.0, None, False
    m = m.sort_values("As of Date in Form YYYY-MM-DD")
    net = (m["Noncommercial Positions-Long (All)"]
           - m["Noncommercial Positions-Short (All)"]).reset_index(drop=True)
    win = net.iloc[-window:]
    idx = float((win < win.iloc[-1]).mean() * 100)           # COT Index (Percentile)
    mom = squash(zlast(net.diff(4)))                         # زخم 4 أسابيع
    score = 0.7 * (idx - 50) / 50 + 0.3 * mom
    crowded = idx > 90 or idx < 10                           # مراكز متطرفة
    return float(np.clip(score, -1, 1)), idx, crowded


# ───────────────────────── 5) التجميع والإشارة ─────────────────────────
def label(x):
    return "Bullish 🟢" if x > THRESHOLD else "Bearish 🔴" if x < -THRESHOLD else "Neutral ⚪"


def analyze(fred, cot_df, headlines, fed_text=""):
    mf = macro_factors(fred)
    tight_fed = fed_factor(fred, fed_text)
    risk_off = news_risk_off(headlines)
    rows = []
    for asset, ex in EXPOSURE.items():
        macro = (ex["inflation"] * mf["inflation"] + ex["growth"] * mf["growth"]
                 + ex["tightening"] * mf["tight_real"])
        fed = ex["tightening"] * tight_fed
        news = ex["risk_off"] * risk_off
        cot, idx, crowded = cot_score(cot_df, COT_MARKET[asset])
        parts = {"cot": cot, "macro": macro, "fed": fed, "news": news}
        total = sum(WEIGHTS[k] * v for k, v in parts.items())
        rows.append({"Asset": asset, **{k.upper(): round(v, 3) for k, v in parts.items()},
                     "TOTAL": round(total, 3), "Signal": label(total),
                     "COT_Index": None if idx is None else round(idx, 1),
                     "Crowded": crowded})
    return pd.DataFrame(rows)


# ───────────────────────── 6) بيانات تجريبية ─────────────────────────
def demo_inputs():
    rng = np.random.default_rng(7)
    m = pd.date_range("2019-01-01", periods=84, freq="MS")
    d = pd.date_range("2019-01-01", periods=1500, freq="B")
    fred = {
        "CPIAUCSL": pd.Series(250 * np.cumprod(1 + rng.normal(0.003, 0.002, 84)), m),
        "UNRATE": pd.Series(4 + np.cumsum(rng.normal(0, 0.1, 84)), m),
        "FEDFUNDS": pd.Series(np.linspace(0.1, 5, 84), m),
        "T10Y2Y": pd.Series(np.linspace(1, -0.3, 1500), d),
        "DFII10": pd.Series(np.cumsum(rng.normal(0.003, 0.03, 1500)), d),
    }
    weeks = pd.date_range("2021-01-05", periods=200, freq="W-TUE")
    rows = []
    for key, base in [("GOLD - COMMODITY EXCHANGE INC.", 150000),
                      ("USD INDEX - ICE FUTURES U.S.", 30000),
                      ("E-MINI S&P 500 - CHICAGO MERCANTILE EXCHANGE", 50000)]:
        L = base + np.cumsum(rng.normal(0, base * 0.02, 200))
        S = base * 0.6 + np.cumsum(rng.normal(0, base * 0.015, 200))
        rows.append(pd.DataFrame({
            "Market and Exchange Names": key,
            "As of Date in Form YYYY-MM-DD": weeks.strftime("%Y-%m-%d"),
            "Noncommercial Positions-Long (All)": L,
            "Noncommercial Positions-Short (All)": S}))
    cot_df = pd.concat(rows, ignore_index=True)
    now = datetime.now(timezone.utc)
    heads = [(now - timedelta(hours=2), "Missile attack escalates tensions in region"),
             (now - timedelta(hours=10), "Sanctions expanded on major exporter"),
             (now - timedelta(hours=30), "Ceasefire talks resume")]
    fed_text = "Inflation remains elevated and policy will stay restrictive, higher for longer."
    return fred, cot_df, heads, fed_text


# ───────────────────────── 7) التشغيل ─────────────────────────
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--newsapi", help="NewsAPI key")
    ap.add_argument("--fed-text", default="", help="نص بيان الفيدرالي الأخير")
    ap.add_argument("--out", default="market_impact_report.xlsx")
    a = ap.parse_args()

    if a.demo:
        fred, cot_df, heads, fed_text = demo_inputs()
    else:
        fred, cot_df = fetch_fred(), fetch_cot()
        heads = fetch_headlines(a.newsapi) if a.newsapi else []
        fed_text = a.fed_text

    res = analyze(fred, cot_df, heads, fed_text)
    print(res.to_string(index=False))
    res.to_excel(a.out, index=False)
    print(f"\nSaved → {a.out}")


if __name__ == "__main__":
    main()
