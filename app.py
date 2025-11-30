#############################################
#        app.py — PART 1 / 5 (START)        #
#############################################

import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np
import requests
from io import BytesIO
import base64
import re
from datetime import datetime, timedelta, time as datetime_time

# -------------------------------------------------------
#                 SUPABASE CONFIG (HTTP)
# -------------------------------------------------------
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDUxMjg5OTEsImV4cCI6MjA2MDcwNDk5MX0.hM-WA6setQ_PZ13rOBEoy2a3rn7wQ6wLFMV9SyBWfHE"


# ----------------- SUPABASE: LIST FILES -----------------
def supabase_list_files():
    url = f"{SUPABASE_URL}/storage/v1/object/list/uploads"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json"
    }
    body = {"prefix": ""}
    response = requests.post(url, json=body, headers=headers)
    return response.json()


# ----------------- SUPABASE: DOWNLOAD FILE -----------------
def supabase_download_file(filename):
    url = f"{SUPABASE_URL}/storage/v1/object/uploads/{filename}"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}"}
    r = requests.get(url, headers=headers)
    return r.content if r.status_code == 200 else None


# ----------------- SUPABASE: UPLOAD FILE -----------------
def supabase_upload_file(file_obj, filename):
    url = f"{SUPABASE_URL}/storage/v1/object/uploads/{filename}"
    headers = {
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/octet-stream"
    }
    r = requests.put(url, data=file_obj, headers=headers)
    return r.status_code == 200


# ----------------- SUPABASE: DELETE ALL -----------------
def supabase_delete_all():
    files = supabase_list_files()
    names = [f["name"] for f in files if "name" in f]

    url = f"{SUPABASE_URL}/storage/v1/object/uploads"
    headers = {"Authorization": f"Bearer {SUPABASE_KEY}",
               "Content-Type": "application/json"}
    body = {"prefixes": names}

    requests.delete(url, json=body, headers=headers)


# ===================================================================
#                         BEAUTIFUL UI THEME
# ===================================================================
st.set_page_config(
    page_title="Production Dashboard",
    layout="wide",
    initial_sidebar_state="expanded"
)

