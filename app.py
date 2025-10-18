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
st.set_page_config(layout="wide", page_title="OEE & Production Data Analytics System", initial_sidebar_state="expanded")
st.title("🧠 سیستم تحلیل هوشمند عملکرد تولید (OEE)")

# ------------------------------------------------------------------------------
# --- ۱. تنظیمات اتصال و متغیرهای سراسری ---
# ------------------------------------------------------------------------------

# --- Supabase Configuration (تایید شده) ---
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

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
# --- ۲. توابع کمکی اصلی و محاسبات (بدون تغییر منطق) ---
# ------------------------------------------------------------------------------

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
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d%m%Y').date()
        except ValueError:
            return None
    return None

def standardize_dataframe_for_oee(df, type='prod'):
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
    try:
        response = supabase.table(table_name).select("*").execute()
        data = response.data
        if not data:
            return pd.DataFrame()
        
        df = pd.DataFrame(data)
        
        date_col_in_db = None
        if 'date' in df.columns:
            date_col_in_db = 'date'
        elif 'Date' in df.columns: 
            date_col_in_db = 'Date'
            
        if date_col_in_db:
            df['Date'] = pd.to_datetime(df[date_col_in_db]).dt.date
            if date_col_in_db == 'date': 
                df.drop(columns=['date'], inplace=True, errors='ignore')
            
        if 'Date' in df.columns:
            df = df.sort_values(by='Date', ascending=True).reset_index(drop=True)

        for col in ['Duration', 'PackQty', 'Waste', 'Ton', 'Capacity', 'Manpower']:
            col_lower = col.lower()
            if col_lower in df.columns: 
                df[col] = pd.to_numeric(df[col_lower], errors='coerce').fillna(0)
            elif col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)
        
        return df

    except Exception as e:
        return pd.DataFrame()

def insert_to_db(df, table_name):
    if df.empty:
        return True
    
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
# --- ۳. منطق اصلی برنامه و ناوبری (بازسازی شده) ---
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

# --- ناوبری اصلی برنامه (منوی جامع) ---

if 'page' not in st.session_state:
    st.session_state.page = "Dashboard & KPIs" 

st.sidebar.header("منوی برنامه")
# منوی کامل شامل تمامی بخش‌های تحلیل و مدیریتی
page_options = ["📊 Dashboard & KPIs", "📈 Advanced Trend Analysis", "⬆️ Upload Data", "🗄️ Data Archive", "📧 Contact Me"] 
try:
    selected_page_index = page_options.index(st.session_state.page)
except ValueError:
    selected_page_index = 0 # Default to Dashboard if state is invalid

selected_page = st.sidebar.radio("برو به:", options=page_options, index=selected_page_index, key="sidebar_radio")

if selected_page != st.session_state.page:
    st.session_state.page = selected_page
    st.rerun()

# ------------------------------------------------------------------------------
# --- ۴. پیاده‌سازی صفحات ---
# ------------------------------------------------------------------------------

