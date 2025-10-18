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

# --- Helper Functions (Preserved for Data Processing) ---

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
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Production data headers not found in range D2:P3 of your Excel sheet.
 (Error: {e}) Please check the sheet format.")
        return pd.DataFrame()

    # Data is in Excel rows 4-9 (iloc 3-8) from column D (iloc 3) to P (iloc 15)
    data = df_raw_sheet.iloc[3:9, 3:16].copy()

    if len(headers) == data.shape[1]:
        data.columns = headers
    else:
        st.error(
            f"Error in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Number of columns in production section does not match headers. 
 Expected {len(headers)} columns, but {data.shape[1]} found. Please check the sheet format. (After header combination)")
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
    required_cols = ["Start", "End", "Product", "Capacity", "Manpower", "PackQty", "Date", 
                     "Waste",
                     "ProductionTypeForTon"]
    for col in required_cols:
        if col not in data.columns:
            st.warning(
                f"Warning in file '{uploaded_file_name}' (Sheet: '{selected_sheet_name}'): Required column '{col}' not found for production section.
 Data might be incomplete. Please check the sheet format. (After column rename)")
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
    data = data[data["Duration"] > 0]  # Remove rows with 0 or negative duration

    # Convert numeric columns, coercing errors to NaN and then filling with 0
    data["PackQty"] = pd.to_numeric(data["PackQty"], errors="coerce").fillna(0)
    data["Waste"] = pd.to_numeric(data["Waste"], errors="coerce").fillna(0)
    data["Capacity"] = pd.to_numeric(data["Capacity"], errors="coerce").fillna(0)
    data["Manpower"] = pd.to_numeric(data["Manpower"], errors="coerce").fillna(0)
    
    # Calculate Potential Production in Packs (Capacity is Packs/Hour, Duration is Hours)
    data["PotentialPacks"] = data["Capacity"] * data["Duration"]

    # Calculate Ton - this calculation is per-row and correct here
    data["Ton"] = data.apply(calculate_ton, axis=1)

    # Select and order final columns for the output DataFrame
    final_cols = ["Date", "Product", "Capacity", "Manpower", "Duration", "PackQty", "Waste", "Ton",
                  "PotentialPacks", # Added for OEE/Efficiency calculation later
                  "ProductionTypeForTon"] 
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
        # **IMPORTANT: We need Duration in HOURS for consistency with Production Duration (which is in hours)**
        # I'll modify this to convert to hours, as production duration is in hours.
        # convert_duration_to_minutes returns minutes. I'll convert to hours now.
        raw_errors_df["Duration"] = raw_errors_df["RawDuration"].apply(convert_duration_to_minutes) / 60

        # Clean RawErrorName: fillna, convert to string, strip whitespace
        raw_errors_df["RawErrorName"] = raw_errors_df["RawErrorName"].fillna('').astype(str).str.strip()
        raw_errors_df["RawErrorName"] = raw_errors_df["RawErrorName"].str.title()

        # Filter out rows where RawErrorName is an empty string after stripping and duration is > 0
        df_filtered = raw_errors_df[(raw_errors_df["RawErrorName"] != '') & (raw_errors_df["Duration"] > 0)].copy()

        # Aggregate durations by error name
        aggregated_errors = df_filtered.groupby("RawErrorName")["Duration"].sum().reset_index()
        aggregated_errors.columns = ["Error", "Duration"] # Duration is now in Hours

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
            f"Error in file '{uploaded_file_name_for_debug}' (Sheet: '{selected_sheet_name}'): Raw error data not found in expected range (G12:H1000) of your Excel sheet.
 (Error: `{e}`). Please check the sheet format.")
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

# --- OEE and Metrics Calculation Logic ---

def calculate_oee_metrics(prod_df, err_df, total_days):
    """Calculates OEE, Availability, Performance (Efficiency), and Quality from aggregated data."""
    
    # 1. Production and Waste Totals
    total_production_duration = prod_df['Duration'].sum()
    total_downtime_hours = err_df['Duration'].sum()
    total_packs_produced = prod_df['PackQty'].sum()
    total_waste_packs = prod_df['Waste'].sum()
    total_potential_packs = prod_df['PotentialPacks'].sum()
    
    # 2. Availability (A)
    # Total available time is production duration + downtime (Assuming this is the scheduled time)
    total_scheduled_time_hours = total_production_duration + total_downtime_hours
    
    # Handle division by zero
    if total_scheduled_time_hours > 0:
        availability = (total_production_duration / total_scheduled_time_hours) * 100
    else:
        availability = 0.0

    # 3. Performance (P) / Efficiency (New Formula)
    # Ratio of actual output to maximum potential output during the production time
    if total_potential_packs > 0:
        performance = (total_packs_produced / total_potential_packs) * 100
    else:
        performance = 0.0
        
    # 4. Quality (Q)
    # Ratio of good packs to total packs produced
    if total_packs_produced > 0:
        quality = ((total_packs_produced - total_waste_packs) / total_packs_produced) * 100
    else:
        quality = 0.0

    # 5. OEE (Overall Equipment Effectiveness)
    # OEE = A * P * Q
    oee = (availability / 100) * (performance / 100) * (quality / 100) * 100

    # 6. Waste Percentage
    if total_packs_produced > 0:
        waste_percent = (total_waste_packs / total_packs_produced) * 100
    else:
        waste_percent = 0.0
        
    return {
        "OEE": oee,
        "Availability": availability,
        "Performance": performance, # This is the New Efficiency
        "Quality": quality,
        "TotalDowntimeHours": total_downtime_hours,
        "TotalWastePacks": total_waste_packs,
        "WastePercent": waste_percent,
        "TotalTon": prod_df['Ton'].sum(),
        "TotalScheduledHours": total_scheduled_time_hours
    }


# --- Main Application ---

st.set_page_config(layout="wide", page_title="Dashboard | Production & Error Analysis")
st.title("📊 داشبورد تحلیل تولید و خطا")

# Manage page state with st.session_state
if 'page' not in st.session_state:
    st.session_state.page = "Data Analyzing Dashboard"  # Set default page to Dashboard

# Sidebar navigation using st.sidebar.radio
with st.sidebar:
    st.header("منوی اصلی")
    page_options = ["Data Analyzing Dashboard", "Trend Analysis", "Upload Data", "Data Archive", "Contact Me"]
    selected_page_index = page_options.index(st.session_state.page)
    selected_page = st.radio("بخش‌ها:", options=page_options, index=selected_page_index, key="sidebar_radio")

    if selected_page != st.session_state.page:
        st.session_state.page = selected_page
        st.rerun()  # Rerun to switch page immediately


if st.session_state.page == "Upload Data":
    st.header("بارگذاری فایل‌های اکسل")
    st.markdown("---")
    # Allow multiple files to be uploaded
    uploaded_files = st.file_uploader("فایل‌های اکسل (.xlsx) خود را بارگذاری کنید:", type=["xlsx"], accept_multiple_files=True)

    # Add an explicit upload button
    if st.button("شروع بارگذاری"):
        if uploaded_files:
            upload_to_supabase(uploaded_files)  # Pass the list of files
        else:
            st.warning("لطفاً ابتدا فایل‌ها را انتخاب کنید.")

elif st.session_state.page == "Data Archive":
    st.header("آرشیو فایل‌ها")
    st.markdown("---")
    
    search_query_archive = st.text_input("جستجو در آرشیو (نام فایل):", key="search_archive_input")

    files_info = get_all_supabase_files()  # This now includes 'file_date' and 'full_path'

    if files_info:
        # Sort files by date descending
        files_info.sort(key=lambda x: x['file_date'], reverse=True)

        # Filter by search query if present
        if search_query_archive:
            files_info = [f for f in files_info if search_query_archive.lower() in f['name'].lower()]

        if files_info:
            st.markdown("### فایل‌های موجود:")
            
            # Display files in a table for a cleaner look
            archive_data = []
            for f_info in files_info:
                archive_data.append({
                    'File Name': f_info['name'],
                    'Date': f_info['file_date'].strftime('%d %B %Y')
                })
            
            df_archive = pd.DataFrame(archive_data)
            
            # Use columns for action buttons next to the table
            cols_list = st.columns([0.7, 0.3])
            cols_list[0].dataframe(df_archive, use_container_width=True, hide_index=True)

            # Add download/delete buttons (simplified in this view)
            with st.expander("دانلود/حذف فایل‌ها به صورت تکی"):
                 for f_info in files_info:
                    col1_btn, col2_btn, col3_btn = st.columns([0.6, 0.2, 0.2])
                    file_name_display = f_info['name']
                    file_full_path_for_download = f_info['full_path']
                    
                    with col1_btn:
                        st.text(file_name_display)
                    
                    with col2_btn:
                        if file_full_path_for_download and file_full_path_for_download.lower().endswith('.xlsx'):
                            download_data = download_from_supabase(file_full_path_for_download)
                            if download_data:
                                st.download_button(
                                    label="دانلود",
                                    data=download_data,
                                    file_name=file_name_display,
                                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                    key=f"download_{file_full_path_for_download}"
                                )
                    # Deletion logic can be more complex and is usually restricted. Left as is for now.

        else:
            st.info("فایلی مطابق جستجوی شما در آرشیو یافت نشد.")
    else:
        st.info("هیچ فایلی در آرشیو موجود نیست.
 لطفاً ابتدا فایل‌ها را بارگذاری کنید.")

    st.markdown("---")
    st.subheader("عملیات مدیریتی (حذف تمام فایل‌ها)")
    with st.expander("نمایش/مخفی کردن گزینه حذف"):
        password_for_delete = st.text_input("رمز عبور برای حذف تمام فایل‌ها:", type="password", key="delete_password_input")
        if st.button("حذف همه فایل‌ها"):
            if password_for_delete == ARCHIVE_DELETE_PASSWORD:
                clear_supabase_bucket()
            elif password_for_delete: # Only show error if input is not empty
                st.error("رمز عبور اشتباه است. لطفاً دوباره تلاش کنید.")


elif st.session_state.page == "Data Analyzing Dashboard":
    st.header("داشبورد تحلیل داده (OEE، کارایی، ضایعات و خطا)")
    st.markdown("---")

    all_files_info = get_all_supabase_files()

    if not all_files_info:
        st.warning("فایلی برای تحلیل موجود نیست. لطفاً ابتدا فایل‌ها را بارگذاری کنید.")
    else:
        # --- Filtering in Sidebar for Simplicity and Cleanliness ---
        with st.sidebar:
            st.subheader("فیلترهای تحلیل")
            min_available_date = min(f['file_date'] for f in all_files_info)
            max_available_date = max(f['file_date'] for f in all_files_info)
            
            # Date Picker
            col_start_date_sb, col_end_date_sb = st.columns(2)
            with col_start_date_sb:
                default_start_date = st.session_state.get('dashboard_start_date', min_available_date)
                selected_start_date = st.date_input("از تاریخ:", value=default_start_date,
                                                    min_value=min_available_date, max_value=max_available_date,
                                                    key="dashboard_start_date_picker_sb")
            with col_end_date_sb:
                default_end_date = st.session_state.get('dashboard_end_date', max_available_date)
                selected_end_date = st.date_input("تا تاریخ:", value=default_end_date,
                                                  min_value=min_available_date, max_value=max_available_date,
                                                  key="dashboard_end_date_picker_sb")

            # Error handling for date range
            if selected_end_date < selected_start_date:
                st.error("خطا: تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.")
                selected_end_date = selected_start_date 
                st.session_state.dashboard_end_date_picker_sb = selected_end_date

            st.session_state.dashboard_start_date = selected_start_date
            st.session_state.dashboard_end_date = selected_end_date

            files_in_date_range = [
                f for f in all_files_info
                if selected_start_date <= f['file_date'] <= selected_end_date
            ]
            
            if not files_in_date_range:
                st.warning("فایلی در بازه تاریخ انتخاب شده یافت نشد.")
                st.stop() # Stop execution if no files are found

            st.markdown("---")
            st.subheader("وضعیت فایل‌ها")
            num_selected_days = (selected_end_date - selected_start_date).days + 1
            st.info(f"تعداد روزهای انتخابی: **{num_selected_days}**")
            st.success(f"تعداد فایل‌های یافت شده: **{len(files_in_date_range)}**")

        # --- Data Processing Block ---
        all_production_data = []
        all_error_data = []
        progress_text = "در حال پردازش فایل‌ها..."
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
                    st.error(f"خطا در پردازش فایل اکسل '{file_full_path}': {e}")
            
            my_bar.progress((i + 1) / len(files_in_date_range), text=f"در حال پردازش فایل: {file_full_path}")

        my_bar.empty()

        final_prod_df = pd.concat(all_production_data, ignore_index=True) if all_production_data else pd.DataFrame()
        final_err_df = pd.concat(all_error_data, ignore_index=True) if all_error_data else pd.DataFrame()

        # --- Machine Selection Filter (after data concatenation) ---
        unique_machines = ['همه دستگاه‌ها']
        if not final_prod_df.empty and "ProductionTypeForTon" in final_prod_df.columns:
            filtered_unique_machines = [m for m in final_prod_df["ProductionTypeForTon"].unique().tolist() if m is not None]
            if "Unknown Machine" in filtered_unique_machines:
                filtered_unique_machines.remove("Unknown Machine")
                filtered_unique_machines.append("Unknown Machine")
            unique_machines.extend(sorted(filtered_unique_machines))
        
        selected_machine = st.selectbox("انتخاب دستگاه:", unique_machines)

        # Filter by machine
        filtered_prod_df = final_prod_df.copy()
        filtered_err_df = final_err_df.copy()
        if selected_machine != 'همه دستگاه‌ها':
            filtered_prod_df = final_prod_df[
                final_prod_df["ProductionTypeForTon"] == selected_machine].copy()
            filtered_err_df = final_err_df[final_err_df["MachineType"] == selected_machine].copy()
        
        # --- Check for filtered data ---
        if filtered_prod_df.empty and filtered_err_df.empty:
            st.warning(f"داده‌ای برای دستگاه '{selected_machine}' در بازه زمانی انتخاب شده یافت نشد.")
            st.stop()


        # --- 1. Top Metrics (OEE, Efficiency, Waste, Downtime) ---
        metrics = calculate_oee_metrics(filtered_prod_df, filtered_err_df, num_selected_days)
        
        st.subheader("شاخص‌های کلیدی عملکرد (KPIs)")
        
        col_oee, col_efficiency, col_waste, col_downtime = st.columns(4)
        
        with col_oee:
            # OEE
            st.metric("OEE (او ای)", f"{metrics['OEE']:.2f} %", help="OEE = در دسترس بودن × عملکرد × کیفیت")
        
        with col_efficiency:
            # Efficiency (New Formula)
            st.metric("کارایی (Efficiency) جدید", f"{metrics['Performance']:.2f} %", help="عملکرد (Performance) = تولید واقعی / تولید بالقوه (فرمول جدید)")
        
        with col_waste:
            # Waste Percentage
            st.metric("درصد ضایعات", f"{metrics['WastePercent']:.2f} %", help="کل ضایعات / کل تولید واقعی (بر حسب بسته)")
        
        with col_downtime:
            # Total Downtime
            st.metric("کل زمان توقف (خطاها)", f"{metrics['TotalDowntimeHours']:.2f} ساعت", help="مجموع مدت زمان ثبت شده برای خطاها (خطاهای کلی)")

        st.markdown("---")
        
        # --- 2. Tabs for Data Display and Charts (Better UX) ---
        
        tab_charts, tab_errors, tab_raw_data = st.tabs(["نمودارهای تحلیل تولید", "تحلیل خطا و توقفات", "نمایش داده خام"])
        
        with tab_charts:
            st.subheader("نمودار تحلیل تولید")
            
            # --- Total Production (Tons) by Product ---
            st.markdown("##### ۱. کل تولید (تن) بر اساس محصول")
            total_ton_per_product = filtered_prod_df.groupby("Product")["Ton"].sum().reset_index()
            total_ton_per_product = total_ton_per_product.sort_values(by="Ton", ascending=False)
            
            fig_ton = px.treemap(total_ton_per_product, path=[px.Constant("همه محصولات"), 'Product'], values="Ton",
                            title="مقایسه وزنی تولید (تن)", hover_data=['Ton'], color="Product")
            fig_ton.update_layout(margin=dict(t=50, l=25, r=25, b=25))
            st.plotly_chart(fig_ton, use_container_width=True)

            # --- Waste Percentage by Product ---
            st.markdown("##### ۲. درصد ضایعات (Waste%) بر اساس محصول")
            agg_waste_percent_df = filtered_prod_df.groupby("Product").agg(
                TotalWaste=('Waste', 'sum'),
                TotalPackQty=('PackQty', 'sum')
            ).reset_index()
            
            agg_waste_percent_df["Waste(%)"] = np.where(
                agg_waste_percent_df['TotalPackQty'] > 0,
                (agg_waste_percent_df['TotalWaste'] / agg_waste_percent_df['TotalPackQty']) * 100,
                0
            )

            agg_waste_percent_df = agg_waste_percent_df.sort_values(by="Waste(%)", ascending=False)
            
            fig_waste = px.bar(agg_waste_percent_df, x="Product", y="Waste(%)", 
                            title="درصد ضایعات",
                            labels={"Waste(%)": "درصد ضایعات (%)"},
                            color="Product",
                            text_auto=".2s", height=500)
            fig_waste.update_layout(xaxis_tickangle=-45)
            st.plotly_chart(fig_waste, use_container_width=True)


        with tab_errors:
            st.subheader("تحلیل تفصیلی خطاها و توقفات")
            
            if not filtered_err_df.empty:
                # --- Error Data Sum (Detail - ققیک) ---
                st.markdown("##### ۱. جزئیات توقفات (خطاهای تفصیلی)")
                err_sum_detail = filtered_err_df.groupby("Error")["Duration"].sum().reset_index()
                err_sum_detail = err_sum_detail.sort_values(by="Duration", ascending=False)
                err_sum_detail['Duration (Minutes)'] = err_sum_detail['Duration'] * 60 # Convert back to minutes for a common display unit
                
                # Bar chart for top errors
                fig_errors = px.bar(err_sum_detail, x="Error", y="Duration (Minutes)", 
                                    title="مدت زمان توقف (خطاها) بر اساس نوع (دقیقه)",
                                    labels={"Duration (Minutes)": "مدت زمان (دقیقه)", "Error": "نوع خطا"},
                                    color="Error", text_auto=".1s", height=600)
                fig_errors.update_layout(xaxis_tickangle=-45, margin=dict(b=150))
                st.plotly_chart(fig_errors, use_container_width=True)

                # Table of errors
                st.dataframe(err_sum_detail.rename(columns={'Duration (Minutes)': 'مدت زمان (دقیقه)', 'Error': 'نوع خطا', 'Duration': 'مدت زمان (ساعت)'}), 
                            use_container_width=True, hide_index=True)

                csv_err = err_sum_detail.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "دانلود گزارش جزئیات خطا",
                    csv_err,
                    file_name="error_detail_report.csv",
                    mime="text/csv"
                )
            else:
                st.info("داده‌ای برای تحلیل خطاها در فیلترهای اعمال شده یافت نشد.")


        with tab_raw_data:
            st.subheader("نمایش داده‌های ترکیبی فیلتر شده (جهت بررسی صحت داده)")
            
            st.markdown("##### داده خام تولید (Product Production Data)")
            if not filtered_prod_df.empty:
                # Select only relevant columns for display and rename them
                display_cols = ['Date', 'ProductionTypeForTon', 'Product', 'Duration', 'Capacity', 'PackQty', 'Waste', 'Ton']
                display_df = filtered_prod_df[display_cols].rename(columns={
                    'Date': 'تاریخ',
                    'ProductionTypeForTon': 'نوع دستگاه/تولید',
                    'Product': 'محصول',
                    'Duration': 'مدت زمان (ساعت)',
                    'Capacity': 'ظرفیت (بسته/ساعت)',
                    'PackQty': 'تولید واقعی (بسته)',
                    'Waste': 'ضایعات (بسته)',
                    'Ton': 'تن'
                })
                st.dataframe(display_df, use_container_width=True, hide_index=True)
            else:
                st.info("داده خام تولیدی برای نمایش وجود ندارد.")
                
            st.markdown("---")
            st.markdown("##### داده خام خطاها (Error Data)")
            if not filtered_err_df.empty:
                display_err_df = filtered_err_df.rename(columns={
                    'Date': 'تاریخ',
                    'MachineType': 'نوع دستگاه',
                    'Error': 'نوع خطا',
                    'Duration': 'مدت زمان (ساعت)'
                })
                st.dataframe(display_err_df, use_container_width=True, hide_index=True)
            else:
                st.info("داده خام خطایی برای نمایش وجود ندارد.")


elif st.session_state.page == "Trend Analysis":
    st.header("📈 تحلیل روند روزانه (Trends)")
    st.markdown("---")
    # This section remains largely similar but with updated naming and metrics (using OEE components)

    # --- Trend Data Processing ---
    all_files_info = get_all_supabase_files()
    if not all_files_info:
        st.warning("فایلی برای تحلیل روند موجود نیست. لطفاً ابتدا فایل‌ها را بارگذاری کنید.")
        st.stop()
        
    # --- Filtering in Sidebar for Simplicity and Cleanliness ---
    with st.sidebar:
        st.subheader("فیلترهای تحلیل روند")
        min_available_date = min(f['file_date'] for f in all_files_info)
        max_available_date = max(f['file_date'] for f in all_files_info)
        
        col_start_date_trend_sb, col_end_date_trend_sb = st.columns(2)
        with col_start_date_trend_sb:
            default_start_date_trend = st.session_state.get('trend_start_date', min_available_date)
            selected_start_date_trend = st.date_input("از تاریخ:", value=default_start_date_trend,
                                                min_value=min_available_date, max_value=max_available_date,
                                                key="trend_start_date_picker_sb")
        with col_end_date_trend_sb:
            default_end_date_trend = st.session_state.get('trend_end_date', max_available_date)
            selected_end_date_trend = st.date_input("تا تاریخ:", value=default_end_date_trend,
                                              min_value=min_available_date, max_value=max_available_date,
                                              key="trend_end_date_picker_sb")

        if selected_end_date_trend < selected_start_date_trend:
            st.error("خطا: تاریخ پایان نمی‌تواند قبل از تاریخ شروع باشد.")
            selected_end_date_trend = selected_start_date_trend 
            st.session_state.trend_end_date_picker_sb = selected_end_date_trend 

        st.session_state.trend_start_date = selected_start_date_trend
        st.session_state.trend_end_date = selected_end_date_trend

        files_in_date_range_trend = [
            f for f in all_files_info
            if selected_start_date_trend <= f['file_date'] <= selected_end_date_trend
        ]
        
        if not files_in_date_range_trend:
            st.warning("فایلی در بازه تاریخ انتخاب شده یافت نشد.")
            st.stop()
        
    # --- Data Processing for Trend ---
    all_production_data_trend = []
    all_error_data_trend = []
    
    progress_text_trend = "در حال پردازش فایل‌ها برای تحلیل روند..."
    my_bar_trend = st.progress(0, text=progress_text_trend)

    for i, file_info_dict in enumerate(files_in_date_range_trend): 
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
                st.error(f"خطا در پردازش فایل '{file_full_path}' برای تحلیل روند: {e}")
        
        my_bar_trend.progress((i + 1) / len(files_in_date_range_trend), text=f"در حال پردازش فایل: {file_full_path}")
    
    my_bar_trend.empty()

    final_prod_df_trend = pd.concat(all_production_data_trend, ignore_index=True) if all_production_data_trend else pd.DataFrame()
    final_err_df_trend = pd.concat(all_error_data_trend, ignore_index=True) if all_error_data_trend else pd.DataFrame()
    
    # --- Machine Selection Filter for Trend ---
    unique_machines_trend = ['همه دستگاه‌ها']
    if not final_prod_df_trend.empty and "ProductionTypeForTon" in final_prod_df_trend.columns:
        filtered_unique_machines_trend = [m for m in final_prod_df_trend["ProductionTypeForTon"].unique().tolist() if m is not None]
        if "Unknown Machine" in filtered_unique_machines_trend:
            filtered_unique_machines_trend.remove("Unknown Machine")
            filtered_unique_machines_trend.append("Unknown Machine")
        unique_machines_trend.extend(sorted(filtered_unique_machines_trend))
    
    selected_machine_trend = st.selectbox("انتخاب دستگاه برای تحلیل روند:", unique_machines_trend)

    # Filter by machine for trend data
    filtered_prod_df_trend = final_prod_df_trend.copy()
    filtered_err_df_trend = final_err_df_trend.copy()
    if selected_machine_trend != 'همه دستگاه‌ها':
        filtered_prod_df_trend = final_prod_df_trend[
            final_prod_df_trend["ProductionTypeForTon"] == selected_machine_trend].copy()
        filtered_err_df_trend = final_err_df_trend[final_err_df_trend["MachineType"] == selected_machine_trend].copy()
    
    # --- Daily Aggregation for Trend Charts ---
    
    # Aggregation for OEE components: Production
    daily_prod_agg = filtered_prod_df_trend.groupby("Date").agg(
        TotalDuration=('Duration', 'sum'),
        TotalPackQty=('PackQty', 'sum'),
        TotalWaste=('Waste', 'sum'),
        TotalPotentialPacks=('PotentialPacks', 'sum'),
        TotalTon=('Ton', 'sum')
    ).reset_index()

    # Aggregation for OEE components: Errors
    daily_err_agg = filtered_err_df_trend.groupby("Date").agg(
        TotalDowntime=('Duration', 'sum')
    ).reset_index()
    
    # Merge Production and Error data
    daily_data = pd.merge(daily_prod_agg, daily_err_agg, on='Date', how='outer').fillna(0)
    
    # Calculate daily OEE and components
    if not daily_data.empty:
        daily_data['TotalScheduledHours'] = daily_data['TotalDuration'] + daily_data['TotalDowntime']
        
        # Availability (A)
        daily_data['Availability'] = np.where(
            daily_data['TotalScheduledHours'] > 0,
            (daily_data['TotalDuration'] / daily_data['TotalScheduledHours']) * 100,
            0
        )
        
        # Performance (P) / Efficiency
        daily_data['Performance'] = np.where(
            daily_data['TotalPotentialPacks'] > 0,
            (daily_data['TotalPackQty'] / daily_data['TotalPotentialPacks']) * 100,
            0
        )
        
        # Quality (Q)
        daily_data['Quality'] = np.where(
            daily_data['TotalPackQty'] > 0,
            ((daily_data['TotalPackQty'] - daily_data['TotalWaste']) / daily_data['TotalPackQty']) * 100,
            0
        )
        
        # OEE
        daily_data['OEE'] = (daily_data['Availability'] / 100) * (daily_data['Performance'] / 100) * (daily_data['Quality'] / 100) * 100
        
        # Waste Percentage
        daily_data['Waste(%)'] = np.where(
            daily_data['TotalPackQty'] > 0,
            (daily_data['TotalWaste'] / daily_data['TotalPackQty']) * 100,
            0
        )

        # --- Trend Analysis Charts ---
        
        st.subheader("۱. تحلیل روند روزانه OEE و شاخص‌های آن")
        fig_trend_oee = px.line(daily_data, x="Date", y=["OEE", "Availability", "Performance", "Quality"], 
                                title=f"روند روزانه OEE، در دسترس بودن، کارایی و کیفیت برای {selected_machine_trend}",
                                labels={"value": "درصد (%)", "variable": "شاخص"},
                                markers=True, line_shape='spline')
        st.plotly_chart(fig_trend_oee, use_container_width=True)

        st.subheader("۲. تحلیل روند روزانه تولید و ضایعات")

        col_trend_ton, col_trend_waste = st.columns(2)
        
        with col_trend_ton:
            st.markdown("##### روند کل تولید (تن)")
            fig_trend_ton = px.line(daily_data, x="Date", y="TotalTon", 
                                    title=f"روند روزانه کل تولید (تن) برای {selected_machine_trend}",
                                    labels={"TotalTon": "تن"},
                                    markers=True, line_shape='spline')
            st.plotly_chart(fig_trend_ton, use_container_width=True)

        with col_trend_waste:
            st.markdown("##### روند درصد ضایعات (Waste%)")
            fig_trend_waste = px.line(daily_data, x="Date", y="Waste(%)", 
                                      title=f"روند روزانه درصد ضایعات برای {selected_machine_trend}",
                                      labels={"Waste(%)": "درصد ضایعات (%)"},
                                      markers=True, line_shape='spline')
            st.plotly_chart(fig_trend_waste, use_container_width=True)


        st.subheader("۳. تحلیل روند روزانه توقفات")
        fig_trend_error = px.line(daily_data, x="Date", y="TotalDowntime",
                                    title=f"روند روزانه کل زمان توقف (ساعت) برای {selected_machine_trend}",
                                    labels={"TotalDowntime": "مدت زمان (ساعت)"},
                                    markers=True, line_shape='spline')
        st.plotly_chart(fig_trend_error, use_container_width=True)
            
    else:
        st.warning("داده‌ای برای تحلیل روند روزانه پس از اعمال فیلترها موجود نیست.")
            
elif st.session_state.page == "Contact Me":
    st.subheader("ارتباط با محمد اسدالله‌زاده")
    st.markdown("---")
    st.markdown("""
    در دنیای پرشتاب امروز، با پیشرفت سریع فناوری، هوش مصنوعی دیگر یک گزینه نیست، بلکه یک ضرورت است. استفاده از هوش مصنوعی می‌تواند به طور قابل توجهی عملکرد را افزایش دهد، خطاهای انسانی را به حداقل برساند و فرآیندهای کاری را ساده‌سازی کند. تکیه صرف به روش‌های سنتی اغلب منجر به هدر رفتن زمان و تلاش می‌شود، بدون آنکه کارایی مورد نظر به دست آید.

    برای پاسخگویی به این نیاز، من شروع به ساخت پلتفرمی کرده‌ام که اتوماسیون را با هوشمندی ترکیب می‌کند. با انگیزه‌ای که از علاقه به پایتون - با وجود اینکه هنوز در حال یادگیری هستم - و تمایل عمیق به ایجاد راه‌حل‌های فنی منضبط و مبتنی بر داده دارم، توسعه این وب‌سایت مبتنی بر Streamlit را برای تحلیل عملکرد روزانه تولید آغاز کردم.

    اگرچه مهارت‌های پایتون من هنوز در حال رشد است، اما صبر، تعهد و کنجکاوی زیادی را صرف این پروژه کرده‌ام. در طول این فرآیند، ابزارهایی مانند **جمنای (Gemini AI)** در رفع اشکالات، پالایش استراتژی‌ها و به ثمر رساندن این ایده، بسیار مفید بودند. صادقانه بگویم، بدون کمک هوش مصنوعی، رسیدن به این نقطه بسیار دشوارتر می‌شد.

    با این حال، من متعهد به بهبود هستم؛ هم در کدنویسی و هم در طراحی سیستم. از بازخوردها، پیشنهادات یا هر گونه راهنمایی شما برای ارتقاء بیشتر این پلتفرم استقبال می‌کنم.

    📧 ایمیل: m.asdz@yahoo.com
    🔗 لینکدین: Mohammad Asdollahzadeh

    از بازدید شما سپاسگزارم و واقعاً قدردان حمایتتان هستم.

    با احترام،
    محمد اسدالله‌زاده
    """)
