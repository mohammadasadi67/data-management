# app_dark_pro.py
# Production & Error Analysis Dashboard — Dark Pro Edition
# Built for Mohammad Asadollahzadeh — Enterprise-grade UI/UX, single-file deploy

import os
import base64
import time
import re
from io import BytesIO
from datetime import datetime, timedelta, time as datetime_time

import numpy as np
import pandas as pd
px.defaults.template = "plotly_white"

import plotly.graph_objects as go
import streamlit as st
from supabase import create_client, Client

# ===============================
# THEME & GLOBAL CONFIG
# ===============================

st.set_page_config(
    page_title="Dark Pro • Production & Error Analytics",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Inject Dark Pro CSS ---
DARK_CSS = """
<style>
/* Base */
:root {
  --bg: #0f1115;
  --panel: #151924;
  --panel-2: #171b26;
  --text: #e6eefc;
  --muted: #96a0b5;
  --primary: #61dafb;  /* neon cyan */
  --accent: #9b6bff;   /* neon purple */
  --warn: #ffb020;
  --danger: #ff4d4d;
  --success: #00e09b;
  --glow: 0 0 20px rgba(97,218,251,0.35);
}

html, body, [class*="css"]  {
  background: var(--bg) !important;
  color: var(--text) !important;
  font-family: Inter, -apple-system, BlinkMacSystemFont, Segoe UI, Roboto, Arial, "Noto Sans", "Apple Color Emoji", "Segoe UI Emoji", "Segoe UI Symbol";
}

/* Sidebar */
section[data-testid="stSidebar"] {
  background: linear-gradient(180deg, #12151e 0%, #0f1115 100%) !important;
  border-right: 1px solid rgba(255,255,255,0.06);
}

section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] p {
  color: var(--muted) !important;
}

/* Headers */
h1, h2, h3, .stMarkdown h1, .stMarkdown h2, .stMarkdown h3 {
  letter-spacing: 0.2px;
  color: var(--text) !important;
}

h1 {
  font-size: 1.85rem;
}

/* Cards */
.block-container { padding-top: 1.5rem; }
.stMetric {
  background: linear-gradient(180deg, #151924, #101420);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 18px;
  padding: 16px 14px;
  box-shadow: var(--glow);
}
div[data-testid="stMetricValue"] {
  color: var(--primary) !important;
  font-weight: 800;
}

/* Buttons */
.stButton>button {
  background: linear-gradient(180deg, #1a2030 0%, #121726 100%) !important;
  color: var(--text) !important;
  border: 1px solid rgba(255,255,255,0.07) !important;
  border-radius: 14px !important;
  padding: 10px 16px !important;
  transition: all .2s ease;
  box-shadow: 0 0 0 transparent;
}
.stButton>button:hover {
  transform: translateY(-1px);
  border-color: rgba(97,218,251,0.5) !important;
  box-shadow: 0 0 12px rgba(97,218,251,0.25);
}

/* Inputs */
.stSelectbox, .stMultiSelect, .stDateInput, .stTextInput, .stNumberInput {
  background: var(--panel) !important;
}
div[data-baseweb="select"]>div {
  background: var(--panel) !important;
  color: var(--text) !important;
}
.stTextInput>div>div>input, .stDateInput input {
  color: var(--text) !important;
}

/* Tables */
.dataframe {
  border-radius: 12px !important;
  overflow: hidden;
}
thead tr th {
  background: #151924 !important;
  color: var(--muted) !important;
}
tbody tr:nth-child(even) td {
  background: #121725 !important;
}
tbody tr:nth-child(odd) td {
  background: #101622 !important;
}

/* Plotly container */
.js-plotly-plot .plotly .main-svg {
  border-radius: 14px;
}

/* Expander */
.streamlit-expanderHeader {
  background: #141927 !important; color: var(--text) !important;
  border-radius: 10px !important; border: 1px solid rgba(255,255,255,0.06);
}

/* Toast-like notes */
.note {
  padding: 10px 14px; border-radius: 10px; border: 1px dashed rgba(255,255,255,0.15);
  color: var(--muted); background: #111522;
}
</style>
"""
st.markdown(DARK_CSS, unsafe_allow_html=True)

# Global Plotly Theme
#px.defaults.template = "plotly_dark"
px.defaults.template = "plotly_white"

px.defaults.width = None
px.defaults.height = 450

# ===============================
# SUPABASE CONFIG (secrets first)
# ===============================

SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# Initialize Supabase client globally
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"


# ===============================
# UTILITIES
# ===============================

def toast(msg: str, icon: str = "✅"):
    try:
        st.toast(f"{icon} {msg}")
    except Exception:
        st.info(msg)

def parse_filename_date_to_datetime(filename):
    try:
        date_str_match = re.search(r'(\d{8})', filename)
        if date_str_match:
            date_str_part = date_str_match.group(1)
            if len(date_str_part) == 8 and date_str_part.isdigit():
                day = int(date_str_part[0:2])
                month = int(date_str_part[2:4])
                year = int(date_str_part[4:8])
                if not (1 <= month <= 12 and 1 <= day <= 31 and 2000 <= year <= datetime.now().year + 5):
                    raise ValueError("Invalid date components")
                return datetime(year, month, day).date()
    except Exception:
        pass
    return datetime.now().date()

def get_download_link(file_bytes, filename):
    b64 = base64.b64encode(file_bytes).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}">Download {filename}</a>'
    return href

