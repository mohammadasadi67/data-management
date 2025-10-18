import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from io import BytesIO
from supabase import create_client, Client
import base64
from datetime import datetime, timedelta, time as datetime_time
import re
import time
import numpy as np
import json
import logging

# تنظیمات لاگینگ (اختیاری)
# logging.basicConfig(level=logging.INFO)

# --- Supabase Configuration ---
# توجه: کلیدهای شما حفظ شده‌اند.
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# Initialize Supabase client globally
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"

# --- DB Table Names ---
PROD_TABLE = "production_data"
ERROR_TABLE = "error_data"
# -------------------------


st.set_page_config(layout="wide", page_title="OEE & Production Dashboard", initial_sidebar_state="expanded")
st.title("📊 داشبورد تحلیل تولید و OEE")


# --- Helper Functions (Updated/New) ---

@st.cache_data(ttl=3600, show_spinner="دریافت اطلاعات از پایگاه داده...")
def load_data_from_supabase_tables(table_name):
    """Fetches all data from a specified Supabase PostgreSQL table."""
    try:
        response = supabase.table(table_name).select("*").order("Date", desc=False).execute()
        data = response.data
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        # Convert necessary columns to correct types
        if 'Date' in df.columns:
            df['Date'] = pd.to_datetime(df['Date']).dt.date
        
        # Ensure numeric columns are correct
        for col in ['Duration', 'PackQty', 'Waste', 'Ton', 'Capacity', 'Manpower']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df

    except Exception as e:
        # Check if the error is due to missing table (42P01: relation does not exist)
        if isinstance(e, dict) and e.get('code') == '42P01':
            st.error(f"خطای پایگاه داده: جدول '{table_name}' وجود ندارد. لطفاً مطمئن شوید جداول را در Supabase ایجاد کرده‌اید.")
        elif '42P01' in str(e): # General check for 42P01 if error format is different
             st.error(f"خطای پایگاه داده: جدول '{table_name}' وجود ندارد. لطفاً مطمئن شوید جداول را در Supabase ایجاد کرده‌اید.")
        else:
            st.error(f"خطا در بارگذاری داده‌ها از Supabase برای جدول {table_name}: {e}")
        return pd.DataFrame()

def insert_to_db(df, table_name):
    """Inserts DataFrame records into the specified Supabase table."""
    if df.empty:
        return True
    try:
        # Convert DataFrame to list of dictionaries
        data_to_insert = df.to_dict('records')
        
        # Use upsert to handle potential duplicates (based on a unique key if one exists, 
        # but since we don't have a natural key in the Excel data, we just insert).
        # For simplicity, we assume we are not inserting duplicates.
        response = supabase.table(table_name).insert(data_to_insert).execute()
        
        if response.data:
            return True
        else:
            # Supabase API can return an error dictionary even if 'execute' succeeds but insertion fails
            error_data = getattr(response, 'error', None)
            if error_data:
                 st.error(f"خطا در درج داده به جدول {table_name}: {error_data.get('message', 'خطای نامشخص')}")
                 return False
            return True # Assume success if no error is explicitly returned

    except Exception as e:
        st.error(f"خطای کلی در درج داده به جدول {table_name}: {e}")
        return False

# --- OEE and Analysis Metrics (New/Replaced Logic) ---

