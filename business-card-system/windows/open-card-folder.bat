@echo off
setlocal
cd /d "%~dp0..\app"

rem 仕分け結果の確認用。「不明」フォルダと一覧を開くだけ。

if not exist "poc\real-cards" (
    echo [エラー] 名刺のフォルダがありません: "%CD%\poc\real-cards"
    echo   先に「4 名刺を仕分ける」を実行してください。
    echo.
    pause
    exit /b 1
)

rem 窓は1つだけ開く。以前は real-cards と その中の unknown を別々に
rem 開いていたため、見た目のほとんど同じ窓が2枚並んで紛らわしかった
rem （実テストで報告）。`/select` なら1つの窓の中で unknown を選んだ
rem 状態にできる。
echo 名刺フォルダを開きます: %CD%\poc\real-cards
if exist "poc\real-cards\unknown" goto :open_with_unknown
explorer "%CD%\poc\real-cards"
goto :opened

:open_with_unknown
echo 「不明」フォルダを選んだ状態で開きます。名刺なら1つ上へ移してください。
explorer /select,"%CD%\poc\real-cards\unknown"

:opened

if exist "sort.md" (
    echo 仕分けの一覧も開きます: "%CD%\sort.md"
    start "" "%CD%\sort.md"
)

echo.
echo 開いたら、この画面は閉じて構いません。
timeout /t 5 >nul
