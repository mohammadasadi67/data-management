import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
from supabase import create_client, Client
import base64
from datetime import datetime, timedelta
import re
import numpy as np
import logging
import time

# تنظیمات اصلی برنامه
st.set_page_config(layout="wide", page_title="OEE & Production Dashboard", initial_sidebar_state="expanded")
st.title("📊 داشبورد تحلیل تولید و OEE")

# ------------------------------------------------------------------------------
# --- ۱. تنظیمات اتصال و متغیرهای سراسری ---
# ------------------------------------------------------------------------------

# --- Supabase Configuration (تایید شده) ---
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# --- DB Table Names ---
PROD_TABLE = "production_data"
ERROR_TABLE = "error_data"

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"

# اتصال به Supabase (Cache Resource)
@st.cache_resource
def get_supabase_client():
    """ایجاد و کش کردن اتصال به Supabase."""
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return supabase
    except Exception as e:
        st.error(f"خطا در اتصال به پایگاه داده Supabase: {e}")
        st.stop() 

supabase = get_supabase_client()

# ------------------------------------------------------------------------------
# --- ۲. توابع کمکی اصلی ---
# ------------------------------------------------------------------------------

# 🔑 واژه‌نامه برای نقشه‌برداری ستون‌های فارسی اکسل به نام‌های استاندارد انگلیسی (ضروری برای OEE)
COLUMN_MAP = {
    'مقدار کل': 'PackQty', 
    'بسته': 'PackQty',
    'ضایعات': 'Waste',
    'تناژ': 'Ton',
    'زمان فعالیت': 'Duration',
    'ظرفیت': 'Capacity',
    'تعداد نفرات': 'Manpower',
    'مدت زمان': 'Duration', 
}

def parse_filename_date_to_datetime(filename):
    """استخراج ddmmyyyy از نام فایل و تبدیل به آبجکت date."""
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d%m%Y').date()
        except ValueError:
            return None
    return None

def standardize_dataframe_for_oee(df, type='prod'):
    """استانداردسازی نام ستون‌ها و تبدیل به انواع داده‌ای مورد نیاز."""
    df_standard = df.rename(columns=lambda x: COLUMN_MAP.get(x.strip(), x.strip())).copy()
    
    required_cols_prod = ['PackQty', 'Waste', 'Duration', 'Capacity', 'Ton']
    required_cols_error = ['Duration']
    
    if type == 'prod':
        for col in required_cols_prod:
            if col in df_standard.columns:
                df_standard[col] = pd.to_numeric(df_standard[col], errors='coerce').fillna(0)
    elif type == 'error':
        for col in required_cols_error:
            if col in df_standard.columns:
                df_standard[col] = pd.to_numeric(df_standard[col], errors='coerce').fillna(0)
                
    return df_standard

def read_production_data(df_raw_sheet, uploaded_file_name, sheet_name_for_debug, file_date_obj):
    """خوانش و پردازش داده‌های Production از محدوده D4:P9."""
    try:
        data_prod = df_raw_sheet.iloc[3:9, 3:16].copy() 
        headers_prod = df_raw_sheet.iloc[2, 3:16].tolist()
        data_prod.columns = headers_prod
        
        product_names = df_raw_sheet.iloc[3:9, 2].tolist() 
        
        data_prod['ProductTypeForTon'] = [str(p).strip() for p in product_names]
        df_prod = data_prod.melt(id_vars=['ProductTypeForTon'], var_name='MetricName', value_name='MetricValue').dropna(subset=['MetricValue'])
        
        df_prod = df_prod.pivot_table(index='ProductTypeForTon', columns='MetricName', values='MetricValue', aggfunc='first').reset_index()
        df_prod.columns.name = None
        
        df_prod = standardize_dataframe_for_oee(df_prod, type='prod')
        
        shift = df_raw_sheet.iloc[1, 1].strip() if not pd.isna(df_raw_sheet.iloc[1, 1]) else 'Unknown'
        
        df_prod['Date'] = file_date_obj
        df_prod['Shift'] = shift
        df_prod['Filename'] = uploaded_file_name
        
        return df_prod[['Date', 'Shift', 'Filename', 'ProductTypeForTon', 'PackQty', 'Waste', 'Duration', 'Capacity', 'Ton']]
        
    except Exception as e:
        return pd.DataFrame()


