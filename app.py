import streamlit as st
import pandas as pd
import plotly.express as px
from io import BytesIO
from supabase import create_client, Client
import base64
from datetime import datetime, timedelta, time as datetime_time
import re
import time
import numpy as np  # Import numpy for numerical operations like np.where

# ==============================
# Page & Theme (Light Mode)
# ==============================
st.set_page_config(layout="wide", page_title="Production & Error Dashboard (Light)", page_icon="☀️")

# Plotly light theme
px.defaults.template = "plotly_white"

# Light UI styling
st.markdown(
    """
    <style>
        .stApp { background-color: #FFFFFF; color: #111111; font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, Helvetica Neue, Arial; }
        .block-container { max-width: 1400px; padding-top: 1.5rem; padding-bottom: 2rem; }
        h1,h2,h3,h4 { color: #1E293B; font-weight: 600; }
        .stButton>button { background-color: #007BFF; color: #fff; border-radius: 8px; border: none; padding: 8px 16px; transition: .2s; }
        .stButton>button:hover { background-color: #0056b3; transform: translateY(-1px); }
        .stMetric { background-color: #F8FAFC; border-radius: 12px; padding: 12px; box-shadow: 0 2px 8px rgba(0,0,0,.06); }
        section[data-testid="stSidebar"] { background-color: #F4F6F8; }
        div[data-testid="stProgress"] > div > div > div { background-color: #007BFF; }
        .stAlert { background-color: #F9FAFB !important; color: #111111 !important; border-left: 4px solid #007BFF; }
        table, .dataframe { background-color: #FFFFFF !important; color: #111111 !important; }
    </style>
    """,
    unsafe_allow_html=True
)

# --- Supabase Configuration ---
SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# Initialize Supabase client globally
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"

# --- Helper Functions ---

def parse_filename_date_to_datetime(filename):
    """
    Extracts ddmmyyyy from filename and converts it to a datetime.date object.
    Returns datetime.date.today() if extraction fails or date is invalid.
    """
    try:
        date_str_match = re.search(r'(\d{8})', filename)
        if date_str_match:
            date_str_part = date_str_match.group(1)
            if len(date_str_part) == 8 and date_str_part.isdigit():
                day = int(date_str_part[0:2])
                month = int(date_str_part[2:4])
                year = int(date_str_part[4:8])

                # Basic validation for date components
                if not (1 <= month <= 12 and 1 <= day <= 31 and year >= 2000 and year <= datetime.now().year + 5):
                    raise ValueError("Invalid date components")

                return datetime(year, month, day).date()
    except (ValueError, TypeError):
        pass  # Fall through to return today's date if any error occurs

    return datetime.now().date()  # Default to today's date