def convert_time(val):
    if pd.isna(val) or pd.isnull(val): return 0
    if isinstance(val, datetime_time): return val.hour + val.minute/60 + val.second/3600
    if isinstance(val, datetime): return val.hour + val.minute/60 + val.second/3600
    if isinstance(val, (int, float)):
        if 0 <= val < 1: return val * 24
        try:
            vi = int(val); h = vi // 100; m = vi % 100
            if 0 <= m < 60: return (h % 24) + m/60
        except ValueError:
            pass
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    dt = datetime.strptime(s, fmt)
                    return dt.hour + dt.minute/60 + (dt.second if fmt == "%H:%M:%S" else 0)/3600
                except ValueError:
                    continue
        if s.isdigit():
            vi = int(s); h = vi // 100; m = vi % 100
            if 0 <= m < 60: return (h % 24) + m/60
        try:
            return float(s)
        except ValueError:
            pass
    return 0

def convert_duration_to_minutes(duration_val):
    if pd.isna(duration_val) or pd.isnull(duration_val): return 0
    if isinstance(duration_val, timedelta): return duration_val.total_seconds() / 60
    if isinstance(duration_val, datetime):
        return (duration_val.hour*3600 + duration_val.minute*60 + duration_val.second)/60
    if isinstance(duration_val, datetime_time):
        return (duration_val.hour*60 + duration_val.minute + duration_val.second/60)
    if isinstance(duration_val, (int, float)):
        if 0 <= duration_val < 1: return duration_val * 24 * 60
        if duration_val < 2400:
            try:
                vi = int(duration_val); h = vi // 100; m = vi % 100
                if 0 <= h < 24 and 0 <= m < 60: return h*60 + m
            except ValueError:
                pass
        return float(duration_val) * 60
    if isinstance(duration_val, str):
        s = duration_val.strip()
        if ":" in s:
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    dt = datetime.strptime(s, fmt)
                    if fmt == "%H:%M:%S": return dt.hour*60 + dt.minute + dt.second/60
                    return dt.hour*60 + dt.minute
                except ValueError:
                    continue
        if s.isdigit():
            vi = int(s); h = vi // 100; m = vi % 100
            if 0 <= h < 24 and 0 <= m < 60: return h*60 + m
        try:
            return float(s) * 60
        except ValueError:
            pass
    return 0

def determine_machine_type(name_string):
    s_lower = str(name_string).strip().lower()
    if "gasti" in s_lower: return "GASTI"
    if "200cc" in s_lower or s_lower == "200": return "200cc"
    if "125" in s_lower or s_lower == "125": return "125"
    if "1000cc" in s_lower or s_lower == "1000": return "1000cc"
    return "Unknown Machine"

def calculate_ton(row):
    product_type_str = str(row.get("ProductionTypeForTon", "")).strip().lower()
    qty = row.get("PackQty", 0) or 0
    grams_per_packet = 0
    if "gasti" in product_type_str: grams_per_packet = 90
    elif "200cc" in product_type_str: grams_per_packet = 200
    else:
        try:
            nv = float(row.get("ProductionTypeForTon", 0))
            if nv == 200: grams_per_packet = 200
        except Exception: pass
    if grams_per_packet == 0:
        if "125" in product_type_str: grams_per_packet = 125
        else:
            try:
                nv = float(row.get("ProductionTypeForTon", 0))
                if int(nv) == 125: grams_per_packet = 125
            except Exception: pass
    if grams_per_packet == 0:
        if "1000cc" in product_type_str: grams_per_packet = 1000
        else:
            try:
                nv = float(row.get("ProductionTypeForTon", 0))
                if str(int(nv)).startswith("1000"): grams_per_packet = 1000
            except Exception: pass
    if grams_per_packet == 0: grams_per_packet = 1000
    return (qty * grams_per_packet) / 1_000_000

# ===============================
# SUPABASE I/O
# ===============================

