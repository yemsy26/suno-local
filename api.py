"""
api.py
Servidor FastAPI - Puente entre el frontend y el orquestador Python.

Endpoints:
  POST /generate          -> Lanza un job de generacion musical (async)
  POST /remaster          -> Ruta 2: remasteriza audio existente con RVC
  POST /repair            -> Ruta 3: limpia audio con DeepFilterNet
  GET  /jobs/{job_id}     -> Estado actual de un job
  GET  /jobs/{job_id}/stream -> Stream SSE con logs en tiempo real
  POST /jobs/{job_id}/abort  -> Aborta un job en curso
  GET  /gallery           -> Lista de canciones guardadas
  GET  /gallery/{id}      -> Metadatos de una cancion especifica
  GET  /gallery/{id}/download -> Descarga el WAV de una cancion
  DELETE /gallery/{id}    -> Elimina una cancion de la galeria
  PUT /gallery/{id}       -> Renombra una cancion
  GET  /audio/{job_id}    -> Sirve el WAV de salida de un job
  POST /generate_lyrics   -> Genera letra con Ollama
  GET  /api/voices        -> Lista modelos RVC disponibles
  GET  /health            -> Estado del servidor y GPU
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Optional

import torch
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from gallery_db import GalleryDB
from orchestrator import (
    MusicGenerationPipeline,
    PipelineConfig,
    PipelineState,
    load_config,
    log as orch_log,
)

# ──────────────────────────────────────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────────────────────────────────────

log = logging.getLogger("api")

# ──────────────────────────────────────────────────────────────────────────────
# Estado global de jobs
# ──────────────────────────────────────────────────────────────────────────────

_jobs: dict   = {}
_config: PipelineConfig = PipelineConfig()

# ──────────────────────────────────────────────────────────────────────────────
# Schemas Pydantic
# ──────────────────────────────────────────────────────────────────────────────

class LyricsResponse(BaseModel):
    lyrics: str
    style: Optional[str] = None
    title: Optional[str] = None


class JobStatus(BaseModel):
    job_id: str
    stage: str
    prompt: str
    errors: list
    timings: dict
    output_path: Optional[str] = None
    created_at: str


class RenameRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=100)


# ──────────────────────────────────────────────────────────────────────────────
# Queue Handler para SSE
# ──────────────────────────────────────────────────────────────────────────────

class _QueueHandler(logging.Handler):
    """Redirige mensajes de log a una asyncio.Queue para SSE streaming."""

    def __init__(self, queue: asyncio.Queue):
        super().__init__()
        self._queue = queue
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    def emit(self, record: logging.LogRecord) -> None:
        msg = self.format(record)
        if self._loop and not self._loop.is_closed():
            asyncio.run_coroutine_threadsafe(self._queue.put(msg), self._loop)


# ──────────────────────────────────────────────────────────────────────────────
# Funciones de thread para cada ruta
# ──────────────────────────────────────────────────────────────────────────────

def _run_generation_thread(
    job_id: str,
    state: PipelineState,
    config: PipelineConfig,
    log_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    db: GalleryDB,
) -> None:
    """Thread para generacion completa (Ruta 1)."""
    handler = _QueueHandler(log_queue)
    handler.set_loop(loop)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    )
    orch_log.addHandler(handler)

    try:
        pipeline = MusicGenerationPipeline(config)
        result   = pipeline.run_generation(state)
        _jobs[job_id]["state"] = result

        if result.stage == "COMPLETED" and result.output_path:
            title = _jobs[job_id].get("title", "Nueva Canción")
            db.insert_track(
                job_id=job_id,
                title=title,
                prompt=state.prompt,
                output_path=str(result.output_path),
                metadata={"voice_model": Path(config.rvc_model_path).stem if config.rvc_model_path else "Ninguno"},
                timings=result.timings,
            )
            log.info(f"[API] Job {job_id} guardado en galeria: {result.output_path}")

    except Exception as exc:
        log.error(f"[API] Error critico en job {job_id}: {exc}")
        if job_id in _jobs:
            _jobs[job_id]["state"].stage = "FAILED"
            _jobs[job_id]["state"].errors.append(str(exc))
    finally:
        orch_log.removeHandler(handler)
        asyncio.run_coroutine_threadsafe(log_queue.put("__END__"), loop)


def _run_remaster_thread(
    job_id: str,
    audio_input_path: str,
    config: PipelineConfig,
    log_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    db: GalleryDB,
) -> None:
    """Thread para remasterizacion (Ruta 2)."""
    handler = _QueueHandler(log_queue)
    handler.set_loop(loop)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    )
    orch_log.addHandler(handler)

    try:
        pipeline      = MusicGenerationPipeline(config)
        initial_state = _jobs[job_id]["state"]
        result: PipelineState = pipeline.run_remaster(
            audio_input_path=audio_input_path,
            job_id=job_id,
            initial_state=initial_state,
        )
        _jobs[job_id]["state"] = result

        if result.stage == "COMPLETED" and result.output_path:
            db.insert_track(
                job_id=job_id,
                title=result.prompt,
                prompt=result.prompt,
                output_path=str(result.output_path),
                metadata={"voice_model": Path(config.rvc_model_path).stem if config.rvc_model_path else "Ninguno"},
                timings=result.timings,
            )
            log.info(f"[API] Remaster {job_id} guardado en galeria: {result.output_path}")

    except Exception as exc:
        log.error(f"[API] Error critico en remaster {job_id}: {exc}")
        if job_id in _jobs:
            _jobs[job_id].setdefault("state", PipelineState(job_id=job_id, prompt="[REMASTER]"))
            _jobs[job_id]["state"].stage = "FAILED"
            _jobs[job_id]["state"].errors.append(str(exc))
    finally:
        orch_log.removeHandler(handler)
        asyncio.run_coroutine_threadsafe(log_queue.put("__END__"), loop)


def _run_repair_thread(
    job_id: str,
    audio_input_path: str,
    config: PipelineConfig,
    log_queue: asyncio.Queue,
    loop: asyncio.AbstractEventLoop,
    db: GalleryDB,
    initial_state: PipelineState,
) -> None:
    """Thread para reparacion/limpieza (Ruta 3)."""
    handler = _QueueHandler(log_queue)
    handler.set_loop(loop)
    handler.setFormatter(
        logging.Formatter("%(asctime)s | %(levelname)-8s | %(message)s", datefmt="%H:%M:%S")
    )
    orch_log.addHandler(handler)

    try:
        pipeline = MusicGenerationPipeline(config)
        result   = pipeline.run_repair(audio_input_path, job_id, initial_state)
        _jobs[job_id]["state"] = result

        if result.stage == "COMPLETED" and result.output_path:
            db.insert_track(
                job_id=job_id,
                title=result.prompt,
                prompt=result.prompt,
                output_path=str(result.output_path),
                metadata={"voice_model": "REPAIR_ONLY"},
                timings=result.timings,
            )
    except Exception as e:
        log.error(f"[API] Repair failed: {e}")
        if job_id in _jobs:
            _jobs[job_id]["state"].stage = "FAILED"
            _jobs[job_id]["state"].errors.append(str(e))
    finally:
        orch_log.removeHandler(handler)
        asyncio.run_coroutine_threadsafe(log_queue.put("__END__"), loop)


# ──────────────────────────────────────────────────────────────────────────────
# DB y Lifespan
# ──────────────────────────────────────────────────────────────────────────────

db = GalleryDB()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _config
    _config = load_config("config.json")
    
    # C3: Validar temp_dir y hacer fallback si no existe (e.g. RAM disk Z:/ no montada)
    temp_path = Path(_config.temp_dir)
    if not temp_path.exists() or str(_config.temp_dir).startswith("Z:"):
        fallback = Path("temp")
        fallback.mkdir(exist_ok=True)
        _config.temp_dir = str(fallback)
        log.warning(f"[CONFIG] temp_dir '{temp_path}' inaccesible. Usando fallback: '{fallback.absolute()}'")
    
    db.init()
    log.info("[API] Servidor iniciado. Config y DB listos.")
    yield
    db.close()  # M10: Cerrar conexión SQLite limpiamente (hace checkpoint del WAL)
    log.info("[API] Servidor detenido.")


# ──────────────────────────────────────────────────────────────────────────────
# App FastAPI
# ──────────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Suno-Local API",
    description="Backend de generacion musical local con IA",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_FRONTEND_DIR = Path(__file__).parent / "frontend"
if _FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(_FRONTEND_DIR), html=True), name="frontend")
    log.info(f"[API] Frontend estatico montado en /ui -> {_FRONTEND_DIR}")
else:
    log.warning(f"[API] Directorio frontend no encontrado: {_FRONTEND_DIR}")


# ──────────────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────────────

@app.get("/", include_in_schema=False)
async def root_redirect():
    return RedirectResponse(url="/ui/index.html")


@app.get("/health")
async def health():
    """Estado del servidor y disponibilidad de GPU."""
    cuda = torch.cuda.is_available()
    gpu_info = {}
    if cuda:
        props = torch.cuda.get_device_properties(0)
        gpu_info = {
            "name":              props.name,
            "vram_total_mb":     round(props.total_memory / (1024 ** 2)),
            "vram_allocated_mb": round(torch.cuda.memory_allocated() / (1024 ** 2), 1),
            "vram_reserved_mb":  round(torch.cuda.memory_reserved()  / (1024 ** 2), 1),
        }
    return {
        "status":       "ok",
        "cuda_available": cuda,
        "gpu":          gpu_info,
        "active_jobs":  len([j for j in _jobs.values()
                             if j.get("state") and
                             j["state"].stage not in ("COMPLETED", "FAILED", "ABORTED")]),
        "timestamp":    datetime.utcnow().isoformat(),
    }


@app.get("/api/voices")
async def get_voices():
    """Escanea el directorio de modelos RVC y retorna los disponibles."""
    rvc_dir = Path("models/rvc")
    voices  = []
    if rvc_dir.exists():
        for pth_file in rvc_dir.rglob("*.pth"):
            index_file = pth_file.with_suffix(".index")
            voices.append({
                "name":        pth_file.stem,
                "model_path":  str(pth_file).replace("\\", "/"),
                "index_path":  str(index_file).replace("\\", "/") if index_file.exists() else "",
            })
    return {"voices": voices}


@app.post("/generate_lyrics")
async def generate_lyrics_api(
    topic: str = Form(...),
    style: Optional[str] = Form(None)
):
    """Llama a Ollama localmente para generar una letra basada en el tema y el estilo."""
    import httpx

    style_instruction = ""
    persona = "Eres un compositor poético y galardonado."
    regla_de_oro = "Regla de oro: Escribe una historia metafórica. Por favor NO escribas la frase del tema literalmente dentro de la canción."
    
    if style:
        s_lower = style.lower()
        if "corrido" in s_lower or "tumbado" in s_lower or "bélico" in s_lower:
            persona = "Eres un compositor de Corridos Tumbados y regional mexicano."
            regla_de_oro = "Regla de oro: Escribe un corrido AUTÉNTICO. Usa lenguaje coloquial del norte de México y la calle. NO uses metáforas románticas o poéticas como 'el cielo llora' o 'valle del silencio'. Sé directo."
            style_instruction = (
                f"El género musical de esta canción es: '{style}'.\n"
                "ADAPTA LA LETRA ESTRICTAMENTE A ESTE GÉNERO:\n"
                "- Usa palabras como: 'compa', 'tierra', 'jefe', 'destino'.\n"
                "- Las estrofas deben tener 4 versos cortos (ritmo rápido).\n\n"
            )
        elif "reggaeton" in s_lower or "reggaetón" in s_lower or "urbano" in s_lower or "dembow" in s_lower or "perreo" in s_lower:
            persona = "Eres un exitoso artista de Reggaetón y música urbana latina."
            regla_de_oro = "Regla de oro: Escribe con flow callejero y ritmo urbano. NO uses poesía clásica ni baladas tristes."
            style_instruction = (
                f"El género musical de esta canción es: '{style}'.\n"
                "ADAPTA LA LETRA ESTRICTAMENTE A ESTE GÉNERO:\n"
                "- Usa palabras muy cortas, frases rítmicas de 4 a 8 sílabas, vocabulario de fiesta o calle.\n\n"
            )
        else:
            style_instruction = (
                f"El género musical de esta canción es: '{style}'.\n"
                "ADAPTA LA LETRA ESTRICTAMENTE A ESTE GÉNERO:\n"
                "- Si es rápido: Usa palabras cortas y rítmicas.\n"
                "- Si es lento o romántico: Usa frases más largas, poéticas y emocionales.\n"
                "- Si es tropical: Usa un tono alegre y coros pegadizos.\n\n"
            )

    # Etiquetas estructurales por género
    if "reggaet" in style.lower() or "urbano" in style.lower() or "trap" in style.lower() or "electr" in style.lower():
        estructuras = "[Verse 1], [Chorus], [Verse 2], [Chorus], [Bridge], [Beat Drop], [Verse 3], [Chorus]"
        etiquetas_permitidas = "[Verse 1], [Verse 2], [Verse 3], [Chorus], [Bridge], [Beat Drop]"
    else:
        estructuras = "[Verse 1], [Chorus], [Verse 2], [Chorus], [Bridge], [Guitar Solo], [Verse 3], [Chorus]"
        etiquetas_permitidas = "[Verse 1], [Verse 2], [Verse 3], [Chorus], [Bridge], [Guitar Solo]"

    prompt = (
        f"{persona}\n\n"
        f"Tema para inspirarte: {topic}\n"
        f"{regla_de_oro}\n\n"
        f"{style_instruction}"
        "REGLAS:\n"
        f"1. Estructura Larga (Mínimo 3 Minutos): Para que la canción alcance los 3 minutos sin hacer pausas muertas, DEBES escribir una letra MUY LARGA (mínimo 200 palabras). INICIA con [Short Instrumental Intro]. Usa obligatoriamente {estructuras}. TERMINA con [Instrumental Outro].\n"
        f"2. ETIQUETAS MUSICALES: Usa SOLO estas etiquetas exactas en inglés: {etiquetas_permitidas}. Está prohibido inventar otras (NO uses [Número Uno] ni [Verso Dos]).\n"
        "3. Calidad: Escribe en español nativo con rimas naturales (AABB, ABAB). Adáptate al tono de la 'Regla de oro'.\n"
        "4. Ritmo: Usa frases cortas para que la música respire.\n"
        "5. Formato: Devuelve ÚNICAMENTE la letra, sin hablar conmigo ni incluir título."
    )

    config = _config  # I1: Reutilizar _config global en lugar de crear uno nuevo por petición
    model  = config.ollama_model if config.ollama_model else "llama3"

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            # Paso 1: Generar la letra pura
            resp_lyrics = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model, 
                    "prompt": prompt, 
                    "stream": False,
                    "options": {"num_predict": 2048}
                }
            )
            resp_lyrics.raise_for_status()
            raw_lyrics = resp_lyrics.json()["response"].strip()
            
            # Soporte para modelos de razonamiento (como DeepSeek-R1): Eliminar bloques <think>
            import re
            raw_lyrics = re.sub(r'<think>.*?</think>', '', raw_lyrics, flags=re.DOTALL).strip()
            
            # Limpieza básica por si Ollama introdujo algo de texto antes de la letra
            if "[" in raw_lyrics:
                raw_lyrics = raw_lyrics[raw_lyrics.find("["):]
                
            # Limpieza brutal con Python para forzar gramática donde los LLMs pequeños fallan
            raw_lyrics = raw_lyrics.replace("sin tú", "sin ti").replace("con ti", "contigo").replace("Sin tú", "Sin ti").replace("Con ti", "Contigo")
            
            # Limpieza brutal para que no repita el tema literalmente (lo reemplaza por 'esta pena' para no romper la oración)
            if topic.lower() in raw_lyrics.lower():
                raw_lyrics = re.sub(re.escape(topic), "esta pena", raw_lyrics, flags=re.IGNORECASE)
            
            # Forzar las etiquetas estructurales a INGLÉS estricto para que ACE-Step no las cante
            raw_lyrics = re.sub(r'(?i)\[verso\s*(\d+)?\]', r'[Verse \1]', raw_lyrics).replace('[Verse ]', '[Verse]')
            raw_lyrics = re.sub(r'(?i)\[verso\s*uno\]', '[Verse 1]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[verso\s*dos\]', '[Verse 2]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[verso\s*tres\]', '[Verse 3]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[número\s*.*?\]', '[Verse]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[coro\]', '[Chorus]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[estribillo\]', '[Chorus]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[refren\]', '[Chorus]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[puente\]', '[Bridge]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[instrumental intro\]', '[Instrumental Intro]', raw_lyrics)
            raw_lyrics = re.sub(r'(?i)\[instrumental outro\]', '[Instrumental Outro]', raw_lyrics)
            
            # Limpieza de etiquetas falsas (Ej: [Nado con estrellas...])
            # Si el corchete tiene más de 3 palabras, no es una etiqueta estructural, cambiar a paréntesis.
            def sanitize_brackets(match):
                content = match.group(1)
                # Si no es una etiqueta permitida y es muy larga, la neutralizamos
                if len(content.split()) >= 3 and "instrumental" not in content.lower() and "verse" not in content.lower():
                    return f"({content})"
                return match.group(0)
            raw_lyrics = re.sub(r'\[([^\]]+)\]', sanitize_brackets, raw_lyrics)
            
            # Asegurar que siempre termine con Instrumental Outro
            if "[Instrumental Outro]" not in raw_lyrics:
                raw_lyrics += "\n\n[Instrumental Outro]"

            # Paso 2: Generar el título profesional basado en la letra generada
            title_prompt = (
                "Eres un experto en marketing musical. Lee la siguiente letra de canción y crea un título súper pegadizo, "
                "comercial y NATURAL en ESPAÑOL (máximo 4 palabras). No uses listas de palabras raras, crea un título poético y real.\n"
                "IMPORTANTE: Responde ÚNICAMENTE con el título. Sin comillas, sin introducciones.\n\n"
                f"LETRA:\n{raw_lyrics}"
            )
            
            resp_title = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": model, 
                    "prompt": title_prompt, 
                    "stream": False,
                    "options": {"num_predict": 50}
                }
            )
            resp_title.raise_for_status()
            raw_title_response = resp_title.json()["response"].replace('"', '').replace('*', '').strip()
            
            # Limpieza de IA habladora ("Aquí tienes el título:\n\nEl Frío de tu Ausencia")
            title_lines = [t.strip() for t in raw_title_response.split('\n') if t.strip()]
            title = title_lines[-1] if title_lines else "Nueva Canción"
            
            # Quitar prefijos molestos si los puso
            if title.upper().startswith("TÍTULO:"):
                title = title[7:].strip()
            elif title.upper().startswith("TITLE:"):
                title = title[6:].strip()
                
            if not title:
                title = "Nueva Canción"
            elif len(title) > 60:
                # Si sigue siendo una oración larga, cortamos las primeras 5 palabras
                title = " ".join(title.split()[:5])
                
            title = title.title()
            
        return {"title": title, "lyrics": raw_lyrics.strip()}
    except Exception as e:
        orch_log.warning(f"Ollama no disponible ({e}). Usando plantilla de respaldo.")
        fallback_lyric = f"""[Verse 1]
