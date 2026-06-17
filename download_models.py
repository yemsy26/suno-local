"""
download_models.py
# ═══════════════════════════════════════════════════════════════════
Descarga automática de modelos base para Suno Local
  - MDX-Net_Inst_HQ_3.onnx  → models/uvr5/
  - Carpeta RVC              → models/rvc/  (vacía, listo para pegar .pth)
# ═══════════════════════════════════════════════════════════════════
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
import urllib.request
import urllib.error
from pathlib import Path

# Force UTF-8 output on Windows to avoid cp1252 encode errors
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _bar(count, block_size, total_size):
    """Progress bar simple para urllib.request.urlretrieve."""
    downloaded = count * block_size
    if total_size > 0:
        pct = min(downloaded / total_size * 100, 100)
        mb_done = downloaded / (1024 ** 2)
        mb_total = total_size / (1024 ** 2)
        bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
        print(f"\r    [{bar}] {pct:5.1f}%  {mb_done:.1f}/{mb_total:.1f} MB", end="", flush=True)
    else:
        mb_done = downloaded / (1024 ** 2)
        print(f"\r    Descargado: {mb_done:.1f} MB", end="", flush=True)


def download_file(url: str, dest: Path, description: str = "") -> bool:
    """Descarga `url` en `dest`. Retorna True si tuvo éxito."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 1024:
        print(f"  [✓] {dest.name} ya existe ({dest.stat().st_size / (1024**2):.1f} MB). Saltando.")
        return True

    label = description or dest.name
    print(f"\n  [↓] Descargando: {label}")
    print(f"      URL: {url}")
    try:
        urllib.request.urlretrieve(url, dest, reporthook=_bar)
        print()  # salto de línea tras la barra
        size_mb = dest.stat().st_size / (1024 ** 2)
        print(f"  [✓] Descarga completada: {dest} ({size_mb:.1f} MB)")
        return True
    except urllib.error.HTTPError as e:
        print(f"\n  [✗] HTTP {e.code}: {e.reason}  →  {url}")
        return False
    except Exception as e:
        print(f"\n  [✗] Error: {e}")
        return False


def uv_pip_install(*packages: str) -> bool:
    """
    Instala paquetes usando 'uv pip install' (compatible con entornos uv sin pip).
    Retorna True si tuvo éxito.
    """
    # Buscar uv: primero en PATH, luego en la ubicación habitual de Windows
    uv_candidates = [
        "uv",
        str(Path.home() / "AppData" / "Roaming" / "Python" / "Python314" / "Scripts" / "uv.exe"),
        str(Path.home() / ".cargo" / "bin" / "uv.exe"),
        str(Path.home() / ".local" / "bin" / "uv"),
    ]

    uv_exe = None
    for candidate in uv_candidates:
        try:
            subprocess.run(
                [candidate, "--version"],
                check=True, capture_output=True
            )
            uv_exe = candidate
            break
        except (FileNotFoundError, subprocess.CalledProcessError):
            continue

    if not uv_exe:
        print("  [✗] No se encontró 'uv'. Instálalo con: pip install uv")
        return False

    venv_python = Path(sys.executable)
    result = subprocess.run(
        [uv_exe, "pip", "install", "--python", str(venv_python), *packages],
        capture_output=False,
    )
    return result.returncode == 0


def ensure_huggingface_hub():
    """Asegura que huggingface_hub esté disponible, instalándolo si no lo está."""
    try:
        import huggingface_hub
        return True
    except ImportError:
        print("  [*] Instalando huggingface_hub via uv...")
        if uv_pip_install("huggingface_hub"):
            try:
                import importlib
                import huggingface_hub  # noqa: F401
                return True
            except ImportError:
                # Necesita reinicio del proceso en algunos casos
                print("  [*] Relanzando script con huggingface_hub instalado...")
                os.execv(sys.executable, [sys.executable] + sys.argv)
        print("  [✗] No se pudo instalar huggingface_hub.")
        return False


# ── Modelos ───────────────────────────────────────────────────────────────────

