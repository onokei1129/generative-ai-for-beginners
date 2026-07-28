@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  ラベル入力（練習用サンプル）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   デスクトップの「1 セットアップ」を先に実行してください。
    echo.
    pause
    exit /b 1
)

if not exist "poc\practice\scan_001.jpg" (
    echo 練習用サンプルが無いので、いまここで作ります...
    echo.
    .venv\Scripts\python -m poc.receipts --out .\poc\practice
    if errorlevel 1 (
        echo.
        echo [エラー] サンプルを作れませんでした。
        pause
        exit /b 1
    )
    echo.
)

echo ブラウザが自動で開きます。開かないときは次を手で開いてください。
echo   http://127.0.0.1:8100/
echo.
echo 終了するときは、この黒い画面で Ctrl-C を押すか、ウィンドウを閉じてください。
echo.

.venv\Scripts\python poc\label.py .\poc\practice

echo.
pause