Escribiendo sobre {topic},
con el alma y emoción.
Todo empieza con pasión,
sin perder la dirección.

[Chorus]
Música para soñar,
nunca vamos a parar.
Música para saltar,
todos juntos a bailar."""
        return {"title": "Canción de Respaldo", "lyrics": fallback_lyric}

@app.post("/generate", response_model=JobStatus)
async def generate_song(
    prompt:      str           = Form(...),
    style:       Optional[str] = Form(None),
    voice_model: Optional[str] = Form(None),
    synthetic_voice_seed: int  = Form(-1),
    pitch_shift: Optional[int] = Form(0),
    title:       Optional[str] = Form(None),
):
    """
    Ruta 1: Genera cancion completa desde letra (y estilo) usando el backend configurado.
    """
    job_id    = uuid.uuid4().hex[:12]
    temp_path = Path(_config.temp_dir) / job_id
    temp_path.mkdir(parents=True, exist_ok=True)

    config = load_config()
    config.rvc_pitch_shift = pitch_shift
    if voice_model and voice_model.lower() != "none":
        config.rvc_model_path = voice_model
        idx = voice_model.replace('.pth', '.index')
        if Path(idx).exists():
            config.rvc_index_path = idx
    elif voice_model and voice_model.lower() == "none":
        config.rvc_model_path = "none"

    full_prompt = f"[{style}]\n{prompt}" if style else prompt

    state = PipelineState(job_id=job_id, prompt=full_prompt, stage="INIT", synthetic_voice_seed=synthetic_voice_seed)

    loop:      asyncio.AbstractEventLoop = asyncio.get_event_loop()
    log_queue: asyncio.Queue            = asyncio.Queue()

    _jobs[job_id] = {
        "state":      state,
        "config":     config,
        "thread":     None,
        "log_queue":  log_queue,
        "created_at": datetime.utcnow().isoformat(),
        "title":      title or "Nueva Canción"
    }

    t = threading.Thread(
        target=_run_generation_thread,
        args=(job_id, state, config, log_queue, loop, db),
        daemon=True,
        name=f"gen-{job_id}",
    )
    _jobs[job_id]["thread"] = t
    t.start()

    return JobStatus(
        job_id=job_id,
        stage="QUEUED",
        prompt=full_prompt,
        errors=[],
        timings={},
        created_at=_jobs[job_id]["created_at"],
    )


@app.post("/remaster", response_model=JobStatus)
async def remaster(
    file:        UploadFile      = File(...),
    voice_model: Optional[str]   = Form(None),
    pitch_shift: Optional[int]   = Form(None),
):
    """
    Ruta 2: Carga un archivo de audio y lo procesa con UVR5 + RVC.
    Omite generacion musical.
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
        raise HTTPException(
            status_code=400,
            detail=f"Formato de audio no soportado: '{ext}'. Usa MP3, WAV, FLAC, OGG o M4A."
        )

    job_id    = uuid.uuid4().hex[:12]
    temp_path = Path(_config.temp_dir) / job_id
    temp_path.mkdir(parents=True, exist_ok=True)
    input_audio_path = temp_path / f"input{ext}"
    content = await file.read()
    input_audio_path.write_bytes(content)
    log.info(f"[API] Archivo recibido para remaster: {input_audio_path} ({len(content)/1024:.1f} KB)")

    config = PipelineConfig(**asdict(_config))
    config.supervised_mode = False
    if voice_model:
        config.rvc_model_path = voice_model
        idx = voice_model.replace('.pth', '.index')
        if Path(idx).exists():
            config.rvc_index_path = idx
    if pitch_shift is not None:
        config.rvc_pitch_shift = pitch_shift

    loop:      asyncio.AbstractEventLoop = asyncio.get_event_loop()
    log_queue: asyncio.Queue            = asyncio.Queue()

    initial_state = PipelineState(
        job_id=job_id,
        prompt=f"[REMASTER] {file.filename}",
        stage="QUEUED",
        api_checkpoint_event=threading.Event(),
        api_checkpoint_action=None,
    )
    _jobs[job_id] = {
        "state":      initial_state,
        "log_queue":  log_queue,
        "created_at": datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=_run_remaster_thread,
        args=(job_id, str(input_audio_path), config, log_queue, loop, db),
        daemon=True,
        name=f"remaster-{job_id}",
    )
    thread.start()
    _jobs[job_id]["thread"] = thread

    log.info(f"[API] Remaster job {job_id} iniciado. Archivo: {file.filename}")

    return JobStatus(
        job_id=job_id,
        stage="QUEUED",
        prompt=f"[REMASTER] {file.filename}",
        errors=[],
        timings={},
        output_path=None,
        created_at=_jobs[job_id]["created_at"],
    )