def download_uvr5():
    """Descarga el modelo MDX-Net Inst HQ 3 para UVR5."""
    print("\n" + "-" * 60)
    print("  [1/3] MODELO UVR5 - MDX-Net_Inst_HQ_3.onnx")
    print("-" * 60)

    uvr5_dir = Path("models/uvr5")
    uvr5_dir.mkdir(parents=True, exist_ok=True)

    # El filename correcto en el repo publico de Blane187
    dest = uvr5_dir / "MDX-Net_Inst_HQ_3.onnx"
    if dest.exists() and dest.stat().st_size > 1024 * 1024:
        print(f"  [OK] {dest.name} ya existe ({dest.stat().st_size / (1024**2):.1f} MB). Saltando.")
        return True

    if not ensure_huggingface_hub():
        return False

    from huggingface_hub import hf_hub_download

    hf_token = os.environ.get("HF_TOKEN")
    if hf_token:
        print("  [*] Usando token HF_TOKEN para autenticacion.")

    # Intentar con distintos repos publicos
    candidates = [
        # Repo publico de Blane187 con TODOS los modelos UVR
        ("Blane187/all_public_uvr_models", "all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx"),
        # Repo de seanghay (filename ligeramente distinto)
        ("seanghay/uvr_models", "UVR-MDX-NET-Inst_HQ_3.onnx"),
    ]

    for repo_id, filename in candidates:
        print(f"  [*] Intentando: {repo_id} / {filename}")
        try:
            downloaded = hf_hub_download(
                repo_id=repo_id,
                filename=filename,
                local_dir=str(uvr5_dir),
                token=hf_token,
            )
            # Renombrar al nombre canonico esperado por el pipeline
            src = Path(downloaded)
            if src.name != dest.name:
                src.rename(dest)
            print(f"  [OK] Descargado y guardado en: {dest}")
            return True
        except Exception as e:
            print(f"  [!] {repo_id}: {str(e)[:120]}")

    print("  [X] No se pudo descargar MDX-Net automaticamente.")
    print("  Para descarga manual:")
    print("    1. Ve a: https://huggingface.co/Blane187/all_public_uvr_models")
    print("    2. Descarga: all_public_uvr_models/UVR-MDX-NET-Inst_HQ_3.onnx")
    print(f"    3. Guarda el archivo como: {dest.resolve()}")
    return False





def prepare_rvc():
    """Crea la estructura de carpetas para RVC."""
#     print("\n" + "─" * 60)
    print("  [3/3] ESTRUCTURA PARA MODELOS RVC")
#     print("─" * 60)

    rvc_dir = Path("models/rvc")
    rvc_dir.mkdir(parents=True, exist_ok=True)

    readme = rvc_dir / "INSTRUCCIONES.txt"
    readme.write_text(
        "MODELOS RVC\n"
#         "═══════════\n\n"
        "Coloca aquí tus modelos de voz entrenados:\n\n"
        "  voz_propia.pth      ← Pesos del modelo RVC\n"
        "  voz_propia.index    ← Índice FAISS del modelo\n\n"
        "Puedes obtener modelos pre-entrenados de:\n"
        "  https://huggingface.co/search/full-text?q=rvc&type=model\n\n"
        "O entrenar el tuyo usando el repositorio oficial de RVC:\n"
        "  https://github.com/RVC-Project/Retrieval-based-Voice-Conversion-WebUI\n",
        encoding="utf-8"
    )

    pth_exists = list(rvc_dir.glob("*.pth"))
    idx_exists = list(rvc_dir.glob("*.index"))

    if pth_exists:
        print(f"  [✓] Encontrado: {pth_exists[0].name}")
    else:
        print("  [!] No se encontró ningún archivo .pth")
        print("      → Coloca tu modelo en: models/rvc/voz_propia.pth")

    if idx_exists:
        print(f"  [✓] Encontrado: {idx_exists[0].name}")
    else:
        print("  [!] No se encontró ningún archivo .index")
        print("      → Coloca tu índice en: models/rvc/voz_propia.index")

    print(f"  [✓] INSTRUCCIONES.txt escrito en: {readme}")
    return True


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("  SUNO LOCAL – DESCARGA DE MODELOS BASE")
    print(f"  Python: {sys.version.split()[0]}  |  venv: {Path(sys.prefix).name}")
    print("=" * 60)

    results = {
        "UVR5 MDX-Net":   download_uvr5(),
        "RVC (carpetas)": prepare_rvc(),
    }

    print("\n" + "=" * 60)
    print("  RESUMEN FINAL")
    print("=" * 60)
    for name, ok in results.items():
        status = "[✓]" if ok else "[✗]"
        print(f"  {status}  {name}")

    all_ok = all(results.values())
    if all_ok:
        print("\n  ✨ Todos los modelos base están listos. ¡Puedes arrancar el servidor!")
        print("     Ejecuta: python api.py")
    else:
        print("\n  ⚠  Algunos modelos no pudieron descargarse.")
        print("     Revisa los mensajes anteriores y descárgalos manualmente.")

    print("=" * 60)


if __name__ == "__main__":
    main()


