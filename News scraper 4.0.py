#!/usr/bin/env python3
"""
Economic News Events Scraper (MyFXBook only)
- MyFXBook via export URL (CSV/XML) or best-effort HTML fallback
- Configurable dashboard timezone + source feed timezone (DST-safe)
- Tomorrow-only + High-impact-only view (no interactive prompts)
- Saves printed results to News.txt
"""

from __future__ import annotations
import os
import re, random
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple

import requests
from bs4 import BeautifulSoup
import pandas as pd
from datetime import datetime, timedelta, timezone
try:
    from zoneinfo import ZoneInfo  # py3.9+
except Exception:
    ZoneInfo = None

# --- Dashboard / runtime timezone resolution ---
def resolve_tz(tz_pref: str | None = "auto"):
    """
    Resolve a timezone from an IANA name (e.g., 'America/New_York'), 'auto'/'local'/'dashboard',
    or a fixed offset like 'UTC+3', 'GMT-04:30', '+02', '-0530'. Fallback: UTC.
    """
    if tz_pref is None or str(tz_pref).lower() in {"auto", "local", "dashboard"}:
        try:
            return datetime.now().astimezone().tzinfo
        except Exception:
            return timezone.utc

    if ZoneInfo:
        try:
            return ZoneInfo(tz_pref)
        except Exception:
            pass

    m = re.fullmatch(r'(?:(?:UTC|GMT))?([+-]\d{1,2})(?::?(\d{2}))?', str(tz_pref))
    if m:
        h = int(m.group(1)); mm = int(m.group(2) or 0)
        mm = mm if h >= 0 else -mm
        return timezone(timedelta(hours=h, minutes=mm))

    return timezone.utc

def tz_label(tz) -> str:
    return getattr(tz, "key", str(tz))

# Global runtime TZ (display/compare timezone)
TZ = resolve_tz(os.getenv("DASHBOARD_TZ", "auto"))
# Source timezone for feed times (default UTC). Override via --source-tz or MFB_SOURCE_TZ
SOURCE_TZ = resolve_tz(os.getenv("MFB_SOURCE_TZ", "UTC"))

# ----------------------------- Config ---------------------------------

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Connection": "keep-alive",
}
USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
]


# ---------------------------- Data types --------------------------------

@dataclass
class NewsEvent:
    source: str
    dt: pd.Timestamp   # tz-aware display TZ
    currency: str
    impact: str
    title: str


# ---------------------------- Scraper -----------------------------------

