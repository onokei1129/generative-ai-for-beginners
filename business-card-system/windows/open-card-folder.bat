@echo off
setlocal
cd /d "%~dp0..\app"

rem 仕分け結果の確認用。「不明」フォルダと一覧を開くだけ。

if not exist "poc\real-cards" (
    echo [エラー] 名刺のフォルダがありません: %CD%\poc\real-cards
    echo   先に「4 名刺を仕分ける」を実行してください。
    echo.
    pause
    exit /b 1
)

echo 名刺フォルダを開きます: %CD%\poc\real-cards
start "" "%CD%\poc\real-cards"

if exist "poc\real-cards\unknown" (
    echo 「不明」フォルダも開きます。名刺なら1つ上へ移してください。
    start "" "%CD%\poc\real-cards\unknown"
)

if exist "sort.md" (
    echo 仕分けの一覧も開きます: %CD%\sort.md
    start "" "%CD%\sort.md"
)

echo.
echo 開いたら、この画面は閉じて構いません。
timeout /t 5 >nul
