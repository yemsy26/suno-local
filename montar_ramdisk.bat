@echo off
title Montar RAM Disk Z:\
echo ========================================================
echo   SUNO LOCAL - CREADOR DE DISCO EN MEMORIA RAM (ImDisk)
echo ========================================================
echo.
echo Este script creara un disco duro virtual de 4 GB 
echo usando tu memoria RAM para acelerar la IA.
echo.
echo Requiere permisos de Administrador. Si la ventana pide permisos, dile que SI.
echo.

net session >nul 2>&1
if %errorLevel% == 0 (
    echo [OK] Permisos de Administrador detectados.
    goto :crear_disco
) else (
    echo [INFO] Solicitando permisos de Administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c %~dpnx0' -Verb RunAs"
    exit /b
)

:crear_disco
echo Creando disco Z:\ ...
imdisk -a -s 4G -m Z: -p "/fs:ntfs /q /y" >nul 2>&1
if %errorLevel% == 0 (
    echo.
    echo [EXITO] Disco Z:\ creado perfectamente.
    echo Todo el sistema Suno Local ahora correra sobre RAM.
) else (
    echo.
    echo [ERROR] No se pudo crear el disco. Asegurate de tener ImDisk instalado.
)
echo.
pause
