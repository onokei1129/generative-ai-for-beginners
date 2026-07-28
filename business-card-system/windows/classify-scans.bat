@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0..\app"

echo ============================================
echo  スキャンフォルダから名刺だけを取り出す
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

where tesseract >nul 2>&1
if errorlevel 1 (
    echo [エラー] tesseract が見つかりません。仕分けには必要です。
    echo.
    echo   https://github.com/UB-Mannheim/tesseract/wiki からインストールし、
    echo   Japanese と Japanese ^(vertical^) を選んでください。
    echo   入れたあとに反応しない場合は、この画面を閉じて開き直してください。
    echo.
    pause
    exit /b 1
)

set "SCANDIR=%USERPROFILE%\Dropbox\ScanSnap"
echo 既定の読み込み元: %SCANDIR%
echo.
set /p "INPUT=別のフォルダを使う場合はパスを入力（そのままEnterで既定）: "
if not "!INPUT!"=="" set "SCANDIR=!INPUT!"

if not exist "!SCANDIR!" (
    echo.
    echo [エラー] フォルダが見つかりません: !SCANDIR!
    echo.
    pause
    exit /b 1
)

echo.
echo 読み込み元: !SCANDIR!
echo 書き出し先: %CD%\poc\real-cards
echo.
echo 判定には1枚あたり数秒かかります。枚数が多い場合はしばらくお待ちください。
echo.

.venv\Scripts\python poc\classify.py "!SCANDIR!" --copy-to .\poc\real-cards --copy-unknown --csv sort.csv --report sort.md
if errorlevel 1 (
    echo.
    echo [エラー] 仕分けに失敗しました。
    pause
    exit /b 1
)

echo.
echo ============================================
echo  結果は次のファイルにあります。
echo    %CD%\sort.md    （一覧）
echo    %CD%\sort.csv   （Excelで開けます）
echo.
echo  「不明」と判定された画像は
echo    %CD%\poc\real-cards\unknown
echo  に入っています。名刺なら1つ上のフォルダへ移してください。
echo.
echo  次は「5 仕分け結果を確認する」を実行してください。
echo  （不明フォルダと一覧が開きます。振り分けが済んだら「6 ラベル入力」へ）
echo ============================================
echo.
pause
