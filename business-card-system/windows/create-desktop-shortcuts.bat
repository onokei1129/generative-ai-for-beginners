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

rem OneDrive でデスクトップが同期されている場合はそちらを使う
set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%OneDrive%\Desktop" set "DESKTOP=%OneDrive%\Desktop"
if not exist "%DESKTOP%" (
    echo [エラー] デスクトップのフォルダが見つかりません: "%DESKTOP%"
    pause
    exit /b 1
)

set "FOLDER=%DESKTOP%\名刺システム"

rem フォルダを開くのは**初回だけ**。作り直すたびに開くと窓が溜まる。
rem 2回目以降は場所を文字で出すだけにする（デスクトップにあるので迷わない）。
set "FIRST="
if not exist "%FOLDER%" set "FIRST=1"
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

echo.
echo ============================================
echo  作成しました: %FOLDER%
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
if defined FIRST explorer "%FOLDER%"
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
