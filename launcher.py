import sys
import os
import streamlit.web.cli as stcli

def resolve_path(path):
    """
    Esta función ayuda a encontrar el archivo medtify_app.py tanto si
    estamos ejecutando el script en Python normal como si estamos
    dentro del .exe compilado (sys._MEIPASS).
    """
    if getattr(sys, 'frozen', False):
        # Si estamos en el .exe, buscar en la carpeta temporal interna
        basedir = sys._MEIPASS
    else:
        # Si estamos en desarrollo, usar la ruta actual
        basedir = os.path.dirname(__file__)
    
    return os.path.join(basedir, path)

if __name__ == "__main__":
    # Buscamos tu archivo principal dentro del paquete
    app_path = resolve_path("medtify_app.py")
    
    # Simulamos el comando "streamlit run medtify_app.py"
    sys.argv = [
        "streamlit",
        "run",
        app_path,
        "--global.developmentMode=false",
    ]
    
    # Iniciamos Streamlit
    sys.exit(stcli.main())