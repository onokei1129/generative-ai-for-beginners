@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  この1枚がなぜその判定になったのか調べる
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「1 セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

rem 画像やPDFをこのバッチへドラッグ＆ドロップすると %~1 に入る。
rem 無ければ画面で受け取る。
set "TARGET=%~1"
if not defined TARGET (
    echo 調べたいファイルをこの画面へドラッグ＆ドロップして Enter を押してください。
    echo.
    set /p "TARGET=ファイル: "
)

if not defined TARGET (
    echo.
    echo ファイルが指定されていません。
    echo.
    pause
    exit /b 1
)

rem 画面へドロップすると引用符が付くことがあるので外す
set TARGET=%TARGET:"=%

if not exist "%TARGET%" (
    echo.
    echo [エラー] ファイルが見つかりません:
    echo   %TARGET%
    echo.
    pause
    exit /b 1
)

echo.
call "%~dp0_check-tesseract.bat"
echo.

.venv\Scripts\python -m poc.classify "%TARGET%"

echo.
echo --------------------------------------------
echo  判定が違っていたら、上の内容をそのまま共有してください。
echo  「OCRが読んだ文字」が空、または文字化けしていれば、
echo  語の追加では直りません（読み取り自体の問題です）。
echo --------------------------------------------
echo.
pause
