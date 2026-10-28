"""
econ_calendar.py - تأثير الأخبار الاقتصادية المجدولة (Actual vs Forecast)
يعتمد على EXPOSURE من market_impact.py

python econ_calendar.py --demo
python econ_calendar.py --finnhub KEY   (قد يتطلب خطة مدفوعة حسب الحساب)
"""
import argparse
import numpy as np
from market_impact import EXPOSURE

# أي حدث يحرك أي عوامل؟ (الاتجاه: +1 = رقم أعلى يعني العامل أقوى)
RULES = [
    (("cpi", "inflation rate", "pce"), {"inflation": 1.0, "tightening": 0.6}),
    (("nonfarm", "payroll", "employment change"), {"growth": 1.0, "tightening": 0.4}),
    (("unemployment rate",), {"growth": -1.0, "tightening": -0.4}),
    (("interest rate decision", "fed funds"), {"tightening": 1.0}),
    (("retail sales", "gdp", "ism"), {"growth": 1.0, "tightening": 0.2}),
]


def surprise(actual, forecast):
    """مفاجأة نسبية بين -1 و +1."""
    if actual is None or forecast is None or forecast == 0:
        return 0.0
    return float(np.tanh((actual - forecast) / abs(forecast) * 6))


def event_impact(name, actual, forecast):
    s = surprise(actual, forecast)
    low = name.lower()
    for keys, factors in RULES:
        if any(k in low for k in keys):
            fx = {f: s * w for f, w in factors.items()}
            return {a: round(sum(ex.get(f, 0) * v for f, v in fx.items()), 3)
                    for a, ex in EXPOSURE.items()}
    return None  # حدث غير معروف: نتجاهله


def fetch_finnhub(key):
    import requests
    r = requests.get("https://finnhub.io/api/v1/calendar/economic",
                     params={"token": key}, timeout=20)
    r.raise_for_status()
    return [(e["event"], e.get("actual"), e.get("estimate"))
            for e in r.json().get("economicCalendar", [])
            if e.get("country") == "US" and e.get("actual") is not None]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--finnhub")
    a = ap.parse_args()
    events = ([("US CPI YoY", 3.4, 3.2), ("Nonfarm Payrolls", 150, 190)]
              if a.demo else fetch_finnhub(a.finnhub))
    for name, act, fc in events:
        imp = event_impact(name, act, fc)
        if imp:
            print(f"{name}: actual={act} forecast={fc} -> {imp}")
