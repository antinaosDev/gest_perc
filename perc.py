import pandas as pd
import streamlit as st
import re
import json
import os
import base64
import requests
import altair as alt  # Gráficos interactivos
from datetime import datetime
import time
import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

# --- NUEVOS IMPORTS PARA PERCAPITA ---
import plotly.express as px
import plotly.figure_factory as ff
import plotly.graph_objects as go
import numpy as np
import chardet
from class_ges import *
from analisis_func import *

@st.cache_data(show_spinner="Procesando y consolidando archivos...")
def cargar_datos_cache_v2(archivos_cargados):
    return reporte_percapita(archivos_cargados)

@st.cache_data
def convert_df_to_csv(df):
    return df.to_csv(index=False, sep=';').encode('utf-8-sig')

# -----------------------------------------------------------------------------
# 0. CONFIGURACIÓN Y CONSTANTES
# -----------------------------------------------------------------------------
MASTER_ACCOUNT_ID = "cuenta_perc" 
URL_ADMIN_MASTER = st.secrets["URL_ADMIN_MASTER"]

# CONSTANTES DE FECHA
MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

# IMÁGENES POR DEFECTO (Respaldo)
DEFAULT_LOGO_ALAIN = "https://drive.google.com/file/d/1QyEf4sN2lMxaBOOY8asFDTYFxELcT_rR/view?usp=sharing"
DEFAULT_LOGO_NOTI = "https://drive.google.com/file/d/14GQkoC_ykLs6BPK75FQDiCrbQ8Xj9r4b/view?usp=sharing"

# CREDENCIALES (Cargadas desde st.secrets)
BOOTSTRAP_CREDS = dict(st.secrets["gcp_service_account"])

# -----------------------------------------------------------------------------
# 1. FUNCIONES BACKEND
# -----------------------------------------------------------------------------

def procesar_imagen_drive(url_drive, creds_dict=None):
    """Procesa URLs de Google Drive para obtener contenido visualizable."""
    if not url_drive or len(url_drive) < 10: return None
    file_id = None
    patterns = [r'/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    for pattern in patterns:
        match = re.search(pattern, url_drive)
        if match:
            file_id = match.group(1)
            break
    if not file_id: return None
    # Retorna URL pública directa para compatibilidad web
    return f"https://drive.google.com/uc?export=view&id={file_id}"

def normalize_rut(rut):
    """Estandariza RUT."""
    if not rut: return "S/I"
    rut = str(rut).upper().strip()
    rut = rut.replace(".", "").replace("-", "").replace(" ", "")
    rut = rut.lstrip("0")
    if len(rut) < 2: return "INVALIDO"
    return rut

def get_demographic_data(url_demographic, client):
    """Carga bases secundarias (Sector y Percápita)."""
    dem_data = {'sector': pd.DataFrame(), 'percapita': pd.DataFrame()}
    try:
        if not url_demographic or len(url_demographic) < 10: return dem_data
        sheet_dem = client.open_by_url(url_demographic)
        
        # 1. Sector
        try:
            ws_sector = sheet_dem.worksheet("sector")
            data_sector = ws_sector.get_all_records()
            df_sector = pd.DataFrame(data_sector)
            if not df_sector.empty and 'RUT' in df_sector.columns:
                df_sector['RUT_CLEAN'] = df_sector['RUT'].apply(normalize_rut)
                df_sector = df_sector.drop_duplicates(subset=['RUT_CLEAN'])
                dem_data['sector'] = df_sector[['RUT_CLEAN', 'SECTOR']]
        except: pass

        # 2. Percápita (Lógica del último mes)
        try:
            ws_perca = sheet_dem.worksheet("percapita")
            data_perca = ws_perca.get_all_records()
            df_perca = pd.DataFrame(data_perca)
            if not df_perca.empty and 'RUT' in df_perca.columns:
                df_perca['RUT_CLEAN'] = df_perca['RUT'].apply(normalize_rut)
                df_perca['ANIO_NUM'] = pd.to_numeric(df_perca['ANIO_CORTE'], errors='coerce').fillna(0)
                
                meses_map_rev = {
                    "ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4, "MAYO":5, "JUNIO":6,
                    "JULIO":7, "AGOSTO":8, "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12
                }
                def mes_to_num(m):
                    return meses_map_rev.get(str(m).upper().strip(), 0)
                
                df_perca['MES_NUM'] = df_perca['MES_CORTE'].apply(mes_to_num)
                
                # Filtrar último mes
                max_anio = df_perca['ANIO_NUM'].max()
                max_mes = df_perca[df_perca['ANIO_NUM'] == max_anio]['MES_NUM'].max()
                
                df_perca_latest = df_perca[
                    (df_perca['ANIO_NUM'] == max_anio) & 
                    (df_perca['MES_NUM'] == max_mes)
                ].copy()
                
                df_perca_latest['ESTA_PERCAPITADO'] = "SI"
                dem_data['percapita'] = df_perca_latest[['RUT_CLEAN', 'ESTA_PERCAPITADO']]
        except: pass

        # 3. Rescates Manuales desde el archivo externo
        try:
            url_rescates = st.secrets["URL_RESCATES"]
            sheet_rescates = client.open_by_url(url_rescates)
            ws_rescates = sheet_rescates.worksheet("percapita")
            data_rescates = ws_rescates.get_all_records()
            df_rescates = pd.DataFrame(data_rescates)
            if not df_rescates.empty and 'RUT' in df_rescates.columns:
                df_rescates['RUT_CLEAN'] = df_rescates['RUT'].apply(normalize_rut)
                df_rescates['ESTA_PERCAPITADO'] = "SI"
                
                if not dem_data['percapita'].empty:
                    dem_data['percapita'] = pd.concat([dem_data['percapita'], df_rescates[['RUT_CLEAN', 'ESTA_PERCAPITADO']]]).drop_duplicates(subset=['RUT_CLEAN'])
                else:
                    dem_data['percapita'] = df_rescates[['RUT_CLEAN', 'ESTA_PERCAPITADO']]
        except Exception as e:
            print(f"Error leyendo rescates manuales: {e}")
    except: pass
    return dem_data

def load_app_configuration(account_id):
    """Carga configuración y LOGOS desde Admin."""
    config = {'valido': False, 'mensaje': '', 'datos': {}, 'credenciales': None, 'imagenes': {}}
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
        
        # Obtenemos los valores manualmente para evitar el error de headers duplicados en gspread
        raw_data = sheet_admin.get_all_values()
        if not raw_data:
            config['mensaje'] = "La hoja está vacía."
            return config
            
        headers = raw_data[0]
        records = [dict(zip(headers, row)) for row in raw_data[1:]]

        
        target_row = next((item for item in records if str(item['CUENTA']) == account_id), None)
        if not target_row:
            config['mensaje'] = "Cuenta no encontrada."
            return config

        if str(target_row.get('ESTADO_APP', '')).upper() != 'ACTIVO':
            config['mensaje'] = "Cuenta desactivada."
            return config

        config['datos']['URL_SHEET'] = str(target_row.get('URL_SHEET', '')).strip()
        config['datos']['URL_DATOS_DEM'] = str(target_row.get('DATOS_DEM', '')).strip()
        
        config['debug_keys'] = list(target_row.keys())
        config['debug_vals'] = list(target_row.values())
        
        # Búsqueda robusta de la clave para evitar problemas con espacios en los headers
        clave_encontrada = 'percapita_ch_2025'
        for key, val in target_row.items():
            if str(key).strip().upper() == 'CLAVE_PLATAFORMA':
                clave_encontrada = str(val).strip()
                break
        config['clave'] = clave_encontrada
        
        cred_raw = target_row.get('CREDENTIAL_DICT', '')
        if isinstance(cred_raw, str) and len(cred_raw) > 10:
            try: config['credenciales'] = json.loads(cred_raw)
            except: config['credenciales'] = BOOTSTRAP_CREDS
        else: config['credenciales'] = BOOTSTRAP_CREDS

        # === CARGA DE IMÁGENES EXACTAMENTE COMO EN LA APP BASE ===
        # Usamos los mismos nombres de claves para mantener compatibilidad
        url_logo_alain = str(target_row.get('LOGO_ALAIN', '')).strip() 
        url_logo_noti = str(target_row.get('LOGO_NOTI', '')).strip()    
        
        if len(url_logo_alain) < 5: url_logo_alain = DEFAULT_LOGO_ALAIN
        if len(url_logo_noti) < 5: url_logo_noti = DEFAULT_LOGO_NOTI

        config['imagenes']['LOGO_ALAIN'] = procesar_imagen_drive(url_logo_alain)
        config['imagenes']['LOGO_NOTI'] = procesar_imagen_drive(url_logo_noti)
        config['valido'] = True
            
    except Exception as e:
        config['mensaje'] = f"Error: {e}"
    return config

@st.cache_data(ttl=60)
def get_rescate_data(config):
    """Obtiene datos y filtra solo los NO INSCRITOS."""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(config['credenciales'], scopes=scope)
        client = gspread.authorize(creds)
        
        sheet = client.open_by_url(config['datos']['URL_SHEET']).sheet1
        data = sheet.get_all_values()
        df = pd.DataFrame(data[1:], columns=data[0])
        df.columns = df.columns.str.strip()
        
        dem_info = get_demographic_data(config['datos']['URL_DATOS_DEM'], client)
        
        if 'RUT' in df.columns:
            df['RUT_CLEAN'] = df['RUT'].apply(normalize_rut)
            
            # Cruce Sector
            if not dem_info['sector'].empty:
                df = df.merge(dem_info['sector'], on='RUT_CLEAN', how='left')
                df['SECTOR'] = df['SECTOR'].fillna('Sin Sector')
            else:
                df['SECTOR'] = 'Sin Info'

            # Cruce Percapita
            if not dem_info['percapita'].empty:
                df = df.merge(dem_info['percapita'], on='RUT_CLEAN', how='left')
                df['ESTADO_PERCAPITA'] = df['ESTA_PERCAPITADO'].fillna("PENDIENTE INSCRIPCION")
                df.loc[df['ESTA_PERCAPITADO'] == 'SI', 'ESTADO_PERCAPITA'] = 'INSCRITO'
            else:
                df['ESTADO_PERCAPITA'] = 'Sin Base Percapita'

        # Filtrar solo pendientes
        df_rescate = df[df['ESTADO_PERCAPITA'] == "PENDIENTE INSCRIPCION"].copy()
        
        # Seleccionar columnas útiles (SIN INFO CLÍNICA)
        # Se elimina EDAD_NUM de la visualización, se usa solo EDAD_ACTUAL
        cols_deseadas = ['RUT', 'RUT_CLEAN', 'NOMBRE_PACIENTE', 'TELEFONO', 'EDAD_ACTUAL', 'GENERO',
                         'SECTOR', 'POLICLINICO', 'NOMBRE_PROFESIONAL', 'PROFESION', 'FECHA_AGENDADA', 'HORA_AGENDADA', 'MOTIVO_CONSULTA']
        cols_existentes = [c for c in cols_deseadas if c in df_rescate.columns]
        return df_rescate[cols_existentes]
        
    except Exception as e:
        st.error(f"Error cargando datos: {e}")
        return pd.DataFrame()

# -----------------------------------------------------------------------------
# 2. INTERFAZ DE USUARIO (VISUALIZACIÓN)
# -----------------------------------------------------------------------------

st.set_page_config(page_title="Gestión Percápita | CESFAM Cholchol", page_icon="🏥", layout="wide")
APP_CONFIG = load_app_configuration(MASTER_ACCOUNT_ID)

# Estilos CSS
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --primary-blue: #00A8E8;  /* Celeste Tecnológico */
        --navy-blue: #0A193D;     /* Azul oscuro profundo */
        --success-green: #FFB703; /* Amarillo Tecnológico (Alertas Suaves) */
        --accent-orange: #FB8500; /* Naranjo Tecnológico */
        --text-dark: #0A193D;     /* Texto oscuro */
        --text-gray: #6B7A90;
        --bg-light: #F4F7F9;      /* Fondo limpio */
        --white: #FFFFFF;
        --card-shadow: 0 8px 16px -4px rgba(0, 168, 232, 0.1), 0 4px 8px -4px rgba(0, 168, 232, 0.06);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: var(--bg-light);
        color: var(--text-dark);
    }

    /* Estilos Generales */
    .main-container { padding-top: 2rem; }
    
    /* Header Institucional */
    .main-header {
        background: var(--white);
        padding: 30px; 
        border-radius: 16px; 
        margin-bottom: 25px; 
        box-shadow: var(--card-shadow);
        display: flex;
        align-items: center;
        gap: 20px;
        border-left: 6px solid var(--primary-blue);
    }
    .header-text h1 { margin:0; font-size: 2.2rem; font-weight: 700; color: var(--text-dark); }
    .header-text p { margin:0; color: var(--text-gray); font-size: 1.1rem; margin-top: 5px; }
    
    /* Tarjetas de Información */
    .info-card {
        background-color: var(--white);
        border-left: 5px solid var(--primary-blue);
        padding: 20px;
        border-radius: 16px;
        margin-bottom: 25px;
        box-shadow: var(--card-shadow);
    }
    
    /* KPIs */
    .kpi-metric {
        background-color: var(--white); 
        padding: 25px 20px; 
        border-radius: 16px;
        text-align: center; 
        box-shadow: var(--card-shadow);
        transition: transform 0.3s ease, box-shadow 0.3s ease;
        position: relative;
        overflow: hidden;
    }
    .kpi-metric:hover { 
        transform: translateY(-5px); 
        box-shadow: 0 10px 20px rgba(0,0,0,0.1); 
    }
    .kpi-value { font-size: 2.5rem; font-weight: 800; color: var(--text-dark); margin: 0; line-height: 1; }
    .kpi-label { font-size: 0.95rem; color: var(--text-gray); margin-top: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; }
