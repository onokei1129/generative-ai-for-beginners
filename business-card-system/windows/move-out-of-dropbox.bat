@echo off
setlocal enabledelayedexpansion
chcp 932 >nul

rem このアプリを、同期フォルダ（Dropbox / OneDrive など）の外へ写す。
rem
rem なぜ必要か:
rem   同期フォルダの中で動かすと、サーバーが記録を何も残さずに消える。
rem   Python 本体も部品も、必要な部分をそのつどファイルから読み出している。
rem   同期ソフトがその同じファイルを掴んでいる間に読み直しに失敗すると、
rem   OS がその場でプロセスを消す。例外ではないので後始末も走らない。
rem   落ちた記録が空のまま、落ちる場所が毎回ちがうのは、そのためである。
rem
rem 方針:
rem   **元は消さない。** 写すだけにする。新しい場所で動くことを確かめて
rem   から、元をご自分で消していただく。写している途中で電源が落ちても、
rem   元がそのまま残っていれば、いつでも今までどおり使える。

set "SRC=%~dp0.."
for %%I in ("%SRC%") do set "SRC=%%~fI"
set "DEST=%~1"
if "%DEST%"=="" set "DEST=C:\名刺管理アプリケーション"

echo ============================================
echo  同期フォルダの外へ写します
echo ============================================
echo.
echo  いまの場所 : %SRC%
echo  写す先     : %DEST%
echo.

rem 写す先が同期フォルダの中では、意味がない。
echo %DEST% | findstr /i "Dropbox OneDrive iCloud" >nul
if not errorlevel 1 (
    echo [中止] 写す先も同期フォルダの中です。
    echo   同期していない場所を指定してください。例:
    echo     move-out-of-dropbox.bat C:\名刺管理アプリケーション
    echo.
    pause
    exit /b 1
)

if exist "%DEST%\app\poc\label.py" (
    echo [注意] 写す先には、すでにこのアプリがあります。
    echo   上書きすると、そちらで入力した内容が消えるおそれがあります。
    echo.
    set /p "GO=上書きして続けますか。よろしければ y を入力してください: "
    if /i not "!GO!"=="y" (
        echo 中止しました。
        pause
        exit /b 1
    )
)

echo  写す途中でも、いまの場所はそのまま残ります。
echo  新しい場所で動くのを確かめてから、いまの場所を消してください。
echo.
set /p "GO=始めてよろしければ y を入力してください: "
if /i not "!GO!"=="y" (
    echo 中止しました。
    pause
    exit /b 1
)

echo.
echo 写しています（数分かかります）...
echo.

rem .venv は写さない。仮想環境には元の場所が焼き込まれており、
rem 写しても動かない。新しい場所で作り直す。
rem __pycache__ と .pytest_cache も作り直せるので写さない。
robocopy "%SRC%" "%DEST%" /E /R:2 /W:2 /NFL /NDL /NJH /NJS ^
    /XD ".venv" "__pycache__" ".pytest_cache" ".git"

rem robocopy は 0～7 が成功。8 以上が失敗。
rem ここを errorlevel 1 で見ると、正常に写せたのに失敗と出る。
if errorlevel 8 (
    echo.
    echo [エラー] 写せませんでした。
    echo   空き容量とアクセス権を確かめて、もう一度実行してください。
    echo   いまの場所はそのまま残っています。
    echo.
    pause
    exit /b 1
)

echo.
echo 写し終わりました。新しい場所で Python を用意します...
echo.

pushd "%DEST%\windows"
call setup.bat /quick
set "SETUP_RESULT=%ERRORLEVEL%"
popd

if not "%SETUP_RESULT%"=="0" (
    echo.
    echo [注意] 新しい場所での用意が最後まで終わりませんでした。
    echo   %DEST%\windows\setup.bat を直接実行してみてください。
    echo   いまの場所はそのまま残っているので、それまでは今までどおり使えます。
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================
echo  写し終わりました
echo ============================================
echo.
echo  新しい場所: %DEST%
echo.
echo  このあと:
echo    1. %DEST%\windows\menu.bat を開いて、動くことを確かめてください。
echo    2. デスクトップの近道は古い場所を指しています。
echo       %DEST%\windows\create-desktop-shortcuts.bat
echo       を実行して作り直してください。
echo    3. 確かめたあと、古い場所をご自分で消してください:
echo       %SRC%
echo.
echo  ** 古い場所は消していません。** 確かめるまで残しておいてください。
echo.
pause
