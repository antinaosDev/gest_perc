import os
import time
import re
import glob
import calendar
import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# -------------------------------------------------------------
# CONFIGURACIÓN
# -------------------------------------------------------------
DOWNLOAD_DIR = r"D:\PROYECTOS PROGRAMACIÓN\ANTIGRAVITY_PROJECTS\descargas_percapita"
MAX_CONCURRENT_DOWNLOADS = 3 # Navegadores que se abrirán en paralelo

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

def clean_filename(text):
    return re.sub(r'[^a-zA-Z0-9_-]', '_', text.strip())

# Se eliminó generar_lista_fechas ya que ahora extraeremos las fechas reales del HTML

# Función que ejecutará CADA NAVEGADOR en paralelo
def trabajador_navegador(tarea, cookies_nav, url_destino):
    centro, fecha, n_centro, n_fecha = tarea
    
    # Importamos playwright DENTRO del hilo para que cada hilo tenga su propia instancia segura
    from playwright.sync_api import sync_playwright
    
    with sync_playwright() as p:
        # headless=True significa que estos navegadores paralelos serán "invisibles" para no molestarte visualmente
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True)
        context.add_cookies(cookies_nav) # Le pasamos tu sesión clonada
        page = context.new_page()
        
        SELECT_CENTRO = "#select_esta"
        SELECT_FECHA = "#select_CORTE" 
        BTN_DESCARGA = "input[type='submit'][value='Exportar Detalle']"
        
        try:
            # 1. Navegar directo a la URL de reportes
            page.goto(url_destino, timeout=60000)
            
            # Clicar el tab por si acaso, para que los elementos se vuelvan visibles
            try:
                page.locator("a[href='#tab_consultas_diarias']").click(force=True, timeout=2000)
            except:
                pass
                
            page.wait_for_selector(SELECT_CENTRO, state="attached", timeout=15000)
            
            # 2. Seleccionar el centro y fecha INYECTANDO JAVASCRIPT DIRECTO.
            # Esto evita el error de "Timeout" de Playwright cuando el menú está oculto en la pantalla.
            js_seleccionar = f"""() => {{
                // Asignar el centro
                let selCentro = document.querySelector('{SELECT_CENTRO}');
                if (selCentro) selCentro.value = '{centro["value"]}';
                
                // Asignar la fecha
                let selFecha = document.querySelector('{SELECT_FECHA}');
                if (selFecha) {{
                    // Si por alguna extraña razón la fecha no está en la lista de este navegador fantasma, la inyectamos
                    if (!Array.from(selFecha.options).some(o => o.value === '{fecha["value"]}')) {{
                        let opt = document.createElement("option");
                        opt.value = '{fecha["value"]}';
                        opt.text = '{fecha["label"]}';
                        selFecha.appendChild(opt);
                    }}
                    selFecha.value = '{fecha["value"]}';
                }}
            }}"""
            page.evaluate(js_seleccionar)
            time.sleep(1)
            
            # 5. Clic a descargar (con 5 minutos de paciencia máxima)
            with page.expect_download(timeout=300000) as download_info:
                page.locator(BTN_DESCARGA).click(force=True, no_wait_after=True)
                
            download = download_info.value
            
            # Extensión por defecto .csv (para estandarizar)
            ruta_guardado = os.path.join(DOWNLOAD_DIR, f"{n_centro}_{n_fecha}.csv")
            download.save_as(ruta_guardado)
            
            # Comprobar si el archivo está vacío (Fonasa a veces devuelve archivos < 500 bytes cuando no hay datos)
            if os.path.exists(ruta_guardado) and os.path.getsize(ruta_guardado) < 500:
                os.remove(ruta_guardado) # Borramos la basura
                return f"[{n_centro} | {fecha['label']}] ⏩ Sin Datos (Saltado)"
                
            return f"[{n_centro} | {fecha['label']}] ✅ OK"
            
        except Exception as e:
            err_msg = str(e).replace('\n', ' ')[:50]
            return f"[{n_centro} | {fecha['label']}] ❌ Error: {err_msg}..."
        finally:
            browser.close()

