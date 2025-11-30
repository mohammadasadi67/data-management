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
        # If it's a float between 0 and 1, assume it's an Excel time serial number (fraction of a day)
        if 0 <= val < 1:
            return val * 24  # Convert fraction of a day to hours
        
        # Try to interpret as HHMM format (e.g., 730, 2600).
        # We now allow larger HHMM values and take modulo 24 for the hour.
        try:
            val_int = int(val)
            h = val_int // 100
            m = val_int % 100
            
            # Validate minutes (0-59) and apply modulo 24 to hours for cycling
            if 0 <= m < 60:
                return (h % 24) + m / 60
        except ValueError:
            pass # Not a valid HHMM number

        # Fallback: If it's a number but not a time fraction or valid HHMM string,
        # it might already be in raw hours format.
        return float(val)

    # Case 4: String
    if isinstance(val, str):
        s = val.strip()
        # Try parsing as HH:MM:SS
        if ':' in s:
            try:
                dt_obj = datetime.strptime(s, "%H:%M:%S")
                return dt_obj.hour + dt_obj.minute / 60 + dt_obj.second / 3600
            except ValueError:
                # Fallback to HH:MM if HH:MM:SS fails
                try:
                    dt_obj = datetime.strptime(s, "%H:%M")
                    return dt_obj.hour + dt_obj.minute / 60
                except ValueError:
                    pass
        # Try parsing as HHMM integer string (e.g., "730", "2600")
        if s.isdigit(): # Removed length check to allow longer strings if they are valid HHMM numeric rep
            try:
                val_int = int(s)
                h = val_int // 100
                m = val_int % 100
                if 0 <= m < 60: # Validate minutes, apply modulo 24 to hours
                    return (h % 24) + m / 60
            except ValueError:
                pass
        # Try parsing as a raw float string (e.g., "7.5" for 7.5 hours)
        try:
            return float(s)
        except ValueError:
            pass

    return 0  # Default for unhandled types or errors


def convert_duration_to_minutes(duration_val):
    """
    Converts various Excel duration/time formats (timedelta, datetime.time, datetime.datetime, numeric, string) to total minutes.
    """
    if pd.isna(duration_val) or pd.isnull(duration_val):  # Handle both NaN and pd.NaT
        return 0

    # Case 1: Python datetime.timedelta object (Pandas often reads Excel time duration as timedelta)
    if isinstance(duration_val, timedelta):
        return duration_val.total_seconds() / 60

    # Case 2: Python datetime.datetime object (Pandas often reads Excel time as time object)
    if isinstance(duration_val, datetime):
        # Calculate total seconds from midnight
        total_seconds = duration_val.hour * 3600 + duration_val.minute * 60 + duration_val.second
        return total_seconds / 60  # Convert to minutes

    # Case 3: Python datetime.time object (Pandas often reads Excel time as time object)
    if isinstance(duration_val, datetime_time):
        hours = duration_val.hour
        minutes = duration_val.minute
        seconds = duration_val.second
        return hours * 60 + minutes + seconds / 60

    # Case 4: Numeric value (Excel often stores time as a fraction of a day, or HHMM)
    if isinstance(duration_val, (int, float)):
        if 0 <= duration_val < 1:  # Represents fraction of a day (e.g., 0.5 for 12:00 PM)
            return duration_val * 24 * 60  # Convert fraction of a day to minutes
        elif duration_val >= 1:
            # Try HHMM conversion if not too large (e.g., 730 for 7:30)
            if duration_val < 2400:  # Heuristic for HHMM format
                try:
                    val_int = int(duration_val)
                    h = val_int // 100
                    m = val_int % 100
                    if 0 <= h < 24 and 0 <= m < 60:  # Validate HHMM makes sense as time
                        return h * 60 + m
                except ValueError:
                    pass
            # Fallback if not HHMM or HHMM conversion failed, assume it's raw minutes or hours
            # This part is a bit ambiguous without exact Excel input examples.
            # Assuming here that a raw float could be hours, e.g. 2.5 for 2.5 hours.
            return float(duration_val) * 60  # Treat raw float as hours and convert to minutes

    # Case 5: String (e.g., "0:30", "1:15", "30", "730", "2.5")
    if isinstance(duration_val, str):
        duration_str = duration_val.strip()

        # Try to parse as HH:MM:SS (more robust) or HH:MM
        if ':' in duration_str:
            try:
                # Try HH:MM:SS first
                dt_obj = datetime.strptime(duration_str, "%H:%M:%S")
                return dt_obj.hour * 60 + dt_obj.minute + dt_obj.second / 60
            except ValueError:
                try:
                    # Fallback to HH:MM
                    dt_obj = datetime.strptime(duration_str, "%H:%M")
                    return dt_obj.hour * 60 + dt_obj.minute
                except ValueError:
                    pass

        # Try to parse as HHMM (e.g., "730")
        if duration_str.isdigit():
            try:
                val_int = int(duration_str)
                h = val_int // 100
                m = val_int % 100
                if 0 <= h < 24 and 0 <= m < 60:  # Validate HHMM makes sense as time
                    return h * 60 + m
            except ValueError:
                pass

        # Try to parse as raw number (string like "1.5" or "30") (assume hours and convert to minutes)
        try:
            return float(duration_str) * 60
        except ValueError:
            pass

    return 0  # Default to 0 if all conversions fail


