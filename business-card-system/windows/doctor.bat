@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  動かない部品を探す（診断）
echo ============================================
echo.
echo  「OCRを使えませんでした」などのエラーが出るとき、
echo  どの部品が原因かを1つずつ調べます。数分かかります。
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「1 セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

call "%~dp0_check-tesseract.bat"
echo.

.venv\Scripts\python -m poc.doctor

echo.
echo --------------------------------------------
echo  この画面の内容をそのまま共有してください。
echo --------------------------------------------
echo.
pause
