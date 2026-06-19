@echo off
SETLOCAL EnableDelayedExpansion
title Suno Local - Iniciando...

SET "ROOT=%~dp0"
SET "VENV=%ROOT%.venv_py311"
SET "PYTHON=%VENV%\Scripts\python.exe"
SET "API_PORT=8765"
SET "API_URL=http://127.0.0.1:%API_PORT%/health"

cls
echo =========================================================
echo  SUNO LOCAL - Iniciador Automático
echo =========================================================
echo.

echo [1/5] Verificando entorno virtual Python 3.11...
IF NOT EXIST "%PYTHON%" (
    echo [ERROR] Entorno virtual no encontrado.
    echo Ejecuta primero: setup_y_descargar.bat
    pause
    exit /b 1
)

echo [2/5] Verificando GPU... (Omitido temporalmente para evitar cuelgues)
REM "%PYTHON%" -c "import torch; print('CUDA:', torch.cuda.is_available())" >nul 2>&1

echo [3/5] Verificando Ollama...
curl -s --max-time 2 http://localhost:11434/api/tags >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ADVERTENCIA] Ollama no esta corriendo. El paso 1 fallara.
    SET "OLLAMA_WARN=1"
) ELSE (
    SET "OLLAMA_WARN=0"
)

echo [4/5] Iniciando servidor FastAPI...
start "Suno Local - Servidor" cmd /k "cd /d %ROOT% && .venv_py311\Scripts\python.exe api.py"

echo Esperando a que el servidor este listo...
SET /A WAIT_COUNT=0
:WAIT_LOOP
    timeout /t 1 /nobreak >nul
    curl -s --max-time 2 "%API_URL%" >nul 2>&1
    IF NOT ERRORLEVEL 1 GOTO SERVER_READY
    SET /A WAIT_COUNT+=1
    echo ... intento !WAIT_COUNT! de 30
    IF !WAIT_COUNT! GEQ 30 GOTO SERVER_TIMEOUT
GOTO WAIT_LOOP

:SERVER_TIMEOUT
echo [ERROR] El servidor no respondio a tiempo. Revisa la otra ventana.
pause
exit /b 1

:SERVER_READY
echo [5/5] Abriendo navegador...
timeout /t 1 /nobreak >nul
start "" "http://127.0.0.1:%API_PORT%"

echo =========================================================
echo  SISTEMA CORRIENDO EN: http://127.0.0.1:%API_PORT%
echo =========================================================
IF "%OLLAMA_WARN%"=="1" (
    echo RECUERDA INICIAR OLLAMA MANUALMENTE.
)
echo Ya puedes cerrar esta ventana.
timeout /t 5 >nul
