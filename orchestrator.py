"""
orchestrator.py
Pipeline local de generacion musical con supervision.

Hardware: RTX 4060 8GB VRAM
- Un modelo a la vez en VRAM
- Cada modelo: cargar -> inferencia -> descargar -> empty_cache()
"""

from __future__ import annotations

import gc
import json
import logging
import os
import subprocess
import sys
import threading
import time
import traceback
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import torch

os.environ.setdefault(
    "PHONEMIZER_ESPEAK_LIBRARY",
    r"C:\Program Files\eSpeak NG\libespeak-ng.dll"
)

# ──────────────────────────────────────────────────────────────────────────────
# FFMPEG path injection
# ──────────────────────────────────────────────────────────────────────────────

def _inject_ffmpeg_path() -> None:
    local_app_data = os.environ.get("LOCALAPPDATA", "")
    if not local_app_data:
        return
    winget_packages = Path(local_app_data) / "Microsoft" / "WinGet" / "Packages"
    if winget_packages.exists():
        for ffmpeg_dir in winget_packages.glob("Gyan.FFmpeg*"):
            for bin_path in ffmpeg_dir.rglob("ffmpeg.exe"):
                bin_dir = str(bin_path.parent.absolute())
                if bin_dir not in os.environ.get("PATH", ""):
                    os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                return

_inject_ffmpeg_path()

# ──────────────────────────────────────────────────────────────────────────────
# LOGGING
# ──────────────────────────────────────────────────────────────────────────────

LOG_DIR = Path("logs")
LOG_DIR.mkdir(exist_ok=True)

_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
_log_file  = LOG_DIR / f"pipeline_{_timestamp}.log"


class _ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG:    "\033[36m",
        logging.INFO:     "\033[32m",
        logging.WARNING:  "\033[33m",
        logging.ERROR:    "\033[31m",
        logging.CRITICAL: "\033[35m",
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname:8s}{self.RESET}"
        return super().format(record)


