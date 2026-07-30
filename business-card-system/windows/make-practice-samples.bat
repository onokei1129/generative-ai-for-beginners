@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  練習用サンプルを作る
echo ============================================
echo.
echo 名刺16枚と領収書12枚の見本を作ります。
echo 実際の名刺は使いません。ラベル入力の練習用です。
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

if exist "poc\practice\scan_001.jpg" (
    echo すでに練習用サンプルがあります: "%CD%\poc\practice"
    echo.
    choice /c YN /m "作り直しますか（入力済みのラベルは消えます）"
    if errorlevel 2 goto :done
    rmdir /s /q "poc\practice"
)

.venv\Scripts\python -m poc.receipts --out .\poc\practice
if errorlevel 1 (
    echo.
    echo [エラー] サンプルを作れませんでした。
    pause
    exit /b 1
)

:done
echo.
echo ============================================
echo  次は「ラベル入力をひらく」を実行してください。
echo ============================================
echo.
pause