def upload_to_supabase(files_list):
    """
    Uploads a list of files directly to the root of the 'uploads' bucket.
    It first attempts to remove any existing file with the same name to ensure overwrite.
    """
    uploaded_count = 0
    total_files = len(files_list)
    if total_files == 0:
        st.info("No files selected for upload.")
        return

    progress_bar = st.progress(0, text="Uploading files...")

    for i, file in enumerate(files_list):
        file_path_in_supabase = file.name
        try:
            # Attempt to remove existing file to ensure overwrite
            try:
                supabase.storage.from_("uploads").remove([file_path_in_supabase])
            except Exception as e:
                error_message = str(e).lower()
                if "not_found" not in error_message and "resource not found" not in error_message:
                    st.warning(
                        f"Warning: Could not remove existing file '{file.name}' (might not exist or permission issue): {e}")

            response = supabase.storage.from_("uploads").upload(
                file_path_in_supabase,
                file.getvalue(),
                {"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
            )

            if isinstance(response, dict) and 'error' in response and response['error']:
                st.error(
                    f"Supabase upload of '{file.name}' returned an error: {response['error'].get('message', 'Unknown error')}")
            else:
                uploaded_count += 1
                progress_bar.progress((i + 1) / total_files, text=f"Uploading '{file.name}' ({i + 1}/{total_files})...")

        except Exception as upload_e:
            st.error(f"Error during upload of '{file.name}' to Supabase: {upload_e}")

    progress_bar.empty()
    if uploaded_count > 0:
        st.success(f"Successfully uploaded {uploaded_count} of {total_files} files!")
        get_all_supabase_files.clear()  # Clear cache to force refetch
        st.rerun()
    else:
        st.error("No files were successfully uploaded.")


@st.cache_data(ttl=3600, show_spinner="Fetching file list from Supabase...")
def get_all_supabase_files():
    """
    Fetches all .xlsx files directly from the root of Supabase storage,
    parses their dates, and caches the result.
    """
    all_files_info_collected = []

    try:
        items = supabase.storage.from_("uploads").list(path="", options={"limit": 5000, "directories": False})

        if not items:
            return []

        for item in items:
            item_name = item.get('name')
            if item_name and item_name.lower().endswith(".xlsx"):
                file_date = parse_filename_date_to_datetime(item_name)  # Parse date here
                all_files_info_collected.append({
                    'name': item_name,
                    'full_path': item_name,  # full_path is just the name as they are in root
                    'file_date': file_date,  # Add datetime.date object
                    'metadata': item
                })

    except Exception as e:
        st.error(f"Error listing files from root: {e}")
        return []

    return all_files_info_collected


def download_from_supabase(filename):
    """
    Downloads a file from Supabase storage using its filename (as it's at the root).
    Includes a retry mechanism for transient 404 Not Found errors.
    """
    max_retries = 3
    retry_delay_seconds = 0.5

    for attempt in range(max_retries):
        try:
            data = supabase.storage.from_("uploads").download(filename)
            return data
        except Exception as e:
            error_message = str(e)
            if "not_found" in error_message.lower() or (
                "statusCode" in getattr(e, '__dict__', {}) and getattr(e, '__dict__', {}).get('statusCode') == 404):
                time.sleep(retry_delay_seconds)
            else:
                st.error(f"Error downloading file '{filename}' on attempt {attempt + 1}: {e}")
                return None

    st.error(f"Error: Download of file '{filename}' failed after {max_retries} attempts. Object not found.")
    return None


def get_download_link(file_bytes, filename):
    """
    Creates a download link for files.
    """
    b64 = base64.b64encode(file_bytes).decode()
    href = f'<a href="data:application/octet-stream;base64,{b64}" download="{filename}">Download {filename}</a>'
    return href


def convert_time(val):
    """
    Converts various time representations (datetime.time, float, int, string)
    into decimal hours (e.g., 7.5 for 07:30 or 730).
    Specifically handles HHMM values like 2600 as 0200.
    """
    if pd.isna(val) or pd.isnull(val):
        return 0

    # Case 1: datetime.time object (often read for HH:MM cells in Excel)
    if isinstance(val, datetime_time):
        return val.hour + val.minute / 60 + val.second / 3600

    # Case 2: datetime.datetime object (less common, but possible if date is also present)
    if isinstance(val, datetime):
        return val.hour + val.minute / 60 + val.second / 3600

    # Case 3: Numeric (float or int)
    if isinstance(val, (int, float)):
        if 0 <= val < 1:
            return val * 24  # Convert fraction of a day to hours
        
        try:
            val_int = int(val)
            h = val_int // 100
            m = val_int % 100
            if 0 <= m < 60:
                return (h % 24) + m / 60
        except ValueError:
            pass

        return float(val)

    # Case 4: String
    if isinstance(val, str):
        s = val.strip()
        if ':' in s:
            try:
                dt_obj = datetime.strptime(s, "%H:%M:%S")
                return dt_obj.hour + dt_obj.minute / 60 + dt_obj.second / 3600
            except ValueError:
                try:
                    dt_obj = datetime.strptime(s, "%H:%M")
                    return dt_obj.hour + dt_obj.minute / 60
                except ValueError:
                    pass
        if s.isdigit():
            try:
                val_int = int(s)
                h = val_int // 100
                m = val_int % 100
                if 0 <= m < 60:
                    return (h % 24) + m / 60
            except ValueError:
                pass
        try:
            return float(s)
        except ValueError:
            pass

    return 0  # Default for unhandled types or errors


def convert_duration_to_minutes(duration_val):
    """
    Converts various Excel duration/time formats (timedelta, datetime.time, datetime.datetime, numeric, string) to total minutes.
    """
    if pd.isna(duration_val) or pd.isnull(duration_val):
        return 0

    if isinstance(duration_val, timedelta):
        return duration_val.total_seconds() / 60

    if isinstance(duration_val, datetime):
        total_seconds = duration_val.hour * 3600 + duration_val.minute * 60 + duration_val.second
        return total_seconds / 60

    if isinstance(duration_val, datetime_time):
        hours = duration_val.hour
        minutes = duration_val.minute
        seconds = duration_val.second
        return hours * 60 + minutes + seconds / 60

    if isinstance(duration_val, (int, float)):
        if 0 <= duration_val < 1:
            return duration_val * 24 * 60
        elif duration_val >= 1:
            if duration_val < 2400:
                try:
                    val_int = int(duration_val)
                    h = val_int // 100
                    m = val_int % 100
                    if 0 <= h < 24 and 0 <= m < 60:
                        return h * 60 + m
                except ValueError:
                    pass
            return float(duration_val) * 60

    if isinstance(duration_val, str):
        duration_str = duration_val.strip()
        if ':' in duration_str:
            try:
                dt_obj = datetime.strptime(duration_str, "%H:%M:%S")
                return dt_obj.hour * 60 + dt_obj.minute + dt_obj.second / 60
            except ValueError:
                try:
                    dt_obj = datetime.strptime(duration_str, "%H:%M")
                    return dt_obj.hour * 60 + dt_obj.minute
                except ValueError:
                    pass
        if duration_str.isdigit():
            try:
                val_int = int(duration_str)
                h = val_int // 100
                m = val_int % 100
                if 0 <= h < 24 and 0 <= m < 60:
                    return h * 60 + m
            except ValueError:
                pass
        try:
            return float(duration_str) * 60
        except ValueError:
            pass

    return 0  # Default to 0 if all conversions fail


def format_production_date_from_filename(filename):
    """
    Extracts ddmmyyyy from filename and formats it as dd "month name" yy.
    """
    try:
        match = re.search(r'(\d{8})', filename)
        if match:
            date_str = match.group(1)
            day = int(date_str[0:2])
            month = int(date_str[2:4])
            year = int(date_str[4:8])

            dt_object = datetime(year, month, day)
            return dt_object.strftime("%d %B %y")
        else:
            return filename
    except (ValueError, TypeError):
        return f"{datetime.now().day} {datetime.now().strftime('%B')} {datetime.now().strftime('%y')}"


def calculate_ton(row):
    product_type_str = str(row["ProductionTypeForTon"]).strip().lower() if pd.notna(row["ProductionTypeForTon"]) else ""
    qty = row["PackQty"]

    grams_per_packet = 0

    if "gasti" in product_type_str:
        grams_per_packet = 90
    elif "200cc" in product_type_str:
        grams_per_packet = 200
    else:
        try:
            numeric_type_val = float(row["ProductionTypeForTon"])
            if numeric_type_val == 200:
                grams_per_packet = 200
        except (ValueError, TypeError):
            pass

    if grams_per_packet == 0:
        if "125" in product_type_str:
            grams_per_packet = 125
        else:
            try:
                numeric_type_val = float(row["ProductionTypeForTon"])
                if numeric_type_val == 125:
                    grams_per_packet = 125
            except (ValueError, TypeError):
                pass

    if grams_per_packet == 0:
        if "1000cc" in product_type_str:
            grams_per_packet = 1000
        else:
            try:
                numeric_type_val = float(row["ProductionTypeForTon"])
                if str(int(numeric_type_val)).startswith('1000'):
                    grams_per_packet = 1000
            except (ValueError, TypeError):
                pass

    if grams_per_packet == 0:
        grams_per_packet = 1000  # Default if no specific type is matched

    calculated_ton = (qty * grams_per_packet) / 1_000_000
    return calculated_ton


def determine_machine_type(name_string):
    s = str(name_string).strip()
    s_lower = s.lower()

    if "gasti" in s_lower:
        return "GASTI"
    elif "200cc" in s_lower or s_lower == "200":
        return "200cc"
    elif "125" in s_lower or s_lower == "125":
        return "125"
    elif "1000cc" in s_lower or s_lower == "1000":
        return "1000cc"

    return "Unknown Machine"


def read_production_data(df_raw_sheet, uploaded_file_name, selected_sheet_name, file_date_obj):
    """
    Reads production data from the Excel sheet.
    Accepts file_date_obj (datetime.date) to assign to each row.
    UPDATED: Calculate Target_Hour using NominalSpeed (Capacity).
    """
    try:
        row2_headers = df_raw_sheet.iloc[1, 3:16].fillna('').astype(str).tolist()
        row3_headers = df_raw_sheet.iloc[2, 3:16].fillna('').astype(str).tolist()

        combined_headers = []
        for r2, r3 in zip(row2_headers, row3_headers):
            if r3.strip() and r3.strip() != 'nan':
                combined_headers.append(r3.strip())
            elif r2.strip() and r2.strip() != 'nan':
                combined_headers.append(r2.strip())
            else:
                combined_headers.append("")

        headers = [h if h else f"Unnamed_Col_{i}" for i, h in enumerate(combined_headers)]

    except IndexError as e:
        st.error(
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Production data headers not found in range D2:P3 of your Excel sheet. (Error: {e}) Please check the sheet format.")
        return pd.DataFrame()

    data = df_raw_sheet.iloc[3:9, 3:16].copy()

    if len(headers) == data.shape[1]:
        data.columns = headers
    else:
        st.error(
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Number of columns in production section does not match headers. Expected {len(headers)} columns, but {data.shape[1]} found.")
        return pd.DataFrame()

    rename_map = {
        "start": "Start",
        "finish": "End",
        "time": "Duration_Original",
        "production title": "Product",
        "cap": "Capacity",  # Nominal speed
        "manpower": "Manpower",
        "quanity": "PackQty",
        "date": "ProdDate_Original",
        "waste": "Waste"
    }

    actual_rename_map = {k: v for k, v in rename_map.items() if k in data.columns}
    data = data.rename(columns=actual_rename_map)

    data["Date"] = file_date_obj 

    determined_machine_type_for_sheet = determine_machine_type(selected_sheet_name)
    if determined_machine_type_for_sheet == "Unknown Machine":
        determined_machine_type_for_sheet = determine_machine_type(uploaded_file_name)
    data['ProductionTypeForTon'] = determined_machine_type_for_sheet

    required_cols = ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Date", 
                     "Waste", "ProductionTypeForTon"]
    for col in required_cols:
        if col not in data.columns:
            st.warning(
                f"Warning in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Required column '{col}' not found for production section.")
            data[col] = pd.NA
            if col in ["PackQty", "Waste", "Capacity", "Manpower"]:
                data[col] = 0

    if 'Product' in data.columns:
        data["Product"] = data["Product"].fillna('').astype(str).str.strip()
        data["Product"] = data["Product"].str.title()
        data = data[data["Product"] != ''].copy()

    data["StartTime"] = data["Start"].apply(convert_time)
    data["EndTime"] = data["End"].apply(convert_time)

    data['EndTimeAdjusted'] = data.apply(
        lambda row: row['EndTime'] + 24 if row['EndTime'] < row['StartTime'] else row['EndTime'], axis=1)

    data["Duration"] = data["EndTimeAdjusted"] - data["StartTime"]
    data = data.dropna(subset=["Duration"])
    data = data[data["Duration"] != 0]

    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    
    data["NominalSpeed"] = pd.to_numeric(data["Capacity"], errors="coerce").fillna(0)
    data = data.drop(columns=['Capacity'], errors='ignore')
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)

    data["Ton"] = data.apply(calculate_ton, axis=1)

    data['Target_Hour'] = np.where(
        data['NominalSpeed'] > 0,
        data['PackQty'] / data['NominalSpeed'],
        0
    )
    
    data['PotentialProduction'] = data['NominalSpeed'] * data['Duration']
    data['Efficiency(%)'] = np.where(
        data['PotentialProduction'] > 0,
        (data['PackQty'] / data['PotentialProduction']) * 100,
        0
    )

    final_cols = ["Date", "Product", "NominalSpeed", "Manpower", "Duration", "PackQty", "Waste", "Ton",
                  "PotentialProduction", "Efficiency(%)", "Target_Hour", "ProductionTypeForTon"]
    for col in final_cols:
        if col not in data.columns:
            data[col] = 0
    data = data[[col for col in final_cols if col in data.columns]]

    return data


def read_error_data(df_raw_sheet, sheet_name_for_debug="Unknown Sheet", uploaded_file_name_for_debug="Unknown File", file_date_obj=None):
    """
    Reads error data from the Excel sheet.
    NEW LOGIC: Finds the row with 'f12' header, unpivots columns f12 to f100 
    (which contain duration in minutes) into Error and Duration rows.
    """
    try:
        header_row = None
        for r in range(df_raw_sheet.shape[0]):
            if any(str(c).lower().strip().startswith('f12') for c in df_raw_sheet.iloc[r]):
                header_row = r
                break
        
        if header_row is None:
            return pd.DataFrame() 

        error_section_df = df_raw_sheet.iloc[header_row:].copy()
        error_section_df.columns = error_section_df.iloc[0].astype(str).str.lower().str.strip()
        error_section_df = error_section_df[1:].reset_index(drop=True)
        
        error_duration_cols_pattern = [f'f{i}' for i in range(12, 101)] 
        cols_to_melt = [col for col in error_section_df.columns if col in error_duration_cols_pattern]
        
        if not cols_to_melt:
            return pd.DataFrame()

        df_long = error_section_df.melt(
            value_vars=cols_to_melt,
            var_name='RawErrorColumn',
            value_name='Duration'
        )
        
        df_long['Duration'] = pd.to_numeric(df_long['Duration'], errors='coerce').fillna(0)
        df_long = df_long[df_long['Duration'] > 0].copy()
        
        df_long['Error'] = df_long['RawErrorColumn'].str.replace('f', '', regex=False).astype(str).str.strip()
        
        aggregated_errors = df_long.groupby("Error")["Duration"].sum().reset_index()
        aggregated_errors = aggregated_errors[aggregated_errors['Error'].str.isnumeric()].copy()
        
        aggregated_errors['Date'] = file_date_obj
        aggregated_errors['MachineType'] = determine_machine_type(sheet_name_for_debug)

        return aggregated_errors.dropna(subset=['Date'])
    
    except Exception as e:
        st.error(
            f"Error in file '{uploaded_file_name_for_debug}' (Sheet: '{sheet_name_for_debug}'): An unexpected error occurred while processing error data: `{e}`")
        return pd.DataFrame()


def calculate_metrics(prod_df: pd.DataFrame, err_df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """
    Calculates Line Efficiency and OE based on the new 24-hour cycle logic, 
    grouped by the specified columns.
    """
    if prod_df.empty:
        return pd.DataFrame()

    prod_group_cols = [col for col in group_cols if col in prod_df.columns]
    
    prod_agg = prod_df.groupby(prod_group_cols).agg(
        Total_Target_Hour=('Target_Hour', 'sum'),
        Total_Duration=('Duration', 'sum'),
        Total_PackQty=('PackQty', 'sum')
    ).reset_index()

    if err_df.empty:
        prod_agg['NetProduction_H'] = prod_agg['Total_Duration']
        prod_agg['Line_Efficiency(%)'] = np.where(
            prod_agg['NetProduction_H'] > 0,
            (prod_agg['Total_Target_Hour'] / prod_agg['NetProduction_H']) * 100,
            0
        )
        prod_agg['OE(%)'] = prod_agg['Line_Efficiency(%)']
        prod_agg['LegalStoppage_H'] = 0.0
        prod_agg['IdleTime_H'] = 0.0
        prod_agg['Downtime_H'] = 0.0
        prod_agg['Losses_H'] = 0.0
        prod_agg['OE_Adjust_H'] = 0.0
        return prod_agg

    err_group_cols = [col for col in group_cols if col in err_df.columns]

    daily_err_agg = err_df.copy() 
    daily_err_agg['Error'] = daily_err_agg['Error'].astype(str).str.strip()

    def sum_duration_for_codes(df, codes):
        codes_str = [str(c) for c in codes]
        return df[df['Error'].isin(codes_str)]['Duration'].sum() / 60 

    err_summary = daily_err_agg.groupby(err_group_cols).apply(lambda x: pd.Series({
        'LegalStoppage_H': sum_duration_for_codes(x, ['33']),
        'IdleTime_H': sum_duration_for_codes(x, ['32']),
        'Downtime_H': sum_duration_for_codes(x, [str(c) for c in range(21, 32)]),
        'Losses_H': sum_duration_for_codes(x, [str(c) for c in range(1, 21)]),
        'OE_Adjust_H': sum_duration_for_codes(x, ['24', '25']) 
    })).reset_index()
    
    daily_metrics = pd.merge(prod_agg, err_summary, on=err_group_cols, how='left').fillna(0)
    
    Total_Day_Hours = 24.0
    
    daily_metrics['GrossProduction_H'] = Total_Day_Hours - daily_metrics['LegalStoppage_H'] - daily_metrics['IdleTime_H']
    daily_metrics['NetProduction_H'] = daily_metrics['GrossProduction_H'] - daily_metrics['Downtime_H']
    
    daily_metrics['Line_Efficiency(%)'] = np.where(
        daily_metrics['NetProduction_H'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['NetProduction_H']) * 100,
        0
    )
    
    daily_metrics['OE_Denominator'] = daily_metrics['NetProduction_H'] + daily_metrics['OE_Adjust_H']
    daily_metrics['OE(%)'] = np.where(
        daily_metrics['OE_Denominator'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['OE_Denominator']) * 100,
        0
    )
    
    return daily_metrics


def clear_supabase_bucket():
    """
    Deletes all .xlsx files from the Supabase 'uploads' bucket.
    """
    try:
        items = supabase.storage.from_("uploads").list(path="", options={"limit": 5000, "directories": False})
        file_names_to_delete = [item['name'] for item in items if item.get('name') is not None]

        if file_names_to_delete:
            supabase.storage.from_("uploads").remove(file_names_to_delete)
            st.success(f"Successfully deleted {len(file_names_to_delete)} files from Supabase.")
            get_all_supabase_files.clear()
            st.rerun()
        else:
            st.info("No files found in Supabase to delete.")
    except Exception as e:
        st.error(f"Error deleting files from Supabase: {e}")


# --- MAIN APP ---

st.title("📊 Production and Error Analysis Dashboard")

# Manage page state with st.session_state
if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard" # Default page

# Sidebar navigation
st.sidebar.header("Navigation")
page_options = ["Upload Data", "Data Archive", "Data Analyzing Dashboard", "Trend Analysis", "Contact Me"]
selected_page_index = page_options.index(st.session_state.page)
selected_page = st.sidebar.radio("Go to:", options=page_options, index=selected_page_index, key="sidebar_radio")

# Switch page
if selected_page != st.session_state.page:
    st.session_state.page = selected_page
    st.rerun()


# ========== Upload Page ==========
if st.session_state.page == "Upload Data":
    st.header("Upload Your Excel File(s)")
    uploaded_files = st.file_uploader("Upload your Excel (.xlsx) file(s)", type=["xlsx"], accept_multiple_files=True)

    if st.button("Initiate Upload"):
        if uploaded_files:
            upload_to_supabase(uploaded_files)
        else:
            st.warning("Please select files to upload first.")

# ========== Archive Page ==========
elif st.session_state.page == "Data Archive":
    st.header("File Archive")

    search_query_archive = st.text_input("Search in Archive (Filename):", key="search_archive_input")

    files_info = get_all_supabase_files()

    if files_info:
        files_info.sort(key=lambda x: x['name'])

        if search_query_archive:
            files_info = [f for f in files_info if search_query_archive.lower() in f['name'].lower()]

        if files_info:
            st.markdown("### Available Files:")
            for f_info in files_info:
                file_name_display = f_info['name']
                file_full_path_for_download = f_info['full_path']
                
                col1, col2 = st.columns([0.7, 0.3])

                with col1:
                    st.markdown(f"- {file_name_display} (uploaded: {f_info['file_date'].strftime('%d %b %Y')})")
                
                with col2:
                    if file_full_path_for_download and file_full_path_for_download.lower().endswith('.xlsx'):
                        download_data = download_from_supabase(file_full_path_for_download)
                        if download_data:
                            st.download_button(
                                label="Download",
                                data=download_data,
                                file_name=file_name_display,
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"download_{file_full_path_for_download}"
                            )
                    else:
                        st.warning("This item is not downloadable (invalid format).")
        else:
            st.info("No files found matching your search in the archive.")
    else:
        st.info("No files available in the archive. Please upload files first.")

    st.markdown("---")
    st.subheader("Admin Actions (Delete All Files)")
    with st.expander("Show/Hide Delete Option"):
        password_for_delete = st.text_input("Enter password to delete all files:", type="password", key="delete_password_input")
        if st.button("Delete All Files"):
            if password_for_delete == ARCHIVE_DELETE_PASSWORD:
                clear_supabase_bucket()
            elif password_for_delete:
                st.error("Incorrect password for deletion. Please try again.")

# ========== Dashboard Page ==========
elif st.session_state.page == "Data Analyzing Dashboard":
    st.header("Data Analyzing Dashboard")

    all_files_info = get_all_supabase_files()

    if not all_files_info:
        st.warning("No files available for analysis. Please upload files first.")
    else:
        min_available_date = min(f['file_date'] for f in all_files_info)
        max_available_date = max(f['file_date'] for f in all_files_info)

        col_start_date, col_end_date = st.columns(2)
        with col_start_date:
            default_start_date = st.session_state.get('dashboard_start_date', min_available_date)
            selected_start_date = st.date_input(
                "Start Date:", 
                value=default_start_date, 
                min_value=min_available_date, 
                max_value=max_available_date, 
                key="dashboard_start_date_picker"
            )
        with col_end_date:
            default_end_date = st.session_state.get('dashboard_end_date', max_available_date)
            selected_end_date = st.date_input(
                "End Date:", 
                value=default_end_date, 
                min_value=min_available_date, 
                max_value=max_available_date, 
                key="dashboard_end_date_picker"
            )

        if selected_end_date < selected_start_date:
            st.error("Error: End Date cannot be before Start Date. Adjusting End Date.")
            selected_end_date = selected_start_date
            st.session_state.dashboard_end_date_picker = selected_end_date
        
        st.session_state.dashboard_start_date = selected_start_date
        st.session_state.dashboard_end_date = selected_end_date

        files_in_date_range = [
            f for f in all_files_info if selected_start_date <= f['file_date'] <= selected_end_date
        ]

        num_selected_days = (selected_end_date - selected_start_date).days + 1
        st.info(f"Number of days selected: **{num_selected_days}**")

        if not files_in_date_range:
            st.info("No files found within the selected date range. Please adjust your date selection or upload more files.")
        else:
            st.markdown("##### Files to be analyzed based on selected dates:")
            for f_info in files_in_date_range:
                st.markdown(f"- `{f_info['name']}` (Date: {f_info['file_date'].strftime('%d %b %Y')})")

            selected_files_full_paths_dashboard = [f['full_path'] for f in files_in_date_range]
            
            all_production_data = []
            all_error_data = []

            progress_text = "Processing files..."
            my_bar = st.progress(0, text=progress_text)

            for i, file_info_dict in enumerate(files_in_date_range):
                file_full_path = file_info_dict['full_path']
                file_data = download_from_supabase(file_full_path)

                if file_data:
                    try:
                        xls = pd.ExcelFile(BytesIO(file_data))
                        for sheet_name in xls.sheet_names:
                            df_raw_sheet = pd.read_excel(BytesIO(file_data), sheet_name=sheet_name, header=None)
                            original_filename = file_full_path.split('/')[-1]

                            prod_df = read_production_data(df_raw_sheet, original_filename, sheet_name, file_info_dict['file_date'])
                            err_df = read_error_data(df_raw_sheet, sheet_name, original_filename, file_info_dict['file_date'])

                            if not prod_df.empty:
                                all_production_data.append(prod_df)
                            if not err_df.empty:
                                all_error_data.append(err_df)

                    except Exception as e:
                        st.error(f"Error processing Excel file '{file_full_path}': {e}")

                my_bar.progress((i + 1) / len(files_in_date_range), text=f"Processing file: {file_full_path}")

            my_bar.empty()

            final_prod_df = pd.concat(all_production_data, ignore_index=True) if all_production_data else pd.DataFrame()
            final_err_df = pd.concat(all_error_data, ignore_index=True) if all_error_data else pd.DataFrame()

            unique_machines = ['All Machines']
            if not final_prod_df.empty and "ProductionTypeForTon" in final_prod_df.columns:
                filtered_unique_machines = [m for m in final_prod_df["ProductionTypeForTon"].unique().tolist() if m is not None]
                if "Unknown Machine" in filtered_unique_machines:
                    filtered_unique_machines.remove("Unknown Machine")
                filtered_unique_machines.append("Unknown Machine")
                unique_machines.extend(sorted(filtered_unique_machines))

            selected_machine = st.selectbox("Select Machine:", unique_machines)

            filtered_prod_df_by_machine = final_prod_df.copy()
            filtered_err_df_by_machine = final_err_df.copy()

            if selected_machine != 'All Machines':
                filtered_prod_df_by_machine = final_prod_df[
                    final_prod_df["ProductionTypeForTon"] == selected_machine].copy()
                
                if not final_err_df.empty and "MachineType" in final_err_df.columns:
                    filtered_err_df_by_machine = final_err_df[
                        final_err_df["MachineType"] == selected_machine].copy()
                else:
                    filtered_err_df_by_machine = pd.DataFrame()
            
            filtered_prod_df_by_product = filtered_prod_df_by_machine.copy()
            
            unique_products = ['All Products']
            if not filtered_prod_df_by_machine.empty and "Product" in filtered_prod_df_by_machine.columns:
                filtered_unique_products = [p for p in filtered_prod_df_by_machine["Product"].unique().tolist() if p is not None and str(p).strip() != '']
                unique_products.extend(sorted(filtered_unique_products))

            selected_product = st.selectbox("Select Product:", unique_products)
            
            if selected_product != 'All Products':
                filtered_prod_df_by_product = filtered_prod_df_by_machine[
                    filtered_prod_df_by_machine["Product"] == selected_product].copy()

            chart_prod_df = filtered_prod_df_by_product.copy()
            
            daily_machine_metrics_df = calculate_metrics(
                filtered_prod_df_by_machine, 
                filtered_err_df_by_machine, 
                group_cols=['Date', 'ProductionTypeForTon']
            )

            daily_product_metrics_df = calculate_metrics(
                chart_prod_df, 
                filtered_err_df_by_machine, 
                group_cols=['Date', 'ProductionTypeForTon', 'Product']
            )

            st.markdown("---")
            st.subheader(f"Metrics for Machine: {selected_machine}, Product: {selected_product}")

            if daily_machine_metrics_df.empty and daily_product_metrics_df.empty:
                st.warning("No production or error data available for the selected filters and date range to calculate metrics.")
            else:
                total_metrics_df = calculate_metrics(
                    final_prod_df, 
                    final_err_df, 
                    group_cols=['Date']
                )

                if selected_product != 'All Products':
                    current_metrics_df = daily_product_metrics_df
                elif selected_machine != 'All Machines':
                    current_metrics_df = daily_machine_metrics_df
                else:
                    current_metrics_df = total_metrics_df
                
                total_target_hour = current_metrics_df['Total_Target_Hour'].sum()
                total_pack_qty = current_metrics_df['Total_PackQty'].sum()
                
                total_legal_stoppage_h = current_metrics_df['LegalStoppage_H'].sum()
                total_idle_time_h = current_metrics_df['IdleTime_H'].sum()
                total_downtime_h = current_metrics_df['Downtime_H'].sum()
                total_losses_h = current_metrics_df['Losses_H'].sum()
                total_oe_adjust_h = current_metrics_df['OE_Adjust_H'].sum()
                
                total_gross_prod_h = (num_selected_days * 24.0) - total_legal_stoppage_h - total_idle_time_h
                total_net_prod_h = total_gross_prod_h - total_downtime_h
                total_oe_denom = total_net_prod_h + total_oe_adjust_h
                
                total_line_efficiency = (total_target_hour / total_net_prod_h) * 100 if total_net_prod_h > 0 else 0
                total_oe = (total_target_hour / total_oe_denom) * 100 if total_oe_denom > 0 else 0

                col1, col2, col3, col4, col5 = st.columns(5)
                col1.metric("Total Production (Pcs)", f"{int(total_pack_qty):,}")
                col2.metric("Total Target Hour (H)", f"{total_target_hour:,.2f}")
                col3.metric("Total Line Efficiency (%)", f"{total_line_efficiency:.1f}%")
                col4.metric("Total OE (%)", f"{total_oe:.1f}%")
                col5.metric("Total Downtime (H)", f"{total_downtime_h:,.2f}")

                st.markdown("---")

                st.subheader("Daily Performance Trend")
                
                if selected_product != 'All Products':
                    chart_df_metrics = daily_product_metrics_df
                elif selected_machine != 'All Machines':
                    chart_df_metrics = daily_machine_metrics_df
                else:
                    chart_df_metrics = total_metrics_df

                if not chart_df_metrics.empty:
                    chart_df_metrics = chart_df_metrics.sort_values(by='Date')
                    chart_df_metrics['Date_Str'] = chart_df_metrics['Date'].apply(lambda x: x.strftime('%Y-%m-%d'))
                    
                    fig_oe_le = px.line(
                        chart_df_metrics,
                        x='Date_Str',
                        y=['Line_Efficiency(%)', 'OE(%)'],
                        title='Daily Line Efficiency and OE Trend',
                        labels={'value': 'Percentage (%)', 'variable': 'Metric', 'Date_Str': 'Date'},
                        markers=True
                    )
                    fig_oe_le.update_layout(yaxis_range=[0, 100])
                    st.plotly_chart(fig_oe_le, use_container_width=True)

                    fig_prod_hours = px.bar(
                        chart_df_metrics,
                        x='Date_Str',
                        y=['Total_Target_Hour', 'NetProduction_H'],
                        title='Daily Target vs. Net Production Hours',
                        labels={'value': 'Hours', 'variable': 'Type', 'Date_Str': 'Date'},
                        barmode='group'
                    )
                    st.plotly_chart(fig_prod_hours, use_container_width=True)

                    st.subheader("Total Time Loss Distribution (Hours)")
                    
                    loss_data = pd.DataFrame({
                        'Category': [
                            'Downtime (21-31)', 
                            'Losses (1-20)', 
                            'Idle Time (32)', 
                            'Legal Stoppage (33)',
                            'OE Adjustment (24, 25)'
                        ],
                        'Hours': [
                            total_downtime_h, 
                            total_losses_h, 
                            total_idle_time_h, 
                            total_legal_stoppage_h,
                            total_oe_adjust_h
                        ]
                    })
                    loss_data = loss_data[loss_data['Hours'] > 0]

                    if not loss_data.empty:
                        fig_losses = px.pie(
                            loss_data,
                            values='Hours',
                            names='Category',
                            title='Total Loss Distribution',
                            hole=.3,
                        )
                        st.plotly_chart(fig_losses, use_container_width=True)
                    else:
                        st.info("No time losses recorded for the selected filter.")
                
                else:
                    st.info("No metrics data generated for charting.")

                st.markdown("---")

                st.subheader("Raw Data and Metrics Tables")
                
                tab_raw_prod, tab_raw_err, tab_metrics_m, tab_metrics_p = st.tabs([
                    "Raw Production Data (Filtered)", 
                    "Raw Error Data (Filtered)",
                    "Daily Machine Metrics",
                    "Daily Product Metrics"
                ])

                with tab_raw_prod:
                    st.markdown("##### Raw Production Data (Filtered by Machine/Product)")
                    if not chart_prod_df.empty:
                        st.dataframe(chart_prod_df.sort_values(by='Date', ascending=False), use_container_width=True)
                    else:
                        st.info("No raw production data available for the current filter.")

                with tab_raw_err:
                    st.markdown("##### Raw Error Data (Filtered by Machine, Aggregated by Error Code)")
                    if not filtered_err_df_by_machine.empty:
                        display_err_df = filtered_err_df_by_machine.groupby(['Date', 'MachineType', 'Error'])['Duration'].sum().reset_index()
                        display_err_df = display_err_df.sort_values(by=['Date', 'Duration'], ascending=[False, False])
                        display_err_df['Duration (Min)'] = display_err_df['Duration'].apply(lambda x: f"{x:,.0f}")
                        display_err_df['Duration (Hr)'] = (display_err_df['Duration'] / 60).apply(lambda x: f"{x:,.2f}")
                        st.dataframe(display_err_df.drop(columns=['Duration']), use_container_width=True)
                    else:
                        st.info("No raw error data available for the current filter.")

                with tab_metrics_m:
                    st.markdown("##### Daily Machine Metrics (Aggregated by Date and Machine)")
                    if not daily_machine_metrics_df.empty:
                        st.dataframe(daily_machine_metrics_df.sort_values(by='Date', ascending=False), use_container_width=True)
                    else:
                        st.info("No machine metrics calculated for the current filters.")

                with tab_metrics_p:
                    st.markdown("##### Daily Product Metrics (Aggregated by Date, Machine, and Product)")
                    if not daily_product_metrics_df.empty:
                        st.dataframe(daily_product_metrics_df.sort_values(by='Date', ascending=False), use_container_width=True)
                    else:
                        st.info("No product metrics calculated for the current filters.")

# ========== Trend Page ==========
elif st.session_state.page == "Trend Analysis":
    st.header("Trend Analysis (Machine and Product Over Time)")

    all_files_info_trend = get_all_supabase_files()

    if not all_files_info_trend:
        st.warning("No files available for analysis. Please upload files first.")
    else:
        min_available_date = min(f['file_date'] for f in all_files_info_trend)
        max_available_date = max(f['file_date'] for f in all_files_info_trend)

        col_start_date, col_end_date = st.columns(2)
        with col_start_date:
            default_start_date = st.session_state.get('trend_start_date', min_available_date)
            selected_start_date = st.date_input(
                "Start Date:", 
                value=default_start_date, 
                min_value=min_available_date, 
                max_value=max_available_date, 
                key="trend_start_date_picker"
            )
        with col_end_date:
            default_end_date = st.session_state.get('trend_end_date', max_available_date)
            selected_end_date = st.date_input(
                "End Date:", 
                value=default_end_date, 
                min_value=min_available_date, 
                max_value=max_available_date, 
                key="trend_end_date_picker"
            )

        if selected_end_date < selected_start_date:
            st.error("Error: End Date cannot be before Start Date. Adjusting End Date.")
            selected_end_date = selected_start_date
            st.session_state.trend_end_date_picker = selected_end_date
        
        st.session_state.trend_start_date = selected_start_date
        st.session_state.trend_end_date = selected_end_date
        
        files_in_date_range_trend = [
            f for f in all_files_info_trend if selected_start_date <= f['file_date'] <= selected_end_date
        ]

        if not files_in_date_range_trend:
            st.info("No files found within the selected date range.")
            st.stop()
            
        all_production_data_trend = []
        all_error_data_trend = []
        
        with st.spinner("Preparing trend data..."):
            for file_info_dict in files_in_date_range_trend:
                file_full_path = file_info_dict['full_path']
                file_data = download_from_supabase(file_full_path)

                if file_data:
                    try:
                        xls = pd.ExcelFile(BytesIO(file_data))
                        for sheet_name in xls.sheet_names:
                            df_raw_sheet = pd.read_excel(BytesIO(file_data), sheet_name=sheet_name, header=None)
                            original_filename = file_full_path.split('/')[-1]

                            prod_df = read_production_data(df_raw_sheet, original_filename, sheet_name, file_info_dict['file_date'])
                            err_df = read_error_data(df_raw_sheet, sheet_name, original_filename, file_info_dict['file_date'])

                            if not prod_df.empty:
                                all_production_data_trend.append(prod_df)
                            if not err_df.empty:
                                all_error_data_trend.append(err_df)
                    except Exception as e:
                        st.error(f"Error processing Excel file for trend '{file_full_path}': {e}")
            
            final_prod_df_trend = pd.concat(all_production_data_trend, ignore_index=True) if all_production_data_trend else pd.DataFrame()
            final_err_df_trend = pd.concat(all_error_data_trend, ignore_index=True) if all_error_data_trend else pd.DataFrame()
        
        if final_prod_df_trend.empty:
            st.warning("No production data available for the selected trend period.")
            st.stop()
        
        st.markdown("---")
        
        col_group, col_target = st.columns(2)
        with col_group:
            grouping_level = st.selectbox(
                "Group Trend By:",
                options=["Machine Type", "Product"],
                key="trend_grouping"
            )
        
        if grouping_level == "Machine Type":
            unique_identifiers = [m for m in final_prod_df_trend["ProductionTypeForTon"].unique().tolist() if m is not None and m != 'Unknown Machine']
            group_cols = ['Date', 'ProductionTypeForTon']
            metrics_df_trend = calculate_metrics(final_prod_df_trend, final_err_df_trend, group_cols=group_cols)
            metrics_df_trend = metrics_df_trend.rename(columns={'ProductionTypeForTon': 'Grouping_Key'})
        else:
            unique_identifiers = [p for p in final_prod_df_trend["Product"].unique().tolist() if p is not None and str(p).strip() != '']
            group_cols = ['Date', 'ProductionTypeForTon', 'Product']
            metrics_df_trend = calculate_metrics(final_prod_df_trend, final_err_df_trend, group_cols=group_cols)
            metrics_df_trend = metrics_df_trend.rename(columns={'Product': 'Grouping_Key'})
            metrics_df_trend = metrics_df_trend[metrics_df_trend['Grouping_Key'] != ''].copy()

        unique_identifiers = sorted(list(set(metrics_df_trend['Grouping_Key'].dropna().astype(str).tolist())))

        with col_target:
            selected_identifiers = st.multiselect(
                f"Select {grouping_level}s to Compare:",
                options=unique_identifiers,
                default=unique_identifiers[:3] if len(unique_identifiers) > 3 else unique_identifiers,
                key="trend_identifiers"
            )
        
        if not selected_identifiers:
            st.warning(f"Please select at least one {grouping_level} for comparison.")
            st.stop()
        
        metrics_df_filtered = metrics_df_trend[metrics_df_trend['Grouping_Key'].isin(selected_identifiers)].copy()

        if metrics_df_filtered.empty:
            st.warning("No data found for the selected identifiers in the date range.")
            st.stop()
            
        metrics_df_filtered['Date_Str'] = metrics_df_filtered['Date'].apply(lambda x: x.strftime('%Y-%m-%d'))

        st.subheader(f"Comparison of Daily OE (%) by {grouping_level}")
        fig_oe_comp = px.line(
            metrics_df_filtered,
            x='Date_Str',
            y='OE(%)',
            color='Grouping_Key',
            title=f'Daily OE Trend Comparison by {grouping_level}',
            labels={'OE(%)': 'OE (%)', 'Grouping_Key': grouping_level, 'Date_Str': 'Date'},
            markers=True
        )
        fig_oe_comp.update_layout(yaxis_range=[0, 100])
        st.plotly_chart(fig_oe_comp, use_container_width=True)

        st.subheader(f"Comparison of Total Production (PackQty) by {grouping_level}")
        fig_prod_comp = px.bar(
            metrics_df_filtered,
            x='Date_Str',
            y='Total_PackQty',
            color='Grouping_Key',
            title=f'Daily Total Production (PackQty) Comparison by {grouping_level}',
            labels={'Total_PackQty': 'Production (Pcs)', 'Grouping_Key': grouping_level, 'Date_Str': 'Date'},
            barmode='group'
        )
        st.plotly_chart(fig_prod_comp, use_container_width=True)
        
        st.markdown("---")
        st.subheader("Comparison Data Table")
        st.dataframe(metrics_df_filtered.sort_values(by=['Date', 'Grouping_Key'], ascending=[False, True]), use_container_width=True)

# ========== Contact Page ==========
elif st.session_state.page == "Contact Me":
    st.subheader("Connect with Mohammad Asadollahzadeh")
    st.markdown("---")
    st.markdown("""
    In today’s cutting-edge world, with rapid advances in technology, AI is no longer optional—it’s essential. Using AI can significantly boost performance, minimize human error, and streamline workflows. Relying solely on traditional methods often results in wasted time and effort, without delivering the efficiency we seek.

    To address this, I’ve started building a platform that blends automation with intelligence. Driven by my passion for Python—despite still learning—and a deep interest in creating disciplined, data-driven technical solutions, I began developing this Streamlit-based website to analyze daily production performance.

    While my Python skills are still growing, I’ve poured in patience, dedication, and curiosity. Throughout the process, tools like AI copilots were instrumental in helping me debug, refine strategies, and bring this idea to life.

    That said, I’m committed to improving—both in coding and system design. I welcome your feedback, suggestions, or any guidance to help enhance this platform further.

    📧 Email: m.asdz@yahoo.com
    🔗 LinkedIn: Mohammad Asdollahzadeh

    Thank you for visiting, and I truly appreciate your support.

    Warm regards,
    Mohammad Asadollahzadeh
    """)
