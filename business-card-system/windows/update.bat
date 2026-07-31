@echo off
rem 最新版に更新して、ショートカットを作り直す。
rem
rem 注意: git pull はこのファイル自身も書き換えうる。cmd.exe はバッチを
rem 実行しながら少しずつ読むため、実行中に書き換わると途中から壊れる。
rem そのため一時フォルダへコピーし、そちらから実行し直している。

if "%~1"=="" (
    copy /y "%~f0" "%TEMP%\bcards-update.bat" >nul
    if errorlevel 1 (
        echo [エラー] 一時ファイルを作れませんでした。
        pause
        exit /b 1
    )
    "%TEMP%\bcards-update.bat" "%~dp0."
    exit /b
)

setlocal
set "BCWIN=%~1"

echo ============================================
echo  最新版に更新します
echo ============================================
echo.

where git >nul 2>&1
if errorlevel 1 (
    echo [エラー] git が見つかりません。
    echo   https://git-scm.com/download/win からインストールし、
    echo   この画面を閉じて開き直してください。
    echo.
    pause
    exit /b 1
)

cd /d "%BCWIN%\..\.."
if errorlevel 1 (
    echo [エラー] フォルダへ移動できませんでした: "%BCWIN%\..\.."
    pause
    exit /b 1
)

git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 (
    echo [エラー] ここは git の作業フォルダではありません: "%CD%"
    echo   windows フォルダを移動していませんか。
    echo.
    pause
    exit /b 1
)

echo 対象: %CD%

rem いまのブランチ名を取る
set "BRANCH="
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
if "%BRANCH%"=="" (
    echo [エラー] ブランチ名を取得できませんでした。
    pause
    exit /b 1
)
echo ブランチ: %BRANCH%
echo.

rem 追跡先（upstream）が設定されていないと、引数なしの git pull は
rem "There is no tracking information for the current branch." で止まる。
rem その場合は origin から明示的に取得し、次回以降のために追跡先も設定する。
git rev-parse --abbrev-ref --symbolic-full-name @{u} >nul 2>&1
if errorlevel 1 (
    echo 追跡先が未設定のため、origin/"%BRANCH%" から取得します。
    echo.
    git pull origin "%BRANCH%"
    if not errorlevel 1 git branch --set-upstream-to=origin/%BRANCH% >nul 2>&1
) else (
    git pull
)
if errorlevel 1 (
    echo.
    echo ============================================
    echo  更新できませんでした。
    echo.
    echo  よくある原因:
    echo   ・手元のファイルを書き換えている
    echo       → 名刺の画像やラベルは対象外なので、
    echo         心当たりが無ければ次を実行してください。
    echo           git stash
    echo         そのあともう一度このボタンを押します。
    echo   ・ネットワークにつながっていない
    echo   ・origin にこのブランチが無い
    echo       → 次で作業用ブランチに切り替えてから、もう一度押してください。
    echo           git fetch origin
    echo           git checkout claude/business-card-system-requirements-oznnvt
    echo.
    echo  上の英語のメッセージをそのまま共有していただければ調べられます。
    echo ============================================
    echo.
    pause
    exit /b 1
)

echo.
echo ショートカットを作り直します。
echo.
rem /quiet を付ける。付けないと更新のたびにエクスプローラーの窓が増える。
call "%BCWIN%\create-desktop-shortcuts.bat" /quiet

rem 続けてセットアップまで済ませる。以前は「0 更新」と「1 セットアップ」を
rem 別々に押す必要があったが、更新のあとは必ずセットアップが要るため、
rem 1つにまとめた。/quick は2回目以降の確認テストを省く指定
rem （数分かかるため。初回だけ通しで確認する）。
echo.
call "%BCWIN%\setup.bat" /quick
if errorlevel 1 exit /b 1

echo.
echo ============================================
echo  準備ができました。
echo  デスクトップの「名刺システム」フォルダから
echo  「2 名刺を仕分ける」へ進んでください。
echo ============================================
echo.
echo この画面は8秒後に閉じます。
timeout /t 8 >nul
exit /b 0
