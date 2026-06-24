import gspread
from google.oauth2.service_account import Credentials
import toml
import json

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

def load_app_configuration(account_id):
    config = {'valido': False, 'mensaje': '', 'datos': {}, 'credenciales': None, 'imagenes': {}}
    target_row = next((item for item in records if str(item['CUENTA']) == account_id), None)
    if not target_row:
        config['mensaje'] = "Cuenta no encontrada."
        return config

    if str(target_row.get('ESTADO_APP', '')).upper() != 'ACTIVO':
        config['mensaje'] = "Cuenta desactivada."
        return config

    plataforma_encontrada = ""
    for key, val in target_row.items():
        if str(key).strip().upper() == 'PLATAFORMA':
            plataforma_encontrada = str(val).strip()
            break
    
    clave_encontrada = 'percapita_ch_2025'
    for key, val in target_row.items():
        if str(key).strip().upper() == 'CLAVE_PLATAFORMA':
            clave_encontrada = str(val).strip()
            break
            
    config['clave'] = clave_encontrada
    config['valido'] = True
    return config

print("cuenta_cesfam ->", load_app_configuration("cuenta_cesfam"))
print("Dirección Cesfam ->", load_app_configuration("Dirección Cesfam"))
