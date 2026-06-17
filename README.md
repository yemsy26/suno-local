# Suno Local AI - Plataforma de Generación Musical Profesional

**Autor y Titular de Derechos:** Ramón Antonio Burgos Jerez  
**Licencia:** MIT License (Ver archivo `LICENSE`)  
**Versión:** 1.0.0

---

## 🎵 Descripción del Proyecto

**Suno Local AI** es una plataforma profesional para la generación local y de código abierto de música con inteligencia artificial. Está diseñada específicamente para producir canciones de alta calidad en **español latino**, respetando acentos, ritmo, y permitiendo el uso tanto de voces genéricas libres de derechos como de modelos de clonación de voz (RVC) propios.

Al ser el dueño legítimo de este proyecto y ejecutarse enteramente en arquitectura local, el autor posee el **100% de los derechos de autor** sobre el código generado, pudiendo distribuir, monetizar y publicar en plataformas musicales sin restricciones de copyright por parte del motor neuronal.

## 🚀 Novedades y Mejoras Nivel "Pro" (V1.5)

El sistema ha sido reestructurado para ofrecer un flujo de trabajo digno de un estudio discográfico, resolviendo cuellos de botella clásicos de las IAs:

- **Masterización Acústica (FFmpeg DSP):** Implementación de compresión de bus (*Glue Compressor* / Falso Sidechain) para amalgamar la voz con la pista. Se ha inyectado un Ecualizador de Presencia a 4000Hz para devolver el brillo y dicción a las consonantes (R/S) perdidas durante la clonación RVC, y se usa un Headroom de -15 LUFS para erradicar el *clipping* (saturación).
- **Aceleración Extrema (GPU y RAM):** Reducción quirúrgica de pasos de difusión (de 50 a 35) reduciendo un 30% el consumo de GPU. Además, soporta **Discos en Memoria RAM** nativos (vía ImDisk) para procesar terabytes de audio a la velocidad de la electricidad sin desgastar el disco duro.
- **Dicción Española Pura:** Se utiliza el motor **DiffRhythm** emparejado con `espeak-ng` como fonemizador, forzando la pronunciación de vocales latinas perfectas, evitando el "acento gringo" de otros modelos generativos.
- **Escritor Billboard Integrado:** Ollama ha sido condicionado para escupir letras comerciales: bloquea onomatopeyas gringas ("Wao", "Yeah"), fuerza métricas cortas (6-8 sílabas), y exige duraciones exactas de 3.5 minutos (~250 palabras). El sistema además mutila automáticamente las muletillas de la IA ("Aquí tienes tu canción:").
- **Respaldo Legal Automático:** Cada canción genera un `CERTIFICADO_LEGAL.md` con huellas criptográficas y stems aislados (`beat.wav`, `vocals.wav`), sirviendo como prueba irrefutable de autoría humana/local frente a las distribuidoras musicales.

## 🏗️ Arquitectura y Carpetas (Inspección de Sistema)

- `orchestrator.py`: El "Cerebro Central". Coordina el motor musical, la separación UVR5, clonación RVC y el Rack de Masterización de FFmpeg.
- `api.py`: El servidor backend (FastAPI) que filtra los inputs del usuario, extrae las letras puras del LLM y lanza el Pipeline.
- `audio_analyzer.py`: **Auditor de Calidad.** Revisa automáticamente cada canción generada (mide BPM y métricas vocales).
- `montar_ramdisk.bat`: Herramienta inyectora que crea un disco virtual `Z:\` en tu memoria RAM (requiere ImDisk).
- `models/`: Directorio donde residen los pesos neuronales (UVR5, DeepFilterNet).
- `gallery/`: Almacenamiento maestro. Aquí se deposita la canción final, los stems separados y el certificado legal.

---

## 🛠️ Instrucciones de Instalación

### Requisitos Previos (Para Windows y Linux)
- **Python 3.10 o 3.11** instalado y agregado al PATH.
- **Git** instalado.
- Tarjeta Gráfica NVIDIA con al menos 8GB de VRAM. (Recomendado RTX 3060/4060 o superior).
- **FFmpeg** instalado y agregado al PATH.
- *(Opcional pero Recomendado en Windows)*: **ImDisk Toolkit** instalado para habilitar el Disco RAM de ultra velocidad.

### Instalación en Windows
1. Clona o descarga este repositorio en tu disco duro.
2. **(Aceleración RAM):** Ejecuta `montar_ramdisk.bat` como Administrador para montar el disco virtual `Z:\`. *Haz esto siempre antes de iniciar el servidor*.
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
2. Instala FFmpeg a nivel sistema y Espeak:
   ```bash
   sudo apt update
   sudo apt install ffmpeg espeak-ng
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
5. *(Opcional)* Crea un RAM Disk nativo en Linux (tmpfs):
   ```bash
   sudo mount -t tmpfs -o size=4G tmpfs /mnt/ramdisk
   # Luego debes editar config.json y apuntar temp_dir a "/mnt/ramdisk"
   ```
6. Descarga los modelos de Inteligencia Artificial:
   ```bash
   python download_models.py
   ```
7. Inicia el servidor maestro:
   ```bash
   uvicorn api:app --host 0.0.0.0 --port 8765
   ```
8. Accede a través de tu navegador local en `http://localhost:8765/ui/index.html`.

---

## ⚖️ Declaración Legal de Uso
Este software y las piezas musicales que genera son de autoría exclusiva de **Ramón Antonio Burgos Jerez**. El sistema certifica criptográficamente el proceso de creación local para proteger la inversión financiera y de tiempo en plataformas de distribución profesional (Spotify, Apple Music). El titular posee el 100% de los derechos de monetización y publishing.
