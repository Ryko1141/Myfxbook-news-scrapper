#!/usr/bin/env python3
"""
Economic News Events Scraper (MyFXBook only)
- MyFXBook via export URL (CSV/XML) or best-effort HTML fallback
- Europe/London timezone, per-impact windows, high-impact filter
- Added: Filter events by minutes into the future
"""

from __future__ import annotations
import os
import re, random
from dataclasses import dataclass
import time
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
    # auto/local/dashboard => system local tz (proxy for your dashboard)
    if tz_pref is None or str(tz_pref).lower() in {"auto", "local", "dashboard"}:
        try:
            return datetime.now().astimezone().tzinfo
        except Exception:
            return timezone.utc

    # IANA tz via zoneinfo
    if ZoneInfo:
        try:
            return ZoneInfo(tz_pref)
        except Exception:
            pass

    # Fixed-offset parser
    m = re.fullmatch(r'(?:(?:UTC|GMT))?([+-]\d{1,2})(?::?(\d{2}))?', str(tz_pref))
    if m:
        h = int(m.group(1)); mm = int(m.group(2) or 0)
        mm = mm if h >= 0 else -mm
        return timezone(timedelta(hours=h, minutes=mm))

    return timezone.utc

def tz_label(tz) -> str:
    # Try to show a friendly name; .key is present for ZoneInfo
    return getattr(tz, "key", str(tz))

# Global runtime TZ (display/compare timezone). Default: system local.
TZ = resolve_tz(os.getenv("DASHBOARD_TZ", "auto"))

# Source timezone for calendar data (what timezone MyFXBook provides times in).
# Many feeds/exported files are UTC; if your feed is already local, pass --source-tz local
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
    dt: pd.Timestamp   
    currency: str
    impact: str        # Low, Medium, High
    title: str

# ---------------------------- Scraper -----------------------------------