def read_error_data(df_raw_sheet, sheet_name_for_debug, uploaded_file_name_for_debug, file_date_obj):
    """خوانش و پردازش داده‌های Error از محدوده D13:P15."""
    try:
        data_err = df_raw_sheet.iloc[12:15, 3:16].copy()
        headers_err = df_raw_sheet.iloc[11, 3:16].tolist()
        data_err.columns = headers_err
        
        machine_names = df_raw_sheet.iloc[12:15, 2].tolist() 
        
        data_err['MachineType'] = [str(m).strip() for m in machine_names]
        df_err = data_err.melt(id_vars=['MachineType'], var_name='Error', value_name='Duration').dropna(subset=['Duration'])
        
        df_err = standardize_dataframe_for_oee(df_err, type='error')
        
        shift = df_raw_sheet.iloc[1, 1].strip() if not pd.isna(df_raw_sheet.iloc[1, 1]) else 'Unknown'

        df_err['Date'] = file_date_obj
        df_err['Shift'] = shift
        df_err['Filename'] = uploaded_file_name_for_debug
        
        return df_err[['Date', 'Shift', 'Filename', 'MachineType', 'Error', 'Duration']]
        
    except Exception as e:
        return pd.DataFrame()


def upload_to_supabase(uploaded_files, bucket_name="production-archive"):
    """بارگذاری فایل‌های خام به Supabase Storage (Archive)."""
    try:
        for file in uploaded_files:
            file_path = f"{file.name}"
            supabase.storage.from_(bucket_name).upload(file_path, file.getvalue(), file_options={"content-type": file.type, "upsert": True})
        st.success(f"✅ {len(uploaded_files)} فایل با موفقیت به آرشیو ذخیره شدند.")
        return True
    except Exception as e:
        st.error(f"❌ خطا در آپلود فایل‌ها به Supabase Storage: {e}")
        return False

@st.cache_data(ttl=3600, show_spinner="دریافت اطلاعات از پایگاه داده...")
def load_data_from_supabase_tables(table_name):
    """بارگذاری داده‌ها از جداول Supabase با رفع مشکل Case Sensitivity."""
    try:
        # Load all data without ordering in DB query
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # Check for date column case and standardize to 'Date'
        date_col_in_db = None
        if 'date' in df.columns:
            date_col_in_db = 'date'
        elif 'Date' in df.columns: 
            date_col_in_db = 'Date'
            
        if date_col_in_db:
            df['Date'] = pd.to_datetime(df[date_col_in_db]).dt.date
            if date_col_in_db == 'date': 
                df.drop(columns=['date'], inplace=True, errors='ignore')
            
        # Sort the DataFrame by the standardized 'Date' column in Python
        if 'Date' in df.columns:
            df = df.sort_values(by='Date', ascending=True).reset_index(drop=True)

        # Ensure numeric columns are correct
        for col in ['Duration', 'PackQty', 'Waste', 'Ton', 'Capacity', 'Manpower']:
            col_lower = col.lower()
            if col_lower in df.columns: 
                df[col] = pd.to_numeric(df[col_lower], errors='coerce').fillna(0)
            elif col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        return df

    except Exception as e:
        # st.error(f"Error loading table {table_name}: {e}")
        return pd.DataFrame()

def insert_to_db(df, table_name):
    """درج DataFrame به جدول Supabase."""
    if df.empty:
        return True
    
    # Column names are converted to lowercase for insertion (safer for PostgreSQL)
    df_insert = df.copy()
    df_insert.columns = [col.lower() for col in df_insert.columns]
    
    try:
        data_to_insert = df_insert.to_dict('records')
        response = supabase.table(table_name).insert(data_to_insert).execute()
        
        if response.data:
            return True
        else:
            error_data = getattr(response, 'error', None)
            if error_data:
                 st.error(f"خطا در درج داده به جدول {table_name}: {error_data.get('message', 'خطای نامشخص')}")
                 return False
            return True

    except Exception as e:
        st.error(f"خطای کلی در درج داده به جدول {table_name}: {e}")
        return False
        
