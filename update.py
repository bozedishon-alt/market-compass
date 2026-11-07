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
import numpy as np
import pandas as pd

from market_impact import (EXPOSURE, analyze, demo_inputs, fetch_cot, fetch_fred,
                           fetch_headlines, squash, zlast)

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



# id, المجموعة, الاسم, التحويل, الوحدة, الشرح, أوزان العوامل
MACRO_DEFS = [
 ("CPIAUCSL","التضخم","التضخم العام (CPI)","yoy12","%","ارتفاع الأسعار مقارنة بالسنة الماضية.",{"inflation":1,"tightening":0.6}),
 ("CPILFESL","التضخم","التضخم الأساسي","yoy12","%","بدون الغذاء والطاقة، ويكشف الضغط الحقيقي على الأسعار.",{"inflation":1,"tightening":0.6}),
 ("PCEPILFE","التضخم","تضخم PCE الأساسي","yoy12","%","المقياس المفضل لدى الفيدرالي في قراراته.",{"inflation":1,"tightening":0.7}),
 ("PPIACO","التضخم","أسعار المنتجين (PPI)","yoy12","%","تكلفة السلع عند المصنع، وغالباً تسبق ارتفاع أسعار المستهلك.",{"inflation":0.7,"tightening":0.3}),
 ("CES0500000003","التضخم","نمو الأجور","yoy12","%","ارتفاع الأجور يدعم الإنفاق لكنه يغذي التضخم.",{"inflation":0.6,"growth":0.3,"tightening":0.3}),
 ("T10YIE","التضخم","توقعات التضخم (10 سنوات)","level","%","ما يتوقعه السوق للتضخم مستقبلاً.",{"inflation":1}),
 ("DCOILWTICO","التضخم","النفط (WTI)","level","$","ارتفاعه يرفع التضخم ويعكس توتراً عالمياً.",{"inflation":0.6,"risk_off":0.3}),
 ("PAYEMS","سوق العمل","الوظائف الجديدة (شهرياً)","diff1","ألف","عدد الوظائف المضافة، وهو أهم رقم يتابعه السوق.",{"growth":1,"tightening":0.3}),
 ("UNRATE","سوق العمل","معدل البطالة","level","%","ارتفاعه يعني ضعف الاقتصاد.",{"growth":-1,"tightening":-0.3}),
 ("ICSA","سوق العمل","طلبات إعانة البطالة","level","ألف","إنذار مبكر: ارتفاعها يعني زيادة التسريحات.",{"growth":-0.7}),
 ("JTSJOL","سوق العمل","الوظائف الشاغرة","level","ألف","مدى حاجة الشركات للتوظيف.",{"growth":0.6,"tightening":0.3}),
 ("A191RL1Q225SBEA","النمو","نمو الاقتصاد (GDP)","level","%","نمو الناتج المحلي ربع سنوي بمعدل سنوي.",{"growth":1,"tightening":0.3}),
 ("RSAFS","النمو","مبيعات التجزئة (شهرياً)","mom","%","إنفاق المستهلكين وهو محرك الاقتصاد الأمريكي.",{"growth":1,"tightening":0.2}),
 ("INDPRO","النمو","الإنتاج الصناعي","yoy12","%","نشاط المصانع والتعدين.",{"growth":0.8}),
 ("HOUST","النمو","بدء بناء المنازل","level","ألف","قطاع حساس جداً لأسعار الفائدة.",{"growth":0.6}),
 ("UMCSENT","النمو","ثقة المستهلك","level","نقطة","مزاج الناس تجاه الاقتصاد، ويسبق الإنفاق.",{"growth":0.6}),
 ("FEDFUNDS","السياسة النقدية","سعر الفائدة الأمريكية","level","%","الفائدة الأساسية التي يحددها الفيدرالي.",{"tightening":1}),
 ("DGS2","السياسة النقدية","عائد سندات سنتين","level","%","يعكس توقعات السوق لمسار الفائدة.",{"tightening":1}),
 ("DFII10","السياسة النقدية","العائد الحقيقي (10 سنوات)","level","%","العائد بعد خصم التضخم، وهو أكبر عدو للذهب.",{"tightening":1}),
 ("WALCL","السياسة النقدية","ميزانية الفيدرالي (سنوياً)","yoy52","%","انكماشها يسحب السيولة من الأسواق.",{"tightening":-0.6}),
 ("M2SL","السياسة النقدية","عرض النقود M2 (سنوياً)","yoy12","%","كمية النقود المتداولة في الاقتصاد.",{"tightening":-0.5,"inflation":0.3}),
 ("T10Y2Y","المخاطر والأسواق","منحنى العائد (10 سنوات − سنتان)","level","نقطة","إذا صار سالباً فهو إنذار تقليدي بالركود.",{"growth":0.8}),
 ("BAMLH0A0HYM2","المخاطر والأسواق","فروق ائتمان الشركات الضعيفة","level","%","اتساعها علامة على توتر مالي.",{"risk_off":1,"growth":-0.4}),
 ("VIXCLS","المخاطر والأسواق","مؤشر الخوف (VIX)","level","نقطة","ارتفاعه يعني قلقاً في الأسواق.",{"risk_off":1}),
 ("DTWEXBGS","المخاطر والأسواق","مؤشر الدولار الواسع","level","نقطة","قوة الدولار تشدد الأوضاع المالية عالمياً.",{"tightening":0.5,"risk_off":0.2}),
]