</style>
""", unsafe_allow_html=True)

# --- SIDEBAR (CON LOGO APP) ---
with st.sidebar:
    if os.path.exists("logo_noti.png"):
        st.image("logo_noti.png", use_container_width=True)
    elif APP_CONFIG['imagenes'].get('LOGO_NOTI'):
        st.image(APP_CONFIG['imagenes']['LOGO_NOTI'], use_container_width=True)
    else:
        st.header("MEDTIFY")
    
    st.markdown(f"""
    <div style="background: rgba(0,168,232,0.1); border: 1px solid #00A8E8; padding: 15px; border-radius: 10px; text-align: center; margin-bottom: 20px;">
        <h4 style="color: #00A8E8; margin: 0; font-size: 1.1em;">👤 Usuario Activo</h4>
        <p style="color: #6B7A90; margin: 5px 0 0 0; font-weight: bold;">{MASTER_ACCOUNT_ID.upper()}</p>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("---")
    app_mode = st.radio("🛠️ Módulo Activo:", ["📋 Rescate de Pacientes", "📊 Análisis Archivo Percápita"])
    st.markdown("---")

    st.markdown("### 🏥 Panel Institucional")
    st.success("🟢 Sistema Online y Sincronizado")
    
    st.markdown("""
    **Módulos Disponibles:**
    - 📊 Dashboard General
    - 📋 Nómina de Rescate
    - 📈 Estadísticas
    """)
    
    st.info("""
    💡 **Tip de uso:**
    Utilice las cabeceras de la tabla para ordenar y buscar pacientes fácilmente por RUT o Profesional.
    """)
    
    st.markdown("---")
    st.caption("Versión 1.2.0 | Equipo de Gestión")

# --- LOGIN ---
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False

