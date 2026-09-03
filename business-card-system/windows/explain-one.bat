@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  この1枚がなぜその判定になったのか調べる
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" goto :no_venv

rem 画像やPDFをこのバッチへドラッグ＆ドロップすると %~1 に入る。
rem 無ければ画面で受け取る。
set "TARGET=%~1"
if defined TARGET goto :got_target
echo 調べたいファイルをこの画面へドラッグ＆ドロップして Enter を押してください。
echo.
set /p "TARGET=ファイル: "

:got_target
if not defined TARGET goto :no_target

rem 画面へドロップすると引用符が付くことがあるので外す
set TARGET=%TARGET:"=%

rem 注意: この先で %TARGET% を丸括弧のブロック（ if ... ^( ^) ）の中に
rem 置いてはいけない。名刺のファイル名は「(会社名)_山田 太郎.pdf」のように
rem 丸括弧を含むことがあり、展開された ^) がブロックの終わりと解釈されて
rem コマンドプロンプトごと落ちる。goto で分岐すればこの問題は起きない。
if not exist "%TARGET%" goto :not_found

echo.
call "%~dp0_check-tesseract.bat"
echo.

.venv\Scripts\python -m poc.classify "%TARGET%"

echo.
echo --------------------------------------------
echo  判定が違っていたら、上の内容をそのまま共有してください。
echo  「OCRが読んだ文字」が空、または文字化けしていれば、
echo  語の追加では直りません（読み取り自体の問題です）。
echo --------------------------------------------
echo.
pause
exit /b 0

:no_venv
echo [エラー] セットアップがまだです。
echo   先に「1 セットアップ」を実行してください。
echo.
pause
exit /b 1

:no_target
echo.
echo ファイルが指定されていません。
echo.
pause
exit /b 1

:not_found
echo.
echo [エラー] ファイルが見つかりません:
echo   "%TARGET%"
echo.
pause
exit /b 1
