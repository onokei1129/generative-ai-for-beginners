@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  ラベル入力（練習用サンプル）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

if not exist "poc\practice\scan_001.jpg" (
    echo [エラー] 練習用サンプルがありません。
    echo   先に「練習サンプルを作る」を実行してください。
    echo.
    pause
    exit /b 1
)

echo ブラウザが自動で開きます。開かない場合は
echo   http://127.0.0.1:8100/
echo を手で開いてください。
echo.
echo 終了するときは、この黒い画面で Ctrl-C を押すか、ウィンドウを閉じてください。
echo.

.venv\Scripts\python poc\label.py .\poc\practice

echo.
pause