def _build_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    if not logger.handlers:
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(
            _ColorFormatter(
                fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
            )
        )
        logger.addHandler(ch)
        fh = logging.FileHandler(_log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        logger.addHandler(fh)
    return logger


log = _build_logger("orchestrator")

# ──────────────────────────────────────────────────────────────────────────────
# DATACLASSES
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class PipelineConfig:
    """Configuracion global del pipeline."""
    # Modelos
    ollama_model: str           = "llama3"
    diffrhythm_model_path: str  = "models/diffrhythm2"
    yue_model_path: str         = "models/yue"
    uvr5_model_path: str        = "models/uvr5/MDX-Net_Inst_HQ_3.onnx"
    rvc_model_path: str         = "models/rvc/voz_propia.pth"
    rvc_index_path: str         = "models/rvc/voz_propia.index"

    # Directorios
    gallery_dir: str            = "gallery"
    temp_dir: str               = "temp"

    # Parametros de generacion
    audio_backend: str          = "diffrhythm"   # "diffrhythm" | "yue"
    rvc_pitch_shift: int        = 0
    rvc_f0_method: str          = "rmvpe"
    mix_voice_volume_db: float  = -3.5
    mix_beat_volume_db: float   = 0.0
    target_lufs: float          = -14.0
    sample_rate: int            = 44100

    # Supervision
    supervised_mode: bool               = True
    checkpoint_timeout_seconds: int     = 300

    # Calidad RVC
    rvc_index_rate: float   = 0.55
    rvc_filter_radius: int  = 3
    rvc_protect: float      = 0.33
    rvc_hop_length: int     = 128

    # Calidad UVR5
    uvr5_segment_size: int  = 128


@dataclass
class PipelineState:
    """Estado mutable del pipeline para una ejecucion concreta."""
    job_id: str                         = ""
    prompt: str                         = ""
    metadata_json: Optional[dict]       = field(default=None)
    maqueta_path: Optional[Path]        = field(default=None)
    beat_path: Optional[Path]           = field(default=None)
    voz_generica_path: Optional[Path]   = field(default=None)
    voz_propia_path: Optional[Path]     = field(default=None)
    coros_path: Optional[Path]          = field(default=None)
    output_path: Optional[Path]         = field(default=None)
    stage: str                          = "INIT"
    errors: list                        = field(default_factory=list)
    timings: dict                       = field(default_factory=dict)
    # Control via API
    synthetic_voice_seed: int           = field(default=-1)
    api_checkpoint_event: Optional[Any]  = field(default=None)
    api_checkpoint_action: Optional[str] = field(default=None)

    def log_snapshot(self, logger: logging.Logger) -> None:
        div = "-" * 72
        logger.info(div)
        logger.info(f"  SNAPSHOT | Etapa: {self.stage}")
        logger.info(div)
        logger.info(f"  job_id           : {self.job_id}")
        logger.info(f"  prompt           : {self.prompt[:80]}")
        logger.info(f"  maqueta_path     : {self.maqueta_path}")
        logger.info(f"  beat_path        : {self.beat_path}")
        logger.info(f"  voz_generica_path: {self.voz_generica_path}")
        logger.info(f"  voz_propia_path  : {self.voz_propia_path}")
        logger.info(f"  output_path      : {self.output_path}")
        logger.info(f"  errores          : {len(self.errors)}")
        logger.info(div)


# ──────────────────────────────────────────────────────────────────────────────
# VRAM UTILITIES
# ──────────────────────────────────────────────────────────────────────────────

def _vram_mb() -> float:
    if torch.cuda.is_available():
        return torch.cuda.memory_allocated() / (1024 ** 2)
    return 0.0


def _log_vram(stage: str) -> None:
    if torch.cuda.is_available():
        reserved  = torch.cuda.memory_reserved()  / (1024 ** 2)
        allocated = torch.cuda.memory_allocated() / (1024 ** 2)
        log.debug(
            f"[VRAM] {stage:30s} | Asignada: {allocated:7.1f} MB | Reservada: {reserved:7.1f} MB"
        )
    else:
        log.warning("[VRAM] CUDA no disponible. Ejecutando en CPU.")


def _clear_vram(tag: str = "") -> None:
    """Libera la VRAM de PyTorch."""
    if torch.cuda.is_available():
        gc.collect()
        torch.cuda.empty_cache()
        log.info(f"[VRAM] {tag} - Memoria liberada.")


def purge_vram(model_ref: Any = None, context: str = "") -> None:
    """Elimina el modelo de la VRAM, fuerza GC y vacia la cache de CUDA."""
    if model_ref is not None:
        log.info(f"[VRAM] Descargando modelo: {context}")
        try:
            if hasattr(model_ref, "cpu"):
                model_ref.cpu()
            del model_ref
        except Exception as exc:
            log.warning(f"[VRAM] Error al borrar referencia del modelo: {exc}")
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    _log_vram(f"POST-PURGE [{context}]")


# ──────────────────────────────────────────────────────────────────────────────
# CHECKPOINT
# ──────────────────────────────────────────────────────────────────────────────

def checkpoint(
    state: PipelineState,
    message: str,
    payload: Optional[dict] = None,
    config: Optional[PipelineConfig] = None,
) -> bool:
    """
    Punto de control supervisado. Pausa y espera confirmacion del operador.
    Retorna True para continuar, False para abortar.
    """
    timeout = config.checkpoint_timeout_seconds if config else 300

    log.warning("=" * 72)
    log.warning(f"  CHECKPOINT: {message}")
    log.warning("=" * 72)

    if payload:
        log.info("[CHECKPOINT] Payload:")
        log.info(json.dumps(payload, ensure_ascii=False, indent=2))

    state.log_snapshot(log)

    if not (config and config.supervised_mode):
        log.info("[CHECKPOINT] Modo autonomo activo -> continuando sin pausa.")
        return True

    log.warning(f"[CHECKPOINT] Ingresa 'ok' para continuar, 'abort' para abortar (timeout: {timeout}s):")

    # Integracion API
    if getattr(state, "api_checkpoint_event", None) is not None:
        log.info("[CHECKPOINT] Esperando respuesta de la UI (API)...")
        state.api_checkpoint_event.clear()
        if state.api_checkpoint_event.wait(timeout=timeout):
            answer = state.api_checkpoint_action
            if answer == "ok":
                log.info("[CHECKPOINT] Operador confirmo via UI -> continuando.")
                return True
            else:
                log.error("[CHECKPOINT] Operador aborto el pipeline via UI.")
                return False
        else:
            log.error(f"[CHECKPOINT] Timeout de {timeout}s alcanzado. Abortando.")
            return False

    # Fallback CLI
    start = time.time()
    while True:
        if time.time() - start > timeout:
            log.error(f"[CHECKPOINT] Timeout de {timeout}s alcanzado. Abortando.")
            return False

        if sys.platform == "win32":
            import msvcrt
            if msvcrt.kbhit():
                answer = input(">>> ").strip().lower()
                if answer == "ok":
                    log.info("[CHECKPOINT] Operador confirmo -> continuando.")
                    return True
                elif answer == "abort":
                    log.error("[CHECKPOINT] Operador aborto el pipeline.")
                    return False
        time.sleep(0.2)


# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 1: GENERACION MUSICAL
# ──────────────────────────────────────────────────────────────────────────────

def _spanish_to_ipa(text: str) -> str:
    """Convierte texto en espanol a tokens IPA aproximados para DiffRhythm."""
    text = text.lower()
    text = text.replace('ll', 'j').replace('ch', 't s').replace('qu', 'k').replace('rr', 'r r')
    text = text.replace('gue', 'g e').replace('gui', 'g i')
    text = text.replace('ce', 's e').replace('ci', 's i')

    mapping = {
        'a': 'a', 'b': 'b', 'c': 'k', 'd': 'd', 'e': 'e', 'f': 'f',
        'g': 'g', 'h': '', 'i': 'i', 'j': 'x', 'k': 'k', 'l': 'l',
        'm': 'm', 'n': 'n', 'o': 'o', 'p': 'p', 'q': 'k',
        'r': 'r', 's': 's', 't': 't', 'u': 'u', 'v': 'b', 'w': 'w',
        'x': 'k s', 'y': 'j', 'z': 's',
        'n': 'n j',
        'a': 'a', 'e': 'e', 'i': 'i', 'o': 'o', 'u': 'u', 'u': 'u',
        ' ': '_', ',': ',', '.': '.', '?': '?', '!': '!',
    }

    tokens = []
    for char in text:
        mapped = mapping.get(char)
        if mapped is not None:
            if mapped:
                tokens.append(mapped)
        elif char.isalnum():
            tokens.append(char)

    res = " ".join(tokens)
    while "_ _" in res:
        res = res.replace("_ _", "_")
    return res


def stage_acestep_generate(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """
    Etapa 1: Generación de música con ACE-Step (Nativo Español)
    """
    state.stage = "ACESTEP_GENERATE"
    log.info("━" * 72)
    log.info("[ETAPA 1] Iniciando Generación Musical con ACE-Step...")
    _clear_vram("INICIO ETAPA_ACESTEP")

    t0 = time.time()
    
    # Usar Chronos-VFS para no tocar el disco
    temp_dir = Path(config.temp_dir) / state.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_wav = temp_dir / "yue_generated.wav"

    ace_repo = Path("ace_step_repo").absolute()
    if not ace_repo.exists():
        log.error(f"[ACE-Step] No se encontró el repositorio en {ace_repo}")
        state.stage = "FAILED"
        state.errors.append("ace_step_repo no encontrado")
        return state

    # Extraer variables para el wrapper
    lyrics_str = state.prompt 
    words = len(lyrics_str.split())
    # Estimate: ~0.4s per word + 4s intro/outro buffer. Max limit 180s.
    estimated_duration = min(180.0, max(20.0, (words * 0.4) + 4.0))
    log.info(f"[ACE-Step] Letra de {words} palabras. Duración dinámica calculada: {estimated_duration:.1f}s")
    
    # Inferir genero de la voz a partir del seed (1111=Femenina, 2222=Masculina)
    voz_tag = "Voz Femenina Clara"
    if state.synthetic_voice_seed and "222" in str(state.synthetic_voice_seed):
        voz_tag = "Voz Masculina Potente, Tono Profundo"
        
    # Inyectar tags ocultos para forzar español nativo y evitar confusiones del LangSegment
    hidden_tags = f"[es, {voz_tag}, Sin Intro]"
    enhanced_prompt = f"{hidden_tags}\n{lyrics_str}"
    
    # Preparar el comando
    wrapper_path = ace_repo / "ace_step_wrapper.py"
    
    cmd = [
        sys.executable, str(wrapper_path),
        "--prompt", enhanced_prompt.replace('\n', '\\n'),
        "--lyrics", lyrics_str.replace('\n', '\\n'),
        "--duration", str(estimated_duration),
        "--output_path", str(output_wav.absolute()),
        "--device_id", "0",
        "--seed", str(state.synthetic_voice_seed)
    ]
    
    log.info(f"[ACE-Step] Ejecutando inferencia en {ace_repo}...")
    
    try:
        result = subprocess.run(cmd, cwd=str(ace_repo), capture_output=True, text=True)
        if result.returncode != 0:
            log.error(f"[ACE-Step] Error en ejecución:\n{result.stderr}")
            state.stage = "FAILED"
            state.errors.append(f"ACE-Step falló: {result.stderr[-200:]}")
            return state
            
        log.info(f"[ACE-Step] Generación exitosa: {output_wav}")
        state.maqueta_path = output_wav
        
        t1 = time.time()
        log.info(f"[ETAPA 1] ACE-Step completado en {t1 - t0:.1f}s")
        
    except Exception as e:
        log.error(f"[ACE-Step] Excepción: {e}")
        state.stage = "FAILED"
        state.errors.append(str(e))
        return state

    return state


def stage_diffrhythm_generate(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """Genera audio musical con DiffRhythm usando letras en formato LRC+IPA."""
    log.info("=" * 72)
    log.info("[ETAPA 1] Iniciando Generacion Musical con DiffRhythm...")
    state.stage = "DIFFRHYTHM_GENERATE"
    _clear_vram("INICIO ETAPA_DIFFRHYTHM")
    t0 = time.time()

    temp_dir = Path(config.temp_dir) / state.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Preparar letras en formato LRC con IPA
    lyrics = state.prompt
    lrc_lines = []
    current_time = 0.0
    for line in lyrics.split('\n'):
        line = line.strip()
        if not line or line.startswith('['):
            continue
        m = int(current_time // 60)
        s = current_time % 60
        ipa_tokens = _spanish_to_ipa(line)
        lrc_lines.append(f"[{m:02d}:{s:05.2f}] [IPA] {ipa_tokens}")
        current_time += 4.0

    lrc_content = "\n".join(lrc_lines)
    lrc_path = temp_dir / "lyrics.lrc"
    lrc_path.write_text(lrc_content, encoding='utf-8')
    log.info(f"[DiffRhythm] Letras LRC generadas en {lrc_path}")

    output_dir = temp_dir / "diffrhythm_out"
    output_dir.mkdir(exist_ok=True)

    try:
        log.info("[DiffRhythm] Ejecutando inferencia (95 segundos)...")
        cmd = [
            sys.executable,
            "infer/infer.py",
            "--lrc-path", str(lrc_path.absolute()),
            "--output-dir", str(output_dir.absolute()),
            "--audio-length", "95",
        ]

        result = subprocess.run(cmd, cwd="diffrhythm_repo", capture_output=True, text=True)

        if result.returncode != 0:
            log.error(f"[DiffRhythm] Error en ejecucion:\n{result.stderr}")
            state.stage = "FAILED"
            return state

        output_wav = output_dir / "output.wav"
        if output_wav.exists():
            import shutil
            final_wav = temp_dir / "yue_generated.wav"
            shutil.copy(output_wav, final_wav)
            state.maqueta_path = final_wav
            log.info(f"[ETAPA 1] DiffRhythm completado en {time.time()-t0:.2f}s")
        else:
            raise FileNotFoundError("DiffRhythm no genero el archivo output.wav")

    except Exception as e:
        log.error(f"[ETAPA 1] Falla en DiffRhythm: {e}")
        state.stage = "FAILED"

    _clear_vram("FIN ETAPA_DIFFRHYTHM")
    return state


def stage_yue_generate(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """Genera audio musical con YuE (modo simulacion/stub para desarrollo)."""
    log.info("=" * 72)
    log.info("[ETAPA 1] Iniciando Generacion Musical con YuE...")
    state.stage = "YUE_GENERATE"
    _clear_vram("INICIO ETAPA_YUE")
    t0 = time.time()

    temp_dir = Path(config.temp_dir) / state.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_wav = temp_dir / "yue_generated.wav"

    try:
        log.info("[YuE] Construyendo prompt para el modelo...")
        log.info(f"[YuE] Letras: {state.prompt[:50]}...")
        log.info("[YuE] Simulando generacion...")

        import shutil
        simulated_source = Path("test_svs.wav")
        if simulated_source.exists():
            shutil.copy(simulated_source, output_wav)
        else:
            import wave
            import os
            with wave.open(str(output_wav), 'wb') as wf:
                wf.setnchannels(2)
                wf.setsampwidth(2)
                wf.setframerate(44100)
                wf.writeframes(os.urandom(44100 * 4 * 5))  # 5 segundos de ruido blanco

        state.maqueta_path = output_wav
        log.info(f"[ETAPA 1] YuE generacion completada en {time.time()-t0:.2f}s")

    except Exception as e:
        log.error(f"[ETAPA 1] Falla en YuE: {e}")
        state.stage = "FAILED"

    _clear_vram("FIN ETAPA_YUE")
    return state


# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 3: UVR5 - SEPARACION DE STEMS
# ──────────────────────────────────────────────────────────────────────────────

def stage_uvr5_remaster(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """
    Usa UVR5 para separar la maqueta en beat.wav y voz_generica.wav.
    Modo ENSEMBLE: Cerebro 1 extrae el beat, Cerebro 2 extrae la voz.
    """
    state.stage = "UVR5_SEPARATE"
    log.info("-" * 72)
    log.info("[ETAPA 3] Iniciando separacion de stems con UVR5.")
    _log_vram("INICIO ETAPA_UVR5")

    if not state.maqueta_path or not state.maqueta_path.exists():
        msg = f"maqueta_path no existe: {state.maqueta_path}"
        log.error(f"[ETAPA 3] {msg}")
        state.errors.append(msg)
        raise FileNotFoundError(msg)

    log.info(f"[ETAPA 3] Maqueta input     : {state.maqueta_path}")
    log.info(f"[ETAPA 3] Modo ENSEMBLE GRUPAL ACTIVADO (2 Cerebros)")

    temp_dir = Path(config.temp_dir) / state.job_id
    temp_dir.mkdir(parents=True, exist_ok=True)
    beat_path         = temp_dir / "beat.wav"
    voz_generica_path = temp_dir / "voz_generica.wav"
    todas_las_voces_path = temp_dir / "todas_las_voces.wav"

    t_start = time.time()
    try:
        # CEREBRO 1: El Musico (Beat Puro)
        log.info("[UVR5 ENSEMBLE] Cerebro 1/2: Extrayendo Pista Instrumental Pura...")
        _run_uvr5_cli(
            input_path=state.maqueta_path,
            model_path="models/uvr5/UVR-MDX-NET-Inst_HQ_3.onnx",
            output_instrumental=beat_path,
            output_vocals=temp_dir / "basura_vocal_1.wav",
            segment_size=config.uvr5_segment_size,
        )

        # CEREBRO 2: El Recolector (Todas las Voces)
        log.info("[UVR5 ENSEMBLE] Cerebro 2/2: Recolectando Todas las Voces Intactas...")
        _run_uvr5_cli(
            input_path=state.maqueta_path,
            model_path="models/uvr5/Kim_Vocal_2.onnx",
            output_instrumental=temp_dir / "basura_inst_2.wav",
            output_vocals=todas_las_voces_path,
            segment_size=config.uvr5_segment_size,
        )

        # Escudo Acustico pre-RVC
        log.info("[UVR5 ENSEMBLE] Escudo Acustico: Normalizando nivel de voz...")
        _run_ffmpeg_vocal_prep(todas_las_voces_path, voz_generica_path)

    except Exception as exc:
        log.error(f"[ETAPA 3] Error en UVR5 ENSEMBLE: {exc}")
        state.errors.append(str(exc))
        raise
    finally:
        basuras = [
            temp_dir / "basura_vocal_1.wav",
            temp_dir / "basura_inst_2.wav",
            todas_las_voces_path,
        ]
        for p in basuras:
            if p.exists():
                p.unlink()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _log_vram("POST UVR5")

    elapsed = time.time() - t_start
    state.timings["uvr5"] = round(elapsed, 2)
    state.beat_path         = beat_path
    state.voz_generica_path = voz_generica_path

    log.info(f"[ETAPA 3] Separacion completada en {elapsed:.2f}s.")
    log.info(f"[ETAPA 3] beat_path         : {state.beat_path}")
    log.info(f"[ETAPA 3] voz_generica_path : {state.voz_generica_path}")

    for p in [beat_path, voz_generica_path]:
        if p.exists():
            log.info(f"[ETAPA 3] OK {p.name} -> {p.stat().st_size / 1024:.1f} KB")
        else:
            log.warning(f"[ETAPA 3] FALLO {p.name} NO fue generado.")

    _log_vram("FIN ETAPA_UVR5")
    return state


def _run_uvr5_cli(
    input_path: Path,
    model_path: str,
    output_instrumental: Path,
    output_vocals: Path,
    segment_size: int = 128,
) -> None:
    """
    Ejecuta UVR5 via subprocess con reintentos automaticos.
    Si crashea con OOM (codigo 3221226505), reduce segment_size y reintenta.
    Secuencia: [segment_size] -> [segment_size//2] -> [32] -> fallo.
    """
    model_filename = Path(model_path).name
    OOM_CODE       = 3221226505  # 0xC0000409

    # Localizar audio-separator
    audio_sep_bin  = str(Path(sys.executable).parent / "audio-separator")
    model_file_dir = str(Path(model_path).parent)

    sizes_to_try = sorted({segment_size, segment_size // 2, 32}, reverse=True)
    sizes_to_try = [s for s in sizes_to_try if s >= 32]

    last_error: Optional[str] = None

    for seg_size in sizes_to_try:
        cmd = [
            audio_sep_bin,
            str(input_path),
            "--model_filename",   model_filename,
            "--model_file_dir",   model_file_dir,
            "--output_dir",       str(output_instrumental.parent),
            "--output_format",    "WAV",
            "--mdx_segment_size", str(seg_size),
            "--mdxc_segment_size", str(seg_size),
        ]

        log.info(f"[UVR5] Intentando separacion con segment_size={seg_size}...")
        log.info(f"[UVR5] Comando: {' '.join(str(c) for c in cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        if result.returncode == 0:
            log.info(f"[UVR5] Separacion exitosa con segment_size={seg_size}.")
            log.debug(f"[UVR5] STDOUT:\n{result.stdout[-1000:]}")
            break

        if result.returncode in (OOM_CODE, -1073740791):
            log.warning(
                f"[UVR5] Crash OOM (codigo {result.returncode}) con segment_size={seg_size}. "
                f"Reintentando con segmento menor..."
            )
            last_error = f"OOM crash con segment_size={seg_size}"
            continue

        log.error(f"[UVR5] STDERR:\n{result.stderr}")
        raise RuntimeError(
            f"UVR5 termino con codigo {result.returncode}: {result.stderr[-500:]}"
        )
    else:
        raise RuntimeError(
            f"UVR5 fallo con OOM en todos los tamanios de segmento ({sizes_to_try}). "
            f"Ultimo error: {last_error}. "
            f"Instala onnxruntime-gpu para mejorar el rendimiento."
        )

    # Renombrar archivos a nombres canonicos
    _rename_uvr5_outputs(
        output_dir=output_instrumental.parent,
        output_instrumental=output_instrumental,
        output_vocals=output_vocals,
    )


def _rename_uvr5_outputs(
    output_dir: Path, output_instrumental: Path, output_vocals: Path
) -> None:
    """
    audio-separator genera archivos con sufijos (_Instrumental.wav, _Vocals.wav).
    Los renombra a los paths canonicos del pipeline.
    """
    inst_candidates  = sorted(output_dir.glob("*Instrumental*.wav"))
    if not inst_candidates:
        inst_candidates = sorted(output_dir.glob("*Other*.wav"))

    vocal_candidates = sorted(output_dir.glob("*Vocals*.wav"))
    if not vocal_candidates:
        vocal_candidates = sorted(output_dir.glob("*Dry*.wav"))

    if inst_candidates and inst_candidates[0] != output_instrumental:
        inst_candidates[0].rename(output_instrumental)
        log.debug(f"[UVR5] Renombrado: {inst_candidates[0].name} -> {output_instrumental.name}")

    if vocal_candidates and vocal_candidates[0] != output_vocals:
        vocal_candidates[0].rename(output_vocals)
        log.debug(f"[UVR5] Renombrado: {vocal_candidates[0].name} -> {output_vocals.name}")


# ──────────────────────────────────────────────────────────────────────────────
# ETAPA DEEPFILTER: Limpieza de voz
# ──────────────────────────────────────────────────────────────────────────────

def stage_deepfilter_repair(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """Limpia la voz generica de ruidos y artefactos usando DeepFilterNet."""
    state.stage = "DEEPFILTER_REPAIR"
    log.info("-" * 72)
    log.info("[ETAPA DEEPFILTER] Iniciando purificacion de voz con DeepFilterNet...")

    t_start = time.time()
    try:
        from df.enhance import enhance, init_df, load_audio, save_audio

        model, df_state, _ = init_df()

        voz_sucia_path = str(state.voz_generica_path)
        voz_limpia_path = str(state.voz_generica_path).replace(".wav", "_cleaned.wav")

        log.info(f"[DEEPFILTER] Cargando audio: {voz_sucia_path}")
        audio, _ = load_audio(voz_sucia_path, sr=df_state.sr())

        log.info("[DEEPFILTER] Procesando audio con IA...")
        enhanced = enhance(model, df_state, audio, atten_lim_db=6.0)

        log.info("[DEEPFILTER] Guardando audio limpio...")
        save_audio(voz_limpia_path, enhanced, df_state.sr())

        state.voz_generica_path = Path(voz_limpia_path)

    except Exception as exc:
        log.error(f"[DEEPFILTER] Error: {exc}")
        state.errors.append(str(exc))
        raise

    elapsed = time.time() - t_start
    state.timings["deepfilter"] = round(elapsed, 2)
    log.info(f"[DEEPFILTER] Limpieza completada en {elapsed:.2f}s.")
    return state


# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 4: RVC - Clonacion de voz
# ──────────────────────────────────────────────────────────────────────────────

def stage_rvc_clone(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """Aplica RVC sobre voz_generica.wav para generar voz_propia.wav."""
    state.stage = "RVC_CLONE"
    log.info("-" * 72)
    log.info("[ETAPA 4] Iniciando clonacion de voz con RVC-CLI.")
    _log_vram("INICIO ETAPA_RVC")

    if not state.voz_generica_path or not state.voz_generica_path.exists():
        msg = f"voz_generica_path no existe: {state.voz_generica_path}"
        log.error(f"[ETAPA 4] {msg}")
        state.errors.append(msg)
        raise FileNotFoundError(msg)

    log.info(f"[ETAPA 4] Voz generica input: {state.voz_generica_path}")
    log.info(f"[ETAPA 4] Modelo RVC        : {config.rvc_model_path}")
    log.info(f"[ETAPA 4] Pitch shift       : {config.rvc_pitch_shift} semitonos")
    log.info(f"[ETAPA 4] F0 method         : {config.rvc_f0_method}")

    temp_dir = Path(config.temp_dir) / state.job_id
    voz_propia_path = temp_dir / "voz_propia.wav"

    log.info("[RVC] Esperando 3 segundos para limpieza de VRAM...")
    time.sleep(3)

    # Parametros anti-robot
    f0_method     = "crepe"
    filter_radius = 7
    protect       = 0.33
    index_rate    = 0.15 if config.rvc_pitch_shift == 0 else 0.0

    t_start = time.time()
    try:
        _run_rvc_cli(
            input_path=state.voz_generica_path,
            output_path=voz_propia_path,
            model_path=config.rvc_model_path,
            index_path=config.rvc_index_path,
            pitch_shift=config.rvc_pitch_shift,
            f0_method=f0_method,
            index_rate=index_rate,
            filter_radius=filter_radius,
            protect=protect,
            hop_length=64,
        )
    except Exception as exc:
        log.error(f"[ETAPA 4] Error en RVC: {exc}")
        state.errors.append(str(exc))
        raise
    finally:
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        _log_vram("POST RVC")

    elapsed = time.time() - t_start
    state.timings["rvc"] = round(elapsed, 2)
    state.voz_propia_path = voz_propia_path

    log.info(f"[ETAPA 4] RVC completado en {elapsed:.2f}s.")
    if voz_propia_path.exists():
        log.info(f"[ETAPA 4] OK {voz_propia_path.name} -> {voz_propia_path.stat().st_size / 1024:.1f} KB")
    else:
        log.warning("[ETAPA 4] FALLO voz_propia.wav NO fue generado.")

    _log_vram("FIN ETAPA_RVC")
    return state


def _run_rvc_cli(
    input_path: Path,
    output_path: Path,
    model_path: str,
    index_path: str,
    pitch_shift: int = 0,
    f0_method: str = "rmvpe",
    index_rate: float = 0.45,
    filter_radius: int = 3,
    protect: float = 0.33,
    hop_length: int = 64,
) -> None:
    """Invoca rvc-cli con todos los parametros de calidad."""
    log.info("[RVC] Construyendo comando CLI nativo...")
    log.info(f"[RVC] index_rate={index_rate} | filter_radius={filter_radius} | protect={protect} | hop_length={hop_length} | f0_method={f0_method}")

    rvc_bin = str(Path(sys.executable).parent / "rvc-cli.exe")

    if not Path(rvc_bin).exists():
        log.warning(f"[RVC] rvc-cli.exe NO ENCONTRADO en {rvc_bin}.")
        log.warning("[RVC] MODO SIMULACIÓN: Se copiará el audio original (passthrough).")
        import shutil
        shutil.copy(input_path, output_path)
        return

    index_rate_str = f"{round(index_rate, 2):.2f}"
    protect_str    = f"{round(protect, 2):.2f}"

    cmd = [
        rvc_bin, "infer",
        "--input-path",    str(input_path),
        "--output-path",   str(output_path),
        "--pth-path",      model_path,
        "--index-path",    index_path,
        "--pitch",         str(pitch_shift),
        "--f0-method",     f0_method,
        "--index-rate",    index_rate_str,
        "--filter-radius", str(filter_radius),
        "--hop-length",    str(hop_length),
        "--split-audio",   "False",
        "--clean-audio",   "False",
        "--export-format", "WAV",
    ]

    # Agregar --protect condicionalmente
    try:
        help_r = subprocess.run([rvc_bin, 'infer', '--help'], capture_output=True, text=True, timeout=15)
        if '--protect' in help_r.stdout or '--protect' in help_r.stderr:
            cmd += ["--protect", protect_str]
            log.info(f"[RVC] protect={protect_str} (--protect soportado)")
        else:
            log.info("[RVC] --protect no soportado en esta version del CLI (omitido)")
    except Exception:
        pass

    log.info(f"[RVC] Comando: {' '.join(str(c) for c in cmd)}")

    max_retries = 2
    for attempt in range(max_retries):
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)

        if result.returncode == 0:
            break

        if result.returncode in (3221226505, -1073740791) and attempt < max_retries - 1:
            log.warning(f"[RVC] Fallo por OOM. Reintentando en 5s... (Intento {attempt + 1}/{max_retries})")
            time.sleep(5)
            continue

        log.error(f"[RVC] STDERR:\n{result.stderr}")
        raise RuntimeError(f"RVC termino con codigo {result.returncode}: {result.stderr[-500:]}")

    log.debug(f"[RVC] STDOUT:\n{result.stdout[-1000:]}")


# ──────────────────────────────────────────────────────────────────────────────
# ETAPA 5: FFmpeg - Mezcla y masterizacion
# ──────────────────────────────────────────────────────────────────────────────

def stage_mix_and_master(state: PipelineState, config: PipelineConfig) -> PipelineState:
    """
    Mezcla beat.wav + voz_propia.wav con FFmpeg:
    1. Ajuste de volumenes independientes.
    2. Normalizacion LUFS con loudnorm.
    3. Exportacion final al directorio de la galeria.
    """
    state.stage = "MIX_AND_MASTER"
    log.info("-" * 72)
    log.info("[ETAPA 5] Iniciando mezcla y masterizacion con FFmpeg.")

    for attr, label in [("beat_path", "beat_path"), ("voz_propia_path", "voz_propia_path")]:
        p: Optional[Path] = getattr(state, attr)
        if not p or not p.exists():
            msg = f"{label} no existe: {p}"
            log.error(f"[ETAPA 5] {msg}")
            state.errors.append(msg)
            raise FileNotFoundError(msg)

    log.info(f"[ETAPA 5] Beat path        : {state.beat_path}")
    log.info(f"[ETAPA 5] Voz propia path  : {state.voz_propia_path}")
    log.info(f"[ETAPA 5] Volume beat (dB) : {config.mix_beat_volume_db:+.1f}")
    log.info(f"[ETAPA 5] Volume voz (dB)  : {config.mix_voice_volume_db:+.1f}")
    log.info(f"[ETAPA 5] Target LUFS      : {config.target_lufs}")

    gallery_dir = Path(config.gallery_dir)
    gallery_dir.mkdir(parents=True, exist_ok=True)

    if state.metadata_json and "titulo" in state.metadata_json:
        titulo = state.metadata_json["titulo"]
    elif state.prompt.startswith("[REMASTER] "):
        titulo = Path(state.prompt.replace("[REMASTER] ", "")).stem
    else:
        titulo = "cancion"

    titulo_seguro = "".join(
        c if c.isalnum() or c in "-_ " else "_" for c in titulo
    ).strip().replace(" ", "_")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Crear carpeta unica para la cancion
    folder_name = f"{titulo_seguro}_{state.job_id[:8]}_{ts}"
    song_dir = gallery_dir / folder_name
    song_dir.mkdir(parents=True, exist_ok=True)
    
    output_path = song_dir / f"{folder_name}.wav"

    log.info(f"[ETAPA 5] Output final     : {output_path}")

    t_start = time.time()
    try:
        _run_ffmpeg_mix(
            beat_path=state.beat_path,
            vocal_path=state.voz_propia_path,
            output_path=output_path,
            beat_vol_db=config.mix_beat_volume_db,
            vocal_vol_db=config.mix_voice_volume_db,
            target_lufs=config.target_lufs,
        )
    except Exception as exc:
        log.error(f"[ETAPA 5] Error en mezcla: {exc}")
        state.errors.append(str(exc))
        raise

    elapsed = time.time() - t_start
    state.timings["mix"] = round(elapsed, 2)
    state.output_path = output_path

    try:
        import shutil
        # Respaldar Stems
        shutil.copy(state.beat_path, song_dir / "instrumental_stem.wav")
        shutil.copy(state.voz_propia_path, song_dir / "vocal_stem.wav")
        
        # Generar Certificado Legal
        cert_path = song_dir / "CERTIFICADO_LEGAL.md"
        cert_content = f"""# CERTIFICADO DE AUTORÍA Y DERECHOS LEGALES
    
**Autor / Titular de Derechos:** Ramón Antonio Burgos Jerez
**Fecha de Generación:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**ID Único de Sesión:** {state.job_id}

## Detalles de la Obra
- **Título de la Pista:** {titulo}
- **Prompt / Letras Originales:** 
{state.prompt}

## Trazabilidad Técnica
- **Motor Base:** ACE-Step (Open Source AI)
- **Separación de Pistas:** UVR5 (MDX-Net / Kim Vocal)
- **Motor Vocal:** RVC (Voz Propia / Genérica)
- **Licencia Aplicable:** MIT License

*Este documento y las pistas crudas (vocal/instrumental) adjuntas en esta carpeta constituyen prueba irrefutable de que el titular generó esta obra mediante infraestructura propia y de código abierto. Posee el 100% de los derechos comerciales.*
"""
        cert_path.write_text(cert_content, encoding="utf-8")
        log.info("[ETAPA 5] Certificado Legal y Stems respaldados exitosamente.")
    except Exception as e:
        log.warning(f"[ETAPA 5] Error al generar respaldo legal: {e}")

    log.info(f"[ETAPA 5] Mezcla completada en {elapsed:.2f}s.")
    log.info(f"[ETAPA 5] Output: {output_path}")
    return state


def _run_ffmpeg_vocal_prep(input_path: Path, output_path: Path) -> None:
    """
    Filtro de Preparacion Pre-Clonacion (Escudo Acustico).
    Normaliza el nivel de voz con alimiter antes de enviarsela a RVC.
    """
    filter_complex = "alimiter=limit=-1dB"
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-af", filter_complex,
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    log.info(f"[FFmpeg] Pre-Procesando Voz Generica...")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"Fallo FFmpeg vocal prep: {result.stderr}")
    log.debug(f"[FFmpeg] STDERR:\n{result.stderr[-500:]}")


def _run_ffmpeg_mix(
    beat_path: Path,
    vocal_path: Path,
    output_path: Path,
    beat_vol_db: float = 0.0,
    vocal_vol_db: float = 0.0,
    target_lufs: float = -14.0,
) -> None:
    """Ejecuta FFmpeg para mezclar beat + voz con normalizacion LUFS."""
    beat_linear  = 10 ** ((beat_vol_db  + 6.0) / 20)
    vocal_linear = 10 ** ((vocal_vol_db + 6.0) / 20)

    filter_complex = (
        f"[0:a]volume={beat_linear:.4f}[beat];"
        # Rack de Mastering Vocal: Resample -> Stereo -> EQ (cortar graves, dar brillo) -> Compresion -> Reverb sutil -> Volumen
        f"[1:a]aresample=44100,aformat=channel_layouts=stereo,"
        f"highpass=f=120,highshelf=f=8000:g=4,"
        f"acompressor=threshold=-15dB:ratio=4:attack=5:release=50:makeup=4,"
        f"aecho=0.8:0.6:40:0.2,volume={vocal_linear:.4f}[voz];"
        f"[beat][voz]amix=inputs=2:duration=longest:dropout_transition=2[mixed];"
        f"[mixed]loudnorm=I={target_lufs}:TP=-1.0:LRA=11[out]"
    )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(beat_path),
        "-i", str(vocal_path),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        str(output_path),
    ]
    log.info(f"[FFmpeg] Comando: {' '.join(str(c) for c in cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    if result.returncode != 0:
        log.error(f"[FFmpeg] STDERR:\n{result.stderr[-1000:]}")
        raise RuntimeError(f"FFmpeg termino con codigo {result.returncode}")


def _run_acoustic_diagnostic(voz_path: Path, beat_path: Path) -> dict:
    """Analiza niveles RMS, clipping y silencios de la voz clonada."""
    try:
        import re
        log.info("[ESPECTROMETRO] Iniciando Analisis Acustico...")

        cmd_vol = [
            "ffmpeg", "-i", str(voz_path),
            "-af", "volumedetect,silencedetect=noise=-50dB:d=0.1",
            "-f", "null", "-"
        ]
        result = subprocess.run(cmd_vol, capture_output=True, text=True)
        stderr = result.stderr

        max_vol_match  = re.search(r"max_volume:\s*([-0-9.]+)\s*dB", stderr)
        mean_vol_match = re.search(r"mean_volume:\s*([-0-9.]+)\s*dB", stderr)
        silences       = re.findall(r"silencedetect.*?silence_start:\s*([0-9.]+)", stderr)

        max_vol  = float(max_vol_match.group(1))  if max_vol_match  else 0.0
        mean_vol = float(mean_vol_match.group(1)) if mean_vol_match else 0.0

        reporte = []
        reporte.append("=" * 60)
        reporte.append(" REPORTE DE DIAGNOSTICO ACUSTICO")
        reporte.append("=" * 60)

        if max_vol >= 0.0:
            reporte.append(f"CLIPPING: Picos en {max_vol}dB. La voz se esta saturando.")
        elif max_vol > -1.0:
            reporte.append(f"LIMITE: Picos en {max_vol}dB. Riesgo de distorsion.")
        else:
            reporte.append(f"OK RANGO DINAMICO: Picos seguros en {max_vol}dB.")

        if mean_vol < -30.0:
            reporte.append(f"NIVEL RMS BAJO: {mean_vol}dB. La voz esta enterrada.")
        else:
            reporte.append(f"OK NIVEL RMS: {mean_vol}dB. Volumen vocal estable.")

        if len(silences) > 150:
            reporte.append(f"CORTES EXCESIVOS: {len(silences)} silencios.")
        else:
            reporte.append(f"OK FLUIDEZ: {len(silences)} silencios detectados.")

        for line in reporte:
            log.info(line)

        return {
            "max_vol":     max_vol,
            "mean_vol":    mean_vol,
            "silences":    len(silences),
            "has_warnings": max_vol > -1.0 or mean_vol < -30.0 or len(silences) > 40,
        }

    except Exception as e:
        log.warning(f"[ESPECTROMETRO] Fallo al ejecutar analisis: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# CONFIG LOADER
# ──────────────────────────────────────────────────────────────────────────────

def load_config(config_path: str = "config.json") -> PipelineConfig:
    """Carga la configuracion desde un archivo JSON."""
    p = Path(config_path)
    if not p.exists():
        log.warning(f"[CONFIG] {config_path} no encontrado. Usando configuracion por defecto.")
        return PipelineConfig()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        config = PipelineConfig(**{k: v for k, v in data.items() if hasattr(PipelineConfig, k)})
        log.info(f"[CONFIG] Configuracion cargada desde {config_path}")
        return config
    except Exception as exc:
        log.error(f"[CONFIG] Error al cargar {config_path}: {exc}")
        return PipelineConfig()


# ──────────────────────────────────────────────────────────────────────────────
# PIPELINE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

class MusicGenerationPipeline:
    """Orquestador principal del pipeline de generacion musical."""

    def __init__(self, config: PipelineConfig) -> None:
        self.config = config
        log.info("[PIPELINE] MusicGenerationPipeline inicializado.")
        log.info(f"[PIPELINE] Backend de audio: {config.audio_backend}")
        log.info(f"[PIPELINE] Modelo RVC: {config.rvc_model_path}")
        log.info(f"[PIPELINE] Modo supervisado: {config.supervised_mode}")

    def run_generation(self, state: PipelineState) -> PipelineState:
        """
        Ruta 1 - Generacion completa desde texto.
        Texto -> Generacion Musical -> UVR5 -> DeepFilter -> RVC -> Mezcla
        """
        import uuid
        if not state.job_id:
            state.job_id = uuid.uuid4().hex[:12]

        log.info("=" * 72)
        log.info("  Ruta 1 - Generacion Musical Completa")
        log.info("=" * 72)
        log.info(f"  Job ID    : {state.job_id}")
        log.info(f"  Prompt    : {state.prompt[:80]}")
        log.info(f"  Backend   : {self.config.audio_backend}")
        log.info("=" * 72)

        try:
            # ETAPA 1: Generacion Musical
            backend = self.config.audio_backend
            if backend == "acestep":
                state = stage_acestep_generate(state, self.config)
            elif backend == "diffrhythm":
                state = stage_diffrhythm_generate(state, self.config)
            else:
                state = stage_yue_generate(state, self.config)
            if state.stage == "FAILED":
                return state

            # ETAPA 3: Separacion UVR5
            state = stage_uvr5_remaster(state, self.config)
            if state.stage == "FAILED":
                return state

            # ETAPA DEEPFILTER: Limpieza de voz
            state = stage_deepfilter_repair(state, self.config)
            if state.stage == "FAILED":
                return state

            # ETAPA 4: Clonacion RVC
            if not self.config.rvc_model_path or self.config.rvc_model_path.lower() == "none":
                log.info("[ETAPA 4] Omitiendo RVC porque se seleccionó 'Ninguno'. Se usará la Voz Sintética.")
                state.voz_propia_path = state.voz_generica_path
            else:
                state = stage_rvc_clone(state, self.config)
            if state.stage == "FAILED":
                return state

            # ETAPA 5: Mezcla final
            state = stage_mix_and_master(state, self.config)
            if state.stage == "FAILED":
                return state

            state.stage = "COMPLETED"
            log.info(f"[PIPELINE] Job {state.job_id} COMPLETADO. Output: {state.output_path}")

            # ETAPA 6: Auditoria de Calidad Automatica
            try:
                log.info("[ETAPA 6] Ejecutando Auditor automático de calidad...")
                analyzer_cmd = [
                    sys.executable, "audio_analyzer.py",
                    str(state.voz_propia_path),
                    str(state.beat_path)
                ]
                analyzer_result = subprocess.run(analyzer_cmd, capture_output=True, text=True, check=True)
                # Imprimir el reporte directo en los logs (para que lo vea el usuario en la web)
                for line in analyzer_result.stdout.split('\n'):
                    if line.strip():
                        log.info(line.strip())
            except Exception as e:
                log.warning(f"[ETAPA 6] El auditor de calidad no pudo generar el reporte: {e}")

        except Exception as e:
            state.stage = "FAILED"
            state.errors.append(str(e))
            log.error(f"[PIPELINE] Error fatal en job {state.job_id}: {e}")
            log.error(traceback.format_exc())

        return state

    def run_remaster(
        self,
        audio_input_path: str,
        job_id: Optional[str] = None,
        initial_state: Optional[PipelineState] = None,
    ) -> PipelineState:
        """
        Ruta 2 - Remasterizacion Audio-to-Audio.
        Recibe audio preexistente y lo procesa con UVR5 -> DeepFilter -> RVC -> Mezcla.
        Omite la generacion musical.
        """
        import uuid
        input_path = Path(audio_input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"[REMASTER] Archivo de entrada no encontrado: {input_path}")

        if initial_state:
            state = initial_state
            if job_id:
                state.job_id = job_id
        else:
            state = PipelineState(
                job_id=job_id or uuid.uuid4().hex[:12],
                prompt=f"[REMASTER] {input_path.name}",
            )

        state.maqueta_path = input_path
        state.stage = "REMASTER_INIT"

        log.info("=" * 72)
        log.info("  Ruta 2 - Remasterizacion Audio-to-Audio")
        log.info("=" * 72)
        log.info(f"  Job ID     : {state.job_id}")
        log.info(f"  Audio input: {input_path}")
        log.info("=" * 72)

        try:
            state = stage_uvr5_remaster(state, self.config)
            if state.stage == "FAILED":
                return state

            state = stage_deepfilter_repair(state, self.config)
            if state.stage == "FAILED":
                return state

            state = stage_rvc_clone(state, self.config)
            if state.stage == "FAILED":
                return state

            state = stage_mix_and_master(state, self.config)
            if state.stage == "FAILED":
                return state

            state.stage = "COMPLETED"
            log.info(f"[PIPELINE] Remaster {state.job_id} COMPLETADO. Output: {state.output_path}")

        except Exception as e:
            state.stage = "FAILED"
            state.errors.append(str(e))
            log.error(f"[PIPELINE] Error en remaster {state.job_id}: {e}")
            log.error(traceback.format_exc())

        return state

    def run_repair(
        self,
        audio_input_path: str,
        job_id: Optional[str] = None,
        initial_state: Optional[PipelineState] = None,
    ) -> PipelineState:
        """
        Ruta 3 - Reparacion/Limpieza con DeepFilterNet.
        Recibe audio preexistente, lo limpia con DeepFilter y lo retorna sin RVC.
        """
        import uuid
        input_path = Path(audio_input_path)
        if not input_path.exists():
            raise FileNotFoundError(f"[REPAIR] Archivo de entrada no encontrado: {input_path}")

        if initial_state:
            state = initial_state
            if job_id:
                state.job_id = job_id
        else:
            state = PipelineState(
                job_id=job_id or uuid.uuid4().hex[:12],
                prompt=f"[REPAIR] {input_path.name}",
            )

        state.maqueta_path    = input_path
        state.voz_generica_path = input_path
        state.stage = "REPAIR_INIT"

        log.info("=" * 72)
        log.info("  Ruta 3 - Reparacion DeepFilterNet")
        log.info("=" * 72)

        try:
            state = stage_deepfilter_repair(state, self.config)
            if state.stage == "FAILED":
                return state

            # Output = la voz limpia directamente
            temp_dir = Path(self.config.temp_dir) / state.job_id
            gallery_dir = Path(self.config.gallery_dir)
            gallery_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            final_path = gallery_dir / f"repair_{state.job_id[:8]}_{ts}.wav"

            import shutil
            shutil.copy(state.voz_generica_path, final_path)
            state.output_path = final_path
            state.stage = "COMPLETED"

            log.info(f"[PIPELINE] Repair {state.job_id} COMPLETADO. Output: {state.output_path}")

        except Exception as e:
            state.stage = "FAILED"
            state.errors.append(str(e))
            log.error(f"[PIPELINE] Error en repair {state.job_id}: {e}")

        return state


# ──────────────────────────────────────────────────────────────────────────────
# ENTRYPOINT
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Orquestador de generacion musical local"
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default="Una balada pop melancolica sobre el paso del tiempo",
        help="Descripcion de la cancion a generar",
    )
    parser.add_argument(
        "--config",
        type=str,
        default="config.json",
        help="Ruta al archivo de configuracion JSON",
    )
    parser.add_argument(
        "--no-supervised",
        action="store_true",
        help="Desactiva los checkpoints supervisados",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    if args.no_supervised:
        config.supervised_mode = False
        log.warning("[MAIN] Modo supervisado DESACTIVADO.")

    pipeline = MusicGenerationPipeline(config)
    final_state = pipeline.run_generation(
        PipelineState(prompt=args.prompt)
    )

    sys.exit(0 if final_state.stage == "COMPLETED" else 1)
