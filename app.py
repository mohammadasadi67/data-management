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
            # Treat raw float as hours and convert to minutes
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
    UPDATED: Calculate Target_Hour using NominalSpeed (Capacity).
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
        "cap": "Capacity", # This is the Nominal Speed
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
    required_cols = ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Date", 
                     "Waste", "ProductionTypeForTon"]
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
    # If EndTime is less than StartTime, it means the time crosses midnight.
    # Add 24 hours to EndTime.
    data['EndTimeAdjusted'] = data.apply(
        lambda row: row['EndTime'] + 24 if row['EndTime'] < row['StartTime'] else row['EndTime'], axis=1)

    # Calculate Duration in hours using the adjusted EndTime
    data["Duration"] = data["EndTimeAdjusted"] - data["StartTime"]
    data = data.dropna(subset=["Duration"])  # Drop rows where duration couldn't be calculated (e.g., missing Start/End)
    data = data[data["Duration"] != 0]  # Remove rows with 0 duration

    # Convert numeric columns, coercing errors to NaN and then filling with 0
    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    
    # NEW: Use 'Capacity' as 'NominalSpeed'
    data["NominalSpeed"] = pd.to_numeric(data["Capacity"], errors="coerce").fillna(0)
    data = data.drop(columns=['Capacity'], errors='ignore') # Remove the old Capacity column
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)

    # Calculate Ton - this calculation is per-row and correct here
    data["Ton"] = data.apply(calculate_ton, axis=1)

    # NEW: Calculate Target Hour (Production Quantity / Nominal Speed)
    # Target Hour is in hours
    data['Target_Hour'] = np.where(
        data['NominalSpeed'] > 0,
        data['PackQty'] / data['NominalSpeed'],
        0
    )
    
    # OLD: Keep previous efficiency calculation (PotentialProduction) but remove Efficiency(%) column
    data['PotentialProduction'] = data['NominalSpeed'] * data['Duration']
    # data['Efficiency(%)'] = np.where( # REMOVED: Efficiency(%) based on user request
    #     data['PotentialProduction'] > 0,
    #     (data['PackQty'] / data['PotentialProduction']) * 100,
    #     0
    # )

    # Select and order final columns for the output DataFrame
    final_cols = ["Date", "Product", "NominalSpeed", "Manpower", "Duration", "PackQty", "Waste", "Ton",
                  "PotentialProduction", "Target_Hour", "ProductionTypeForTon"] # Efficiency(%) removed
    
    # Ensure all columns exist before selecting
    for col in final_cols:
        if col not in data.columns:
            data[col] = 0 # Add missing columns (especially 'Target_Hour')

    data = data[[col for col in final_cols if col in data.columns]]

    return data