def calculate_oee_metrics(df_prod, df_err):
    """Calculates OEE, Availability, Performance, and Quality metrics."""
    if df_prod.empty:
        return 0, 0, 0, 0, 0, 0, 0, 0 # Returns default KPIs

    # --- 1. Planned Production Time (Total Duration) ---
    # Duration is in hours, convert to minutes
    total_planned_time_min = df_prod["Duration"].sum() * 60

    # --- 2. Down Time (Error Time) ---
    # df_err['Duration'] is already in minutes
    total_down_time_min = df_err["Duration"].sum()
    
    # --- 3. Operating Time ---
    operating_time_min = total_planned_time_min - total_down_time_min
    operating_time_min = max(0, operating_time_min) # Cannot be negative

    # --- KPI 1: Availability (%) ---
    availability_pct = 0
    if total_planned_time_min > 0:
        availability_pct = (operating_time_min / total_planned_time_min) * 100
    
    # --- 4. Total Production (Packages) ---
    total_pack_qty = df_prod["PackQty"].sum()
    total_waste = df_prod["Waste"].sum()
    total_good_qty = total_pack_qty - total_waste

    # --- KPI 2: Quality (%) ---
    quality_pct = 0
    if total_pack_qty > 0:
        quality_pct = (total_good_qty / total_pack_qty) * 100
    
    # --- 5. Ideal Cycle Rate (Capacity) ---
    # We use the average recorded Capacity (units/hour) for the time period
    avg_capacity_units_per_hour = df_prod["Capacity"].mean() 
    
    ideal_cycle_rate_per_min = avg_capacity_units_per_hour / 60 if avg_capacity_units_per_hour > 0 else 0
        
    # --- 6. Theoretical Production Time (Ideal Run Time) ---
    # Theoretical Production Time (Ideal Time to produce actual total_pack_qty)
    theoretical_run_time_min = 0 
    if ideal_cycle_rate_per_min > 0:
        theoretical_run_time_min = total_pack_qty / ideal_cycle_rate_per_min
        
    # --- KPI 3: Performance (%) ---
    performance_pct = 0
    if operating_time_min > 0:
        performance_pct = (theoretical_run_time_min / operating_time_min) * 100
        # Performance should not exceed 100% (Cap it for OEE standard)
        performance_pct = min(performance_pct, 100) 
        
    # --- KPI 4: OEE (%) ---
    oee_pct = (availability_pct / 100) * (performance_pct / 100) * (quality_pct / 100) * 100
    
    # --- KPI 5: Line Efficiency (Total Yield % against Theoretical Max) ---
    # Total Potential Packages = Total Planned Time (min) * Ideal Cycle Rate (units/min)
    total_potential_packages = total_planned_time_min * ideal_cycle_rate_per_min
    line_efficiency_pct = 0
    if total_potential_packages > 0:
        line_efficiency_pct = (total_good_qty / total_potential_packages) * 100
        line_efficiency_pct = min(line_efficiency_pct, 100)
    
    
    return oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, total_down_time_min, total_good_qty, total_pack_qty

# --- Helper functions from original code (kept for consistency) ---

# All original helper functions (parse_filename_date_to_datetime, upload_to_supabase, 
# get_all_supabase_files, download_from_supabase, get_download_link, convert_time, 
# convert_duration_to_minutes, calculate_ton, determine_machine_type, read_production_data, 
# read_error_data, clear_supabase_bucket) should be included here. 
# Due to the length, I will only include the necessary modifications to read_production_data and read_error_data.

# NOTE: The rest of the original helper functions (parse_filename_date_to_datetime to clear_supabase_bucket) 
# must be placed here for the code to run, but are omitted for brevity in this response. 
# Assuming user copies the original functions from their 'test.txt' file, only the modified part is shown.

# **Modification to read_production_data (Removing old efficiency calc and streamlining)**
# This function must be updated to NOT calculate Efficiency(%) and PotentialProduction
def read_production_data(df_raw_sheet, uploaded_file_name, selected_sheet_name, file_date_obj):
    # ... (Keep all lines up to the final column selection) ...
    # Old logic for Efficiency(%) and PotentialProduction is REMOVED
    # (Lines 336-338 in original content)
    
    # Select and order final columns for the output DataFrame
    final_cols = ["Date", "Product", "Capacity", "Manpower", "Duration", "PackQty", "Waste", "Ton", 
                  "ProductionTypeForTon"] # Efficiency columns removed
    data = data[[col for col in final_cols if col in data.columns]]
    return data
    
# **Modification to read_error_data (No change needed, it's fine)**
# def read_error_data(df_raw_sheet, sheet_name_for_debug="Unknown Sheet", uploaded_file_name_for_debug="Unknown File", file_date_obj=None):
#    ... (Keep the original function) ...

# ----------------------------------------------------------------------------------------------------------------

