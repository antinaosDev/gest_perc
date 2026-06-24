import time
import random # <--- VITAL PARA HUMANIZAR EL COMPORTAMIENTO
import os
import pandas as pd
import streamlit as st
import pyperclip
import altair as alt  # Librería de gráficos de alto rendimiento
from datetime import datetime, timedelta
from groq import Groq # Importamos la librería de IA
import requests # Para llamadas API robustas
import re # IMPORTANTE: Para limpiar las etiquetas <think>
import json # NECESARIO: Para leer las credenciales y el contador JSON
import tempfile # NECESARIO PARA EL PDF
from fpdf import FPDF # NECESARIO PARA EL PDF
import ast # NECESARIO PARA LEER LISTAS DESDE EXCEL

# Librerías de Automatización
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.common.exceptions import TimeoutException
import gspread
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request

# -----------------------------------------------------------------------------
# 0. CONSTANTES DE LOCALIZACIÓN Y CONFIGURACIÓN
# -----------------------------------------------------------------------------

MESES_ES = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
}

DIAS_ES = {
    0: "Lunes", 1: "Martes", 2: "Miércoles", 3: "Jueves", 4: "Viernes", 5: "Sábado", 6: "Domingo"
}

# === DATOS DE ARRANQUE (BOOTSTRAP) ===
# MASTER_ACCOUNT_ID se maneja dinámicamente con st.session_state
URL_ADMIN_MASTER = "https://docs.google.com/spreadsheets/d/1UkY4sTIalaHhJGgBBPyelgcxU3ebFX-NYa74c2qdviw/edit?usp=sharing"

# === TUS IMÁGENES POR DEFECTO (RESPALDO DE SEGURIDAD) ===
DEFAULT_LOGO_ALAIN = "https://drive.google.com/file/d/1QyEf4sN2lMxaBOOY8asFDTYFxELcT_rR/view?usp=sharing"
DEFAULT_LOGO_NOTI = "https://drive.google.com/file/d/14GQkoC_ykLs6BPK75FQDiCrbQ8Xj9r4b/view?usp=sharing"

# CREDENCIALES BOOTSTRAP (Fijas)
try:
    BOOTSTRAP_CREDS = dict(st.secrets["gcp_service_account"])
except Exception:
    BOOTSTRAP_CREDS = {}

# -----------------------------------------------------------------------------
# 1. FUNCIONES DE UTILIDAD Y BACKEND
# -----------------------------------------------------------------------------

def procesar_imagen_drive(url_drive, creds_dict):
    """Procesa URLs de Google Drive para obtener contenido binario de imágenes."""
    if not url_drive or len(url_drive) < 10: return None
    file_id = None
    patterns = [r'/d/([a-zA-Z0-9_-]+)', r'id=([a-zA-Z0-9_-]+)']
    for pattern in patterns:
        match = re.search(pattern, url_drive)
        if match:
            file_id = match.group(1)
            break
    if not file_id: return None
    public_download_url = f"https://drive.google.com/uc?export=view&id={file_id}"
    try:
        response = requests.get(public_download_url, timeout=5)
        if response.status_code == 200: return response.content 
    except: pass
    try:
        scopes = ['https://www.googleapis.com/auth/drive.readonly']
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        creds.refresh(Request()) 
        headers = {"Authorization": f"Bearer {creds.token}"}
        api_url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        response = requests.get(api_url, headers=headers, timeout=5)
        if response.status_code == 200: return response.content
    except: pass
    return public_download_url

# === NUEVAS FUNCIONES PARA DEMOGRAFÍA Y PERCÁPITA ===
def normalize_rut(rut):
    """Limpia el RUT para asegurar cruces exitosos (sin puntos ni guiones)."""
    if not rut: return "S/I"
    rut = str(rut).upper().strip()
    rut = rut.replace(".", "").replace("-", "").replace(" ", "")
    rut = rut.lstrip("0") # Quitar ceros a la izquierda
    if len(rut) < 2: return "INVALIDO"
    return rut

def get_demographic_data(url_demographic, client):
    """Carga y procesa las hojas 'sector' y 'percapita'."""
    dem_data = {'sector': pd.DataFrame(), 'percapita': pd.DataFrame()}
    try:
        if not url_demographic or len(url_demographic) < 10:
            return dem_data
        
        # Abrimos la planilla demográfica
        sheet_dem = client.open_by_url(url_demographic)
        
        # 1. Cargar Sector
        try:
            ws_sector = sheet_dem.worksheet("sector")
            data_sector = ws_sector.get_all_records()
            df_sector = pd.DataFrame(data_sector)
            if not df_sector.empty and 'RUT' in df_sector.columns:
                df_sector['RUT_CLEAN'] = df_sector['RUT'].apply(normalize_rut)
                df_sector = df_sector.drop_duplicates(subset=['RUT_CLEAN'])
                dem_data['sector'] = df_sector[['RUT_CLEAN', 'DISTRITO', 'SECTOR']]
        except: pass

        # 2. Cargar Percapita (Lógica Inteligente: Último Mes Disponible)
        try:
            ws_perca = sheet_dem.worksheet("percapita")
            data_perca = ws_perca.get_all_records()
            df_perca = pd.DataFrame(data_perca)
            
            if not df_perca.empty and 'RUT' in df_perca.columns:
                df_perca['RUT_CLEAN'] = df_perca['RUT'].apply(normalize_rut)
                
                # Normalizar columnas de fecha
                df_perca['ANIO_NUM'] = pd.to_numeric(df_perca['ANIO_CORTE'], errors='coerce').fillna(0)
                
                # Mapa de meses para ordenar
                meses_map_rev = {
                    "ENERO":1, "FEBRERO":2, "MARZO":3, "ABRIL":4, "MAYO":5, "JUNIO":6,
                    "JULIO":7, "AGOSTO":8, "SEPTIEMBRE":9, "OCTUBRE":10, "NOVIEMBRE":11, "DICIEMBRE":12
                }
                def mes_to_num(m):
                    m_str = str(m).upper().strip()
                    return meses_map_rev.get(m_str, 0)
                
                df_perca['MES_NUM'] = df_perca['MES_CORTE'].apply(mes_to_num)
                
                # Encontrar el MÁXIMO periodo disponible (Ej: 2025 Septiembre)
                max_anio = df_perca['ANIO_NUM'].max()
                max_mes = df_perca[df_perca['ANIO_NUM'] == max_anio]['MES_NUM'].max()
                
                # Filtrar base solo con el último corte
                df_perca_latest = df_perca[
                    (df_perca['ANIO_NUM'] == max_anio) & 
                    (df_perca['MES_NUM'] == max_mes)
                ].copy()
                
                # CREAR ETIQUETA LEGIBLE DE FECHA PARA EL REPORTE
                nombre_mes_corte = MESES_ES.get(max_mes, "Desconocido")
                label_fecha = f"{nombre_mes_corte} {int(max_anio)}"
                df_perca_latest['FECHA_CORTE_PERCA'] = label_fecha
                
                df_perca_latest['ESTA_PERCAPITADO'] = "SI"
                dem_data['percapita'] = df_perca_latest[['RUT_CLEAN', 'NOMBRE_CENTRO', 'ESTA_PERCAPITADO', 'FECHA_CORTE_PERCA']]
                
        except Exception as e: pass
            
    except Exception as e: pass
        
    return dem_data

# === LISTAS MAESTRAS DE CLASIFICACIÓN (POR DEFECTO) ===
DEFAULT_RESPUESTAS_SI = [
    "sí", "si", "sip", "sii", "siii", "sipo", "sipu", "sipi", "sí, confirmo", "confirmo",
    "confirmado", "confirmada", "confirmadísimo", "confirmadísima", "claro", "claro que sí",
    "por supuesto", "obvio", "obvio que sí", "obviao", "obvio po", "obvio que voy",
    "obvio hermano voy", "de todas maneras", "de todas formas", "de una", "de pana",
    "de pana sí", "de pana voy", "altiro", "altiro sí", "altiro voy", "bacán", "bacán voy",
    "filete", "la raja voy", "pulento", "terrible sí", "terrible filete voy", "ahí estaré",
    "voy", "voy sí", "sí voy", "sí voy a ir", "sí alcanzo", "sí puedo", "puedo ir",
    "confirmo asistencia", "confirmo la hora", "confirmo cita", "asistiré", "llego",
    "llego sí", "llegaré", "cuento con ir", "cualquier cosa llego", "ningún problema",
    "ningún drama", "todo bien", "todo ok", "ok", "okay", "okey", "oki", "okis",
    "dale sí", "dale no más", "vale", "vale sí", "va", "vamos", "yes", "yes bro",
    "simon", "affirmative", "afirmativo", "positivo", "sí, sin falta", "sí, estaré ahí",
    "me sirve", "me acomoda", "está bien", "está perfect", "perfect", "perfecto",
    "excelente", "súper", "super bien", "joya", "joyita", "regio", "maravilloso",
    "ya", "ya sí", "ya bacán", "ya voy", "ya confirmo", "ya estaré", "listo", "lito",
    "listo confirmo", "listoco", "todo listo", "listo entonces", "listo voy",
    "confirmadito", "simonazo", "seeh", "seee", "seeeh", "sehhh", "seee si",
    "vamos pa’ esa", "vamos nomás", "vamo’", "vamo altiro", "✔️", "👍", "👌", "🙌",
    "🤙", "💯", "🔥 voy", "🍀 voy", "✨ sí"
]

DEFAULT_RESPUESTAS_NO = [
    "no", "nop", "nope", "noo", "nooo", "noppo", "nopo", "no puedo", "no puedo ir",
    "no voy", "no alcanzo", "no me da", "no me da el tiempo", "no me sirve",
    "no me acomoda", "no estoy disponible", "no podré asistir", "no asistiré", "no iré",
    "no llego", "no estaré", "no me es posible", "me es imposible", "imposible",
    "negativo", "lamentablemente no puedo", "tengo que cancelar", "cancelo", "cancelado",
    "cancelada", "cancelar hora", "cancelar asistencia", "reagendar", "quiero reagendar",
    "necesito reagendar", "necesito otra hora", "cambiar hora", "no puedo a esa hora",
    "no puedo ese día", "no puedo no más", "no me tinca", "no me resulta",
    "hoy no me resulta", "no puedo sorry", "sorry no puedo", "no sorry", "no quiero ir",
    "prefiero no ir", "voy a faltar", "estoy ocupado", "estoy tapado de cosas",
    "estoy enfermo", "estoy enferma", "estoy pal gato", "estoy pa’ la cagá",
    "no tengo tiempo", "no llego ni cagando", "no alcanzo ni al metro", "no será posible",
    "no cacho si pueda", "no estoy en condiciones", "no doy más", "no puedo manejar",
    "mi pega no me deja", "tengo reunión", "no la hago", "no me da la agenda",
    "no lo lograré", "🚫", "❌", "🛑", "🙅", "🙅‍♂️", "🙅‍♀️"
]

def load_app_configuration(account_id):
    """Carga la configuración dinámica desde Google Sheets (Admin Master)."""
    config = {
        'valido': False, 'mensaje': '', 'datos': {}, 'credenciales_finales': None, 
        'licencia': {}, 'uso_ia_actual': 0, 'row_index': -1, 'templates': {}, 
        'imagenes': {'LOGO_ALAIN': None, 'LOGO_NOTI': None},
        'keywords': {'SI': DEFAULT_RESPUESTAS_SI, 'NO': DEFAULT_RESPUESTAS_NO} # Inicializamos con defaults
    }
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
        records = sheet_admin.get_all_records()
        target_row = None
        row_idx = -1
        for idx, item in enumerate(records):
            if str(item['CUENTA']) == account_id:
                target_row = item
                row_idx = idx + 2 
                break
        if not target_row:
            config['mensaje'] = f"Cuenta '{account_id}' no encontrada en Admin."
            return config

        config['row_index'] = row_idx
        estado_app = str(target_row.get('ESTADO_APP', 'INACTIVO')).upper().strip()
        estado_ia = str(target_row.get('ESTADO_IA', 'GRATIS')).upper().strip()
        
        try: limite_gratis_conf = int(target_row.get('LIMITE_GRATIS', 2))
        except: limite_gratis_conf = 2
        try: limite_pro_conf = int(target_row.get('LIMITE_PRO', 5))
        except: limite_pro_conf = 5
        
        limite = limite_pro_conf if estado_ia == 'PRO' else limite_gratis_conf
        activo = True if estado_app == 'ACTIVO' else False
        config['licencia'] = {'activo': activo, 'plan': estado_ia, 'limite': limite}

        if not activo:
            config['mensaje'] = "La cuenta está inactiva."
            return config

        usos_raw = target_row.get('USOS_IA', '')
        hoy_str = datetime.now().strftime("%d/%m/%Y")
        contador_calculado = 0
        try:
            if isinstance(usos_raw, str) and "{" in usos_raw:
                datos_uso = json.loads(usos_raw)
                if datos_uso.get('fecha') == hoy_str:
                    contador_calculado = int(datos_uso.get('contador', 0))
            else: contador_calculado = 0
        except: contador_calculado = 0
        config['uso_ia_actual'] = contador_calculado

        config['templates']['MSG_AGEND'] = str(target_row.get('MENSAJE_AGEND', '')).strip()
        config['templates']['MSG_REAGEND'] = str(target_row.get('MENSAJE_REAGEND', '')).strip()
        config['templates']['PROMPT'] = str(target_row.get('PROMPT', '')).strip()
        
        config['datos']['GROQ_API_KEY'] = str(target_row.get('GROQ_API_KEY', '')).strip()
        config['datos']['URL_SHEET'] = str(target_row.get('URL_SHEET', '')).strip()
        
        # === LECTURA DE URL DEMOGRÁFICA ===
        config['datos']['URL_DATOS_DEM'] = str(target_row.get('DATOS_DEM', '')).strip()
        
        # === LECTURA DE CLAVE DE PLATAFORMA ===
        config['datos']['CLAVE_PLATAFORMA'] = str(target_row.get('CLAVE_PLATAFORMA', '')).strip()
        
        # === LECTURA DE PALABRAS CLAVE PERSONALIZADAS (AFIRMACION / NEGACION) ===
        try:
            raw_si = str(target_row.get('AFIRMACION', '')).strip()
            # Si contiene brackets, intentamos parsear como lista
            if len(raw_si) > 5 and "[" in raw_si:
                config['keywords']['SI'] = ast.literal_eval(raw_si)
        except: pass 

        try:
            raw_no = str(target_row.get('NEGACION', '')).strip()
            if len(raw_no) > 5 and "[" in raw_no:
                config['keywords']['NO'] = ast.literal_eval(raw_no)
        except: pass

        cred_raw = target_row.get('CREDENTIAL_DICT', '')
        if isinstance(cred_raw, dict): config['credenciales_finales'] = cred_raw
        elif isinstance(cred_raw, str) and len(cred_raw) > 10:
            try: config['credenciales_finales'] = json.loads(cred_raw)
            except: config['credenciales_finales'] = BOOTSTRAP_CREDS
        else: config['credenciales_finales'] = BOOTSTRAP_CREDS

        url_logo_alain = str(target_row.get('LOGO_ALAIN', '')).strip() 
        url_logo_noti = str(target_row.get('LOGO_NOTI', '')).strip()    
        if len(url_logo_alain) < 5: url_logo_alain = DEFAULT_LOGO_ALAIN
        if len(url_logo_noti) < 5: url_logo_noti = DEFAULT_LOGO_NOTI

        config['imagenes']['LOGO_ALAIN'] = procesar_imagen_drive(url_logo_alain, BOOTSTRAP_CREDS)
        config['imagenes']['LOGO_NOTI'] = procesar_imagen_drive(url_logo_noti, BOOTSTRAP_CREDS)

        config['valido'] = True
            
    except Exception as e:
        config['mensaje'] = f"Error conectando a Admin Master: {e}"
        
    return config

def registrar_consumo_ia(row_index, nuevo_contador):
    """Actualiza el contador de uso de IA en la hoja Admin."""
    try:
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(BOOTSTRAP_CREDS, scopes=scope)
        client = gspread.authorize(creds)
        sheet_admin = client.open_by_url(URL_ADMIN_MASTER).sheet1
        hoy_str = datetime.now().strftime("%d/%m/%Y")
        json_data = json.dumps({"fecha": hoy_str, "contador": nuevo_contador})
        sheet_admin.update_cell(row_index, 8, json_data) 
        return True
    except Exception as e:
        return False

LISTA_PROFESIONES = sorted([
    "ASISTENTE SOCIAL", "EDUCADORA", "ENFERMERA(O)", "FONOAUDIOLOGO", "KINESIOLOGO",
    "MATRON(A)", "MEDICO APS", "NUTRICIONISTA", "ODONTOLOGIA APS", "PROCEDIMIENTO",
    "PROFESOR", "PSICOLOGIA", "QUIMICO FARMACEUTICO", "TECNICO ENFERMERIA",
    "TECNICO ODONTOLOGIA", "TECNOLOGO MEDICO", "TERAPEUTA OCUPACIONAL"
])

LISTA_HORAS = [f"{h:02d}:{m:02d}" for h in range(8, 18) for m in (0, 15, 30, 45)]