def read_error_data(df_raw_sheet, sheet_name_for_debug="Unknown Sheet", uploaded_file_name_for_debug="Unknown File", file_date_obj=None):
    """
    Reads error data from the Excel sheet.
    NEW LOGIC: Finds the row with 'f12' header, unpivots columns f12 to f100 
    (which contain duration in minutes) into Error and Duration rows.
    """
    try:
        # 1. Find the header row containing 'f12' (case-insensitive)
        header_row = None
        for r in range(df_raw_sheet.shape[0]):
             if any(str(c).lower().strip().startswith('f12') for c in df_raw_sheet.iloc[r]):
                 header_row = r
                 break
        
        if header_row is None:
             # st.info(f"Info: No 'f12' header found for error data in {uploaded_file_name_for_debug}/{sheet_name_for_debug}.")
             return pd.DataFrame() 

        # 2. Reread the error section with the correct header
        error_section_df = df_raw_sheet.iloc[header_row:].copy()
        error_section_df.columns = error_section_df.iloc[0].astype(str).str.lower().str.strip() # Use the identified row as header (lowercase and stripped)
        error_section_df = error_section_df[1:].reset_index(drop=True) # Data rows below header
        
        # 3. Select fXX columns
        error_duration_cols_pattern = [f'f{i}' for i in range(12, 101)] 
        # Filter for existing columns that start with 'f' followed by the code
        cols_to_melt = [col for col in error_section_df.columns if col in error_duration_cols_pattern]
        
        if not cols_to_melt:
            # st.info(f"Info: No f12 to f100 columns found after header detection in {uploaded_file_name_for_debug}/{sheet_name_for_debug}.")
            return pd.DataFrame()

        # 4. Melt (Unpivot) the DataFrame
        # We don't have an ID column, so we melt the values and rely on the date later.
        df_long = error_section_df.melt(
            value_vars=cols_to_melt,
            var_name='RawErrorColumn',
            value_name='Duration' # This is already the RawDuration in minutes
        )
        
        # 5. Process Duration and Error Code
        df_long['Duration'] = pd.to_numeric(df_long['Duration'], errors='coerce').fillna(0)
        df_long = df_long[df_long['Duration'] > 0].copy()
        
        # Extract the Error Code from the column name (fXX -> XX)
        df_long['Error'] = df_long['RawErrorColumn'].str.replace('f', '', regex=False).astype(str).str.strip()
        
        # 6. Aggregate by 'Error' (Sum durations for the same error code across all rows in the sheet)
        aggregated_errors = df_long.groupby("Error")["Duration"].sum().reset_index()
        
        # Remove rows where the error code is not purely numeric 
        aggregated_errors = aggregated_errors[aggregated_errors['Error'].str.isnumeric()].copy()
        
        # 7. Add Date and MachineType
        aggregated_errors['Date'] = file_date_obj
        # Ensure we use the determined machine type, even if the sheet name is complex.
        machine_type = determine_machine_type(sheet_name_for_debug)
        if machine_type == "Unknown Machine":
             machine_type = determine_machine_type(uploaded_file_name_for_debug)
        aggregated_errors['MachineType'] = machine_type

        return aggregated_errors.dropna(subset=['Date'])
    
    except Exception as e:
        st.error(
            f"Error in file '{uploaded_file_name_for_debug}' (Sheet: '{sheet_name_for_debug}'): An unexpected error occurred while processing error data: `{e}`")
        return pd.DataFrame()