# --- NEW: Master Processing Function for Upload Page ---
def process_and_insert_data(uploaded_files, sheet_name_to_process):
    """Uploads to storage, processes the specified sheet, and inserts data into DB tables."""
    total_files = len(uploaded_files)
    success_count = 0
    
    # First, upload all files to storage (Archive)
    st.markdown("### ۱. آرشیو فایل‌های خام (Storage)")
    upload_to_supabase(uploaded_files) 
    
    # After storage upload, we can now process them from the uploaded file object itself (faster than re-downloading)
    st.markdown("### ۲. پردازش و درج داده به جداول (PostgreSQL)")
    status = st.status("در حال پردازش و درج داده‌ها...", expanded=True)
    
    for i, file in enumerate(uploaded_files):
        original_filename = file.name
        file_date_obj = parse_filename_date_to_datetime(original_filename)
        
        status.write(f"در حال پردازش فایل: **{original_filename}** (تاریخ: {file_date_obj})")
        
        try:
            # Read all sheets to find the correct one
            df_raw_sheet = pd.read_excel(BytesIO(file.getvalue()), sheet_name=sheet_name_to_process, header=None)

            # Read Production and Error data
            prod_df = read_production_data(df_raw_sheet, original_filename, sheet_name_to_process, file_date_obj)
            err_df = read_error_data(df_raw_sheet, sheet_name_to_process, original_filename, file_date_obj)

            # Insert Production Data
            if not prod_df.empty:
                prod_success = insert_to_db(prod_df, PROD_TABLE)
                if prod_success:
                    status.write(f"✅ داده‌های تولید با موفقیت به جدول `{PROD_TABLE}` درج شد.")
                else:
                    status.write(f"❌ خطای درج داده‌های تولید به `{PROD_TABLE}`.")
                    continue # Skip error data insertion if prod data failed
            else:
                status.write(f"⚠️ فایل **{original_filename}** حاوی داده‌های تولید معتبر نبود یا خالی بود.")

            # Insert Error Data
            if not err_df.empty:
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

    # Final status update with the bug fix
    if success_count == total_files:
        status.update(label="✅ تمام فایل‌ها با موفقیت پردازش و آپلود شدند!", state="complete", expanded=False)
    else:
        status.update(label=f"⚠️ {success_count} از {total_files} فایل با موفقیت پردازش شدند. جزئیات را بررسی کنید.", state="error", expanded=True)
        
    st.cache_data.clear() # Clear all caches to force data reload from DB
    st.rerun() 
# ----------------------------------------------------------------------------------------------------------------

# --- Main Application Logic (Navigation) ---

# Manage page state with st.session_state
if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard"  # Set default page to Dashboard

st.sidebar.header("منوی برنامه")
# Contact Me page is removed from navigation
page_options = ["Data Analyzing Dashboard", "Upload Data", "Data Archive", "Trend Analysis"] 
selected_page_index = page_options.index(st.session_state.page)
selected_page = st.sidebar.radio("برو به:", options=page_options, index=selected_page_index, key="sidebar_radio")

# Update session state based on radio selection
if selected_page != st.session_state.page:
    st.session_state.page = selected_page
    st.rerun()  # Rerun to switch page immediately


