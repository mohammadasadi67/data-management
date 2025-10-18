import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from supabase import create_client, Client
import base64
from datetime import datetime, timedelta, time as datetime_time
import re
import time
import numpy as np
import json # Added for better handling of Supabase data

# --- Supabase Configuration ---
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# Initialize Supabase client globally
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"

# --- Page Configuration and State Initialization ---
st.set_page_config(layout="wide", page_title="OEE Analysis Dashboard", page_icon="🏭")

if 'page' not in st.session_state:
    st.session_state.page = "Dashboard"
if 'prod_df' not in st.session_state:
    st.session_state.prod_df = pd.DataFrame()
if 'err_df' not in st.session_state:
    st.session_state.err_df = pd.DataFrame()
if 'archived_files' not in st.session_state:
    st.session_state.archived_files = []
if 'prod_files_loaded' not in st.session_state:
    st.session_state.prod_files_loaded = False
if 'err_files_loaded' not in st.session_state:
    st.session_state.err_files_loaded = False

# --- Helper Functions (Reconstructed based on context) ---

def parse_filename_date_to_datetime(filename):
    """Extracts ddmmyyyy from filename and converts it to a datetime.date object."""
    date_match = re.search(r'(\d{8})', filename)
    if date_match:
        try:
            return datetime.strptime(date_match.group(1), '%d%m%Y').date()
        except ValueError:
            pass
    return None

def load_data_from_supabase(table_name):
    """Loads all data from a specified Supabase table."""
    try:
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        return pd.DataFrame(data)
    except Exception as e:
        st.error(f"Error loading data from Supabase table {table_name}: {e}")
        return pd.DataFrame()

def list_archived_files():
    """Lists files from the 'archive' Supabase storage bucket."""
    try:
        # Use the global supabase client to access Storage
        response = supabase.storage.from_("archive").list()
        
        # Supabase list() returns a list of file metadata dictionaries.
        if isinstance(response, list):
            # Filter out the directory listing metadata object (name: '.')
            files = [f['name'] for f in response if f['name'] != '.']
            return files
        else:
            # Handle potential error dictionaries returned by the API call
            error_message = response.get('message', 'خطای نامشخص') if isinstance(response, dict) else 'فرمت پاسخ نامعتبر'
            st.error(f"خطا در لیست کردن فایل‌های آرشیو: {error_message}")
            return []
            
    except Exception as e:
        st.error(f"خطای کلی در دسترسی به آرشیو Supabase: {e}")
        return []

def process_uploaded_files(uploaded_files, file_type):
    """Processes uploaded Excel files for production or error data."""
    all_data = []
    
    # Define columns expected for each type
    expected_cols = {
        'production': ['MachineType', 'Product', 'ProductionTypeForTon', 'StartTime', 'StopTime', 'TotalGood', 'IdealTime', 'AvailableTime'],
        'error': ['MachineType', 'Error', 'Duration', 'StartTime', 'StopTime', 'Date']
    }
    
    for file in uploaded_files:
        try:
            df = pd.read_excel(file)
            
            # Standardize column names (example logic)
            df.columns = df.columns.str.strip().str.replace(' ', '')
            
            # Check for necessary columns
            if not all(col in df.columns for col in expected_cols[file_type]):
                st.warning(f"File {file.name} is missing expected columns for {file_type} data. Skipping.")
                continue

            # Add source info
            df['SourceFile'] = file.name
            df['Date'] = parse_filename_date_to_datetime(file.name)
            
            # Basic type conversion/cleaning
            if file_type == 'production':
                df['StartTime'] = pd.to_datetime(df['StartTime'], errors='coerce')
                df['StopTime'] = pd.to_datetime(df['StopTime'], errors='coerce')
            elif file_type == 'error':
                df['StartTime'] = pd.to_datetime(df['StartTime'], errors='coerce')
                df['StopTime'] = pd.to_datetime(df['StopTime'], errors='coerce')
                # Ensure Duration is numeric
                df['Duration'] = pd.to_numeric(df['Duration'], errors='coerce').fillna(0)
                df['Error'] = df['Error'].astype(str) # Ensure error codes are strings for grouping

            all_data.append(df)
            
        except Exception as e:
            st.error(f"Error processing file {file.name}: {e}")
            
    if all_data:
        combined_df = pd.concat(all_data, ignore_index=True)
        return combined_df
    return pd.DataFrame()