LISTA_MOTIVOS = sorted([
    "ACCIONES PREVENTIVAS", "ACCIONES REMOTAS", "ADM MEDICAMENTO EV", "CAMPAÑA PAP", "CATEER URINARIO",
    "CONSEJERIA FAMILIAR", "CONSEJERIA INDIVIDUAL", "CONSULTA", "CONSULTA (MADIS)", "CONSULTA ABREVIADA",
    "CONSULTA BREVE", "CONSULTA CONTROL APS", "CONSULTA DIAGNOSTICO ADULTO PRAPS", "CONSULTA FONOAUDIOLOGICA",
    "CONSULTA INDIVIDUAL", "CONSULTA INGRESO", "CONSULTA INGRESO ADULTO MAYOR", "CONSULTA INGRESO DENTAL",
    "CONSULTA INGRESO ECICEP G1 Y G2", "CONSULTA INGRESO ECICEP G3", "CONSULTA KINESICA AGUDA RESPIRATORIA",
    "CONSULTA LACTANCIA MATERNA", "CONSULTA MATRONA", "CONSULTA MORBILIDAD INFANTIL", "CONSULTA NUTRICIONAL 3 AÑOS 6 MESES",
    "CONSULTA NUTRICIONAL 3 MESES", "CONSULTA PERIODONCIA", "CONSULTA PROTESIS REMOVIBLE", "CONSULTA PSICOLOGICA",
    "CONSULTA REGULACION FERTILIDAD", "CONSULTA SALUD MENTAL", "CONSULTA SOCIAL", "CONSULTA TRATAMIENTO GES GESTANTE",
    "CONSULTA URGENCIA", "CONSULTA VACUNATORIO", "CONSULTORIA", "CONTROL", "CONTROL CARDIOVASCULAR",
    "CONTROL ECICEP G1 Y G2", "CONTROL ECICEP G3", "CONTROL ENFERMERIA", "CONTROL FONOAUDIOLOGICO",
    "CONTROL GRUPAL", "CONTROL INDIVIDUAL", "CONTROL NANEAS", "CONTROL ODONTOLOGICO", "CONTROL PERIODONTAL",
    "CONTROL PRENATAL", "CONTROL RESPIRATORIO CRONICO", "CONTROL SALUD INTEGRAL ADOLESCENTE", "CONTROL SALUD INTEGRAL DIADA",
    "CONTROL SALUD INTEGRAL INFANCIA", "CONTROL SALUD INTEGRAL INFANCIA (1 Y 3 MESES)", "CONTROL SALUD INTEGRAL INFANCIA C/ESPE",
    "CONTROL SALUD MENTAL", "CONTROL SALUD SEXUAL Y REPRODUCTIVA", "CURACION MENOR", "CURACIONES AVANZADAS",
    "CURACIONES SIMPLES", "ECOGRAFIA", "ECOGRAFIA OBSTETRICA", "EDUCACION", "EDUCACION GRUPAL", "EDUCACION GRUPAL (MADIS)",
    "EDUCACION INDIVIDUAL", "ELECTROCARDIOGRAMA", "EMP", "EMPAM", "EMPAM SEGUIMIENTO", "EVALUACION - ENTRENAMIENTO AT (REHABILITACION)",
    "EVALUACION INICIAL (REHABILITACION)", "EVALUACION INTERMEDIA (REHABILITACION)", "EXAMEN FUNCIONAL VIII PAR",
    "EXAMEN OCULAR", "FONDO DE OJO", "GESTION ADMINISTRATIVA", "GESTION DE CASO", "HOSPITAL DIGITAL RURAL",
    "HOSPITALIZACION ABREVIADA - INTERVENCION PSICOSOCIAL", "INCLUYE PRESION ARTERIAL", "INGRESO-REINGRESO RESPIRATORIO",
    "INGRESO/EGRESO MAS AMA", "INTERVENCION PSICOSOCIAL", "INTERVENCION PSICOSOCIAL GRUPAL", "INYECTABLE",
    "LAVADO DE OIDOS", "MEMPAM", "MEMPAM SEGUIMIENTO", "OTRAS", "OTRAS INTERVENCIONES", "OTROS CONTROLES",
    "OTROS PROCEDIMIENTOS", "OTROS PROCEDIMIENTOS AUDIOLOGICOS", "OTROS PROCEDIMIENTOS RADIOLOGICOS", "PROCEDIMIENTO - TTO - OTRAS",
    "PSICOTERAPIA INDIVIDUAL", "RADIOGRAFIA", "REEDUCACION GRUPAL", "REFERENCIA ASISTIDA", "REFERENCIA ODONTOLOGICA",
    "REHABILITACION", "REHABILITACION INDIVIDUAL", "REHABILITACION PULMONAR", "SALUD FAMILIAR", "SCREENING PRESION ARTERIAL",
    "TALLER", "TALLER MAS AMA", "TALLER NEP", "TALLER PROMOCION LENGUAJE", "TALLER PROMOCION MOTOR", "TAMIZAJE",
    "TAMIZAJE PRAPS", "TECNICO ENFERMERIA", "TELECONSULTA", "TELEINTERCONSULTA", "TEST DE EJERCICIO", "TEST DE MARCHE",
    "TOMA MUESTRA", "TRABAJO EXTRAMURAL", "TRATAMIENTO ODONTOLOGICO INTEGRAL", "TTO - OTRAS", "VACUNATORIO",
    "VDRL, PR VDRL, SDA SC", "VIDA SANA", "VIDA SANA EDUCACION", "VISITA DOMICILIARIA", "VISITA DOMICILIARIA INTEGRAL",
    "VISITA FARMACEUTICA EN DOMICILIO", "VISITAS DOMICILIARIA"
])

# -----------------------------------------------------------------------------
# LOGICA DEL NEGOCIO (BACKEND)
# -----------------------------------------------------------------------------

def connect_sheet(url_sheet=None, creds_dict=None):
    try:
        if url_sheet is None:
            url_sheet = APP_CONFIG['datos']['URL_SHEET']
        if creds_dict is None:
            creds_dict = APP_CONFIG['credenciales_finales']
            
        scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scope)
        client = gspread.authorize(creds)
        # MODIFICADO: Retorna sheet, client y mensaje
        return client.open_by_url(url_sheet).sheet1, client, "OK"
    except Exception as e: return None, None, str(e)

# --- FUNCIÓN DE CARGA ---
@st.cache_data(ttl=15)
def get_data_fresh(account_id):
    """Obtiene datos frescos de Google Sheets + Cruce Demográfico y Percapita."""
    config = load_app_configuration(account_id)
    if not config['valido']: return None
    
    url_sheet = config['datos'].get('URL_SHEET', '')
    url_dem = config['datos'].get('URL_DATOS_DEM', '')
    creds_dict = config.get('credenciales_finales')
    
    sheet, client, msg = connect_sheet(url_sheet, creds_dict) 
    if not sheet: return None
    
    # 1. Cargar Datos Pacientes (Base Operativa)
    data = sheet.get_all_values()
    df = pd.DataFrame(data[1:], columns=data[0])
    df.columns = df.columns.str.strip()
    
    # 2. Cargar Datos Demográficos (Nueva Lógica)
    dem_info = get_demographic_data(url_dem, client)
    
    # === LÓGICA DE CRUCE (MERGE) ===
    if 'RUT' in df.columns:
        df['RUT_CLEAN'] = df['RUT'].apply(normalize_rut)
        
        # A) Cruce con Sector/Distrito
        if not dem_info['sector'].empty:
            df = df.merge(dem_info['sector'], on='RUT_CLEAN', how='left')
            
            # --- NORMALIZACIÓN DE SECTORES (CORRECCIÓN SOLICITADA) ---
            # Reemplazar valores vacíos, nulos o 'No_Especificado' por 'Sin Sector'
            df['SECTOR'] = df['SECTOR'].replace(['No_Especificado', 'NO_ESPECIFICADO', 'No Especificado', ''], 'Sin Sector')
            df['SECTOR'] = df['SECTOR'].fillna('Sin Sector')
            
            df['DISTRITO'] = df['DISTRITO'].fillna('Sin Distrito')
        else:
            df['DISTRITO'] = 'Sin Info'
            df['SECTOR'] = 'Sin Info'
            
        # B) Cruce con Percápita (Solo último mes)
        if not dem_info['percapita'].empty:
            df = df.merge(dem_info['percapita'], on='RUT_CLEAN', how='left')
            # Si cruza es "INSCRITO", si es NaN es "PENDIENTE"
            df['ESTADO_PERCAPITA'] = df['ESTA_PERCAPITADO'].apply(lambda x: "INSCRITO" if x == "SI" else "PENDIENTE INSCRIPCION")
            df['CENTRO_SALUD'] = df['NOMBRE_CENTRO'].fillna('Desconocido')
            
            # Propagar la fecha de corte a todo el DF para mostrar en alerta (Forward Fill y Backward Fill)
            df['PERIODO_CORTE_LABEL'] = df['FECHA_CORTE_PERCA'].ffill().bfill()
        else:
            df['ESTADO_PERCAPITA'] = 'Sin Datos Base'
            df['CENTRO_SALUD'] = '-'
            df['PERIODO_CORTE_LABEL'] = 'Desconocido'
    
    # === PRE-PROCESAMIENTO AVANZADO PARA ANALITICA BI ===
    try:
        # 0. Determinación de Fecha y Hora Efectiva (Handling Rescheduling)
        # Default a la original
        df['FECHA_EFECTIVA'] = df['FECHA_AGENDADA']
        df['HORA_EFECTIVA'] = df['HORA_AGENDADA']
        
        # Identificar registros reagendados válidos (CAMBIO_DE_HORA='SI' y datos presentes)
        df['CAMBIO_CLEAN'] = df['CAMBIO_DE_HORA'].astype(str).str.strip().str.upper()
        mask_reag = (df['CAMBIO_CLEAN'] == 'SI') & (df['NUEVA_FECHA'].astype(str).str.len() > 5) & (df['HORA_NUEVA_FECHA'].astype(str).str.len() > 2)
        
        # Sobreescribir con datos nuevos donde corresponda
        df.loc[mask_reag, 'FECHA_EFECTIVA'] = df.loc[mask_reag, 'NUEVA_FECHA']
        df.loc[mask_reag, 'HORA_EFECTIVA'] = df.loc[mask_reag, 'HORA_NUEVA_FECHA']

        # 1. Procesamiento de Fechas Efectivas
        df['FECHA_DT'] = pd.to_datetime(df['FECHA_EFECTIVA'], format="%d/%m/%Y", errors='coerce')
        df['NUEVA_FECHA_DT'] = pd.to_datetime(df['NUEVA_FECHA'], format="%d/%m/%Y", errors='coerce') # Mantener para referencia
        
        # 2. Extracción de Hora y Formato AM/PM para Heatmap (Usando Hora Efectiva Limpia)
        
        # Función auxiliar de limpieza
        def clean_time_str(t_str):
            if not isinstance(t_str, str): return str(t_str)
            # Quitar puntos y espacios extra: "8:30 a.m." -> "8:30 am" -> "8:30 AM"
            t_str = t_str.lower().replace('.', '').strip()
            return t_str.upper()

        df['HORA_EFECTIVA_CLEAN'] = df['HORA_EFECTIVA'].apply(clean_time_str)

        # Convertimos a datetime tolerante a errores (intentando formato 12h y 24h)
        temp_dates = pd.to_datetime(df['HORA_EFECTIVA_CLEAN'], format='%I:%M %p', errors='coerce')
        
        # Fallback para formato 24h si el anterior falla
        mask_na = temp_dates.isna()
        if mask_na.any():
             temp_dates_24 = pd.to_datetime(df.loc[mask_na, 'HORA_EFECTIVA_CLEAN'], format='%H:%M', errors='coerce')
             temp_dates = temp_dates.fillna(temp_dates_24)

        df['HORA_INT'] = temp_dates.dt.hour.fillna(-1).astype(int) # 0-23
        df['HORA_LABEL'] = temp_dates.dt.strftime('%I %p').fillna('S/I') # 08 AM, 02 PM
        
        # Legacy support
        df['HORA_SIMPLE'] = df['HORA_AGENDADA'].astype(str).str.split(':').str[0] 
        
        # 3. Normalización de Texto
        df['MOTIVO_CLEAN'] = df['MOTIVO_CONSULTA'].astype(str).str.upper().str.strip()
        df['PROFESION_CLEAN'] = df['PROFESION'].astype(str).str.upper().str.strip()
        df['ESTADO_CLEAN'] = df['ESTADO'].replace('', 'PENDIENTE').fillna('PENDIENTE')

        # 4. Procesamiento Demográfico
        if 'EDAD_ACTUAL' in df.columns:
            df['EDAD_NUM'] = pd.to_numeric(df['EDAD_ACTUAL'], errors='coerce').fillna(0)
        else:
            df['EDAD_NUM'] = 0
        
        # 5. Calculo Días Restantes (Usando FECHA_DT que ahora es la efectiva)
        now = pd.Timestamp.now().normalize()
        if 'FECHA_DT' in df.columns:
            df['DIAS_RESTANTES'] = (df['FECHA_DT'] - now).dt.days.fillna(-999)
            dias_es = {0: 'Lunes', 1: 'Martes', 2: 'Miércoles', 3: 'Jueves', 4: 'Viernes', 5: 'Sábado', 6: 'Domingo'}
            df['DIA_SEMANA_ES'] = df['FECHA_DT'].dt.dayofweek.map(dias_es)
        else:
            df['DIAS_RESTANTES'] = -999
            df['DIA_SEMANA_ES'] = None

        # 6. ESTANDARIZACION DE CONFIRMACIONES
        df['STATUS_CONFIRMACION'] = 'PENDIENTE'
        if 'CONFIRMA_HORA' in df.columns:
            df.loc[df['CONFIRMA_HORA'].str.contains('CONFIRMADO', na=False), 'STATUS_CONFIRMACION'] = 'CONFIRMADO'
            df.loc[df['CONFIRMA_HORA'].str.contains('NO ASISTIRA', na=False), 'STATUS_CONFIRMACION'] = 'NO ASISTIRA'
        if 'CONFIRMA_REAGEN' in df.columns:
            df.loc[df['CONFIRMA_REAGEN'].str.contains('CONFIRMADO', na=False), 'STATUS_CONFIRMACION'] = 'CONFIRMADO (R)'
            df.loc[df['CONFIRMA_REAGEN'].str.contains('NO ASISTIRA', na=False), 'STATUS_CONFIRMACION'] = 'NO ASISTIRA (R)'
        
        # 7. ESTADO DEL PACIENTE UNIFICADO
        df['ESTADO_REAL'] = 'PENDIENTE'
        df.loc[df['ESTADO'].str.contains('OK', na=False), 'ESTADO_REAL'] = 'NOTIFICADO'
        if 'ESTADO_REA' in df.columns:
            df.loc[df['ESTADO_REA'].str.contains('OK', na=False), 'ESTADO_REAL'] = 'NOTIFICADO'
        df.loc[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO'), 'ESTADO_REAL'] = 'CONFIRMADO'

    except Exception as e:
        pass 
        
    return df

def init_driver():
    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")
    options.add_argument("--disable-infobars")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--remote-debugging-port=9222")
    user_data = os.path.join(os.getcwd(), "medtify_session")
    options.add_argument(f"--user-data-dir={user_data}")
    try: return webdriver.Chrome(options=options)
    except: return None

def esperar_login_qr(driver):
    wait = WebDriverWait(driver, 120)
    try:
        wait.until(EC.presence_of_element_located((By.ID, "side")))
        return True
    except TimeoutException: return False

def calcular_dias(fecha_texto):
    try:
        fecha_cita = datetime.strptime(str(fecha_texto).strip(), "%d/%m/%Y").date()
        hoy = datetime.now().date()
        return (fecha_cita - hoy).days
    except: return -999


# === FUNCIÓN PARA LLAMADA A IA (GROQ) CON PROMPT DINÁMICO DESDE SHEETS ===
# === FUNCIÓN PARA LLAMADA A IA (GROQ) ACTUALIZADA ===
def generar_analisis_clinico(df):
    try:
        client = Groq(api_key=GROQ_API_KEY)
        
        # --- 1. CÁLCULO DE VARIABLES ESTADÍSTICAS ---
        fecha_hoy = datetime.now().strftime("%d/%m/%Y")
        total_pacientes = len(df)
        
        # Demografía
        avg_edad = round(df['EDAD_NUM'].mean(), 1) if 'EDAD_NUM' in df.columns else 0
        pacientes_adulto_mayor = len(df[df['EDAD_NUM'] >= 65]) if 'EDAD_NUM' in df.columns else 0
        dist_genero = df['GENERO'].value_counts().head(3).to_dict() if 'GENERO' in df.columns else {}
        
        # Percapita
        no_inscritos_cnt = 0
        dist_sector = {}
        if 'ESTADO_PERCAPITA' in df.columns:
            no_inscritos_cnt = len(df[df['ESTADO_PERCAPITA'] == "PENDIENTE INSCRIPCION"])
        if 'SECTOR' in df.columns:
            dist_sector = df['SECTOR'].value_counts().head(3).to_dict()

        # Operativa
        notificados = len(df[df['ESTADO'].str.contains('OK', na=False)])
        confirmados = len(df[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
        cancelados = len(df[df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')]) 
        pendientes_respuesta = notificados - confirmados - cancelados
        
        # Tasa de Conversión
        tasa_conf = int((confirmados / notificados) * 100) if notificados > 0 else 0
        tasa_incertidumbre = round((pendientes_respuesta/total_pacientes)*100, 1) if total_pacientes > 0 else 0

        # Cupos Recuperables
        cupos_recuperables = 0
        if 'DIAS_RESTANTES' in df.columns:
            cupos_recuperables = len(df[
                (df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')) & 
                (df['DIAS_RESTANTES'] > 0)
            ])

        # Gestión de Demanda
        top_prof_orig = df['PROFESION'].value_counts().head(3).to_dict()
        reasig_pendientes = len(df[(df['CAMBIO_DE_HORA'] == 'SI') & (df['ESTADO_REA'] == '')])
        errores_notif = len(df[df['ESTADO'].str.contains('ERROR', na=False)])
        
        # Recurrencia
        ruts_unicos = df['RUT'].nunique() if 'RUT' in df.columns else 0
        recurrencia = total_pacientes - ruts_unicos

        # --- CÁLCULO DE VARIABLES COMPLEJAS ---
        top_motivos = df['MOTIVO_CONSULTA'].value_counts().head(4).to_dict() if 'MOTIVO_CONSULTA' in df.columns else 'Sin Info'
        
        hora_peak = 'N/A'
        if 'HORA_AGENDADA' in df.columns and not df.empty:
            try: hora_peak = str(df['HORA_AGENDADA'].mode()[0])
            except: pass
            
        dia_critico = 'N/A'
        if 'FECHA_AGENDADA' in df.columns and not df.empty:
            try: dia_critico = str(df['FECHA_AGENDADA'].mode()[0])
            except: pass

        cnt_reagendamientos = len(df[df['CAMBIO_DE_HORA']=='SI']) if 'CAMBIO_DE_HORA' in df.columns else 0

        # === NUEVO BLOQUE: CÁLCULO DE POLICONSULTANTES (CRÍTICO PARA TU PROMPT) ===
        cnt_policonsultantes = 0
        detalle_policonsultantes = "Sin casos complejos detectados"
        
        try:
            if 'RUT' in df.columns and 'MOTIVO_CONSULTA' in df.columns:
                # Copia temporal para no afectar el DF principal
                df_temp = df.copy()
                df_temp['MOTIVO_NORM_IA'] = df_temp['MOTIVO_CONSULTA'].astype(str).str.strip().str.upper()
                
                # Agrupar por RUT y contar motivos únicos
                poli_stats = df_temp.groupby('RUT')['MOTIVO_NORM_IA'].nunique()
                
                # Filtrar quienes tienen 2 o más motivos distintos
                polis_reales = poli_stats[poli_stats >= 2]
                cnt_policonsultantes = len(polis_reales)
                
                # Generar el resumen de texto para la IA
                if cnt_policonsultantes > 0:
                    ejemplos = []
                    # Tomamos solo los primeros 3 para no saturar a la IA
                    for rut_val in polis_reales.index[:3]:
                        mots = df_temp[df_temp['RUT'] == rut_val]['MOTIVO_NORM_IA'].unique()
                        mots_str = ", ".join(mots[:2]) # Max 2 motivos por ejemplo
                        ejemplos.append(f"(RUT {rut_val}: {mots_str})")
                    
                    detalle_policonsultantes = " | ".join(ejemplos)
                    if cnt_policonsultantes > 3:
                        detalle_policonsultantes += f" y {cnt_policonsultantes - 3} casos más."
        except Exception as e:
            print(f"Error calculando polis para IA: {e}")
            pass
        # =========================================================================

        # --- 2. CARGA Y LIMPIEZA DEL PROMPT ---
        prompt_template = APP_CONFIG['templates'].get('PROMPT', '').strip()

        if not prompt_template:
            prompt_template = "Analiza los datos: Confirmados {confirmados}, Tasa {tasa_conf}%."

        # Reemplazos de seguridad por si quedaron fórmulas viejas en el Excel
        prompt_final = prompt_template
        prompt_final = prompt_final.replace("{df['MOTIVO_CONSULTA'].value_counts().head(4).to_dict() if 'MOTIVO_CONSULTA' in df.columns else 'Datos no disponibles'}", "{top_motivos}")
        prompt_final = prompt_final.replace("{df['HORA_AGENDADA'].mode()[0] if 'HORA_AGENDADA' in df.columns and not df.empty else 'N/A'}", "{hora_peak}")
        prompt_final = prompt_final.replace("{df['FECHA_AGENDADA'].mode()[0] if 'FECHA_AGENDADA' in df.columns and not df.empty else 'N/A'}", "{dia_critico}")
        prompt_final = prompt_final.replace("{len(df[df['CAMBIO_DE_HORA']=='SI']) if 'CAMBIO_DE_HORA' in df.columns else 0}", "{cnt_reagendamientos}")
        prompt_final = prompt_final.replace("{round((pendientes_respuesta/total_pacientes)*100, 1) if total_pacientes > 0 else 0}", "{tasa_incertidumbre}")

        # Diccionario con TODOS los datos calculados
        datos_para_prompt = {
            "fecha_hoy": fecha_hoy,
            "avg_edad": avg_edad,
            "pacientes_adulto_mayor": pacientes_adulto_mayor,
            "dist_genero": dist_genero,
            "dist_sector": dist_sector,
            "no_inscritos_cnt": no_inscritos_cnt,
            "total_pacientes": total_pacientes,
            "tasa_conf": tasa_conf,
            "confirmados": confirmados,
            "cancelados": cancelados,
            "errores_notif": errores_notif,
            "top_prof_orig": top_prof_orig,
            "cupos_recuperables": cupos_recuperables,
            "reasig_pendientes": reasig_pendientes,
            "pendientes_respuesta": pendientes_respuesta,
            "recurrencia": recurrencia,
            # Variables Limpias
            "top_motivos": top_motivos,
            "hora_peak": hora_peak,
            "dia_critico": dia_critico,
            "cnt_reagendamientos": cnt_reagendamientos,
            "tasa_incertidumbre": tasa_incertidumbre,
            # === NUEVAS VARIABLES AGREGADAS PARA CORREGIR EL ERROR ===
            "cnt_policonsultantes": cnt_policonsultantes,
            "detalle_policonsultantes": detalle_policonsultantes
        }

        # --- 4. INYECCIÓN ---
        try:
            prompt_listo = prompt_final.format(**datos_para_prompt)
        except KeyError as e:
            return f"⚠️ Error en tu Prompt de Sheets: Variable no reconocida {e}. Revisa las llaves."
        except Exception as e:
            return f"⚠️ Error formateando: {str(e)}"

        # --- 5. LLAMADA A LA IA ---
        completion = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt_listo}],
            temperature=0.3,
            max_tokens=1500
        )
        
        content = completion.choices[0].message.content
        content_clean = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        return content_clean

    except Exception as e:
        return f"⚠️ Error crítico IA: {str(e)}"

# === MODIFICADA: VERSIÓN HUMANIZADA (ANTI-BAN) ===
def enviar_mensaje_wsp(driver, numero, mensaje):
    wait = WebDriverWait(driver, 20) # Aumentamos tiempo de espera
    action = ActionChains(driver)
    
    # Pausa inicial aleatoria (simula preparación)
    time.sleep(random.uniform(1.0, 2.5))

    try: action.send_keys(Keys.ESCAPE).perform(); time.sleep(0.5)
    except: pass

    try:
        # 1. Buscar botón de nuevo chat
        try: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-icon="new-chat-outline"]')))
        except: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="Nuevo chat"]')))
        btn.click()
        
        # Pausa humana antes de escribir
        time.sleep(random.uniform(0.8, 2.0))

        # 2. Escribir número dígito por dígito (Human Typing)
        input_drawer = driver.switch_to.active_element
        num_clean = str(numero).replace("+", "").replace(" ", "").strip()
        num_fmt = f"+56{num_clean}" if len(num_clean) == 9 else f"+{num_clean}"
        
        for digito in num_fmt:
            input_drawer.send_keys(digito)
            # Micro-pausa entre teclas (0.05 a 0.2 segundos)
            time.sleep(random.uniform(0.05, 0.2))
        
        # Pausa para que WhatsApp busque el contacto
        time.sleep(random.uniform(1.5, 3.0)) 
        input_drawer.send_keys(Keys.ENTER)
        
        # 3. Esperar carga del chat (variable)
        time.sleep(random.uniform(2.5, 5.0))

        try: 
            msg_box = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, '#main footer div[contenteditable="true"]')))
        except TimeoutException:
            # Lógica de escape si no existe
            action.send_keys(Keys.ESCAPE).perform()
            time.sleep(0.5)
            action.send_keys(Keys.ESCAPE).perform()
            time.sleep(1.0)
            return False, "Número Inválido / No tiene WhatsApp"

        # 4. Pegar mensaje simulando revisión
        msg_box.click()
        time.sleep(random.uniform(0.5, 1.0))
        
        pyperclip.copy(mensaje)
        msg_box.send_keys(Keys.CONTROL, "v")
        
        # Pausa CRÍTICA: El humano "lee" lo que pegó antes de enviar
        time.sleep(random.uniform(1.5, 3.5))
        
        msg_box.send_keys(Keys.ENTER)
        
        # Pausa final post-envío
        time.sleep(random.uniform(1.0, 2.0))
        
        return True, "Enviado OK"
    except Exception as e:
        try: action.send_keys(Keys.ESCAPE).perform()
        except: pass
        return False, f"Error: {str(e)}"