@app.post("/repair", response_model=JobStatus)
async def repair_audio(file: UploadFile = File(...)):
    """
    Ruta 3: Limpia un archivo de audio con DeepFilterNet (sin RVC ni mezcla).
    """
    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp3", ".wav", ".flac", ".ogg", ".m4a"):
        raise HTTPException(status_code=400, detail="Formato no soportado")

    job_id    = uuid.uuid4().hex[:12]
    temp_path = Path(_config.temp_dir) / job_id
    temp_path.mkdir(parents=True, exist_ok=True)
    input_audio_path = temp_path / f"input_repair{ext}"

    content = await file.read()
    input_audio_path.write_bytes(content)
    log.info(f"[API] Archivo recibido para repair: {input_audio_path}")

    config = PipelineConfig(**asdict(_config))
    config.supervised_mode = False

    loop:      asyncio.AbstractEventLoop = asyncio.get_event_loop()
    log_queue: asyncio.Queue            = asyncio.Queue()

    initial_state = PipelineState(
        job_id=job_id,
        prompt=f"[REPAIR] {file.filename}",
        stage="QUEUED",
        api_checkpoint_event=threading.Event(),
        api_checkpoint_action=None,
    )
    _jobs[job_id] = {
        "state":      initial_state,
        "log_queue":  log_queue,
        "created_at": datetime.utcnow().isoformat(),
    }

    thread = threading.Thread(
        target=_run_repair_thread,
        args=(job_id, str(input_audio_path), config, log_queue, loop, db, initial_state),
        daemon=True,
        name=f"repair-{job_id}",
    )
    thread.start()
    _jobs[job_id]["thread"] = thread

    return JobStatus(
        job_id=job_id,
        stage="QUEUED",
        prompt=initial_state.prompt,
        errors=[],
        timings={},
        output_path=None,
        created_at=_jobs[job_id]["created_at"],
    )