if st.session_state.page == "Upload Data":
    st.header("⬆️ بارگذاری فایل‌های اکسل و درج در پایگاه داده")

    sheet_name_to_process = st.text_input(
        "نام شیت (Sheet Name) حاوی داده‌ها:",
        value="daily", # Default value to help the user
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
    # The original Data Archive page logic (for file storage management) is kept here.
    # ... (Original code for Data Archive: search, download, delete bucket) ...
    st.header("📦 آرشیو فایل‌های خام")
    st.warning("این بخش صرفاً مدیریت فایل‌های اکسل خام در Supabase Storage (بخش آرشیو) است، نه داده‌های درون جداول تحلیل.")
    # You must insert the original logic for Data Archive here from your file.


elif st.session_state.page == "Data Analyzing Dashboard":
    st.header("📈 داشبورد تحلیل OEE و تولید")

    # Load all data from DB tables (faster and more reliable than re-parsing Excel)
    df_prod_all = load_data_from_supabase_tables(PROD_TABLE)
    df_err_all = load_data_from_supabase_tables(ERROR_TABLE)

    if df_prod_all.empty:
        st.warning("داده‌ای برای تحلیل وجود ندارد. لطفاً ابتدا از بخش 'بارگذاری فایل‌ها'، داده‌ها را درج کنید.")
        st.info(f"اطلاعات از جداول `{PROD_TABLE}` و `{ERROR_TABLE}` بارگذاری می‌شود.")
        st.markdown("---")
    else:
        # --- Filters ---
        col_filters, col_date = st.columns([1, 3])
        
        # 1. Date Filter
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
                st.warning("لطفاً بازه تاریخ را مشخص کنید.")
                selected_start_date, selected_end_date = min_available_date, max_available_date
        
        # Filter data by date
        df_prod_filtered = df_prod_all[
            (df_prod_all['Date'] >= selected_start_date) & 
            (df_prod_all['Date'] <= selected_end_date)
        ].copy()
        df_err_filtered = df_err_all[
            (df_err_all['Date'] >= selected_start_date) & 
            (df_err_all['Date'] <= selected_end_date)
        ].copy()

        # 2. Machine Filter
        unique_machines = ['All Machines'] + sorted(df_prod_filtered["ProductionTypeForTon"].unique().tolist())
        with col_filters:
            selected_machine = st.selectbox("انتخاب ماشین:", unique_machines)

        if selected_machine != 'All Machines':
            df_prod_filtered = df_prod_filtered[
                df_prod_filtered["ProductionTypeForTon"] == selected_machine
            ].copy()
            df_err_filtered = df_err_filtered[
                df_err_filtered["MachineType"] == selected_machine
            ].copy()

        # --- OEE Calculations ---
        oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, \
            total_down_time_min, total_good_qty, total_pack_qty = calculate_oee_metrics(df_prod_filtered, df_err_filtered)

        # --- Display KPIs (Metrics) ---
        st.markdown("### شاخص‌های عملکرد کلیدی (KPIs)")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        # Format the metric display
        def display_metric(col, label, value, delta=None):
            if delta is not None:
                col.metric(label, f"{value:,.1f} %", delta=f"{delta:,.1f} %")
            else:
                col.metric(label, f"{value:,.1f} %")

        display_metric(col1, "OEE", oee_pct)
        display_metric(col2, "در دسترس بودن (Availability)", availability_pct)
        display_metric(col3, "عملکرد (Performance)", performance_pct)
        display_metric(col4, "کیفیت (Quality)", quality_pct)
        display_metric(col5, "بازدهی خط (Line Efficiency)", line_efficiency_pct)

        col_prod, col_downtime = st.columns(2)
        
        with col_prod:
            col_prod.metric("بسته‌بندی کل (Units)", f"{total_pack_qty:,.0f} بسته")
        with col_downtime:
            col_downtime.metric("توقف کل (Downtime)", f"{total_down_time_min:,.0f} دقیقه")
        
        st.markdown("---")

        # --- Charts ---
        
        # 1. OEE Component Breakdown (Gauge/Radial Chart)
        st.subheader("تحلیل اجزای OEE")
        
        # Using a Gauge chart for better visual
        fig_oee = go.Figure()
        
        # Availability
        fig_oee.add_trace(go.Indicator(
            mode="gauge+number",
            value=availability_pct,
            title={'text': "Availability"},
            gauge={'axis': {'range': [None, 100]},
                   'bar': {'color': "#2A8C8C"},
                   'steps': [{'range': [0, 60], 'color': "#FF5733"}, {'range': [60, 85], 'color': "#FFC300"}],
                   'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 85}},
            domain={'row': 0, 'column': 0}
        ))
        
        # Performance
        fig_oee.add_trace(go.Indicator(
            mode="gauge+number",
            value=performance_pct,
            title={'text': "Performance"},
            gauge={'axis': {'range': [None, 100]},
                   'bar': {'color': "#00AEEF"},
                   'steps': [{'range': [0, 60], 'color': "#FF5733"}, {'range': [60, 85], 'color': "#FFC300"}],
                   'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 85}},
            domain={'row': 0, 'column': 1}
        ))
        
        # Quality
        fig_oee.add_trace(go.Indicator(
            mode="gauge+number",
            value=quality_pct,
            title={'text': "Quality"},
            gauge={'axis': {'range': [None, 100]},
                   'bar': {'color': "#2ECC71"},
                   'steps': [{'range': [0, 90], 'color': "#FF5733"}, {'range': [90, 95], 'color': "#FFC300"}],
                   'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 95}},
            domain={'row': 1, 'column': 0}
        ))
        
        # OEE
        fig_oee.add_trace(go.Indicator(
            mode="gauge+number",
            value=oee_pct,
            title={'text': "OEE"},
            gauge={'axis': {'range': [None, 100]},
                   'bar': {'color': "#8E44AD"},
                   'steps': [{'range': [0, 60], 'color': "#FF5733"}, {'range': [60, 85], 'color': "#FFC300"}],
                   'threshold': {'line': {'color': "red", 'width': 4}, 'thickness': 0.75, 'value': 85}},
            domain={'row': 1, 'column': 1}
        ))
        
        fig_oee.update_layout(
            grid={'rows': 2, 'columns': 2, 'pattern': "independent"},
            height=600,
            margin=dict(l=20, r=20, t=50, b=20)
        )
        st.plotly_chart(fig_oee, use_container_width=True)

        st.markdown("---")

        # 2. Top Downtime Reasons (Bar Chart)
        if not df_err_filtered.empty:
            st.subheader("۱۰ مورد برتر دلایل توقف")
            
            # Aggregate total downtime by error
            top_errors = df_err_filtered.groupby("Error")["Duration"].sum().reset_index()
            top_errors = top_errors.sort_values(by="Duration", ascending=False).head(10)

            fig_err = px.bar(top_errors, x="Error", y="Duration",
                             title="دلایل توقف (بر حسب دقیقه)",
                             labels={"Duration": "مدت زمان (دقیقه)", "Error": "دلیل توقف"},
                             color="Duration",
                             color_continuous_scale=px.colors.sequential.Sunset)
            fig_err.update_traces(texttemplate='%{y:.1f}', textposition='outside')
            st.plotly_chart(fig_err, use_container_width=True)
        else:
            st.info("داده‌های توقف (Error) برای بازه انتخابی وجود ندارد.")
            
        st.markdown("---")
        
        # 3. Production Tons by Product (Treemap - Kept from original code but enhanced)
        st.subheader("مقدار تولید (Ton) بر اساس محصول")
        
        total_ton_per_product = df_prod_filtered.groupby("Product")["Ton"].sum().reset_index()
        total_ton_per_product = total_ton_per_product.sort_values(by="Ton", ascending=False)
        
        fig_ton = px.treemap(total_ton_per_product, path=[px.Constant("کل محصولات"), 'Product'], values="Ton", 
                             title="توزیع تولید (Ton) بر اساس محصول",
                             color="Ton", color_continuous_scale=px.colors.sequential.Teal)
        fig_ton.update_layout(margin=dict(t=50, l=25, r=25, b=25))
        st.plotly_chart(fig_ton, use_container_width=True)


elif st.session_state.page == "Trend Analysis":
    st.header("⏳ تحلیل روند زمانی (Trend Analysis)")

    # Load all data from DB tables
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
        
        # Convert TotalDuration (hours) to minutes
        daily_df['TotalDurationMin'] = daily_df['TotalDuration'] * 60
        
        # Calculate OEE components for each day (reusing the logic in a lambda function or loop is too complex/slow)
        # We perform the component calculation on the already aggregated daily data for simplicity in trend
        
        daily_df['OperatingTime'] = daily_df['TotalDurationMin'] - daily_df['TotalDowntime']
        daily_df['OperatingTime'] = daily_df['OperatingTime'].apply(lambda x: max(0, x))
        
        # Availability
        daily_df['Availability'] = np.where(daily_df['TotalDurationMin'] > 0, 
                                            (daily_df['OperatingTime'] / daily_df['TotalDurationMin']) * 100, 0)
        
        # Quality
        daily_df['TotalGoodQty'] = daily_df['TotalPackQty'] - daily_df['TotalWaste']
        daily_df['Quality'] = np.where(daily_df['TotalPackQty'] > 0, 
                                       (daily_df['TotalGoodQty'] / daily_df['TotalPackQty']) * 100, 0)

        # Performance
        daily_df['IdealCycleRatePerMin'] = daily_df['AvgCapacity'] / 60
        daily_df['TheoreticalRunTime'] = np.where(daily_df['IdealCycleRatePerMin'] > 0, 
                                                 daily_df['TotalPackQty'] / daily_df['IdealCycleRatePerMin'], 0)
        daily_df['Performance'] = np.where(daily_df['OperatingTime'] > 0, 
                                            (daily_df['TheoreticalRunTime'] / daily_df['OperatingTime']) * 100, 0)
        daily_df['Performance'] = daily_df['Performance'].apply(lambda x: min(x, 100)) # Cap at 100%

        # OEE
        daily_df['OEE'] = (daily_df['Availability'] / 100) * (daily_df['Performance'] / 100) * (daily_df['Quality'] / 100) * 100
        
        
        # --- Display Charts ---

        st.subheader("روند OEE و اجزای آن")
        fig_trend = px.line(daily_df, x="Date", y=["OEE", "Availability", "Performance", "Quality"], 
                            title="روند روزانه OEE و اجزای آن",
                            labels={"value": "درصد (%)", "Date": "تاریخ"},
                            template="plotly_white")
        fig_trend.update_layout(legend_title_text='شاخص')
        st.plotly_chart(fig_trend, use_container_width=True)

        st.subheader("روند روزانه تولید (Ton) و توقف (Downtime)")
        
        # Create a dual-axis chart for Ton and Downtime
        fig_dual = go.Figure()

        # Bar chart for Production (Tons)
        fig_dual.add_trace(go.Bar(
            x=daily_df['Date'],
            y=daily_df['TotalPackQty'],
            name='تولید کل (بسته)',
            yaxis='y1',
            marker_color='skyblue'
        ))

        # Line chart for Downtime (Minutes)
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

# NOTE: The remaining original helper functions are required for the code to run correctly
# and should be included by the user in the final app.py file.
