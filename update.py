"""
update.py - يجلب كل شيء تلقائياً ويكتب docs/latest.json (يقرؤه الموقع)
المصادر: COT (CFTC) + FRED + GDELT/NewsAPI + بيان الفيدرالي (federalreserve.gov)
التجربة بدون إنترنت:  python update.py --demo
"""
import argparse
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from econ_calendar import event_impact
from market_impact import analyze, demo_inputs, fetch_cot, fetch_fred, fetch_headlines

OUT = Path("docs")
UA = {"User-Agent": "Mozilla/5.0 (market-compass)"}

EVENT_DEFS = [
    ("CPIAUCSL", "التضخم السنوي الأمريكي (CPI)", "US CPI",
     "التضخم أعلى من القراءة السابقة: الأسعار ترتفع أسرع، فتميل الفائدة للبقاء مرتفعة.",
     "التضخم أقل من القراءة السابقة: ضغط الأسعار يخف."),
    ("UNRATE", "معدل البطالة الأمريكي", "Unemployment Rate",
     "البطالة ارتفعت: سوق العمل يضعف وهذا يقلق المستثمرين.",
     "البطالة انخفضت أو ثبتت: سوق العمل متماسك."),
]


def safe(fn, default):
    try:
        return fn()
    except Exception as e:  # لا نوقف التحديث بسبب مصدر واحد
        print("تحذير:", fn.__name__ if hasattr(fn, "__name__") else "source", e)
        return default


def gdelt_headlines():
    import requests
    q = "(war OR sanctions OR ceasefire OR missile OR escalation OR truce) sourcelang:english"
    r = requests.get("https://api.gdeltproject.org/api/v2/doc/doc", timeout=40, headers=UA,
                     params={"query": q, "mode": "artlist", "format": "json",
                             "maxrecords": 75, "timespan": "1d"})
    out = []
    for a in r.json().get("articles", []):
        ts = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        out.append((ts, a.get("title", "")))
    return out


def fed_statement():
    import requests
    base = "https://www.federalreserve.gov"
    html = requests.get(base + "/newsevents/pressreleases.htm", timeout=40, headers=UA).text
    links = sorted(set(re.findall(r"/newsevents/pressreleases/monetary\d{8}a\.htm", html)))
    if not links:
        return ""
    page = requests.get(base + links[-1], timeout=40, headers=UA).text
    return re.sub(r"<[^>]+>", " ", page)


def fred_events(fred):
    ev = []
    for sid, ar, key, up, down in EVENT_DEFS:
        s = fred[sid].dropna()
        if sid == "CPIAUCSL":
            s = (s.pct_change(12) * 100).dropna()
        if len(s) < 2:
            continue
        a, f = round(float(s.iloc[-1]), 2), round(float(s.iloc[-2]), 2)
        ev.append({"n": ar, "a": a, "f": f, "u": "%", "txt": up if a > f else down,
                   "imp": event_impact(key, a, f) or {}})
    return ev


def snapshot(fred):
    g = lambda k: float(fred[k].dropna().iloc[-1])
    return [{"k": "سعر الفائدة الأمريكية", "v": f"{g('FEDFUNDS'):.2f}%"},
            {"k": "عائد السندات الحقيقي (10 سنوات)", "v": f"{g('DFII10'):.2f}%"},
            {"k": "منحنى العائد (10 سنوات − سنتان)", "v": f"{g('T10Y2Y'):.2f}"}]


def telegram(text):
    import requests
    token, chat = os.getenv("TELEGRAM_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if token and chat:
        requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
                      data={"chat_id": chat, "text": text}, timeout=20)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    a = ap.parse_args()

    if a.demo:
        fred, cot_df, heads, fed_text = demo_inputs()
    else:
        key = os.getenv("NEWSAPI_KEY")
        fred, cot_df = fetch_fred(), fetch_cot()
        heads = safe(lambda: fetch_headlines(key), []) if key else safe(gdelt_headlines, [])
        fed_text = safe(fed_statement, "")

    df = analyze(fred, cot_df, heads, fed_text)
    payload = {
        "demo": a.demo,
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "assets": json.loads(df.to_json(orient="records")),
        "events": fred_events(fred),
        "snapshot": snapshot(fred),
        "sources": {"headlines": len(heads), "fed_text": bool(fed_text)},
    }
    OUT.mkdir(exist_ok=True)
    old_p = OUT / "state.json"
    old = json.loads(old_p.read_text()) if old_p.exists() else {}
    now = {r["Asset"]: r["Signal"] for r in payload["assets"]}
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False))
    old_p.write_text(json.dumps(now, ensure_ascii=False))
    if now != old and not a.demo:
        telegram("🧭 بوصلة السوق\n" + "\n".join(f"{k}: {v}" for k, v in now.items()))
    print(json.dumps(now, ensure_ascii=False), payload["sources"])


if __name__ == "__main__":
    main()