def calculate_metrics(prod_df, err_df, group_cols):
    """
    Calculates key OEE metrics (Availability, Performance, Quality, OE, Line Efficiency) 
    grouped by specified columns.
    """
    if prod_df.empty:
        return pd.DataFrame()

    # 1. Total Planned Production Time (PPT) and Available Time (AT)
    # Assumed logic: AT is given directly in the production data
    
    # 2. Total Ideal Time (IT) and Total Good Product Count (Good_Qty)
    prod_metrics = prod_df.groupby(group_cols).agg(
        Total_Available_Time=('AvailableTime', 'sum'), # T_A (Total Available)
        Total_Ideal_Time=('IdealTime', 'sum'),         # T_I (Total Ideal Run Time)
        Total_Good_Qty=('TotalGood', 'sum'),           # Q_G (Good Quality Count)
        Total_Production_Tons=('ProductionTypeForTon', 'sum'), # Total Tons produced
        # Assuming we need to calculate Run Time (RT)
        Total_Actual_Time=('StartTime', lambda x: (prod_df.loc[x.index, 'StopTime'] - prod_df.loc[x.index, 'StartTime']).dt.total_seconds().sum() / 60) # Total Actual Run Time (minutes)
    ).reset_index()

    # Calculate Total Production Time (PT) and Down Time (DT)
    # This part requires assumptions about how DT is derived. 
    # Standard OEE: DT = AT - RT (or calculated from error logs)
    # Assuming AT is the max time machine was supposed to run (Total Available Time)
    
    prod_metrics['Total_Run_Time'] = prod_metrics['Total_Actual_Time'] # T_R (Actual Run Time) - Simplified

    # --- Metrics Calculation ---
    
    # 1. Availability (A) = Run Time / Available Time
    prod_metrics['Availability(%)'] = np.where(
        prod_metrics['Total_Available_Time'] > 0,
        (prod_metrics['Total_Run_Time'] / prod_metrics['Total_Available_Time']) * 100,
        0
    )

    # 2. Performance (P) = (Ideal Cycle Time * Total Quantity) / Run Time
    # Assuming Ideal Cycle Time is implicitly derived from (Total_Ideal_Time / Total_Good_Qty)
    # Let's use a simplified approach based on your available columns:
    # P = Ideal Time / Actual Run Time
    prod_metrics['Performance(%)'] = np.where(
        prod_metrics['Total_Run_Time'] > 0,
        (prod_metrics['Total_Ideal_Time'] / prod_metrics['Total_Run_Time']) * 100,
        0
    )
    
    # Cap Performance at 100% (or standard OEE definition)
    prod_metrics['Performance(%)'] = prod_metrics['Performance(%)'].clip(upper=100)
    
    # 3. Quality (Q) = Good Quantity / Total Quantity (Simplified)
    # Assuming Total Good Qty is the only measure available, we assume the denominator 
    # (Total Qty) is equal to TotalGood for simplicity or we need a specific rejection column.
    # We will use Quality = 100% for now unless reject data is available.
    prod_metrics['Quality(%)'] = 100 
    
    # 4. OE = A * P * Q (Since Q=100%, OE = A * P)
    prod_metrics['OE(%)'] = (prod_metrics['Availability(%)'] / 100) * (prod_metrics['Performance(%)'] / 100) * 100

    # 5. Line Efficiency (IE) = (Total Good Qty / Max Theoretical Qty) * 100
    # Assuming Max Theoretical Qty is implicitly related to Available Time and Ideal Time.
    # Line Efficiency (IE) = Ideal Run Time / Available Time
    prod_metrics['Line_Efficiency(%)'] = np.where(
        prod_metrics['Total_Available_Time'] > 0,
        (prod_metrics['Total_Ideal_Time'] / prod_metrics['Total_Available_Time']) * 100,
        0
    )
    
    # Cleanup and format for display
    for col in ['Availability(%)', 'Performance(%)', 'Quality(%)', 'OE(%)', 'Line_Efficiency(%)']:
        prod_metrics[col] = prod_metrics[col].round(2)

    return prod_metrics


# --- Navigation ---
def set_page(page_name):
    st.session_state.page = page_name