# --- NEW CORE METRICS CALCULATION FUNCTION ---
def calculate_metrics(prod_df: pd.DataFrame, err_df: pd.DataFrame, group_cols: list) -> pd.DataFrame:
    """
    Calculates Line Efficiency and OE based on the new 24-hour cycle logic, 
    grouped by the specified columns (e.g., ['Date', 'Product'] or ['Date', 'ProductionTypeForTon']).
    """
    if prod_df.empty:
        return pd.DataFrame()

    # --- 1. Aggregate Production Data ---
    # Need to handle case where 'Product' is not in group_cols (e.g., when grouping by Machine)
    prod_group_cols = [col for col in group_cols if col in prod_df.columns]
    
    prod_agg = prod_df.groupby(prod_group_cols).agg(
        Total_Target_Hour=('Target_Hour', 'sum'),
        Total_Duration=('Duration', 'sum'),
        Total_PackQty=('PackQty', 'sum')
    ).reset_index()

    if err_df.empty:
        # If no error data, fall back to simple efficiency based on actual running time (Total_Duration)
        # However, for 24-hour based metrics, we cannot calculate accurately without error data.
        # Fallback to 0 for downtime-related metrics to ensure continuity.
        prod_agg['NetProduction_H'] = prod_agg['Total_Duration']
        # We need a proxy for Total_Duration if we can't rely on the full 24hr calculation
        # If we can't calculate Gross/Net Production Hour, we cannot calculate LE/OE properly.
        # Set them to 0 and rely on the warning later.
        prod_agg['Line_Efficiency(%)'] = 0.0
        prod_agg['OE(%)'] = 0.0
        prod_agg['LegalStoppage_H'] = 0.0
        prod_agg['IdleTime_H'] = 0.0
        prod_agg['Downtime_H'] = 0.0
        prod_agg['Losses_H'] = 0.0
        prod_agg['OE_Adjust_H'] = 0.0
        return prod_agg

    # --- 2. Aggregate Error Data and Convert to Hours ---
    
    daily_err_agg = err_df.copy() 
    daily_err_agg['Error'] = daily_err_agg['Error'].astype(str).str.strip()

    # Helper function to sum duration (in minutes) for specific codes and convert to hours
    def sum_duration_for_codes(df, codes):
        codes_str = [str(c) for c in codes]
        # Duration is in minutes (from read_error_data) -> convert to hours by dividing by 60
        return df[df['Error'].isin(codes_str)]['Duration'].sum() / 60 

    # Aggregate all error categories by the most detailed grouping possible in the error data (Date and MachineType)
    err_summary = daily_err_agg.groupby(['Date', 'MachineType']).apply(lambda x: pd.Series({
        'LegalStoppage_H': sum_duration_for_codes(x, ['33']),
        'IdleTime_H': sum_duration_for_codes(x, ['32']),
        'Downtime_H': sum_duration_for_codes(x, [str(c) for c in range(21, 32)]), # 21 to 31
        'Losses_H': sum_duration_for_codes(x, [str(c) for c in range(1, 21)]), # 1 to 20
        'OE_Adjust_H': sum_duration_for_codes(x, ['24', '25']) 
    })).reset_index()
    
    # --- 3. Merge Production and Error Data ---
    
    # Rename 'ProductionTypeForTon' in prod_agg to 'MachineType' for merging if necessary
    prod_agg_temp = prod_agg.copy()
    if 'ProductionTypeForTon' in prod_agg_temp.columns:
         prod_agg_temp = prod_agg_temp.rename(columns={'ProductionTypeForTon': 'MachineType'})
         merge_cols = ['Date', 'MachineType']
    else:
         merge_cols = ['Date'] # Fallback if no machine type available

    # Perform the merge using the common columns (Date and MachineType)
    daily_metrics = pd.merge(prod_agg_temp, err_summary, on=merge_cols, how='left').fillna(0)
    
    # --- 4. Define Time Variables (in Hours) ---
    Total_Day_Hours = 24.0 # 6 morning to 6 morning next day is 24 hours
    
    # Gross Production Hour = 24 - Legal Stoppage - Idle Time
    daily_metrics['GrossProduction_H'] = Total_Day_Hours - daily_metrics['LegalStoppage_H'] - daily_metrics['IdleTime_H']
    
    # Net Production Hour = Gross Production Hour - Downtime
    # Downtime includes codes 21 to 31
    daily_metrics['NetProduction_H'] = daily_metrics['GrossProduction_H'] - daily_metrics['Downtime_H']
    
    # --- 5. Calculate Line Efficiency and OE ---
    
    # Line Efficiency = Target Hour / Net Production Hour
    daily_metrics['Line_Efficiency(%)'] = np.where(
        daily_metrics['NetProduction_H'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['NetProduction_H']) * 100,
        0
    )
    
    # OE = (Target Hour / (Net Production + code 24 and code 25)) * 100
    daily_metrics['OE_Denominator'] = daily_metrics['NetProduction_H'] + daily_metrics['OE_Adjust_H']
    daily_metrics['OE(%)'] = np.where(
        daily_metrics['OE_Denominator'] > 0,
        (daily_metrics['Total_Target_Hour'] / daily_metrics['OE_Denominator']) * 100,
        0
    )
    
    # Rename MachineType back to ProductionTypeForTon if Product metrics are calculated (for consistency)
    if 'Product' in group_cols and 'MachineType' in daily_metrics.columns:
        daily_metrics = daily_metrics.rename(columns={'MachineType': 'ProductionTypeForTon'})

    return daily_metrics