# === FUNCIÓN DE MENSAJES DINÁMICOS ===
def get_template(row, tipo):
    # Convertimos la fila a diccionario para usar .format(**row)
    # Aseguramos que todos los valores sean string para evitar errores
    data_row = {k: str(v) for k, v in row.to_dict().items()}
    
    if tipo == "REAGENDAMIENTO":
        custom_msg = CUSTOM_TEMPLATES.get('MSG_REAGEND', '')
        # Si hay mensaje personalizado en el Excel, lo usamos
        if custom_msg and len(custom_msg) > 10:
            try:
                return custom_msg.format(**data_row)
            except:
                pass # Si falla la inyección de variables, pasa al default
        
        # DEFAULT
        return f"""🚨 *REAGENDAMIENTO DE HORA - CESFAM CHOLCHOL* 🚨
Estimado/a {data_row.get('NOMBRE_PACIENTE', '')}:
Por motivos de fuerza mayor, es necesario reprogramar su hora médica. 
Lamentamos cualquier inconveniente que esto pueda causarle y agradecemos su comprensión.

📅 Nueva fecha: {data_row.get('NUEVA_FECHA', '')}
⏰ Nueva hora: {data_row.get('HORA_NUEVA_FECHA', '')}
👨‍⚕️ Profesional asignado: {data_row.get('NOM_PROF_REASIG', '')}
📋 Motivo de la consulta: {data_row.get('MOTIVO_CONSULTA_REA', '')}

📍 Lugar: CESFAM Cholchol
✉️ Necesitas cancelar o confirmar tu hora, contáctanos a: cholcholsome@gmail.com

Atentamente,
Equipo CESFAM Cholchol

🤖 Este es un mensaje automático. Si necesitas asistencia personalizada, por favor visita nuestras dependencias."""

    elif tipo == "RECORDATORIO":
        custom_msg = CUSTOM_TEMPLATES.get('MSG_AGEND', '')
        if custom_msg and len(custom_msg) > 10:
            try:
                return custom_msg.format(**data_row)
            except:
                pass 

        # DEFAULT
        return f"""🏥 *RECORDATORIO HORA MÉDICA - CESFAM CHOLCHOL*
Estimado/a {data_row.get('NOMBRE_PACIENTE', '')}:
Le recordamos su próxima atención de salud:

📅 Fecha: {data_row.get('FECHA_AGENDADA', '')}
⏰ Hora: {data_row.get('HORA_AGENDADA', '')}
👨‍⚕️ Profesional: {data_row.get('NOMBRE_PROFESIONAL', '')}
📋 Motivo Consulta: {data_row.get('MOTIVO_CONSULTA', '')}
📍 Lugar: CESFAM Cholchol
✉️ Necesitas cancelar o confirmar tu hora, contáctanos a: cholcholsome@gmail.com

🔔 *Importante:* Llegar 20 min antes.

Atentamente,
Equipo CESFAM Cholchol

🤖 Este es un mensaje automático. Si necesitas asistencia personalizada, por favor visita nuestras dependencias.
699: 
700: 👉 *IMPORTANTE: Responde SI para confirmar tu asistencia.*"""

    return ""

def verificar_respuestas_wsp(driver, numero, keywords_si=None, keywords_no=None):
    """
    Versión Robustecida v3.1 (Con listas dinámicas)
    """
    # Si no se pasan listas, usar las globales por defecto
    if keywords_si is None: keywords_si = DEFAULT_RESPUESTAS_SI
    if keywords_no is None: keywords_no = DEFAULT_RESPUESTAS_NO

    wait = WebDriverWait(driver, 15) 
    action = ActionChains(driver)
    
    try: action.send_keys(Keys.ESCAPE).perform(); time.sleep(0.5)
    except: pass

    try:
        # 1. Buscar y abrir chat
        try: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'span[data-icon="new-chat-outline"]')))
        except: btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, 'div[title="Nuevo chat"]')))
        btn.click()
        time.sleep(1.0)

        input_drawer = driver.switch_to.active_element
        num_clean = str(numero).replace("+", "").replace(" ", "").strip()
        num_fmt = f"+56{num_clean}" if len(num_clean) == 9 else f"+{num_clean}"
        input_drawer.send_keys(num_fmt)
        time.sleep(2.0)
        input_drawer.send_keys(Keys.ENTER)
        
        # Esperar a que cargue el historial del chat
        time.sleep(3.0) 

        # 2. Lógica de Lectura Inteligente
        try:
            # Buscamos TODOS los contenedores de mensajes (filas)
            rows = driver.find_elements(By.CSS_SELECTOR, 'div[role="row"]')
            
            if not rows:
                return "ERROR", "Chat vacío"

            # Tomamos el ÚLTIMO mensaje (el más reciente)
            last_row = rows[-1]
            
            # --- DETECTAR DIRECCIÓN (ENTRANTE VS SALIENTE) ---
            es_mensaje_mio = False
            try:
                # Buscamos cualquier icono de confirmación de lectura
                last_row.find_element(By.CSS_SELECTOR, 'span[data-icon*="msg-"]')
                es_mensaje_mio = True
            except:
                es_mensaje_mio = False # Si no tiene ticks, es un mensaje recibido

            if es_mensaje_mio:
                return "PENDIENTE", "El último mensaje es tuyo"

            # --- EXTRAER TEXTO ---
            try:
                text_element = last_row.find_element(By.CSS_SELECTOR, "span.selectable-text")
                mensaje_texto = text_element.text.strip()
            except:
                # Fallback
                mensaje_texto = last_row.text.strip()

            msg_clean = mensaje_texto.lower()

            # --- LÓGICA DE CLASIFICACIÓN ROBUSTA (Primero NO, luego SI) ---
            
            # 1. Chequeo de Negación/Cancelación (Prioridad Alta)
            for frase in keywords_no:
                frase_clean = frase.lower()
                prefix = r'\b' if re.match(r'^\w', frase_clean) else r''
                suffix = r'\b' if re.search(r'\w$', frase_clean) else r''
                pattern = prefix + re.escape(frase_clean) + suffix
                if re.search(pattern, msg_clean):
                    return "NO ASISTIRA", f"{mensaje_texto} (Match: {frase})"

            # 2. Chequeo de Confirmación
            for frase in keywords_si:
                frase_clean = frase.lower()
                prefix = r'\b' if re.match(r'^\w', frase_clean) else r''
                suffix = r'\b' if re.search(r'\w$', frase_clean) else r''
                pattern = prefix + re.escape(frase_clean) + suffix
                if re.search(pattern, msg_clean):
                    return "CONFIRMADO", f"{mensaje_texto} (Match: {frase})"

            # 3. Respuesta no clasificada
            return "AMBIGUO", f"No clasificado: {mensaje_texto}"

        except Exception as e:
            return "ERROR", f"Error analizando chat: {str(e)}"

    except Exception as e:
        try: action.send_keys(Keys.ESCAPE).perform()
        except: pass
        return "ERROR", f"Error general: {str(e)}"