def calculate_oee_metrics(df_prod, df_err):
    """محاسبه OEE و اجزای آن."""
    if df_prod.empty:
        return 0, 0, 0, 0, 0, 0, 0, 0

    total_planned_time_min = df_prod["Duration"].sum() * 60
    total_down_time_min = df_err["Duration"].sum()
    operating_time_min = max(0, total_planned_time_min - total_down_time_min)

    availability_pct = (operating_time_min / total_planned_time_min) * 100 if total_planned_time_min > 0 else 0
    
    total_pack_qty = df_prod["PackQty"].sum()
    total_waste = df_prod["Waste"].sum()
    total_good_qty = total_pack_qty - total_waste

    quality_pct = (total_good_qty / total_pack_qty) * 100 if total_pack_qty > 0 else 0
    
    avg_capacity_units_per_hour = df_prod["Capacity"].mean() 
    ideal_cycle_rate_per_min = avg_capacity_units_per_hour / 60 if avg_capacity_units_per_hour > 0 else 0
        
    theoretical_run_time_min = total_pack_qty / ideal_cycle_rate_per_min if ideal_cycle_rate_per_min > 0 else 0
        
    performance_pct = (theoretical_run_time_min / operating_time_min) * 100 if operating_time_min > 0 else 0
    performance_pct = min(performance_pct, 100) 
        
    oee_pct = (availability_pct / 100) * (performance_pct / 100) * (quality_pct / 100) * 100
    
    total_potential_packages = total_planned_time_min * ideal_cycle_rate_per_min
    line_efficiency_pct = (total_good_qty / total_potential_packages) * 100 if total_potential_packages > 0 else 0
    line_efficiency_pct = min(line_efficiency_pct, 100)
    
    return oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, total_down_time_min, total_good_qty, total_pack_qty

# ------------------------------------------------------------------------------
# --- ۳. منطق اصلی برنامه و ناوبری ---
# ------------------------------------------------------------------------------

def process_and_insert_data(uploaded_files, sheet_name_to_process):
    """آپلود فایل‌ها و درج داده‌ها به جداول."""
    total_files = len(uploaded_files)
    success_count = 0
    
    st.markdown("### ۱. آرشیو فایل‌های خام (Storage)")
    upload_to_supabase(uploaded_files) 
    
    st.markdown("### ۲. پردازش و درج داده به جداول (PostgreSQL)")
    status = st.status("در حال پردازش و درج داده‌ها...", expanded=True)
    
    for i, file in enumerate(uploaded_files):
        original_filename = file.name
        file_date_obj = parse_filename_date_to_datetime(original_filename)
        
        if not file_date_obj:
            status.write(f"❌ فایل **{original_filename}**: تاریخ در نام فایل پیدا نشد. Skip.")
            continue
            
        status.write(f"در حال پردازش فایل: **{original_filename}** (تاریخ: {file_date_obj})")
        
        try:
            df_raw_sheet = pd.read_excel(BytesIO(file.getvalue()), sheet_name=sheet_name_to_process, header=None)

            prod_df = read_production_data(df_raw_sheet, original_filename, sheet_name_to_process, file_date_obj)
            err_df = read_error_data(df_raw_sheet, sheet_name_to_process, original_filename, file_date_obj)

            if not prod_df.empty and 'PackQty' in prod_df.columns:
                prod_success = insert_to_db(prod_df, PROD_TABLE)
                if prod_success:
                    status.write(f"✅ داده‌های تولید با موفقیت به جدول `{PROD_TABLE}` درج شد.")
                else:
                    status.write(f"❌ خطای درج داده‌های تولید به `{PROD_TABLE}`.")
                    continue 
            else:
                status.write(f"⚠️ فایل **{original_filename}** حاوی داده‌های تولید معتبر نبود یا خالی بود.")

            if not err_df.empty and 'Duration' in err_df.columns:
                err_success = insert_to_db(err_df, ERROR_TABLE)
                if err_success:
                    status.write(f"✅ داده‌های خطا با موفقیت به جدول `{ERROR_TABLE}` درج شد.")
                else:
                    status.write(f"❌ خطای درج داده‌های خطا به `{ERROR_TABLE}`.")
            else:
                 status.write(f"⚠️ فایل **{original_filename}** حاوی داده‌های خطا معتبر نبود یا خالی بود.")

            success_count += 1

        except ValueError as e:
            if 'Worksheet named' in str(e) and 'not found' in str(e):
                status.write(f"❌ خطا در پردازش فایل اکسل **'{original_filename}'** (شیت: {sheet_name_to_process}): شیت با نام وارد شده پیدا نشد. **لطفاً نام شیت را بررسی کنید.**")
            else:
                status.write(f"❌ خطای پردازش فایل اکسل **'{original_filename}'** (شیت: {sheet_name_to_process}): ساختار شیت اکسل مطابقت ندارد. (جزئیات خطا: {e})")

        except Exception as e:
            status.write(f"❌ خطای نامشخص هنگام پردازش فایل **'{original_filename}'**: {e}")

    if success_count == total_files:
        status.update(label="✅ تمام فایل‌ها با موفقیت پردازش و آپلود شدند!", state="complete", expanded=False)
    else:
        status.update(label=f"⚠️ {success_count} از {total_files} فایل با موفقیت پردازش شدند. جزئیات را بررسی کنید.", state="error", expanded=True)
        
    st.cache_data.clear() 
    time.sleep(1) 
    st.rerun() 

