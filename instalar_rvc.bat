@echo off
chcp 65001 >nul
title Suno Local - Instalador RVC

echo ====================================================================
echo  SISTEMA DE CLONACION RVC - GUIA DE INSTALACION
echo ====================================================================
echo.
echo Para que el sistema de Clonacion de Voz (Tu propia Voz) funcione,
echo necesitas el ejecutable oficial rvc-cli.exe, el cual no se
echo incluye por defecto debido a su gran tamano y conflictos de Python.
echo.
echo PASOS PARA ACTIVARLO:
echo 1. Ve a GitHub y descarga el proyecto oficial de RVC-CLI.
echo 2. Copia el archivo rvc-cli.exe y pegalo exactamente en esta ruta:
echo    %~dp0.venv_py311\Scripts\rvc-cli.exe
echo.
echo Una vez que el archivo rvc-cli.exe este en esa carpeta, el cerebro
echo de Suno Local lo detectara automaticamente y dejara de ignorar tu voz.
echo.
echo ====================================================================
pause
