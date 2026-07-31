@echo off
setlocal
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

rem /quiet を付けて呼ぶと一時停止しない（「1 準備する」から呼ぶとき）。
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"

echo ============================================
echo  デスクトップにショートカットを作ります
echo ============================================
echo.

rem --------------------------------------------------------------------
rem デスクトップの場所は Windows 本体に聞く。
rem
rem OneDrive や iCloud Drive で同期していると、%USERPROFILE%\Desktop は
rem 画面に出ているデスクトップとは別のことがある。実テストで、「作成」と
rem 出ているのに画面に現れない状態になった。GetFolderPath は Windows の
rem 設定（フォルダーの移動先）を見るので、同期ソフトの種類に依存しない。
rem --------------------------------------------------------------------
set "DESKTOP="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%d"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" goto :no_desktop

echo デスクトップ: %DESKTOP%
call :make_all "%DESKTOP%"

rem 場所の取得を誤っていても画面に出るよう、素の場所にも置いておく。
rem （同じ場所なら二重に作らない）
set "PLAIN=%USERPROFILE%\Desktop"
if /i "%PLAIN%"=="%DESKTOP%" goto :count
if not exist "%PLAIN%" goto :count
echo 念のためこちらにも: %PLAIN%
call :make_all "%PLAIN%"

:count
set "MADE=0"
for %%f in ("%DESKTOP%\名刺 *.lnk") do set /a MADE+=1
if "%MADE%"=="0" goto :none_made

echo.
echo ============================================
echo  デスクトップに %MADE% 個できました。
echo.
echo  画面に「名刺 1 準備する」から始まるアイコンが並びます。
echo  見当たらないときは、デスクトップで F5 を押してください。
echo.
echo  1 から順に押してください。3 と 4 は何度往復しても構いません。
echo.
echo  仕分けが違っていたとき:
echo    その画像を「名刺 この1枚を調べる」へドラッグ＆ドロップすると、
echo    判定の根拠とOCRが読んだ文字が出ます。
echo.
echo  次からは「名刺 1 準備する」を押すだけで、最新版の取得・
echo  ショートカットの作り直し・セットアップまで終わります。
echo ============================================
echo.
if defined QUIET exit /b 0
pause
exit /b 0

:none_made
echo.
echo ============================================
echo  [エラー] ショートカットが1つも残りませんでした。
echo    場所: "%DESKTOP%"
echo.
echo  上の「デスクトップ:」の場所をエクスプローラで直接開いて、
echo  その行をそのまま共有してください。
echo ============================================
echo.
pause
exit /b 1

:no_desktop
echo [エラー] デスクトップのフォルダが見つかりません: "%DESKTOP%"
pause
exit /b 1


rem --------------------------------------------------------------------
rem 指定した場所へ一式を作る
rem --------------------------------------------------------------------
:make_all
set "TARGET=%~1"

rem 自分が前に作った分だけ消す。`名刺 ` で始まるものに限るので、
rem 利用者が置いた他のショートカットには触れない。
if exist "%TARGET%\名刺 *.lnk" del /q "%TARGET%\名刺 *.lnk"

rem 以前の版はデスクトップに「名刺システム」フォルダを作り、その中へ
rem 入れていた。画面から見えず分かりにくかったため直接置く形に変えた。
rem 古いほうのショートカットを消し、空になったらフォルダも片付ける
rem （rd は空のときだけ消えるので、中身が残っていれば触らない）。
if exist "%TARGET%\名刺システム\*.lnk" del /q "%TARGET%\名刺システム\*.lnk"
if exist "%TARGET%\名刺システム" rd "%TARGET%\名刺システム" 2>nul

rem 押す順に番号を振る。まとめられるものはまとめてある。
rem   1 = 更新 ＋ セットアップ  （更新のあとは必ずセットアップが要る）
rem   2 = 仕分け ＋ 結果を開く  （仕分けたら必ず結果を確認する）
rem   4 = 進み具合 ＋ 精度測定  （測る前に進み具合を出す作りになっている）
rem 練習用はショートカットから外した。windows フォルダの
rem make-practice-samples.bat / label-practice.bat を直接実行できる。
call :make "名刺 1 準備する（更新とセットアップ）" "update.bat"
call :make "名刺 2 名刺を仕分ける"                 "classify-scans.bat"
call :make "名刺 3 ラベル入力"                     "label-real-cards.bat"
call :make "名刺 4 精度を測る"                     "measure-accuracy.bat"
call :make "名刺 アプリを起動"                     "run-app.bat"
call :make "名刺 この1枚を調べる"                  "explain-one.bat"
call :make "名刺 動かないとき（診断）"             "doctor.bat"
exit /b 0

:make
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%TARGET%\%~1.lnk'); $s.TargetPath='%HERE%\%~2'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,76'; $s.Save()"
if errorlevel 1 (
    echo   [失敗] "%~1"
) else (
    echo   作成: "%~1"
)
exit /b 0
