# Suno Local - Open Source AI Music Studio (v2.1 Stable)

**Autor y Titular de Derechos:** Ramón Antonio Burgos Jerez  
**Licencia:** MIT License (Ver archivo `LICENSE`)  
**Versión:** 2.1.0 (Professional Edition)

---

## 🎵 Descripción del Proyecto

**Suno Local** es una plataforma integral de grado profesional para la composición, producción y masterización de música generada por Inteligencia Artificial de forma **100% local**. Está diseñada para operar de forma óptima en GPUs comerciales (mínimo 8GB VRAM) y destaca por su capacidad nativa para componer canciones con **letras y voces en español**, evitando los tradicionales acentos robóticos o la necesidad de traducciones fonéticas (hacks).

El software otorga total soberanía sobre la creación musical. Al ejecutarse localmente y utilizar motores Open Source, el creador retiene el **100% de los derechos comerciales** (publishing y master) para su libre distribución y monetización en plataformas de streaming (Spotify, Apple Music, YouTube).

## 🚀 Características y Pipeline de Producción

El núcleo del sistema integra una cadena de procesamiento (Pipeline) que replica el flujo de un estudio de grabación profesional:

1. **Inteligencia de Letras (LLM):** Motor de composición lírica asistida. Sanitiza, estructura (Verso, Coro, Puente) y adapta el "prompt" del usuario para el motor musical.
2. **Motor Generativo Text-to-Music (ACE-Step 1.5):** Utiliza un modelo de lenguaje de 1.7B parámetros y un modelo de difusión (DiT) turbo (8 pasos). Genera hasta 3.5 minutos continuos de música instrumental y vocal simultánea. Posee directrices estrictas de entonación y energía para asegurar un rendimiento humano.
3. **Separación Acústica de Alta Fidelidad (UVR5 / BS-Roformer):** Extrae la voz de la base instrumental generada utilizando el modelo `BS-Roformer` (SDR ~12.97), considerado el estándar actual en separación de stems.
4. **Purificación Vocal (DeepFilterNet 3):** Reduce el piso de ruido y limpia transitorios indeseados en la capa vocal con una atenuación quirúrgica.
5. **Clonación Vocal Dinámica (RVC v2):** Permite re-grabar la voz extraída utilizando modelos de voz personalizados, impulsado por el algoritmo avanzado de extracción de tono `rmvpe`.
6. **Masterización DSP Automatizada (FFmpeg):** Una vez procesada la voz, el sistema mezcla ambos stems (Base + Voz) empleando compresión niveladora suave, EQ analógico emulado, atenuadores de graves cruzados y un limitador `loudnorm` calibrado a **-13 LUFS** para cumplir con los estándares de streaming comercial.

## 🏗️ Arquitectura del Sistema

* `orchestrator.py`: Motor central. Controla la lógica secuencial (ACE-Step -> UVR5 -> RVC -> FFmpeg).
* `ace_step_15_wrapper.py`: Capa de aislamiento de VRAM. Ejecuta el motor ACE-Step en un subproceso para garantizar la liberación de memoria en GPUs de 8GB.
* `api.py`: Servidor backend (FastAPI) que provee la interfaz asíncrona para la cola de tareas (Jobs).
* `frontend/`: Aplicación web moderna (HTML/JS/CSS) que ofrece una experiencia de usuario interactiva y fluida.
* `gallery.db`: Base de datos SQLite que administra el catálogo musical generado.
* `gallery/`: Directorio de almacenamiento definitivo. Por cada composición, guarda:
  * Archivo máster final (`.wav`).
  * Archivo de base instrumental aislada.
  * Archivo de voz limpia aislada.
  * `CERTIFICADO_LEGAL.md`: Documento criptográfico local que avala la autoría humana del diseño y el uso de la infraestructura.

## 🛠️ Instrucciones de Instalación (Windows)

### Requisitos Previos
* **Sistema Operativo:** Windows 10/11.
* **Hardware:** GPU NVIDIA con al menos 8GB de VRAM (Serie RTX 3000 o superior recomendada).
* **Software:**
  * [Python 3.10 o 3.11](https://www.python.org/downloads/) instalado y agregado al PATH.
  * [Git](https://git-scm.com/) instalado.
  * [FFmpeg](https://ffmpeg.org/) instalado y agregado al PATH del sistema.

### Pasos de Instalación
1. Clona este repositorio en tu disco local:
   ```cmd
   git clone https://github.com/yemsy26/suno-local.git
   cd suno-local
   ```
2. Ejecuta el instalador automático:
   ```cmd
   setup_y_descargar.bat
   ```
   *Este script inicializará un entorno virtual (venv), instalará las dependencias necesarias (`requirements.txt`), y descargará los pesos de los modelos de IA.*

### Uso de la Plataforma
1. Para iniciar el servidor y los motores neuronales, simplemente ejecuta:
   ```cmd
   iniciar.bat
   ```
2. El sistema confirmará que el entorno virtual y el backend están operativos.
3. Abre tu navegador web favorito y navega hacia:  
   **`http://localhost:8765/ui/index.html`**

## ⚖️ Declaración Legal y Derechos
El autor, **Ramón Antonio Burgos Jerez**, diseñó e integró la lógica de orquestación, el motor de masterización DSP y el frontend de usuario. Todo el código alojado en este repositorio está cobijado bajo la **Licencia MIT**. Las piezas musicales producidas localmente a través de este software no están sujetas a regalías de terceros y pueden comercializarse de forma independiente.