st.sidebar.title("🏭 OEE Dashboard")
st.sidebar.button("📊 Dashboard", on_click=set_page, args=("Dashboard",))
st.sidebar.button("📈 Trend Analysis", on_click=set_page, args=("Trend Analysis",))
st.sidebar.button("📂 Data Management", on_click=set_page, args=("Data Management",))
st.sidebar.button("📧 Contact Me", on_click=set_page, args=("Contact Me",))

# --- Main Application Logic ---

def Data_Analyzing_Dashboard():
    st.title("📊 داشبورد تحلیل داده‌های تولید")
    st.markdown("---")

    if st.session_state.prod_df.empty:
        st.info("لطفاً فایل‌های تولید و خطای خود را در بخش Data Management بارگذاری کنید.")
        return

    final_prod_df = st.session_state.prod_df.copy()
    final_err_df = st.session_state.err_df.copy()
    
    # --- Filters ---
    with st.expander("فیلترهای داده‌ها", expanded=True):
        col1, col2, col3 = st.columns(3)
        
        # Determine available machine types
        all_machines = final_prod_df['MachineType'].unique().tolist() if 'MachineType' in final_prod_df.columns else []
        selected_machine = col1.selectbox("انتخاب ماشین:", ["All"] + all_machines)

        # Determine min/max dates
        min_date = final_prod_df['Date'].min() if not final_prod_df.empty and 'Date' in final_prod_df.columns else datetime.now().date()
        max_date = final_prod_df['Date'].max() if not final_prod_df.empty and 'Date' in final_prod_df.columns else datetime.now().date()

        date_range = col2.date_input("محدوده تاریخ:", value=(min_date, max_date) if min_date != max_date else (min_date, min_date), min_value=min_date, max_value=max_date)

        # Apply Filters
        prod_df_filtered = final_prod_df.copy()
        err_df_filtered = final_err_df.copy()
        
        if selected_machine != "All":
            prod_df_filtered = prod_df_filtered[prod_df_filtered['MachineType'] == selected_machine].copy()
            if 'MachineType' in err_df_filtered.columns:
                err_df_filtered = err_df_filtered[err_df_filtered['MachineType'] == selected_machine].copy()
            
        if len(date_range) == 2:
            start_date, end_date = date_range[0], date_range[1]
            prod_df_filtered = prod_df_filtered[
                (prod_df_filtered['Date'] >= start_date) & 
                (prod_df_filtered['Date'] <= end_date)
            ].copy()
            
            if 'Date' in err_df_filtered.columns:
                 err_df_filtered = err_df_filtered[
                    (err_df_filtered['Date'] >= start_date) & 
                    (err_df_filtered['Date'] <= end_date)
                ].copy()

    # --- 1. Key Metrics Summary ---
    st.header("خلاصه کلید متغیرهای عملکرد (OEE)")
    
    # Calculate overall metrics
    overall_metrics = calculate_metrics(prod_df_filtered, err_df_filtered, group_cols=[])
    
    if not overall_metrics.empty:
        metric_row = overall_metrics.iloc[0]
        col_met1, col_met2, col_met3, col_met4, col_met5 = st.columns(5)
        
        col_met1.metric("Available Time (Min)", f"{metric_row['Total_Available_Time']:.0f}")
        col_met2.metric("OE (%)", f"{metric_row['OE(%)']:.2f}")
        col_met3.metric("Availability (%)", f"{metric_row['Availability(%)']:.2f}")
        col_met4.metric("Performance (%)", f"{metric_row['Performance(%)']:.2f}")
        col_met5.metric("Line Efficiency (IE) (%)", f"{metric_row['Line_Efficiency(%)']:.2f}")

    st.markdown("---")

    # --- 2. Combined Production Data Table ---
    # **درخواست ۲: حذف ستون افیشنسی از جدول Combined Production Data**
    st.subheader("Combined Production Data from Selected Files (Row-Level Efficiency)")
    df_display = prod_df_filtered.copy()
    
    # حذف ستون Efficiency(%) در صورت وجود
    if 'Efficiency(%)' in df_display.columns:
        df_display = df_display.drop(columns=['Efficiency(%)'], errors='ignore')
        
    st.dataframe(df_display, use_container_width=True)

    st.markdown("---")

    # --- 3. Product Metrics Bar Chart (Replaced) ---
    # **درخواست ۳: جایگزینی نمودار average efficiency by product با بار چارت IE و OE**
    
    # Calculate metrics grouped by Product
    metrics_by_product = calculate_metrics(prod_df_filtered, err_df_filtered, group_cols=['Product', 'ProductionTypeForTon'])

    if not metrics_by_product.empty:
        st.subheader("مقایسه Line Efficiency (IE) و OE بر اساس محصول (Bar Chart)")
        
        fig_product_metrics = px.bar(
            metrics_by_product.sort_values(by='Line_Efficiency(%)', ascending=False),
            x='Product',
            y=['Line_Efficiency(%)', 'OE(%)'],
            title='مقایسه Line Efficiency (IE) و OE بر اساس محصول',
            height=500,
            barmode='group',
            labels={'Line_Efficiency(%)': 'Line Efficiency (IE) (%)', 'OE(%)': 'OE (%)'},
            template="plotly_dark"
        )
        st.plotly_chart(fig_product_metrics, use_container_width=True)

    st.markdown("---")

    # --- 4. Downtime Error Breakdown (New Chart) ---
    # **درخواست ۴: افزودن نمایش خطاهای Down Time**
    if not err_df_filtered.empty and 'Error' in err_df_filtered.columns and 'Duration' in err_df_filtered.columns:
        st.subheader("تجزیه و تحلیل کد خطای توقف (Downtime Error Code Breakdown) - بر حسب دقیقه")
        
        # Aggregate raw error data by code
        error_breakdown = err_df_filtered.groupby('Error')['Duration'].sum().reset_index()
        
        # Ensure 'Error' is treated as a string for grouping and visualization
        error_breakdown['Error Code'] = error_breakdown['Error'].astype(str)
        
        # Filter out rows with zero duration for cleaner chart
        error_breakdown = error_breakdown[error_breakdown['Duration'] > 0].sort_values(by='Duration', ascending=False)

        fig_error = px.bar(
            error_breakdown,
            x='Error Code',
            y='Duration',
            color='Error Code',
            title='مدت زمان کل کدهای خطای توقف و اتلاف (بر حسب دقیقه)',
            labels={'Duration': 'مدت زمان کل (دقیقه)', 'Error Code': 'کد خطا'},
            hover_data={'Duration': ':.1f'},
            height=500,
            template="plotly_dark"
        )
        st.plotly_chart(fig_error, use_container_width=True)
    elif st.session_state.err_files_loaded:
        st.info("هیچ داده خطایی منطبق با فیلترهای ماشین و تاریخ فعلی پیدا نشد.")
    elif not st.session_state.err_files_loaded:
        st.info("لطفاً فایل‌های خطای خود را برای نمایش این نمودار در بخش Data Management بارگذاری کنید.")
    
    # --- 5. Removed Chart ---
    # **درخواست ۱: حذف نمودار 'daily line efficiency and oe trend for machine'**
    # این کدها در اینجا حذف شده‌اند.
    st.markdown("---")