if not st.session_state.logged_in:
    # --- PANTALLA DE LOGIN PREMIUM ---
    st.markdown("""
    <style>
        /* Fondo animado y elegante para toda la app durante el login */
        div[data-testid="stAppViewContainer"] {
            background: linear-gradient(-45deg, #0A193D, #00A8E8, #FB8500, #FFB703);
            background-size: 400% 400%;
            animation: gradientBG 15s ease infinite;
        }
        @keyframes gradientBG {
            0% { background-position: 0% 50%; }
            50% { background-position: 100% 50%; }
            100% { background-position: 0% 50%; }
        }
        
        /* Eliminar padding superior extra y esconder barra principal */
        .stApp > header { display: none; }
        
        /* Estilo del contenedor Formulario (Card Glassmorphism) */
        div[data-testid="stForm"] {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            padding: 40px 30px;
            box-shadow: 0 15px 35px rgba(0,0,0,0.2);
            border: 1px solid rgba(255, 255, 255, 0.2);
            margin-top: 5vh;
        }
        
        /* Textos dentro del form */
        .login-title {
            color: #0F2557;
            font-family: 'Inter', sans-serif;
            font-weight: 800;
            font-size: 28px;
            margin-bottom: 5px;
            text-align: center;
            letter-spacing: -0.5px;
        }
        .login-subtitle {
            color: #6c757d;
            text-align: center;
            font-size: 14px;
            margin-bottom: 30px;
        }
        
        /* Botón de Submit dentro del Form */
        div[data-testid="stFormSubmitButton"] > button {
            background: linear-gradient(135deg, #00A8E8 0%, #FB8500 100%) !important;
            color: white !important;
            border-radius: 12px !important;
            border: none !important;
            font-weight: 600 !important;
            padding: 0.6rem !important;
            width: 100% !important;
            transition: all 0.3s ease !important;
            box-shadow: 0 4px 15px rgba(0, 109, 182, 0.3) !important;
            margin-top: 15px !important;
        }
        div[data-testid="stFormSubmitButton"] > button:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 109, 182, 0.4) !important;
        }
        
        /* Inputs */
        div[data-baseweb="input"] {
            border-radius: 10px !important;
            border: 1px solid #e0e6ed !important;
            background-color: #f8f9fa !important;
            transition: border-color 0.3s ease, box-shadow 0.3s ease;
        }
        div[data-baseweb="input"]:focus-within {
            border-color: #006DB6 !important;
            box-shadow: 0 0 0 2px rgba(0, 109, 182, 0.2) !important;
        }
    </style>
    """, unsafe_allow_html=True)

    c1, c2, c3 = st.columns([1, 1.5, 1])
    with c2:
        with st.form("login_form", clear_on_submit=False):
            col_l, col_img, col_r = st.columns([1, 1.5, 1])
            with col_img:
                if os.path.exists("logo_noti.png"):
                    st.image("logo_noti.png", use_container_width=True)
                elif APP_CONFIG['imagenes'].get('LOGO_NOTI'):
                    st.image(APP_CONFIG['imagenes']['LOGO_NOTI'], use_container_width=True)
                else:
                    st.markdown('<div style="font-size: 50px; text-align: center;">🏥</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="login-title">Portal Análisis Percápita</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-subtitle">Centro de Salud Familiar Cholchol</div>', unsafe_allow_html=True)
            
            password = st.text_input("Contraseña de Acceso", type="password", placeholder="Ingrese la clave").strip()
            
            submitted = st.form_submit_button("Ingresar al Sistema")
            
            if submitted:
                clave_correcta = APP_CONFIG.get('clave', 'percapita_ch_2025')
                if password == clave_correcta:
                    st.session_state.logged_in = True
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta. Verifique su clave.")
    st.stop()

# --- APP PRINCIPAL ---
if not APP_CONFIG['valido']:
    st.error(f"Error config: {APP_CONFIG['mensaje']}")
    st.stop()