# --- Main Application ---

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
        else:
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
                            # Read the sheet with no header to process headers manually later
                            df_raw_sheet = pd.read_excel(BytesIO(file_data), sheet_name=sheet_name, header=None)
                            original_filename = file_full_path.split('/')[-1] # Extract original name from full path

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
                filtered_unique_machines = [m for m in final_prod_df["ProductionTypeForTon"].unique().tolist() if m is not None]
                if "Unknown Machine" in filtered_unique_machines:
                    filtered_unique_machines.remove("Unknown Machine")
                    filtered_unique_machines.append("Unknown Machine")
                unique_machines.extend(sorted(filtered_unique_machines))
            
            # Select Machine for Filtering
            selected_machine = st.selectbox("Select Machine:", unique_machines)

            # Filter by machine first
            filtered_prod_df_by_machine = final_prod_df.copy()
            filtered_err_df_by_machine = final_err_df.copy()
            
            if selected_machine != 'All Machines':
                # Filter production data
                filtered_prod_df_by_machine = final_prod_df[
                    final_prod_df["ProductionTypeForTon"] == selected_machine].copy()
                
                # *** FIX: Check if MachineType exists BEFORE attempting to filter error data ***
                if not final_err_df.empty and "MachineType" in final_err_df.columns:
                    filtered_err_df_by_machine = final_err_df[
                        final_err_df["MachineType"] == selected_machine].copy()
                else:
                    # If error data is missing the column or is empty, use an empty DataFrame
                    filtered_err_df_by_machine = pd.DataFrame()


            # --- ALL PRODUCTS WILL BE SHOWN BY DEFAULT ---
            filtered_prod_df_by_product = filtered_prod_df_by_machine.copy()
            
            # chart_prod_df is now directly the filtered production data
            chart_prod_df = filtered_prod_df_by_product.copy()

            
            # =========================================================================
            # --- NEW: Daily Efficiency and OE Calculations (Per Machine and Per Product) ---
            # =========================================================================

            if not filtered_prod_df_by_product.empty:
                st.subheader("Daily Overall Equipment Effectiveness (OE) & Line Efficiency")

                # 1. Calculate Daily Metrics by MACHINE (Grouping by Date and MachineType)
                daily_machine_metrics = calculate_metrics(
                    prod_df=filtered_prod_df_by_product.copy(),
                    err_df=filtered_err_df_by_machine.copy(),
                    group_cols=['Date', 'ProductionTypeForTon']
                )

                # --- Display Machine Metrics ---
                st.markdown("#### Machine Efficiency & OE Summary")

                # Display Overall Metrics for the entire period for the Machine
                total_target_h_m = daily_machine_metrics['Total_Target_Hour'].sum()
                total_net_prod_h_m = daily_machine_metrics['NetProduction_H'].sum()
                total_oe_adjust_h_m = daily_machine_metrics['OE_Adjust_H'].sum()

                overall_line_eff_m = (total_target_h_m / total_net_prod_h_m) * 100 if total_net_prod_h_m > 0 else 0
                overall_oe_m = (total_target_h_m / (total_net_prod_h_m + total_oe_adjust_h_m)) * 100 if (total_net_prod_h_m + total_oe_adjust_h_m) > 0 else 0

                col_eff_m, col_oe_m, col_time_m = st.columns(3)
                with col_eff_m:
                    st.metric(
                        label=f"Overall Line Efficiency ({selected_machine})", 
                        value=f"{overall_line_eff_m:.2f} %",
                        help="Target Hour / Net Production Hour"
                    )
                with col_oe_m:
                    st.metric(
                        label=f"Overall OE ({selected_machine})", 
                        value=f"{overall_oe_m:.2f} %",
                        help="Target Hour / (Net Production Hour + Code 24 & 25 Hours)"
                    )
                with col_time_m:
                    st.metric(
                        label="Total Target Hours (Period)",
                        value=f"{total_target_h_m:.2f} hrs",
                        help="Sum of (PackQty / NominalSpeed) over all production rows"
                    )

                st.markdown("##### Daily Breakdown (Machine):")
                display_cols_m = ['Date', 'ProductionTypeForTon', 'Line_Efficiency(%)', 'OE(%)', 'Total_Target_Hour', 'NetProduction_H', 'Downtime_H', 'Losses_H', 'IdleTime_H', 'LegalStoppage_H']
                
                # Filter columns based on availability after calculation
                available_cols_m = [col for col in display_cols_m if col in daily_machine_metrics.columns]
                
                st.dataframe(
                    daily_machine_metrics[available_cols_m].style.format({
                        'Line_Efficiency(%)': "{:.2f} %",
                        'OE(%)': "{:.2f} %",
                        'Total_Target_Hour': "{:.2f}",
                        'NetProduction_H': "{:.2f}",
                        'Downtime_H': "{:.2f}",
                        'Losses_H': "{:.2f}",
                        'IdleTime_H': "{:.2f}",
                        'LegalStoppage_H': "{:.2f}"
                    }),
                    use_container_width=True
                )
                
                # --- REMOVED: Machine Efficiency & OE Trend (Daily) ---
                # This entire section was previously here and has been removed as requested.

                st.markdown("---") 

                # 2. Calculate Daily Metrics by PRODUCT (Grouping by Date and Product)
                daily_product_metrics = calculate_metrics(
                    prod_df=filtered_prod_df_by_product.copy(),
                    err_df=filtered_err_df_by_machine.copy(), # Note: Error data is only available at Machine/Date level, so we merge it with Date/Product.
                    group_cols=['Date', 'Product', 'ProductionTypeForTon'] # We need ProductionTypeForTon for merging with error data inside the function
                )

                # --- Display Product Metrics ---
                st.subheader(f"Daily Line Efficiency & OE per Product (Machine: {selected_machine})")

                # Overall Metrics by Product (Aggregated over all dates in the period)
                overall_product_metrics = daily_product_metrics.groupby('Product').agg(
                    Total_Target_Hour=('Total_Target_Hour', 'sum'),
                    Total_NetProduction_H=('NetProduction_H', 'sum'),
                    Total_OE_Adjust_H=('OE_Adjust_H', 'sum')
                ).reset_index()

                overall_product_metrics['Line_Efficiency(%)'] = np.where(
                    overall_product_metrics['Total_NetProduction_H'] > 0,
                    (overall_product_metrics['Total_Target_Hour'] / overall_product_metrics['Total_NetProduction_H']) * 100,
                    0
                )
                overall_product_metrics['OE(%)'] = np.where(
                    (overall_product_metrics['Total_NetProduction_H'] + overall_product_metrics['Total_OE_Adjust_H']) > 0,
                    (overall_product_metrics['Total_Target_Hour'] / (overall_product_metrics['Total_NetProduction_H'] + overall_product_metrics['Total_OE_Adjust_H'])) * 100,
                    0
                )

                st.markdown("##### Overall Metrics by Product (Selected Period):")
                display_cols_p_overall = ['Product', 'Line_Efficiency(%)', 'OE(%)', 'Total_Target_Hour', 'Total_NetProduction_H']
                st.dataframe(
                    overall_product_metrics[display_cols_p_overall].style.format({
                        'Line_Efficiency(%)': "{:.2f} %",
                        'OE(%)': "{:.2f} %",
                        'Total_Target_Hour': "{:.2f}",
                        'Total_NetProduction_H': "{:.2f}"
                    }),
                    use_container_width=True
                )

                st.markdown("##### Daily Breakdown by Product:")
                display_cols_p_daily = ['Date', 'Product', 'Line_Efficiency(%)', 'OE(%)', 'Total_Target_Hour', 'NetProduction_H']

                st.dataframe(
                    daily_product_metrics[display_cols_p_daily].style.format({
                        'Line_Efficiency(%)': "{:.2f} %",
                        'OE(%)': "{:.2f} %",
                        'Total_Target_Hour': "{:.2f}",
                        'NetProduction_H': "{:.2f}"
                    }),
                    use_container_width=True
                )
                
                st.markdown("---") 
            # End of NEW OE/LE SECTION
            
            # --- Display Combined Production Data ---
            st.subheader("Combined Production Data from Selected Files (Row-Level)")
            if not filtered_prod_df_by_product.empty:
                # Prepare DataFrame without 'Efficiency(%)' and other non-display columns
                prod_display_cols = [col for col in filtered_prod_df_by_product.columns if col not in ['PotentialProduction', 'ProductionTypeForTon']]
                
                st.dataframe(
                    filtered_prod_df_by_product[prod_display_cols],
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
                                  title="Total Production (Tons) by Product", hover_data=['Ton'], color="Product") 
                # Color by product for distinction
                fig1.update_layout(margin=dict(t=50, l=25, r=25, b=25))  # Adjust margins for treemap
                st.plotly_chart(fig1, use_container_width=True)

                st.subheader("Waste Percentage by Product")
                # Updated title
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
                    fig2 = px.bar(agg_waste_percent_df, x="Product", y="Waste(%)", title="Waste Percentage by Product",
                                  labels={"Waste(%)": "Waste (%)"}, color="Product", 
                                  color_discrete_sequence=px.colors.qualitative.Plotly,  # Use qualitative color scale
                                  text_auto=True)
                    fig2.update_traces(textfont_size=14, textfont_color='black', textfont_weight='bold')
                    st.plotly_chart(fig2, use_container_width=True)
                else:
                    st.info("No data found to display waste percentage.")

                # --- NEW CHART: Line Efficiency & OE by Product (Overall) ---
                # THIS IS THE REQUESTED REPLACEMENT CHART
                st.subheader("Overall Line Efficiency & OE by Product (Selected Period)")
                if not overall_product_metrics.empty:
                    # Melt the overall product metrics for Line Efficiency and OE
                    product_metrics_melted = overall_product_metrics.melt(
                        id_vars=['Product'],
                        value_vars=['Line_Efficiency(%)', 'OE(%)'],
                        var_name='Metric',
                        value_name='Percentage'
                    )
                    
                    # Sort for better visualization (e.g., by Line Efficiency descending)
                    sort_order = overall_product_metrics.sort_values(by='Line_Efficiency(%)', ascending=False)['Product'].tolist()
                    product_metrics_melted['Product'] = pd.Categorical(product_metrics_melted['Product'], categories=sort_order, ordered=True)
                    product_metrics_melted = product_metrics_melted.sort_values('Product')

                    fig_le_oe_product = px.bar(
                        product_metrics_melted, 
                        x="Product", 
                        y="Percentage", 
                        color="Metric",
                        barmode='group', # Group bars for each product
                        title="Overall Line Efficiency and OE by Product (Selected Period)", 
                        labels={"Percentage": "Percentage (%)"},
                        text_auto='.2f',
                        height=500
                    )
                    fig_le_oe_product.update_traces(textposition='outside')
                    fig_le_oe_product.update_layout(yaxis_range=[0, product_metrics_melted['Percentage'].max() * 1.1])
                    st.plotly_chart(fig_le_oe_product, use_container_width=True)
                else:
                    st.info("No calculated Line Efficiency or OE data found to display by product.")
                
                # --- REMOVED: Efficiency by Product (Original Formula) ---
                # This entire section was previously here and has been removed as requested.

            else:
                st.warning("No production data available for charts after applying filters.")

            # --- Display Combined Error Data ---
            st.subheader("Downtime / Errors from Selected Files (Minutes)")
            if not filtered_err_df_by_machine.empty:
                err_sum = filtered_err_df_by_machine.groupby("Error")["Duration"].sum().reset_index()
                err_sum = err_sum.sort_values(by="Duration", ascending=False)
                # Keeping this as a bar chart
                fig3 = px.bar(err_sum, x="Error", y="Duration", title="Downtime by Error Type (Minutes)",
                              labels={"Duration": "Duration (minutes)"}, color="Error",
                              color_discrete_sequence=px.colors.qualitative.Plotly, text_auto=True, height=600)
                fig3.update_traces(textfont_size=14, textfont_color='black', textfont_weight='bold')
                fig3.update_layout(xaxis_tickangle=-45, margin=dict(b=150))
                st.plotly_chart(fig3, use_container_width=True)

                csv = err_sum.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "Download Error Summary Report",
                    csv,
                    file_name="error_summary.csv",
                    mime="text/csv"
                )
            else:
                st.info("No error data found for the selected machine and date range.")

elif st.session_state.page == "Trend Analysis":
    st.header("Trend Analysis")
    st.markdown(
        "This section is currently under development. Please use the **Data Analyzing Dashboard** for trend charts.")

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