class EconomicNewsScraper:
    def __init__(self, myfxbook_export_url: str = "", source_tz=None):
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        self.myfxbook_export_url = myfxbook_export_url.strip()
        self.source_tz = source_tz if source_tz is not None else SOURCE_TZ

    def _safe_get(self, url: str) -> Optional[str]:
        try:
            self.session.headers["User-Agent"] = random.choice(USER_AGENTS)
            r = self.session.get(url, timeout=20, allow_redirects=True)
            if r.status_code != 200:
                return None
            return r.text
        except Exception:
            return None

    def get_myfxbook(self, start: str, end: str) -> List[NewsEvent]:
        if self.myfxbook_export_url:
            text = self._safe_get(self.myfxbook_export_url)
            if not text:
                return []
            if self.myfxbook_export_url.lower().endswith(".xml"):
                return self._mfb_from_xml(text, start, end)
            return self._mfb_from_csv(text, start, end)
        html = self._safe_get("https://www.myfxbook.com/forex-economic-calendar")
        return self._mfb_from_html(html, start, end) if html else []

    def _mfb_from_csv(self, csv_text: str, start: str, end: str) -> List[NewsEvent]:
        start_dt = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
        end_dt   = pd.Timestamp(end).tz_localize(TZ)   if TZ else pd.Timestamp(end)
        out: List[NewsEvent] = []
        for line in csv_text.splitlines():
            line = line.strip()
            if not line or line.lower().startswith("date"):
                continue
            cols = [c.strip() for c in re.split(r",|;", line)]
            if len(cols) < 5:
                continue
            d, tm, cur, imp, title = cols[:5]
            ts = pd.to_datetime(f"{d} {tm}", errors="coerce")
            if pd.isna(ts):
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
            tl = ts.tz_convert(TZ) if TZ else ts
            if not (start_dt <= tl <= end_dt):
                continue
            out.append(NewsEvent(
                source="MyFXBook",
                dt=tl,
                currency=cur or "UNK",
                impact=(imp or "Unknown").title(),
                title=title or "",
            ))
        return out

    def _mfb_from_xml(self, xml_text: str, start: str, end: str) -> List[NewsEvent]:
        from xml.etree import ElementTree as ET
        try:
            root = ET.fromstring(xml_text)
        except Exception:
            return []
        start_dt = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
        end_dt   = pd.Timestamp(end).tz_localize(TZ)   if TZ else pd.Timestamp(end)
        out: List[NewsEvent] = []
        for it in root.iterfind(".//item"):
            d = it.findtext("date") or ""
            tm = it.findtext("time") or "00:00"
            cur = it.findtext("currency") or "UNK"
            imp = it.findtext("impact") or "Unknown"
            title = it.findtext("title") or ""
            ts = pd.to_datetime(f"{d} {tm}", errors="coerce")
            if pd.isna(ts):
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
            tl = ts.tz_convert(TZ) if TZ else ts
            if not (start_dt <= tl <= end_dt):
                continue
            out.append(NewsEvent(source="MyFXBook", dt=tl, currency=cur, impact=imp.title(), title=title))
        return out

    def _mfb_from_html(self, html: str, start: str, end: str) -> List[NewsEvent]:
        soup = BeautifulSoup(html, "html.parser")
        out: List[NewsEvent] = []

        for tr in soup.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 4:
                continue
            texts = [td.get_text(strip=True) for td in tds]
            time_txt = next((t for t in texts if re.fullmatch(r"\d{1,2}:\d{2}", t)), "")
            cur = next((t for t in texts if re.fullmatch(r"[A-Z]{3}", t)), "")
            imp = next((t for t in texts if any(k in t.lower() for k in ("high","medium","low"))), "Unknown")
            if imp == "Unknown":
                try:
                    if tr.find(attrs={"class": re.compile(r"high", re.I)}) or tr.find(attrs={"title": re.compile(r"high", re.I)}):
                        imp = "High"
                    elif tr.find(attrs={"class": re.compile(r"med", re.I)}) or tr.find(attrs={"title": re.compile(r"med", re.I)}):
                        imp = "Medium"
                    elif tr.find(attrs={"class": re.compile(r"low", re.I)}) or tr.find(attrs={"title": re.compile(r"low", re.I)}):
                        imp = "Low"
                except Exception:
                    pass
            title = ""
            for t in texts:
                if len(t) > 8 and not re.fullmatch(r"[\d\.\,\%\-\+\s:APMapm]*", t):
                    title = t; break
            if not title:
                continue
            # discover date header, else fallback to caller's start date
            day_el = tr.find_previous(string=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"))
            day_str = str(day_el) if day_el else ""
            try:
                base_date = pd.to_datetime(re.sub(r"[^\w\s:-]", " ", day_str).strip(), errors="coerce")
                if pd.isna(base_date):
                    base_date = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
                ts = pd.to_datetime(f"{base_date.date()} {time_txt or '00:00'}")
                if ts.tzinfo is None:
                    ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
                tl = ts.tz_convert(TZ) if TZ else ts
            except Exception:
                continue
            out.append(NewsEvent(source="MyFXBook", dt=tl, currency=cur or "UNK", impact=imp.title(), title=title))

        if not out:
            return []
        start_dt = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
        end_dt   = pd.Timestamp(end).tz_localize(TZ)   if TZ else pd.Timestamp(end)
        return [e for e in out if start_dt <= e.dt <= end_dt]


# ---------------------------- Transform ---------------------------------

IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1, "Unknown": 0}

def parse_event_time(event_string):
    parts = event_string.split(", ")
    if len(parts) < 2:
        return None, None
    date_string = parts[0]
    time_string = parts[1]
    from datetime import datetime as _dt, time as _dtime
    try:
        date_obj = _dt.strptime(date_string, "%b %d").replace(year=_dt.now().year).date()
    except Exception:
        date_obj = None
    try:
        hours, minutes = map(int, time_string.split(":"))
        time_obj = _dtime(hours, minutes)
    except Exception:
        time_obj = None
    return date_obj, time_obj

def to_frame(events: List[NewsEvent]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=["source","date","currency","impact","event","dt","date_obj","time_obj"])
    rows = []
    for e in events:
        # work from tz-aware dt in display TZ
        dt_local = e.dt.tz_convert(TZ) if (hasattr(e.dt, "tz_convert") and TZ) else e.dt
        date_obj = dt_local.date()
        time_obj = dt_local.time()

        # try to rebuild dt from title if it has month + time
        months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']
        if ', ' in e.title and any(m in e.title for m in months):
            try:
                d_candidate, t_candidate = parse_event_time(e.title)
                if t_candidate is not None:
                    use_date = d_candidate or date_obj
                    combined = pd.Timestamp.combine(use_date, t_candidate)
                    src_tz = SOURCE_TZ or TZ
                    if src_tz is not None:
                        try:
                            combined = combined.tz_localize(src_tz)
                        except Exception:
                            pass
                    if TZ is not None:
                        try:
                            dt_local = combined.tz_convert(TZ)
                        except Exception:
                            dt_local = combined
                    else:
                        dt_local = combined
                    date_obj = dt_local.date()
                    time_obj = dt_local.time()
            except Exception:
                pass

        rows.append(dict(
            source=e.source,
            date=dt_local.strftime("%Y-%m-%d"),
            currency=e.currency,
            impact=e.impact,
            event=e.title,
            dt=dt_local,
            date_obj=date_obj,
            time_obj=time_obj,
        ))
    df = pd.DataFrame(rows).sort_values(["date_obj", "time_obj"])
    return df

