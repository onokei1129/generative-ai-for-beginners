@echo off
setlocal
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

rem /quiet を付けて呼ぶと、フォルダを開かず一時停止もしない。
rem 「0 最新版に更新する」から呼ぶときに使う。付けないと更新のたびに
rem エクスプローラーの窓が1つ増え、押すほど溜まっていく（実テストで発生）。
set "QUIET="
if /i "%~1"=="/quiet" set "QUIET=1"

echo ============================================
echo  デスクトップにショートカットを作ります
echo ============================================
echo.

rem デスクトップの場所は Windows 本体に聞く。
rem
rem OneDrive や iCloud Drive でデスクトップを同期していると、
rem %USERPROFILE%\Desktop は**画面に出ているフォルダとは別**のことがある。
rem 実テストで、「作成」と出ているのにデスクトップに現れない、という状態に
rem なった（左ペインに iCloud Drive\Desktop があった）。
rem GetFolderPath は Windows の設定（フォルダーの移動先）を見るので、
rem どの同期ソフトを使っていても実際の場所が返る。
set "DESKTOP="
for /f "usebackq delims=" %%d in (`powershell -NoProfile -Command "[Environment]::GetFolderPath('Desktop')"`) do set "DESKTOP=%%d"
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" goto :no_desktop
echo デスクトップ: %DESKTOP%
echo.
goto :have_desktop

:no_desktop
echo [エラー] デスクトップのフォルダが見つかりません: "%DESKTOP%"
pause
exit /b 1

:have_desktop

set "FOLDER=%DESKTOP%\名刺システム"
if not exist "%FOLDER%" mkdir "%FOLDER%"

rem 番号が変わったときに古いショートカットが残ると紛らわしいので、
rem このフォルダのショートカット（.lnk）だけ作り直す。
rem 消すのはショートカットのみで、名刺の画像やラベルには一切触れない。
if exist "%FOLDER%\*.lnk" del /q "%FOLDER%\*.lnk"

rem 押す順に番号を振る。まとめられるものはまとめてある。
rem   1 = 更新 ＋ セットアップ      （更新のあとは必ずセットアップが要る）
rem   2 = 仕分け ＋ 結果を開く      （仕分けたら必ず結果を確認する）
rem   4 = 進み具合 ＋ 精度測定      （測る前に進み具合を出す作りになっている）
rem 練習用（練習サンプル・練習ラベル）はショートカットから外した。
rem バッチは windows フォルダに残してあるので、必要なら直接実行できる。
call :make "1 準備する（更新とセットアップ）" "update.bat"
call :make "2 名刺を仕分ける"                 "classify-scans.bat"
call :make "3 ラベル入力"                     "label-real-cards.bat"
call :make "4 精度を測る"                     "measure-accuracy.bat"
call :make "アプリを起動"                     "run-app.bat"
call :make "この1枚を調べる"                  "explain-one.bat"
call :make "動かないとき（診断）"             "doctor.bat"

rem 実際にファイルが残ったか数える。`:make` は PowerShell の戻り値しか
rem 見ていないため、「作成」と出ても同期フォルダの都合で残らないことがある。
set "MADE=0"
for %%f in ("%FOLDER%\*.lnk") do set /a MADE+=1
if "%MADE%"=="0" goto :none_made

echo.
echo ============================================
echo  作成しました: %FOLDER%  ^(%MADE% 個^)
echo.
echo  1 から順に押してください。3 と 4 は何度往復しても構いません。
echo.
echo  仕分けが違っていたとき:
echo    その画像を「この1枚を調べる」へドラッグ＆ドロップすると、
echo    判定の根拠とOCRが読んだ文字が出ます。
echo.
echo  次からは「1 準備する」を押すだけで、最新版の取得・
echo  ショートカットの作り直し・セットアップまで終わります。
echo ============================================
echo.

rem 呼び出し元が案内を出す場合は、ここでは開かない・止めない
if defined QUIET exit /b 0
goto :open_folder

:none_made
echo.
echo ============================================
echo  [エラー] ショートカットが1つも残りませんでした。
echo    場所: "%FOLDER%"
echo.
echo  デスクトップを同期している場合（OneDrive / iCloud Drive など）、
echo  上に出ている「デスクトップ:」の場所を直接開いて確認してください。
echo  そこに入っていれば、同期の設定側の問題です。
echo ============================================
echo.
pause
exit /b 1

:open_folder

rem 自分でこのバッチを押したときは必ず開く。窓が溜まって困るのは
rem 「1 準備する」から呼ばれる側（/quiet）で、そちらは開かない。
rem 一度「初回だけ開く」にしたところ、押しても何も起きないように見えた。
echo 作ったフォルダを開きます。
explorer "%FOLDER%"
echo.
pause
exit /b 0

:make
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%FOLDER%\%~1.lnk'); $s.TargetPath='%HERE%\%~2'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,76'; $s.Save()"
if errorlevel 1 (
    echo   [失敗] "%~1"
) else (
    echo   作成: "%~1"
)
exit /b 0
