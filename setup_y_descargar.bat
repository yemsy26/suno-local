@echo off
chcp 65001 >nul
SETLOCAL EnableDelayedExpansion
title Suno Local - Descarga de Modelos

echo.
echo  ====================================================================
echo   SUNO LOCAL - SETUP Y DESCARGA DE MODELOS
echo   RTX 4060 ^| Python 3.11 ^| CUDA 12.1
echo  ====================================================================
echo.
echo  OPCIONAL: Para descargar modelos gated de HuggingFace,
echo  define tu token antes de ejecutar este .bat:
echo    set HF_TOKEN=hf_xxxxxxxxxxxxxxxxx
echo.
IF "%HF_TOKEN%"=="" (
    echo  [i] HF_TOKEN no definido. Se usaran solo repos publicos.
) ELSE (
    echo  [OK] HF_TOKEN detectado.
)
echo.

:: Directorio del script (raíz del proyecto)
SET "ROOT=%~dp0"
SET "VENV=%ROOT%.venv_py311"
SET "PYTHON=%VENV%\Scripts\python.exe"
SET "UV=%USERPROFILE%\AppData\Roaming\Python\Python314\Scripts\uv.exe"

:: ── Paso 1: Verificar entorno virtual ────────────────────────────────────────
echo  [1/4] Verificando entorno virtual Python 3.11...
IF NOT EXIST "%PYTHON%" (
    echo  [!] Entorno virtual no encontrado en: %VENV%
    echo  [*] Creando entorno con uv...
    IF NOT EXIST "%UV%" (
        echo  [✗] uv.exe no encontrado. Instala uv con:
        echo       pip install uv
        pause
        exit /b 1
    )
    "%UV%" venv --python 3.11 "%VENV%"
    IF ERRORLEVEL 1 (
        echo  [✗] Error creando el entorno virtual.
        pause
        exit /b 1
    )
    echo  [✓] Entorno creado.
) ELSE (
    echo  [✓] Entorno virtual encontrado.
)

:: ── Paso 2: Instalar PyTorch CUDA 12.1 ───────────────────────────────────────
echo.
echo  [2/4] Verificando PyTorch con soporte CUDA 12.1...
"%PYTHON%" -c "import torch; assert torch.cuda.is_available(), 'No CUDA'" >nul 2>&1
IF ERRORLEVEL 1 (
    echo  [*] Instalando PyTorch 2.5.1+cu121 (puede tardar unos minutos)...
    "%UV%" pip install --python "%PYTHON%" ^
        torch torchvision torchaudio ^
        --index-url https://download.pytorch.org/whl/cu121
    IF ERRORLEVEL 1 (
        echo  [✗] Error instalando PyTorch con CUDA.
        pause
        exit /b 1
    )
) ELSE (
    echo  [✓] PyTorch + CUDA ya instalados.
)

:: ── Paso 3: Instalar dependencias del proyecto ────────────────────────────────
echo.
echo  [3/4] Instalando dependencias del proyecto (requirements.txt)...
"%UV%" pip install --python "%PYTHON%" -r "%ROOT%requirements.txt" ^
    --quiet
IF ERRORLEVEL 1 (
    echo  [!] Algunos paquetes fallaron (verifica requirements.txt)
) ELSE (
    echo  [✓] Dependencias instaladas.
)

:: ── Paso 4: Descargar modelos ─────────────────────────────────────────────────
echo.
echo  [4/4] Descargando modelos de IA...
echo.
"%PYTHON%" "%ROOT%download_models.py"
IF ERRORLEVEL 1 (
    echo.
    echo  [!] Algunos modelos no pudieron descargarse automaticamente.
    echo      Revisa los mensajes anteriores para instrucciones manuales.
)

:: ── Verificación final GPU ────────────────────────────────────────────────────
echo.
echo  ── Verificacion final de GPU ──────────────────────────────
"%PYTHON%" "%ROOT%check_gpu.py"

echo.
echo  ╔══════════════════════════════════════════════════════════╗
echo  ║  Setup completado. Para arrancar el servidor:            ║
echo  ║                                                          ║
echo  ║    .venv_py311\Scripts\python.exe api.py                 ║
echo  ╚══════════════════════════════════════════════════════════╝
echo.
pause