# --- ناوبری اصلی برنامه ---

if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard" 

st.sidebar.header("منوی برنامه")
page_options = ["Data Analyzing Dashboard", "Upload Data", "Trend Analysis", "Data Archive"] 
selected_page_index = page_options.index(st.session_state.page)
selected_page = st.sidebar.radio("برو به:", options=page_options, index=selected_page_index, key="sidebar_radio")

if selected_page != st.session_state.page:
    st.session_state.page = selected_page
    st.rerun()


if st.session_state.page == "Upload Data":
    st.header("⬆️ بارگذاری فایل‌های اکسل و درج در پایگاه داده")

    sheet_name_to_process = st.text_input(
        "نام شیت (Sheet Name) حاوی داده‌ها:",
        value="daily", 
        help="نام دقیق شیتی که داده‌های تولید و خطا در آن قرار دارند (حساس به حروف کوچک و بزرگ)."
    )

    uploaded_files = st.file_uploader(
        "فایل‌های اکسل (.xlsx) را اینجا آپلود کنید", 
        type=["xlsx"], 
        accept_multiple_files=True
    )

    if st.button("🚀 شروع پردازش و درج داده‌ها"):
        if not uploaded_files:
            st.warning("لطفاً ابتدا فایل‌ها را انتخاب کنید.")
        elif not sheet_name_to_process.strip():
            st.error("لطفاً نام شیت (Sheet Name) را وارد کنید.")
        else:
            process_and_insert_data(uploaded_files, sheet_name_to_process.strip())


elif st.session_state.page == "Data Archive":
    st.header("🗄️ مدیریت و حذف داده‌های آرشیو")
    
    st.warning("⚠️ این بخش به شما اجازه می‌دهد تا تمام داده‌های یک جدول را حذف کنید. این عمل غیرقابل بازگشت است.")

    table_to_delete = st.selectbox(
        "جدول مورد نظر برای حذف داده‌ها:",
        [PROD_TABLE, ERROR_TABLE],
        key="archive_table_select"
    )
    
    delete_password = st.text_input("رمز عبور حذف:", type="password")
    
    delete_button_clicked = st.button(
        f"🔥 حذف تمام داده‌های جدول '{table_to_delete}'", 
        type="primary", 
        use_container_width=True
    )
    
    if delete_button_clicked:
        if delete_password == ARCHIVE_DELETE_PASSWORD:
            try:
                # Safe deletion using a filter
                supabase.table(table_to_delete).delete().neq('id', '0').execute() 
                st.cache_data.clear() 
                st.success(f"✅ تمام داده‌های جدول **{table_to_delete}** با موفقیت حذف شدند.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ خطای حذف: {e}")
        else:
            st.error("رمز عبور حذف اشتباه است.")


