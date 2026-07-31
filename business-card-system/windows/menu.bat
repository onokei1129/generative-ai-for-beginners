@echo off
rem 名刺システムの入口。デスクトップに置くアイコンはこれ1つ。
rem
rem 以前はやることの数だけショートカットを並べていた（7～8個）。実テストで
rem 「デスクトップが雑然としてしまった」という報告になったため、1つにまとめ、
rem 番号で選ぶ形にした。
rem
rem 注意: 「1 準備する」は git pull を行い、このファイル自身も書き換えうる。
rem cmd.exe はバッチを実行しながら少しずつ読むため、実行中に書き換わると
rem 途中から壊れる。そのため一時フォルダへ写し、そちらから動かす。

if /i "%~1"=="/run" goto :prep

copy /y "%~f0" "%TEMP%\bcards-menu.bat" >nul
if errorlevel 1 goto :prep_here
"%TEMP%\bcards-menu.bat" /run "%~dp0."
exit /b

rem 写しを作れないときは、そのまま動かす（更新を選ぶまでは支障ない）。
:prep_here
set "SRC=%~dp0."
goto :start

:prep
set "SRC=%~2"

:start
setlocal
set "HERE=%SRC%"
if "%HERE:~-1%"=="." set "HERE=%HERE:~0,-1%"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
title 名刺システム

:menu
cls
set "REV="
for /f "delims=" %%v in ('git -C "%HERE%" rev-parse --short HEAD 2^>nul') do set "REV=%%v"
if not defined REV set "REV=不明"

echo ============================================
echo  名刺システム
echo ============================================
echo  場所: %HERE%
echo  版:   %REV%
echo.
echo   1  準備する（最新版の取得とセットアップ）
echo   2  名刺を仕分ける
echo   3  ラベル入力
echo   4  精度を測る
echo.
echo   5  アプリを起動
echo   6  この1枚を調べる
echo   7  動かないとき（診断）
echo.
echo   0  閉じる
echo.
echo  はじめてのときは 1 から順に。3 と 4 は何度往復しても構いません。
echo.

set "CHOICE="
set /p "CHOICE=番号を入れて Enter: "

if "%CHOICE%"=="1" goto :do_1
if "%CHOICE%"=="2" goto :do_2
if "%CHOICE%"=="3" goto :do_3
if "%CHOICE%"=="4" goto :do_4
if "%CHOICE%"=="5" goto :do_5
if "%CHOICE%"=="6" goto :do_6
if "%CHOICE%"=="7" goto :do_7
if "%CHOICE%"=="0" exit /b 0
if not defined CHOICE goto :menu
echo.
echo  1 から 7 か 0 を入れてください。
echo.
pause
goto :menu

:do_1
call "%HERE%\update.bat"
goto :menu

:do_2
call "%HERE%\classify-scans.bat"
goto :menu

:do_3
call "%HERE%\label-real-cards.bat"
goto :menu

:do_4
call "%HERE%\measure-accuracy.bat"
goto :menu

:do_5
call "%HERE%\run-app.bat"
goto :menu

:do_6
rem ファイルは explain-one.bat が画面で受け取る（この画面へドラッグできる）。
call "%HERE%\explain-one.bat"
goto :menu

:do_7
call "%HERE%\doctor.bat"
goto :menu