CSS = """
<style>
body {
    background-color: #f5f7fa;
}
.sidebar .sidebar-content {
    background-color: #1d3557 !important;
}
h1, h2, h3, h4 {
    color: #1d3557;
}
.stButton>button {
    background-color:#1d3557;
    color:white;
    border-radius:8px;
    padding:8px 20px;
}
.stButton>button:hover {
    background-color:#457b9d;
}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# ===================================================================
#                        UTILITY FUNCTIONS
# ===================================================================

def parse_filename_date_to_datetime(filename):
    try:
        date_str_match = re.search(r'(\d{8})', filename)
        if date_str_match:
            ds = date_str_match.group(1)
            day = int(ds[0:2])
            month = int(ds[2:4])
            year = int(ds[4:8])
            return datetime(year, month, day).date()
    except:
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
                return (h % 24) + m/60
        except:
            pass
        return float(val)
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            try:
                t = datetime.strptime(s, "%H:%M:%S")
                return t.hour + t.minute/60
            except:
                try:
                    t = datetime.strptime(s, "%H:%M")
                    return t.hour + t.minute/60
                except:
                    pass
        if s.isdigit():
            try:
                v = int(s)
                h = v//100
                m = v%100
                if 0 <= m < 60:
                    return (h % 24) + m/60
            except:
                pass
        try:
            return float(s)
        except:
            return 0
    return 0


def convert_duration_to_minutes(val):
    if pd.isna(val):
        return 0
    if isinstance(val, timedelta):
        return val.total_seconds()/60
    if isinstance(val, datetime):
        return val.hour*60 + val.minute
    if isinstance(val, datetime_time):
        return val.hour*60 + val.minute
    if isinstance(val, (int, float)):
        if 0 <= val < 1:
            return val * 24 * 60
        if val < 2400:
            try:
                h = int(val) // 100
                m = int(val) % 100
                if 0 <= m < 60:
                    return h*60 + m
            except:
                pass
        return val*60
    if isinstance(val, str):
        s = val.strip()
        if ":" in s:
            try:
                t = datetime.strptime(s, "%H:%M:%S")
                return t.hour*60 + t.minute
            except:
                try:
                    t = datetime.strptime(s, "%H:%M")
                    return t.hour*60 + t.minute
                except:
                    pass
        if s.isdigit():
            try:
                v = int(s)
                h = v//100
                m = v%100
                if 0 <= m < 60:
                    return h*60 + m
            except:
                pass
        try:
            return float(s)*60
        except:
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

#############################################
#        app.py — PART 1 / 5 (END)          #
#############################################

#############################################
#        app.py — PART 2 / 5 (START)        #
#############################################

# -------------------------------------------------------
#                CACHING: LIST SUPABASE FILES
# -------------------------------------------------------
@st.cache_data(ttl=600)
def get_all_supabase_files():
    try:
        items = supabase_list_files()
        cleaned = []
        for it in items:
            if "name" in it and it["name"].lower().endswith(".xlsx"):
                cleaned.append({
                    "name": it["name"],
                    "full_path": it["name"],
                    "file_date": parse_filename_date_to_datetime(it["name"])
                })
        return cleaned
    except Exception as e:
        st.error(f"Error listing files: {e}")
        return []


# -------------------------------------------------------
#                     UPLOAD PAGE
# -------------------------------------------------------
def page_upload():
    st.header("📤 Upload Production Files")
    st.write("Upload your daily production Excel files (.xlsx).")

    uploaded_files = st.file_uploader(
        "Choose one or multiple Excel files",
        type=["xlsx"],
        accept_multiple_files=True
    )

    if st.button("Upload Files"):
        if not uploaded_files:
            st.warning("Please select file(s) first.")
            return

        for uf in uploaded_files:
            uploaded = supabase_upload_file(uf.getvalue(), uf.name)
            if uploaded:
                st.success(f"Uploaded: {uf.name}")
            else:
                st.error(f"Failed: {uf.name}")

        get_all_supabase_files.clear()
        st.rerun()


# -------------------------------------------------------
#                  ARCHIVE PAGE
# -------------------------------------------------------
def page_archive():
    st.header("📁 Data Archive")
    st.write("Browse and download stored Excel files.")

    query = st.text_input("Search filename:")

    files = get_all_supabase_files()
    if query:
        files = [f for f in files if query.lower() in f["name"].lower()]

    if not files:
        st.info("No files found.")
        return

    for f in files:
        col1, col2 = st.columns([0.7, 0.3])
        with col1:
            st.write(f"📄 **{f['name']}** — {f['file_date']}")
        with col2:
            data = supabase_download_file(f["name"])
            if data:
                st.download_button(
                    "Download",
                    data,
                    file_name=f["name"],
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )

    st.markdown("---")
    st.subheader("⚠ Admin: Delete All Files")

    pwd = st.text_input("Enter password:", type="password")
    if st.button("Delete ALL"):
        if pwd == "beautifulmind":
            supabase_delete_all()
            get_all_supabase_files.clear()
            st.success("All files deleted.")
            st.rerun()
        else:
            st.error("Wrong password.")


#############################################
#        app.py — PART 2 / 5 (END)          #
#############################################


#############################################
#        app.py — PART 3 / 5 (START)        #
#############################################

# ===================================================================
#                  READ PRODUCTION (CORE FUNCTION)
# ===================================================================
def read_production_data(df_raw, filename, sheet_name, file_date):
    try:
        # Headers in row 2–3 (index 1–2), columns D–P (index 3–15)
        row2 = df_raw.iloc[1, 3:16].fillna('').astype(str).tolist()
        row3 = df_raw.iloc[2, 3:16].fillna('').astype(str).tolist()

        headers = []
        for r2, r3 in zip(row2, row3):
            if r3.strip() and r3.strip() != "nan":
                headers.append(r3.strip())
            elif r2.strip() and r2.strip() != "nan":
                headers.append(r2.strip())
            else:
                headers.append("")

        headers = [h if h else f"Col_{i}" for i, h in enumerate(headers)]

    except Exception as e:
        st.error(f"❌ Header error in {filename} / {sheet_name}: {e}")
        return pd.DataFrame()

    # Data rows: 4–9 (index 3–8)
    data = df_raw.iloc[3:9, 3:16].copy()

    if len(headers) != data.shape[1]:
        st.error(f"❌ Column mismatch in {filename}/{sheet_name}")
        return pd.DataFrame()

    data.columns = headers

    # Standard rename
    rename_map = {
        "start": "Start",
        "finish": "End",
        "production title": "Product",
        "cap": "Capacity",
        "manpower": "Manpower",
        "quanity": "PackQty",
        "waste": "Waste",
    }
    rename_map = {k: v for k, v in rename_map.items() if k in data.columns}
    data = data.rename(columns=rename_map)

    # Add Date
    data["Date"] = file_date

    # Machine type
    mtype = determine_machine_type(sheet_name)
    if mtype == "Unknown":
        mtype = determine_machine_type(filename)
    data["ProductionTypeForTon"] = mtype

    # Ensure required columns
    required = ["Start", "End", "Product", "Capacity", "Manpower",
                "PackQty", "Waste", "ProductionTypeForTon"]
    for col in required:
        if col not in data.columns:
            data[col] = 0

    # Clean product text
    data["Product"] = data["Product"].astype(str).str.strip().str.title()
    data = data[data["Product"] != ""]

    # Convert start/end times
    data["StartTime"] = data["Start"].apply(convert_time)
    data["EndTime"] = data["End"].apply(convert_time)

    # Midnight fix
    data["EndTimeAdj"] = data.apply(
        lambda r: r["EndTime"] + 24 if r["EndTime"] < r["StartTime"] else r["EndTime"],
        axis=1
    )

    data["Duration"] = data["EndTimeAdj"] - data["StartTime"]
    data = data[data["Duration"] > 0]

    # Convert numerics
    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    data["Capacity"] = pd.to_numeric(data["Capacity"], errors="coerce").fillna(0)
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)

    # Ton calculation
    def calc_ton(row):
        t = str(row["ProductionTypeForTon"]).lower()
        qty = row["PackQty"]

        if "gasti" in t: grams = 90
        elif "200" in t: grams = 200
        elif "125" in t: grams = 125
        elif "1000" in t: grams = 1000
        else: grams = 1000

        return (qty * grams) / 1_000_000

    data["Ton"] = data.apply(calc_ton, axis=1)

    data["PotentialProduction"] = data["Capacity"] * data["Duration"]
    data["Efficiency(%)"] = np.where(
        data["PotentialProduction"] > 0,
        (data["PackQty"] / data["PotentialProduction"]) * 100,
        0
    )

    final_cols = ["Date", "Product", "Capacity", "Manpower",
                  "Duration", "PackQty", "Waste", "Ton",
                  "PotentialProduction", "Efficiency(%)", "ProductionTypeForTon"]

    return data[final_cols]


# ===================================================================
#                    READ ERRORS (CORE FUNCTION)
# ===================================================================
def read_error_data(df_raw, sheet_name, filename, file_date):
    try:
        raw = df_raw.iloc[11:1000, 6:8].copy()
        raw.columns = ["Error", "Duration"]
    except:
        return pd.DataFrame()

    raw["Error"] = raw["Error"].fillna('').astype(str).str.strip()
    raw = raw[raw["Error"] != ""]

    raw["Duration"] = raw["Duration"].apply(convert_duration_to_minutes)

    agg = raw.groupby("Error")["Duration"].sum().reset_index()
    agg["Date"] = file_date
    agg["MachineType"] = determine_machine_type(sheet_name)

    return agg


# ===================================================================
#      FULL FILE PROCESSOR (LOOP THROUGH EXCEL SHEETS)
# ===================================================================
def process_files_for_dashboard(files):
    all_prod = []
    all_err = []

    bar = st.progress(0, "Processing...")

    for i, f in enumerate(files):
        fname = f["name"]
        fdate = f["file_date"]

        file_bytes = supabase_download_file(fname)
        if not file_bytes:
            st.error(f"❌ Could not download {fname}")
            continue

        try:
            xls = pd.ExcelFile(BytesIO(file_bytes))
        except:
            st.error(f"❌ Invalid Excel file: {fname}")
            continue

        for sheet in xls.sheet_names:
            df_raw = pd.read_excel(BytesIO(file_bytes), sheet, header=None)

            prod_df = read_production_data(df_raw, fname, sheet, fdate)
            err_df = read_error_data(df_raw, sheet, fname, fdate)

            if not prod_df.empty:
                all_prod.append(prod_df)
            if not err_df.empty:
                all_err.append(err_df)

        bar.progress((i+1)/len(files))

    bar.empty()

    final_prod = pd.concat(all_prod, ignore_index=True) if all_prod else pd.DataFrame()
    final_err = pd.concat(all_err, ignore_index=True) if all_err else pd.DataFrame()

    return final_prod, final_err

#############################################
#        app.py — PART 3 / 5 (END)          #
#############################################

#############################################
#        app.py — PART 4 / 5 (START)        #
#############################################

# ===================================================================
#                     DATA ANALYZING DASHBOARD
# ===================================================================
def page_dashboard():
    st.header("📊 Data Analyzing Dashboard")

    files = get_all_supabase_files()
    if not files:
        st.warning("No files available.")
        return

    # Date range
    min_d = min(f["file_date"] for f in files)
    max_d = max(f["file_date"] for f in files)

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Start Date", min_d)
    with c2:
        end_date = st.date_input("End Date", max_d)

    if end_date < start_date:
        st.error("End date cannot be earlier.")
        return

    selected = [f for f in files if start_date <= f["file_date"] <= end_date]

    st.info(f"Number of days selected: **{(end_date - start_date).days + 1}**")
    st.write("### Files Included:")
    for f in selected:
        st.write(f"- {f['name']} — {f['file_date']}")

    prod_df, err_df = process_files_for_dashboard(selected)

    if prod_df.empty:
        st.warning("No production data found.")
        return

    # Machine Filter
    machines = ["All Machines"] + sorted(prod_df["ProductionTypeForTon"].unique())
    selected_m = st.selectbox("Select Machine", machines)

    if selected_m != "All Machines":
        prod_df = prod_df[prod_df["ProductionTypeForTon"] == selected_m]
        err_df = err_df[err_df["MachineType"] == selected_m]

    st.markdown("## 📦 Combined Production Data")
    st.dataframe(
        prod_df.style.format({"Efficiency(%)": "{:.2f} %"}),
        use_container_width=True
    )

    # ---------------- TREEMAP: TON BY PRODUCT ----------------
    st.subheader("🟦 Total Production (Tons) by Product")
    ton_df = prod_df.groupby("Product")["Ton"].sum().reset_index()
    ton_df = ton_df.sort_values("Ton", ascending=False)

    fig1 = px.treemap(
        ton_df,
        path=[px.Constant("All Products"), "Product"],
        values="Ton",
        color="Product",
        title="Total Tons by Product"
    )
    st.plotly_chart(fig1, use_container_width=True)

    # ---------------- WASTE PERCENTAGE BAR ----------------
    st.subheader("🟧 Waste Percentage by Product")
    waste_df = prod_df.groupby("Product").agg(
        waste=("Waste", "sum"),
        qty=("PackQty", "sum")
    ).reset_index()
    waste_df["Waste(%)"] = np.where(
        waste_df["qty"] > 0, (waste_df["waste"] / waste_df["qty"]) * 100, 0
    )
    waste_df = waste_df.sort_values("Waste(%)", ascending=False)

    fig2 = px.bar(
        waste_df,
        x="Product",
        y="Waste(%)",
        text_auto=".2f",
        color="Product",
        title="Waste Percentage (%)"
    )
    st.plotly_chart(fig2, use_container_width=True)

    # ---------------- EFFICIENCY BAR ----------------
    st.subheader("🟩 Efficiency by Product")
    eff_df = prod_df.groupby("Product").agg(
        qty=("PackQty", "sum"),
        pot=("PotentialProduction", "sum")
    ).reset_index()
    eff_df["Efficiency(%)"] = np.where(
        eff_df["pot"] > 0,
        (eff_df["qty"] / eff_df["pot"]) * 100,
        0
    )
    eff_df = eff_df.sort_values("Efficiency(%)", ascending=False)

    fig3 = px.bar(
        eff_df,
        x="Product",
        y="Efficiency(%)",
        text_auto=".2f",
        color="Efficiency(%)",
        color_continuous_scale=px.colors.sequential.Greens,
        title="Average Efficiency (%)"
    )
    st.plotly_chart(fig3, use_container_width=True)

    # ---------------- ERROR / DOWNTIME ----------------
    st.subheader("🔻 Downtime / Error Summary")
    if err_df.empty:
        st.info("No error data.")
    else:
        esum = err_df.groupby("Error")["Duration"].sum().reset_index()
        esum = esum.sort_values("Duration", ascending=False)

        fig4 = px.bar(
            esum,
            x="Error",
            y="Duration",
            text_auto=True,
            color="Error",
            color_discrete_sequence=px.colors.qualitative.Set2,
            title="Downtime by Error Type (Minutes)"
        )
        fig4.update_layout(xaxis_tickangle=-45)
        st.plotly_chart(fig4, use_container_width=True)

        csv = esum.to_csv(index=False).encode()
        st.download_button(
            "Download Error Summary",
            csv,
            file_name="error_summary.csv"
        )


# ===================================================================
#                          TREND ANALYSIS PAGE
# ===================================================================
def page_trends():
    st.header("📈 Trend Analysis")

    files = get_all_supabase_files()
    if not files:
        st.warning("No data.")
        return

    min_d = min(f["file_date"] for f in files)
    max_d = max(f["file_date"] for f in files)

    c1, c2 = st.columns(2)
    with c1:
        start_date = st.date_input("Start Date", min_d)
    with c2:
        end_date = st.date_input("End Date", max_d)

    if end_date < start_date:
        st.error("End date invalid.")
        return

    selected = [f for f in files if start_date <= f["file_date"] <= end_date]

    prod_df, err_df = process_files_for_dashboard(selected)

    if prod_df.empty:
        st.warning("No production data.")
        return

    # Granularity
    gopts = {"Daily": "D", "Weekly": "W", "Monthly": "M", "Yearly": "Y"}
    gsel = st.radio("Group by:", list(gopts.keys()), horizontal=True)

    prod_df["Date"] = pd.to_datetime(prod_df["Date"])
    err_df["Date"] = pd.to_datetime(err_df["Date"])

    freq = gopts[gsel]

    # Machine filter
    machines = ["All Machines"] + sorted(prod_df["ProductionTypeForTon"].unique())
    selected_m = st.selectbox("Select Machine", machines)

    if selected_m != "All Machines":
        prod_df = prod_df[prod_df["ProductionTypeForTon"] == selected_m]
        err_df = err_df[err_df["MachineType"] == selected_m]

    st.markdown("## 📦 Production Trends")

    prod_resampled = prod_df.set_index("Date")

    # Total ton trend
    ton_trend = prod_resampled.resample(freq)["Ton"].sum().reset_index()
    ton_trend = ton_trend[ton_trend["Ton"] > 0]

    if not ton_trend.empty:
        fig = px.line(
            ton_trend,
            x="Date", y="Ton",
            markers=True,
            title=f"{gsel} Total Production (Tons)"
        )
        st.plotly_chart(fig, use_container_width=True)

    # Efficiency trend
    eff_tr = prod_resampled.groupby(pd.Grouper(freq=freq)).agg(
        qty=("PackQty", "sum"),
        pot=("PotentialProduction", "sum")
    ).reset_index()
    eff_tr["Efficiency(%)"] = np.where(
        eff_tr["pot"] > 0,
        (eff_tr["qty"] / eff_tr["pot"]) * 100,
        0
    )
    eff_tr = eff_tr[eff_tr["qty"] > 0]

    if not eff_tr.empty:
        fig = px.line(
            eff_tr,
            x="Date", y="Efficiency(%)",
            markers=True,
            title=f"{gsel} Average Efficiency (%)"
        )
        st.plotly_chart(fig, use_container_width=True)

    # Waste trend
    waste_tr = prod_resampled.groupby(pd.Grouper(freq=freq)).agg(
        w=("Waste", "sum"),
        qty=("PackQty", "sum")
    ).reset_index()
    waste_tr["Waste(%)"] = np.where(
        waste_tr["qty"] > 0,
        (waste_tr["w"]/waste_tr["qty"])*100,
        0
    )
    waste_tr = waste_tr[waste_tr["qty"] > 0]

    if not waste_tr.empty:
        fig = px.line(
            waste_tr,
            x="Date", y="Waste(%)",
            markers=True,
            title=f"{gsel} Average Waste (%)"
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("## 🔻 Error Trends")
    if err_df.empty:
        st.info("No error data.")
        return

    err_resampled = err_df.set_index("Date")
    dt_total = err_resampled.resample(freq)["Duration"].sum().reset_index()
    dt_total = dt_total[dt_total["Duration"] > 0]

    if not dt_total.empty:
        fig = px.line(
            dt_total,
            x="Date", y="Duration",
            markers=True,
            title=f"{gsel} Total Downtime (Minutes)"
        )
        st.plotly_chart(fig, use_container_width=True)

#############################################
#        app.py — PART 4 / 5 (END)          #
#############################################


#############################################
#        app.py — PART 5 / 5 (START)        #
#############################################

# ===================================================================
#                             CONTACT PAGE
# ===================================================================
def page_contact():
    st.header("📞 Contact Me")
    st.markdown("""
    **Mohammad Asadollahzadeh**

    📧 Email: **m.asdz@yahoo.com**

    🌐 LinkedIn: *Available upon request*

    ---

    In today's industrial world, data-driven decisions are essential.
    This dashboard helps streamline production analysis, reduce downtime,
    and improve efficiency.

    If you need:
    - Custom dashboards  
    - AI integration  
    - Automation systems  
    - Production optimization  

    Feel free to contact me.  
    """)


# ===================================================================
#                           MAIN NAVIGATION
# ===================================================================
st.sidebar.title("📌 Navigation")

pages = {
    "Upload Data": page_upload,
    "Data Archive": page_archive,
    "Data Analyzing Dashboard": page_dashboard,
    "Trend Analysis": page_trends,
    "Contact Me": page_contact,
}

choice = st.sidebar.radio("Go to:", list(pages.keys()))

pages[choice]()

#############################################
#        app.py — PART 5 / 5 (END)          #
#############################################