def Trend_Analysis():
    st.title("📈 تحلیل روند")
    st.markdown("---")

    if st.session_state.prod_df.empty:
        st.info("لطفاً فایل‌های تولید خود را در بخش Data Management بارگذاری کنید.")
        return

    final_prod_df = st.session_state.prod_df.copy()
    final_err_df = st.session_state.err_df.copy()

    # --- Filters (similar to Dashboard) ---
    with st.expander("فیلترهای روند", expanded=True):
        col1, col2 = st.columns(2)
        
        all_machines = final_prod_df['MachineType'].unique().tolist() if 'MachineType' in final_prod_df.columns else []
        selected_machine = col1.selectbox("انتخاب ماشین برای تحلیل روند:", ["All"] + all_machines)

        min_date = final_prod_df['Date'].min() if not final_prod_df.empty and 'Date' in final_prod_df.columns else datetime.now().date()
        max_date = final_prod_df['Date'].max() if not final_prod_df.empty and 'Date' in final_prod_df.columns else datetime.now().date()

        date_range = col2.date_input("محدوده تاریخ روند:", value=(min_date, max_date) if min_date != max_date else (min_date, min_date), min_value=min_date, max_value=max_date)

    # --- Apply Filters ---
    prod_df_filtered = final_prod_df.copy()

    if selected_machine != "All":
        prod_df_filtered = prod_df_filtered[prod_df_filtered['MachineType'] == selected_machine].copy()
        
        # --- FIX: Key Error for MachineType ---
        # **رفع خطای KeyError: 'MachineType' در Trend Analysis**
        if 'MachineType' in final_err_df.columns:
            # این خط همان خط ۹۳۸ در Traceback اصلی بود. با بررسی وجود ستون، از خطا جلوگیری می‌شود.
            final_err_df_filtered = final_err_df[
                final_err_df["MachineType"] == selected_machine
            ].copy()
        else:
            final_err_df_filtered = pd.DataFrame() # اگر ستون نبود، دیتافریم خالی ایجاد شود
        # --- END FIX ---
    else:
        final_err_df_filtered = final_err_df.copy()

    if len(date_range) == 2:
        start_date, end_date = date_range[0], date_range[1]
        prod_df_filtered = prod_df_filtered[
            (prod_df_filtered['Date'] >= start_date) & 
            (prod_df_filtered['Date'] <= end_date)
        ].copy()
        
        if 'Date' in final_err_df_filtered.columns:
            final_err_df_filtered = final_err_df_filtered[
                (final_err_df_filtered['Date'] >= start_date) & 
                (final_err_df_filtered['Date'] <= end_date)
            ].copy()

    # --- Daily Trend Calculation ---
    daily_metrics_df = calculate_metrics(prod_df_filtered, final_err_df_filtered, group_cols=['Date'])
    
    if not daily_metrics_df.empty:
        daily_metrics_df = daily_metrics_df.sort_values(by='Date')

        # --- Daily OEE/Availability Trend ---
        st.subheader("روند روزانه OEE، در دسترس بودن و راندمان خط")
        fig_trend = px.line(
            daily_metrics_df,
            x='Date',
            y=['OE(%)', 'Availability(%)', 'Line_Efficiency(%)'],
            title=f"روند روزانه OEE و متریک‌ها برای {selected_machine}",
            labels={'value': 'درصد (%)', 'variable': 'متریک'},
            template="plotly_dark",
            markers=True
        )
        fig_trend.update_layout(hovermode="x unified")
        st.plotly_chart(fig_trend, use_container_width=True)

        st.markdown("---")

        # --- Daily Downtime Trend ---
        if not final_err_df_filtered.empty and 'Duration' in final_err_df_filtered.columns:
            st.subheader("روند روزانه مدت زمان توقف (Downtime) بر حسب دقیقه")
            daily_downtime = final_err_df_filtered.groupby('Date')['Duration'].sum().reset_index()
            daily_downtime = daily_downtime.sort_values(by='Date')

            fig_downtime = px.bar(
                daily_downtime,
                x='Date',
                y='Duration',
                title=f"روند روزانه کل زمان توقف برای {selected_machine}",
                labels={'Duration': 'مدت زمان کل توقف (دقیقه)'},
                template="plotly_dark"
            )
            st.plotly_chart(fig_downtime, use_container_width=True)
        
    else:
        st.warning("داده‌ای برای نمایش روند در محدوده فیلترهای انتخابی پیدا نشد.")


