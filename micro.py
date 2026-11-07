"""
micro.py - الاقتصاد الجزئي وهيكل الأسواق (شركات، قطاعات، اتجاه الأسعار)
المصدر: Yahoo Finance عبر yfinance (مجاني، غير رسمي، وقد يتعطل أحياناً)
"""
import numpy as np
import pandas as pd

SECTORS = {"XLK": "التقنية", "XLF": "المالية", "XLE": "الطاقة", "XLV": "الصحة",
           "XLY": "السلع الكمالية", "XLP": "السلع الأساسية", "XLI": "الصناعة",
           "XLU": "المرافق", "XLB": "المواد", "XLRE": "العقارات", "XLC": "الاتصالات"}
CYCLICAL = ["XLK", "XLY", "XLI", "XLF", "XLC", "XLB"]
DEFENSIVE = ["XLP", "XLU", "XLV", "XLRE"]
TRACK = {"GOLD": "GC=F", "SPX": "^GSPC", "NASDAQ": "^IXIC", "USD": "DX-Y.NYB",
         "EURUSD": "EURUSD=X", "GBPUSD": "GBPUSD=X", "USDJPY": "JPY=X",
         "AUDUSD": "AUDUSD=X", "USDCAD": "CAD=X", "USDCHF": "CHF=X"}
MEGA = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "UNH",
        "V", "MA", "HD", "PG", "COST", "AVGO", "LLY", "JNJ", "WMT", "BAC"]
EXTRA = ["SPY", "RSP", "GDX"]


def fetch_micro_px():
    import yfinance as yf
    tickers = list(dict.fromkeys(list(TRACK.values()) + list(SECTORS) + EXTRA))
    px = yf.download(tickers, period="1y", auto_adjust=True, progress=False)["Close"]
    return px.ffill().dropna(how="all")


def earnings_stats():
    """نسبة الشركات الكبرى التي تفوقت أرباحها على التوقعات في آخر ربع."""
    import yfinance as yf
    beats, sur = [], []
    for t in MEGA:
        try:
            ed = yf.Ticker(t).earnings_dates.dropna(subset=["Reported EPS"])
            r = ed.sort_index(ascending=False).iloc[0]
            beats.append(bool(r["Reported EPS"] > r["EPS Estimate"]))
            sur.append(float(r["Surprise(%)"]))
        except Exception:
            continue
    if len(beats) < 5:
        return None
    return {"n": len(beats), "beat_rate": round(sum(beats) / len(beats), 2),
            "avg_surprise": round(float(np.mean(sur)), 1)}


def demo_micro():
    rng = np.random.default_rng(5)
    cols = list(dict.fromkeys(list(TRACK.values()) + list(SECTORS) + EXTRA))
    idx = pd.bdate_range(end="2026-11-06", periods=260)
    px = pd.DataFrame({c: 100 * np.cumprod(1 + rng.normal(0.0003, 0.01, 260)) for c in cols},
                      index=idx)
    return px, {"n": 20, "beat_rate": 0.8, "avg_surprise": 6.5}


def _blend(pairs):
    p = [(v, w) for v, w in pairs if v is not None]
    return float(sum(v * w for v, w in p) / sum(w for _, w in p)) if p else 0.0


def build_micro(px, earn):
    def col(t):
        if t in px:
            s = px[t].dropna()
            return s if len(s) > 70 else None
        return None

    def ret(t, n):
        s = col(t)
        return None if s is None else float(s.iloc[-1] / s.iloc[-1 - n] - 1)

    def trend(t):
        s = col(t)
        if s is None:
            return None
        r1, r3 = ret(t, 21), ret(t, 63)
        a50 = bool(s.iloc[-1] > s.iloc[-50:].mean())
        a200 = bool(s.iloc[-1] > s.iloc[-200:].mean()) if len(s) >= 200 else a50
        sc = (0.4 * np.tanh(r1 / 0.04) + 0.3 * np.tanh(r3 / 0.08)
              + 0.15 * (1 if a50 else -1) + 0.15 * (1 if a200 else -1))
        return float(np.clip(sc, -1, 1)), r1, r3, a50, a200, float(s.iloc[-1])

    spy3 = ret("SPY", 63)
    sectors = []
    for t, n in SECTORS.items():
        r1, r3 = ret(t, 21), ret(t, 63)
        if r1 is not None and r3 is not None and spy3 is not None:
            sectors.append({"n": n, "r1m": round(r1 * 100, 1), "rel3m": round((r3 - spy3) * 100, 1)})
    sectors.sort(key=lambda x: -x["rel3m"])

    cyc = [ret(t, 63) for t in CYCLICAL if ret(t, 63) is not None]
    dfn = [ret(t, 63) for t in DEFENSIVE if ret(t, 63) is not None]
    rot = float(np.tanh((np.mean(cyc) - np.mean(dfn)) / 0.05)) if cyc and dfn else 0.0
    rsp = ret("RSP", 63)
    breadth = float(np.tanh((rsp - spy3) / 0.03)) if rsp is not None and spy3 is not None else 0.0
    gdx, gold = ret("GDX", 63), ret("GC=F", 63)
    miners = float(np.tanh((gdx - gold) / 0.1)) if gdx is not None and gold is not None else None
    xlk = ret("XLK", 63)
    tech = float(np.tanh((xlk - spy3) / 0.05)) if xlk is not None and spy3 is not None else None
    es = None
    if earn:
        es = float(0.6 * np.tanh((earn["beat_rate"] - 0.7) / 0.15)
                   + 0.4 * np.tanh(earn["avg_surprise"] / 8))

    T = {a: trend(t) for a, t in TRACK.items()}
    tv = lambda a: T[a][0] if T.get(a) else None
    sc = {a: tv(a) for a in TRACK if tv(a) is not None}
    sc["GOLD"] = _blend([(tv("GOLD"), .7), (miners, .3)])
    sc["SPX"] = _blend([(tv("SPX"), .35), (es, .25), (rot, .2), (breadth, .2)])
    sc["NASDAQ"] = _blend([(tv("NASDAQ"), .4), (es, .25), (tech, .2), (rot, .15)])
    trends = [{"k": a, "p": round(v[5], 4), "r1m": round(v[1] * 100, 1), "r3m": round(v[2] * 100, 1),
               "a50": v[3], "a200": v[4]} for a, v in T.items() if v]
    det = {"sectors": sectors, "earnings": earn, "rotation": round(rot, 2),
           "breadth": round(breadth, 2), "miners": None if miners is None else round(miners, 2),
           "trends": trends}
    return {k: round(v, 3) for k, v in sc.items()}, det
