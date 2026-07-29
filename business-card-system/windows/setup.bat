@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  名刺一元管理システム  セットアップ
echo ============================================
echo.
echo 場所: %CD%
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [エラー] Python が見つかりません。
    echo.
    echo   https://www.python.org/downloads/windows/ からインストールしてください。
    echo   インストール時に「Add python.exe to PATH」に必ずチェックを入れてください。
    echo   インストール後、この画面を閉じてもう一度実行してください。
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo Python の実行環境を作っています...
    python -m venv .venv
    if errorlevel 1 (
        echo [エラー] 実行環境を作れませんでした。
        pause
        exit /b 1
    )
) else (
    echo Python の実行環境はすでにあります。
)

echo.
echo 必要な部品をインストールしています（数分かかります）...
echo.
.venv\Scripts\python -m pip install --upgrade pip --quiet
.venv\Scripts\pip install -r requirements.txt
if errorlevel 1 (
    echo.
    echo [エラー] インストールに失敗しました。
    echo   ネットワークにつながっているか確認して、もう一度実行してください。
    pause
    exit /b 1
)

echo.
echo 動作確認をしています...
echo.
.venv\Scripts\python -m pytest tests -q
echo.

echo --------------------------------------------
echo  OCR^(tesseract^)の状態
echo.
rem 他のバッチと同じ確認を使う。PATH に無い場合は既定の場所も探す。
call "%~dp0_check-tesseract.bat"
if errorlevel 1 (
    echo   ラベル入力を試すだけなら、無くても進められます。
    echo   名刺の仕分け^(4^)と精度測定^(8^)には必要です。
) else (
    echo  日本語データを含めて使える状態です。
)
echo --------------------------------------------
echo.

echo ============================================
echo  セットアップが終わりました。
echo.
echo  次は「練習サンプルを作る」を実行してください。
echo ============================================
echo.
pause
