# Suno Local AI - Plataforma de Generación Musical Profesional

**Autor y Titular de Derechos:** Ramón Antonio Burgos Jerez  
**Licencia:** MIT License (Ver archivo `LICENSE`)  
**Versión:** 1.0.0

---

## 🎵 Descripción del Proyecto

**Suno Local AI** es una plataforma profesional para la generación local y de código abierto de música con inteligencia artificial. Está diseñada específicamente para producir canciones de alta calidad en **español latino**, respetando acentos, ritmo, y permitiendo el uso tanto de voces genéricas libres de derechos como de modelos de clonación de voz (RVC) propios.

Al ser el dueño legítimo de este proyecto y ejecutarse enteramente en arquitectura local, el autor posee el **100% de los derechos de autor** sobre el código generado, pudiendo distribuir, monetizar y publicar en plataformas musicales sin restricciones de copyright por parte del motor neuronal.

## 🏗️ Arquitectura y Carpetas (Inspección de Sistema)

El proyecto cuenta con una estructura modular profesional, separando el backend de Inteligencia Artificial del frontend y de los modelos locales.

- `orchestrator.py`: El "Cerebro Central". Coordina el motor musical, la separación de pistas, limpieza y clonación RVC.
- `api.py`: El servidor backend (FastAPI) que interconecta la inteligencia artificial con la interfaz visual.
- `audio_analyzer.py`: **Auditor de Calidad.** Sistema analítico que revisa automáticamente cada canción generada (mide BPM, tiempos de silencio, métricas vocales).
- `frontend/`: Interfaz gráfica web interactiva para escribir letras y gestionar la cola de generación.
- `ace_step_repo/`: Motor neuronal principal de música (Generación Difusiva) parcheado para español perfecto.
- `models/`: Directorio donde residen los pesos neuronales (UVR5, DeepFilterNet).
- `rvc/` y `rvc_cli/`: Módulos de clonación de voz para mapear la voz entrenada de Ramón Antonio Burgos Jerez (o sintéticas).
- `gallery/` y `gallery.db`: Sistema de base de datos y almacenamiento de todas las canciones terminadas.

---

## 🛠️ Instrucciones de Instalación

### Requisitos Previos (Para Windows y Linux)
- **Python 3.10 o 3.11** instalado y agregado al PATH.
- **Git** instalado.
- Tarjeta Gráfica NVIDIA con al menos 8GB de VRAM. (Recomendado RTX 3060/4060 o superior).
- **FFmpeg** instalado y agregado al PATH (En Windows, los ejecutables ya vienen pre-empaquetados en la raíz).

### Instalación en Windows
1. Clona o descarga este repositorio en tu disco duro.
2. Abre la carpeta del proyecto.
3. Ejecuta el archivo `setup_y_descargar.bat` haciendo doble clic.
   * *Este script creará un entorno virtual aislado, instalará las dependencias necesarias de `requirements.txt` y descargará los modelos de IA pesados.*
4. Una vez completada la instalación, ejecuta `iniciar.bat`.
5. Abre tu navegador y dirígete a `http://localhost:8765/ui/index.html` para usar la plataforma.

### Instalación en Linux (Ubuntu/Debian)
1. Clona el repositorio y entra al directorio:
   ```bash
   git clone https://github.com/yemsy26/suno-local.git
   cd suno-local
   ```
2. Instala FFmpeg a nivel sistema:
   ```bash
   sudo apt update
   sudo apt install ffmpeg
   ```
3. Crea y activa un entorno virtual de Python:
   ```bash
   python3 -m venv .venv_py311
   source .venv_py311/bin/activate
   ```
4. Instala las dependencias y PyTorch con soporte CUDA:
   ```bash
   pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
   pip install -r requirements.txt
   ```
5. Descarga los modelos de Inteligencia Artificial:
   ```bash
   python download_models.py
   ```
6. Inicia el servidor maestro:
   ```bash
   uvicorn api:app --host 0.0.0.0 --port 8765
   ```
7. Accede a través de tu navegador local en `http://localhost:8765/ui/index.html`.

---

## ⚖️ Declaración Legal de Uso
Este software y las piezas musicales que genera son de autoría exclusiva. Todas las arquitecturas subyacentes operan con pesos de código abierto bajo sus respectivas licencias permisivas. El titular de la música generada bajo esta instancia tiene pleno derecho para uso comercial.
