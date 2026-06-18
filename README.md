# Suno Local AI - Plataforma de Generación Musical Profesional (V2.1)

**Autor y Titular de Derechos:** Ramón Antonio Burgos Jerez  
**Licencia:** MIT License (Ver archivo `LICENSE`)  
**Versión:** 2.1.0 (Professional Edition - Stable)

---

## 🎵 Descripción del Proyecto

**Suno Local AI** es una plataforma profesional para la generación local y de código abierto de música con inteligencia artificial. Está diseñada específicamente para producir canciones de alta calidad en **español latino puro**, respetando acentos, fluidez natural y permitiendo el uso tanto de voces genéricas como de modelos de clonación de voz (RVC) propios.

Al ser el dueño legítimo de este proyecto y ejecutarse enteramente en arquitectura local, el autor posee el **100% de los derechos de autor** sobre el código generado, pudiendo distribuir, monetizar y publicar en plataformas musicales sin restricciones de copyright por parte del motor neuronal.

## 🚀 Novedades y Mejoras Nivel "Pro" (V2.1)

El sistema ha sido purgado de viejos códigos y parches ("hacks" fonéticos), y reestructurado para ofrecer un flujo de trabajo digno de un estudio discográfico:

- **Motor Generativo ACE-Step 1.5 Nativo:** Reemplazo total de motores antiguos (DiffRhythm/YuE). Generación musical con dicción española impecable y natural sin necesidad de conversiones fonéticas artificiales ni pérdida de VRAM.
- **Inteligencia Artificial de Letras Mejorada:** El creador de letras interno (Ollama/Phi) ahora incluye una sanitización rigurosa impulsada por Python que garantiza la estructura musical inglesa estricta (`[Verse 1]`, `[Chorus]`, `[Instrumental Outro]`), y bloquea que la IA repita las instrucciones ("semilla") robóticamente en la canción.
- **Clonación Vocal Fluida y Equitativa (RVC rmvpe):** Mapeo perfecto desde la interfaz UI hacia el backend, con instrucciones emocionales igualadas tanto para Hombre como para Mujer (`"highly expressive vocals, passionate, emotional"`). Utiliza el algoritmo avanzado de extracción de tono `rmvpe` (con protección 0.5) para evitar cortes silábicos en agudos.
- **UI/UX Profesional:** Sistema de progresión interactivo en el frontend. Al finalizar una generación, el sistema habilita un botón dinámico para limpiar la pantalla e iniciar una nueva composición instantáneamente sin necesidad de refrescar la página entera.
- **Masterización Acústica (FFmpeg DSP):** Implementación de compresión de bus (*Glue Compressor*) para amalgamar la voz con la pista. Se ha inyectado un Ecualizador de Presencia a 4000Hz para devolver el brillo y dicción a las consonantes perdidas durante la clonación RVC.
- **Gestión Avanzada de VRAM (Offloading):** Diseñado para operar en GPUs comerciales (ej. RTX 4060 8GB). Transfiere inteligentemente componentes del modelo (DiT y vocoders) a la memoria RAM de CPU durante generaciones largas (hasta 3.5 minutos continuos) para evitar errores OOM (Out Of Memory).
- **Control Inteligente de Duración (3.0 - 3.5 min):** El sistema calcula dinámicamente la duración de la canción en base a la longitud de la letra, asegurando estructuras musicales completas y comerciales estándar (180s - 210s) con Intros instrumentales automatizadas.
- **Respaldo Legal Automático:** Cada canción genera un `CERTIFICADO_LEGAL.md` con huellas y stems aislados (`beat.wav`, `vocals.wav`), sirviendo como prueba irrefutable de autoría humana/local frente a las distribuidoras musicales.

## 🏗️ Arquitectura y Carpetas (Inspección de Sistema)

- `orchestrator.py`: El "Cerebro Central". Coordina el motor musical ACE-Step 1.5, la separación UVR5, clonación RVC y el Rack de Masterización de FFmpeg.
- `ace_step_15_wrapper.py`: Capa de seguridad y aislamiento de memoria. Invoca el motor neuronal liberando VRAM de forma eficiente entre cada subproceso.
- `api.py`: El servidor backend (FastAPI) que filtra los inputs del usuario, extrae las letras puras del LLM y lanza el Pipeline.
- `audio_analyzer.py`: **Auditor de Calidad.** Revisa automáticamente cada canción generada (mide BPM y métricas vocales).
- `models/`: Directorio donde residen los pesos neuronales (ACE-Step, UVR5, DeepFilterNet).
- `gallery/`: Almacenamiento maestro. Aquí se deposita la canción final, los stems separados y el certificado legal.

---

## 🛠️ Instrucciones de Instalación

### Requisitos Previos (Para Windows y Linux)
- **Python 3.10 o 3.11** instalado y agregado al PATH.
- **Git** instalado.
- Tarjeta Gráfica NVIDIA con al menos 8GB de VRAM. (Recomendado RTX 3060/4060 o superior).
- **FFmpeg** instalado y agregado al PATH.

### Instalación en Windows
1. Clona o descarga este repositorio en tu disco duro.
2. Ejecuta el archivo `setup_y_descargar.bat` haciendo doble clic.
   * *Este script creará un entorno virtual aislado, instalará las dependencias necesarias de `requirements.txt` y descargará los modelos de IA pesados.*
3. Una vez completada la instalación, ejecuta `iniciar.bat`.
4. Abre tu navegador y dirígete a `http://localhost:8765/ui/index.html` para usar la plataforma.

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
Este software y las piezas musicales que genera son de autoría exclusiva de **Ramón Antonio Burgos Jerez**. El sistema certifica criptográficamente el proceso de creación local para proteger la inversión financiera y de tiempo en plataformas de distribución profesional (Spotify, Apple Music). El titular posee el 100% de los derechos de monetización y publishing.