def filter_events(df: pd.DataFrame,
                  start: str, end: str,
                  currencies: Optional[List[str]] = None,
                  high_only: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    if start_dt.tzinfo is None:
        start_dt = start_dt.tz_localize(TZ)
    if end_dt.tzinfo is None:
        end_dt = end_dt.tz_localize(TZ)
    mask = (df["dt"] >= start_dt) & (df["dt"] <= end_dt)
    if currencies:
        cset = set([c.strip().upper() for c in currencies])
        mask &= df["currency"].str.upper().isin(cset)
    if high_only:
        mask &= df["impact"].str.contains("High", case=False, na=False)
    return df.loc[mask].copy()

def build_windows(df: pd.DataFrame,
                  mins_before: Dict[str, int],
                  mins_after: Dict[str, int]) -> pd.DataFrame:
    if df.empty:
        return df
    def win(row):
        imp = str(row["impact"]).title()
        b = int(mins_before.get(imp, 10))
        a = int(mins_after.get(imp, 15))
        return row["dt"] - pd.Timedelta(minutes=b), row["dt"] + pd.Timedelta(minutes=a)
    ws, we = [], []
    for _, r in df.iterrows():
        s, e = win(r); ws.append(s); we.append(e)
    out = df.copy()
    out["window_start"] = ws
    out["window_end"]   = we
    return out


# ---------------------------- CLI / Demo --------------------------------

def main():
    lines_out = []
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--tz", default=os.getenv("DASHBOARD_TZ", "auto"),
                    help='Dashboard timezone: IANA (e.g. "Europe/London"), fixed offset (e.g. "UTC+3"), or "auto".')
    ap.add_argument("--start")
    ap.add_argument("--end")
    ap.add_argument("--currencies", default="USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD")
    ap.add_argument("--high-only", action="store_true", help="Keep only HIGH impact")
    ap.add_argument("--mfb-export-url", default="", help="Optional MyFXBook CSV/XML export URL")
    ap.add_argument("--source-tz", default=os.getenv("MFB_SOURCE_TZ", "UTC"), help="Timezone of source feed, e.g. 'UTC', 'Europe/London', or 'local'")
    ap.add_argument("--save", action="store_true", help="Save combined CSV")
    args = ap.parse_args()

    global TZ
    TZ = resolve_tz(args.tz)

    if not args.start:
        args.start = pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d")
    if not args.end:
        args.end = (pd.Timestamp.now(tz=TZ)+pd.Timedelta(days=7)).strftime("%Y-%m-%d")

    src_tz = resolve_tz(None if str(args.source_tz).lower() == "local" else args.source_tz)
    scraper = EconomicNewsScraper(myfxbook_export_url=args.mfb_export_url, source_tz=src_tz)

    # Force next-day window and HIGH impact only
    _now = pd.Timestamp.now(tz=TZ)
    _start_local = (_now + pd.Timedelta(days=1)).normalize()
    _end_local = _start_local + pd.Timedelta(days=1) - pd.Timedelta(seconds=1)
    args.start = _start_local.strftime("%Y-%m-%d %H:%M")
    args.end = _end_local.strftime("%Y-%m-%d %H:%M")
    args.high_only = True

    print(f"Fetching {args.start} -> {args.end} ({tz_label(TZ)})… Source: MyFXBook")
    mfb = scraper.get_myfxbook(args.start, args.end)
    df = to_frame(mfb)

    if df.empty:
        print("No events collected (check connectivity / site anti-bot / export URL).")
        return

    # Apply filters (enforce high-only)
    df = filter_events(
        df,
        args.start, args.end,
        currencies=[c.strip().upper() for c in args.currencies.split(",") if c.strip()],
        high_only=True
    )

    mins_before = {"High": 20, "Medium": 15, "Low": 10}
    mins_after  = {"High": 30, "Medium": 20, "Low": 15}
    df = build_windows(df, mins_before, mins_after)

    if df.empty:
        print("No events after filters.")
        return

    cur_day = None
    for _, r in df.sort_values(["date_obj", "time_obj"]).iterrows():
        day_str = r["date_obj"].isoformat()
        print(f"  {r['currency']:>3} | {r['date_obj']} {r['time_obj']}")
        lines_out.append(f"{r['time_obj']} | {r['currency']} ")

    # Save textual output to News.txt
    try:
        out_txt = r"C:\\Users\\sossi\\Desktop\\Trading\\NEWS PROP FIRMS\\News.txt"
        with open(out_txt, "w", encoding="utf-8") as f:
            f.write("\n".join(lines_out) + "\n")
        print(f"\nSaved to {out_txt}")
    except Exception as ex:
        print(f"\nCould not save News.txt: {ex}")

    if args.save:
        out = f"economic_events_{_start_local.strftime('%Y-%m-%d')}.csv"
        df.drop(columns=["dt"]).to_csv(out, index=False)
        print(f"Saved -> {out}")


if __name__ == "__main__":
    main()