@st.cache_data(ttl=3600, show_spinner="📦 Fetching files from Supabase...")
def get_all_supabase_files():
    all_files = []
    try:
        items = supabase.storage.from_("uploads").list(path="", options={"limit": 5000, "directories": False})
        if not items: return []
        for it in items:
            name = it.get("name")
            if name and name.lower().endswith(".xlsx"):
                all_files.append({
                    "name": name,
                    "full_path": name,
                    "file_date": parse_filename_date_to_datetime(name),
                    "metadata": it
                })
    except Exception as e:
        st.error(f"❌ Error listing files: {e}")
        return []
    return all_files

def download_from_supabase(filename):
    max_retries = 3
    delay = 0.5
    for attempt in range(max_retries):
        try:
            data = supabase.storage.from_("uploads").download(filename)
            return data
        except Exception as e:
            if "not_found" in str(e).lower():
                time.sleep(delay)
            else:
                st.error(f"❌ Error downloading '{filename}' (attempt {attempt+1}): {e}")
                return None
    st.error(f"❌ Download failed after {max_retries} attempts. Not found: {filename}")
    return None

def clear_supabase_bucket():
    try:
        items = supabase.storage.from_("uploads").list(path="", options={"limit": 5000, "directories": False})
        to_delete = [it["name"] for it in items if it.get("name")]
        if to_delete:
            supabase.storage.from_("uploads").remove(to_delete)
            toast(f"Deleted {len(to_delete)} files from Supabase.", "🗑️")
            get_all_supabase_files.clear()
            st.rerun()
        else:
            st.info("No files to delete.")
    except Exception as e:
        st.error(f"❌ Error deleting files: {e}")

def upload_to_supabase(files_list):
    uploaded = 0
    total = len(files_list)
    if total == 0:
        st.info("No files selected."); return
    bar = st.progress(0, text="Uploading files...")
    for i, file in enumerate(files_list):
        path = file.name
        try:
            try:
                supabase.storage.from_("uploads").remove([path])
            except Exception as e:
                if "not_found" not in str(e).lower():
                    st.warning(f"⚠️ Could not remove existing '{file.name}': {e}")
            resp = supabase.storage.from_("uploads").upload(
                path,
                file.getvalue(),
                {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )
            if isinstance(resp, dict) and resp.get("error"):
                st.error(f"❌ Upload error for '{file.name}': {resp['error'].get('message','Unknown')}")
            else:
                uploaded += 1
                bar.progress((i+1)/total, text=f"Uploading '{file.name}' ({i+1}/{total})...")
        except Exception as e:
            st.error(f"❌ Error during upload of '{file.name}': {e}")
    bar.empty()
    if uploaded:
        toast(f"Uploaded {uploaded}/{total} file(s).", "✅")
        get_all_supabase_files.clear()
        st.rerun()
    else:
        st.error("No files were uploaded.")

# ===============================
# EXCEL PARSE
# ===============================

def read_production_data(df_raw_sheet, uploaded_file_name, selected_sheet_name, file_date_obj):
    try:
        row2 = df_raw_sheet.iloc[1, 3:16].fillna("").astype(str).tolist()
        row3 = df_raw_sheet.iloc[2, 3:16].fillna("").astype(str).tolist()
        combined = []
        for r2, r3 in zip(row2, row3):
            pick = r3.strip() if r3.strip() and r3.strip() != "nan" else r2.strip()
            combined.append(pick if pick else "")
        headers = [h if h else f"Unnamed_Col_{i}" for i, h in enumerate(combined)]
    except IndexError as e:
        st.error(f"❌ Header parse error in '{uploaded_file_name}' • Sheet '{selected_sheet_name}': {e}")
        return pd.DataFrame()

    data = df_raw_sheet.iloc[3:9, 3:16].copy()
    if len(headers) == data.shape[1]:
        data.columns = headers
    else:
        st.error(f"❌ Columns mismatch in '{uploaded_file_name}' • Sheet '{selected_sheet_name}'.")
        return pd.DataFrame()

    rename_map = {
        "start": "Start",
        "finish": "End",
        "time": "Duration_Original",
        "production title": "Product",
        "cap": "Capacity",
        "manpower": "Manpower",
        "quanity": "PackQty",
        "date": "ProdDate_Original",
        "waste": "Waste"
    }
    actual_map = {k: v for k, v in rename_map.items() if k in data.columns}
    data = data.rename(columns=actual_map)

    data["Date"] = file_date_obj
    mtype = determine_machine_type(selected_sheet_name)
    if mtype == "Unknown Machine":
        mtype = determine_machine_type(uploaded_file_name)
    data["ProductionTypeForTon"] = mtype

    required = ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Date", "Waste", "ProductionTypeForTon"]
    for col in required:
        if col not in data.columns:
            st.warning(f"⚠️ Missing column '{col}' in '{uploaded_file_name}' • '{selected_sheet_name}'")
            data[col] = pd.NA
            if col in ["PackQty", "Waste", "Capacity", "Manpower"]:
                data[col] = 0

    if "Product" in data.columns:
        data["Product"] = data["Product"].fillna("").astype(str).str.strip().str.title()
        data = data[data["Product"] != ""]

    data["StartTime"] = data["Start"].apply(convert_time)
    data["EndTime"] = data["End"].apply(convert_time)
    data["EndTimeAdjusted"] = data.apply(lambda r: r["EndTime"] + 24 if r["EndTime"] < r["StartTime"] else r["EndTime"], axis=1)
    data["Duration"] = data["EndTimeAdjusted"] - data["StartTime"]
    data = data.dropna(subset=["Duration"])
    data = data[data["Duration"] != 0]

    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    data["NominalSpeed"] = pd.to_numeric(data.get("Capacity", 0), errors="coerce").fillna(0)
    data.drop(columns=["Capacity"], errors="ignore", inplace=True)
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)

    data["Ton"] = data.apply(calculate_ton, axis=1)

    data["Target_Hour"] = np.where(data["NominalSpeed"] > 0, data["PackQty"] / data["NominalSpeed"], 0)
    data["PotentialProduction"] = data["NominalSpeed"] * data["Duration"]
    data["Efficiency(%)"] = np.where(
        data["PotentialProduction"] > 0, (data["PackQty"] / data["PotentialProduction"]) * 100, 0
    )

    final_cols = [
        "Date", "Product", "NominalSpeed", "Manpower", "Duration", "PackQty", "Waste", "Ton",
        "PotentialProduction", "Efficiency(%)", "Target_Hour", "ProductionTypeForTon"
    ]
    for c in final_cols:
        if c not in data.columns: data[c] = 0
    return data[[c for c in final_cols if c in data.columns]]