def Data_Management():
    st.title("📂 مدیریت داده و آرشیو")
    st.markdown("---")

    # Placeholder for the file uploader and data management logic
    # Uploader for Production Data
    prod_files = st.file_uploader("بارگذاری فایل‌های اکسل تولید (Production Data)", type=['xlsx'], accept_multiple_files=True, key="prod_uploader")
    if prod_files:
        if st.button("پردازش و بارگذاری داده‌های تولید"):
            with st.spinner("در حال پردازش فایل‌ها..."):
                combined_df = process_uploaded_files(prod_files, 'production')
                if not combined_df.empty:
                    st.session_state.prod_df = combined_df
                    st.session_state.prod_files_loaded = True
                    st.success(f"تعداد {len(combined_df)} رکورد تولید با موفقیت بارگذاری شد.")
                else:
                    st.warning("فایل‌های تولید فاقد داده معتبر بودند یا فرمت آن‌ها صحیح نبود.")

    st.markdown("---")
    
    # Uploader for Error Data
    err_files = st.file_uploader("بارگذاری فایل‌های اکسل خطا (Error Data)", type=['xlsx'], accept_multiple_files=True, key="err_uploader")
    if err_files:
        if st.button("پردازش و بارگذاری داده‌های خطا"):
            with st.spinner("در حال پردازش فایل‌های خطا..."):
                combined_err_df = process_uploaded_files(err_files, 'error')
                if not combined_err_df.empty:
                    st.session_state.err_df = combined_err_df
                    st.session_state.err_files_loaded = True
                    st.success(f"تعداد {len(combined_err_df)} رکورد خطا با موفقیت بارگذاری شد.")
                else:
                    st.warning("فایل‌های خطا فاقد داده معتبر بودند یا فرمت آن‌ها صحیح نبود.")

    st.markdown("---")
    
    st.subheader("وضعیت داده‌های فعلی")
    col_d1, col_d2 = st.columns(2)
    col_d1.metric("تعداد رکورد تولید", len(st.session_state.prod_df))
    col_d2.metric("تعداد رکورد خطا", len(st.session_state.err_df))
    
    # Placeholder for archiving and deletion logic (using Supabase config)
    st.markdown("---")
    st.subheader("آرشیو (Supabase)")
    
    # New logic to list and display archived files
    if st.button("تازه‌سازی و نمایش لیست آرشیو", key="refresh_archive"):
        with st.spinner("در حال بارگذاری لیست فایل‌ها..."):
            st.session_state.archived_files = list_archived_files()
        
    if st.session_state.archived_files:
        st.success(f"تعداد {len(st.session_state.archived_files)} فایل در آرشیو یافت شد.")
        # Displaying the list of files in a clean dataframe
        df_files = pd.DataFrame({'نام فایل آرشیو شده': st.session_state.archived_files})
        st.dataframe(df_files, use_container_width=True, height=200)
    else:
        st.info("هیچ فایلی در آرشیو یافت نشد. برای به‌روزرسانی لیست، دکمه تازه‌سازی را بزنید.")

