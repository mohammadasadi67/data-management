"""
Production Dashboard (Streamlit + Supabase Storage)

Same features as before (upload, archive, dashboard, trends, contact),
but faster, safer and easier to use.

Optional secrets (.streamlit/secrets.toml or Streamlit Cloud "Secrets"):
    SUPABASE_URL   = "https://xxxx.supabase.co"
    SUPABASE_KEY   = "your-publishable-key"
    ADMIN_PASSWORD = "choose-a-strong-password"
"""

import hmac
import os
import re
from datetime import datetime, timedelta, time as datetime_time
from io import BytesIO
from urllib.parse import quote

import numpy as np
import pandas as pd
import plotly.express as px
import requests
import streamlit as st

# ===================================================================
#                          PAGE SETUP
# ===================================================================
st.set_page_config(
    page_title="Production Dashboard",
    page_icon="🏭",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    h1, h2, h3, h4 { color: #1d3557; }
    div[data-testid="stMetric"] {
        background: #f1f5f9;
        border-radius: 10px;
        padding: 12px 16px;
        border: 1px solid #e2e8f0;
    }
    .stButton>button, .stDownloadButton>button { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ===================================================================
#                        CONFIG / SECRETS
# ===================================================================
def _secret(name, default=""):
    try:
        return st.secrets[name]
    except Exception:
        return os.environ.get(name, default)


SUPABASE_URL = _secret("SUPABASE_URL", "https://rlutsxvghmhrgcnqbmch.supabase.co")
SUPABASE_KEY = _secret("SUPABASE_KEY", "sb_publishable_z2H6jQd7GXX-evMSZQTg8w_mGGn_6ns")
ADMIN_PASSWORD = _secret("ADMIN_PASSWORD", "")

BUCKET = "uploads"
XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
TIMEOUT = 30


def _version_tuple(v):
    nums = re.findall(r"\d+", v)[:2]
    return tuple(int(n) for n in nums) if len(nums) == 2 else (0, 0)


_NEW_STREAMLIT = _version_tuple(st.__version__) >= (1, 50)
_NEW_PANDAS = _version_tuple(pd.__version__) >= (2, 2)

FREQUENCIES = {
    "Daily": "D",
    "Weekly": "W",
    "Monthly": "ME" if _NEW_PANDAS else "M",
    "Yearly": "YE" if _NEW_PANDAS else "Y",
}


def show_chart(fig):
    if _NEW_STREAMLIT:
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(fig, use_container_width=True)


def show_df(df, **kwargs):
    if _NEW_STREAMLIT:
        st.dataframe(df, width="stretch", **kwargs)
    else:
        st.dataframe(df, use_container_width=True, **kwargs)


# ===================================================================
#                     SUPABASE STORAGE (HTTP)
# ===================================================================
def _headers(extra=None):
    h = {"Authorization": f"Bearer {SUPABASE_KEY}", "apikey": SUPABASE_KEY}
    if extra:
        h.update(extra)
    return h


def supabase_list_files():
    url = f"{SUPABASE_URL}/storage/v1/object/list/{BUCKET}"
    body = {
        "prefix": "",
        "limit": 1000,  # Supabase returns only 100 by default
        "offset": 0,
        "sortBy": {"column": "name", "order": "asc"},
    }
    r = requests.post(
        url, json=body, headers=_headers({"Content-Type": "application/json"}), timeout=TIMEOUT
    )
    if r.status_code != 200:
        raise RuntimeError(f"Supabase list error {r.status_code}: {r.text}")
    return r.json()


@st.cache_data(ttl=600, show_spinner=False)
def supabase_download_file(filename):
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{quote(filename)}"
    r = requests.get(url, headers=_headers(), timeout=60)
    return r.content if r.status_code == 200 else None


def supabase_upload_file(data, filename):
    """Upload (and replace if it already exists). Returns (ok, message)."""
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}/{quote(filename)}"
    try:
        r = requests.post(
            url,
            data=data,
            headers=_headers({"Content-Type": XLSX_MIME, "x-upsert": "true"}),
            timeout=120,
        )
    except requests.RequestException as e:
        return False, f"Network problem: {e}"
    if r.status_code in (200, 201):
        return True, "OK"
    return False, f"Server answered {r.status_code}: {r.text[:200]}"


def supabase_delete_files(names):
    if not names:
        return True
    url = f"{SUPABASE_URL}/storage/v1/object/{BUCKET}"
    r = requests.delete(
        url,
        json={"prefixes": list(names)},
        headers=_headers({"Content-Type": "application/json"}),
        timeout=TIMEOUT,
    )
    return r.status_code == 200


def clear_caches():
    get_all_supabase_files.clear()
    get_service_files.clear()
    get_stock_files.clear()
    supabase_download_file.clear()
    load_data.clear()
    load_service_data.clear()
    load_stock.clear()


# ===================================================================
#                        UTILITY FUNCTIONS
# ===================================================================
def filename_has_valid_date(filename):
    m = re.search(r"(\d{8})", filename)
    if not m:
        return False
    ds = m.group(1)
    try:
        datetime(int(ds[4:8]), int(ds[2:4]), int(ds[0:2]))
        return True
    except ValueError:
        return False


def parse_filename_date_to_datetime(filename):
    """Expects DDMMYYYY somewhere in the file name."""
    try:
        m = re.search(r"(\d{8})", filename)
        if m:
            ds = m.group(1)
            return datetime(int(ds[4:8]), int(ds[2:4]), int(ds[0:2])).date()
    except Exception:
        pass
    return datetime.now().date()


def convert_time(val):
    if pd.isna(val):
        return 0
    if isinstance(val, datetime_time):
        return val.hour + val.minute / 60
    if isinstance(val, datetime):
        return val.hour + val.minute / 60
    if isinstance(val, (int, float)):
        if 0 <= val < 1:
            return val * 24
        try:
            h = int(val) // 100
            m = int(val) % 100
            if 0 <= m < 60:
                return (h % 24) + m / 60
        except Exception:
            pass
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime.strptime(s, fmt)
                    return t.hour + t.minute / 60
                except Exception:
                    pass
        if s.isdigit():
            v = int(s)
            h, m = v // 100, v % 100
            if 0 <= m < 60:
                return (h % 24) + m / 60
        try:
            return float(s)
        except Exception:
            return 0
    return 0


def convert_duration_to_minutes(val):
    if pd.isna(val):
        return 0
    if isinstance(val, timedelta):
        return val.total_seconds() / 60
    if isinstance(val, (datetime, datetime_time)):
        return val.hour * 60 + val.minute
    if isinstance(val, (int, float)):
        if 0 <= val < 1:
            return val * 24 * 60
        if val < 2400:
            h, m = int(val) // 100, int(val) % 100
            if 0 <= m < 60:
                return h * 60 + m
        return val * 60
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    t = datetime.strptime(s, fmt)
                    return t.hour * 60 + t.minute
                except Exception:
                    pass
        if s.isdigit():
            v = int(s)
            h, m = v // 100, v % 100
            if 0 <= m < 60:
                return h * 60 + m
        try:
            return float(s) * 60
        except Exception:
            return 0
    return 0


def determine_machine_type(name):
    s = str(name).lower()
    if "gasti" in s:
        return "GASTI"
    if "200" in s:
        return "200cc"
    if "125" in s:
        return "125"
    if "1000" in s:
        return "1000cc"
    return "Unknown"


# ===================================================================
#                      READING THE EXCEL FILES
# ===================================================================
def fmt_hours(h):
    """Hours as a float -> 'HH:MM' (what the app understood from the Excel cell)."""
    try:
        total = int(round(float(h) * 60)) % 1440
        return f"{total // 60:02d}:{total % 60:02d}"
    except Exception:
        return ""


def explain_row(r):
    """Short, human-readable guess about why efficiency is above 100%."""
    cap, dur, qty = r["Capacity"], r["Duration"], r["PackQty"]
    notes = []
    if cap > 0 and dur > 0:
        notes.append(
            f"Quantity needs {qty / cap:.1f} h at rated capacity, but the sheet shows {dur:.1f} h "
            f"(implied rate {qty / dur:,.0f}/h vs capacity {cap:,.0f}/h)"
        )
        if qty / (cap * dur) >= 5:
            notes.append("quantity is 5x+ too high: possible extra digit/typo")
    if dur < 0.5:
        notes.append("very short duration: check Start/End")
    if dur > 20:
        notes.append("very long duration: check midnight / AM-PM")
    for label, raw in (("Start", r["StartRaw"]), ("End", r["EndRaw"])):
        if re.fullmatch(r"\d{1,2}(\.0+)?", str(raw)):
            notes.append(f"{label} is a plain number ({raw}) and may be read as minutes, not hours")
    return "; ".join(notes)


def find_suspicious(prod_df, limit):
    bad = prod_df[prod_df["Efficiency(%)"] > limit].copy()
    if not bad.empty:
        bad["Likely cause"] = bad.apply(explain_row, axis=1)
    return bad


def read_production_data(df_raw, filename, sheet_name, file_date):
    """Raises ValueError with a readable message if the sheet layout is wrong."""
    try:
        row2 = df_raw.iloc[1, 3:16].fillna("").astype(str).tolist()
        row3 = df_raw.iloc[2, 3:16].fillna("").astype(str).tolist()
    except Exception:
        raise ValueError("header rows (2–3, columns D–P) not found")

    headers = []
    for r2, r3 in zip(row2, row3):
        if r3.strip() and r3.strip() != "nan":
            headers.append(r3.strip())
        elif r2.strip() and r2.strip() != "nan":
            headers.append(r2.strip())
        else:
            headers.append("")
    headers = [h if h else f"Col_{i}" for i, h in enumerate(headers)]

    data = df_raw.iloc[3:9, 3:16].copy()
    if len(headers) != data.shape[1]:
        raise ValueError("column count does not match the expected layout")
    data.columns = headers

    # Remember where each row came from (df_raw has no header, so index 0 = Excel row 1)
    data["ExcelRow"] = data.index + 1
    data["File"] = filename
    data["Sheet"] = sheet_name

    rename_map = {
        "start": "Start",
        "finish": "End",
        "production title": "Product",
        "cap": "Capacity",
        "manpower": "Manpower",
        "quanity": "PackQty",
        "waste": "Waste",
    }
    data = data.rename(columns={k: v for k, v in rename_map.items() if k in data.columns})

    data["Date"] = file_date

    mtype = determine_machine_type(sheet_name)
    if mtype == "Unknown":
        mtype = determine_machine_type(filename)
    data["ProductionTypeForTon"] = mtype

    for col in ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Waste"]:
        if col not in data.columns:
            data[col] = 0

    data["StartRaw"] = data["Start"].astype(str).str.strip()
    data["EndRaw"] = data["End"].astype(str).str.strip()

    data["Product"] = data["Product"].astype(str).str.strip().str.title()
    data = data[~data["Product"].isin(["", "Nan", "0"])]
    if data.empty:
        return pd.DataFrame()

    data["StartTime"] = data["Start"].apply(convert_time)
    data["EndTime"] = data["End"].apply(convert_time)
    data["EndTimeAdj"] = np.where(
        data["EndTime"] < data["StartTime"], data["EndTime"] + 24, data["EndTime"]
    )
    data["StartRead"] = data["StartTime"].apply(fmt_hours)
    data["EndRead"] = data["EndTime"].apply(fmt_hours)
    data["Duration"] = data["EndTimeAdj"] - data["StartTime"]
    data = data[data["Duration"] > 0].copy()

    for col in ["PackQty", "Waste", "Capacity", "Manpower"]:
        data[col] = pd.to_numeric(data[col], errors="coerce").fillna(0)

    def calc_ton(row):
        t = str(row["ProductionTypeForTon"]).lower()
        qty = row["PackQty"]
        if "gasti" in t:
            grams = 90
        elif "200" in t:
            grams = 200
        elif "125" in t:
            grams = 125
        else:
            grams = 1000
        return (qty * grams) / 1_000_000

    data["Ton"] = data.apply(calc_ton, axis=1)
    data["PotentialProduction"] = data["Capacity"] * data["Duration"]
    data["Efficiency(%)"] = np.where(
        data["PotentialProduction"] > 0,
        (data["PackQty"] / data["PotentialProduction"]) * 100,
        0,
    )

    final_cols = [
        "File", "Sheet", "ExcelRow", "Date", "Product",
        "StartRaw", "StartRead", "EndRaw", "EndRead",
        "Capacity", "Manpower", "Duration", "PackQty", "Waste",
        "Ton", "PotentialProduction", "Efficiency(%)", "ProductionTypeForTon",
    ]
    return data[final_cols]


def read_error_data(df_raw, sheet_name, filename, file_date):
    try:
        raw = df_raw.iloc[11:1000, 6:8].copy()
        raw.columns = ["Error", "Duration"]
    except Exception:
        return pd.DataFrame()

    raw["Error"] = raw["Error"].fillna("").astype(str).str.strip()
    raw = raw[raw["Error"] != ""]
    if raw.empty:
        return pd.DataFrame()

    raw["Duration"] = raw["Duration"].apply(convert_duration_to_minutes)
    agg = raw.groupby("Error")["Duration"].sum().reset_index()
    agg["Date"] = file_date
    agg["MachineType"] = determine_machine_type(sheet_name)
    return agg


@st.cache_data(ttl=600, show_spinner=False)
def load_data(names):
    """Reads every selected file. Cached, so changing a filter is instant."""
    all_prod, all_err, problems = [], [], []

    for fname in names:
        fdate = parse_filename_date_to_datetime(fname)
        file_bytes = supabase_download_file(fname)
        if not file_bytes:
            problems.append(f"{fname}: could not be downloaded")
            continue
        try:
            xls = pd.ExcelFile(BytesIO(file_bytes))
        except Exception:
            problems.append(f"{fname}: not a valid Excel file")
            continue

        for sheet in xls.sheet_names:
            try:
                df_raw = pd.read_excel(xls, sheet_name=sheet, header=None)
                prod_df = read_production_data(df_raw, fname, sheet, fdate)
                err_df = read_error_data(df_raw, sheet, fname, fdate)
            except ValueError as e:
                problems.append(f"{fname} / {sheet}: {e}")
                continue
            except Exception as e:
                problems.append(f"{fname} / {sheet}: unexpected problem ({e})")
                continue

            if not prod_df.empty:
                all_prod.append(prod_df)
            if not err_df.empty:
                all_err.append(err_df)

    final_prod = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()
    final_err = pd.concat(all_err, ignore_index=True) if all_err else pd.DataFrame()
    return final_prod, final_err, problems


@st.cache_data(ttl=600, show_spinner=False)
def get_all_supabase_files():
    items = supabase_list_files()
    cleaned = []
    for it in items:
        name = it.get("name", "")
        if name.lower().endswith(".xlsx") and not is_service_file(name) and not is_stock_file(name):
            cleaned.append(
                {"name": name, "file_date": parse_filename_date_to_datetime(name)}
            )
    cleaned.sort(key=lambda f: (f["file_date"], f["name"]))
    return cleaned


def safe_get_files():
    """Returns files, or None (after showing a friendly message) if Supabase is unreachable."""
    try:
        return get_all_supabase_files()
    except Exception as e:
        st.error(
            "Couldn't load the file list. Check your internet connection and the "
            "Supabase settings, then press **Refresh**."
        )
        with st.expander("Technical details"):
            st.code(str(e))
        return None


# ===================================================================
#              SERVICE / MACHINE HOURS (Excel based, weekly)
# ===================================================================
# A weekly file named  Service_DDMMYYYY.xlsx  with two sheets:
#   "Hours"        ->  Machine | Hours
#   "Service plan" ->  Machine | Service | Every (hours) | Last done at (hours)
#                      | Every (days) | Last done on (date)
# These files are kept out of the production data automatically.

def is_service_file(name):
    return name.lower().startswith("service")


def is_stock_file(name):
    return name.lower().startswith("stock")


def _code(x):
    """Material / part code as clean text (50000001.0 -> '50000001')."""
    if pd.isna(x):
        return ""
    s = str(x).strip()
    return s[:-2] if s.endswith(".0") else s


def today_local():
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo("Asia/Baghdad")).date()
    except Exception:
        return datetime.now().date()


@st.cache_data(ttl=600, show_spinner=False)
def get_service_files():
    out = []
    for it in supabase_list_files():
        name = it.get("name", "")
        if name.lower().endswith(".xlsx") and is_service_file(name):
            out.append({"name": name, "file_date": parse_filename_date_to_datetime(name)})
    out.sort(key=lambda f: (f["file_date"], f["name"]))
    return out


def safe_service_files():
    try:
        return get_service_files()
    except Exception as e:
        st.error("Couldn't load the service files. Check your connection and press **Refresh**.")
        with st.expander("Technical details"):
            st.code(str(e))
        return None


def _norm(s):
    return re.sub(r"[\W_]+", "", str(s).lower())


_ALIASES = {
    "machine": {"machine", "device", "دستگاه"},
    "hours": {"hours", "hour", "counter", "ساعت", "شمارنده"},
    "service": {"service", "task", "سرویس"},
    "every_hours": {"everyhours", "intervalhours", "hoursinterval"},
    "last_hours": {"lastdoneathours", "lastservicehours", "lasthours"},
    "every_days": {"everydays", "intervaldays", "daysinterval"},
    "last_date": {"lastdoneondate", "lastservicedate", "lastdate"},
}


_STOCK_ALIASES = {
    "code": {"material", "materialcode", "partcode", "code", "کد", "کدکالا"},
    "desc": {"materialdescription", "description", "desc", "شرح", "شرحکالا"},
    "bin": {"storagebin", "bin", "location"},
    "stock": {"currentstock", "stock", "qty", "quantity", "موجودی"},
    "unit": {"unit", "uom", "واحد"},
}

_PARTS_ALIASES = {
    "machine": _ALIASES["machine"],
    "service": _ALIASES["service"],
    "code": {"partcode", "material", "materialcode", "code", "کد"},
    "qty": {"qtyneeded", "qty", "quantity", "needed", "تعداد"},
}


def _canon_columns(df, aliases=None):
    aliases = aliases or _ALIASES
    mapping = {}
    for c in df.columns:
        n = _norm(c)
        for canon, names in aliases.items():
            if n in names and canon not in mapping.values():
                mapping[c] = canon
                break
    return df.rename(columns=mapping)


def _find_sheet(xls, keys, exclude=None):
    for s in xls.sheet_names:
        if s == exclude:
            continue
        n = _norm(s)
        if any(k in n for k in keys):
            return s
    return None


def _clean_text(series):
    s = series.astype(str).str.strip()
    return s


@st.cache_data(ttl=600, show_spinner=False)
def load_service_data(names):
    """names: service files sorted oldest -> newest. Hours come from all of them
    (history), the service plan comes from the newest one."""
    hour_rows, plan_df, parts_df, problems = [], pd.DataFrame(), pd.DataFrame(), []

    for i, fname in enumerate(names):
        fdate = parse_filename_date_to_datetime(fname)
        data = supabase_download_file(fname)
        if not data:
            problems.append(f"{fname}: could not be downloaded")
            continue
        try:
            xls = pd.ExcelFile(BytesIO(data))
        except Exception:
            problems.append(f"{fname}: not a valid Excel file")
            continue

        hs = _find_sheet(xls, ("hours", "counter"))
        if hs is None:
            problems.append(f"{fname}: no 'Hours' sheet")
            continue
        h = _canon_columns(pd.read_excel(xls, sheet_name=hs))
        if not {"machine", "hours"} <= set(h.columns):
            problems.append(f"{fname}: the 'Hours' sheet needs the columns Machine and Hours")
            continue
        h = h[["machine", "hours"]].copy()
        h["machine"] = _clean_text(h["machine"])
        h["hours"] = pd.to_numeric(h["hours"], errors="coerce")
        h = h[(h["machine"] != "") & (h["machine"].str.lower() != "nan") & h["hours"].notna()]
        h["date"] = fdate
        h["file"] = fname
        hour_rows.append(h)

        if i == len(names) - 1:  # newest file -> service plan
            # optional sheet: spare parts each service needs
            pts = _find_sheet(xls, ("part",), exclude=hs)
            if pts is not None:
                q = _canon_columns(pd.read_excel(xls, sheet_name=pts, dtype=object), _PARTS_ALIASES)
                if {"machine", "service", "code"} <= set(q.columns):
                    if "qty" not in q.columns:
                        q["qty"] = 1
                    q = q[["machine", "service", "code", "qty"]].copy()
                    q["machine"] = _clean_text(q["machine"])
                    q["service"] = _clean_text(q["service"])
                    q["code"] = q["code"].map(_code)
                    q["qty"] = pd.to_numeric(q["qty"], errors="coerce").fillna(1)
                    q = q[
                        (q["machine"] != "") & (q["machine"].str.lower() != "nan")
                        & (q["service"] != "") & (q["service"].str.lower() != "nan")
                        & (q["code"] != "")
                    ]
                    parts_df = q.reset_index(drop=True)
                else:
                    problems.append(f"{fname}: the 'Parts needed' sheet needs Machine, Service and Part code")

            ps = _find_sheet(xls, ("service", "plan"), exclude=hs)
            if ps is None:
                problems.append(f"{fname}: no 'Service plan' sheet")
                continue
            p = _canon_columns(pd.read_excel(xls, sheet_name=ps))
            if not {"machine", "service"} <= set(p.columns):
                problems.append(f"{fname}: the 'Service plan' sheet needs the columns Machine and Service")
                continue
            for col in ("every_hours", "last_hours", "every_days", "last_date"):
                if col not in p.columns:
                    p[col] = np.nan
            p = p[["machine", "service", "every_hours", "last_hours", "every_days", "last_date"]].copy()
            p["machine"] = _clean_text(p["machine"])
            p["service"] = _clean_text(p["service"])
            p = p[
                (p["machine"] != "") & (p["machine"].str.lower() != "nan")
                & (p["service"] != "") & (p["service"].str.lower() != "nan")
            ]
            for col in ("every_hours", "last_hours", "every_days"):
                p[col] = pd.to_numeric(p[col], errors="coerce")
            p["last_date"] = pd.to_datetime(p["last_date"], errors="coerce")
            plan_df = p.reset_index(drop=True)

    hours_df = pd.concat(hour_rows, ignore_index=True) if hour_rows else pd.DataFrame()
    return hours_df, plan_df, parts_df, problems


def compute_service_status(hours_df, plan_df, today, warn_days=14, warn_pct=10):
    """One row per service with remaining hours / days and a status level
    (0 overdue, 1 due soon, 2 ok, 3 missing data)."""
    if hours_df.empty or plan_df.empty:
        return pd.DataFrame()

    latest_date = hours_df["date"].max()
    window_start = latest_date - timedelta(days=42)

    # current hours + average hours per day for every machine
    info = {}
    tmp = hours_df.assign(_k=hours_df["machine"].str.lower())
    for key, g in tmp.groupby("_k"):
        g = g.sort_values("date")
        last = g.iloc[-1]
        w = g[g["date"] >= window_start]
        rate = None
        if len(w) >= 2:
            span = (w.iloc[-1]["date"] - w.iloc[0]["date"]).days
            gain = w.iloc[-1]["hours"] - w.iloc[0]["hours"]
            if span > 0 and gain > 0:
                rate = float(gain) / span
        info[key] = (float(last["hours"]), last["date"], rate)

    rows = []
    for _, p in plan_df.iterrows():
        cur_h, h_date, rate = info.get(p["machine"].lower(), (None, None, None))
        every_h, last_h = p["every_hours"], p["last_hours"]
        every_d = p["every_days"]

        remaining_h = est_days = used_h = None
        next_h = None
        if pd.notna(every_h) and every_h > 0 and pd.notna(last_h) and cur_h is not None:
            next_h = float(last_h + every_h)
            remaining_h = next_h - cur_h
            used_h = (1 - remaining_h / every_h) * 100
            if rate:
                est_days = remaining_h / rate - (today - h_date).days

        remaining_days = used_d = None
        if pd.notna(every_d) and every_d > 0 and pd.notna(p["last_date"]):
            due = p["last_date"].date() + timedelta(days=int(every_d))
            remaining_days = (due - today).days
            used_d = (1 - remaining_days / every_d) * 100

        day_values = [d for d in (est_days, remaining_days) if d is not None]
        days_left = min(day_values) if day_values else None
        used_vals = [u for u in (used_h, used_d) if u is not None]
        used_pct = max(used_vals) if used_vals else None

        overdue = (remaining_h is not None and remaining_h <= 0) or (days_left is not None and days_left <= 0)
        soon = (
            (remaining_h is not None and remaining_h <= every_h * warn_pct / 100)
            or (days_left is not None and days_left <= warn_days)
        )
        if remaining_h is None and remaining_days is None:
            level, label = 3, "⚪ Missing data"
        elif overdue:
            level, label = 0, "🔴 Overdue"
        elif soon:
            level, label = 1, "🟠 Due soon"
        else:
            level, label = 2, "🟢 OK"

        due_txt = ""
        if days_left is not None:
            due_txt = (today + timedelta(days=int(round(days_left)))).strftime("%d %b %Y")

        rows.append(
            {
                "_level": level,
                "_sort": days_left if days_left is not None else 1e6,
                "Status": label,
                "Machine": p["machine"],
                "Service": p["service"],
                "Hours now": cur_h,
                "Next due (h)": next_h,
                "Hours left": remaining_h,
                "Days left": days_left,
                "Due date": due_txt,
                "Used %": None if used_pct is None else float(min(max(used_pct, 0), 100)),
                "Avg h/day": rate,
            }
        )

    out = pd.DataFrame(rows)
    return out.sort_values(["_level", "_sort"]).drop(columns="_sort").reset_index(drop=True)


@st.cache_data(ttl=600, show_spinner=False)
def get_stock_files():
    out = []
    for it in supabase_list_files():
        name = it.get("name", "")
        if name.lower().endswith(".xlsx") and is_stock_file(name):
            out.append({"name": name, "file_date": parse_filename_date_to_datetime(name)})
    out.sort(key=lambda f: (f["file_date"], f["name"]))
    return out


@st.cache_data(ttl=600, show_spinner=False)
def load_stock(fname):
    """Warehouse stock list -> (one row per material code, problem text)."""
    data = supabase_download_file(fname)
    if not data:
        return pd.DataFrame(), f"{fname}: could not be downloaded"
    try:
        raw = pd.read_excel(BytesIO(data), dtype=object)
    except Exception:
        return pd.DataFrame(), f"{fname}: not a valid Excel file"

    df = _canon_columns(raw, _STOCK_ALIASES)
    if not {"code", "stock"} <= set(df.columns):
        return pd.DataFrame(), f"{fname}: the stock list needs the columns Material and Current stock"
    for c in ("desc", "bin", "unit"):
        if c not in df.columns:
            df[c] = ""
    df = df[["code", "desc", "bin", "stock", "unit"]].copy()
    df["code"] = df["code"].map(_code)
    df["stock"] = pd.to_numeric(df["stock"], errors="coerce").fillna(0)
    df = df[df["code"] != ""]

    def first_text(s):
        return next((str(x).strip() for x in s if pd.notna(x) and str(x).strip()), "")

    grouped = df.groupby("code", sort=False).agg(
        stock=("stock", "sum"),
        desc=("desc", first_text),
        unit=("unit", first_text),
        bins=("bin", lambda s: ", ".join(sorted({str(x).strip() for x in s if pd.notna(x) and str(x).strip()}))),
    ).reset_index()
    return grouped, ""


def add_parts_check(status, parts_df, stock_df):
    """Adds a 'Parts' text column (and a hidden _short flag) to the service status."""
    status = status.copy()
    if status.empty:
        return status
    status["Parts"] = "—"
    status["_short"] = False
    if parts_df.empty:
        return status

    look = stock_df.set_index("code") if not stock_df.empty else None
    pmap = {}
    for _, q in parts_df.iterrows():
        pmap.setdefault((q["machine"].lower(), q["service"].lower()), []).append((q["code"], float(q["qty"])))

    texts, shorts = [], []
    for _, r in status.iterrows():
        items = pmap.get((str(r["Machine"]).lower(), str(r["Service"]).lower()))
        if not items:
            texts.append("—")
            shorts.append(False)
        elif look is None:
            texts.append("❓ no stock list uploaded")
            shorts.append(False)
        else:
            problems = []
            for code, need in items:
                if code not in look.index:
                    problems.append(f"{code}: not in stock list")
                else:
                    have = float(look.at[code, "stock"])
                    if have < need:
                        problems.append(f"{code} {str(look.at[code, 'desc'])[:30]}: need {need:g}, have {have:g}")
            if problems:
                texts.append("❌ " + " | ".join(problems))
                shorts.append(True)
            else:
                texts.append(f"✅ {len(items)} part(s) in stock")
                shorts.append(False)
    status["Parts"] = texts
    status["_short"] = shorts
    return status


def build_order_list(status, parts_df, stock_df):
    """Parts still missing for services that are overdue or due soon."""
    if status.empty or parts_df.empty or stock_df.empty:
        return pd.DataFrame()
    urgent = status[status["_level"].isin([0, 1])]
    keys = {(str(m).lower(), str(s).lower()) for m, s in zip(urgent["Machine"], urgent["Service"])}
    need = {}
    for _, q in parts_df.iterrows():
        if (q["machine"].lower(), q["service"].lower()) in keys:
            need[q["code"]] = need.get(q["code"], 0.0) + float(q["qty"])

    look = stock_df.set_index("code")
    rows = []
    for code, n in need.items():
        known = code in look.index
        have = float(look.at[code, "stock"]) if known else 0.0
        if have < n:
            rows.append(
                {
                    "Part code": code,
                    "Description": str(look.at[code, "desc"]) if known else "(not in stock list)",
                    "Needed": n,
                    "In stock": have,
                    "To order": n - have,
                    "Unit": str(look.at[code, "unit"]) if known else "",
                    "Location": str(look.at[code, "bins"]) if known else "",
                }
            )
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("To order", ascending=False).reset_index(drop=True)


def build_service_template():
    today = today_local()
    out = BytesIO()
    with pd.ExcelWriter(out, engine="openpyxl") as w:
        pd.DataFrame(
            {"Machine": ["GASTI", "125", "200cc", "1000cc"], "Hours": [0, 0, 0, 0]}
        ).to_excel(w, sheet_name="Hours", index=False)

        pd.DataFrame(
            {
                "Machine": ["GASTI", "GASTI", "125"],
                "Service": ["Oil change", "Full overhaul", "Belt check"],
                "Every (hours)": [500, 5000, None],
                "Last done at (hours)": [0, 0, None],
                "Every (days)": [None, 365, 30],
                "Last done on (date)": [None, pd.Timestamp(today), pd.Timestamp(today)],
            }
        ).to_excel(w, sheet_name="Service plan", index=False)

        pd.DataFrame(
            {
                "Machine": ["GASTI", "GASTI"],
                "Service": ["Oil change", "Oil change"],
                "Part code": ["50000001", "50000003"],
                "Qty needed": [2, 1],
            }
        ).to_excel(w, sheet_name="Parts needed", index=False)

        pd.DataFrame(
            {
                "How to use": [
                    "1. Every week: copy this file, update the numbers in the 'Hours' sheet and save it as Service_DDMMYYYY.xlsx (today's date).",
                    "2. Upload it in the app (Upload Data page).",
                    "3. 'Service plan': one row per service. Fill 'Every (hours)' + 'Last done at (hours)' for hour-based services, "
                    "and/or 'Every (days)' + 'Last done on (date)' for calendar-based ones. You can leave the other pair empty.",
                    "4. When a service is done, update 'Last done at (hours)' (and the date) in the next weekly file.",
                    "5. 'Parts needed' (optional): one row per spare part a service uses (Machine, Service, Part code, Qty needed). "
                    "Part code = the Material code in your warehouse stock list. Upload the stock list as Stock_DDMMYYYY.xlsx "
                    "and the app checks that the parts are in stock.",
                    "6. Machine and service names must be written exactly the same in all sheets.",
                    "7. The rows in this template are only examples. Replace them with your own machines, services and parts.",
                    "هر هفته: این فایل را کپی کنید، ساعت‌ها را در برگه‌ی Hours به‌روز کنید و با نام Service_روزماهسال ذخیره و آپلود کنید.",
                    "وقتی سرویسی انجام شد، ستون Last done را در فایل هفته‌ی بعد به‌روز کنید.",
                ]
            }
        ).to_excel(w, sheet_name="Instructions", index=False)

        for ws in w.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 110 if ws.title == "Instructions" else 24
    return out.getvalue()


# ===================================================================
#                     SHARED FILTER / LOADING HELPERS
# ===================================================================
def period_selector(files, key):
    min_d = min(f["file_date"] for f in files)
    max_d = max(f["file_date"] for f in files)

    preset = st.radio(
        "Period",
        ["All data", "Last 7 days", "Last 30 days", "Custom range"],
        horizontal=True,
        key=f"{key}_preset",
        help="'Last N days' counts back from the newest file you have.",
    )

    if preset == "All data":
        start, end = min_d, max_d
    elif preset == "Last 7 days":
        start, end = max(min_d, max_d - timedelta(days=6)), max_d
    elif preset == "Last 30 days":
        start, end = max(min_d, max_d - timedelta(days=29)), max_d
    else:
        c1, c2 = st.columns(2)
        start = c1.date_input("From", min_d, min_value=min_d, max_value=max_d, key=f"{key}_from")
        end = c2.date_input("To", max_d, min_value=min_d, max_value=max_d, key=f"{key}_to")
        if end < start:
            st.error("The 'To' date must be on or after the 'From' date.")
            return None, None, None

    selected = [f for f in files if start <= f["file_date"] <= end]
    days = (end - start).days + 1
    st.caption(f"📅 {start:%d %b %Y} → {end:%d %b %Y}  •  {days} days  •  {len(selected)} file(s)")
    return selected, start, end


def load_filtered_data(key):
    """Common flow for Dashboard and Trends. Returns (prod_df, err_df) or (None, None)."""
    files = safe_get_files()
    if files is None:
        return None, None
    if not files:
        st.info("No files yet. Go to **📤 Upload Data** to add your first production file.")
        return None, None

    selected, _, _ = period_selector(files, key)
    if selected is None:
        return None, None
    if not selected:
        st.warning("No files in this period. Try a wider range.")
        return None, None

    with st.spinner(f"Reading {len(selected)} file(s)…"):
        prod_df, err_df, problems = load_data(tuple(f["name"] for f in selected))

    if problems:
        with st.expander(f"⚠️ {len(problems)} sheet(s)/file(s) were skipped", expanded=False):
            for p in problems:
                st.write(f"- {p}")

    if prod_df.empty:
        st.warning("No production data could be read from the selected files.")
        return None, None

    machines = ["All machines"] + sorted(prod_df["ProductionTypeForTon"].unique())
    machine = st.selectbox("Machine", machines, key=f"{key}_machine")
    if machine != "All machines":
        prod_df = prod_df[prod_df["ProductionTypeForTon"] == machine]
        if not err_df.empty:
            err_df = err_df[err_df["MachineType"] == machine]

    if prod_df.empty:
        st.warning("No data for this machine in the selected period.")
        return None, None

    return prod_df.copy(), err_df.copy()


# ===================================================================
#                           UPLOAD PAGE
# ===================================================================
def page_upload():
    st.header("📤 Upload Production Files")
    st.write("Add your daily production Excel files (.xlsx). You can select many at once.")

    with st.expander("ℹ️ How should my files look?"):
        st.markdown(
            """
            - **File name** must contain the date as **DDMMYYYY**, e.g. `Production_05112026.xlsx`.
            - **Sheet name** (or file name) should mention the machine: `GASTI`, `125`, `200` or `1000`.
            - Production table: headers in rows 2–3, data in rows 4–9, columns D–P.
            - Downtime list: from row 12 down, reason in column G and duration in column H.
            - **Machine hours / service file:** name it `Service_DDMMYYYY.xlsx`
              (get the template on the 🛠️ Service page). It is kept separate from production data.
            - **Warehouse stock list:** name it `Stock_DDMMYYYY.xlsx` (columns: Material, Material Description,
              Storage Bin, Current stock, Unit). The newest one is used for the parts check.
            - Uploading a file with the same name **replaces** the old one.
            """
        )

    uploaded = st.file_uploader(
        "Drag and drop files here, or click Browse",
        type=["xlsx"],
        accept_multiple_files=True,
    )

    if uploaded:
        existing = set()
        files = safe_get_files()
        if files:
            existing = {f["name"] for f in files}

        preview = pd.DataFrame(
            [
                {
                    "File": uf.name,
                    "Detected date": parse_filename_date_to_datetime(uf.name)
                    if filename_has_valid_date(uf.name)
                    else "❓ not found",
                    "Size (KB)": round(uf.size / 1024, 1),
                    "Status": "Will replace existing" if uf.name in existing else "New",
                }
                for uf in uploaded
            ]
        )
        show_df(preview, hide_index=True)

        no_date = [uf.name for uf in uploaded if not filename_has_valid_date(uf.name)]
        if no_date:
            st.warning(
                "These files have no valid DDMMYYYY date in their name, so today's date would "
                "be used: " + ", ".join(no_date)
            )

    if st.button("⬆️ Upload", type="primary", disabled=not uploaded):
        ok_count, failed = 0, []
        bar = st.progress(0.0, "Starting…")
        for i, uf in enumerate(uploaded):
            bar.progress(i / len(uploaded), f"Uploading {uf.name} ({i + 1}/{len(uploaded)})")
            ok, msg = supabase_upload_file(uf.getvalue(), uf.name)
            if ok:
                ok_count += 1
            else:
                failed.append((uf.name, msg))
        bar.progress(1.0, "Done")

        clear_caches()
        if ok_count:
            st.success(f"✅ {ok_count} file(s) uploaded. They're ready in the Dashboard.")
            st.toast("Upload complete", icon="✅")
        for name, msg in failed:
            st.error(f"❌ {name}: {msg}")


# ===================================================================
#                           ARCHIVE PAGE
# ===================================================================
def page_archive():
    st.header("📁 Data Archive")
    st.write("Browse, search and download stored files.")

    files = safe_get_files()
    if files is None:
        return
    try:  # service files are listed here too
        files = sorted(
            files + get_service_files() + get_stock_files(), key=lambda f: (f["file_date"], f["name"])
        )
    except Exception:
        pass
    if not files:
        st.info("The archive is empty. Upload a file to get started.")
        return

    c1, c2 = st.columns([3, 1])
    query = c1.text_input("🔍 Search by file name", placeholder="e.g. 11202 or gasti")
    newest_first = c2.toggle("Newest first", value=True)

    shown = [f for f in files if query.lower() in f["name"].lower()] if query else list(files)
    shown.sort(key=lambda f: f["file_date"], reverse=newest_first)

    if not shown:
        st.info("No file matches your search.")
        return

    st.caption(f"Showing {len(shown)} of {len(files)} files")
    show_df(
        pd.DataFrame({"File": [f["name"] for f in shown], "Date": [f["file_date"] for f in shown]}),
        hide_index=True,
    )

    st.subheader("Download a file")
    choice = st.selectbox("Choose a file", [f["name"] for f in shown])
    data = supabase_download_file(choice)
    if data:
        st.download_button("⬇️ Download", data, file_name=choice, mime=XLSX_MIME)
    else:
        st.error("This file could not be downloaded right now.")

    # ---------------- Admin ----------------
    with st.expander("🔒 Admin: delete files"):
        if not ADMIN_PASSWORD:
            st.info(
                "Deleting is disabled until an **ADMIN_PASSWORD** is set in the app's secrets "
                "(Streamlit Cloud → Settings → Secrets)."
            )
            return

        pwd = st.text_input("Admin password", type="password")
        to_delete = st.multiselect("Files to delete", [f["name"] for f in files])
        delete_all = st.checkbox("Delete ALL files instead")
        confirm = st.checkbox("I understand this cannot be undone")

        if st.button("🗑️ Delete", type="primary"):
            if not hmac.compare_digest(pwd.encode(), str(ADMIN_PASSWORD).encode()):
                st.error("Wrong password.")
            elif not confirm:
                st.warning("Please tick the confirmation box first.")
            else:
                names = [f["name"] for f in files] if delete_all else to_delete
                if not names:
                    st.warning("Select at least one file.")
                elif supabase_delete_files(names):
                    clear_caches()
                    st.success(f"Deleted {len(names)} file(s).")
                    st.rerun()
                else:
                    st.error("Deletion failed. Please try again.")


# ===================================================================
#                          DASHBOARD PAGE
# ===================================================================
def page_dashboard():
    st.header("📊 Production Dashboard")

    prod_df, err_df = load_filtered_data("dash")
    if prod_df is None:
        return

    # ---------------- Data check (efficiency above limit) ----------------
    s1, s2 = st.columns([1, 2])
    limit = s1.number_input(
        "Flag efficiency above (%)", min_value=50, max_value=1000, value=100, step=5, key="eff_limit"
    )
    suspicious = find_suspicious(prod_df, limit)
    exclude = False
    if not suspicious.empty:
        s2.warning(
            f"⚠️ {len(suspicious)} row(s) have efficiency above {limit}%. "
            "Open the **Data check** tab to see exactly where."
        )
        exclude = s2.checkbox("Exclude these rows from the numbers and charts", key="eff_exclude")
    if exclude:
        prod_df = prod_df.drop(index=suspicious.index)
        if prod_df.empty:
            st.warning("Nothing left after excluding the flagged rows.")
            return

    # ---------------- KPI cards ----------------
    qty = prod_df["PackQty"].sum()
    pot = prod_df["PotentialProduction"].sum()
    efficiency = (qty / pot * 100) if pot > 0 else 0
    waste_pct = (prod_df["Waste"].sum() / qty * 100) if qty > 0 else 0
    downtime_h = (err_df["Duration"].sum() / 60) if not err_df.empty else 0

    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Total production", f"{prod_df['Ton'].sum():,.2f} t")
    k2.metric("Efficiency", f"{efficiency:.1f} %")
    k3.metric("Waste", f"{waste_pct:.2f} %")
    k4.metric("Downtime", f"{downtime_h:,.1f} h")

    tab_prod, tab_quality, tab_down, tab_check, tab_data = st.tabs(
        ["📦 Production", "🎯 Waste & Efficiency", "🔻 Downtime", "🔍 Data check", "🗂️ Raw data"]
    )

    with tab_prod:
        ton_df = (
            prod_df.groupby("Product")["Ton"].sum().reset_index().sort_values("Ton", ascending=False)
        )
        fig = px.treemap(
            ton_df,
            path=[px.Constant("All products"), "Product"],
            values="Ton",
            color="Product",
            title="Total tons by product",
        )
        show_chart(fig)

    with tab_quality:
        waste_df = (
            prod_df.groupby("Product").agg(waste=("Waste", "sum"), qty=("PackQty", "sum")).reset_index()
        )
        waste_df["Waste(%)"] = np.where(waste_df["qty"] > 0, waste_df["waste"] / waste_df["qty"] * 100, 0)
        waste_df = waste_df.sort_values("Waste(%)", ascending=False)
        fig2 = px.bar(
            waste_df, x="Product", y="Waste(%)", text_auto=".2f", color="Product",
            title="Waste percentage by product",
        )
        show_chart(fig2)

        eff_df = (
            prod_df.groupby("Product")
            .agg(qty=("PackQty", "sum"), pot=("PotentialProduction", "sum"))
            .reset_index()
        )
        eff_df["Efficiency(%)"] = np.where(eff_df["pot"] > 0, eff_df["qty"] / eff_df["pot"] * 100, 0)
        eff_df = eff_df.sort_values("Efficiency(%)", ascending=False)
        fig3 = px.bar(
            eff_df, x="Product", y="Efficiency(%)", text_auto=".2f", color="Efficiency(%)",
            color_continuous_scale=px.colors.sequential.Greens,
            title="Efficiency by product",
        )
        show_chart(fig3)

    with tab_down:
        if err_df.empty:
            st.info("No downtime data for this selection.")
        else:
            esum = (
                err_df.groupby("Error")["Duration"].sum().reset_index().sort_values("Duration", ascending=False)
            )
            fig4 = px.bar(
                esum, x="Error", y="Duration", text_auto=".0f", color="Error",
                color_discrete_sequence=px.colors.qualitative.Set2,
                title="Downtime by reason (minutes)",
            )
            fig4.update_layout(xaxis_tickangle=-45, showlegend=False)
            show_chart(fig4)
            st.download_button(
                "⬇️ Download downtime summary (CSV)",
                esum.to_csv(index=False).encode(),
                file_name="error_summary.csv",
                mime="text/csv",
            )

    with tab_check:
        if suspicious.empty:
            st.success(f"✅ No row has efficiency above {limit}%.")
        else:
            st.write(
                f"**{len(suspicious)} row(s)** above {limit}%. "
                "Open the file, go to the sheet, and check the Excel row shown."
            )
            view = suspicious[
                ["File", "Sheet", "ExcelRow", "Date", "Product", "StartRaw", "StartRead",
                 "EndRaw", "EndRead", "Duration", "Capacity", "PackQty",
                 "PotentialProduction", "Efficiency(%)", "Likely cause"]
            ].sort_values("Efficiency(%)", ascending=False)
            view = view.rename(
                columns={
                    "ExcelRow": "Excel row",
                    "StartRaw": "Start (in Excel)",
                    "StartRead": "Start (read as)",
                    "EndRaw": "End (in Excel)",
                    "EndRead": "End (read as)",
                    "Duration": "Duration (h)",
                    "PotentialProduction": "Max possible qty",
                }
            )
            show_df(
                view.style.format({"Efficiency(%)": "{:.1f} %", "Duration (h)": "{:.2f}"}),
                hide_index=True,
            )
            st.download_button(
                "⬇️ Download flagged rows (CSV)",
                view.to_csv(index=False).encode(),
                file_name="flagged_rows.csv",
                mime="text/csv",
            )

    with tab_data:
        show_df(prod_df.style.format({"Efficiency(%)": "{:.2f} %"}), hide_index=True)
        st.download_button(
            "⬇️ Download production data (CSV)",
            prod_df.to_csv(index=False).encode(),
            file_name="production_data.csv",
            mime="text/csv",
        )


# ===================================================================
#                          TREND ANALYSIS PAGE
# ===================================================================
def _line(df, y, title):
    fig = px.line(df, x="Date", y=y, markers=True, title=title)
    show_chart(fig)


def page_trends():
    st.header("📈 Trend Analysis")

    prod_df, err_df = load_filtered_data("trend")
    if prod_df is None:
        return

    gsel = st.radio("Group by", list(FREQUENCIES.keys()), horizontal=True)
    freq = FREQUENCIES[gsel]

    prod_df["Date"] = pd.to_datetime(prod_df["Date"])
    p = prod_df.set_index("Date")

    tab_prod, tab_err = st.tabs(["📦 Production", "🔻 Downtime"])

    with tab_prod:
        ton = p.resample(freq)["Ton"].sum().reset_index()
        ton = ton[ton["Ton"] > 0]
        if not ton.empty:
            _line(ton, "Ton", f"{gsel} total production (tons)")

        eff = p.groupby(pd.Grouper(freq=freq)).agg(
            qty=("PackQty", "sum"), pot=("PotentialProduction", "sum")
        ).reset_index()
        eff["Efficiency(%)"] = np.where(eff["pot"] > 0, eff["qty"] / eff["pot"] * 100, 0)
        eff = eff[eff["qty"] > 0]
        if not eff.empty:
            _line(eff, "Efficiency(%)", f"{gsel} efficiency (%)")

        waste = p.groupby(pd.Grouper(freq=freq)).agg(
            w=("Waste", "sum"), qty=("PackQty", "sum")
        ).reset_index()
        waste["Waste(%)"] = np.where(waste["qty"] > 0, waste["w"] / waste["qty"] * 100, 0)
        waste = waste[waste["qty"] > 0]
        if not waste.empty:
            _line(waste, "Waste(%)", f"{gsel} waste (%)")

    with tab_err:
        if err_df.empty:
            st.info("No downtime data for this selection.")
        else:
            err_df["Date"] = pd.to_datetime(err_df["Date"])
            dt = err_df.set_index("Date").resample(freq)["Duration"].sum().reset_index()
            dt = dt[dt["Duration"] > 0]
            if dt.empty:
                st.info("No downtime recorded in this period.")
            else:
                _line(dt, "Duration", f"{gsel} total downtime (minutes)")


# ===================================================================
#                           SERVICE PAGE
# ===================================================================
def _describe_service(r):
    parts = []
    hl, dl = r["Hours left"], r["Days left"]
    if pd.notna(hl):
        parts.append(f"{abs(hl):,.0f} h overdue" if hl <= 0 else f"{hl:,.0f} h left")
    if pd.notna(dl):
        parts.append(f"{abs(dl):.0f} days overdue" if dl <= 0 else f"~{dl:.0f} days left")
    if str(r.get("Parts", "")).startswith("❌"):
        parts.append("❗ " + str(r["Parts"])[2:])
    return " · ".join(parts) or "check the data"


def page_service():
    st.header("🛠️ Machine Service")
    st.caption(
        "Each week, upload a file named Service_DDMMYYYY.xlsx with the new machine hours "
        "(📤 Upload Data page). This page does the countdown and the alarms."
    )

    with st.expander("📥 Excel template & how it works"):
        st.markdown(
            """
            1. Download the template and fill in your machines and services.
            2. **Every week** copy the file, update the **Hours** sheet, save as `Service_DDMMYYYY.xlsx` and upload it.
            3. When a service is done, update *Last done at (hours)* (and the date) in the next weekly file.
            4. The days left are **estimated** from the average hours per day of the last weeks,
               so after two weekly files you get a countdown in days.
            """
        )
        st.download_button(
            "⬇️ Download template",
            build_service_template(),
            file_name=f"Service_{today_local():%d%m%Y}.xlsx",
            mime=XLSX_MIME,
        )

    files = safe_service_files()
    if files is None:
        return
    if not files:
        st.info("No service file yet. Download the template above, fill it in and upload it on **📤 Upload Data**.")
        return

    with st.spinner("Reading service files…"):
        hours_df, plan_df, parts_df, problems = load_service_data(tuple(f["name"] for f in files[-8:]))

    if problems:
        with st.expander(f"⚠️ {len(problems)} problem(s) in the service files", expanded=True):
            for p in problems:
                st.write(f"- {p}")

    if hours_df.empty:
        st.warning("No machine hours could be read. Check the 'Hours' sheet (columns: Machine, Hours).")
        return

    today = today_local()
    latest = hours_df["date"].max()
    age = (today - latest).days
    if age > 7:
        st.warning(f"⏰ Machine hours were last updated on {latest:%d %b %Y} ({age} days ago). Please upload this week's file.")
    else:
        st.caption(f"Machine hours as of {latest:%d %b %Y}")

    c1, c2 = st.columns(2)
    warn_days = c1.number_input("Warn when this many days (or fewer) are left", 1, 90, 14, key="svc_days")
    warn_pct = c2.number_input("…or when this % of the interval (or less) is left", 1, 50, 10, key="svc_pct")

    status = compute_service_status(hours_df, plan_df, today, warn_days, warn_pct)

    # warehouse stock (optional): newest Stock_*.xlsx
    stock_df = pd.DataFrame()
    try:
        stock_files = get_stock_files()
    except Exception:
        stock_files = []
    if stock_files:
        stock_df, stock_problem = load_stock(stock_files[-1]["name"])
        if stock_problem:
            st.warning(stock_problem)
        else:
            st.caption(f"📦 Warehouse stock: {stock_files[-1]['name']} · {len(stock_df):,} items")
    elif not parts_df.empty:
        st.info("Your service plan lists parts, but no stock list is uploaded yet. Upload it as Stock_DDMMYYYY.xlsx to check availability.")
    status = add_parts_check(status, parts_df, stock_df)

    if status.empty:
        st.warning("No services found in the newest file. Check the 'Service plan' sheet.")
    else:
        over = status[status["_level"] == 0]
        soon = status[status["_level"] == 1]

        k1, k2, k3 = st.columns(3)
        k1.metric("🔴 Overdue", len(over))
        k2.metric("🟠 Due soon", len(soon))
        k3.metric("🟢 OK", int((status["_level"] == 2).sum()))

        for _, r in over.iterrows():
            st.error(f"**{r['Machine']} – {r['Service']}**: {_describe_service(r)}")
        for _, r in soon.iterrows():
            st.warning(f"**{r['Machine']} – {r['Service']}**: {_describe_service(r)}")

        view = status.drop(columns=["_level", "_short"])
        show_df(
            view,
            hide_index=True,
            column_config={
                "Hours now": st.column_config.NumberColumn(format="%.0f"),
                "Next due (h)": st.column_config.NumberColumn(format="%.0f"),
                "Hours left": st.column_config.NumberColumn(format="%.0f"),
                "Days left": st.column_config.NumberColumn(format="%.0f"),
                "Avg h/day": st.column_config.NumberColumn(format="%.1f"),
                "Used %": st.column_config.ProgressColumn(format="%.0f%%", min_value=0, max_value=100),
            },
        )
        st.download_button(
            "⬇️ Download service status (CSV)",
            view.to_csv(index=False).encode(),
            file_name="service_status.csv",
            mime="text/csv",
        )
        st.caption("Days left = estimated from the average hours per day (needs at least two weekly files), or from the calendar interval.")

        order = build_order_list(status, parts_df, stock_df)
        if not order.empty:
            st.subheader("🛒 Parts to order")
            st.caption("Missing parts for services that are overdue or due soon.")
            show_df(order, hide_index=True)
            st.download_button(
                "⬇️ Download order list (CSV)",
                order.to_csv(index=False).encode(),
                file_name="parts_to_order.csv",
                mime="text/csv",
            )

    with st.expander("📈 Machine hours history"):
        fig = px.line(
            hours_df.sort_values("date"), x="date", y="hours", color="machine",
            markers=True, title="Machine hours (weekly readings)",
        )
        show_chart(fig)


# ===================================================================
#                            CONTACT PAGE
# ===================================================================
def page_contact():
    st.header("📞 Contact")
    st.markdown(
        """
        **Mohammad Asadollahzadeh**

        📧 Email: **m.asdz@yahoo.com**

        🌐 LinkedIn: *Available upon request*

        ---

        In today's industrial world, data-driven decisions are essential.
        This dashboard helps streamline production analysis, reduce downtime,
        and improve efficiency.

        Need any of these?
        - Custom dashboards
        - AI integration
        - Automation systems
        - Production optimization

        Feel free to get in touch.
        """
    )


# ===================================================================
#                           NAVIGATION
# ===================================================================
PAGES = {
    "📊 Dashboard": page_dashboard,
    "📈 Trends": page_trends,
    "🛠️ Service": page_service,
    "📤 Upload Data": page_upload,
    "📁 Data Archive": page_archive,
    "📞 Contact": page_contact,
}

st.sidebar.title("🏭 Production")
choice = st.sidebar.radio("Go to", list(PAGES.keys()), label_visibility="collapsed")

st.sidebar.divider()
try:
    _files = get_all_supabase_files()
    if _files:
        st.sidebar.caption(
            f"{len(_files)} files stored\n\nLatest data: {max(f['file_date'] for f in _files):%d %b %Y}"
        )
except Exception:
    st.sidebar.caption("⚠️ Storage not reachable")

try:  # service alarm in the sidebar, visible on every page
    _sf = get_service_files()
    if _sf:
        _h, _p, _pp, _ = load_service_data(tuple(f["name"] for f in _sf[-8:]))
        _s = compute_service_status(_h, _p, today_local())
        if not _s.empty:
            _over = int((_s["_level"] == 0).sum())
            _soon = int((_s["_level"] == 1).sum())
            if _over:
                st.sidebar.error(f"🔴 {_over} service(s) overdue")
            if _soon:
                st.sidebar.warning(f"🟠 {_soon} service(s) due soon")
except Exception:
    pass

if st.sidebar.button("🔄 Refresh data"):
    clear_caches()
    st.rerun()

PAGES[choice]()
