@echo off
title Dove lo AI messo - Emulatore Android
echo ========================================================
echo Avvio Emulatore Android Pixel 8 per Dove lo AI messo...
echo ========================================================

set EMULATOR=%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe
set ADB=%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe
set APK=%~dp0android\app\build\outputs\apk\debug\app-debug.apk

if not exist "%EMULATOR%" (
    echo [ERRORE] Emulatore non trovato in: %EMULATOR%
    pause
    exit /b 1
)

echo [1/4] Apertura finestra emulatore Pixel_8_API_31...
start "" "%EMULATOR%" -avd Pixel_8_API_31

echo [2/4] Attesa avvio del dispositivo Android...
"%ADB%" wait-for-device

:wait_boot
for /f "tokens=*" %%i in ('"%ADB%" shell getprop sys.boot_completed 2^>nul') do set BOOT=%%i
if not "%BOOT%"=="1" (
    timeout /t 2 /nobreak >nul
    goto wait_boot
)

echo [3/4] Collegamento porta 8000 al PC...
"%ADB%" reverse tcp:8000 tcp:8000

echo [4/4] Avvio di Dove lo AI messo sullo schermo...
"%ADB%" install -r "%APK%" >nul 2>&1
"%ADB%" shell am start -n com.doveloaimesso.app/.MainActivity

echo.
echo ========================================================
echo APP AVVIATA CON SUCCESSO!
echo Puoi usare l'app nella finestra del telefono Pixel 8.
echo Password predefinita del Caveau: 1234
echo ========================================================
pause