def format_production_date_from_filename(filename):
    """
    Extracts ddmmyyyy from filename and formats it as dd "month name" yy.
    e.g., "21062025.xlsx" -> "21 June 25"
    (This function is now only used for display, internal data uses datetime.date objects)
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


# Refined helper function to determine the clean machine type for display/filtering
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
    """
    try:
        # Headers are in Excel rows 2 and 3 (iloc 1 and 2) from column D (iloc 3) to P (iloc 15)
        row2_headers = df_raw_sheet.iloc[1, 3:16].fillna('').astype(str).tolist()
        row3_headers = df_raw_sheet.iloc[2, 3:16].fillna('').astype(str).tolist()

        combined_headers = []
        for r2, r3 in zip(row2_headers, row3_headers):
            if r3.strip() and r3.strip() != 'nan':  # Prefer row 3 if not empty/nan
                combined_headers.append(r3.strip())
            elif r2.strip() and r2.strip() != 'nan':  # Fallback to row 2 if not empty/nan
                combined_headers.append(r2.strip())
            else:
                combined_headers.append("")  # If both are empty, use an empty string

        # Ensure headers are not empty for indexing purposes, assign a generic name if so
        headers = [h if h else f"Unnamed_Col_{i}" for i, h in enumerate(combined_headers)]

    except IndexError as e:
        st.error(
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Production data headers not found in range D2:P3 of your Excel sheet. (Error: {e}) Please check the sheet format.")
        return pd.DataFrame()

    # Data is in Excel rows 4-9 (iloc 3-8) from column D (iloc 3) to P (iloc 15)
    data = df_raw_sheet.iloc[3:9, 3:16].copy()

    if len(headers) == data.shape[1]:
        data.columns = headers
    else:
        st.error(
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Number of columns in production section does not match headers. Expected {len(headers)} columns, but {data.shape[1]} found. Please check the sheet format. (After header combination)")
        return pd.DataFrame()

    # Rename columns to standardized names for the dashboard
    rename_map = {
        "start": "Start",  # Assumed original header, to be mapped to "Start"
        "finish": "End",  # Assumed original header, to be mapped to "End"
        "time": "Duration_Original",  # Original duration column, not used for final 'Duration'
        "production title": "Product",
        "cap": "Capacity",
        "manpower": "Manpower",
        "quanity": "PackQty",
        "date": "ProdDate_Original",  # Original date column, often empty or redundant
        "waste": "Waste"
    }

    # Only rename columns that actually exist in the DataFrame after initial header assignment
    actual_rename_map = {k: v for k, v in rename_map.items() if k in data.columns}
    data = data.rename(columns=actual_rename_map)

    # Use the passed file_date_obj as the primary date for consistency
    data["Date"] = file_date_obj 

    # Determine the machine type for this sheet/file
    determined_machine_type_for_sheet = determine_machine_type(selected_sheet_name)
    if determined_machine_type_for_sheet == "Unknown Machine":
        determined_machine_type_for_sheet = determine_machine_type(uploaded_file_name)
    data['ProductionTypeForTon'] = determined_machine_type_for_sheet

    # Ensure all required columns exist, adding them as NA if missing, and defaulting numeric ones to 0
    required_cols = ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Date", "Waste",
                     "ProductionTypeForTon"]
    for col in required_cols:
        if col not in data.columns:
            st.warning(
                f"Warning in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Required column '{col}' not found for production section. Data might be incomplete. Please check the sheet format. (After column rename)")
            data[col] = pd.NA
            if col in ["PackQty", "Waste", "Capacity", "Manpower"]:
                data[col] = 0

    # Clean Product names: strip whitespace and fill any remaining empty strings or NaN
    # Only perform cleaning if 'Product' column exists
    if 'Product' in data.columns:
        data["Product"] = data["Product"].fillna('').astype(str).str.strip()
        # Convert to Title Case for consistency (e.g., "product a" and "Product A" become "Product A")
        data["Product"] = data["Product"].str.title()
        # Filter out rows where Product name is empty after cleaning
        data = data[data["Product"] != ''].copy()


    # Convert Start and End times to decimal hours using the enhanced convert_time function
    data["StartTime"] = data["Start"].apply(convert_time)
    data["EndTime"] = data["End"].apply(convert_time)

    # *** IMPORTANT CHANGE: Handle duration crossing midnight ***
    # If EndTime is less than StartTime, it means the time crosses midnight. Add 24 hours to EndTime.
    data['EndTimeAdjusted'] = data.apply(
        lambda row: row['EndTime'] + 24 if row['EndTime'] < row['StartTime'] else row['EndTime'], axis=1)

    # Calculate Duration in hours using the adjusted EndTime
    data["Duration"] = data["EndTimeAdjusted"] - data["StartTime"]
    data = data.dropna(subset=["Duration"])  # Drop rows where duration couldn't be calculated (e.g., missing Start/End)
    data = data[data["Duration"] != 0]  # Remove rows with 0 duration

    # Convert numeric columns, coercing errors to NaN and then filling with 0
    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    data["Capacity"] = pd.to_numeric(data["Capacity"], errors="coerce").fillna(0)
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)

    # Calculate Ton - this calculation is per-row and correct here
    data["Ton"] = data.apply(calculate_ton, axis=1)

    # NEW: Calculate Potential Production and per-row Efficiency
    data['PotentialProduction'] = data['Capacity'] * data['Duration']
    # Calculate Efficiency(%), handling potential division by zero
    data['Efficiency(%)'] = np.where(
        data['PotentialProduction'] > 0,
        (data['PackQty'] / data['PotentialProduction']) * 100,
        0
    )

    # Waste(%) and Efficiency(%) are now calculated AFTER aggregation for charts,
    # so we don't create them here at the row-level.

    # Select and order final columns for the output DataFrame
    # Added "Date" to final_cols
    final_cols = ["Date", "Product", "Capacity", "Manpower", "Duration", "PackQty", "Waste", "Ton",
                  "PotentialProduction", "Efficiency(%)", "ProductionTypeForTon"]
    data = data[[col for col in final_cols if col in data.columns]]

    return data