def fetch_macro():
    from pandas_datareader import data as pdr
    out = {}
    for sid, *_ in MACRO_DEFS:
        try:
            out[sid] = pdr.DataReader(sid, "fred", "2019-01-01")[sid]
        except Exception as e:
            print("تحذير:", sid, e)
    return out


def demo_macro():
    rng = np.random.default_rng(3)
    daily = {"DGS2", "T10YIE", "DCOILWTICO", "T10Y2Y", "BAMLH0A0HYM2", "VIXCLS", "DTWEXBGS"}
    weekly = {"ICSA", "WALCL"}
    out = {}
    for sid, *_ in MACRO_DEFS:
        n, fr = (1500, "B") if sid in daily else (380, "W") if sid in weekly else (84, "MS")
        idx = pd.date_range("2019-01-01", periods=n, freq=fr)
        out[sid] = pd.Series(100 + np.cumsum(rng.normal(0.1, 1, n)), idx)
    return out


def transform(s, mode):
    s = s.dropna()
    if mode == "yoy12":
        return (s.pct_change(12) * 100).dropna()
    if mode == "yoy52":
        return (s.pct_change(52) * 100).dropna()
    if mode == "mom":
        return (s.pct_change() * 100).dropna()
    if mode == "diff1":
        return s.diff().dropna()
    return s


def macro_table(macro):
    rows, acc = [], {}
    for sid, grp, name, mode, unit, desc, w in MACRO_DEFS:
        s = macro.get(sid)
        if s is None or len(s) < 5:
            continue
        t = transform(s, mode)
        gap = t.index.to_series().diff().dt.days.median() if len(t) > 5 else 30
        lag = 21 if gap <= 3 else 4 if gap <= 8 else 1
        if len(t) <= lag + 5:
            continue
        a, f = float(t.iloc[-1]), float(t.iloc[-1 - lag])
        sc = squash(zlast(t.diff(lag), 60))
        imp = {k: round(sum(ex.get(fk, 0) * wv * sc for fk, wv in w.items()), 3)
               for k, ex in EXPOSURE.items()}
        for fk, wv in w.items():
            n, d = acc.get(fk, (0.0, 0.0))
            acc[fk] = (n + wv * sc, d + abs(wv))
        rows.append({"g": grp, "n": name, "a": round(a, 2), "f": round(f, 2), "u": unit,
                     "d": desc, "s": round(sc, 2), "imp": imp,
                     "as_of": str(t.index[-1].date())})
    extra = {k: n / d for k, (n, d) in acc.items() if d}
    names = [("inflation", "التضخم"), ("growth", "النمو"),
             ("tightening", "التشدد النقدي"), ("risk_off", "المخاطر")]
    summ = [{"k": k, "n": n, "v": round(extra.get(k, 0), 3)} for k, n in names]
    return rows, summ, extra


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

    macro = demo_macro() if a.demo else safe(fetch_macro, {})
    mrows, msumm, extra = macro_table(macro)
    df = analyze(fred, cot_df, heads, fed_text, extra or None)
    payload = {
        "demo": a.demo,
        "updated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "assets": json.loads(df.to_json(orient="records")),
        "events": fred_events(fred),
        "macro": mrows,
        "macro_summary": msumm,
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