def read_error_data(df_raw_sheet, sheet_name_for_debug="Unknown Sheet", uploaded_file_name_for_debug="Unknown File", file_date_obj=None):
    try:
        header_row = None
        for r in range(df_raw_sheet.shape[0]):
            if any(str(c).lower().strip().startswith("f12") for c in df_raw_sheet.iloc[r]):
                header_row = r; break
        if header_row is None:
            return pd.DataFrame()
        error_df = df_raw_sheet.iloc[header_row:].copy()
        error_df.columns = error_df.iloc[0].astype(str).str.lower().str.strip()
        error_df = error_df[1:].reset_index(drop=True)

        error_cols = [f"f{i}" for i in range(12, 101)]
        cols_to_melt = [c for c in error_df.columns if c in error_cols]
        if not cols_to_melt: return pd.DataFrame()

        df_long = error_df.melt(value_vars=cols_to_melt, var_name="RawErrorColumn", value_name="Duration")
        df_long["Duration"] = pd.to_numeric(df_long["Duration"], errors="coerce").fillna(0)
        df_long = df_long[df_long["Duration"] > 0].copy()
        df_long["Error"] = df_long["RawErrorColumn"].str.replace("f", "", regex=False).astype(str).str.strip()

        agg = df_long.groupby("Error")["Duration"].sum().reset_index()
        agg = agg[agg["Error"].str.isnumeric()].copy()
        agg["Date"] = file_date_obj
        agg["MachineType"] = determine_machine_type(sheet_name_for_debug)
        return agg.dropna(subset=["Date"])
    except Exception as e:
        st.error(f"❌ Error parsing error-data in '{uploaded_file_name_for_debug}' • '{sheet_name_for_debug}': {e}")
        return pd.DataFrame()

# ===============================
# METRICS
# ===============================