# === CLASE AVANZADA PARA GENERAR PDF (DISEÑO INSTITUCIONAL ALTO CONTRASTE) ===
class PDFReport(FPDF):
    def __init__(self, logo_alain_data, logo_noti_data):
        super().__init__()
        self.logo_alain_data = logo_alain_data
        self.logo_noti_data = logo_noti_data
    
    def header(self):
        # FONDO BLANCO EN CABECERA PARA MAXIMO CONTRASTE CON LOGOS
        self.set_fill_color(255, 255, 255) 
        self.rect(0, 0, 210, 40, 'F')
        
        # Logos (Guardar temporalmente si son bytes)
        if self.logo_noti_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_noti_data)
                logo_path = f.name
            try: self.image(logo_path, 10, 5, 25)
            except: pass
            
        if self.logo_alain_data:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as f:
                f.write(self.logo_alain_data)
                logo_path_2 = f.name
            try: self.image(logo_path_2, 175, 5, 25)
            except: pass

        # Títulos alineados
        self.set_y(10)
        self.set_font('Arial', 'B', 18)
        self.set_text_color(0, 109, 182) # Azul Medio (#006DB6)
        self.cell(0, 8, 'CESFAM CHOLCHOL', 0, 1, 'C')
        
        self.set_font('Arial', '', 12)
        self.set_text_color(15, 37, 87) # Azul Marino (#0F2557)
        self.cell(0, 6, 'REPORTE EJECUTIVO DE GESTIÓN CLÍNICA', 0, 1, 'C')
        
        # Fecha en Español manual
        hoy = datetime.now()
        fecha_str = f"{hoy.day} de {MESES_ES[hoy.month]} del {hoy.year} - {hoy.strftime('%H:%M')}"
        
        self.set_font('Arial', 'I', 9)
        self.set_text_color(100, 100, 100)
        self.cell(0, 5, f'Fecha de Emisión: {fecha_str}', 0, 1, 'C')
        
        # Línea divisoria decorativa
        self.set_draw_color(136, 197, 67) # Verde Lima (#88C543)
        self.set_line_width(0.8)
        self.line(10, 38, 200, 38)
        self.ln(15)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f'Elaborado por el desarrollador: Alain Antinao Sepúlveda | Página {self.page_no()}', 0, 0, 'C')

    def chapter_title(self, label):
        self.set_font('Arial', 'B', 14)
        # Azul Marino Institucional (#0F2557)
        self.set_text_color(15, 37, 87)
        self.cell(0, 10, label, 0, 1, 'L')
        self.set_draw_color(0, 109, 182) # Línea Azul
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(5)

    def kpi_table_row(self, label, value, is_header=False):
        self.set_font('Arial', 'B' if is_header else '', 10)
        self.set_text_color(50, 50, 50)
        fill = 1 if is_header else 0
        if is_header:
             self.set_fill_color(240, 245, 250) # Gris azulado
             self.set_text_color(15, 37, 87)
        else:
             self.set_text_color(50, 50, 50)
             
        self.cell(100, 8, label, 1, 0, 'L', fill)
        self.cell(90, 8, str(value), 1, 1, 'C', fill)
        self.ln()

def generate_pdf_report(df, stats, ai_analysis, logos):
    pdf = PDFReport(logos['LOGO_ALAIN'], logos['LOGO_NOTI'])
    pdf.alias_nb_pages()
    pdf.add_page()
    
    # 1. Resumen Mensual Actual
    pdf.chapter_title("1. Rendimiento Mes Actual")
    pdf.kpi_table_row("Total Pacientes (Mes)", str(stats['total_mes']), True)
    pdf.kpi_table_row("Confirmados (Mes)", str(stats['confirmados_mes']))
    pdf.kpi_table_row("Tasa Confirmación (Mes)", f"{stats['tasa_mes']}%")
    pdf.ln(5)

    # 2. Resumen Global Histórico
    pdf.chapter_title("2. Totales Históricos (Global)")
    pdf.kpi_table_row("Total Pacientes (Histórico)", str(stats['total_global']), True)
    pdf.kpi_table_row("Confirmados (Global)", str(stats['confirmados_global']))
    pdf.kpi_table_row("Cancelados (Global)", str(stats['rechazados_global']))
    pdf.kpi_table_row("Tasa Eficiencia Global", f"{stats['tasa_global']}%")
    pdf.ln(5)

    # 3. Gestión de Disponibilidad
    pdf.chapter_title("3. Gestion de Cupos y Disponibilidad")
    
    # Configuración de fuente para texto normal
    pdf.set_font('Arial', '', 10)
    
    if stats['disponibles'] > 0:
        pdf.set_text_color(0, 100, 0) # Verde oscuro
        pdf.set_font('Arial', 'B', 10)
        texto_cupos = f"ALERTA DE OPORTUNIDAD: Se han detectado {stats['disponibles']} cupos disponibles (pacientes que no asistiran) para fechas futuras. Se recomienda activar lista de espera."
        # Decodificación segura para tildes básicas
        pdf.set_x(10)
        pdf.multi_cell(190, 6, texto_cupos.encode('latin-1', 'replace').decode('latin-1'))
        pdf.set_text_color(0,0,0)
    else:
        pdf.set_font('Arial', '', 10)
        texto_cupos = "No hay cupos liberados para fechas futuras en este momento. La agenda se mantiene sin cancelaciones anticipadas."
        pdf.set_x(10)
        pdf.multi_cell(190, 6, texto_cupos.encode('latin-1', 'replace').decode('latin-1'))
    pdf.ln(5)
    
    # 4. Alerta Percapita
    pdf.chapter_title("4. Alerta de Financiamiento (Percapita)")
    if 'no_inscritos' in stats and stats['no_inscritos'] > 0:
        pdf.set_text_color(180, 0, 0) # Rojo
        pdf.set_font('Arial', 'B', 10)
        texto_alerta = f"ALERTA FINANCIERA: Se detectaron {stats['no_inscritos']} pacientes atendidos que figuran como 'PENDIENTE INSCRIPCION' en el ultimo corte percapita disponible."
        pdf.set_x(10)
        pdf.multi_cell(190, 6, texto_alerta.encode('latin-1', 'replace').decode('latin-1'))
        pdf.set_text_color(0,0,0)
    else:
        pdf.set_x(10)
        pdf.multi_cell(190, 6, "Todos los pacientes verificados parecen estar inscritos correctamente en el percapita base.".encode('latin-1', 'replace').decode('latin-1'))
    pdf.ln(5)
    
    pdf.set_font('Arial', 'B', 10)
    pdf.cell(0, 8, "Cola de Envio Pendiente:".encode('latin-1', 'replace').decode('latin-1'), 0, 1)
    pdf.set_font('Arial', '', 10)
    texto_cola = f"Existen {stats['cola_activa']} mensajes listos para ser enviados."
    pdf.set_x(10)
    pdf.multi_cell(190, 6, texto_cola.encode('latin-1', 'replace').decode('latin-1'))
    pdf.ln(5)

    # 5. Análisis IA
    pdf.add_page()
    pdf.chapter_title("5. Analisis Estrategico Inteligente")
    pdf.set_font('Arial', 'I', 9)
    pdf.cell(0, 6, "Analisis generado en base a datos en tiempo real.", 0, 1)
    pdf.ln(5)
    
    pdf.set_font('Arial', '', 11) # Fuente un poco más grande para el reporte
    if ai_analysis:
        # 1. Limpieza de Markdown que ensucia el PDF
        clean_text = ai_analysis.replace('**', '').replace('###', '').replace('####', '')
        
        # 2. Diccionario de reemplazo manual para asegurar caracteres españoles en PDF standard
        replacements = {
            'ñ': chr(241), 'Ñ': chr(209),
            'á': chr(225), 'é': chr(233), 'í': chr(237), 'ó': chr(243), 'ú': chr(250),
            'Á': chr(193), 'É': chr(201), 'Í': chr(205), 'Ó': chr(211), 'Ú': chr(218),
            '“': '"', '”': '"', '–': '-'
        }
        
        for char, replacement in replacements.items():
            clean_text = clean_text.replace(char, replacement)

        # NUEVO: limpiar tabulaciones y retornos que rompen fpdf2
        clean_text = clean_text.replace('\t', '    ').replace('\r', '')

        # 3. Imprimir línea por línea para controlar espaciado
        for line in clean_text.split('\n'):
            # CORRECCIÓN: Romper palabras o separadores muy largos para evitar FPDFException
            safe_words = []
            for word in line.split(' '):
                if len(word) > 40:
                    safe_words.extend([word[i:i+40] for i in range(0, len(word), 40)])
                else:
                    safe_words.append(word)
            line = ' '.join(safe_words)
            
            # Si la línea es un título (detectado por ser corta y mayúsculas o empezar con número)
            pdf.set_x(10)
            if len(line) < 50 and (line.isupper() or line.strip().startswith(('1.', '2.', '3.'))):
                pdf.ln(3)
                pdf.set_font('Arial', 'B', 11)
                pdf.set_x(10)
                pdf.multi_cell(190, 6, line.encode('latin-1', 'replace').decode('latin-1'))
                pdf.set_font('Arial', '', 11)
            else:
                pdf.multi_cell(190, 6, line.encode('latin-1', 'replace').decode('latin-1'))
    else:
        pdf.set_x(10)
        pdf.multi_cell(190, 6, "No se pudo generar el analisis detallado en este momento.")

    # Output
    out = pdf.output() if hasattr(pdf, 'fpdf_version') else pdf.output(dest='S')
    if isinstance(out, (bytes, bytearray)):
        return bytes(out)
    return out.encode('latin-1')

# -----------------------------------------------------------------------------
# 3. INTERFAZ DE USUARIO (FRONTEND) Y LOGIN
# -----------------------------------------------------------------------------

# Configuración de página Streamlit (Debe ser lo primero de UI)
try:
    st.set_page_config(
        page_title="Medtify | Clinical Data Platform",
        page_icon="🏥", 
        layout="wide",
        initial_sidebar_state="expanded"
    )
except: pass

if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'account_id' not in st.session_state:
    st.session_state.account_id = None

if not st.session_state.logged_in:
    # --- PANTALLA DE LOGIN PREMIUM ---
    st.markdown("""
    <style>
        /* Fondo animado y elegante para toda la app durante el login */
        div[data-testid="stAppViewContainer"] {
            background: linear-gradient(-45deg, #0F2557, #006DB6, #0A193D, #004d80);
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
            background: linear-gradient(135deg, #006DB6 0%, #0F2557 100%) !important;
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

    # Columnas para centrar el card (Responsive)
    c1, c2, c3 = st.columns([1, 1.5, 1])
    
    with c2:
        # st.form envuelve nativamente todos los widgets que contenga
        with st.form("login_form", clear_on_submit=False):
            
            # Centrar Logo usando columnas internas del form
            col_l, col_img, col_r = st.columns([1, 1.5, 1])
            with col_img:
                import sys, os
                def resolve_path(path):
                    if getattr(sys, 'frozen', False):
                        return os.path.join(sys._MEIPASS, path)
                    return os.path.join(os.path.dirname(__file__), path)
                
                logo_path = resolve_path("logo_noti.png")
                if os.path.exists(logo_path):
                    st.image(logo_path, use_container_width=True)
                else:
                    st.markdown('<div style="font-size: 50px; text-align: center;">🏥</div>', unsafe_allow_html=True)
            
            st.markdown('<div class="login-title">Medtify</div>', unsafe_allow_html=True)
            st.markdown('<div class="login-subtitle">Plataforma de Inteligencia Clínica</div>', unsafe_allow_html=True)
            
            cuenta_input = st.text_input("Usuario", placeholder="Ingrese su cuenta")
            clave_input = st.text_input("Contraseña", type="password", placeholder="Clave de plataforma")
            
            submitted = st.form_submit_button("Ingresar al Sistema")
            
            if submitted:
                if cuenta_input and clave_input:
                    with st.spinner("Autenticando..."):
                        temp_config = load_app_configuration(cuenta_input)
                        if temp_config['valido']:
                            clave_real = temp_config['datos'].get('CLAVE_PLATAFORMA', '')
                            if str(clave_real) == str(clave_input):
                                st.session_state.logged_in = True
                                st.session_state.account_id = cuenta_input
                                st.rerun()
                            else:
                                st.error("❌ Credenciales incorrectas. Verifique su clave.")
                        else:
                            st.error(f"❌ {temp_config['mensaje']}")
                else:
                    st.warning("⚠️ Por favor, ingrese usuario y clave.")
    st.stop()

# === SI ESTÁ LOGUEADO, CARGAR CONFIGURACIÓN ===
MASTER_ACCOUNT_ID = st.session_state.account_id
APP_CONFIG = load_app_configuration(MASTER_ACCOUNT_ID)

# === VERIFICACIÓN INICIAL DE LICENCIA ===
# Corrección: Leemos directamente desde la configuración global
status = APP_CONFIG['licencia'] 

# === VALIDACIÓN DE ESTADO DE CARGA ===
if not APP_CONFIG['valido']:
    st.error(f"⛔ ERROR DE INICIO: {APP_CONFIG['mensaje']}")
    st.session_state.logged_in = False
    st.stop()

# === VARIABLES GLOBALES ===
DYNAMIC_CREDS = APP_CONFIG['credenciales_finales']
GROQ_API_KEY = APP_CONFIG['datos']['GROQ_API_KEY']
URL_SHEET = APP_CONFIG['datos']['URL_SHEET']
ROW_INDEX_ADMIN = APP_CONFIG['row_index']
CUSTOM_TEMPLATES = APP_CONFIG['templates']
AI_MODEL = "llama-3.3-70b-versatile"
# IMÁGENES (Puede ser Bytes o URL String)
IMG_LOGO_NOTI = APP_CONFIG['imagenes']['LOGO_NOTI']
IMG_LOGO_ALAIN = APP_CONFIG['imagenes']['LOGO_ALAIN']

# Sincronizar session_state
if 'ai_usage' not in st.session_state:
    st.session_state.ai_usage = APP_CONFIG['uso_ia_actual']

if 'ultimo_reporte_ia' not in st.session_state:
    st.session_state.ultimo_reporte_ia = None

# --- CSS PROFESIONAL (PALETA INSTITUCIONAL APLICADA) ---
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    :root {
        --primary-blue: #006DB6;  /* Azul Medio Institucional */
        --navy-blue: #0F2557;     /* Azul Marino Institucional */
        --success-green: #88C543; /* Verde Lima Institucional */
        --text-dark: #0F2557;     /* Texto principal en Azul Marino */
        --text-gray: #8898AA;
        --bg-light: #F5F7FB;
        --white: #FFFFFF;
        --card-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
    }

    html, body, [class*="css"] {
        font-family: 'Inter', sans-serif;
        background-color: var(--bg-light);
        color: var(--text-dark);
    }

    section[data-testid="stSidebar"] {
        background-color: var(--white);
        border-right: 1px solid #E0E6ED;
    }

    .header-container {
        background: var(--white);
        padding: 2rem;
        border-radius: 16px;
        box-shadow: var(--card-shadow);
        margin-bottom: 24px;
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-left: 6px solid var(--primary-blue);
    }
    .header-title { font-size: 1.75rem; font-weight: 700; margin: 0; color: var(--text-dark); }
    .header-subtitle { font-size: 0.95rem; color: var(--text-gray); margin-top: 4px; }
    .date-badge { background-color: #F0F2F5; color: var(--primary-blue); padding: 8px 16px; border-radius: 50px; font-weight: 600; font-size: 0.85rem; border: 1px solid #E0E6ED; }

    .metric-container {
        background: var(--white);
        padding: 1.5rem;
        border-radius: 16px;
        box-shadow: var(--card-shadow);
        height: 100%;
        position: relative;
        overflow: hidden;
        transition: transform 0.2s ease;
    }
    .metric-container:hover { transform: translateY(-3px); }
    .metric-label { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 1px; color: var(--text-gray); font-weight: 600; margin-bottom: 8px; }
    .metric-value { font-size: 2.2rem; font-weight: 700; color: var(--text-dark); }
    .metric-icon { position: absolute; top: 1.5rem; right: 1.5rem; font-size: 1.5rem; opacity: 0.2; }
    
    .color-green { color: var(--success-green); }
    .color-orange { color: #FF9F43; }
    .color-blue { color: var(--primary-blue); }

    .stButton > button {
        border-radius: 8px; font-weight: 600; border: none; padding: 0.6rem 1.5rem; transition: all 0.3s ease; width: 100%;
        border: 2px solid #006DB6;
        color: #0F2557;
        background-color: white;
    }
    .stButton > button:hover {
        background-color: #F5F7FB;
        border-color: #88C543;
        color: #006DB6;
        transform: translateY(-2px);
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    /* Primary Button override (if used via type='primary') */
    button[kind="primary"] {
        background-color: #006DB6 !important;
        border-color: #006DB6 !important;
        color: white !important;
    }

    .terminal-window {
        background: var(--navy-blue); /* Fondo Azul Marino para consola */
        border-radius: 12px; padding: 0; box-shadow: var(--card-shadow);
        font-family: 'Consolas', 'Monaco', monospace; overflow: hidden; border: 1px solid var(--primary-blue);
    }
    .terminal-header { background: #0a193d; padding: 8px 16px; display: flex; gap: 6px; border-bottom: 1px solid #1c3570; }
    .terminal-dot { width: 10px; height: 10px; border-radius: 50%; }
    .dot-red { background: #FF5F56; } .dot-yellow { background: #FFBD2E; } .dot-green { background: #27C93F; }
    .terminal-body { padding: 16px; height: 350px; overflow-y: auto; color: #E0E6ED; font-size: 0.85rem; line-height: 1.5; }
    .log-success { color: var(--success-green); } .log-error { color: #FF5F56; } .log-info { color: #4FC3F7; }

    .stDataFrame { background: var(--white); border-radius: 12px; padding: 5px; box-shadow: var(--card-shadow); }
    
    /* Estilo para el reporte de IA */
    .report-container {
        background-color: #ffffff;
        padding: 30px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        margin-top: 20px;
    }
    .report-header {
        border-bottom: 2px solid var(--primary-blue);
        padding-bottom: 10px;
        margin-bottom: 20px;
        color: var(--primary-blue);
        font-weight: 700;
        font-size: 1.2rem;
    }
    
    /* Footer Adjustment */
    img { margin-bottom: 0px; } 

</style>
""", unsafe_allow_html=True)