# --- صفحه بارگذاری داده ---
if st.session_state.page == "⬆️ Upload Data":
    st.header("⬆️ بارگذاری فایل‌های اکسل و درج در پایگاه داده")

    sheet_name_to_process = st.text_input(
        "نام شیت (Sheet Name) حاوی داده‌ها:",
        value="daily", 
        help="نام دقیق شیتی که داده‌های تولید و خطا در آن قرار دارند."
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

# --- صفحه آرشیو داده ---
elif st.session_state.page == "🗄️ Data Archive":
    st.header("🗄️ مدیریت و حذف داده‌های آرشیو")
    
    st.error("⚠️ هشدار: این بخش به شما اجازه می‌دهد تا تمام داده‌های یک جدول را حذف کنید. این عمل غیرقابل بازگشت است.")

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
                supabase.table(table_to_delete).delete().neq('id', '0').execute() 
                st.cache_data.clear() 
                st.success(f"✅ تمام داده‌های جدول **{table_to_delete}** با موفقیت حذف شدند.")
                st.rerun()
            except Exception as e:
                st.error(f"❌ خطای حذف: {e}")
        else:
            st.error("رمز عبور حذف اشتباه است.")


# --- صفحه تماس با من ---
elif st.session_state.page == "📧 Contact Me":
    st.header("📧 تماس با توسعه‌دهنده")
    st.markdown("---")
    st.markdown("""
    ### درباره این پلتفرم 💡

    در دنیای امروز با پیشرفت‌های سریع تکنولوژی، هوش مصنوعی (AI) دیگر یک انتخاب نیست، بلکه یک **ضرورت** است. استفاده از هوش مصنوعی می‌تواند به طور چشمگیری عملکرد را افزایش دهد، خطای انسانی را به حداقل برساند و جریان کاری را ساده کند. تکیه صرف به روش‌های سنتی اغلب منجر به هدر رفتن زمان و تلاش می‌شود، بدون آنکه کارایی لازم حاصل شود.

    برای پاسخ به این نیاز، من توسعه پلتفرمی را آغاز کردم که **اتوماسیون** را با **هوشمندی** ترکیب می‌کند. با الهام از علاقه‌ام به پایتون (با وجود اینکه هنوز در حال یادگیری هستم) و اشتیاق عمیق برای ایجاد راه‌حل‌های فنی منظم و مبتنی بر داده، توسعه این وب‌سایت مبتنی بر Streamlit را برای تحلیل روزانه عملکرد تولید آغاز کردم.

    در طول این فرآیند، ابزارهایی مانند **Gemini AI** در اشکال‌زدایی، پالایش استراتژی‌ها و به حقیقت پیوستن این ایده بسیار مؤثر بودند. صادقانه بگویم، بدون کمک هوش مصنوعی، رسیدن به این نقطه بسیار دشوارتر می‌شد.

    من متعهد به بهبود هستم—هم در کدنویسی و هم در طراحی سیستم. از بازخورد، پیشنهادات، یا هر گونه راهنمایی برای بهبود بیشتر این پلتفرم استقبال می‌کنم.

    ---

    **اطلاعات تماس:**

    📧 **ایمیل:** m.asdz@yahoo.com  
    🔗 **لینکدین:** [Mohammad Asdollahzadeh](https://www.linkedin.com/in/mohammad-asdollahzadeh)

    با تشکر از بازدید شما، و از حمایت شما صمیمانه قدردانی می‌کنم.

    با احترام،
    **محمد اسدالله زاده**
    """)


# --- صفحه تحلیل روند (پیشرفته) ---
elif st.session_state.page == "📈 Advanced Trend Analysis":
    st.header("📈 تحلیل روند پیشرفته (Trend Analysis)")

    df_prod_all = load_data_from_supabase_tables(PROD_TABLE)
    df_err_all = load_data_from_supabase_tables(ERROR_TABLE)

    if df_prod_all.empty:
        st.warning("داده‌ای برای تحلیل روند وجود ندارد. لطفاً ابتدا داده‌ها را بارگذاری کنید.")
    else:
        # Aggregate data by Date for Trend Analysis (Comprehensive)
        daily_summary = df_prod_all.groupby("Date").agg(
            TotalPackQty=('PackQty', 'sum'),
            TotalWaste=('Waste', 'sum'),
            TotalDuration=('Duration', 'sum'), # in hours
            AvgCapacity=('Capacity', 'mean')
        ).reset_index()
        
        daily_errors = df_err_all.groupby("Date")["Duration"].sum().reset_index().rename(columns={"Duration": "TotalDowntime"}) # in minutes
        daily_df = pd.merge(daily_summary, daily_errors, on="Date", how="left").fillna(0)
        
        # OEE/KPI Calculation on Daily Data
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
        
        # --- Display Trend Charts ---
        st.subheader("روند کلی OEE و اجزای آن")
        fig_trend = px.line(daily_df, x="Date", y=["OEE", "Availability", "Performance", "Quality"], 
                            title="روند روزانه OEE، دسترسی، عملکرد و کیفیت",
                            labels={"value": "درصد (%)", "Date": "تاریخ"},
                            template="plotly_dark") # استفاده از تم تیره برای ظاهر حرفه‌ای‌تر
        fig_trend.update_layout(legend_title_text='شاخص', height=500)
        st.plotly_chart(fig_trend, use_container_width=True)
        
        st.markdown("---")
        
        st.subheader("روند روزانه تولید (بسته) و توقف (Downtime)")
        
        fig_dual = go.Figure()

        fig_dual.add_trace(go.Bar(
            x=daily_df['Date'],
            y=daily_df['TotalGoodQty'],
            name='تولید خالص (بسته)',
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
            title='تحلیل دوگانه روند تولید و توقف',
            template="plotly_dark",
            yaxis=dict(
                title='تولید خالص (بسته)',
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


# --- صفحه داشبورد و شاخص‌های کلیدی (جامع) ---
elif st.session_state.page == "📊 Dashboard & KPIs":
    st.header("📊 داشبورد تحلیل جامع عملکرد")
    
    # --- Connection Status Check ---
    try:
        prod_count_response = supabase.table(PROD_TABLE).select("*", count='exact').limit(0).execute() 
        err_count_response = supabase.table(ERROR_TABLE).select("*", count='exact').limit(0).execute() 
        
        prod_count = prod_count_response.count
        err_count = err_count_response.count
        
        st.success(f"✅ اتصال به Supabase برقرار است. (داده‌های تولید: {prod_count} سطر، داده‌های خطا: {err_count} سطر)")
    except Exception as e:
        st.error(f"❌ خطای حیاتی: اتصال به Supabase قطع است. لطفاً وضعیت API Key و جداول را بررسی کنید. (جزئیات خطا: {e})")
        st.stop()
    st.markdown("---")
    
    df_prod_all = load_data_from_supabase_tables(PROD_TABLE)
    df_err_all = load_data_from_supabase_tables(ERROR_TABLE)

    if df_prod_all.empty:
        st.warning("داده‌ای برای تحلیل وجود ندارد. لطفاً ابتدا از بخش 'بارگذاری فایل‌ها'، داده‌ها را درج کنید.")
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

        unique_machines = ['Total Production'] + sorted(df_prod_filtered["ProductTypeForTon"].unique().tolist())
        with col_filters:
            selected_machine = st.selectbox("انتخاب خط تولید:", unique_machines)

        if selected_machine != 'Total Production':
            df_prod_filtered = df_prod_filtered[
                df_prod_filtered["ProductTypeForTon"] == selected_machine
            ].copy()
            # فیلتر کردن خطاهای مربوط به ماشین انتخاب شده (فرض بر این است که نام ماشین در Error Data به حروف کوچک ذخیره می‌شود)
            df_err_filtered = df_err_filtered[
                df_err_filtered["machinetype"].str.contains(selected_machine.lower(), case=False, na=False)
            ].copy()


        # --- OEE Calculations ---
        oee_pct, line_efficiency_pct, availability_pct, performance_pct, quality_pct, \
            total_down_time_min, total_good_qty, total_pack_qty = calculate_oee_metrics(df_prod_filtered, df_err_filtered)

        # ----------------------------------------------------------------------------------
        # --- نمایش KPIs (فوق گرافیکی و حرفه‌ای) ---
        # ----------------------------------------------------------------------------------
        st.markdown("### شاخص‌های کلیدی عملکرد (KPIs)")
        col1, col2, col3, col4, col5 = st.columns(5)
        
        def display_metric_pro(col, label, value, color_threshold=85):
            # ظاهر حرفه‌ای‌تر با استفاده از رنگ‌های تیره و خطوط باریک
            color = '#2ECC71' if value >= color_threshold else ('#FFC300' if value >= (color_threshold-15) else '#FF4B4B')
            col.markdown(f"""
            <div style='
                border-left: 5px solid {color}; 
                border-radius: 4px; 
                padding: 10px; 
                text-align: right; 
                background-color: #1E1E1E;
                box-shadow: 2px 2px 5px rgba(0,0,0,0.2);
            '>
                <p style='font-size: 13px; margin-bottom: 5px; color: #aaa; text-align: left;'>{label}</p>
                <h2 style='margin-top: 0; color: {color}; font-size: 28px; text-align: left;'>{value:,.1f} %</h2>
            </div>
            """, unsafe_allow_html=True)

        # نمایش OEE و اجزای آن
        display_metric_pro(col1, "OEE (اثربخشی کلی)", oee_pct, color_threshold=75)
        display_metric_pro(col2, "Availability (دسترسی)", availability_pct, color_threshold=85)
        display_metric_pro(col3, "Performance (عملکرد)", performance_pct, color_threshold=85)
        display_metric_pro(col4, "Quality (کیفیت)", quality_pct, color_threshold=95)
        display_metric_pro(col5, "Line Efficiency (راندمان خط)", line_efficiency_pct, color_threshold=70)
        
        st.markdown("<br>", unsafe_allow_html=True)

        col_prod, col_downtime = st.columns(2)
        
        with col_prod:
            st.metric("تولید خالص (بسته)", f"{total_good_qty:,.0f} بسته")
        with col_downtime:
            st.metric("توقف کل (Downtime)", f"{total_down_time_min:,.0f} دقیقه")
        
        st.markdown("---")
        
        # ----------------------------------------------------------------------------------
        # --- بخش هوشمند: بینش‌های کلیدی (Intelligent Insights) ---
        # ----------------------------------------------------------------------------------
        st.subheader("💡 بینش‌های هوشمند (Key Insights)")
        
        if total_down_time_min > 0 and availability_pct < 85:
            st.warning(f"دسترسی خط (Availability) تنها **{availability_pct:.1f}%** است. **{total_down_time_min:,.0f} دقیقه** توقف ثبت شده است. تمرکز بر کاهش توقف ضروری است.")
        elif performance_pct < 85:
            st.info(f"عملکرد (Performance) خط **{performance_pct:.1f}%** است. بررسی سرعت‌های تولید (Capacity) و زمان‌های سیکل برای بهبود کارایی الزامی است.")
        else:
            st.success("عملکرد کلی خط در وضعیت خوبی قرار دارد. برای حفظ این روند، کیفیت (Quality) را زیر نظر داشته باشید.")

        st.markdown("---")

        # ----------------------------------------------------------------------------------
        # --- نمودارهای تحلیل جامع (Everything possible) ---
        # ----------------------------------------------------------------------------------
        
        col_charts1, col_charts2 = st.columns(2)
        
        with col_charts1:
            if not df_err_filtered.empty:
                st.subheader("۱۰ مورد برتر دلایل توقف (Parity of Loss)")
                
                # گروه‌بندی بر اساس خطا و فیلتر کردن
                top_errors = df_err_filtered.groupby("error")["duration"].sum().reset_index()
                top_errors = top_errors.sort_values(by="duration", ascending=False).head(10)

                # نمودار Bar برای Downtime (فوق گرافیکی)
                fig_err = px.bar(top_errors, x="error", y="duration",
                                 title="تحلیل پارِتو: دلایل توقف (بر حسب دقیقه)",
                                 labels={"duration": "مدت زمان (دقیقه)", "error": "دلیل توقف"},
                                 color="duration",
                                 color_continuous_scale=px.colors.sequential.Plotly3,
                                 template="plotly_dark")
                fig_err.update_traces(texttemplate='%{y:.1f}', textposition='outside')
                st.plotly_chart(fig_err, use_container_width=True)
            else:
                st.warning("داده‌های خطا برای نمایش دلایل توقف یافت نشد.")

        with col_charts2:
            st.subheader("توزیع تولید (Ton) بر اساس محصول")
            total_ton_per_product = df_prod_filtered.groupby("producttypeforton")["ton"].sum().reset_index()
            total_ton_per_product = total_ton_per_product.sort_values(by="ton", ascending=False)
            
            # نمودار Treemap برای سهم تولید (فوق گرافیکی)
            fig_ton = px.treemap(total_ton_per_product, path=[px.Constant("Total Production"), 'producttypeforton'], values="ton", 
                                 title="سهم هر محصول در تولید کل (بر حسب تناژ)",
                                 color="ton", 
                                 color_continuous_scale=px.colors.sequential.Teal,
                                 template="plotly_dark")
            fig_ton.update_layout(margin=dict(t=50, l=25, r=25, b=25))
            st.plotly_chart(fig_ton, use_container_width=True)