elif st.session_state.page == "Data Analyzing Dashboard":
    st.header("📈 داشبورد تحلیل OEE و تولید")
    
    # --- Connection Status Check (FIXED) ---
    try:
        # 🚨 FIX: Using select("*", count='exact').limit(0) is the correct and safest way to get row count via PostgREST
        prod_count_response = supabase.table(PROD_TABLE).select("*", count='exact').limit(0).execute() 
        err_count_response = supabase.table(ERROR_TABLE).select("*", count='exact').limit(0).execute() 
        
        prod_count = prod_count_response.count
        err_count = err_count_response.count
        
        st.success(f"✅ اتصال به Supabase برقرار است. (داده‌های تولید: {prod_count} سطر، داده‌های خطا: {err_count} سطر)")
    except Exception as e:
        st.error(f"❌ خطای حیاتی: اتصال به Supabase قطع است. لطفاً وضعیت API Key و جداول را بررسی کنید. (جزئیات خطا: {e})")
        st.stop()
    st.markdown("---")
    # --- End Connection Check ---

    df_prod_all = load_data_from_supabase_tables(PROD_TABLE)
    df_err_all = load_data_from_supabase_tables(ERROR_TABLE)

    if df_prod_all.empty:
        st.warning("داده‌ای برای تحلیل وجود ندارد. لطفاً ابتدا از بخش 'بارگذاری فایل‌ها'، داده‌ها را درج کنید.")
        st.info(f"اطلاعات از جداول `{PROD_TABLE}` و `{ERROR_TABLE}` بارگذاری می‌شود.")
        st.markdown("---")
    else:
        # --- Filters ---
        col_filters, col_date = st.columns([1, 3])
        
        min_available_date = df_prod_all['Date'].min()
        max_available_date = df_prod_all['Date'].max()
        
        with col_date:
            date_range = st.date_input(
                "بازه تاریخ:",
                value=(min_available_date, max_available_date),
                min_value=min_available_date,
                max_value=max_available_date,
                key="dashboard_date_range"
            )
            if len(date_range) == 2:
                selected_start_date, selected_end_date = date_range
            else:
                selected_start_date, selected_end_date = min_available_date, max_available_date
        
        df_prod_filtered = df_prod_all[
            (df_prod_all['Date'] >= selected_start_date) & 
            (df_prod_all['Date'] <= selected_end_date)
        ].copy()
        df_err_filtered = df_err_all[
            (df_err_all['Date'] >= selected_start_date) & 
            (df_err_all['Date'] <= selected_end_date)
        ].copy()

        unique_machines = ['All Lines'] + sorted(df_prod_filtered["ProductTypeForTon"].unique().tolist())
        with col_filters:
            selected_machine = st.selectbox("انتخاب خط تولید:", unique_machines)

        if selected_machine != 'All Lines':
            df_prod_filtered = df_prod_filtered[
                df_prod_filtered["ProductTypeForTon"] == selected_machine
            ].copy()
            df_err_filtered = df_err_filtered[
                df_err_filtered["machinetype"] == selected_machine.lower()
            ].copy()

        # --- OEE Calculations ---
        oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, \
            total_down_time_min, total_good_qty, total_pack_qty = calculate_oee_metrics(df_prod_filtered, df_err_filtered)

        # --- Display KPIs (Metrics) ---
        st.markdown("### شاخص‌های عملکرد کلیدی (KPIs)")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        def display_metric(col, label, value, color_threshold=85):
            col.markdown(f"<div style='background-color:#262730; padding: 10px; border-radius: 5px; text-align: center;'>"\
                         f"<p style='font-size: 14px; margin-bottom: 0; color: #aaa;'>{label}</p>"\
                         f"<h3 style='margin-top: 5px; color: {'#2ECC71' if value >= color_threshold else '#FF4B4B'};'>{value:,.1f} %</h3>"\
                         f"</div>", unsafe_allow_html=True)

        display_metric(col1, "OEE", oee_pct, color_threshold=70)
        display_metric(col2, "Availability", availability_pct, color_threshold=85)
        display_metric(col3, "Performance", performance_pct, color_threshold=85)
        display_metric(col4, "Quality", quality_pct, color_threshold=95)
        display_metric(col5, "Line Efficiency", line_efficiency_pct, color_threshold=70)

        st.markdown("---")

        col_prod, col_downtime = st.columns(2)
        
        with col_prod:
            col_prod.metric("تولید خالص (بسته)", f"{total_good_qty:,.0f} بسته")
        with col_downtime:
            col_downtime.metric("توقف کل (Downtime)", f"{total_down_time_min:,.0f} دقیقه")
        
        st.markdown("---")

        # --- OEE Component Breakdown (Gauge/Radial Chart) ---
        st.subheader("تحلیل اجزای OEE")
        
        fig_oee = go.Figure()
        
        fig_oee.add_trace(go.Indicator(
            mode="gauge+number",
            value=oee_pct,
            title={'text': "OEE", 'font': {'size': 20}},
            gauge={'axis': {'range': [None, 100], 'tickwidth': 1, 'tickcolor': "darkblue"},
                   'bar': {'color': "#8E44AD"},
                   'steps': [{'range': [0, 60], 'color': "#FF5733"}, {'range': [60, 85], 'color': "#FFC300"}],
                   'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 85}},
            domain={'row': 0, 'column': 0}
        ))
        
        components = [("Availability", availability_pct, "#2A8C8C", 85, 0, 1), 
                      ("Performance", performance_pct, "#00AEEF", 85, 1, 0),
                      ("Quality", quality_pct, "#2ECC71", 95, 1, 1)]
                      
        for title, value, color, threshold, row, col in components:
             fig_oee.add_trace(go.Indicator(
                mode="gauge+number",
                value=value,
                title={'text': title, 'font': {'size': 16}},
                gauge={'axis': {'range': [None, 100]},
                       'bar': {'color': color},
                       'steps': [{'range': [0, 60], 'color': "#FF5733"}, {'range': [60, threshold], 'color': "#FFC300"}],
                       'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': threshold}},
                domain={'row': row, 'column': col}
            ))

        fig_oee.update_layout(
            grid={'rows': 2, 'columns': 2, 'pattern': "independent"},
            height=600,
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig_oee, use_container_width=True)

        st.markdown("---")

        # --- Charts ---
        if not df_err_filtered.empty:
            st.subheader("۱۰ مورد برتر دلایل توقف")
            
            top_errors = df_err_filtered.groupby("error")["duration"].sum().reset_index()
            top_errors = top_errors.sort_values(by="duration", ascending=False).head(10)

            fig_err = px.bar(top_errors, x="error", y="duration",
                             title="دلایل توقف (بر حسب دقیقه)",
                             labels={"duration": "مدت زمان (دقیقه)", "error": "دلیل توقف"},
                             color="duration",
                             color_continuous_scale=px.colors.sequential.Sunset)
            fig_err.update_traces(texttemplate='%{y:.1f}', textposition='outside')
            st.plotly_chart(fig_err, use_container_width=True)
        
        st.subheader("مقدار تولید (Ton) بر اساس محصول")
        total_ton_per_product = df_prod_filtered.groupby("producttypeforton")["ton"].sum().reset_index()
        total_ton_per_product = total_ton_per_product.sort_values(by="ton", ascending=False)
        
        fig_ton = px.treemap(total_ton_per_product, path=[px.Constant("کل محصولات"), 'producttypeforton'], values="ton", 
                             title="توزیع تولید (Ton) بر اساس محصول",
                             color="ton", color_continuous_scale=px.colors.sequential.Teal)
        fig_ton.update_layout(margin=dict(t=50, l=25, r=25, b=25))
        st.plotly_chart(fig_ton, use_container_width=True)