# --- SIDEBAR ---
with st.sidebar:
    # Lógica de Logo Dinámico
    if IMG_LOGO_NOTI:
        st.image(IMG_LOGO_NOTI, use_container_width=True)
    else:
        st.markdown("<h2 style='color:#006DB6;text-align:center;'>Medtify</h2>", unsafe_allow_html=True)
    
    st.markdown("### Navegación")
    menu_option = st.radio(
        "Menú",
        ["Dashboard Analytics", "Gestión de Horas", "Nuevo Ingreso", "Centro de Notificaciones", "Base de Pacientes"],
        index=0,
        label_visibility="collapsed"
    )
    
    st.markdown("---")
    
    # === MOSTRAR ESTADO DE LA CUENTA ===
    if status['activo']:
        st.success(f"✅ Cuenta Activa: {MASTER_ACCOUNT_ID}")
        
        limite_diario = status['limite']
        uso_actual = st.session_state.ai_usage
        
        if status['plan'] == 'PRO':
            st.markdown(f"🌟 **Plan PRO** ({limite_diario} Consultas)")
        else:
            st.markdown(f"🌱 **Plan GRATIS** ({limite_diario} Consultas)")
        
        st.progress(min(uso_actual / limite_diario, 1.0))
        st.caption(f"Uso IA Hoy: {uso_actual}/{limite_diario}")
        
        if uso_actual >= limite_diario:
            st.warning("⚠️ Límite diario alcanzado")
            
    else:
        st.error("⛔ Cuenta Suspendida o No Encontrada")
        st.stop() # DETIENE LA EJECUCIÓN SI NO TIENE LICENCIA ACTIVA
    
    st.markdown(f"**Estado Sistema:**")
    st.markdown("🟢 Conectado a Sheets")

# --- CARGA DE DATOS (CON CACHÉ INTELIGENTE) ---
df = get_data_fresh(MASTER_ACCOUNT_ID)
if df is None:
    st.error("Error crítico: No se pudo conectar a la base de datos. Verifique los enlaces de Google Sheets en la cuenta maestra.")
    st.stop()

