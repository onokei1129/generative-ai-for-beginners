@echo off
chcp 65001 >nul
setlocal
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

echo ============================================
echo  デスクトップにショートカットを作ります
echo ============================================
echo.

rem OneDrive でデスクトップが同期されている場合はそちらを使う
set "DESKTOP=%USERPROFILE%\Desktop"
if exist "%OneDrive%\Desktop" set "DESKTOP=%OneDrive%\Desktop"
if not exist "%DESKTOP%" (
    echo [エラー] デスクトップのフォルダが見つかりません: %DESKTOP%
    pause
    exit /b 1
)

set "FOLDER=%DESKTOP%\名刺システム"
if not exist "%FOLDER%" mkdir "%FOLDER%"

call :make "1 セットアップ"                 "setup.bat"
call :make "2 練習サンプルを作る"           "make-practice-samples.bat"
call :make "3 ラベル入力（練習）"           "label-practice.bat"
call :make "4 名刺を仕分ける"               "classify-scans.bat"
call :make "5 ラベル入力（実際の名刺）"     "label-real-cards.bat"
call :make "6 アプリを起動"                 "run-app.bat"

echo.
echo ============================================
echo  作成しました: %FOLDER%
echo.
echo  デスクトップの「名刺システム」フォルダを開き、
echo  番号の順に実行してください。
echo ============================================
echo.
explorer "%FOLDER%"
pause
exit /b 0

:make
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%FOLDER%\%~1.lnk'); $s.TargetPath='%HERE%\%~2'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,76'; $s.Save()"
if errorlevel 1 (
    echo   [失敗] %~1
) else (
    echo   作成: %~1
)
exit /b 0