def read_error_data(df_raw_sheet, sheet_name_for_debug="Unknown Sheet", uploaded_file_name_for_debug="Unknown File", file_date_obj=None):
    """
    Reads error data from the Excel sheet.
    Accepts file_date_obj (datetime.date) to assign to each row.
    """
    try:
        # Error data from G12:H1000 (iloc 11:1000 for rows, 6:8 for columns)
        raw_errors_df = df_raw_sheet.iloc[11:1000, 6:8].copy()
        raw_errors_df.columns = ["RawErrorName", "RawDuration"]

        # Apply conversion to minutes for error durations
        raw_errors_df["RawDuration"] = raw_errors_df["RawDuration"].apply(convert_duration_to_minutes)

        # Clean RawErrorName: fillna, convert to string, strip whitespace
        raw_errors_df["RawErrorName"] = raw_errors_df["RawErrorName"].fillna('').astype(str).str.strip()

        # Filter out rows where RawErrorName is an empty string after stripping
        df_filtered = raw_errors_df[raw_errors_df["RawErrorName"] != ''].copy()

        # Aggregate durations by error name
        aggregated_errors = df_filtered.groupby("RawErrorName")["RawDuration"].sum().reset_index()
        aggregated_errors.columns = ["Error", "Duration"]

        df_final_errors = aggregated_errors.copy()

        # Add Date column for consistency with production data and trend analysis
        if file_date_obj is not None:
            df_final_errors['Date'] = file_date_obj
        else:
            df_final_errors['Date'] = datetime.now().date() # Fallback

        # Add MachineType column to error data for filtering
        df_final_errors['MachineType'] = determine_machine_type(sheet_name_for_debug)

        if df_final_errors.empty:
            return pd.DataFrame()

        return df_final_errors

    except IndexError as e:
        st.error(
            f"Error in file '{uploaded_file_name_for_debug}' (Sheet: '{selected_sheet_name}'): Raw error data not found in expected range (G12:H1000) of your Excel sheet. (Error: `{e}`). Please check the sheet format.")
        return pd.DataFrame()
    except Exception as e:
        st.error(
            f"Error in file '{uploaded_file_name_for_debug}' (Sheet: '{selected_sheet_name}'): An unexpected error occurred while processing error data: `{e}`")
        return pd.DataFrame()


def clear_supabase_bucket():
    """
    Deletes all .xlsx files from the Supabase 'uploads' bucket.
    """
    try:
        # List all objects directly from the root (not recursively)
        items = supabase.storage.from_("uploads").list(path="", options={"limit": 5000, "directories": False})

        # Extract names for deletion (since they are in the root)
        file_names_to_delete = [item['name'] for item in items if item.get('name') is not None]

        if file_names_to_delete:
            response = supabase.storage.from_("uploads").remove(file_names_to_delete)
            st.success(f"Successfully deleted {len(file_names_to_delete)} files from Supabase.")
            get_all_supabase_files.clear()  # Clear cache to force refetch
            st.rerun()
        else:
            st.info("No files found in Supabase to delete.")
    except Exception as e:
        st.error(f"Error deleting files from Supabase: {e}")


# --- Main Application ---

st.set_page_config(layout="wide", page_title="Production & Error Dashboard")
st.title("📊 Production and Error Analysis Dashboard")

# Manage page state with st.session_state
if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard"  # Set default page to Dashboard

# Sidebar navigation using st.sidebar.radio
st.sidebar.header("Navigation")
page_options = ["Upload Data", "Data Archive", "Data Analyzing Dashboard", "Trend Analysis", "Contact Me"]
selected_page_index = page_options.index(st.session_state.page)
selected_page = st.sidebar.radio("Go to:", options=page_options, index=selected_page_index, key="sidebar_radio")

# Update session state based on radio selection
if selected_page != st.session_state.page:
    st.session_state.page = selected_page
    st.rerun()  # Rerun to switch page immediately


if st.session_state.page == "Upload Data":
    st.header("Upload Your Excel File(s)")
    # Allow multiple files to be uploaded
    uploaded_files = st.file_uploader("Upload your Excel (.xlsx) file(s)", type=["xlsx"], accept_multiple_files=True)

    # Add an explicit upload button
    if st.button("Initiate Upload"):
        if uploaded_files:
            upload_to_supabase(uploaded_files)  # Pass the list of files
        else:
            st.warning("Please select files to upload first.")

elif st.session_state.page == "Data Archive":
    st.header("File Archive")

    search_query_archive = st.text_input("Search in Archive (Filename):", key="search_archive_input")

    files_info = get_all_supabase_files()  # This now includes 'file_date' and 'full_path'

    if files_info:
        # Sort files by name for consistent display (flat list)
        files_info.sort(key=lambda x: x['name'])

        # Filter by search query if present
        if search_query_archive:
            files_info = [f for f in files_info if search_query_archive.lower() in f['name'].lower()]

        if files_info:
            st.markdown("### Available Files:")
            # Display files in a flat list
            for f_info in files_info:
                file_name_display = f_info['name']
                file_full_path_for_download = f_info['full_path']  # Use the full path for download

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
                                file_name=file_name_display,  # Keep original filename for download
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                key=f"download_{file_full_path_for_download}"
                            )
                        else:
                            pass
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
            elif password_for_delete: # Only show error if input is not empty
                st.error("Incorrect password for deletion. Please try again.")


