@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  名刺一元管理システム（アプリ本体）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

if not exist "storage\bcards.db" (
    echo 初回起動のため、利用者とデモ用の名刺を用意します...
    echo （tesseract が無い場合はデモ名刺の作成でエラーになりますが、
    echo   利用者は作られるのでそのまま使えます）
    echo.
    .venv\Scripts\python seed.py --demo --count 6
    echo.
)

echo   URL   : http://127.0.0.1:8000/
echo   ID    : admin
echo   パスワード : AdminPass123!
echo.
echo 終了するときは、この黒い画面で Ctrl-C を押すか、ウィンドウを閉じてください。
echo.

rem サーバーが立ち上がってからブラウザを開く
start "" /min cmd /c "timeout /t 5 >nul & explorer http://127.0.0.1:8000/"

.venv\Scripts\python -m uvicorn bcards.main:app --app-dir src --host 127.0.0.1 --port 8000

echo.
pause