def Contact_Me():
    st.subheader("ارتباط با محمد اسدالله‌زاده")
    st.markdown("---")
    st.markdown("""
    در دنیای پرشتاب امروز، با پیشرفت‌های سریع در فناوری، هوش مصنوعی دیگر یک گزینه نیست—بلکه یک ضرورت است. استفاده از هوش مصنوعی می‌تواند به طور قابل توجهی عملکرد را افزایش داده، خطاهای انسانی را به حداقل برساند و جریان کار را ساده‌تر کند. تکیه صرف به روش‌های سنتی اغلب منجر به اتلاف زمان و تلاش می‌شود، بدون اینکه کارایی مورد نظرمان را به دست آوریم.

    برای پرداختن به این موضوع، من شروع به ساخت پلتفرمی کرده‌ام که اتوماسیون را با هوشمندی ترکیب می‌کند. با انگیزه اشتیاقم به پایتون—با وجود اینکه هنوز در حال یادگیری هستم—و علاقه عمیق به ایجاد راهکارهای فنی منضبط و مبتنی بر داده، توسعه این وب‌سایت مبتنی بر Streamlit را برای تحلیل عملکرد روزانه تولید آغاز کردم.

    در حالی که مهارت‌های پایتون من هنوز در حال رشد هستند، صبر، تعهد و کنجکاوی را به کار گرفته‌ام. در طول فرآیند، ابزارهایی مانند **Gemini AI** در کمک به من برای اشکال‌زدایی، پالایش استراتژی‌ها و به ثمر رساندن این ایده بسیار مؤثر بودند. صادقانه بگویم، بدون کمک هوش مصنوعی، رسیدن به این نقطه بسیار دشوارتر می‌بود.

    با این حال، من متعهد به بهبود هستم—هم در کدنویسی و هم در طراحی سیستم. من از بازخورد، پیشنهادات یا هر راهنمایی شما برای کمک به ارتقای بیشتر این پلتفرم استقبال می‌کنم.

    📧 ایمیل: m.asdz@yahoo.com
    🔗 لینکدین: Mohammad Asdollahzadeh

    از بازدید شما متشکرم و از حمایت شما صمیمانه قدردانی می‌کنم.

    با احترام،
    محمد اسدالله‌زاده
    """)


# --- Page Routing ---
if st.session_state.page == "Dashboard":
    Data_Analyzing_Dashboard()
elif st.session_state.page == "Trend Analysis":
    Trend_Analysis()
elif st.session_state.page == "Data Management":
    Data_Management()
elif st.session_state.page == "Contact Me":
    Contact_Me()
