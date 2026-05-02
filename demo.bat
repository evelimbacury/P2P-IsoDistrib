@echo off
title P2P-IsoDistrib Demo
cd /d "%~dp0"

echo ============================================================
echo   P2P-IsoDistrib - Experimento de Download Paralelo
echo ============================================================
echo.

REM Garante que o ISO de teste existe (500 MB)
.venv\bin\python scripts\create_test_iso.py

REM Limpa download anterior se existir
.venv\bin\python -c "import os; os.remove('downloads/test.iso') if os.path.exists('downloads/test.iso') else None; print('[Demo] downloads/ limpo')"

echo.
echo Abrindo terminais...
echo   [1] Tracker
echo   [2] Peer 6000 - publica test.iso automaticamente
echo   [3] Peer 6001 - publica test.iso automaticamente
echo   [4] Peer 6002 - baixa test.iso automaticamente
echo.

REM Terminal 1: Tracker
start "Tracker" cmd /k "cd /d %~dp0 && .venv\bin\python -m src.tracker.tracker"

timeout /t 2 /nobreak > nul

REM Terminal 2: Peer 6000 - publica automaticamente
start "Peer 6000 [Publicador]" cmd /k "cd /d %~dp0 && .venv\bin\python scripts\demo_peer.py --port 6000 --auto publish shared_files/test.iso"

timeout /t 1 /nobreak > nul

REM Terminal 3: Peer 6001 - publica automaticamente
start "Peer 6001 [Publicador]" cmd /k "cd /d %~dp0 && .venv\bin\python scripts\demo_peer.py --port 6001 --auto publish shared_files/test.iso"

REM Aguarda peers computarem SHA256 do 500 MB e registrarem no tracker
timeout /t 8 /nobreak > nul

REM Terminal 4: Peer 6002 - baixa automaticamente
start "Peer 6002 [Downloader]" cmd /k "cd /d %~dp0 && .venv\bin\python scripts\demo_peer.py --port 6002 --auto download test.iso"

echo Experimento iniciado! Acompanhe os 4 terminais.
echo.
echo Quando o download terminar, rode para verificar a integridade:
echo   .venv\bin\python scripts\verify.py
echo.
pause