elif st.session_state.page == "Trend Analysis":
    st.header("⏳ تحلیل روند زمانی (Trend Analysis)")

    df_prod_all = load_data_from_supabase_tables(PROD_TABLE)
    df_err_all = load_data_from_supabase_tables(ERROR_TABLE)

    if df_prod_all.empty:
        st.warning("داده‌ای برای تحلیل روند وجود ندارد. لطفاً ابتدا داده‌ها را بارگذاری کنید.")
    else:
        # Aggregate data by Date for Trend Analysis
        daily_summary = df_prod_all.groupby("Date").agg(
            TotalPackQty=('PackQty', 'sum'),
            TotalWaste=('Waste', 'sum'),
            TotalDuration=('Duration', 'sum'), # in hours
            AvgCapacity=('Capacity', 'mean')
        ).reset_index()
        
        daily_errors = df_err_all.groupby("Date")["Duration"].sum().reset_index().rename(columns={"Duration": "TotalDowntime"}) # in minutes

        daily_df = pd.merge(daily_summary, daily_errors, on="Date", how="left").fillna(0)
        
        # OEE/KPI Calculation
        daily_df['TotalDurationMin'] = daily_df['TotalDuration'] * 60
        daily_df['OperatingTime'] = daily_df['TotalDurationMin'] - daily_df['TotalDowntime']
        daily_df['OperatingTime'] = daily_df['OperatingTime'].apply(lambda x: max(0, x))
        
        daily_df['Availability'] = np.where(daily_df['TotalDurationMin'] > 0, (daily_df['OperatingTime'] / daily_df['TotalDurationMin']) * 100, 0)
        
        daily_df['TotalGoodQty'] = daily_df['TotalPackQty'] - daily_df['TotalWaste']
        daily_df['Quality'] = np.where(daily_df['TotalPackQty'] > 0, (daily_df['TotalGoodQty'] / daily_df['TotalPackQty']) * 100, 0)

        daily_df['IdealCycleRatePerMin'] = daily_df['AvgCapacity'] / 60
        daily_df['TheoreticalRunTime'] = np.where(daily_df['IdealCycleRatePerMin'] > 0, daily_df['TotalPackQty'] / daily_df['IdealCycleRatePerMin'], 0)
        daily_df['Performance'] = np.where(daily_df['OperatingTime'] > 0, (daily_df['TheoreticalRunTime'] / daily_df['OperatingTime']) * 100, 0)
        daily_df['Performance'] = daily_df['Performance'].apply(lambda x: min(x, 100))

        daily_df['OEE'] = (daily_df['Availability'] / 100) * (daily_df['Performance'] / 100) * (daily_df['Quality'] / 100) * 100
        
        
        # --- Display Charts ---
        st.subheader("روند OEE و اجزای آن")
        fig_trend = px.line(daily_df, x="Date", y=["OEE", "Availability", "Performance", "Quality"], 
                            title="روند روزانه OEE و اجزای آن",
                            labels={"value": "درصد (%)", "Date": "تاریخ"},
                            template="plotly_white")
        fig_trend.update_layout(legend_title_text='شاخص')
        st.plotly_chart(fig_trend, use_container_width=True)

        st.subheader("روند روزانه تولید (بسته) و توقف (Downtime)")
        
        fig_dual = go.Figure()

        fig_dual.add_trace(go.Bar(
            x=daily_df['Date'],
            y=daily_df['TotalPackQty'],
            name='تولید کل (بسته)',
            yaxis='y1',
            marker_color='skyblue'
        ))

        fig_dual.add_trace(go.Scatter(
            x=daily_df['Date'],
            y=daily_df['TotalDowntime'],
            name='توقف کل (دقیقه)',
            yaxis='y2',
            mode='lines+markers',
            marker_color='red'
        ))

        fig_dual.update_layout(
            title='روند روزانه تولید و توقف',
            yaxis=dict(
                title='تولید کل (بسته)',
                titlefont=dict(color='skyblue'),
                tickfont=dict(color='skyblue')
            ),
            yaxis2=dict(
                title='توقف کل (دقیقه)',
                titlefont=dict(color='red'),
                tickfont=dict(color='red'),
                overlaying='y',
                side='right'
            ),
            legend=dict(x=0, y=1.1, orientation="h")
        )
        st.plotly_chart(fig_dual, use_container_width=True)
