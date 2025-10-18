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
        # PostgreSQL/Supabase به طور پیش‌فرض نام ستون‌ها را با حروف کوچک ذخیره می‌کند.
        # ما نام ستون‌ها را به lowercase تغییر می‌دهیم تا با دیتابیس تطبیق یابد.
        response = supabase.table(table_name).select("*").order("date", desc=False).execute()
        data = response.data
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        # 🚨 اصلاح حیاتی: بررسی ستون 'date' (حروف کوچک) و تبدیل آن به 'Date' (حروف بزرگ) برای سازگاری با بقیه کد
        if 'date' in df.columns:
            df['Date'] = pd.to_datetime(df['date']).dt.date
            df.drop(columns=['date'], inplace=True) # حذف ستون اصلی 'date'
        elif 'Date' in df.columns:
            # اگر 'Date' وجود داشت (کمتر محتمل است)، فقط آن را تبدیل می‌کنیم
            df['Date'] = pd.to_datetime(df['Date']).dt.date

        # Ensure numeric columns are correct
        for col in ['Duration', 'PackQty', 'Waste', 'Ton', 'Capacity', 'Manpower']:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
                
        return df

    except Exception as e:
        if isinstance(e, dict) and e.get('code') == '42P01':
            st.error(f"خطای پایگاه داده: جدول '{table_name}' وجود ندارد. لطفاً مطمئن شوید جداول را در Supabase ایجاد کرده‌اید.")
        elif '42P01' in str(e): 
             st.error(f"خطای پایگاه داده: جدول '{table_name}' وجود ندارد. لطفاً مطمئن شوید جداول را در Supabase ایجاد کرده‌اید.")
        else:
            st.error(f"خطا در بارگذاری داده‌ها از Supabase برای جدول {table_name}: {e}")
        return pd.DataFrame()

def insert_to_db(df, table_name):
    """Inserts DataFrame records into the specified Supabase table."""
    if df.empty:
        return True
    
    # 🚨 اصلاح حیاتی: تبدیل نام ستون‌های DataFrame به حروف کوچک قبل از درج
    # تا با نحوه نام‌گذاری PostgreSQL (حروف کوچک) مطابقت داشته باشد.
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

# --- OEE and Analysis Metrics (New/Replaced Logic) ---

def calculate_oee_metrics(df_prod, df_err):
    """Calculates OEE, Availability, Performance, and Quality metrics."""
    if df_prod.empty:
        return 0, 0, 0, 0, 0, 0, 0, 0

    # (بقیه منطق calculate_oee_metrics بدون تغییر باقی می‌ماند، چون از ستون‌های استاندارد شده مانند 'Duration', 'PackQty' استفاده می‌کند.)
    
    # --- ۱. Planned Production Time (Total Duration) ---
    total_planned_time_min = df_prod["Duration"].sum() * 60

    # --- ۲. Down Time (Error Time) ---
    total_down_time_min = df_err["Duration"].sum()
    
    # --- ۳. Operating Time ---
    operating_time_min = total_planned_time_min - total_down_time_min
    operating_time_min = max(0, operating_time_min)

    # --- KPI ۱: Availability (%) ---
    availability_pct = 0
    if total_planned_time_min > 0:
        availability_pct = (operating_time_min / total_planned_time_min) * 100
    
    # --- ۴. Total Production (Packages) ---
    total_pack_qty = df_prod["PackQty"].sum()
    total_waste = df_prod["Waste"].sum()
    total_good_qty = total_pack_qty - total_waste

    # --- KPI ۲: Quality (%) ---
    quality_pct = 0
    if total_pack_qty > 0:
        quality_pct = (total_good_qty / total_pack_qty) * 100
    
    # --- ۵. Ideal Cycle Rate (Capacity) ---
    avg_capacity_units_per_hour = df_prod["Capacity"].mean() 
    ideal_cycle_rate_per_min = avg_capacity_units_per_hour / 60 if avg_capacity_units_per_hour > 0 else 0
        
    # --- ۶. Theoretical Production Time (Ideal Run Time) ---
    theoretical_run_time_min = 0 
    if ideal_cycle_rate_per_min > 0:
        theoretical_run_time_min = total_pack_qty / ideal_cycle_rate_per_min
        
    # --- KPI ۳: Performance (%) ---
    performance_pct = 0
    if operating_time_min > 0:
        performance_pct = (theoretical_run_time_min / operating_time_min) * 100
        performance_pct = min(performance_pct, 100) 
        
    # --- KPI ۴: OEE (%) ---
    oee_pct = (availability_pct / 100) * (performance_pct / 100) * (quality_pct / 100) * 100
    
    # --- KPI ۵: Line Efficiency (Total Yield % against Theoretical Max) ---
    total_potential_packages = total_planned_time_min * ideal_cycle_rate_per_min
    line_efficiency_pct = 0
    if total_potential_packages > 0:
        line_efficiency_pct = (total_good_qty / total_potential_packages) * 100
        line_efficiency_pct = min(line_efficiency_pct, 100)
    
    
    return oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, total_down_time_min, total_good_qty, total_pack_qty

# --- Helper functions from original code (must be included here) ---

# (توجه: توابع کمکی parse_filename_date_to_datetime، read_production_data، read_error_data، upload_to_supabase و...
# که قبلاً در کد شما وجود داشتند و برای اجرای منطق اصلی آپلود ضروری هستند، باید در این قسمت قرار گیرند.
# فرض بر این است که شما آن‌ها را از آخرین نسخه کد خود در اینجا کپی می‌کنید.)
# ... (کدهای توابع کمکی قبلی شما باید اینجا قرار گیرند) ...


# ----------------------------------------------------------------------------------------------------------------

# --- NEW: Master Processing Function for Upload Page ---
def process_and_insert_data(uploaded_files, sheet_name_to_process):
    """Uploads to storage, processes the specified sheet, and inserts data into DB tables."""
    # (کد تابع process_and_insert_data بدون تغییر در منطق اینجا قرار می‌گیرد)
    total_files = len(uploaded_files)
    success_count = 0
    
    # First, upload all files to storage (Archive)
    st.markdown("### ۱. آرشیو فایل‌های خام (Storage)")
    # upload_to_supabase(uploaded_files) # اگر تابع upload_to_supabase مربوط به Storage است

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
    # st.rerun() # Rerun is necessary after upload
# ----------------------------------------------------------------------------------------------------------------

# --- Main Application Logic (Navigation) ---

# (بقیه کد اصلی برنامه بدون تغییر باقی می‌ماند.)

if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard"
    
# (Navigation logic and page content for Upload Data, Data Analyzing Dashboard, Data Archive, Trend Analysis)

# ... (بقیه کد برنامه اصلی از اینجا ادامه می‌یابد) ...
