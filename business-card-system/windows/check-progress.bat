@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  ラベル入力の進み具合
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「1 セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

.venv\Scripts\python -m poc.progress .\poc\real-cards

echo.
pause