def main():
    print(f"--- DIRECTORIO DE DESCARGA: {DOWNLOAD_DIR} ---")
    
    lista_centros = []
    cookies_nav = []
    url_actual = ""
    
    # Importación principal
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("Navegando a la página principal...")
        page.goto("https://reportespercapita.fonasa.cl/welcome.php")
        
        print("\n===================================================================")
        print("Paso 1: Inicia sesión manualmente en la ventana del navegador.")
        print("===================================================================")
        
        input("\n>>> PRESIONA [ENTER] AQUÍ UNA VEZ QUE ESTÉS LOGUEADO <<<\n")
        
        print("¡Iniciando fase de captura!")
        
        SELECT_CENTRO = "#select_esta"
        SELECT_FECHA = "#select_CORTE"
        
        print("Haciendo clic automático en el menú...")
        xpaths_a_probar = [
            "/html/body/div/div/div[1]/ul/div/ul/li[2]/a",
            "/html/body/div[1]/div/div[1]/ul/div/ul/li[2]/a",
            "//ul/li[2]/a[contains(@href, '.php')]"
        ]
        for xp in xpaths_a_probar:
            try:
                page.locator(f"xpath={xp}").click(force=True, timeout=3000)
                time.sleep(4) # Esperar a que cargue la vista
                break
            except:
                continue
        
        # Buscar en TODAS las pestañas abiertas, con reintentos si falla
        pagina_correcta = None
        while True:
            # Intentar hacer clic en la pestaña interna por si están ocultos
            try:
                for pestana in context.pages:
                    pestana.locator("a[href='#tab_consultas_diarias']").click(force=True, timeout=1000)
                    time.sleep(1)
            except:
                pass
                
            for pestana in context.pages:
                try:
                    # 'attached' permite detectarlo aunque esté oculto dentro de un "tab" de Bootstrap
                    pestana.wait_for_selector(SELECT_CENTRO, state="attached", timeout=3000)
                    if pestana.locator(f"{SELECT_CENTRO} option").count() > 1:
                        pagina_correcta = pestana
                        break
                except:
                    continue
                    
            if pagina_correcta:
                break # ¡Los encontramos! Salimos del bucle
                
            print("\n❌ El script no pudo encontrar la lista de Centros automáticamente.")
            print("Quizás la página cambió o falta hacer un clic extra.")
            print("POR FAVOR:")
            print("1. Ve a la ventana del navegador.")
            print("2. Navega o haz clic en 'Consulta Certificados por Establecimientos' hasta que veas los desplegables.")
            input(">>> LUEGO PRESIONA [ENTER] AQUÍ PARA REINTENTAR LA LECTURA <<<")

        url_actual = pagina_correcta.url

        lista_fechas = []
        # Extraer Centros y Fechas reales desde la página
        try:
            print("-> Leyendo la lista de Centros...")
            opciones_esta = pagina_correcta.locator(f"{SELECT_CENTRO} option").all()
            for op in opciones_esta:
                texto = op.text_content().strip()
                valor = op.get_attribute("value")
                if valor and "selecc" not in texto.lower() and "todos" not in texto.lower() and valor != "0":
                    lista_centros.append({"value": valor, "label": texto})
                    
            print("-> Leyendo la lista de Fechas disponibles...")
            # Extraemos las fechas EXACTAS que salen en el combo, en vez de inventarlas
            opciones_fecha = pagina_correcta.locator(f"{SELECT_FECHA} option").all()
            for op in opciones_fecha:
                texto = op.text_content().strip()
                valor = op.get_attribute("value")
                if valor and "selecc" not in texto.lower() and valor != "0":
                    lista_fechas.append({"value": valor, "label": texto})
                    
        except Exception as e:
            print(f"❌ Error al extraer datos: {e}")
            input("Presiona ENTER para cerrar.")
            return

        print(f"-> Se detectaron {len(lista_centros)} establecimientos y {len(lista_fechas)} fechas.")

        print("-> Extrayendo cookies de la sesión...")
        cookies_nav = context.cookies()
        browser.close() # Cerramos el navegador "visible"

    # =========================================================
    # FASE 2: DESCARGA PARALELA (Varios navegadores invisibles)
    # =========================================================
    # (Ya tenemos lista_fechas extraída de la web, no hace falta generarla matemáticamente)

    # Filtrar tareas que ya están descargadas
    tareas_pendientes = []
    for centro in lista_centros:
        for fecha in lista_fechas:
            n_centro = clean_filename(centro['label'])
            n_fecha = clean_filename(fecha['label'])
            
            patron = os.path.join(DOWNLOAD_DIR, f"{n_centro}_{n_fecha}.*")
            if not glob.glob(patron):
                tareas_pendientes.append((centro, fecha, n_centro, n_fecha))

    print(f"\nTotal de archivos por descargar: {len(tareas_pendientes)}")
    print(f"¡INICIANDO NAVEGADORES FANTASMAS! ({MAX_CONCURRENT_DOWNLOADS} a la vez)\n")

    # Lanza las descargas en paralelo usando la función trabajador_navegador
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT_DOWNLOADS) as executor:
        # Mapeamos cada tarea al executor
        futuros = {executor.submit(trabajador_navegador, t, cookies_nav, url_actual): t for t in tareas_pendientes}
        
        for futuro in as_completed(futuros):
            print(futuro.result())

    print("\n¡PROCESO FINALIZADO CON ÉXITO!")

if __name__ == "__main__":
    main()