if app_mode == "📊 Análisis Archivo Percápita":
    st.info(
        """
        **Análisis Percápita 📊**

        Esta sección permite cargar, consolidar y analizar el reporte per cápita, además de geolocalizar 
        los distintos centros de la comuna.
        """
    )

    col1, col2 = st.columns([1, 6])
    with col1:
        st.image("https://media0.giphy.com/media/v1.Y2lkPTc5MGI3NjExeDl4a2pzZjUyaDVpdXYwZzBjdTNibjU5NDFkZmZhdHU2Ymo1djBqOSZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/nNOAPjUdo4mpZFkDf8/giphy.gif", use_container_width=True)
    with col2:
        st.subheader('Cargar reporte percapita')
        archivos = st.file_uploader('Selecciona los archivos (CSV, TXT)', type=['csv', 'txt'], accept_multiple_files=True)

    if archivos:
        try:
            df_global, df_auth, df_fall = cargar_datos_cache_v2(archivos)
        except Exception as e:
            st.error(f"Error al procesar los archivos: {e}")
            st.stop()

        with st.expander("👁️ Ver vista previa de datos cargados"):
            st.markdown("#### Primeros 100 registros:")
            st.dataframe(df_global.head(100), hide_index=True, use_container_width=True)

        columnas_sesion = ["RUT", "NOMBRE_CENTRO", "NOMBRE_CENTRO_PROCEDENCIA", "NOMBRE_COMUNA_PROCEDENCIA", "NOMBRE_CENTRO_DESTINO", "NOMBRE_COMUNA_DESTINO", "ANIO_CORTE", "MES_CORTE", "LAT_CENTRO", "LONG_CENTRO"]
        cols_existentes = [c for c in columnas_sesion if c in df_auth.columns]
        st.session_state.df_autorizados = df_auth[cols_existentes]

        tab1_p, tab2_p, tab3_p = st.tabs(['📈 Inscritos Percápita', '📉 Registro Fallecidos', '📊 Análisis de datos'])

        def obtener_anios_validos(df, col_anio):
            raw = df[col_anio].dropna()
            validos = raw[pd.to_numeric(raw, errors='coerce').notna()]
            return sorted(validos.astype(int).unique().tolist())

        año_export_insc = obtener_anios_validos(df_auth, 'ANIO_CORTE')
        año_export_fall = obtener_anios_validos(df_fall, 'ANIO_CORTE')

        with tab1_p:
            with st.container(border=True):
                if año_export_insc:
                    col_filt_1, col_filt_2 = st.columns(2)
                    with col_filt_1:
                        if len(año_export_insc) >= 2:
                            opcion_año = st.select_slider('1. Seleccione rango de años 📆', options=año_export_insc, value=(min(año_export_insc), max(año_export_insc)), key='slider_insc')
                        else:
                            st.info(f"Año único: {año_export_insc[0]}")
                            opcion_año = (año_export_insc[0], año_export_insc[0])
                    
                    with col_filt_2:
                        meses_disponibles = df_auth['MES_CORTE'].unique().tolist()
                        orden_meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
                        meses_ordenados = sorted([m for m in meses_disponibles if m in orden_meses], key=lambda x: orden_meses.index(x))
                        otros_meses = [m for m in meses_disponibles if m not in orden_meses]
                        meses_finales = meses_ordenados + otros_meses
                        mes_corte_seleccionado = st.selectbox("2. Seleccione Mes de Corte 🗓️", options=meses_finales, index=len(meses_finales)-1 if meses_finales else 0)

                    anio_inicio, anio_fin = opcion_año
                    
                    if not df_auth.empty and mes_corte_seleccionado:
                        df_filtrado = df_auth[(df_auth['ANIO_CORTE'] >= anio_inicio) & (df_auth['ANIO_CORTE'] <= anio_fin) & (df_auth['MES_CORTE'] == mes_corte_seleccionado)]
                        if not df_filtrado.empty:
                            df_grouped = df_filtrado.groupby('ANIO_CORTE')['RUT'].count().reset_index()
                            df_grouped.columns = ['Año', 'Inscritos']
                            st.markdown(f"### Evolución de Inscritos - Corte: {mes_corte_seleccionado}")
                            fig = px.bar(df_grouped, x='Año', y='Inscritos', text_auto=True, color='Año')
                            st.plotly_chart(fig, use_container_width=True)

                            st.divider()
                            st.markdown("#### Configuración de Exportación y Reporte 📥")
                            all_columns = df_filtrado.columns.tolist()
                            col_exp_1, col_exp_2 = st.columns([3, 1])
                            
                            with col_exp_1:
                                columnas_seleccionadas = st.multiselect("Seleccione las columnas a incluir en el CSV:", options=all_columns, default=all_columns, key="cols_insc")
                                tipo_grupo = st.radio("Tipo de Grupo Etario para Reporte Estadístico:", ["Quinquenal Estándar", "Personalizado (Años)", "Personalizado con Fracciones (Meses/Años)"])
                                
                                if tipo_grupo == "Personalizado (Años)":
                                    rangos_custom_str = st.text_input("Definir rangos (ej: 0-14, 15-24, 25-64, 65+):", "0-14, 15-24, 25-64, 65+")
                                    grupos_disp = [g.strip() for g in rangos_custom_str.split(',')]
                                elif tipo_grupo == "Personalizado con Fracciones (Meses/Años)":
                                    rangos_custom_str = st.text_input("Definir rangos explícitos (ej: 0 meses a 2 años y 11 meses, 3 años a 5 años y 11 meses, 6 años a 14 años, 15+ años):", "0 meses a 2 años y 11 meses, 3 años a 5 años y 11 meses, 6 años a 14 años, 15+ años")
                                    grupos_disp = [g.strip() for g in rangos_custom_str.split(',')]
                                else:
                                    grupos_disp = ["0-4 años", "5-9 años", "10-14 años", "15-19 años", "20-24 años", "25-29 años", "30-34 años", "35-39 años", "40-44 años", "45-49 años", "50-54 años", "55-59 años", "60-64 años", "65-69 años", "70-74 años", "75-79 años", "80 y más años", "SIN DATOS"]
                                grupos_seleccionados = st.multiselect("Seleccione los Grupos Etarios a incluir en el Excel:", options=grupos_disp, default=grupos_disp, key="cols_edad")
                            
                            with col_exp_2:
                                if columnas_seleccionadas:
                                    nulos_fecha = df_filtrado['FECHA_NACIMIENTO'].isnull().sum() if 'FECHA_NACIMIENTO' in df_filtrado.columns else 0
                                    if nulos_fecha > 5:
                                        st.error(f"❌ Error: Existen {nulos_fecha} registros con la FECHA_NACIMIENTO en blanco. No se puede exportar.")
                                    else:
                                        df_procesado = df_filtrado.copy()
                                        if nulos_fecha > 0:
                                            st.warning(f"⚠️ Faltan {nulos_fecha} fechas de nacimiento. Puedes agregarlas manualmente:")
                                            df_errores = df_procesado[df_procesado['FECHA_NACIMIENTO'].isnull()]
                                            cols_identificacion = [c for c in ['RUT', 'NOMBRES', 'APELLIDO_PATERNO', 'APELLIDO_MATERNO', 'FECHA_NACIMIENTO'] if c in df_errores.columns]
                                            if not cols_identificacion: cols_identificacion = df_errores.columns.tolist()
                                            edited_errores = st.data_editor(df_errores[cols_identificacion], hide_index=True, column_config={"FECHA_NACIMIENTO": st.column_config.DateColumn("FECHA_NACIMIENTO", format="DD/MM/YYYY")})
                                            for idx, row in edited_errores.iterrows():
                                                if pd.notnull(row.get('FECHA_NACIMIENTO')):
                                                    nueva_fecha = pd.to_datetime(row['FECHA_NACIMIENTO'], errors='coerce')
                                                    df_procesado.loc[idx, 'FECHA_NACIMIENTO'] = nueva_fecha
                                                    if pd.notnull(nueva_fecha):
                                                        hoy = pd.Timestamp.today()
                                                        df_procesado.loc[idx, 'EDAD'] = hoy.year - nueva_fecha.year - ((hoy.month, hoy.day) < (nueva_fecha.month, nueva_fecha.day))
                                            if df_procesado['FECHA_NACIMIENTO'].isnull().sum() == 0: st.success("✅ ¡Fechas corregidas!")
                                        
                                        df_exportar = df_procesado[columnas_seleccionadas]
                                        st.download_button(label="📥 Descargar CSV Consolidado", data=convert_df_to_csv(df_exportar), file_name=f'Inscritos_Percapita_{mes_corte_seleccionado}.csv', mime='text/csv', use_container_width=True)
                                        
                                        df_estadistico = df_procesado.copy()
                                        if tipo_grupo in ["Personalizado (Años)", "Personalizado con Fracciones (Meses/Años)"]:
                                            df_estadistico = asignar_grupo_etario_custom(df_estadistico, rangos_custom_str)
                                            col_agrupacion = "GRUPO_ETARIO_CUSTOM"
                                        else:
                                            df_estadistico = asignar_grupo_etario_quinquenal(df_estadistico)
                                            col_agrupacion = "GRUPO_ETARIO_QUINQUENAL"
                                            
                                        if grupos_seleccionados: df_estadistico = df_estadistico[df_estadistico[col_agrupacion].isin(grupos_seleccionados)]
                                        try:
                                            excel_data = generar_excel_estadistico(df_estadistico, col_grupo=col_agrupacion, tipo_grupo_nombre=tipo_grupo)
                                            st.download_button(label="📊 Descargar Reporte Estadístico (Excel)", data=excel_data, file_name=f'Estadistica_{mes_corte_seleccionado}.xlsx', mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', use_container_width=True)
                                        except Exception as e: st.error(f"Error generando Excel: {e}")
                        else: st.warning("No hay datos.")

        with tab2_p:
            with st.container(border=True):
                if año_export_fall:
                    opcion_año_fall = st.select_slider('Seleccione rango de años 📆', options=año_export_fall, value=(min(año_export_fall), max(año_export_fall)), key='slider_fall') if len(año_export_fall)>=2 else (año_export_fall[0], año_export_fall[0])
                    anio_inicio_f, anio_fin_f = opcion_año_fall
                    if not df_fall.empty:
                        df_filtrado_f = df_fall[(df_fall['ANIO_CORTE'] >= anio_inicio_f) & (df_fall['ANIO_CORTE'] <= anio_fin_f)]
                        df_grouped_f = df_filtrado_f.groupby('ANIO_CORTE')['RUT'].count().reset_index()
                        df_grouped_f.columns = ['Año', 'Fallecidos']
                        fig_f = px.bar(df_grouped_f, x='Año', y='Fallecidos', text_auto=True, color='Año')
                        st.plotly_chart(fig_f, use_container_width=True)
                        st.download_button(label="Descargar Nómina Fallecidos", data=convert_df_to_csv(df_filtrado_f), file_name="Fallecidos.csv", mime="text/csv", use_container_width=True)
                else: st.warning("Sin datos de fallecidos.")

        with tab3_p:
            st.subheader("Análisis estadístico detallado 📊")
            años_global = obtener_anios_validos(df_global, 'ANIO_CORTE')
            orden_meses = ["Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
            meses_disp = df_global['MES_CORTE'].dropna().unique().tolist()
            meses_ordenados = sorted([m for m in meses_disp if m in orden_meses], key=lambda x: orden_meses.index(x))

            with st.container(border=True):
                c_filt1, c_filt2, c_filt3 = st.columns(3)
                with c_filt1: año_slider = st.select_slider('Rango años', options=años_global, value=(min(años_global), max(años_global)), key='as_an') if len(años_global)>=2 else (años_global[0], años_global[0]) if años_global else (2025,2025)
                with c_filt2: meses_slider = st.select_slider('Rango meses', options=meses_ordenados, value=(meses_ordenados[0], meses_ordenados[-1]), key='ms_an') if len(meses_ordenados)>=2 else (meses_ordenados[0], meses_ordenados[0]) if meses_ordenados else ("Enero", "Enero")
                with c_filt3: select_gender = st.selectbox('Género:', list(df_global['GENERO'].unique()) + ['TODOS'], index=len(list(df_global['GENERO'].unique())))
                opciones_estab = sorted(df_global['NOMBRE_CENTRO'].astype(str).unique().tolist())
                select_estab = st.multiselect('Establecimientos:', opciones_estab)

            idx_in = orden_meses.index(meses_slider[0])
            idx_fi = orden_meses.index(meses_slider[1])
            meses_fil = orden_meses[idx_in:idx_fi + 1]

            mask = (df_global['ANIO_CORTE'] >= año_slider[0]) & (df_global['ANIO_CORTE'] <= año_slider[1]) & (df_global['MES_CORTE'].isin(meses_fil))
            if select_gender != 'TODOS': mask &= (df_global['GENERO'] == select_gender)
            if select_estab: mask &= (df_global['NOMBRE_CENTRO'].isin(select_estab))
            df_filt = df_global[mask]

            if not df_filt.empty:
                g1, g2, g3 = st.columns(3)
                with g1: st.plotly_chart(px.funnel(df_filt.groupby(['RANGO_ETARIO', 'GENERO'])['RUT'].nunique().reset_index(), x='RUT', y='RANGO_ETARIO', color='GENERO', title='Clasificación Etaria'), use_container_width=True)
                with g2: 
                    fig = px.bar(df_filt.groupby(['TRAMO', 'GENERO'])['RUT'].nunique().reset_index(), x='TRAMO', y='RUT', text_auto=True, color='GENERO', barmode='group', title='Usuarios por Tramo')
                    st.plotly_chart(fig, use_container_width=True)
                with g3: 
                    fig = px.bar(df_filt.groupby(['NOMBRE_CENTRO', 'GENERO'])['RUT'].nunique().reset_index(), x='NOMBRE_CENTRO', y='RUT', text_auto=True, color='GENERO', barmode='group', title='Usuarios por Centro')
                    st.plotly_chart(fig, use_container_width=True)

                with st.container(border=True):
                    st.subheader("Distribución Geográfica 🗺️")
                    def clean_coord(val):
                        try: return float(pd.Series(str(val).replace(',', '.')).str.extract(r'(-?\d+\.\d+)')[0].iloc[0])
                        except: return np.nan
                    
                    df_map = df_filt.groupby(['NOMBRE_CENTRO', 'LAT_CENTRO', 'LONG_CENTRO'])['RUT'].nunique().reset_index()
                    df_map.columns = ['NOMBRE_CENTRO', 'LAT_CENTRO', 'LONG_CENTRO', 'COUNT_RUT']
                    df_map['LAT_CENTRO'] = df_map['LAT_CENTRO'].apply(clean_coord)
                    df_map['LONG_CENTRO'] = df_map['LONG_CENTRO'].apply(clean_coord)
                    df_map = df_map.dropna(subset=['LAT_CENTRO', 'LONG_CENTRO'])
                    df_map = df_map[df_map['COUNT_RUT'] > 0]

                    if not df_map.empty:
                        try:
                            if df_map['COUNT_RUT'].nunique() == 1:
                                fig_map = px.scatter_map(df_map, lat='LAT_CENTRO', lon='LONG_CENTRO', color='NOMBRE_CENTRO', zoom=10, map_style='open-street-map', hover_name='NOMBRE_CENTRO')
                                fig_map.update_traces(marker=dict(size=15))
                            else:
                                fig_map = px.scatter_map(df_map, lat='LAT_CENTRO', lon='LONG_CENTRO', size='COUNT_RUT', color='NOMBRE_CENTRO', zoom=10, map_style='open-street-map', hover_name='NOMBRE_CENTRO')
                            st.plotly_chart(fig_map, use_container_width=True)
                        except Exception as e: st.error(f"Error mapa: {e}")
                    else: st.warning("Sin datos geográficos válidos.")
            else: st.warning("No hay datos.")
            
    # FIN DEL MODULO PERCAPITA
    st.stop()

# Header Institucional
try:
    with open("cesfam.jpg", "rb") as f:
        logo_base64 = base64.b64encode(f.read()).decode()
    logo_url = f"data:image/jpeg;base64,{logo_base64}"
except Exception:
    logo_url = APP_CONFIG['imagenes'].get('LOGO_NOTI', 'https://cdn-icons-png.flaticon.com/512/2966/2966327.png')

st.markdown(f"""
<div class="main-header">
    <img src="{logo_url}" alt="Logo Institucional" style="width: 100px; height: auto; border-radius: 8px; background: white; padding: 5px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
    <div class="header-text">
        <h1>Centro de Salud Familiar Cholchol</h1>
        <p>Tablero de Control Percápita - Seguimiento y Rescate de Pacientes</p>
    </div>
</div>
""", unsafe_allow_html=True)

# Descripción de la Plataforma
st.markdown("""
<div class="info-card">
    <h4 style="margin-top:0; color: #2C3E50;">ℹ️ Acerca de esta Plataforma</h4>
    <p style="color: #555; font-size: 1rem; line-height: 1.5; margin-bottom: 0;">
        Este sistema permite monitorear en tiempo real a los pacientes que han sido atendidos en el establecimiento pero que 
        <strong>no figuran inscritos en la base de datos Percápita</strong>. Utilice esta herramienta para identificar 
        oportunidades de rescate, coordinar con los profesionales y asegurar el correcto registro de la población a cargo.
    </p>
</div>
""", unsafe_allow_html=True)

# Carga de datos
with st.spinner("🔄 Cruzando bases de datos en tiempo real..."):
    df_rescate = get_rescate_data(APP_CONFIG)

if df_rescate.empty:
    st.balloons()
    st.success("🎉 ¡Sin brechas! Todos los pacientes atendidos figuran inscritos.")
    if st.button("Recargar"): st.cache_data.clear(); st.rerun()
else:
    if 'ESTADO' in df_rescate.columns:
        df_rescate['ESTADO'] = df_rescate['ESTADO'].fillna("NO INFORMADO")

    # FILTROS EN SIDEBAR
    with st.sidebar:
        st.markdown("---")
        st.markdown("### 🔍 Filtros Interactivos")

        sectores = ["Todos"] + sorted(df_rescate['SECTOR'].dropna().unique().tolist())
        sector_sel = st.selectbox("Filtrar por Sector", sectores)
        
        profesionales = ["Todos"]
        if 'NOMBRE_PROFESIONAL' in df_rescate.columns:
            profesionales += sorted(df_rescate['NOMBRE_PROFESIONAL'].dropna().unique().tolist())
        prof_sel = st.selectbox("Filtrar por Profesional", profesionales)
        
    df_filtered = df_rescate.copy()
    if sector_sel != "Todos":
        df_filtered = df_filtered[df_filtered['SECTOR'] == sector_sel]
    if prof_sel != "Todos" and 'NOMBRE_PROFESIONAL' in df_filtered.columns:
        df_filtered = df_filtered[df_filtered['NOMBRE_PROFESIONAL'] == prof_sel]

    # 1. KPIs Visuales
    c1, c2, c3 = st.columns(3)
    with c1:
        rut_col = 'RUT_CLEAN' if 'RUT_CLEAN' in df_filtered.columns else 'RUT'
        st.markdown(f"""
        <div class="kpi-metric" style="border-bottom: 4px solid #E74C3C;">
            <p class="kpi-value">{df_filtered[rut_col].nunique()}</p>
            <p class="kpi-label">Brechas Totales</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        sector_crit = df_filtered['SECTOR'].mode()[0] if not df_filtered.empty and 'SECTOR' in df_filtered.columns else "N/A"
        st.markdown(f"""
        <div class="kpi-metric" style="border-bottom: 4px solid #F39C12;">
            <p class="kpi-value" style="font-size:1.5rem;">{sector_crit}</p>
            <p class="kpi-label">Sector Crítico</p>
        </div>""", unsafe_allow_html=True)
    with c3:
        prof_crit = df_filtered['NOMBRE_PROFESIONAL'].mode()[0] if not df_filtered.empty and 'NOMBRE_PROFESIONAL' in df_filtered.columns else "N/A"
        prof_str = str(prof_crit)[:25] + ".." if len(str(prof_crit)) > 25 else str(prof_crit)
        st.markdown(f"""
        <div class="kpi-metric" style="border-bottom: 4px solid #3498DB;">
            <p class="kpi-value" style="font-size:1.1rem;">{prof_str}</p>
            <p class="kpi-label">Top Profesional</p>
        </div>""", unsafe_allow_html=True)

    st.markdown("---")

    # TABS PARA ORGANIZAR LA APP
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Análisis de Brechas", "📈 Dashboard Demográfico", "📋 Nómina de Pacientes", "📝 Gestión de Rescates"])

    with tab1:
        st.markdown("### 📊 Análisis Estratégico y Financiero")
        if not df_filtered.empty:
            rut_col = 'RUT_CLEAN' if 'RUT_CLEAN' in df_filtered.columns else 'RUT'
            total_brechas = df_filtered[rut_col].nunique()
            valor_percapita = 16872
            impacto_total = total_brechas * valor_percapita
            
            sector_max = df_filtered['SECTOR'].value_counts().index[0] if 'SECTOR' in df_filtered.columns and not df_filtered['SECTOR'].empty else "N/A"
            pct_sector = (df_filtered['SECTOR'].value_counts().iloc[0] / len(df_filtered) * 100) if sector_max != "N/A" else 0
            
            st.info(f"**💡 Storytelling Analítico:** El sistema detecta **{total_brechas} pacientes únicos** sin registro percapita al año y mes evaluado. Esta población representa una fuga de capital proyectada de **CLP {impacto_total:,.0f} anuales** (basado en el per cápita basal de CLP 16.872). El **{pct_sector:.1f}%** de esta fuga de capital se concentra en el sector **{sector_max}**.")
            
            g_a, g_b = st.columns(2)
            with g_a:
                if 'SECTOR' in df_filtered.columns:
                    df_fin = df_filtered.copy()
                    df_fin['SECTOR'] = df_fin['SECTOR'].replace({'Sin Sector': 'Sin Información', 'NO_ESPECIFICADO': 'Sin Información', 'No Especificado': 'Sin Información'})
                    df_fin = df_fin.groupby('SECTOR')[rut_col].nunique().reset_index()
                    df_fin.rename(columns={rut_col: 'RUT'}, inplace=True)
                    df_fin['Fuga de Capital (CLP)'] = df_fin['RUT'] * valor_percapita
                    df_fin['Agrupador'] = 'Todos los Sectores'
                    fig_tree = px.treemap(df_fin, path=['Agrupador', 'SECTOR'], values='Fuga de Capital (CLP)',
                                          color='Fuga de Capital (CLP)', color_continuous_scale='Reds',
                                          title="Distribución de Fuga de Capital por Sector")
                    fig_tree.update_traces(textinfo="label+value+percent parent")
                    st.plotly_chart(fig_tree, use_container_width=True)
            
            with g_b:
                t1, t2, t3 = st.tabs(["📝 Motivos Consulta", "👨‍⚕️ Profesionales", "💼 Profesiones"])
                rut_col = 'RUT_CLEAN' if 'RUT_CLEAN' in df_filtered.columns else 'RUT'
                df_unica = df_filtered.drop_duplicates(subset=[rut_col], keep='last').copy()
                with t1:
                    if 'MOTIVO_CONSULTA' in df_unica.columns:
                        df_mot = df_unica.groupby('MOTIVO_CONSULTA')[rut_col].nunique().reset_index()
                        df_mot.rename(columns={rut_col: 'RUT'}, inplace=True)
                        df_mot = df_mot.sort_values('RUT', ascending=False).head(10).sort_values('RUT', ascending=True)
                        fig_mot = px.bar(df_mot, x='RUT', y='MOTIVO_CONSULTA', text_auto=True, orientation='h',
                                          title="Top 10 Motivos de Consulta",
                                          color='RUT', color_continuous_scale=['#00A8E8', '#0F2557'])
                        fig_mot.update_layout(coloraxis_showscale=False)
                        st.plotly_chart(fig_mot, use_container_width=True)
                with t2:
                    if 'NOMBRE_PROFESIONAL' in df_filtered.columns:
                        df_prof = df_unica.groupby('NOMBRE_PROFESIONAL')[rut_col].nunique().reset_index()
                        df_prof.rename(columns={rut_col: 'RUT'}, inplace=True)
                        df_prof = df_prof.sort_values('RUT', ascending=False).head(10).sort_values('RUT', ascending=True)
                        fig_prof = px.bar(df_prof, x='RUT', y='NOMBRE_PROFESIONAL', text_auto=True, orientation='h',
                                          title="Top 10 Profesionales",
                                          color='RUT', color_continuous_scale=['#FFB703', '#FB8500'])
                        fig_prof.update_layout(coloraxis_showscale=False)
                        st.plotly_chart(fig_prof, use_container_width=True)
                with t3:
                    if 'PROFESION' in df_filtered.columns:
                        df_profesion = df_unica.groupby('PROFESION')[rut_col].nunique().reset_index()
                        df_profesion.rename(columns={rut_col: 'RUT'}, inplace=True)
                        df_profesion = df_profesion.sort_values('RUT', ascending=False).head(10).sort_values('RUT', ascending=True)
                        fig_profesion = px.bar(df_profesion, x='RUT', y='PROFESION', text_auto=True, orientation='h',
                                          title="Top 10 Profesiones",
                                          color='RUT', color_continuous_scale=['#2ECC71', '#27AE60'])
                        fig_profesion.update_layout(coloraxis_showscale=False)
                        st.plotly_chart(fig_profesion, use_container_width=True)

    with tab2:
        st.markdown("### 📈 Perfil Demográfico de la Brecha")
        if not df_filtered.empty:
            if 'EDAD_ACTUAL' in df_filtered.columns and 'GENERO' in df_filtered.columns:
                df_filtered['EDAD_NUM_CHART'] = pd.to_numeric(df_filtered['EDAD_ACTUAL'], errors='coerce')
                
                fig_demo = px.histogram(df_filtered, x="EDAD_NUM_CHART", color="GENERO",
                                        title="Distribución de Edad y Género de Pacientes no Inscritos",
                                        labels={'EDAD_NUM_CHART':'Edad (Años)'},
                                        nbins=15, barmode='group',
                                        color_discrete_sequence=px.colors.qualitative.Set2)
                st.plotly_chart(fig_demo, use_container_width=True)
                
            if 'FECHA_AGENDADA' in df_filtered.columns:
                df_time = df_filtered.dropna(subset=['FECHA_AGENDADA']).copy()
                df_time['FECHA'] = pd.to_datetime(df_time['FECHA_AGENDADA'].astype(str).str.split(' ').str[0], errors='coerce')
                df_time = df_time.dropna(subset=['FECHA'])
                if not df_time.empty:
                    rut_col_time = 'RUT_CLEAN' if 'RUT_CLEAN' in df_time.columns else 'RUT'
                    df_time_grp = df_time.groupby('FECHA')[rut_col_time].nunique().reset_index()
                    df_time_grp.rename(columns={rut_col_time: 'RUT'}, inplace=True)
                    df_time_grp['Fuga'] = df_time_grp['RUT'] * 16872
                    fig_time = px.area(df_time_grp, x='FECHA', y='Fuga', title="Evolución Temporal de Fuga de Capital", color_discrete_sequence=['#FFB703'])
                    fig_time.update_traces(mode='lines+markers', line=dict(color='#FB8500', width=3), fillcolor='rgba(255, 183, 3, 0.3)')
                    st.plotly_chart(fig_time, use_container_width=True)
                
            st.info("🚨 **Nota de Gestión:** El perfil demográfico permite focalizar el medio de contacto. Pacientes menores de 40 años responden mejor a canales digitales o WhatsApp, mientras que pacientes sobre 60 años pueden requerir llamados telefónicos directos o gestiones presenciales.")

    with tab3:
        st.markdown("### 📋 Nómina Estratégica para Gestión")
        
        # Análisis Estadístico de la Nómina
        if not df_filtered.empty:
            st.markdown("#### 📈 Resumen Estadístico de la Nómina")
            
            # Clasificación Cronológica (Chile)
            import pytz
            from datetime import datetime
            chile_tz = pytz.timezone('America/Santiago')
            ahora_chile = datetime.now(chile_tz).replace(tzinfo=None)
            
            df_sorted = df_filtered.copy()
            
            if 'FECHA_AGENDADA' in df_sorted.columns:
                fecha_base = df_sorted['FECHA_AGENDADA'].astype(str).str.split(' ').str[0].replace({'nan': '', 'None': ''})
                
                if 'HORA_AGENDADA' in df_sorted.columns:
                    hora_base = df_sorted['HORA_AGENDADA'].astype(str).replace({'nan': '00:00', 'None': '00:00', '': '00:00'})
                    df_sorted['FECHA_HORA_STR'] = fecha_base + ' ' + hora_base
                    df_sorted['FECHA_HORA'] = pd.to_datetime(df_sorted['FECHA_HORA_STR'], errors='coerce', dayfirst=True)
                else:
                    df_sorted['FECHA_HORA'] = pd.to_datetime(fecha_base, errors='coerce', dayfirst=True)
                    
                # Fallback: si por culpa de la hora da NaT, intentar solo con la fecha
                idx_nat = df_sorted['FECHA_HORA'].isna() & (fecha_base != '')
                if idx_nat.any():
                    df_sorted.loc[idx_nat, 'FECHA_HORA'] = pd.to_datetime(fecha_base[idx_nat], errors='coerce', dayfirst=True)
                
                df_sorted = df_sorted.sort_values(by='FECHA_HORA', ascending=True)
                
                def categorize_rescue(dt):
                    if pd.isna(dt):
                        return "Sin Fecha"
                    if dt < ahora_chile:
                        return "Rescate Retroactivo"
                    else:
                        return "Por Rescatar"
                        
                df_sorted['TIPO_RESCATE'] = df_sorted['FECHA_HORA'].apply(categorize_rescue)
            else:
                df_sorted['TIPO_RESCATE'] = "Por Rescatar"
            
            e1, e2, e3 = st.columns(3)
            with e1:
                rut_col_stat = 'RUT_CLEAN' if 'RUT_CLEAN' in df_sorted.columns else 'RUT'
                st.metric("Pacientes a Rescatar", df_sorted[rut_col_stat].nunique())
            with e2:
                top_sector = df_sorted['SECTOR'].mode()[0] if 'SECTOR' in df_sorted.columns and not df_sorted['SECTOR'].empty else "N/A"
                st.metric("Sector Principal", top_sector)
            with e3:
                riesgo = df_sorted[rut_col_stat].nunique() * 16872
                st.metric("Fuga Capital", f"CLP {riesgo:,.0f}")
                
            c_met, c_chart = st.columns([1.2, 1])
            with c_met:
                st.markdown("<br>", unsafe_allow_html=True)
                filtro_tipo = st.radio("Filtro de Gestión (Cronológico):", ["🟢 Mostrar Todo", "🔵 Rescate Retroactivo", "🟡 Por Rescatar"], horizontal=False)
                if "Sin Fecha" in df_sorted['TIPO_RESCATE'].values:
                    st.info("💡 **Sin Fecha:** Atenciones que el sistema no tiene registradas con hora agendada (Ej. demanda espontánea).")
            
            with c_chart:
                df_pie = df_sorted['TIPO_RESCATE'].value_counts().reset_index()
                df_pie.columns = ['Tipo', 'Cantidad']
                fig_donut = px.pie(df_pie, values='Cantidad', names='Tipo', hole=0.5, 
                                   color='Tipo', color_discrete_map={'Rescate Retroactivo': '#00A8E8', 'Por Rescatar': '#FFB703', 'Sin Fecha': '#6B7A90'},
                                   title="Estado de Horas")
                fig_donut.update_traces(textposition='inside', textinfo='percent+label')
                fig_donut.update_layout(showlegend=False, margin=dict(t=30, b=0, l=0, r=0))
                st.plotly_chart(fig_donut, use_container_width=True)
                
            if filtro_tipo == "🔵 Rescate Retroactivo":
                df_sorted = df_sorted[df_sorted['TIPO_RESCATE'] == "Rescate Retroactivo"]
            elif filtro_tipo == "🟡 Por Rescatar":
                df_sorted = df_sorted[df_sorted['TIPO_RESCATE'] == "Por Rescatar"]
            
        cols_final_table = [c for c in df_sorted.columns if c not in ['EDAD_NUM_CHART', 'FECHA_HORA', 'FECHA_HORA_STR', 'RUT_CLEAN', 'LABEL_SELECT']]
        if 'TIPO_RESCATE' in cols_final_table:
            cols_final_table.insert(0, cols_final_table.pop(cols_final_table.index('TIPO_RESCATE')))

        import io
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine='xlsxwriter') as writer:
            df_export = df_sorted[cols_final_table].copy()
            
            conteo_atenciones = df_export.groupby('RUT').size().reset_index(name='CANT_ATENCIONES')
            df_export = df_export.merge(conteo_atenciones, on='RUT', how='left')
            
            cols_export = list(df_export.columns)
            cols_export.insert(2, cols_export.pop(cols_export.index('CANT_ATENCIONES')))
            df_export = df_export[cols_export]
            
            df_export.to_excel(writer, index=False, sheet_name='Nómina_Completa')
            
            if 'FECHA_HORA' in df_sorted.columns:
                df_contacto = df_sorted.sort_values('FECHA_HORA', ascending=False).drop_duplicates(subset=['RUT'], keep='first').copy()
            else:
                df_contacto = df_sorted.drop_duplicates(subset=['RUT'], keep='first').copy()
                
            cols_contacto = [c for c in ['RUT', 'NOMBRE_PACIENTE', 'TELEFONO', 'SECTOR', 'EDAD_ACTUAL', 'FECHA_AGENDADA', 'HORA_AGENDADA', 'NOMBRE_PROFESIONAL', 'MOTIVO_CONSULTA'] if c in df_contacto.columns]
            df_contacto = df_contacto[cols_contacto]
            df_contacto = df_contacto.merge(conteo_atenciones, on='RUT', how='left')
            df_contacto.rename(columns={'FECHA_AGENDADA': 'ULTIMA_FECHA_AGENDADA', 'HORA_AGENDADA': 'ULTIMA_HORA_AGENDADA'}, inplace=True)
            df_contacto.to_excel(writer, index=False, sheet_name='Contactabilidad_Únicos')
            
            if 'SECTOR' in df_contacto.columns:
                df_sec = df_contacto.groupby('SECTOR')['RUT'].nunique().reset_index(name='Total_Pacientes_Unicos')
                df_sec['Fuga_Estimada_CLP'] = df_sec['Total_Pacientes_Unicos'] * 16872
                df_sec = df_sec.sort_values('Total_Pacientes_Unicos', ascending=False)
                df_sec.to_excel(writer, index=False, sheet_name='Resumen_Sectores')
                
            if 'NOMBRE_PROFESIONAL' in df_contacto.columns:
                df_prof = df_contacto.groupby('NOMBRE_PROFESIONAL')['RUT'].nunique().reset_index(name='Total_Pacientes_Unicos')
                df_prof['Fuga_Estimada_CLP'] = df_prof['Total_Pacientes_Unicos'] * 16872
                df_prof = df_prof.sort_values('Total_Pacientes_Unicos', ascending=False)
                df_prof.to_excel(writer, index=False, sheet_name='Resumen_Profesionales')

            workbook = writer.book
            header_format = workbook.add_format({
                'bold': True, 'font_color': 'white', 'bg_color': '#00A8E8', 'border': 1
            })
            
            for sheet_name in writer.sheets:
                worksheet = writer.sheets[sheet_name]
                if sheet_name == 'Nómina_Completa':
                    df_sheet = df_export
                elif sheet_name == 'Contactabilidad_Únicos':
                    df_sheet = df_contacto
                elif sheet_name == 'Resumen_Sectores':
                    df_sheet = df_sec
                else:
                    df_sheet = df_prof
                
                for col_num, value in enumerate(df_sheet.columns.values):
                    worksheet.write(0, col_num, value, header_format)
                    max_len = max(df_sheet.iloc[:, col_num].astype(str).map(len).max(), len(str(value)))
                    worksheet.set_column(col_num, col_num, min(max_len + 2, 50))
                    
                worksheet.autofilter(0, 0, len(df_sheet), len(df_sheet.columns) - 1)
            
        excel_data = excel_buffer.getvalue()
        
        st.download_button(
            label="📊 Descargar Nómina Institucional (Excel)",
            data=excel_data,
            file_name=f"NOMINA_ESTRATEGICA_{datetime.now().strftime('%Y%m%d')}.xlsx",
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type='primary',
            use_container_width=False
        )
            
        configuracion_columnas = {
            "TIPO_RESCATE": st.column_config.TextColumn("Tipo de Rescate", width="small"),
            "RUT": st.column_config.TextColumn("RUT", width="small"),
            "NOMBRE_PACIENTE": st.column_config.TextColumn("Nombre Paciente", width="medium"),
            "TELEFONO": st.column_config.TextColumn("Teléfono", width="small"),
            "EDAD_ACTUAL": st.column_config.NumberColumn("Edad"),
            "SECTOR": "Sector",
            "POLICLINICO": "Policlínico",
            "PROFESION": "Especialidad",
            "NOMBRE_PROFESIONAL": "Profesional",
            "FECHA_AGENDADA": "Fecha",
            "HORA_AGENDADA": "Hora"
        }
        
        st.dataframe(
            df_sorted[cols_final_table],
            use_container_width=True,
            hide_index=True,
            column_config=configuracion_columnas
        )

        if st.button("🔄 Forzar Actualización desde la Nube"): 
            st.cache_data.clear()
            st.rerun()

    with tab4:
        st.markdown("### 📝 Registro Manual de Pacientes Rescatados")
        st.info("Los pacientes registrados aquí **desaparecerán automáticamente** de las brechas de per cápita pendientes.")
        
        if not df_filtered.empty:
            df_ordenado_4 = df_filtered.copy()
            if 'FECHA_AGENDADA' in df_ordenado_4.columns:
                fecha_b = df_ordenado_4['FECHA_AGENDADA'].astype(str).str.split(' ').str[0].replace({'nan': '', 'None': ''})
                if 'HORA_AGENDADA' in df_ordenado_4.columns:
                    hora_b = df_ordenado_4['HORA_AGENDADA'].astype(str).replace({'nan': '00:00', 'None': '00:00', '': '00:00'})
                    df_ordenado_4['FECHA_HORA_STR'] = fecha_b + ' ' + hora_b
                    df_ordenado_4['FECHA_HORA'] = pd.to_datetime(df_ordenado_4['FECHA_HORA_STR'], errors='coerce', dayfirst=True)
                else:
                    df_ordenado_4['FECHA_HORA'] = pd.to_datetime(fecha_b, errors='coerce', dayfirst=True)
                idx_nat = df_ordenado_4['FECHA_HORA'].isna() & (fecha_b != '')
                if idx_nat.any():
                    df_ordenado_4.loc[idx_nat, 'FECHA_HORA'] = pd.to_datetime(fecha_b[idx_nat], errors='coerce', dayfirst=True)
                df_ordenado_4 = df_ordenado_4.sort_values(by='FECHA_HORA', ascending=True)
            
            def format_option(row):
                try:
                    f = row['FECHA_AGENDADA']
                    h = row['HORA_AGENDADA']
                    if pd.isna(f) or pd.isna(h):
                        return f"{row['RUT']} - {row['NOMBRE_PACIENTE']}"
                    return f"{row['RUT']} - {row['NOMBRE_PACIENTE']} ({f} {h})"
                except:
                    return str(row['RUT'])

            df_ordenado_4['LABEL_SELECT'] = df_ordenado_4.apply(format_option, axis=1)
            opciones_dict = dict(zip(df_ordenado_4['LABEL_SELECT'], df_ordenado_4['RUT']))
            
            rut_label = st.selectbox("Seleccione el paciente a rescatar (Ordenado cronológicamente)", [""] + list(opciones_dict.keys()))
            
            if rut_label:
                rut_seleccionado = opciones_dict[rut_label]
                paciente_data = df_filtered[df_filtered['RUT'] == rut_seleccionado].iloc[0]
                
                # Retrieve TIPO_RESCATE
                import pytz
                from datetime import datetime
                chile_tz = pytz.timezone('America/Santiago')
                ahora_chile = datetime.now(chile_tz).replace(tzinfo=None)
                
                status_rescate = "Desconocido"
                if 'FECHA_AGENDADA' in df_filtered.columns:
                    try:
                        f_base = str(paciente_data['FECHA_AGENDADA']).split(' ')[0]
                        if f_base in ['nan', 'None', '']: f_base = ""
                        h_base = str(paciente_data.get('HORA_AGENDADA', '00:00')).replace('nan', '00:00').replace('None', '00:00')
                        if h_base == '': h_base = '00:00'
                        
                        dt_cita = pd.to_datetime(f_base + ' ' + h_base, dayfirst=True)
                        if pd.isna(dt_cita) and f_base != "":
                            dt_cita = pd.to_datetime(f_base, dayfirst=True)
                            
                        if pd.isna(dt_cita):
                            status_rescate = "Sin Fecha"
                        elif dt_cita < ahora_chile:
                            status_rescate = "Rescate Retroactivo (Cita pasada)"
                        else:
                            status_rescate = "Por Rescatar (Cita futura)"
                    except:
                        pass
                
                if status_rescate == "Rescate Retroactivo (Cita pasada)":
                    st.warning(f"⚠️ **Estado de la Hora:** {status_rescate} - ¡Paciente ya se atendió! Procede a capturarlo a la brevedad.")
                elif status_rescate == "Por Rescatar (Cita futura)":
                    st.success(f"✅ **Estado de la Hora:** {status_rescate} - ¡Estás a tiempo de interceptarlo en su próxima atención!")
                else:
                    st.info(f"ℹ️ **Estado de la Hora:** {status_rescate} - (Demanda espontánea o sin agendamiento formal).")
                    
                with st.form("form_rescate", clear_on_submit=True):
                    c_f1, c_f2 = st.columns(2)
                    with c_f1:
                        nombre = st.text_input("Nombres", value=paciente_data['NOMBRE_PACIENTE'])
                        opciones_centro = ["Centro De Salud Familiar Chol Chol", "Posta De Salud Rural Malalche", "Posta De Salud Rural Huentelar", "Posta De Salud Rural Huamaqui"]
                        centro_actual = paciente_data['NOMBRE_CENTRO'] if 'NOMBRE_CENTRO' in df_filtered.columns else ""
                        idx_centro = opciones_centro.index(centro_actual) if centro_actual in opciones_centro else 0
                        centro = st.selectbox("Centro de Salud", opciones_centro, index=idx_centro)
                        rut_val = st.text_input("RUT", value=paciente_data['RUT'], disabled=True)
                    with c_f2:
                        meses_dict = {1:"Enero",2:"Febrero",3:"Marzo",4:"Abril",5:"Mayo",6:"Junio",7:"Julio",8:"Agosto",9:"Septiembre",10:"Octubre",11:"Noviembre",12:"Diciembre"}
                        anio = st.number_input("Año de Corte", value=datetime.now().year, min_value=2020)
                        mes = st.selectbox("Mes de Corte", list(meses_dict.values()), index=datetime.now().month - 1)
                    
                    obs = st.text_area("Observaciones (Ej: Inscrito Fonasa, No contesta, Cambio domicilio)")
                    
                    if st.form_submit_button("Confirmar Rescate", type="primary", use_container_width=True):
                        try:
                            scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
                            creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=scope)
                            client_gs = gspread.authorize(creds)
                            
                            url_rescates = st.secrets["URL_RESCATES"]
                            sheet_rescates = client_gs.open_by_url(url_rescates)
                            ws_rescates = sheet_rescates.worksheet("percapita")
                            
                            # NOMBRES NOMBRE_CENTRO RUT ANIO_CORTE MES_CORTE OBS FECHA_RESCATE USUARIO_GESTOR
                            fecha_rescate = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            usuario_gestor = MASTER_ACCOUNT_ID
                            
                            row = [nombre, centro, rut_val, anio, mes, obs, fecha_rescate, usuario_gestor]
                            ws_rescates.append_row(row)
                            
                            st.success(f"✅ ¡Paciente {nombre} ({rut_val}) registrado como rescatado!")
                            st.cache_data.clear()
                            time.sleep(2)
                            st.rerun()
                        except Exception as e:
                            st.error(f"❌ Error guardando datos: {e}")
        else:
            st.warning("No hay pacientes pendientes con los filtros actuales para rescatar.")

# --- FOOTER (REPLICADO EXACTO DE APP BASE) ---
st.markdown("---")
with st.container():
    col_f1, col_f2, col_f3, col_f4 = st.columns([3, 1, 5, 1])
    
    with col_f2:
        # LOGO EMPRESA (LOGO_ALAIN) - Tal cual el código base
        if os.path.exists("logo_alain.png"):
            st.image("logo_alain.png", width=150)
        elif APP_CONFIG['imagenes'].get('LOGO_ALAIN'):
            st.image(APP_CONFIG['imagenes']['LOGO_ALAIN'], width=150)
        else:
            st.info("Logo Dev")
            
    with col_f3:
        st.markdown("""
            <div style='text-align: left; color: #888888; font-size: 16px; padding-bottom: 20px;'>
                💼 Aplicación desarrollada por <strong>Alain Antinao Sepúlveda</strong> <br>
                📧 Contacto: <a href="mailto:alain.antinao.s@gmail.com" style="color: #006DB6;">alain.antinao.s@gmail.com</a> <br>
                🌐 Más información en: <a href="https://alain-antinao-s.notion.site/Alain-C-sar-Antinao-Sep-lveda-1d20a081d9a980ca9d43e283a278053e" target="_blank" style="color: #006DB6;">Mi página personal</a>
            </div>
        """, unsafe_allow_html=True)