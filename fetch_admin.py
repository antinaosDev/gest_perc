import sys
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import toml

try:
    secrets = toml.load("../.streamlit/secrets.toml")
    URL_ADMIN_MASTER = secrets["URL_ADMIN_MASTER"]
    BOOTSTRAP_CREDS = secrets["gcp_service_account"]
    
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
    client = gspread.authorize(creds)
    sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
    
    raw_data = sheet_admin.get_all_values()
    headers = raw_data[0]
    records = [dict(zip(headers, row)) for row in raw_data[1:]]
    
    print(f"Headers: {headers}")
    for item in records:
        print(f"User: {item.get('CUENTA')} | Pass: {item.get('CLAVE_PLATAFORMA', item.get('CLAVE_PLATAFORMA ', 'NOT FOUND'))} | Plat: {item.get('Plataforma')}")
except Exception as e:
    print(f"Error: {e}")
