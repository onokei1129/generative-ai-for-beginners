@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  OCRの精度を測る
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「1 セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

if not exist "poc\real-cards" (
    echo [エラー] 名刺のフォルダがありません: "%CD%\poc\real-cards"
    echo   先に「4 名刺を仕分ける」を実行してください。
    echo.
    pause
    exit /b 1
)

call "%~dp0_check-tesseract.bat"
if errorlevel 1 (
    pause
    exit /b 1
)

echo まず、入力の進み具合を確認します。
echo.
.venv\Scripts\python -m poc.progress .\poc\real-cards
if errorlevel 2 (
    echo.
    pause
    exit /b 1
)

echo.
set /p "GO=このまま精度を測りますか？ 測る場合は Enter、やめる場合は n を入力: "
if /i "%GO%"=="n" exit /b 0

echo.
echo 測定中です。1枚あたり数秒かかります。
echo.

.venv\Scripts\python poc\runner.py --real .\poc\real-cards --out real-rule.md
if errorlevel 1 (
    echo.
    echo [エラー] 測定に失敗しました。上の内容をそのまま共有してください。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  結果: %CD%\real-rule.md
echo ============================================
echo.
set /p "OPEN=結果を開きますか？ 開く場合は Enter、閉じる場合は n: "
if /i not "%OPEN%"=="n" start "" "%CD%\real-rule.md"
pause