class EconomicNewsScraper:
    def __init__(self, myfxbook_export_url: str = "", source_tz=None):
        self.s = requests.Session()
        self.s.headers.update(DEFAULT_HEADERS)
        self.myfxbook_export_url = myfxbook_export_url.strip()
        # Timezone the source data is expressed in (e.g., UTC)
        self.source_tz = source_tz if source_tz is not None else SOURCE_TZ

    def _rotate_headers(self):
        self.s.headers["User-Agent"] = random.choice(USER_AGENTS)

    # ---------- MyFXBook ----------
    def get_myfxbook(self, start: str, end: str) -> List[NewsEvent]:
        """Prefer a direct export URL (CSV/XML). If not set, try HTML fallback."""
        if self.myfxbook_export_url:
            text = self._safe_get(self.myfxbook_export_url)
            if not text:
                return []
            if self.myfxbook_export_url.lower().endswith(".xml"):
                return self._mfb_from_xml(text, start, end)
            return self._mfb_from_csv(text, start, end)
        # HTML fallback (brittle; kept as last resort)
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
            # Localize parsed naive timestamp to source timezone, then convert to runtime TZ
            if ts.tzinfo is None:
                ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
            tl = (ts.tz_convert(TZ) if TZ else ts)
            if not (start_dt <= tl <= end_dt):
                continue
            out.append(NewsEvent(
                source="MyFXBook", dt=tl,
                currency=cur.upper(), impact=imp.title(), title=title,
            ))
        return out

    def _mfb_from_xml(self, xml: str, start: str, end: str) -> List[NewsEvent]:
        start_dt = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
        end_dt   = pd.Timestamp(end).tz_localize(TZ)   if TZ else pd.Timestamp(end)
        out: List[NewsEvent] = []
        # Very light XML parsing (no external deps)
        for node in re.findall(r"<event>(.*?)</event>", xml, flags=re.S):
            def tag(t):
                m = re.search(fr"<{t}>(.*?)</{t}>", node, flags=re.S)
                return (m.group(1).strip() if m else "")
            title = tag("title")
            cur = tag("currency") or tag("country")
            imp = tag("impact")
            dt_s = tag("datetime") or tag("time")
            ts = pd.to_datetime(dt_s, errors="coerce")
            if pd.isna(ts) or not title or not cur:
                continue
            if ts.tzinfo is None:
                ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
            tl = ts.tz_convert(TZ) if TZ else ts
            if not (start_dt <= tl <= end_dt):
                continue
            out.append(NewsEvent("MyFXBook", tl, cur.upper(), imp.title(), title))
        return out

    def _mfb_from_html(self, html: str, start: str, end: str) -> List[NewsEvent]:
        """Best-effort scraper; site structure may change."""
        start_dt = pd.Timestamp(start).tz_localize(TZ) if TZ else pd.Timestamp(start)
        end_dt   = pd.Timestamp(end).tz_localize(TZ)   if TZ else pd.Timestamp(end)
        soup = BeautifulSoup(html, "html.parser")
        out: List[NewsEvent] = []

        # Heuristic: look for table rows with time / currency / title / impact
        for tr in soup.find_all("tr"):
            tds = tr.find_all(["td", "th"])
            if len(tds) < 4:
                continue
            texts = [td.get_text(strip=True) for td in tds]
            time_txt = next((t for t in texts if re.fullmatch(r"\d{1,2}:\d{2}", t)), "")
            cur = next((t for t in texts if re.fullmatch(r"[A-Z]{3}", t)), "")
            imp = next((t for t in texts if "high" in t.lower() or "medium" in t.lower() or "low" in t.lower()), "Unknown")
            title = ""
            for t in texts:
                if len(t) > 8 and not re.fullmatch(r"[\d\.\,\%\-\+\s:APMapm]*", t):
                    title = t; break
            if not title:
                continue
            # assume current day context if no explicit date on row
            day_el = tr.find_previous(string=re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\b"))
            day_str = str(day_el) if day_el else pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d")
            # try to coerce to a reasonable local timestamp
            try:
                base_date = pd.to_datetime(re.sub(r"[^\w\s:-]", " ", day_str).strip(), errors="coerce")
                if pd.isna(base_date):
                    base_date = pd.Timestamp.now(tz=TZ).normalize()
                ts = pd.to_datetime(f"{base_date.date()} {time_txt or '00:00'}")
                if ts.tzinfo is None:
                    ts = ts.tz_localize(self.source_tz) if self.source_tz else ts
                tl = ts.tz_convert(TZ) if TZ else ts
            except Exception:
                continue
            if not (start_dt <= tl <= end_dt):
                continue
            out.append(NewsEvent("MyFXBook", tl, cur or "N/A", imp.title(), title))
        return out

    def _safe_get(self, url: str) -> Optional[str]:
        self._rotate_headers()
        try:
            r = self.s.get(url, timeout=20, allow_redirects=True)
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        return None

# ---------------------------- Aggregation / Windows ---------------------

IMPACT_RANK = {"Low": 1, "Medium": 2, "High": 3}

def to_frame(events: List[NewsEvent]) -> pd.DataFrame:
    if not events:
        # Remove unused columns
        return pd.DataFrame(columns=["source","date","currency","impact","event","dt"])
    rows = []
    for e in events:
        rows.append(dict(
            source=e.source,
            date=e.dt.strftime("%Y-%m-%d"),
            currency=e.currency,
            impact=e.impact,
            event=e.title,
            dt=e.dt
        ))
    df = pd.DataFrame(rows).sort_values("dt")
    return df

def filter_events(df: pd.DataFrame,
                  start: str, end: str,
                  currencies: Optional[List[str]] = None,
                  high_only: bool = False) -> pd.DataFrame:
    if df.empty:
        return df
    # Ensure start/end are timezone aware
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

def filter_events_by_future_minutes(df: pd.DataFrame, minutes: int) -> pd.DataFrame:
    """Filter events to only those occurring within the specified minutes into the future."""
    if df.empty:
        return df
    
    now = pd.Timestamp.now(tz=TZ) if TZ else pd.Timestamp.now()
    future_cutoff = now + pd.Timedelta(minutes=minutes)
    
    print(f"Debug: Current time: {now}")
    print(f"Debug: Future cutoff: {future_cutoff}")
    print(f"Debug: Looking for events between {now} and {future_cutoff}")
    
    # Create properly reconstructed datetime from date_obj and time_obj
    df_normalized = df.copy()
    
    for idx, row in df_normalized.iterrows():
        # Reconstruct datetime from the correctly parsed date_obj and time_obj
        if pd.notna(row['date_obj']) and pd.notna(row['time_obj']):
            # Combine date and time objects into a proper datetime
            combined_dt = pd.Timestamp.combine(row['date_obj'], row['time_obj'])
            # Localize to runtime TZ
            event_dt = combined_dt.tz_localize(TZ) if TZ else combined_dt
        else:
            # Fallback to original dt if date_obj/time_obj are not available
            event_dt = row["dt"]
            if event_dt.tzinfo is None:
                event_dt = event_dt.tz_localize(TZ) if TZ else event_dt
            elif TZ and event_dt.tzinfo != TZ:
                event_dt = event_dt.tz_convert(TZ)
        
        df_normalized.at[idx, "dt"] = event_dt
        
        # Debug first few events
        if idx < 3:
            print(f"Debug: Event {idx}: {row['date_obj']} {row['time_obj']} -> {event_dt}")
    
    mask = (df_normalized["dt"] >= now) & (df_normalized["dt"] <= future_cutoff)
    filtered_count = mask.sum()
    print(f"Debug: Found {filtered_count} events in future timeframe")
    
    return df_normalized.loc[mask].copy()

def build_windows(df: pd.DataFrame,
                  mins_before: Dict[str, int],
                  mins_after: Dict[str, int]) -> pd.DataFrame:
    """Adds window_start/window_end (tz-aware) per row based on impact."""
    if df.empty:
        return df
    def win(row):
        imp = row["impact"].title()
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

def is_news_active(df_with_windows: pd.DataFrame, when: Optional[pd.Timestamp] = None) -> Tuple[bool, Optional[pd.Series]]:
    if df_with_windows.empty:
        return False, None
    now = when or pd.Timestamp.now(tz=TZ)
    hit = df_with_windows[(df_with_windows["window_start"] <= now) & (df_with_windows["window_end"] >= now)]
    if hit.empty:
        return False, None
    # choose highest impact, then nearest end
    hit = hit.assign(rank=hit["impact"].map(lambda s: IMPACT_RANK.get(str(s).title(), 0)))
    hit = hit.sort_values(["rank","window_end"], ascending=[False, True])
    return True, hit.iloc[0]

def next_news(df_with_windows: pd.DataFrame, after: Optional[pd.Timestamp] = None) -> Optional[pd.Series]:
    if df_with_windows.empty:
        return None
    now = after or pd.Timestamp.now(tz=TZ)
    fut = df_with_windows[df_with_windows["window_start"] > now].sort_values("window_start")
    return None if fut.empty else fut.iloc[0]

def parse_event_time(event_string):
    # Split the text into date and time parts (e.g., "Sep 25, 09:00")
    parts = event_string.split(", ")
    date_string = parts[0]
    time_string = parts[1]

    # Parse date part into date_obj (assume current year if not provided)
    from datetime import datetime as _dt, time as _dtime
    try:
        date_obj = _dt.strptime(date_string, "%b %d").replace(year=_dt.now().year)
    except Exception:
        date_obj = None

    # Convert time string to a datetime.time object
    try:
        hours, minutes = map(int, time_string.split(":"))
        time_obj = _dtime(hours, minutes)
    except Exception:
        time_obj = None

    return time_string, time_obj

def to_frame(events: List[NewsEvent]) -> pd.DataFrame:
    if not events:
        return pd.DataFrame(columns=["source","date","currency","impact","event","dt","date_obj","time_obj"])
    rows = []
    for e in events:
        # Start from the tz-aware event datetime expressed in display TZ (TZ)
        dt_local = e.dt.tz_convert(TZ) if (hasattr(e.dt, "tz_convert") and TZ) else e.dt
        date_obj = dt_local.date()
        time_obj = dt_local.time()

        # If the title includes a date/time (e.g., "Sep 25, 09:00"), rebuild dt using source tz, then convert to display tz
        parsed_date_candidate = None
        parsed_time_candidate = None
        title_months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
        if ', ' in e.title and any(m in e.title for m in title_months):
            try:
                _, parsed_time_obj = parse_event_time(e.title)
                if parsed_time_obj:
                    parsed_time_candidate = parsed_time_obj
                    parts = e.title.split(', ')
                    if len(parts) >= 1:
                        date_part = parts[0]
                        from datetime import datetime as _dt
                        try:
                            parsed_date_candidate = _dt.strptime(date_part, "%b %d").replace(year=_dt.now().year).date()
                        except Exception:
                            parsed_date_candidate = None
            except Exception:
                parsed_date_candidate = None
                parsed_time_candidate = None

        # If we parsed a time (and maybe date), create a timezone-aware dt using SOURCE_TZ (handles DST), then convert to TZ
        if parsed_time_candidate is not None:
            event_date = parsed_date_candidate or dt_local.date()
            combined = pd.Timestamp.combine(event_date, parsed_time_candidate)
            src_tz = SOURCE_TZ or TZ
            if src_tz is not None:
                try:
                    combined = combined.tz_localize(src_tz)
                except Exception:
                    # Already tz-aware? then ignore
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


# ---------------------------- CLI / Demo --------------------------------

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=pd.Timestamp.now(tz=TZ).strftime("%Y-%m-%d"))
    ap.add_argument("--end",   default=(pd.Timestamp.now(tz=TZ)+pd.Timedelta(days=7)).strftime("%Y-%m-%d"))
    ap.add_argument("--currencies", default="USD,EUR,GBP,JPY,AUD,CAD,CHF,NZD")
    ap.add_argument("--high-only", action="store_true", help="Keep only HIGH impact")
    ap.add_argument("--mfb-export-url", default="", help="Optional MyFXBook CSV/XML export URL")
    ap.add_argument("--source-tz", default=os.getenv("MFB_SOURCE_TZ", "UTC"), help="Timezone of source feed, e.g. 'UTC', 'Europe/London', or 'local'")
    ap.add_argument("--save", action="store_true", help="Save combined CSV")
    args = ap.parse_args()

    src_tz = resolve_tz(None if str(args.source_tz).lower() == "local" else args.source_tz)
    scraper = EconomicNewsScraper(myfxbook_export_url=args.mfb_export_url, source_tz=src_tz)

    print(f"Fetching {args.start} → {args.end} ({tz_label(TZ)})… Source: MyFXBook")
    mfb = scraper.get_myfxbook(args.start, args.end)
    df = to_frame(mfb)

    if df.empty:
        print("❌ No events collected (check connectivity / site anti-bot / export URL).")
        return
    
    # Debug: Show what we fetched
    print(f"✅ Fetched {len(df)} events from MyFXBook")
    if len(df) > 0:
        print(f"First event: {df.iloc[0]['date']} {df.iloc[0]['time_obj']} - {df.iloc[0]['event']}")
        print(f"Last event: {df.iloc[-1]['date']} {df.iloc[-1]['time_obj']} - {df.iloc[-1]['event']}")
    current_time = pd.Timestamp.now(tz=TZ) if TZ else pd.Timestamp.now()
    print(f"Current time: {current_time}")
    print(f"Sample event dt: {df.iloc[0]['dt']} (tzinfo: {df.iloc[0]['dt'].tzinfo})")

    # Debug: Check if event titles contain time info that we can parse
    print(f"Debug: Raw event titles (first 3):")
    for i in range(min(3, len(df))):
        print(f"  Event {i}: '{df.iloc[i]['event']}'")
        # Try to extract time from event title if it contains time info
        if 'Sep' in df.iloc[i]['event'] and ',' in df.iloc[i]['event']:
            try:
                time_str, time_obj = parse_event_time(df.iloc[i]['event'])
                print(f"    Parsed time: {time_str} -> {time_obj}")
            except:
                print(f"    Could not parse time from title")

    # Ask user for minutes into the future
    try:
        minutes = int(input("\nEnter minutes into the future to filter events: "))
        if minutes <= 0:
            print("Minutes must be a positive number. Using original timeframe.")
            minutes = None
    except (ValueError, KeyboardInterrupt):
        print("Invalid input. Using original timeframe.")
        minutes = None

    # Apply future minutes filter if specified
    if minutes is not None:
        df = filter_events_by_future_minutes(df, minutes)
        if df.empty:
            print(f"No events found within the next {minutes} minutes.")
            return
        print(f"Filtered to events within the next {minutes} minutes.")

    df = filter_events(
        df,
        args.start, args.end,
        currencies=[c.strip().upper() for c in args.currencies.split(",") if c.strip()],
        high_only=args.high_only
    )

    mins_before = {"High": 20, "Medium": 15, "Low": 10}
    mins_after  = {"High": 30, "Medium": 20, "Low": 15}
    df = build_windows(df, mins_before, mins_after)

    if df.empty:
        print("No events after filters.")
        return

    # Pretty print
    print("\n" + "="*110)
    print(f"ECONOMIC EVENTS ({len(df)}) — {tz_label(TZ)}")
    print("="*110)
    cur_day = None
    for _, r in df.sort_values(["date_obj", "time_obj"]).iterrows():
        day_str = r["date_obj"].isoformat()
        if day_str != cur_day:
            cur_day = day_str
            print(f"\n📅 {cur_day}")
        impact_icon = "🔴" if r["impact"].lower().startswith("high") else ("🟡" if r["impact"].lower().startswith("med") else "🟢")
        print(f"  {r['currency']:>3} | {impact_icon} {r['impact']:<6} | {r['source']:<12} | {r['date_obj']} {r['time_obj']}")

    if args.save:
        out = f"economic_events_{args.start}_to_{args.end}.csv"
        df.drop(columns=["dt"]).to_csv(out, index=False)
        print(f"\nSaved → {out}")

if __name__ == "__main__":
    main()