# -----------------------------------------------------------------------------
# VISTA 1: DASHBOARD ANALYTICS (ACTUALIZADO CON GESTIÓN DE DISPONIBILIDAD)
# -----------------------------------------------------------------------------
if menu_option == "Dashboard Analytics":
    # HEADER
    hoy_header = datetime.now()
    fecha_header_esp = f"{hoy_header.day} de {MESES_ES[hoy_header.month]} de {hoy_header.year}"
    
    st.markdown(f"""
    <div class="header-container">
        <div>
            <h1 class="header-title">📊 Inteligencia Clínica</h1>
            <p class="header-subtitle">Análisis Estadístico y Gestión de Disponibilidad | CESFAM Cholchol</p>
        </div>
        <div class="date-badge">
            📅 {fecha_header_esp}
        </div>
    </div>
    """, unsafe_allow_html=True)

    # --- 1. CÁLCULOS DE MÉTRICAS (GLOBAL VS MES ACTUAL) ---
    
    # Globales
    total_global = len(df)
    confirmados_global = len(df[df['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
    rechazados_global = len(df[df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')])
    notificados_global = len(df[df['ESTADO'].str.contains('OK') | df['ESTADO_REA'].str.contains('OK')])
    tasa_global = int((confirmados_global / notificados_global) * 100) if notificados_global > 0 else 0
    
    # Mensuales (Mes Actual)
    if 'FECHA_DT' in df.columns:
        mes_actual = datetime.now().month
        anio_actual = datetime.now().year
        df_mes = df[(df['FECHA_DT'].dt.month == mes_actual) & (df['FECHA_DT'].dt.year == anio_actual)]
        
        total_mes = len(df_mes)
        confirmados_mes = len(df_mes[df_mes['STATUS_CONFIRMACION'].str.contains('CONFIRMADO')])
        rechazados_mes = len(df_mes[df_mes['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')])
        notificados_mes = len(df_mes[df_mes['ESTADO'].str.contains('OK') | df_mes['ESTADO_REA'].str.contains('OK')])
        tasa_mes = int((confirmados_mes / notificados_mes) * 100) if notificados_mes > 0 else 0
    else:
        total_mes = 0; confirmados_mes = 0; rechazados_mes = 0; tasa_mes = 0

    # --- 2. CÁLCULO DE "HORAS DISPONIBLES" (Lógica del Usuario) ---
    # Criterio: Status es 'NO ASISTIRA' Y la fecha es FUTURA (días > 0)
    # Excluye citas de hoy (0) o pasadas (<0)
    if 'DIAS_RESTANTES' in df.columns:
        horas_disponibles_df = df[
            (df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA')) & 
            (df['DIAS_RESTANTES'] > 0)
        ]
        total_horas_disponibles = len(horas_disponibles_df)
    else:
        total_horas_disponibles = 0

    # Reagendamientos Pendientes (Gestión administrativa)
    reagendamientos_pendientes = len(df[(df['CAMBIO_DE_HORA'] == 'SI') & (df['ESTADO_REA'] == '')])

    # Recurrencia (Total - Unique RUTs)
    ruts_unicos = df['RUT'].nunique() if 'RUT' in df.columns else 0
    recurrentes = len(df) - ruts_unicos

    # --- 3. PANELES DE KPI ---
    
    # BOTÓN EXPORTAR PDF (Ligado a Créditos IA)
    # LÓGICA: AL PRESIONAR EL BOTÓN, PRIMERO EJECUTA LA IA Y LUEGO GENERA EL PDF
    if st.button("📄 Exportar Reporte Ejecutivo (PDF)"):
        if st.session_state.ai_usage >= status['limite']:
            st.error("🚫 Límite de créditos alcanzado. No se puede generar el análisis IA para el reporte.")
        else:
            with st.spinner("📊 Analizando los datos en tiempo real..."):
                # 1. Ejecutar Análisis IA (Descuenta crédito)
                ai_result = generar_analisis_clinico(df)
                
                # 2. Guardar en sesión (para que no se pierda al recargar)
                st.session_state.ultimo_reporte_ia = ai_result
                
                # 3. Descontar Crédito y Guardar en Nube
                nuevo_contador = st.session_state.ai_usage + 1
                st.session_state.ai_usage = nuevo_contador
                registrar_consumo_ia(ROW_INDEX_ADMIN, nuevo_contador)
            
            with st.spinner("📄 Maquetando Reporte PDF Institucional..."):
                # Calc no inscritos
                no_inscritos_pdf = 0
                if 'ESTADO_PERCAPITA' in df.columns:
                    no_inscritos_pdf = len(df[df['ESTADO_PERCAPITA'] == "PENDIENTE INSCRIPCION"])

                # 4. Preparar estadísticas para el PDF
                stats_export = { 
                    'total_global': total_global, 
                    'confirmados_global': confirmados_global, 
                    'rechazados_global': rechazados_global, 
                    'tasa_global': tasa_global,
                    'total_mes': total_mes,
                    'confirmados_mes': confirmados_mes,
                    'tasa_mes': tasa_mes,
                    'disponibles': total_horas_disponibles,
                    'no_inscritos': no_inscritos_pdf, # KPI Nuevo
                    'cola_activa': len(df[(df['ESTADO'] == '') & (df['DIAS_RESTANTES'] >= 1) & (df['DIAS_RESTANTES'] <= 2)]) if 'DIAS_RESTANTES' in df.columns else 0
                }
                
                # 5. Generar PDF usando la clase PDFReport personalizada
                pdf_bytes = generate_pdf_report(df, stats_export, ai_result, APP_CONFIG['imagenes'])
                
                st.download_button(
                    label="⬇️ Descargar Reporte PDF Final", 
                    data=pdf_bytes, 
                    file_name=f"Reporte_Ejecutivo_{datetime.now().strftime('%Y%m%d')}.pdf", 
                    mime='application/pdf'
                )
                st.success("✅ Reporte generado y crédito descontado exitosamente.")
    
    # BLOQUE DE DISPONIBILIDAD (NUEVO DESTACADO)
    if total_horas_disponibles > 0:
        st.markdown("""
        <div style="background-color: #d4edda; border-left: 5px solid #88C543; padding: 15px; border-radius: 5px; margin-bottom: 20px;">
            <h4 style="color: #155724; margin:0;">✅ Oportunidad de Gestión</h4>
            <p style="color: #155724; margin:0;">Se han detectado cupos liberados para días futuros.</p>
        </div>
        """, unsafe_allow_html=True)

    # --- MÉTRICAS SEPARADAS POR MES E HISTÓRICO ---
    st.markdown(f"#### 📅 Mes en Curso: {MESES_ES[datetime.now().month]}")
    m1, m2, m3 = st.columns(3)
    
    with m1:
        st.metric(
            label="Pacientes este Mes", 
            value=total_mes, 
            delta="Agenda Mensual", 
            delta_color="off",
            border=True
        )
    with m2:
        st.metric(
            label="Confirmados este Mes", 
            value=confirmados_mes, 
            delta=f"{tasa_mes}% Tasa de Éxito",
            border=True
        )
    with m3:
        st.metric(
            label="Horas Disp. Futuras", 
            value=total_horas_disponibles, 
            delta="Cupos Recuperables", 
            delta_color="normal",
            border=True
        )

    st.write("")
    st.markdown("#### 🌍 Histórico Global")
    m4, m5, m6 = st.columns(3)
    
    with m4: 
        st.metric("Total Histórico", total_global, border=True)
    with m5: 
        st.metric("Total Confirmados", confirmados_global, f"{tasa_global}% Global", border=True)
    with m6: 
        st.metric("Reagendamientos Pendientes", reagendamientos_pendientes, "Requiere Acción", delta_color="inverse", border=True)
    
    st.write("")
    # Métricas adicionales (Fila 3)
    c1, c2 = st.columns(2)
    
    # Cola de envío (Lógica Inteligente: Si es Viernes, miramos 3 días adelante)
    dia_semana_hoy = datetime.now().weekday() # 0=Lunes, 4=Viernes
    limite_dias_envio = 3 if dia_semana_hoy == 4 else 2 # Si es viernes (4), límite es 3. Si no, 2.
    
    if 'DIAS_RESTANTES' in df.columns:
        cola_activa = len(df[
            (df['ESTADO'] == '') & 
            (df['CAMBIO_DE_HORA'] != 'SI') & 
            (df['DIAS_RESTANTES'] >= 1) & 
            (df['DIAS_RESTANTES'] <= limite_dias_envio) & # <--- AQUÍ USAMOS LA VARIABLE DINÁMICA
            (~df['STATUS_CONFIRMACION'].str.contains('NO ASISTIRA', na=False))
        ])
    else:
        cola_activa = 0

    with c1: st.metric(f"Cola de Envío (Próx. {limite_dias_envio} días)", cola_activa, "Listos para salir", border=True)
    with c2: st.metric("Pacientes Recurrentes", recurrentes, "Mismo RUT", border=True)

    st.divider()
    
    # --- SISTEMA DE PESTAÑAS (ACTUALIZADO) ---
    # Se agrega "🔍 Policonsultantes" al final
    tab1, tab2, tab_dem, tab3, tab4, tab5, tab6, tab7, tab8, tab9 = st.tabs([
        "📉 Respuesta", "📊 Demografía Edad", "🗺️ Territorio & Percápita", "🩺 Carga", "♻️ Gestión Cupos", "⏰ Temporal", "⚠️ Cambios", "🗓️ Calendario", "🧠 IA Analista", "🔍 Policonsultantes"
    ])
    
    # === TAB 1: RESPUESTA PACIENTE (Update con No Asistira) ===
    with tab1:
        c_donut, c_funnel = st.columns(2)
        
        with c_donut:
            st.markdown("##### 📢 Estado de Confirmación")
            # Preparamos datos para Donut Chart
            df_status = df['STATUS_CONFIRMACION'].value_counts().reset_index()
            df_status.columns = ['Estado', 'Cantidad']
            
            base = alt.Chart(df_status).encode(theta=alt.Theta("Cantidad", stack=True))
            pie = base.mark_arc(outerRadius=120).encode(
                color=alt.Color("Estado", scale=alt.Scale(domain=['CONFIRMADO', 'NO ASISTIRA', 'PENDIENTE', 'CONFIRMADO (R)', 'NO ASISTIRA (R)'], range=['#88C543', '#D32F2F', '#A8A8A8', '#6DA036', '#9A2323'])),
                order=alt.Order("Cantidad", sort="descending"),
                tooltip=["Estado", "Cantidad"]
            )
            text = base.mark_text(radius=140).encode(
                text="Cantidad",
                order=alt.Order("Cantidad", sort="descending"),
                color=alt.value("black") 
            )
            st.altair_chart(pie + text, use_container_width=True)

        with c_funnel:
            st.markdown("##### 📉 Embudo de Gestión")
            funnel_data = pd.DataFrame({
                'Etapa': ['1. Total Agendado', '2. Notificados', '3. Confirmados', '4. Cancelados'],
                'Cantidad': [total_global, notificados_global, confirmados_global, rechazados_global]
            })
            c_funnel_chart = alt.Chart(funnel_data).mark_bar().encode(
                x=alt.X('Cantidad', title='N° Pacientes'),
                y=alt.Y('Etapa', sort=None, title=''),
                color=alt.Color('Etapa', scale=alt.Scale(scheme='tealblues')),
                tooltip=['Etapa', 'Cantidad']
            ).properties(height=300)
            st.altair_chart(c_funnel_chart, use_container_width=True)

    # === TAB 2: DEMOGRAFÍA ===
    with tab2:
        col_edad, col_genero = st.columns(2)
        with col_edad:
            st.markdown("##### 🎂 Distribución por Edad")
            if 'EDAD_NUM' in df.columns:
                # === MODIFICACIÓN SOLICITADA: RANGOS ETARIOS PERSONALIZADOS ===
                df['Rango_Edad'] = pd.cut(
                    df['EDAD_NUM'], 
                    bins=[-1, 4, 9, 14, 19, 44, 64, 79, 150], 
                    labels=['0-4', '5-9', '10-14', '15-19', '20-44', '45-64', '65-79', '80+'],
                    right=True
                )
                df_age = df['Rango_Edad'].value_counts().sort_index().reset_index()
                df_age.columns = ['Rango', 'Cantidad']
                
                chart_age = alt.Chart(df_age).mark_bar(color='#006DB6').encode(
                    x=alt.X('Rango', title='Grupo Etario', sort=None),
                    y=alt.Y('Cantidad', title='N° Pacientes'),
                    tooltip=['Rango', 'Cantidad']
                ).properties(height=300)
                st.altair_chart(chart_age, use_container_width=True)
            else:
                st.info("Datos de edad no disponibles.")

        with col_genero:
            st.markdown("##### ⚧️ Distribución por Género")
            if 'GENERO' in df.columns:
                df_gen = df['GENERO'].value_counts().reset_index()
                df_gen.columns = ['Genero', 'Total']
                chart_gen = alt.Chart(df_gen).mark_arc(innerRadius=50).encode(
                    theta=alt.Theta(field="Total", type="quantitative"),
                    color=alt.Color(field="Genero", type="nominal", scale=alt.Scale(scheme='pastel1')),
                    tooltip=['Genero', 'Total']
                ).properties(height=300)
                st.altair_chart(chart_gen, use_container_width=True)

    # === NUEVA TAB: DEMOGRAFÍA TERRITORIAL Y PERCÁPITA ===
    with tab_dem:
        st.subheader("🗺️ Análisis Territorial y Financiero")
        col_sec, col_perca = st.columns(2)
        
        with col_sec:
            st.markdown("##### 📍 Distribución por Sector")
            if 'SECTOR' in df.columns:
                df_sec = df['SECTOR'].value_counts().reset_index()
                df_sec.columns = ['Sector', 'Pacientes']
                st.altair_chart(alt.Chart(df_sec).mark_bar(color='#2E86C1').encode(
                    x='Pacientes', y=alt.Y('Sector', sort='-x'), tooltip=['Sector', 'Pacientes']
                ).properties(height=300), use_container_width=True)
            else:
                st.info("Sin datos de sector.")

        with col_perca:
            st.markdown("##### 💰 Estado Percápita (Inscripción)")
            if 'ESTADO_PERCAPITA' in df.columns:
                df_per = df['ESTADO_PERCAPITA'].value_counts().reset_index()
                df_per.columns = ['Estado', 'Cantidad']
                
                # Gráfico Donut
                base_p = alt.Chart(df_per).encode(theta=alt.Theta("Cantidad", stack=True))
                pie_p = base_p.mark_arc(outerRadius=100).encode(
                    color=alt.Color("Estado", scale=alt.Scale(domain=['INSCRITO', 'PENDIENTE INSCRIPCION', 'Sin Datos Base'], range=['#28B463', '#CB4335', '#BDC3C7'])),
                    tooltip=["Estado", "Cantidad"]
                )
                text_p = base_p.mark_text(radius=120).encode(text="Cantidad", color=alt.value("black"))
                st.altair_chart(pie_p + text_p, use_container_width=True)
                
                # Alerta Visual con Fecha de Corte
                no_ins = df[df['ESTADO_PERCAPITA'] == "PENDIENTE INSCRIPCION"]
                
                # Obtener la fecha de corte (asumiendo que es la misma para todos los registros procesados)
                fecha_corte_msg = df['PERIODO_CORTE_LABEL'].mode()[0] if 'PERIODO_CORTE_LABEL' in df.columns and not df['PERIODO_CORTE_LABEL'].empty else "fecha desconocida"

                if not no_ins.empty:
                    st.error(f"🚨 **ALERTA:** {len(no_ins)} pacientes atendidos NO figuran inscritos en el último corte ({fecha_corte_msg}).")
                    with st.expander("Ver Listado de No Inscritos"):
                        st.dataframe(no_ins[['RUT', 'NOMBRE_PACIENTE', 'TELEFONO', 'SECTOR']])
            else:
                st.info("Sin datos percapita.")

    # === TAB 3: CARGA ASISTENCIAL ===
    with tab3:
        c_prof, c_motivo = st.columns(2)
        with c_prof:
            st.markdown("##### 👨‍⚕️ Carga por Profesional")
            df_prof = df['NOMBRE_PROFESIONAL'].value_counts().reset_index().head(10)
            df_prof.columns = ['Profesional', 'Pacientes']
            chart_prof = alt.Chart(df_prof).mark_bar(cornerRadius=5).encode(
                x=alt.X('Pacientes', title='Total Atenciones'),
                y=alt.Y('Profesional', sort='-x', title=None),
                color=alt.Color('Pacientes', scale=alt.Scale(scheme='blues')),
                tooltip=['Profesional', 'Pacientes']
            ).properties(height=400)
            st.altair_chart(chart_prof, use_container_width=True)
        with c_motivo:
            st.markdown("##### 📋 Top Motivos de Consulta")
            if 'MOTIVO_CLEAN' in df.columns:
                df_motivo = df['MOTIVO_CLEAN'].value_counts().reset_index().head(10)
                df_motivo.columns = ['Motivo', 'Frecuencia']
                chart_motivo = alt.Chart(df_motivo).mark_bar(color='#FF9F43', cornerRadius=5).encode(
                    x=alt.X('Frecuencia'),
                    y=alt.Y('Motivo', sort='-x', title=None),
                    tooltip=['Motivo', 'Frecuencia']
                ).properties(height=400)
                st.altair_chart(chart_motivo, use_container_width=True)

    # === TAB 4: GESTIÓN CUPOS (NUEVO) ===
    with tab4:
        st.markdown("##### ♻️ Detalle de Horas Disponibles (Recuperables)")
        st.caption("Pacientes que respondieron 'NO' y cuya cita es en el futuro (Días Restantes > 0).")
        
        if total_horas_disponibles > 0:
            # Mostrar tabla filtrada solo con columnas relevantes para gestión rápida
            st.dataframe(
                horas_disponibles_df[['FECHA_AGENDADA', 'HORA_AGENDADA', 'NOMBRE_PROFESIONAL', 'RUT', 'NOMBRE_PACIENTE', 'TELEFONO', 'DIAS_RESTANTES']],
                use_container_width=True,
                hide_index=True
            )
            
            # Gráfico de disponibilidad por día
            st.markdown("##### 📅 Disponibilidad por Fecha")
            df_disp_date = horas_disponibles_df['FECHA_AGENDADA'].value_counts().reset_index()
            df_disp_date.columns = ['Fecha', 'Cupos Libres']
            
            chart_disp = alt.Chart(df_disp_date).mark_bar(color='#88C543').encode(
                x=alt.X('Fecha', sort=None),
                y=alt.Y('Cupos Libres'),
                tooltip=['Fecha', 'Cupos Libres']
            ).properties(height=300)
            st.altair_chart(chart_disp, use_container_width=True)
            
        else:
            st.success("🎉 No hay cancelaciones futuras pendientes de reasignar. ¡Agenda eficiente!")

    # === TAB 5: GESTIÓN TEMPORAL (HEATMAP MEJORADO) ===
    with tab5:
        st.markdown("##### 🕒 Mapa de Calor: Días vs Horas Punta")
        st.caption("Visualiza las cargas horarias críticas distribuidas por día de la semana (Considera reagendamientos).")
        
        if 'HORA_INT' in df.columns and 'DIA_SEMANA_ES' in df.columns:
            # Filtramos horas inválidas
            df_heat = df[df['HORA_INT'] != -1].copy()
            
            dias_orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
            
            heatmap = alt.Chart(df_heat).mark_rect().encode(
                x=alt.X('HORA_LABEL:O', title='Bloque Horario', sort=alt.EncodingSortField(field="HORA_INT", order="ascending")),
                y=alt.Y('DIA_SEMANA_ES:O', title='Día de la Semana', sort=dias_orden),
                color=alt.Color('count()', title='Carga Pacientes', scale=alt.Scale(scheme='orangered')),
                tooltip=[
                    alt.Tooltip('DIA_SEMANA_ES', title='Día'),
                    alt.Tooltip('HORA_LABEL', title='Hora'),
                    alt.Tooltip('count()', title='Pacientes')
                ]
            ).properties(height=350).configure_axis(
                labelFontSize=12,
                titleFontSize=14
            )
            
            st.altair_chart(heatmap, use_container_width=True)
        else:
            st.warning("Datos insuficientes para generar el mapa de calor temporal.")

    # === TAB 6: CONTROL DE CAMBIOS ===
    with tab6:
        col_kpi_rea, col_chart_rea = st.columns([1, 2])
        total_reagendados_historicos = len(df[df['CAMBIO_DE_HORA'] == 'SI'])
        with col_kpi_rea:
            st.warning(f"Total Reagendamientos: {total_reagendados_historicos}")
            st.markdown("**Desglose:**")
            if total_reagendados_historicos > 0:
                if 'ESTADO_REA' in df.columns:
                    counts_rea = df[df['CAMBIO_DE_HORA'] == 'SI']['ESTADO_REA'].value_counts()
                    st.write(counts_rea)
        with col_chart_rea:
            st.markdown("##### 🔄 Motivos de Reagendamiento")
            if total_reagendados_historicos > 0:
                df_mot_rea = df[df['CAMBIO_DE_HORA'] == 'SI']['MOTIVO_CONSULTA_REA'].value_counts().reset_index()
                df_mot_rea.columns = ['Motivo Cambio', 'Cantidad']
                chart_mot_rea = alt.Chart(df_mot_rea).mark_arc().encode(
                    theta=alt.Theta(field="Cantidad", type="quantitative"),
                    color=alt.Color(field="Motivo Cambio", type="nominal", scale=alt.Scale(scheme='category20b')),
                    tooltip=['Motivo Cambio', 'Cantidad']
                )
                st.altair_chart(chart_mot_rea, use_container_width=True)

    # === TAB 7: CALENDARIO (LOCALIZADO) ===
    with tab7:
        col_evol, col_cal = st.columns([1, 2])
        
        with col_evol:
            st.markdown("##### 📈 Evolución Mensual")
            if 'FECHA_DT' in df.columns and not df.empty:
                # Filtrar fechas válidas
                df_valid_dates = df.dropna(subset=['FECHA_DT'])
                if not df_valid_dates.empty:
                    # Agrupar por mes y año usando la FECHA_EFECTIVA (FECHA_DT)
                    df_monthly = df_valid_dates.set_index('FECHA_DT').resample('ME').size().reset_index(name='Total')
                    
                    if not df_monthly.empty:
                        # Asegurarse de que no queden NaT después del resample
                        df_monthly = df_monthly.dropna(subset=['FECHA_DT'])
                        
                        if not df_monthly.empty:
                            # TRADUCCIÓN DE MESES
                            df_monthly['Mes_Num'] = df_monthly['FECHA_DT'].dt.month.astype(int)
                            df_monthly['Año'] = df_monthly['FECHA_DT'].dt.year.astype(int)
                            df_monthly['Mes_Label'] = df_monthly.apply(lambda x: f"{MESES_ES.get(x['Mes_Num'], 'Desconocido')} {x['Año']}", axis=1)
                            
                            chart_monthly = alt.Chart(df_monthly).mark_bar(color='#006DB6').encode(
                                x=alt.X('Mes_Label', sort=None, title='Mes'),
                                y=alt.Y('Total', title='Total Pacientes'),
                                tooltip=['Mes_Label', 'Total']
                            ).properties(height=300)
                            st.altair_chart(chart_monthly, use_container_width=True)
                        else:
                            st.info("No hay datos mensuales válidos.")
                    else:
                        st.info("No hay registros mensuales.")
                else:
                    st.info("No hay fechas válidas en los registros.")
            else:
                st.info("No hay datos históricos suficientes.")

        with col_cal:
            st.markdown("##### 🗓️ Calendario Semanal (Heatmap)")
            if 'FECHA_DT' in df.columns and 'DIA_SEMANA_ES' in df.columns:
                df_cal = df.copy()
                # Usamos la FECHA_DT que ahora es la efectiva
                df_cal = df_cal[df_cal['FECHA_DT'].notna()]
                dias_orden = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
                heatmap = alt.Chart(df_cal).mark_rect().encode(
                    x=alt.X('DIA_SEMANA_ES:N', title='Día de la Semana', sort=dias_orden), 
                    y=alt.Y('week(FECHA_DT):O', title='Semana del Año'),
                    color=alt.Color('count()', title='N° Pacientes', scale=alt.Scale(scheme='greens')),
                    tooltip=[
                        alt.Tooltip('yearmonthdate(FECHA_DT)', title='Fecha'),
                        alt.Tooltip('DIA_SEMANA_ES', title='Día'),
                        alt.Tooltip('count()', title='Pacientes')
                    ]
                ).properties(width=700, height=300)
                st.altair_chart(heatmap, use_container_width=True)
            else:
                st.warning("No hay fechas válidas para generar el calendario.")

    # === TAB 8: ANALISTA VIRTUAL ===
    with tab8:
        col_ia_1, col_ia_2 = st.columns([1, 2])
        
        with col_ia_1:
            st.markdown("### 🧠 Analista Virtual")
            limite_max = status['limite']
            uso_actual = st.session_state.ai_usage
            
            st.markdown(f"""
            <div style="background-color:#F8F9FA; padding:15px; border-radius:10px; border-left: 4px solid #006DB6; font-size:0.9rem;">
                <strong>Plan Actual:</strong> {status['plan']}<br>
                <strong>Consultas:</strong> {uso_actual} / {limite_max}
            </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            st.divider()
            
            if uso_actual >= limite_max:
                st.error(f"🚫 Límite diario alcanzado ({limite_max}).")
                st.button("✨ Generar Reporte", disabled=True)
            else:
                if st.button("✨ Generar Reporte Ejecutivo", type="primary", use_container_width=True):
                    
                    with col_ia_2:
                        with st.spinner("🧠 Analizando datos y registrando consumo..."):
                            # 1. Generar Reporte (Usando Prompt de Excel)
                            resultado_ia = generar_analisis_clinico(df)
                            
                            # 2. Guardar en Memoria para persistencia
                            st.session_state.ultimo_reporte_ia = resultado_ia
                            
                            # 3. Incrementar Contador Local
                            nuevo_contador = uso_actual + 1
                            st.session_state.ai_usage = nuevo_contador
                            
                            # 4. Guardar Contador en Nube (Col H)
                            exito_save = registrar_consumo_ia(ROW_INDEX_ADMIN, nuevo_contador)
                            
                            if exito_save:
                                st.toast("Consumo registrado en la nube", icon="✅")
                            else:
                                st.warning("Error guardando contador en nube")
                            
                            # 5. Recargar para actualizar UI
                            time.sleep(0.5)
                            st.rerun()
        
        with col_ia_2:
            # MOSTRAR EL REPORTE (Persistente)
            if st.session_state.ultimo_reporte_ia:
                st.markdown(f"""
                <div class="report-container">
                    <div class="report-header">
                        📊 REPORTE GERENCIAL DIARIO | {datetime.now().strftime("%d/%m/%Y")}
                    </div>
                    <div style="color: #444; line-height: 1.6;">
                        {st.session_state.ultimo_reporte_ia}
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                if st.button("🗑️ Limpiar Pantalla"):
                    st.session_state.ultimo_reporte_ia = None
                    st.rerun()
            else:
                st.info("👋 Presiona el botón para que la IA analice los datos.")

    # === TAB 9: DETECTOR DE POLICONSULTANTES (CRITERIO MULTI-MOTIVO) ===
    with tab9:
        st.markdown("### 🔍 Análisis de Policonsultantes (Multi-Causal)")
        st.markdown("Identifica pacientes que consultan por **distintos motivos clínicos** (ej: Control + Urgencia + Consulta).")
        
        col_config, col_kpi = st.columns([1, 2])
        
        with col_config:
            st.markdown("##### ⚙️ Configuración")
            # Cambiamos el slider para reflejar "Motivos Distintos"
            umbral_motivos = st.slider(
                "Mínimo de Motivos Distintos", 
                min_value=2, 
                max_value=10, 
                value=2,
                help="El paciente debe tener al menos esta cantidad de motivos de consulta DIFERENTES para aparecer en la lista."
            )
        
        # --- LÓGICA DE PROCESAMIENTO AVANZADA ---
        if 'RUT' in df.columns and not df.empty:
            
            # 1. Agrupamos por RUT y calculamos dos cosas:
            #    - Cuántos motivos únicos tiene (nunique)
            #    - El total de citas (count) para referencia
            #    - Obtenemos los datos personales
            
            # Limpiamos espacios en blanco extra en motivos para evitar duplicados falsos ("Motivo " vs "Motivo")
            if 'MOTIVO_CONSULTA' in df.columns:
                df['MOTIVO_NORMALIZADO'] = df['MOTIVO_CONSULTA'].astype(str).str.strip().str.upper()
            else:
                df['MOTIVO_NORMALIZADO'] = "SIN INFO"

            # Agregación maestra
            stats_pacientes = df.groupby('RUT_CLEAN').agg({
                'MOTIVO_NORMALIZADO': 'nunique', # ESTA ES LA CLAVE: Cuenta únicos
                'FECHA_AGENDADA': 'count'        # Cuenta total de citas
            }).reset_index()
            
            # Renombramos para trabajar fácil
            stats_pacientes.columns = ['RUT_CLEAN', 'CANT_MOTIVOS_UNICOS', 'TOTAL_ATENCIONES']
            
            # 2. Filtramos: Solo los que cumplen el umbral de motivos DISTINTOS
            polis_ruts = stats_pacientes[stats_pacientes['CANT_MOTIVOS_UNICOS'] >= umbral_motivos]['RUT_CLEAN'].tolist()
            
            # 3. Filtramos el DataFrame original con esos RUTs para ver el detalle
            df_polis = df[df['RUT_CLEAN'].isin(polis_ruts)].copy()
            
            if not df_polis.empty:
                with col_kpi:
                    st.metric(
                        "Pacientes Policonsultantes", 
                        len(polis_ruts), 
                        f"Con {umbral_motivos}+ motivos distintos"
                    )

                # 4. Transformación para el Reporte Visual
                # Creamos el detalle concatenado
                df_polis['DETALLE_CITA'] = (
                    "[" + df_polis['MOTIVO_CONSULTA'] + "] " + 
                    df_polis['FECHA_AGENDADA'] + " con " + 
                    df_polis['NOMBRE_PROFESIONAL']
                )
                
                # Agrupamos para consolidar en una fila por paciente
                # Usamos set() en los motivos para mostrar el resumen de qué tipos de atención tomó
                reporte_polis = df_polis.groupby('RUT_CLEAN').agg({
                    'NOMBRE_PACIENTE': 'first',
                    'RUT': 'first',
                    'TELEFONO': 'first',
                    'SECTOR': 'first',
                    'DETALLE_CITA': lambda x: " || ".join(x), # Historial completo
                    'MOTIVO_NORMALIZADO': lambda x: ", ".join(sorted(list(set(x)))) # Resumen de motivos únicos
                }).reset_index()
                
                # Traemos las métricas calculadas en el paso 1
                reporte_polis = reporte_polis.merge(stats_pacientes, on='RUT_CLEAN', how='left')
                
                # Ordenar: Primero los que tienen MÁS motivos distintos, luego por total de citas
                reporte_polis = reporte_polis.sort_values(by=['CANT_MOTIVOS_UNICOS', 'TOTAL_ATENCIONES'], ascending=[False, False])
                
                # --- VISUALIZACIÓN ---
                st.divider()
                st.subheader(f"📋 Listado de Policonsultantes ({len(reporte_polis)} detectados)")
                
                # Configuramos la tabla para que se vea bien
                st.dataframe(
                    reporte_polis[['CANT_MOTIVOS_UNICOS', 'TOTAL_ATENCIONES', 'RUT', 'NOMBRE_PACIENTE', 'MOTIVO_NORMALIZADO', 'DETALLE_CITA']],
                    use_container_width=True,
                    column_config={
                        "CANT_MOTIVOS_UNICOS": st.column_config.NumberColumn("Motivos Distintos", help="Cantidad de tipos de atención diferentes"),
                        "TOTAL_ATENCIONES": st.column_config.NumberColumn("Total Atenciones"),
                        "MOTIVO_NORMALIZADO": st.column_config.TextColumn("Resumen Tipos Atención", width="medium"),
                        "DETALLE_CITA": st.column_config.TextColumn("Historial Detallado (Fecha | Prof)", width="large"),
                    }
                )
                
                # --- BOTÓN DE EXPORTACIÓN ---
                col_exp1, col_exp2 = st.columns([1, 4])
                with col_exp1:
                    csv_polis = reporte_polis.to_csv(index=False).encode('utf-8-sig')
                    st.download_button(
                        label="📥 Descargar Excel (CSV)",
                        data=csv_polis,
                        file_name=f"Policonsultantes_Multicausal_{datetime.now().strftime('%Y%m%d')}.csv",
                        mime='text/csv',
                        type="primary"
                    )
                with col_exp2:
                    st.info(f"💡 El filtro actual muestra pacientes que tienen al menos {umbral_motivos} tipos de atención diferentes.")
                    
            else:
                st.success(f"✅ No se encontraron pacientes con {umbral_motivos} o más motivos de consulta distintos.")
        else:
            st.warning("No hay datos suficientes.")

# -----------------------------------------------------------------------------
# VISTA 2: GESTIÓN DE HORAS (REAGENDAMIENTO)
# -----------------------------------------------------------------------------
elif menu_option == "Gestión de Horas":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">📝 Gestión de Horas Médicas</h1>
            <p class="header-subtitle">Seleccione un paciente de la tabla para modificar sus datos</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_search, _ = st.columns([2, 1])
    with col_search:
        search_text = st.text_input("🔎 Filtrar por Nombre, RUT o Teléfono:", placeholder="Escriba para filtrar la tabla...")

    df_view = df.copy()
    if search_text and not df_view.empty:
        mask = df_view.astype(str).apply(lambda x: x.str.contains(search_text, case=False, na=False)).any(axis=1)
        df_view = df_view[mask]

    st.info("👆 Haga clic en la casilla a la izquierda de la fila para seleccionar un paciente.")
    
    event = st.dataframe(
        df_view,
        on_select="rerun",
        selection_mode="single-row",
        use_container_width=True,
        height=400,
        hide_index=True
    )

    if len(event.selection.rows) > 0:
        selected_row_index = event.selection.rows[0]
        patient_selected = df_view.iloc[selected_row_index]
        
        st.divider()
        st.markdown(f"### ✏️ Editando: **{patient_selected['NOMBRE_PACIENTE']}** (RUT: {patient_selected.get('RUT', 'S/I')})")
        
        with st.form("form_reagendamiento"):
            st.info(f"📅 Cita Actual: {patient_selected['FECHA_AGENDADA']} a las {patient_selected['HORA_AGENDADA']} con {patient_selected['NOMBRE_PROFESIONAL']}")
            
            activar_reagendamiento = st.checkbox("🛑 Activar Reagendamiento", value=(str(patient_selected['CAMBIO_DE_HORA']) == "SI"))
            
            col_a, col_b = st.columns(2)
            with col_a:
                new_date_val = patient_selected['NUEVA_FECHA']
                try:
                    default_date = datetime.strptime(new_date_val, "%d/%m/%Y") if new_date_val else datetime.now()
                except:
                    default_date = datetime.now()
                    
                new_fecha = st.date_input("Nueva Fecha", value=default_date)
                
                # === SELECTBOX DE HORAS ===
                current_time_val = patient_selected['HORA_NUEVA_FECHA']
                idx_hora = 0
                if current_time_val in LISTA_HORAS:
                    idx_hora = LISTA_HORAS.index(current_time_val)
                
                new_hora_str = st.selectbox("Nueva Hora (Menú)", LISTA_HORAS, index=idx_hora)
            
            with col_b:
                new_prof = st.text_input("Profesional Reasignado (Nombre)", value=patient_selected['NOM_PROF_REASIG'])
                current_prof_rea = patient_selected['PROFESION_PROF_RE'] if patient_selected['PROFESION_PROF_RE'] in LISTA_PROFESIONES else LISTA_PROFESIONES[0]
                new_profesion_rea = st.selectbox("Profesión (Reasignado)", LISTA_PROFESIONES, index=LISTA_PROFESIONES.index(current_prof_rea))
                current_motivo_rea = patient_selected['MOTIVO_CONSULTA_REA'] if patient_selected['MOTIVO_CONSULTA_REA'] in LISTA_MOTIVOS else LISTA_MOTIVOS[0]
                new_motivo = st.selectbox("Motivo Reagendamiento", LISTA_MOTIVOS, index=LISTA_MOTIVOS.index(current_motivo_rea))

            submit_update = st.form_submit_button("💾 Guardar Cambios")
            
            if submit_update:
                try:
                    sheet_obj, _, msg = connect_sheet()
                    if sheet_obj:
                        row_num = patient_selected.name + 2
                        cambio_val = "SI" if activar_reagendamiento else "NO"
                        fecha_str = new_fecha.strftime("%d/%m/%Y") if activar_reagendamiento else ""
                        hora_str = new_hora_str if activar_reagendamiento else ""
                        
                        # === CRÍTICO: ACTUALIZACIÓN DE CELDAS CON NUEVOS ÍNDICES ===
                        sheet_obj.update_cell(row_num, 16, cambio_val) # CAMBIO_DE_HORA
                        sheet_obj.update_cell(row_num, 17, fecha_str) # NUEVA_FECHA
                        sheet_obj.update_cell(row_num, 18, hora_str)  # HORA_NUEVA_FECHA
                        sheet_obj.update_cell(row_num, 19, new_prof)  # NOM_PROF_REASIG
                        sheet_obj.update_cell(row_num, 20, new_profesion_rea) # PROFESION_PROF_RE
                        sheet_obj.update_cell(row_num, 21, new_motivo) # MOTIVO_CONSULTA_REA
                        
                        if activar_reagendamiento:
                            sheet_obj.update_cell(row_num, 22, "") # Reset ESTADO_REA
                        
                        st.success("✅ Datos actualizados correctamente en la nube.")
                        time.sleep(1.5)
                        st.cache_data.clear()
                        st.rerun()
                    else:
                        st.error("Error de conexión.")
                except Exception as e:
                    st.error(f"Error al actualizar: {e}")


# -----------------------------------------------------------------------------
# VISTA 3: NUEVO INGRESO
# -----------------------------------------------------------------------------
elif menu_option == "Nuevo Ingreso":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">📥 Nuevo Ingreso</h1>
            <p class="header-subtitle">Registrar paciente manualmente en el sistema con datos demográficos</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    with st.form("form_ingreso", clear_on_submit=True):
        st.markdown("**1. Datos Personales**")
        c1, c2, c3 = st.columns(3)
        with c1:
            rut = st.text_input("RUT Paciente", placeholder="Ej: 12345678-9") # NUEVO CAMPO RUT
            nombre = st.text_input("Nombre Completo Paciente", placeholder="Ej: Juan Pérez")
            telefono = st.text_input("Teléfono", placeholder="Ej: 56912345678 (Debe comenzar con 569)")
        with c2:
            # Definimos 'hoy' primero para usarlo como límite máximo
            hoy = datetime.now()

            fecha_nac = st.date_input(
                "Fecha de Nacimiento",
                value=datetime(1980, 1, 1),       # Fecha por defecto
                min_value=datetime(1900, 1, 1),   # Fecha mínima (lo más antiguo)
                max_value=hoy                     # <--- ESTO AGREGA EL LÍMITE HASTA HOY
            )

            # Cálculo de edad (se mantiene igual, pero usamos .date() para comparar correctamente)
            hoy_edad = hoy.date()
            edad_calc = hoy_edad.year - fecha_nac.year - ((hoy_edad.month, hoy_edad.day) < (fecha_nac.month, fecha_nac.day))

            
        with c3:
            genero = st.selectbox("Género", ["Femenino", "Masculino", "Otro", "No Informa"])
            
        st.markdown("**2. Datos de la Atención**")
        c4, c5 = st.columns(2)
        with c4:
            fecha = st.date_input("Fecha de Atención", min_value=datetime.now())
            hora = st.time_input("Hora de Atención")
        with c5:
            profesional = st.text_input("Nombre Profesional", placeholder="Ej: Dra. Ana López")
            profesion = st.selectbox("Profesión", LISTA_PROFESIONES)
            motivo = st.selectbox("Motivo Consulta", LISTA_MOTIVOS)
        
        submit = st.form_submit_button("💾 Guardar Paciente", use_container_width=True)
        
        if submit:
            if not (telefono.startswith("569") and len(telefono) == 11 and telefono.isdigit()):
                st.error("⚠️ El teléfono debe tener el formato 569XXXXXXXX (11 dígitos y comenzar con 569).")
            elif nombre and telefono and profesional and rut:
                try:
                    sheet_obj, _, msg = connect_sheet()
                    if sheet_obj:

                        # === MAPEO DE 27 COLUMNAS (AGREGADA TOTAL_REV) ===
                        new_row = [
                            rut,                                            # 1. RUT
                            nombre,                                         # 2. NOMBRE_PACIENTE
                            telefono,                                       # 3. TELEFONO
                            fecha_nac.strftime("%d/%m/%Y"),                 # 4. FECHA_NACIMIENTO
                            str(edad_calc),                                 # 5. EDAD_ACTUAL
                            genero,                                         # 6. GENERO
                            fecha.strftime("%d/%m/%Y"),                     # 7. FECHA_AGENDADA
                            hora.strftime("%H:%M"),                         # 8. HORA_AGENDADA
                            profesional,                                    # 9. NOMBRE_PROFESIONAL
                            profesion,                                      # 10. PROFESION
                            motivo,                                         # 11. MOTIVO_CONSULTA
                            "", "", "", "",                                 # 12-15: Datos Notif 1
                            "NO",                                           # 16: CAMBIO_DE_HORA
                            "", "", "", "", "",                             # 17-21: Datos Reagendamiento
                            "", "", "",                                     # 22-24: Datos Notif 2
                            "", "",                                         # 25-26: CONFIRMA_HORA, CONFIRMA_REAGEN
                            ""                                              # 27: TOTAL_REV (COLUMNA AA)
                        ]
                        
                        sheet_obj.append_row(new_row)
                        st.success(f"✅ Paciente {nombre} ({edad_calc} años) registrado exitosamente.")
                        st.cache_data.clear() 
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Error de conexión con Google Sheets.")
                except Exception as e:
                    st.error(f"Error al guardar: {e}")
            else:
                st.warning("⚠️ Por favor complete los campos obligatorios (RUT, Nombre, Teléfono).")

# -----------------------------------------------------------------------------
# VISTA 4: CENTRO DE NOTIFICACIONES (CORREGIDO DUPLICATE ID + LÓGICA 5 REV)
# -----------------------------------------------------------------------------
elif menu_option == "Centro de Notificaciones":

    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">Centro de Notificaciones</h1>
            <p class="header-subtitle">Motor de automatización de WhatsApp</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_action, col_terminal = st.columns([1, 2])

    with col_action:
        st.markdown("### 🚀 Control de Misión")
        st.markdown("""
        <div style="background:white; padding:20px; border-radius:16px; box-shadow: var(--card-shadow);">
            <p style="color:#8898AA; font-size:0.9rem;">
                El bot procesará automáticamente:<br>
                • Recordatorios (2 días antes, o 3 si es viernes)<br>
                • Reagendamientos Urgentes<br>
                • Revisiones (Máx 5 intentos)
            </p>
            <hr style="margin:15px 0; border-top:1px solid #eee;">
            <p style="font-weight:600; margin-bottom:10px;">Estado del Servicio:</p>
            <span style="background:#E6FFFA; color:#28C76F; padding:5px 10px; border-radius:4px; font-size:0.8rem; font-weight:bold;">DISPONIBLE</span>
        </div>
        """, unsafe_allow_html=True)
        
        st.write("")
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        # SOLUCIÓN ERROR: Se agregó key="btn_iniciar_masivo"
        iniciar = st.button("▶ INICIAR ENVÍOS MASIVOS", use_container_width=True, key="btn_iniciar_masivo")
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.info("📱 Mantén tu celular conectado a internet.")
        
        st.write("")
        st.markdown('<div class="primary-action">', unsafe_allow_html=True)
        # SOLUCIÓN ERROR: Se agregó key="btn_verificar_resp"
        verificar = st.button("🔎 VERIFICAR RESPUESTAS", use_container_width=True, key="btn_verificar_resp")
        st.markdown('</div>', unsafe_allow_html=True)

    with col_terminal:
        st.markdown("### 📟 Log del Sistema")
        log_placeholder = st.empty()
        
        log_placeholder.markdown("""
        <div class="terminal-window">
            <div class="terminal-header">
                <div class="terminal-dot dot-red"></div>
                <div class="terminal-dot dot-yellow"></div>
                <div class="terminal-dot dot-green"></div>
            </div>
            <div class="terminal-body">
                <span class="log-info">[SYSTEM]</span> Esperando comando de inicio...<br>
                <span class="log-info">[SYSTEM]</span> Conexión a GSheets: OK<br>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # === LÓGICA DE ENVÍO (BOTÓN 1) CORREGIDA ===
        if iniciar:
            driver = init_driver()
            if not driver:
                st.error("Error crítico: No se pudo iniciar Chrome Driver.")
                st.stop()
            
            logs = []
            def update_terminal(new_log_line):
                logs.append(new_log_line)
                log_content = "<br>".join(logs[-15:])
                log_placeholder.markdown(f"""
                <div class="terminal-window">
                    <div class="terminal-header">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                    </div>
                    <div class="terminal-body">
                        {log_content}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            update_terminal(f'<span class="log-info">[BOOT]</span> Iniciando navegador seguro...')
            
            try:
                driver.get("https://web.whatsapp.com")
                update_terminal(f'<span class="log-info">[AUTH]</span> Esperando escaneo QR...')
                
                if esperar_login_qr(driver):
                    update_terminal(f'<span class="log-success">[AUTH]</span> Login exitoso. Acceso concedido.')
                    time.sleep(2)
                else:
                    update_terminal(f'<span class="log-error">[ERROR]</span> Tiempo agotado. Abortando.')
                    driver.quit()
                    st.stop()

                sheet_conn, _, _ = connect_sheet()
                data = sheet_conn.get_all_values()
                df_proc = pd.DataFrame(data[1:], columns=data[0])
                df_proc.columns = df_proc.columns.str.strip()
                
                total_rows = len(df_proc)
                progress_bar = st.progress(0)

                # CONTADOR PARA PAUSAS LARGAS (COOL-DOWN)
                mensajes_enviados_racha = 0 

                for idx, row in df_proc.iterrows():
                    # 1. LÓGICA DE DESCANSO LARGO (FRENO DE EMERGENCIA)
                    if mensajes_enviados_racha >= random.randint(5, 9):
                        tiempo_descanso = random.randint(120, 300) # 2 a 5 minutos
                        update_terminal(f'<span class="log-info">☕ Tomando descanso de seguridad por {tiempo_descanso}s...</span>')
                        time.sleep(tiempo_descanso)
                        mensajes_enviados_racha = 0 # Reiniciar contador
                    
                    # 2. PAUSA MICRO PARA NO SATURAR CPU (PERO NO FRENA EL BUCLE)
                    time.sleep(0.05)

                    try: 
                        try: _ = driver.window_handles
                        except: break

                        fila = idx + 2
                        nombre = row['NOMBRE_PACIENTE']
                        
                        es_cambio = str(row['CAMBIO_DE_HORA']).strip().upper() == "SI"
                        st_rea = str(row['ESTADO_REA']).strip()
                        st_nor = str(row['ESTADO']).strip()
                        
                        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
                        accion = False

                        # === BLOQUE DE ENVÍO REAGENDAMIENTO ===
                        if es_cambio and st_rea == "":
                            # --- AQUI SÍ ESPERAMOS (SOLO SI VAMOS A ENVIAR) ---
                            update_terminal(f'<span class="log-info">⏳ Esperando turno seguro para enviar...</span>')
                            time.sleep(random.uniform(12, 30))
                            
                            update_terminal(f'<span class="log-info">[PROC] Reagendando: {nombre}...')
                            
                            if not row['HORA_NUEVA_FECHA'] or not row['NUEVA_FECHA']:
                                update_terminal(f'<span class="log-error">[FAIL] Datos incompletos para {nombre}')
                            else:
                                # Usar mensaje dinámico desde Admin
                                msg = get_template(row, "REAGENDAMIENTO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                if ok:
                                    mensajes_enviados_racha += 1
                                    try:
                                        sheet_conn.update_cell(fila, 22, "NOTIFICADO OK") # ESTADO_REA
                                        sheet_conn.update_cell(fila, 23, ahora)            # FECHA_NOTIF_2
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")       # METODO_REA
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT] Reagendamiento enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 22, "ERROR")            
                                        sheet_conn.update_cell(fila, 23, ahora)
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR] Fallo envío a {nombre}: {log}')
                            accion = True

                        # === BLOQUE DE ENVÍO RECORDATORIO NORMAL ===
                        elif not es_cambio and st_nor == "":
                            dias = calcular_dias(row['FECHA_AGENDADA'])
                            
                            # === LÓGICA DE VIERNES (NOTIFICAR HASTA EL LUNES) ===
                            dia_semana_hoy = datetime.now().weekday() # 4 es Viernes
                            rango_maximo = 3 if dia_semana_hoy == 4 else 2
                            
                            # Actualización visual en Google Sheets (Column O - Observación)
                            if str(row['OBSERVACION']).strip() == "":
                                try:
                                    if dias == 0: sheet_conn.update_cell(fila, 15, "⚠️ Atención HOY")
                                    elif dias == 1: sheet_conn.update_cell(fila, 15, "⚠️ Falta 1 día")
                                    elif dias == 2: sheet_conn.update_cell(fila, 15, "⚠️ Faltan 2 días")
                                    elif dias == 3 and dia_semana_hoy == 4: sheet_conn.update_cell(fila, 15, "⚠️ Faltan 3 días (Fin de Semana)")
                                    elif dias > rango_maximo: sheet_conn.update_cell(fila, 15, f"Faltan {dias} días")
                                except: pass

                            # === CONDICIÓN DE ENVÍO ===
                            if 1 <= dias <= rango_maximo:
                                # --- AQUI SÍ ESPERAMOS (SOLO SI VAMOS A ENVIAR) ---
                                update_terminal(f'<span class="log-info">⏳ Esperando turno seguro para enviar...</span>')
                                time.sleep(random.uniform(12, 30))

                                update_terminal(f'<span class="log-info">[PROC] Recordatorio: {nombre} ({dias} días)...')
                                
                                # Obtener mensaje dinámico
                                msg = get_template(row, "RECORDATORIO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                
                                if ok:
                                    mensajes_enviados_racha += 1
                                    try:
                                        sheet_conn.update_cell(fila, 12, "NOTIFICADO OK") # ESTADO
                                        sheet_conn.update_cell(fila, 13, ahora)           # FECHA_NOTIF_1
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")      # METODO
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT] Recordatorio enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 12, "ERROR")          
                                        sheet_conn.update_cell(fila, 13, ahora)
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR] Fallo envío a {nombre}: {log}')
                                accion = True

                            elif dias < 0:
                                 if row['OBSERVACION'] == "": 
                                     try: sheet_conn.update_cell(fila, 15, "Fecha Pasada") 
                                     except: pass

                    except Exception as e_inner:
                        update_terminal(f'<span class="log-error">[CRIT] Error en fila {fila}: {str(e_inner)}</span>')
                        continue 

                    progress_bar.progress((idx + 1) / total_rows)

                update_terminal(f'<span class="log-success">[DONE] Todas las tareas finalizadas.</span>')
                st.balloons()
                st.cache_data.clear() 
                
            except Exception as e:
                st.error(f"Error crítico: {e}")
            finally:
                if driver: driver.quit()
            driver = init_driver()
            if not driver:
                st.error("Error crítico: No se pudo iniciar Chrome Driver.")
                st.stop()
            
            logs = []
            def update_terminal(new_log_line):
                logs.append(new_log_line)
                log_content = "<br>".join(logs[-15:])
                log_placeholder.markdown(f"""
                <div class="terminal-window">
                    <div class="terminal-header">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                    </div>
                    <div class="terminal-body">
                        {log_content}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            update_terminal(f'<span class="log-info">[BOOT]</span> Iniciando navegador seguro...')
            
            try:
                driver.get("https://web.whatsapp.com")
                update_terminal(f'<span class="log-info">[AUTH]</span> Esperando escaneo QR...')
                
                if esperar_login_qr(driver):
                    update_terminal(f'<span class="log-success">[AUTH]</span> Login exitoso. Acceso concedido.')
                    time.sleep(2)
                else:
                    update_terminal(f'<span class="log-error">[ERROR]</span> Tiempo agotado. Abortando.')
                    driver.quit()
                    st.stop()

                sheet_conn, _, _ = connect_sheet()
                data = sheet_conn.get_all_values()
                df_proc = pd.DataFrame(data[1:], columns=data[0])
                df_proc.columns = df_proc.columns.str.strip()
                
                total_rows = len(df_proc)
                progress_bar = st.progress(0)

                # CONTADOR PARA PAUSAS LARGAS (COOL-DOWN)
                mensajes_enviados_racha = 0 

                for idx, row in df_proc.iterrows():
                    # 1. LÓGICA DE DESCANSO LARGO (FRENO DE EMERGENCIA)
                    if mensajes_enviados_racha >= random.randint(5, 9):
                        tiempo_descanso = random.randint(120, 300) # 2 a 5 minutos
                        update_terminal(f'<span class="log-info">☕ Tomando descanso de seguridad por {tiempo_descanso}s...</span>')
                        time.sleep(tiempo_descanso)
                        mensajes_enviados_racha = 0 # Reiniciar contador
                    
                    # 2. PAUSA ENTRE MENSAJES INDIVIDUALES
                    time.sleep(random.uniform(12, 30))

                    try: 
                        try: _ = driver.window_handles
                        except: break

                        fila = idx + 2
                        nombre = row['NOMBRE_PACIENTE']
                        
                        es_cambio = str(row['CAMBIO_DE_HORA']).strip().upper() == "SI"
                        st_rea = str(row['ESTADO_REA']).strip()
                        st_nor = str(row['ESTADO']).strip()
                        
                        ahora = datetime.now().strftime("%d/%m/%Y %H:%M")
                        accion = False

                        # === BLOQUE DE ENVÍO REAGENDAMIENTO ===
                        if es_cambio and st_rea == "":
                            update_terminal(f'<span class="log-info">[PROC] Reagendando: {nombre}...')
                            
                            if not row['HORA_NUEVA_FECHA'] or not row['NUEVA_FECHA']:
                                update_terminal(f'<span class="log-error">[FAIL] Datos incompletos para {nombre}')
                            else:
                                # Usar mensaje dinámico desde Admin
                                msg = get_template(row, "REAGENDAMIENTO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                if ok:
                                    mensajes_enviados_racha += 1
                                    try:
                                        sheet_conn.update_cell(fila, 22, "NOTIFICADO OK") # ESTADO_REA
                                        sheet_conn.update_cell(fila, 23, ahora)            # FECHA_NOTIF_2
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")       # METODO_REA
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT] Reagendamiento enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 22, "ERROR")            
                                        sheet_conn.update_cell(fila, 23, ahora)
                                        sheet_conn.update_cell(fila, 24, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR] Fallo envío a {nombre}: {log}')
                            accion = True

                        # === BLOQUE DE ENVÍO RECORDATORIO NORMAL ===
                        elif not es_cambio and st_nor == "":
                            dias = calcular_dias(row['FECHA_AGENDADA'])
                            
                            # === LÓGICA DE VIERNES (NOTIFICAR HASTA EL LUNES) ===
                            dia_semana_hoy = datetime.now().weekday() # 4 es Viernes
                            rango_maximo = 3 if dia_semana_hoy == 4 else 2
                            
                            # Actualización visual en Google Sheets (Column O - Observación)
                            if str(row['OBSERVACION']).strip() == "":
                                try:
                                    if dias == 0: sheet_conn.update_cell(fila, 15, "⚠️ Atención HOY")
                                    elif dias == 1: sheet_conn.update_cell(fila, 15, "⚠️ Falta 1 día")
                                    elif dias == 2: sheet_conn.update_cell(fila, 15, "⚠️ Faltan 2 días")
                                    elif dias == 3 and dia_semana_hoy == 4: sheet_conn.update_cell(fila, 15, "⚠️ Faltan 3 días (Fin de Semana)")
                                    elif dias > rango_maximo: sheet_conn.update_cell(fila, 15, f"Faltan {dias} días")
                                except: pass

                            # === CONDICIÓN DE ENVÍO MODIFICADA ===
                            if 1 <= dias <= rango_maximo:
                                update_terminal(f'<span class="log-info">[PROC] Recordatorio: {nombre} ({dias} días)...')
                                
                                # Obtener mensaje dinámico
                                msg = get_template(row, "RECORDATORIO")
                                ok, log = enviar_mensaje_wsp(driver, row['TELEFONO'], msg)
                                
                                if ok:
                                    mensajes_enviados_racha += 1
                                    try:
                                        sheet_conn.update_cell(fila, 12, "NOTIFICADO OK") # ESTADO
                                        sheet_conn.update_cell(fila, 13, ahora)           # FECHA_NOTIF_1
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")      # METODO
                                    except: pass
                                    update_terminal(f'<span class="log-success">[SENT] Recordatorio enviado a {nombre}')
                                else:
                                    try:
                                        sheet_conn.update_cell(fila, 12, "ERROR")          
                                        sheet_conn.update_cell(fila, 13, ahora)
                                        sheet_conn.update_cell(fila, 14, "WHATSAPP")
                                    except: pass
                                    update_terminal(f'<span class="log-error">[ERR] Fallo envío a {nombre}: {log}')
                                accion = True

                            elif dias < 0:
                                 if row['OBSERVACION'] == "": 
                                     try: sheet_conn.update_cell(fila, 15, "Fecha Pasada") 
                                     except: pass

                    except Exception as e_inner:
                        update_terminal(f'<span class="log-error">[CRIT] Error en fila {fila}: {str(e_inner)}</span>')
                        continue 

                    progress_bar.progress((idx + 1) / total_rows)

                update_terminal(f'<span class="log-success">[DONE] Todas las tareas finalizadas.</span>')
                st.balloons()
                st.cache_data.clear() 
                
            except Exception as e:
                st.error(f"Error crítico: {e}")
            finally:
                if driver: driver.quit()

        # === LÓGICA DE VERIFICACIÓN (BOTÓN 2) - ACTUALIZADA CON LÍMITE DE 5 ===
        if verificar:
            driver = init_driver()
            if not driver:
                st.error("Error crítico: No se pudo iniciar Chrome Driver.")
                st.stop()
            
            logs = []
            def update_terminal(new_log_line):
                logs.append(new_log_line)
                log_content = "<br>".join(logs[-15:])
                log_placeholder.markdown(f"""
                <div class="terminal-window">
                    <div class="terminal-header">
                        <div class="terminal-dot dot-red"></div>
                        <div class="terminal-dot dot-yellow"></div>
                        <div class="terminal-dot dot-green"></div>
                    </div>
                    <div class="terminal-body">
                        {log_content}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            update_terminal(f'<span class="log-info">[BOOT]</span> Iniciando verificación GLOBAL de respuestas...')
            
            try:
                driver.get("https://web.whatsapp.com")
                update_terminal(f'<span class="log-info">[AUTH]</span> Esperando escaneo QR...')
                
                if esperar_login_qr(driver):
                    update_terminal(f'<span class="log-success">[AUTH]</span> Login exitoso.')
                    time.sleep(2)
                else:
                    update_terminal(f'<span class="log-error">[ERROR]</span> Tiempo agotado.')
                    driver.quit()
                    st.stop()

                sheet_conn, _, _ = connect_sheet()
                data = sheet_conn.get_all_values()
                df_proc = pd.DataFrame(data[1:], columns=data[0])
                df_proc.columns = df_proc.columns.str.strip()
                
                total_rows = len(df_proc)
                progress_bar = st.progress(0)
                
                count_confirmados = 0
                count_rechazos = 0

                # === CARGAMOS LISTAS PERSONALIZADAS ===
                mis_si = APP_CONFIG['keywords'].get('SI', DEFAULT_RESPUESTAS_SI)
                mis_no = APP_CONFIG['keywords'].get('NO', DEFAULT_RESPUESTAS_NO)

                for idx, row in df_proc.iterrows():
                    try: 
                        try: _ = driver.window_handles
                        except: break

                        fila = idx + 2
                        nombre = row['NOMBRE_PACIENTE']

                        # -----------------------------------------------------------
                        # 1. CONTROL DE REVISIONES (COLUMNA AA / 27)
                        # -----------------------------------------------------------
                        try:
                            val_rev = str(row.get('TOTAL_REV', '0')).strip()
                            if not val_rev.isdigit(): val_rev = '0'
                            conteo_actual = int(val_rev)
                        except:
                            conteo_actual = 0
                        
                        if conteo_actual >= 5:
                            continue 
                        # -----------------------------------------------------------

                        es_reagendamiento = str(row['CAMBIO_DE_HORA']).strip().upper() == "SI"
                        
                        if es_reagendamiento:
                            col_confirma = 26 # CONFIRMA_REAGEN
                            estado_notif = str(row['ESTADO_REA']).strip()
                            estado_actual_conf = str(row['CONFIRMA_REAGEN'])
                            fecha_target_str = row['NUEVA_FECHA'] 
                        else:
                            col_confirma = 25 # CONFIRMA_HORA
                            estado_notif = str(row['ESTADO']).strip()
                            estado_actual_conf = str(row['CONFIRMA_HORA'])
                            fecha_target_str = row['FECHA_AGENDADA']

                        dias_para_cita = calcular_dias(fecha_target_str)
                        if dias_para_cita < 0:
                            continue 
                        
                        ya_finalizado = "CONFIRMADO" in estado_actual_conf or "NO ASISTIRA" in estado_actual_conf

                        if estado_notif == "NOTIFICADO OK" and not ya_finalizado:
                            update_terminal(f'<span class="log-info">[CHECK] Revisando {nombre} (Intento {conteo_actual + 1}/5)...')
                            
                            estado_clasificacion, detalle = verificar_respuestas_wsp(driver, row['TELEFONO'], mis_si, mis_no)
                            
                            # Actualizar Contador
                            try:
                                nuevo_conteo = conteo_actual + 1
                                sheet_conn.update_cell(fila, 27, nuevo_conteo) 
                            except Exception as e_upd:
                                print(f"Error update rev: {e_upd}")

                            if estado_clasificacion == "CONFIRMADO":
                                update_terminal(f'<span class="log-success">[YES] {nombre}: "{detalle}"')
                                try:
                                    sheet_conn.update_cell(fila, col_confirma, "CONFIRMADO")
                                    count_confirmados += 1
                                except Exception as e_sheet:
                                    update_terminal(f'<span class="log-error">[SAVE ERR] {e_sheet}')
                            
                            elif estado_clasificacion == "NO ASISTIRA":
                                update_terminal(f'<span class="log-error">[NO] {nombre}: "{detalle}"')
                                try:
                                    sheet_conn.update_cell(fila, col_confirma, "NO ASISTIRA")
                                    count_rechazos += 1
                                except Exception as e_sheet:
                                    update_terminal(f'<span class="log-error">[SAVE ERR] {e_sheet}')
                                    
                            else:
                                update_terminal(f'<span class="log-info">[WAIT] {nombre}: "{detalle}"')
                            
                            time.sleep(1)

                    except Exception as e_inner:
                        update_terminal(f'<span class="log-error">[ERR] {nombre}: {str(e_inner)}</span>')
                        continue 

                    progress_bar.progress((idx + 1) / total_rows)

                update_terminal(f'<span class="log-success">[DONE] Proceso completo. {count_confirmados} Confirmados | {count_rechazos} Cancelaciones.')
                st.balloons()
                st.cache_data.clear() 
                
            except Exception as e:
                st.error(f"Error crítico: {e}")
            finally:
                if driver: driver.quit()

elif menu_option == "Base de Pacientes":
    st.markdown("""
    <div class="header-container">
        <div>
            <h1 class="header-title">Base de Pacientes</h1>
            <p class="header-subtitle">Registro maestro de citas y estados de notificación</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    col_search, col_filter = st.columns([3, 1])
    with col_search:
        search_term = st.text_input("🔎 Buscar paciente por RUT, nombre o teléfono")
    with col_filter:
        # === FILTROS ACTUALIZADOS ===
        filter_status = st.selectbox("Filtrar Estado", ["Todos", "Pendientes", "Notificados", "NO INSCRITOS (Percápita)", "Errores"])

    df_display = df.copy()
    if search_term:
        df_display = df_display[
            df_display['NOMBRE_PACIENTE'].str.contains(search_term, case=False) | 
            df_display['TELEFONO'].str.contains(search_term) |
            df_display['RUT'].str.contains(search_term) # Busqueda por RUT Agregada
        ]
    
    if filter_status == "Pendientes":
        df_display = df_display[df_display['ESTADO'] == '']
    elif filter_status == "Notificados":
        df_display = df_display[df_display['ESTADO'].str.contains('OK')]
    elif filter_status == "Errores":
        df_display = df_display[df_display['ESTADO'].str.contains('ERROR')]
    elif filter_status == "NO INSCRITOS (Percápita)":
        if 'ESTADO_PERCAPITA' in df_display.columns:
            df_display = df_display[df_display['ESTADO_PERCAPITA'] == "PENDIENTE INSCRIPCION"]

    csv = df_display.to_csv(index=False).encode('utf-8')
    st.download_button(
        label="📥 Descargar Datos Actuales (CSV)",
        data=csv,
        file_name=f"reporte_pacientes_{datetime.now().strftime('%Y%m%d')}.csv",
        mime='text/csv',
        use_container_width=True
    )

    # Configuración de columnas
    cols_config = {
        "RUT": st.column_config.TextColumn("RUT", width="medium"),
        "TELEFONO": st.column_config.TextColumn("Teléfono", width="medium"),
        "NOMBRE_PACIENTE": st.column_config.TextColumn("Paciente", width="large"),
        "EDAD_ACTUAL": st.column_config.NumberColumn("Edad"),
        "ESTADO": st.column_config.TextColumn("Estado", width="small"),
    }
    
    # Agregar columnas visuales nuevas si existen
    if 'SECTOR' in df_display.columns:
        cols_config["SECTOR"] = st.column_config.TextColumn("Sector")
    if 'ESTADO_PERCAPITA' in df_display.columns:
        cols_config["ESTADO_PERCAPITA"] = st.column_config.TextColumn("Estado Percápita", help="Basado en el último corte")

    st.dataframe(
        df_display, 
        use_container_width=True, 
        height=600,
        column_config=cols_config
    )

# --- FOOTER ---
st.markdown("---")
with st.container():
    col1, col2, col3, col4 = st.columns([3,1,5,1])
    with col2:
        # LOGO PIE DE PÁGINA (Dinámico)
        if IMG_LOGO_ALAIN:
            st.image(IMG_LOGO_ALAIN, width=150)
        else:
            st.info("Logo Dev")
            
    with col3:
        st.markdown("""
            <div style='text-align: left; color: #888888; font-size: 16px; padding-bottom: 20px;'>
                💼 Aplicación desarrollada por <strong>Alain Antinao Sepúlveda</strong> <br>
                📧 Contacto: <a href="mailto:alain.antinao.s@gmail.com" style="color: #006DB6;">alain.antinao.s@gmail.com</a> <br>
                🌐 Más información en: <a href="https://alain-antinao-s.notion.site/Alain-C-sar-Antinao-Sep-lveda-1d20a081d9a980ca9d43e283a278053e" target="_blank" style="color: #006DB6;">Mi página personal</a>
            </div>
        """, unsafe_allow_html=True)