elif st.session_state.page == "Data Analyzing Dashboard":
    st.header("Data Analyzing Dashboard")

    all_files_info = get_all_supabase_files()

    if not all_files_info:
        st.warning("No files available for analysis. Please upload files first.")
    else:
        # Determine min/max dates from available files for date picker defaults
        min_available_date = min(f['file_date'] for f in all_files_info)
        max_available_date = max(f['file_date'] for f in all_files_info)

        # Ensure selected dates are within the available range and handle initial state
        col_start_date, col_end_date = st.columns(2)
        with col_start_date:
            # Set default value of date_input to the stored session state value, or min_available_date
            default_start_date = st.session_state.get('dashboard_start_date', min_available_date)
            selected_start_date = st.date_input(
                "Start Date:",
                value=default_start_date,
                min_value=min_available_date,
                max_value=max_available_date,
                key="dashboard_start_date_picker"
            )
        with col_end_date:
            # Set default value of date_input to the stored session state value, or max_available_date
            default_end_date = st.session_state.get('dashboard_end_date', max_available_date)
            selected_end_date = st.date_input(
                "End Date:",
                value=default_end_date,
                min_value=min_available_date,
                max_value=max_available_date,
                key="dashboard_end_date_picker"
            )

        # Ensure end date is not before start date
        if selected_end_date < selected_start_date:
            st.error("Error: End Date cannot be before Start Date. Adjusting End Date.")
            selected_end_date = selected_start_date  # Reset to start date to prevent further errors
            # Update the date_input widget with the corrected value
            st.session_state.dashboard_end_date_picker = selected_end_date  # This will re-render the widget

        # Update session state with selected dates
        st.session_state.dashboard_start_date = selected_start_date
        st.session_state.dashboard_end_date = selected_end_date

        # Filter files based on selected date range
        files_in_date_range = [
            f for f in all_files_info
            if selected_start_date <= f['file_date'] <= selected_end_date
        ]

        # Calculate and display the number of days selected
        num_selected_days = (selected_end_date - selected_start_date).days + 1
        st.info(f"Number of days selected: **{num_selected_days}**")


        if not files_in_date_range:
            st.info(
                "No files found within the selected date range. Please adjust your date selection or upload more files.")
        else:  # This 'else' block is correctly matched with the 'if not files_in_date_range'
            # Display the list of files that will be analyzed
            st.markdown("##### Files to be analyzed based on selected dates:")
            for f_info in files_in_date_range:
                st.markdown(f"- `{f_info['name']}` (Date: {f_info['file_date'].strftime('%d %b %Y')})")

            # We now use the filtered files from the date range directly.
            selected_files_full_paths_dashboard = [f['full_path'] for f in files_in_date_range]
            
            # --- Processing files for analysis ---
            all_production_data = []
            all_error_data = []

            progress_text = "Processing files..."
            my_bar = st.progress(0, text=progress_text)

            for i, file_info_dict in enumerate(files_in_date_range): # Iterate through dicts for file_date
                file_full_path = file_info_dict['full_path']
                file_data = download_from_supabase(file_full_path)
                if file_data:
                    try:
                        xls = pd.ExcelFile(BytesIO(file_data))

                        # Iterate through ALL sheets in the Excel file
                        for sheet_name in xls.sheet_names:
                            df_raw_sheet = pd.read_excel(BytesIO(file_data), sheet_name=sheet_name, header=None)

                            original_filename = file_full_path.split('/')[-1]  # Extract original name from full path
                            # Pass original_filename and file_date_obj to read_production_data and read_error_data
                            prod_df = read_production_data(df_raw_sheet, original_filename, sheet_name, file_info_dict['file_date'])
                            err_df = read_error_data(df_raw_sheet, sheet_name, original_filename, file_info_dict['file_date'])

                            if not prod_df.empty:
                                all_production_data.append(prod_df)
                            if not err_df.empty:
                                all_error_data.append(err_df)

                    except Exception as e:
                        # General error during file processing (e.g., corrupted Excel)
                        st.error(f"Error processing Excel file '{file_full_path}': {e}")

                my_bar.progress((i + 1) / len(files_in_date_range), text=f"Processing file: {file_full_path}")

            my_bar.empty()

            final_prod_df = pd.concat(all_production_data, ignore_index=True) if all_production_data else pd.DataFrame()
            final_err_df = pd.concat(all_error_data, ignore_index=True) if all_error_data else pd.DataFrame()

            # --- Machine Selection Filter ---
            unique_machines = ['All Machines']
            if not final_prod_df.empty and "ProductionTypeForTon" in final_prod_df.columns:
                filtered_unique_machines = [m for m in final_prod_df["ProductionTypeForTon"].unique().tolist() if
                                            m is not None]
                if "Unknown Machine" in filtered_unique_machines:
                    filtered_unique_machines.remove("Unknown Machine")
                    filtered_unique_machines.append("Unknown Machine")
                unique_machines.extend(sorted(filtered_unique_machines))

            selected_machine = st.selectbox("Select Machine:", unique_machines)

            # Filter by machine first
            filtered_prod_df_by_machine = final_prod_df.copy()
            filtered_err_df_by_machine = final_err_df.copy()

            if selected_machine != 'All Machines':
                filtered_prod_df_by_machine = final_prod_df[
                    final_prod_df["ProductionTypeForTon"] == selected_machine].copy()
                filtered_err_df_by_machine = final_err_df[filtered_err_df_by_machine["MachineType"] == selected_machine].copy()

            # --- ALL PRODUCTS WILL BE SHOWN BY DEFAULT ---
            # No product multiselect in sidebar.
            # filtered_prod_df_by_product now directly takes the machine-filtered data.
            filtered_prod_df_by_product = filtered_prod_df_by_machine.copy()

            # Error data filtered only by machine, as product filter is removed.
            filtered_err_df_by_product = filtered_err_df_by_machine.copy()

            # chart_prod_df is now directly the filtered production data
            chart_prod_df = filtered_prod_df_by_product.copy()

            # --- Conditional styling function for Efficiency(%) ---
            def highlight_efficiency(val):
                color = ''
                if pd.isna(val):
                    return ''
                val = float(val)  # Convert to float for robust comparison
                if val > 100:
                    color = 'red'
                elif 90 <= val <= 100:
                    color = 'orange'  # Using orange for better visibility than yellow
                return f'color: {color}'


            # --- Display Combined Production Data ---
            st.subheader("Combined Production Data from Selected Files")
            if not filtered_prod_df_by_product.empty:
                # Apply conditional styling using the .style accessor
                st.dataframe(
                    filtered_prod_df_by_product.style.applymap(
                        highlight_efficiency, subset=['Efficiency(%)']
                    ).format({"Efficiency(%)": "{:.2f} %"}),  # Format for display
                    use_container_width=True
                )
            else:
                st.warning("No production data found for selected machine and date range. Please check your filters.")


            # --- Charts Section ---
            if not chart_prod_df.empty:
                st.subheader("Total Production (Tons) by Product")
                total_ton_per_product = chart_prod_df.groupby("Product")["Ton"].sum().reset_index()
                # Sort by Ton in descending order for better clarity (important for treemaps too)
                total_ton_per_product = total_ton_per_product.sort_values(by="Ton", ascending=False)

                # Changed to treemap
                fig1 = px.treemap(total_ton_per_product, path=[px.Constant("All Products"), 'Product'], values="Ton",
                                  title="Total Production (Tons) by Product",
                                  hover_data=['Ton'],
                                  color="Product") # Color by product for distinction
                fig1.update_layout(margin=dict(t=50, l=25, r=25, b=25)) # Adjust margins for treemap
                st.plotly_chart(fig1, use_container_width=True)

                st.subheader("Waste Percentage by Product") # Updated title
                # Calculate aggregated waste percentage: (Sum of Waste / Sum of PackQty) * 100
                agg_waste_percent_df = chart_prod_df.groupby("Product").agg(
                    TotalWaste=('Waste', 'sum'),
                    TotalPackQty=('PackQty', 'sum')
                ).reset_index()
                agg_waste_percent_df["Waste(%)"] = np.where(
                    agg_waste_percent_df['TotalPackQty'] > 0,
                    (agg_waste_percent_df['TotalWaste'] / agg_waste_percent_df['TotalPackQty']) * 100,
                    0
                )
                # Sort by Waste(%) in descending order
                agg_waste_percent_df = agg_waste_percent_df.sort_values(by="Waste(%)", ascending=False)

                if not agg_waste_percent_df.empty:
                    # Changed to bar chart with Waste(%)
                    fig2 = px.bar(agg_waste_percent_df, x="Product", y="Waste(%)",
                                  title="Waste Percentage by Product",
                                  labels={"Waste(%)": "Waste (%)"},
                                  color="Product", # Assign distinct color to each product
                                  color_discrete_sequence=px.colors.qualitative.Plotly, # Use qualitative color scale
                                  text_auto=True)
                    fig2.update_traces(textfont_size=14, textfont_color='black', textfont_weight='bold')
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("No data found to display waste percentage.")

                st.subheader("Efficiency by Product")
                chart_prod_df['PotentialProduction'] = chart_prod_df['Capacity'] * \
                                                                     chart_prod_df['Duration']

                agg_efficiency_df = chart_prod_df.groupby("Product").agg(
                    TotalPackQty=('PackQty', 'sum'),
                    TotalPotentialProduction=('PotentialProduction', 'sum')
                ).reset_index()

                agg_efficiency_df["Efficiency(%)"] = (
                    agg_efficiency_df.apply(
                        lambda row: (row["TotalPackQty"] / row["TotalPotentialProduction"] * 100) if row[
                                                                                                         "TotalPotentialProduction"] > 0 else 0,
                        axis=1
                    )
                )
                agg_efficiency_df = agg_efficiency_df.sort_values(by="Efficiency(%)", ascending=False)

                if not agg_efficiency_df.empty:
                    # Keeping this as a bar chart as efficiency is not typically tree-like
                    fig_efficiency = px.bar(agg_efficiency_df, x="Product", y="Efficiency(%)",
                                            title="Average Efficiency by Product",
                                            color="Efficiency(%)",
                                            color_continuous_scale=px.colors.sequential.Greens,
                                            text_auto=True)
                    fig_efficiency.update_traces(textfont_size=14, textfont_color='black', textfont_weight='bold')
                    st.plotly_chart(fig_efficiency, use_container_width=True)
                else:
                    st.info("No data found to display efficiency.")
            else:
                st.warning("No production data available for charts after applying filters.")


            # --- Display Combined Error Data ---
            st.subheader("Downtime / Errors from Selected Files")
            if not filtered_err_df_by_product.empty:
                err_sum = filtered_err_df_by_product.groupby("Error")["Duration"].sum().reset_index()
                err_sum = err_sum.sort_values(by="Duration", ascending=False)
                
                # Keeping this as a bar chart
                fig3 = px.bar(err_sum, x="Error", y="Duration", title="Downtime by Error Type (Minutes)",
                              labels={"Duration": "Duration (minutes)"},
                              color="Error",
                              color_discrete_sequence=px.colors.qualitative.Plotly,
                              text_auto=True,
                              height=600)
                
                fig3.update_traces(textfont_size=14, textfont_color='black', textfont_weight='bold')
                
                fig3.update_layout(xaxis_tickangle=-45,
                                  margin=dict(b=150))
                
                st.plotly_chart(fig3, use_container_width=True)

                csv = err_sum.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download Error Summary Report",
                    csv,
                    file_name="error_summary.csv",
                    mime="text/csv"
                )
            else:
                st.info(f"No error data found for selected machine and date range in the current view.")