def calculate_metrics(prod_df: pd.DataFrame, err_df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    if prod_df.empty: return pd.DataFrame()

    prod_group_cols = [c for c in group_cols if c in prod_df.columns]
    prod_agg = prod_df.groupby(prod_group_cols).agg(
        Total_Target_Hour=('Target_Hour', 'sum'),
        Total_Duration=('Duration', 'sum'),
        Total_PackQty=('PackQty', 'sum')
    ).reset_index()

    if err_df.empty:
        prod_agg['NetProduction_H'] = prod_agg['Total_Duration']
        prod_agg['Line_Efficiency(%)'] = np.where(
            prod_agg['NetProduction_H'] > 0,
            (prod_agg['Total_Target_Hour'] / prod_agg['NetProduction_H']) * 100, 0
        )
        prod_agg['OE(%)'] = prod_agg['Line_Efficiency(%)']
        for c in ['LegalStoppage_H','IdleTime_H','Downtime_H','Losses_H','OE_Adjust_H']:
            prod_agg[c] = 0.0
        return prod_agg

    err_group_cols = [c for c in group_cols if c in err_df.columns]
    daily_err = err_df.copy()
    daily_err['Error'] = daily_err['Error'].astype(str).str.strip()

    def sum_codes(df, codes):
        codes = [str(c) for c in codes]
        return df[df['Error'].isin(codes)]['Duration'].sum() / 60  # minutes -> hours

    err_summary = daily_err.groupby(err_group_cols).apply(lambda x: pd.Series({
        'LegalStoppage_H': sum_codes(x, ['33']),
        'IdleTime_H': sum_codes(x, ['32']),
        'Downtime_H': sum_codes(x, [str(c) for c in range(21, 32)]),
        'Losses_H': sum_codes(x, [str(c) for c in range(1, 21)]),
        'OE_Adjust_H': sum_codes(x, ['24','25']),
    })).reset_index()

    daily_metrics = pd.merge(prod_agg, err_summary, on=err_group_cols, how='left').fillna(0)

    Total_Day_Hours = 24.0
    daily_metrics['GrossProduction_H'] = Total_Day_Hours - daily_metrics['LegalStoppage_H'] - daily_metrics['IdleTime_H']
    daily_metrics['NetProduction_H'] = daily_metrics['GrossProduction_H'] - daily_metrics['Downtime_H']

    daily_metrics['Line_Efficiency(%)'] = np.where(
        daily_metrics['NetProduction_H'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['NetProduction_H']) * 100, 0
    )

    daily_metrics['OE_Denominator'] = daily_metrics['NetProduction_H'] + daily_metrics['OE_Adjust_H']
    daily_metrics['OE(%)'] = np.where(
        daily_metrics['OE_Denominator'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['OE_Denominator']) * 100, 0
    )

    return daily_metrics

# ===============================
# NAVIGATION
# ===============================

if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard"

st.sidebar.markdown("### 🌌 Dark Pro Navigation")
page = st.sidebar.radio(
    "Go to:",
    options=["Upload Data", "Data Archive", "Data Analyzing Dashboard", "Trend Analysis", "Contact Me"],
    index=["Upload Data", "Data Archive", "Data Analyzing Dashboard", "Trend Analysis", "Contact Me"].index(st.session_state.page),
    key="sidebar_radio"
)
if page != st.session_state.page:
    st.session_state.page = page
    st.rerun()

st.title("⚙️ Dark Pro — Production & Error Analytics")

# ===============================
# PAGES
# ===============================

if st.session_state.page == "Upload Data":
    st.subheader("📤 Upload Your Excel Files")
    uploaded_files = st.file_uploader("Upload .xlsx files", type=["xlsx"], accept_multiple_files=True)
    colu1, colu2 = st.columns([1,1])
    with colu1:
        if st.button("🚀 Initiate Upload"):
            if uploaded_files: upload_to_supabase(uploaded_files)
            else: st.warning("Please select file(s) first.")
    with colu2:
        with st.expander("ℹ️ Upload Tips"):
            st.markdown("""
            - Filename should contain production date as **ddmmyyyy** (e.g., `21062025.xlsx`).
            - You can upload multiple files at once.
            - Existing files with the same name will be overwritten.
            """)

elif st.session_state.page == "Data Archive":
    st.subheader("📁 File Archive")
    search_query_archive = st.text_input("Search by filename:")

    files_info = get_all_supabase_files()
    if files_info:
        files_info.sort(key=lambda x: x['name'])
        if search_query_archive:
            files_info = [f for f in files_info if search_query_archive.lower() in f['name'].lower()]

        if files_info:
            for f in files_info:
                col1, col2 = st.columns([0.7, 0.3])
                with col1:
                    st.markdown(f"- **{f['name']}** — <span class='muted'>📅 {f['file_date'].strftime('%d %b %Y')}</span>", unsafe_allow_html=True)
                with col2:
                    data = download_from_supabase(f["full_path"])
                    if data:
                        st.download_button(
                            "⬇️ Download",
                            data,
                            file_name=f["name"],
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            key=f"dl_{f['full_path']}"
                        )
        else:
            st.info("No files matched your search.")
    else:
        st.info("No files available. Upload first.")

    st.markdown("---")
    st.subheader("🛡️ Admin • Delete All Files")
    with st.expander("Show/Hide"):
        pwd = st.text_input("Enter admin password:", type="password")
        if st.button("❌ Delete All Files"):
            if pwd and pwd == ARCHIVE_DELETE_PASSWORD:
                clear_supabase_bucket()
            elif pwd:
                st.error("Incorrect password.")

elif st.session_state.page == "Data Analyzing Dashboard":
    st.subheader("📊 Data Analyzing Dashboard")

    all_files = get_all_supabase_files()
    if not all_files:
        st.warning("No files available for analysis.")
    else:
        min_d = min(f['file_date'] for f in all_files)
        max_d = max(f['file_date'] for f in all_files)

        c1, c2 = st.columns(2)
        with c1:
            sdate = st.date_input("Start Date:", value=st.session_state.get('dashboard_start_date', min_d), min_value=min_d, max_value=max_d, key="dash_start")
        with c2:
            edate = st.date_input("End Date:", value=st.session_state.get('dashboard_end_date', max_d), min_value=min_d, max_value=max_d, key="dash_end")

        if edate < sdate:
            st.error("End Date cannot be before Start Date."); edate = sdate; st.session_state.dashboard_end_date = edate

        st.session_state.dashboard_start_date = sdate
        st.session_state.dashboard_end_date = edate

        files_in_range = [f for f in all_files if sdate <= f['file_date'] <= edate]
        num_days = (edate - sdate).days + 1
        st.info(f"🗓️ Selected range: **{num_days}** day(s)")

        if not files_in_range:
            st.info("No files in this range.")
        else:
            st.markdown("##### Files to analyze:")
            st.markdown("<div class='note'>" + "<br>".join([f"- {f['name']} • {f['file_date'].strftime('%d %b %Y')}" for f in files_in_range]) + "</div>", unsafe_allow_html=True)

            all_prod, all_err = [], []
            bar = st.progress(0, text="Processing files...")
            for i, f in enumerate(files_in_range):
                raw = download_from_supabase(f["full_path"])
                if raw:
                    try:
                        xls = pd.ExcelFile(BytesIO(raw))
                        for sheet in xls.sheet_names:
                            df_raw = pd.read_excel(BytesIO(raw), sheet_name=sheet, header=None)
                            prod = read_production_data(df_raw, f["full_path"].split("/")[-1], sheet, f["file_date"])
                            err = read_error_data(df_raw, sheet, f["full_path"].split("/")[-1], f["file_date"])
                            if not prod.empty: all_prod.append(prod)
                            if not err.empty: all_err.append(err)
                    except Exception as e:
                        st.error(f"❌ Error processing '{f['full_path']}': {e}")
                bar.progress((i+1)/len(files_in_range), text=f"Processing {f['full_path']}")
            bar.empty()

            final_prod = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()
            final_err  = pd.concat(all_err, ignore_index=True) if all_err else pd.DataFrame()

            unique_machines = ['All Machines']
            if not final_prod.empty and "ProductionTypeForTon" in final_prod.columns:
                ms = [m for m in final_prod["ProductionTypeForTon"].unique().tolist() if m is not None]
                if "Unknown Machine" in ms: ms.remove("Unknown Machine")
                ms.append("Unknown Machine")
                unique_machines.extend(sorted(ms))

            machine = st.selectbox("Select Machine:", unique_machines)

            fprod_m = final_prod.copy()
            ferr_m  = final_err.copy()
            if machine != "All Machines":
                fprod_m = final_prod[final_prod["ProductionTypeForTon"] == machine].copy()
                if not final_err.empty and "MachineType" in final_err.columns:
                    ferr_m = final_err[final_err["MachineType"] == machine].copy()
                else:
                    ferr_m = pd.DataFrame()

            unique_products = ['All Products']
            if not fprod_m.empty and "Product" in fprod_m.columns:
                ps = [p for p in fprod_m["Product"].unique().tolist() if p and str(p).strip() != ""]
                unique_products.extend(sorted(ps))

            product = st.selectbox("Select Product:", unique_products)
            fprod_mp = fprod_m.copy()
            if product != "All Products":
                fprod_mp = fprod_m[fprod_m["Product"] == product].copy()

            chart_prod_df = fprod_mp.copy()

            daily_m = calculate_metrics(fprod_m, ferr_m, group_cols=['Date', 'ProductionTypeForTon'])
            daily_p = calculate_metrics(chart_prod_df, ferr_m, group_cols=['Date', 'ProductionTypeForTon', 'Product'])

            st.markdown("---")
            st.subheader(f"✨ Metrics • Machine: {machine} • Product: {product}")

            total_metrics_df = calculate_metrics(final_prod, final_err, group_cols=['Date'])

            if product != "All Products":
                current = daily_p
            elif machine != "All Machines":
                current = daily_m
            else:
                current = total_metrics_df

            if current.empty and total_metrics_df.empty:
                st.warning("No data to calculate metrics.")
            else:
                tgt = current['Total_Target_Hour'].sum() if not current.empty else 0
                qty = current['Total_PackQty'].sum() if not current.empty else 0

                lstop = current['LegalStoppage_H'].sum() if 'LegalStoppage_H' in current else 0
                idle  = current['IdleTime_H'].sum() if 'IdleTime_H' in current else 0
                down  = current['Downtime_H'].sum() if 'Downtime_H' in current else 0
                loss  = current['Losses_H'].sum() if 'Losses_H' in current else 0
                oeadj = current['OE_Adjust_H'].sum() if 'OE_Adjust_H' in current else 0

                gross = (num_days * 24.0) - lstop - idle
                net   = gross - down
                denom = net + oeadj

                line_eff = (tgt / net) * 100 if net > 0 else 0
                oe_val   = (tgt / denom) * 100 if denom > 0 else 0

                k1, k2, k3, k4, k5 = st.columns(5)
                k1.metric("Total Production (pcs)", f"{int(qty):,}")
                k2.metric("Target Hour (h)", f"{tgt:,.2f}")
                k3.metric("Line Efficiency", f"{line_eff:.1f}%")
                k4.metric("Overall OE", f"{oe_val:.1f}%")
                k5.metric("Downtime (h)", f"{down:,.2f}")

                st.markdown("---")
                st.subheader("📈 Daily Performance Trend")

                def add_date_str(df):
                    if df is None or df.empty: return df
                    df = df.sort_values(by="Date")
                    df["Date_Str"] = df["Date"].apply(lambda x: x.strftime("%Y-%m-%d"))
                    return df

                if product != "All Products":
                    chart_m = add_date_str(daily_p); x_name = "Product"
                elif machine != "All Machines":
                    chart_m = add_date_str(daily_m); x_name = "ProductionTypeForTon"
                else:
                    chart_m = add_date_str(total_metrics_df); x_name = None

                if chart_m is not None and not chart_m.empty:
                    fig_trend = px.line(
                        chart_m,
                        x="Date_Str",
                        y=["Line_Efficiency(%)", "OE(%)"],
                        title="Daily Line Efficiency & OE Trend",
                        markers=True
                    )
                    fig_trend.update_layout(yaxis_range=[0, 100])
                    st.plotly_chart(fig_trend, use_container_width=True)

                    # Target vs Net Production Hours
                    bars = ["Total_Target_Hour", "NetProduction_H"]
                    fig_hours = px.bar(
                        chart_m,
                        x="Date_Str",
                        y=bars,
                        barmode="group",
                        title="Daily Target vs Net Production Hours"
                    )
                    st.plotly_chart(fig_hours, use_container_width=True)

                    # Loss distribution donut (aggregated)
                    loss_df = pd.DataFrame({
                        "Category": ["Downtime (21-31)", "Losses (1-20)", "Idle (32)", "Legal (33)", "OE Adjust (24,25)"],
                        "Hours": [down, loss, idle, lstop, oeadj]
                    })
                    loss_df = loss_df[loss_df["Hours"] > 0]
                    st.subheader("🧩 Loss Distribution (Total)")
                    if not loss_df.empty:
                        fig_loss = px.pie(loss_df, names="Category", values="Hours", hole=0.35, title="Total Loss Distribution (Hours)")
                        st.plotly_chart(fig_loss, use_container_width=True)
                    else:
                        st.info("No time losses recorded for this selection.")
                else:
                    st.info("No metrics generated for charting.")

                st.markdown("---")
                st.subheader("🗂️ Raw Tables")
                tab1, tab2, tab3, tab4 = st.tabs([
                    "Production (Filtered)",
                    "Errors (Filtered)",
                    "Metrics by Machine (Daily)",
                    "Metrics by Product (Daily)"
                ])
                with tab1:
                    if not chart_prod_df.empty:
                        st.dataframe(chart_prod_df.sort_values(by="Date", ascending=False), use_container_width=True)
                    else:
                        st.info("No production data for current filter.")
                with tab2:
                    if not ferr_m.empty:
                        disp = ferr_m.groupby(['Date','MachineType','Error'])['Duration'].sum().reset_index()
                        disp = disp.sort_values(by=['Date','Duration'], ascending=[False, False])
                        disp['Duration (Min)'] = disp['Duration'].map(lambda x: f"{x:,.0f}")
                        disp['Duration (Hr)']  = (disp['Duration']/60).map(lambda x: f"{x:,.2f}")
                        st.dataframe(disp.drop(columns=['Duration']), use_container_width=True)
                    else:
                        st.info("No error data for current filter.")
                with tab3:
                    if not daily_m.empty:
                        st.dataframe(daily_m.sort_values(by="Date", ascending=False), use_container_width=True)
                    else:
                        st.info("No machine metrics computed.")
                with tab4:
                    if not daily_p.empty:
                        st.dataframe(daily_p.sort_values(by="Date", ascending=False), use_container_width=True)
                    else:
                        st.info("No product metrics computed.")

elif st.session_state.page == "Trend Analysis":
    st.subheader("📈 Trend Analysis")

    all_files = get_all_supabase_files()
    if not all_files:
        st.warning("No files uploaded.")
    else:
        min_d = min(f['file_date'] for f in all_files)
        max_d = max(f['file_date'] for f in all_files)
        c1, c2 = st.columns(2)
        with c1:
            sdate = st.date_input("Start Date:", value=st.session_state.get('trend_start_date', min_d), min_value=min_d, max_value=max_d, key="trend_start")
        with c2:
            edate = st.date_input("End Date:", value=st.session_state.get('trend_end_date', max_d), min_value=min_d, max_value=max_d, key="trend_end")

        if edate < sdate:
            st.error("End Date cannot be before Start Date."); edate = sdate; st.session_state.trend_end_date = edate
        st.session_state.trend_start_date = sdate
        st.session_state.trend_end_date = edate

        in_range = [f for f in all_files if sdate <= f['file_date'] <= edate]
        if not in_range:
            st.info("No files in this range."); st.stop()

        all_prod, all_err = [], []
        with st.spinner("Preparing trend data..."):
            for f in in_range:
                raw = download_from_supabase(f["full_path"])
                if raw:
                    try:
                        xls = pd.ExcelFile(BytesIO(raw))
                        for sheet in xls.sheet_names:
                            df = pd.read_excel(BytesIO(raw), sheet_name=sheet, header=None)
                            p = read_production_data(df, f["full_path"].split("/")[-1], sheet, f["file_date"])
                            e = read_error_data(df, sheet, f["full_path"].split("/")[-1], f["file_date"])
                            if not p.empty: all_prod.append(p)
                            if not e.empty: all_err.append(e)
                    except Exception as e:
                        st.error(f"❌ Trend parse error for '{f['full_path']}': {e}")
        prod_tr = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()
        err_tr  = pd.concat(all_err, ignore_index=True) if all_err else pd.DataFrame()

        if prod_tr.empty:
            st.warning("No production data in the selected period."); st.stop()

        group_choice = st.selectbox("Group trend by:", ["Machine Type", "Product"])
        if group_choice == "Machine Type":
            metrics_tr = calculate_metrics(prod_tr, err_tr, group_cols=['Date', 'ProductionTypeForTon']).rename(columns={'ProductionTypeForTon':'Grouping_Key'})
        else:
            metrics_tr = calculate_metrics(prod_tr, err_tr, group_cols=['Date', 'ProductionTypeForTon','Product']).rename(columns={'Product':'Grouping_Key'})
            metrics_tr = metrics_tr[metrics_tr['Grouping_Key'].astype(str).str.strip() != ""]

        uniq = sorted(metrics_tr['Grouping_Key'].dropna().astype(str).unique().tolist())
        selected = st.multiselect(
            f"Select {group_choice}s to compare:",
            options=uniq,
            default=uniq[:3] if len(uniq) > 3 else uniq
        )
        if not selected:
            st.warning("Select at least one item."); st.stop()

        mdf = metrics_tr[metrics_tr['Grouping_Key'].isin(selected)].copy()
        if mdf.empty:
            st.warning("No data for selected identifiers."); st.stop()

        mdf['Date_Str'] = mdf['Date'].apply(lambda x: x.strftime("%Y-%m-%d"))

        st.subheader(f"OE (%) trend by {group_choice}")
        fig_oe = px.line(mdf, x="Date_Str", y="OE(%)", color="Grouping_Key", markers=True, title=f"Daily OE by {group_choice}")
        fig_oe.update_layout(yaxis_range=[0,100])
        st.plotly_chart(fig_oe, use_container_width=True)

        st.subheader(f"Total Production (pcs) by {group_choice}")
        fig_qty = px.bar(mdf, x="Date_Str", y="Total_PackQty", color="Grouping_Key", barmode="group", title=f"Daily Production by {group_choice}")
        st.plotly_chart(fig_qty, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Comparison Data Table")
        st.dataframe(mdf.sort_values(by=["Date","Grouping_Key"], ascending=[False, True]), use_container_width=True)

elif st.session_state.page == "Contact Me":
    st.subheader("🛰️ Connect with Mohammad Asadollahzadeh")
    st.markdown("""
<div style="display:flex;gap:24px;align-items:center;">
  <img src="https://avatars.githubusercontent.com/u/9919?s=200&v=4" width="72" style="border-radius:14px;box-shadow:0 0 12px rgba(97,218,251,0.25);" />
  <div>
    <h3 style="margin:0">Let's build disciplined, data-driven systems</h3>
    <p style="margin:4px 0 0;color:#96a0b5;">AI-assisted analytics • Industrial dashboards • Python & Streamlit</p>
  </div>
</div>
<br/>
<div class='note'>
  <b>Email:</b> m.asdz@yahoo.com<br/>
  <b>LinkedIn:</b> Mohammad Asadollahzadeh
</div>
""", unsafe_allow_html=True)
    st.markdown("---")
    st.caption("Built with ❤️ • Dark Pro Edition • Streamlit + Supabase + Plotly")
