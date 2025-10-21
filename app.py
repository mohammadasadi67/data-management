# =========================================================
# 📊 STREAMLIT LIGHT PRO THEME SETUP
# =========================================================

import streamlit as st
import plotly.express as px
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from io import BytesIO
from supabase import create_client, Client
import base64
import re
import time

# --- Streamlit Page Config ---
st.set_page_config(
    page_title="Production & Error Dashboard (Light)",
    layout="wide",
    page_icon="☀️"
)

# --- Light Theme Setup ---
px.defaults.template = "plotly_white"

# --- Custom Light Theme Styling ---
st.markdown(
    """
    <style>
        /* 🌞 Global Background and Text */
        .stApp {
            background-color: #FFFFFF;
            color: #111111;
            font-family: 'Inter', sans-serif;
        }

        /* 📦 Main Container */
        .block-container {
            background-color: #FFFFFF;
            padding-top: 2rem;
            padding-bottom: 2rem;
            max-width: 1400px;
        }

        /* 📊 Metric Cards */
        .stMetric {
            background-color: #F8FAFC;
            border-radius: 12px;
            padding: 14px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.07);
            color: #1E293B;
        }

        /* 🔘 Buttons */
        .stButton>button {
            background-color: #007BFF;
            color: white;
            border-radius: 8px;
            border: none;
            font-weight: 500;
            padding: 8px 18px;
            transition: 0.3s;
        }
        .stButton>button:hover {
            background-color: #0056b3;
            transform: scale(1.03);
        }

        /* 🧭 Sidebar */
        section[data-testid="stSidebar"] {
            background-color: #F4F6F8;
        }

        /* 🪄 Headers */
        h1, h2, h3, h4 {
            color: #1E293B;
            font-weight: 600;
        }

        /* 🧾 Tables & DataFrames */
        table, .dataframe {
            background-color: #FFFFFF !important;
            color: #111111 !important;
            border-radius: 6px;
        }

        /* 🔹 Info Boxes */
        .stAlert {
            background-color: #F9FAFB !important;
            color: #111111 !important;
            border-left: 4px solid #007BFF;
        }

        /* 🧩 Tabs */
        .stTabs [role="tablist"] {
            border-bottom: 1px solid #E5E7EB;
        }

        /* ⚙️ Progress Bar */
        div[data-testid="stProgress"] > div > div > div {
            background-color: #007BFF;
        }

    </style>
    """
    , unsafe_allow_html=True
)

# =========================================================
# 🔗 SUPABASE CONFIGURATION (Light Version)
# =========================================================

SUPABASE_URL = "https://rlutsxvghmhrgcnqbmch.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InJsdXRzeHZnaG1ocmdjbnFibWNoIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc0NTEyODk5MSwiZXhwIjoyMDYwNzA0OTkxfQ.VPxJbrPUw4E-MyRGklQMcxveUTznNlWLhPO-mqrHv9c"

# Initialize Supabase client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- Password for Archive Deletion ---
ARCHIVE_DELETE_PASSWORD = "beautifulmind"

# =========================================================
# 🧠 From here, paste the rest of your Streamlit logic
# =========================================================