elif st.session_state.page == "Trend Analysis":
    st.header("📈 Trend Analysis")
    st.markdown("---")

    all_files_info = get_all_supabase_files()

    if not all_files_info:
        st.warning("No files available for trend analysis. Please upload files first.")
    else:
        min_available_date = min(f['file_date'] for f in all_files_info)
        max_available_date = max(f['file_date'] for f in all_files_info)

        col_start_date_trend, col_end_date_trend = st.columns(2)
        with col_start_date_trend:
            selected_start_date_trend = st.date_input(
                "Start Date for Trends:",
                value=st.session_state.get('trend_start_date', min_available_date), # Use specific trend date state
                min_value=min_available_date,
                max_value=max_available_date,
                key="trend_start_date_picker"
            )
        with col_end_date_trend:
            selected_end_date_trend = st.date_input(
                "End Date for Trends:",
                value=st.session_state.get('trend_end_date', max_available_date), # Use specific trend date state
                min_value=min_available_date,
                max_value=max_available_date,
                key="trend_end_date_picker"
            )

        # Update session state with selected dates
        st.session_state.trend_start_date = selected_start_date_trend
        st.session_state.trend_end_date = selected_end_date_trend

        if selected_end_date_trend < selected_start_date_trend:
            st.error("Error: End Date cannot be before Start Date. Please adjust.")
            st.stop()

        files_in_date_range_trend = [
            f for f in all_files_info
            if selected_start_date_trend <= f['file_date'] <= selected_end_date_trend
        ]

        if not files_in_date_range_trend:
            st.info("No files found within the selected date range for trend analysis. Please adjust your date selection or upload more files.")
        else:
            trend_all_production_data = []
            trend_all_error_data = []

            my_bar_trend = st.progress(0, text="Processing files for trend analysis...")
            for i, file_info_dict in enumerate(files_in_date_range_trend):
                file_full_path = file_info_dict['full_path']
                file_data = download_from_supabase(file_full_path)
                if file_data:
                    try:
                        xls = pd.ExcelFile(BytesIO(file_data))
                        for sheet_name in xls.sheet_names:
                            df_raw_sheet = pd.read_excel(BytesIO(file_data), sheet_name=sheet_name, header=None)
                            original_filename = file_full_path.split('/')[-1]

                            prod_df_trend = read_production_data(df_raw_sheet, original_filename, sheet_name, file_info_dict['file_date'])
                            err_df_trend = read_error_data(df_raw_sheet, sheet_name, original_filename, file_info_dict['file_date'])

                            if not prod_df_trend.empty:
                                trend_all_production_data.append(prod_df_trend)
                            if not err_df_trend.empty:
                                trend_all_error_data.append(err_df_trend)
                    except Exception as e:
                        st.error(f"Error processing Excel file '{file_info_dict['name']}' for trends: {e}")
                my_bar_trend.progress((i + 1) / len(files_in_date_range_trend))
            my_bar_trend.empty()

            trend_final_prod_df = pd.concat(trend_all_production_data, ignore_index=True) if trend_all_production_data else pd.DataFrame()
            trend_final_err_df = pd.concat(trend_all_error_data, ignore_index=True) if trend_all_error_data else pd.DataFrame()

            # Convert 'Date' column to datetime objects for proper resampling
            if not trend_final_prod_df.empty:
                trend_final_prod_df['Date'] = pd.to_datetime(trend_final_prod_df['Date'])
            if not trend_final_err_df.empty:
                trend_final_err_df['Date'] = pd.to_datetime(trend_final_err_df['Date'])


            # --- Trend Granularity Selection ---
            st.subheader("Trend Aggregation Level")
            granularity_options = {
                "Daily": "D",
                "Weekly": "W",
                "Monthly": "M",
                "Yearly": "Y"
            }
            selected_granularity_display = st.radio(
                "Group trends by:",
                options=list(granularity_options.keys()),
                horizontal=True,
                key="trend_granularity_radio"
            )
            selected_granularity_code = granularity_options[selected_granularity_display]

            # --- Machine Selection Filter for Trends ---
            trend_unique_machines = ['All Machines']
            if not trend_final_prod_df.empty and "ProductionTypeForTon" in trend_final_prod_df.columns:
                filtered_trend_unique_machines = [m for m in trend_final_prod_df["ProductionTypeForTon"].unique().tolist() if m is not None]
                if "Unknown Machine" in filtered_trend_unique_machines:
                    filtered_trend_unique_machines.remove("Unknown Machine")
                    filtered_trend_unique_machines.append("Unknown Machine")
                trend_unique_machines.extend(sorted(filtered_trend_unique_machines))

            trend_selected_machine = st.selectbox("Select Machine for Trends:", trend_unique_machines, key="trend_machine_select")

            trend_filtered_prod_df_by_machine = trend_final_prod_df.copy()
            trend_filtered_err_df_by_machine = trend_final_err_df.copy()

            if trend_selected_machine != 'All Machines':
                trend_filtered_prod_df_by_machine = trend_final_prod_df[trend_final_prod_df["ProductionTypeForTon"] == trend_selected_machine].copy()
                trend_filtered_err_df_by_machine = trend_final_err_df[trend_final_err_df["MachineType"] == trend_selected_machine].copy()

            # --- Product Selection for Trends (Optional, for detailed product view) ---
            # Get unique products based on filtered machine data
            all_available_products_for_trend = ['All Products']
            if not trend_filtered_prod_df_by_machine.empty:
                valid_products = [p for p in trend_filtered_prod_df_by_machine['Product'].unique().tolist() if p]
                all_available_products_for_trend.extend(sorted(valid_products))

            trend_selected_products = st.multiselect(
                "Select Specific Product(s) for Detailed Trend (Optional):",
                options=all_available_products_for_trend,
                default=['All Products'] # Default to all products
            )

            # Filter by selected products
            if 'All Products' in trend_selected_products:
                # If 'All Products' is selected, ignore other product selections and use all data
                trend_filtered_prod_df_by_product = trend_filtered_prod_df_by_machine.copy()
            else:
                trend_filtered_prod_df_by_product = trend_filtered_prod_df_by_machine[
                    trend_filtered_prod_df_by_machine['Product'].isin(trend_selected_products)
                ].copy()

            # Error data is still filtered only by machine
            trend_filtered_err_df_final = trend_filtered_err_df_by_machine.copy()


            # --- Plotting Production Trends ---
            st.markdown("### Production Trends")
            if not trend_filtered_prod_df_by_product.empty:
                # Set 'Date' as index for resampling
                prod_df_resampled = trend_filtered_prod_df_by_product.set_index('Date')

                # Daily Total Production (Tons) - Resampled
                daily_total_ton = prod_df_resampled.resample(selected_granularity_code)["Ton"].sum().reset_index()
                # Filter out periods with 0 production (meaning no data for that period)
                daily_total_ton = daily_total_ton[daily_total_ton['Ton'] > 0]
                
                if not daily_total_ton.empty:
                    fig_daily_ton = px.line(daily_total_ton, x="Date", y="Ton",
                                            title=f"{selected_granularity_display} Total Production (Tons) Trend", markers=True)
                    st.plotly_chart(fig_daily_ton, use_container_width=True)
                else:
                    st.info(f"No total production data to display for the selected filters and {selected_granularity_display} granularity.")

                # Daily Production (Tons) by Product - Resampled (only if specific products are chosen or if "All Products" is chosen and there aren't too many products)
                if 'All Products' in trend_selected_products or len(trend_selected_products) < 10: # Heuristic to prevent too many lines
                    daily_product_ton = prod_df_resampled.groupby([pd.Grouper(freq=selected_granularity_code), "Product"])["Ton"].sum().reset_index()
                    # Filter out periods with 0 production (meaning no data for that period for a given product)
                    daily_product_ton = daily_product_ton[daily_product_ton['Ton'] > 0]

                    if not daily_product_ton.empty:
                        fig_daily_product_ton = px.line(daily_product_ton, x="Date", y="Ton", color="Product",
                                                        title=f"{selected_granularity_display} Production (Tons) Trend by Product", markers=True)
                        st.plotly_chart(fig_daily_product_ton, use_container_width=True)
                    else:
                        st.info(f"No production data by product to display for the selected filters and {selected_granularity_display} granularity.")
                else:
                    st.info(f"Select fewer products for a readable {selected_granularity_display} trend by product, or select 'All Products'.")


                # Daily Efficiency Trend - Resampled
                daily_efficiency_data = prod_df_resampled.groupby(pd.Grouper(freq=selected_granularity_code)).agg(
                    TotalPackQty=('PackQty', 'sum'),
                    TotalPotentialProduction=('PotentialProduction', 'sum')
                ).reset_index()
                daily_efficiency_data["Efficiency(%)"] = np.where(
                    daily_efficiency_data['TotalPotentialProduction'] > 0,
                    (daily_efficiency_data['TotalPackQty'] / daily_efficiency_data['TotalPotentialProduction']) * 100,
                    0
                )
                # Filter out periods with 0 efficiency (meaning no production data for that period)
                daily_efficiency_data = daily_efficiency_data[daily_efficiency_data['TotalPackQty'] > 0] # Filter by total pack qty > 0

                if not daily_efficiency_data.empty:
                    fig_daily_efficiency = px.line(daily_efficiency_data, x="Date", y="Efficiency(%)",
                                                   title=f"{selected_granularity_display} Average Efficiency (%) Trend", markers=True)
                    st.plotly_chart(fig_daily_efficiency, use_container_width=True)
                else:
                    st.info(f"No efficiency data to display for the selected filters and {selected_granularity_display} granularity.")

                # Daily Waste Trend - Resampled
                daily_waste_data = prod_df_resampled.groupby(pd.Grouper(freq=selected_granularity_code)).agg(
                    TotalWaste=('Waste', 'sum'),
                    TotalPackQty=('PackQty', 'sum')
                ).reset_index()
                daily_waste_data["Waste(%)"] = np.where(
                    daily_waste_data['TotalPackQty'] > 0,
                    (daily_waste_data['TotalWaste'] / daily_waste_data['TotalPackQty']) * 100,
                    0
                )
                # Filter out periods with 0 total pack qty (meaning no production data to calculate waste %)
                daily_waste_data = daily_waste_data[daily_waste_data['TotalPackQty'] > 0]

                if not daily_waste_data.empty:
                    fig_daily_waste = px.line(daily_waste_data, x="Date", y="Waste(%)",
                                              title=f"{selected_granularity_display} Average Waste (%) Trend", markers=True)
                    st.plotly_chart(fig_daily_waste, use_container_width=True)
                else:
                    st.info(f"No waste data to display for the selected filters and {selected_granularity_display} granularity.")

            else:
                st.info("No production data available for trend analysis after applying filters.")

            # --- Plotting Downtime Trends ---
            st.markdown("### Downtime / Error Trends")
            if not trend_filtered_err_df_final.empty:
                # Set 'Date' as index for resampling
                err_df_resampled = trend_filtered_err_df_final.set_index('Date')

                # Daily Total Downtime
                total_downtime = err_df_resampled.resample(selected_granularity_code)["Duration"].sum().reset_index()
                # Filter out periods with 0 downtime (meaning no errors for that period)
                total_downtime = total_downtime[total_downtime['Duration'] > 0]

                if not total_downtime.empty:
                    fig_total_downtime = px.line(total_downtime, x="Date", y="Duration",
                                                 title=f"{selected_granularity_display} Total Downtime (Minutes) Trend", markers=True)
                    st.plotly_chart(fig_total_downtime, use_container_width=True)
                else:
                    st.info(f"No total downtime data to display for the selected filters and {selected_granularity_display} granularity.")


                # Daily Downtime by Error Type - Resampled (only if specific errors are chosen or not too many error types)
                all_available_errors_for_trend = ['All Errors']
                if not trend_filtered_err_df_final.empty:
                    valid_errors = [e for e in trend_filtered_err_df_final['Error'].unique().tolist() if e]
                    all_available_errors_for_trend.extend(sorted(valid_errors))

                trend_selected_errors = st.multiselect(
                    "Select Specific Error Type(s) for Detailed Trend (Optional):",
                    options=all_available_errors_for_trend,
                    default=['All Errors'] # Default to all errors
                )

                if 'All Errors' in trend_selected_errors:
                    err_by_type_resampled = err_df_resampled.groupby([pd.Grouper(freq=selected_granularity_code), "Error"])["Duration"].sum().reset_index()
                    # Filter out periods with 0 duration for specific error types
                    err_by_type_resampled = err_by_type_resampled[err_by_type_resampled['Duration'] > 0]

                    if len(err_by_type_resampled['Error'].unique()) > 10: # Heuristic for too many lines
                        st.info(f"Too many error types to display a readable {selected_granularity_display} trend by error type. Please select specific error types above.")
                    elif not err_by_type_resampled.empty:
                        fig_daily_error_type = px.line(err_by_type_resampled, x="Date", y="Duration", color="Error",
                                                       title=f"{selected_granularity_display} Downtime (Minutes) Trend by Error Type", markers=True)
                        st.plotly_chart(fig_daily_error_type, use_container_width=True)
                    else:
                        st.info(f"No downtime data by error type to display for the selected filters and {selected_granularity_display} granularity.")
                else:
                    err_by_type_resampled_filtered = err_df_resampled[err_df_resampled['Error'].isin(trend_selected_errors)].groupby([pd.Grouper(freq=selected_granularity_code), "Error"])["Duration"].sum().reset_index()
                    # Filter out periods with 0 duration for specific error types
                    err_by_type_resampled_filtered = err_by_type_resampled_filtered[err_by_type_resampled_filtered['Duration'] > 0]

                    if not err_by_type_resampled_filtered.empty:
                        fig_daily_error_type_filtered = px.line(err_by_type_resampled_filtered, x="Date", y="Duration", color="Error",
                                                                title=f"{selected_granularity_display} Downtime (Minutes) Trend for Selected Error Types", markers=True)
                        st.plotly_chart(fig_daily_error_type_filtered, use_container_width=True)
                    else:
                        st.info("No data for selected error types in the chosen date range and granularity.")

            else:
                st.info("No error data available for trend analysis after applying filters.")

elif st.session_state.page == "Contact Me":
    st.subheader("Connect with Mohammad Asadollahzadeh")
    st.markdown("---")
    st.markdown("""
    In today’s cutting-edge world, with rapid advances in technology, AI is no longer optional—it’s essential. Using AI can significantly boost performance, minimize human error, and streamline workflows. Relying solely on traditional methods often results in wasted time and effort, without delivering the efficiency we seek.

To address this, I’ve started building a platform that blends automation with intelligence. Driven by my passion for Python—despite still learning—and a deep interest in creating disciplined, data-driven technical solutions, I began developing this Streamlit-based website to analyze daily production performance.

While my Python skills are still growing, I’ve poured in patience, dedication, and curiosity. Throughout the process, tools like Gemini AI were instrumental in helping me debug, refine strategies, and bring this idea to life. Frankly, without AI assistance, reaching this point would have been far more difficult.

That said, I’m committed to improving—both in coding and system design. I welcome your feedback, suggestions, or any guidance to help enhance this platform further.

📧 Email: m.asdz@yahoo.com
🔗 LinkedIn: Mohammad Asdollahzadeh

Thank you for visiting, and I truly appreciate your support.

Warm regards,
Mohammad Asdollahzadeh


   
    """)