@app.get("/jobs/{job_id}", response_model=JobStatus)
async def get_job(job_id: str):
    """Retorna el estado actual de un job."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} no encontrado")

    job   = _jobs[job_id]
    state = job["state"]
    return JobStatus(
        job_id=job_id,
        stage=state.stage,
        prompt=state.prompt,
        errors=state.errors,
        timings=state.timings,
        output_path=str(state.output_path) if state.output_path else None,
        created_at=job["created_at"],
    )


@app.get("/jobs/{job_id}/stream")
async def stream_job_logs(job_id: str):
    """Server-Sent Events: transmite los logs del pipeline en tiempo real."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} no encontrado")

    log_queue: asyncio.Queue = _jobs[job_id]["log_queue"]

    async def event_generator() -> AsyncGenerator[str, None]:
        yield f"data: {json.dumps({'type': 'connected', 'job_id': job_id})}\n\n"
        while True:
            try:
                message = await asyncio.wait_for(log_queue.get(), timeout=30.0)
                if message == "__END__":
                    state = _jobs[job_id]["state"]
                    payload = {
                        "type":        "completed",
                        "stage":       state.stage,
                        "output_path": str(state.output_path) if state.output_path else None,
                        "errors":      state.errors,
                        "timings":     state.timings,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                    break

                if "CHECKPOINT" in message:
                    state = _jobs[job_id]["state"]
                    yield f"data: {json.dumps({'type': 'checkpoint', 'stage': state.stage, 'message': message})}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'log', 'message': message})}\n\n"

            except asyncio.TimeoutError:
                yield "data: {\"type\": \"heartbeat\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/jobs/{job_id}/abort")
