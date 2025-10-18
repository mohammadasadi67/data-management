import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime
import re
import numpy as np

# ==============================================================================
# 0. تنظیمات و متغیرهای سراسری (Configuration & Global Variables)
#    **کلید Service Role و URL شما مستقیماً اینجا تعریف شده‌اند**
# ==============================================================================

st.set_page_config(
    page_title="مدیریت و تحلیل داده‌های تولیدی",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Supabase Configuration (مقادیر نهایی و معتبر شما) ---
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co" 
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

ARCHIVE_DELETE_PASSWORD = "beautifulmind" # رمز عبور حذف آرشیو شما

@st.cache_resource
def get_supabase_client():
    """ایجاد و کش کردن اتصال به Supabase."""
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        return supabase
    except Exception as e:
        # اگر خطا ۴۰۱ یا PGRST106 اینجا نمایش داده شود، مشکل از تنظیمات Supabase است نه کد
        st.error(f"خطا در اتصال به پایگاه داده Supabase: {e}")
        st.stop()

supabase = get_supabase_client()

# ==============================================================================
# ۱. توابع کمکی (Helper Functions)
# ==============================================================================

def standardize_columns(df):
    """
    استانداردسازی نام ستون‌ها (حل مشکل KeyError): حذف فاصله‌ها، تبدیل به Title Case.
    """
    new_columns = {}
    for col in df.columns:
        cleaned_col = re.sub(r'[^\w\s-]', '', str(col)).strip()
        standard_col = cleaned_col.replace(' ', '').title()
        new_columns[col] = standard_col
    return df.rename(columns=new_columns)

def parse_filename_date_to_datetime(filename):
    """استخراج تاریخ از نام فایل."""
    match = re.search(r'(\d{8})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%d%m%Y').date()
        except ValueError:
            return None
    return None

def load_data_from_supabase(table_name="production_data"):
    """بارگذاری تمام داده‌ها از Supabase با کش."""
    @st.cache_data(ttl=600) 
    def fetch_data():
        try:
            response = supabase.table(table_name).select("*").execute()
            df = pd.DataFrame(response.data)
            
            if df.empty:
                return df
                
            if 'Date' in df.columns:
                df['Date'] = pd.to_datetime(df['Date'], errors='coerce').dt.date
            
            return standardize_columns(df) 
        except Exception as e:
            st.error(f"خطا در بارگذاری داده‌ها از Supabase: {e}")
            return pd.DataFrame()
    return fetch_data()


def process_uploaded_excel(uploaded_file, selected_sheet_name):
    """
    پردازش فایل اکسل آپلود شده و استخراج داده‌های Production و Error.
    """
    try:
        df_raw_sheet = pd.read_excel(uploaded_file, sheet_name=selected_sheet_name, header=None)
        
        # --- استخراج داده‌های Production (بازه D4:P9) ---
        data_prod = df_raw_sheet.iloc[3:9, 3:16].copy()
        headers_prod = df_raw_sheet.iloc[2, 3:16].tolist()
        data_prod.columns = headers_prod
        df_prod = data_prod.melt(ignore_index=False, var_name='ProductionTypeForTon', value_name='ProductionValue').dropna(subset=['ProductionValue'])
        
        
        # --- استخراج داده‌های Error (بازه D13:P15) ---
        data_err = df_raw_sheet.iloc[12:15, 3:16].copy()
        headers_err = df_raw_sheet.iloc[11, 3:16].tolist()
        data_err.columns = headers_err
        df_err = data_err.melt(ignore_index=False, var_name='MachineType', value_name='ErrorDuration').dropna(subset=['ErrorDuration'])


        # --- ترکیب داده‌ها و اطلاعات اولیه ---
        filename = uploaded_file.name
        file_date = parse_filename_date_to_datetime(filename)
        shift = df_raw_sheet.iloc[1, 1].strip() if not pd.isna(df_raw_sheet.iloc[1, 1]) else 'Unknown'
        
        # اضافه کردن ستون‌های Metadata و استانداردسازی
        df_prod['Date'] = file_date
        df_prod['Shift'] = shift
        df_prod['Filename'] = filename
        df_prod = standardize_columns(df_prod).reset_index(drop=True)

        df_err['Date'] = file_date
        df_err['Shift'] = shift
        df_err['Filename'] = filename
        df_err = standardize_columns(df_err).reset_index(drop=True)

        return df_prod, df_err

    except Exception as e:
        st.error(
            f"""
            ❌ خطا در پردازش فایل اکسل '{uploaded_file.name}' (شیت: {selected_sheet_name}):
            ساختار شیت اکسل مطابقت ندارد. (جزئیات خطا: {e})
            """
        )
        return pd.DataFrame(), pd.DataFrame()


def upload_to_supabase(df, table_name):
    """آپلود DataFrame به Supabase."""
    if df.empty:
        st.warning("داده‌ای برای آپلود وجود ندارد.")
        return False
        
    records = df.to_dict('records')
    try:
        supabase.table(table_name).insert(records).execute()
        return True
    except Exception as e:
        st.error(f"❌ خطا در آپلود به جدول '{table_name}': {e}")
        return False


# ==============================================================================
# ۲. ساختار رابط کاربری (UI Structure)
# ==============================================================================

# ستون کناری (Sidebar)
with st.sidebar:
    st.image("https://upload.wikimedia.org/wikipedia/commons/1/10/Streamlit_logo.png", width=50) 
    st.title("منوی مدیریت داده")
    st.markdown("---")
    
    if 'page' not in st.session_state:
        st.session_state.page = "Upload"
        
    if st.button("⬆️ بارگذاری فایل‌ها", use_container_width=True):
        st.session_state.page = "Upload"
    if st.button("📈 داشبورد و تحلیل", use_container_width=True):
        st.session_state.page = "Analysis"
    if st.button("🗄️ مدیریت آرشیو", use_container_width=True):
        st.session_state.page = "Archive"

    st.markdown("---")
    # توضیحات شما از فایل test.txt در یک Expander زیبا
    with st.expander("درباره پلتفرم و توسعه‌دهنده", expanded=False):
        st.markdown(
            """
            در دنیای پیشرفته امروز، هوش مصنوعی دیگر یک گزینه نیست، بلکه یک ضرورت است. 
            من برای تحلیل عملکرد تولید روزانه، با علاقه به پایتون، این پلتفرم مبتنی بر Streamlit را توسعه دادم.
            اگرچه مهارت‌های کدنویسی من در حال رشد است، اما با تعهد و کنجکاوی کار می‌کنم. 
            از حمایت و بازخوردهای شما برای بهبود این پلتفرم استقبال می‌کنم.
            
            📧 **ایمیل:** m.asdz@yahoo.com
            """
        )


# ==============================================================================
# ۳. منطق صفحات (Page Logic)
# ==============================================================================

if st.session_state.page == "Upload":
    st.header("⬆️ بارگذاری و پردازش داده‌های تولیدی")
    st.info("لطفاً فایل‌های اکسل را با فرمت **ddmmyyyy** در نام فایل بارگذاری کنید.")
    st.markdown("---")
    
    col1, col2 = st.columns([1, 2])

    with col1:
        uploaded_files = st.file_uploader(
            "فایل‌های اکسل (Daily Production) را اینجا آپلود کنید",
            type=["xlsx"],
            accept_multiple_files=True
        )
        sheet_name = st.text_input("نام شیت (Sheet Name) حاوی داده‌ها:", value="daily")
        upload_button = st.button("شروع آپلود به Supabase", use_container_width=True, type="primary")

    if upload_button and uploaded_files:
        st.subheader("نتایج پردازش")
        st.cache_data.clear() 

        total_files = len(uploaded_files)
        success_count = 0
        
        with st.status("در حال پردازش و آپلود فایل‌ها...", expanded=True) as status:
            for i, file in enumerate(uploaded_files):
                st.write(f"({i+1}/{total_files}) پردازش فایل: **{file.name}**")
                
                df_prod, df_err = process_uploaded_excel(file, sheet_name)
                
                if df_prod.empty and df_err.empty:
                    st.warning(f"⚠️ فایل **{file.name}** پردازش نشد یا خالی بود.")
                    continue
                
                upload_prod_success = upload_to_supabase(df_prod, "production_data")
                
                if upload_prod_success: 
                    success_count += 1
                    st.success(f"✅ فایل **{file.name}** با موفقیت آپلود شد.")
                else:
                    st.error(f"❌ خطای آپلود برای فایل **{file.name}**.")

            if success_count == total_files:
                status.update(label="✅ تمام فایل‌ها با موفقیت پردازش و آپلود شدند!", state="complete", expanded=False)
            else:
                status.update(label=f"⚠️ {success_count} از {total_files} فایل آپلود شدند. جزئیات را بررسی کنید.", state="warning", expanded=True)
                
        st.rerun()


elif st.session_state.page == "Analysis":
    st.header("📈 داشبورد و تحلیل عملکرد تولید")
    st.markdown("---")

    df_all = load_data_from_supabase()

    if df_all.empty:
        st.info("داده‌ای برای تحلیل وجود ندارد. لطفاً ابتدا فایل‌ها را بارگذاری کنید.")
    else:
        # نام ستون پس از استانداردسازی Productiontypeforton است
        if 'Productiontypeforton' in df_all.columns and 'Date' in df_all.columns: 
            
            # فیلترها
            col_filt1, col_filt2, col_filt3 = st.columns(3)
            
            with col_filt1:
                min_date = df_all['Date'].min()
                max_date = df_all['Date'].max()
                date_range = st.date_input(
                    "محدوده تاریخ:",
                    value=(min_date, max_date),
                    min_value=min_date,
                    max_value=max_date
                )
                
            with col_filt2:
                all_products = ['All'] + sorted(df_all['Productiontypeforton'].unique().tolist())
                selected_product = st.selectbox("نوع محصول:", all_products)
                
            # فیلتر کردن نهایی
            df_filtered = df_all[
                (df_all['Date'] >= date_range[0]) & 
                (df_all['Date'] <= date_range[1])
            ]
            
            if selected_product != 'All':
                df_filtered = df_filtered[df_filtered['Productiontypeforton'] == selected_product]

            st.markdown("### نمودار تحلیل عملکرد")
            
            # تجمیع داده‌ها برای نمودار
            df_chart = df_filtered.groupby(['Date', 'Productiontypeforton'])['Productionvalue'].sum().reset_index()
            
            if not df_chart.empty:
                # نمودار فوق گرافیکی با Plotly
                fig = px.bar(
                    df_chart, 
                    x='Date', 
                    y='Productionvalue', 
                    color='Productiontypeforton',
                    title='تولید تجمعی بر اساس تاریخ و نوع محصول',
                    labels={'Productionvalue': 'مقدار تولید (تن)', 'Date': 'تاریخ'},
                    height=500,
                    template="plotly_dark" 
                )
                fig.update_layout(xaxis_title="تاریخ", yaxis_title="مقدار تولید (تن)")
                st.plotly_chart(fig, use_container_width=True)
                
                st.markdown("### داده‌های فیلتر شده (جزئیات)")
                st.dataframe(df_filtered, use_container_width=True, hide_index=True)
            else:
                st.warning("داده‌ای با فیلترهای اعمال شده پیدا نشد.")
        else:
            st.warning("ستون‌های لازم (Productiontypeforton یا Date) در داده‌های Supabase شما وجود ندارد. لطفاً داده‌های اکسل جدید آپلود کنید.")


elif st.session_state.page == "Archive":
    st.header("🗄️ مدیریت و حذف داده‌های آرشیو")
    st.markdown("---")
    
    st.warning("⚠️ این بخش به شما اجازه می‌دهد تا تمام داده‌های یک جدول را حذف کنید. این عمل غیرقابل بازگشت است.")

    table_to_delete = st.selectbox(
        "جدول مورد نظر برای حذف داده‌ها:",
        ["production_data", "error_data"],
        key="archive_table_select"
    )
    
    delete_password = st.text_input("رمز عبور حذف:", type="password")
    
    if st.button(f"🔥 حذف تمام داده‌های جدول '{table_to_delete}'", type="danger", use_container_width=True):
        if delete_password == ARCHIVE_DELETE_PASSWORD:
            try:
                supabase.table(table_to_delete).delete().neq('id', '0').execute() 
                st.cache_data.clear() 
                st.success(f"✅ تمام داده‌های جدول **{table_to_delete}** با موفقیت حذف شدند.")
            except Exception as e:
                st.error(f"❌ خطای حذف: {e}")
        else:
            st.error("رمز عبور حذف اشتباه است.")
