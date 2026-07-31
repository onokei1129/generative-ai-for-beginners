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

rem --------------------------------------------------------------------
rem どの複製の、どの版を動かしているのか。
rem
rem 実テストで、更新したフォルダと、デスクトップのショートカットが指す
rem フォルダが食い違い、最新版に直したはずの不具合が直らない状態が続いた。
rem 画面の文言だけでは双方とも気づけないので、ここで突き合わせられるように
rem しておく。
rem --------------------------------------------------------------------
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

echo --------------------------------------------
echo  どの複製を動かしているか
echo --------------------------------------------
echo 場所:     %HERE%

set "REV="
set "BRANCH="
for /f "delims=" %%v in ('git -C "%HERE%" rev-parse --short HEAD 2^>nul') do set "REV=%%v"
for /f "delims=" %%b in ('git -C "%HERE%" rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
if not defined REV set "REV=不明（git が無いか、作業フォルダではありません）"
if not defined BRANCH set "BRANCH=不明"
echo 版:       %REV%
echo ブランチ: %BRANCH%

rem origin より遅れていないか。取得に少し時間がかかる。
set "BEHIND="
git -C "%HERE%" fetch origin "%BRANCH%" >nul 2>&1
for /f "delims=" %%n in ('git -C "%HERE%" rev-list --count HEAD..origin/%BRANCH% 2^>nul') do set "BEHIND=%%n"
if not defined BEHIND set "BEHIND=?"
echo 未取得:   %BEHIND% 件
if not "%BEHIND%"=="0" echo   → 「名刺 1 準備する」を押すと最新版になります。
echo.

rem --------------------------------------------------------------------
rem デスクトップのショートカットが、どのフォルダを指しているか。
rem ここが上の「場所」と違っていれば、複製の食い違いが原因。
rem --------------------------------------------------------------------
set "DESKTOP="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%d"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"

echo --------------------------------------------
echo  デスクトップのショートカットの飛び先
echo --------------------------------------------
echo デスクトップ: %DESKTOP%
powershell -NoProfile -Command "$sh=New-Object -ComObject WScript.Shell; $found=$false; @('%DESKTOP%','%DESKTOP%\名刺システム') | Where-Object { Test-Path -LiteralPath $_ } | ForEach-Object { Get-ChildItem -LiteralPath $_ -Filter '*.lnk' -ErrorAction SilentlyContinue } | ForEach-Object { $found=$true; '  {0}' -f $_.Name; '    -> {0}' -f $sh.CreateShortcut($_.FullName).TargetPath }; if (-not $found) { '  （ショートカットが見つかりません）' }"
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