async def abort_job(job_id: str):
    """Aborta un job en curso marcandolo como ABORTED."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} no encontrado")

    state = _jobs[job_id]["state"]
    if state.stage in ("COMPLETED", "FAILED", "ABORTED"):
        return {"status": "already_finished", "stage": state.stage}

    state.stage = "ABORTED"
    state.errors.append("Abortado manualmente desde la interfaz.")
    log.warning(f"[API] Job {job_id} abortado manualmente.")
    return {"status": "aborted", "job_id": job_id}


@app.get("/gallery")
async def list_gallery(limit: int = 50, offset: int = 0):
    """Lista todas las canciones guardadas en la galeria SQLite."""
    tracks = db.list_tracks(limit=limit, offset=offset)
    return {"tracks": tracks, "total": db.count_tracks()}


@app.get("/gallery/{track_id}")
async def get_track(track_id: int):
    """Retorna los metadatos de una cancion especifica."""
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} no encontrado")
    return track


@app.delete("/gallery/{track_id}")
async def delete_track(track_id: int):
    """Elimina una cancion de la galeria."""
    deleted = db.delete_track(track_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Track {track_id} no encontrado")
    return {"status": "deleted", "track_id": track_id}


@app.put("/gallery/{track_id}")
async def rename_gallery_track(track_id: int, req: RenameRequest):
    """Renombra el titulo de una cancion de la galeria."""
    updated = db.rename_track(track_id, req.title)
    if not updated:
        raise HTTPException(status_code=404, detail=f"Track {track_id} no encontrado")
    return {"status": "renamed", "track_id": track_id, "title": req.title}


@app.get("/gallery/{track_id}/download")
async def download_track(track_id: int):
    """Descarga el archivo de audio de la galeria con el titulo original. Tambien incrementa el contador."""
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} no encontrado")

    path = Path(track["output_path"])
    if not path.exists():
        raise HTTPException(status_code=404, detail=f"Archivo {path.name} eliminado del disco.")

    # I7: Incrementar contador de reproducciones al descargar/reproducir
    try:
        db.increment_play_count(track_id)
    except Exception:
        pass  # No bloquear la descarga si falla el contador

    safe_title = "".join(c if c.isalnum() or c in "-_ " else "_" for c in track["title"]).strip()
    return FileResponse(
        path=str(path),
        media_type="audio/wav",
        filename=f"{safe_title}.wav",
    )


@app.get("/audio/{job_id}")
async def serve_audio(job_id: str):
    """Sirve el archivo WAV de salida de un job completado."""
    if job_id not in _jobs:
        raise HTTPException(status_code=404, detail=f"Job {job_id} no encontrado")

    state = _jobs[job_id]["state"]
    if not state.output_path or not Path(state.output_path).exists():
        raise HTTPException(
            status_code=404,
            detail=f"Archivo de audio no disponible para job {job_id} (stage: {state.stage})"
        )

    return FileResponse(
        path=str(state.output_path),
        media_type="audio/wav",
        filename=Path(state.output_path).name,
    )


# ── NUEVOS ENDPOINTS: Favoritos, Búsqueda y Estadísticas ────────────────────

@app.post("/gallery/{track_id}/favorite")
async def toggle_favorite(track_id: int):
    """I7: Alterna el estado de favorito de una canción."""
    track = db.get_track(track_id)
    if not track:
        raise HTTPException(status_code=404, detail=f"Track {track_id} no encontrado")
    new_state = db.toggle_favorite(track_id)
    return {"track_id": track_id, "favorite": new_state}


@app.get("/gallery/search/{query}")
async def search_gallery(query: str, limit: int = 20):
    """I8: Búsqueda full-text en la galería por título, estilo o letra."""
    if len(query.strip()) < 2:
        raise HTTPException(status_code=400, detail="La búsqueda necesita al menos 2 caracteres.")
    results = db.search_tracks(query.strip(), limit=limit)
    return {"tracks": results, "total": len(results), "query": query}



# ──────────────────────────────────────────────────────────────────────────────
# Entrypoint
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "api:app",
        host="127.0.0.1",
        port=8765,
        reload=False,
        log_level="info",
    )
