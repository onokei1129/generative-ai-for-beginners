@echo off
setlocal
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"

rem --------------------------------------------------------------------
rem 呼ばれ方は4通り。
rem
rem   （引数なし）   自分で押した。まず最新版を取ってから作る。
rem   /pull <場所>   一時フォルダへ写した自分自身。取得だけを担当する。
rem   /nopull        取得済みの状態から呼ばれた。作るだけ。
rem   /quiet         「名刺 1 準備する」から呼ばれた。作るだけ、止まらない。
rem
rem 自分で押したときも取得するのは、実テストで「このバッチを何度押しても
rem 直らない」という報告が続いたため。取得するのは update.bat だけであり、
rem このバッチはディスクにある版で作り直すだけだった。押す側からは区別が
rem つかない。
rem --------------------------------------------------------------------
set "QUIET="
set "NOPULL="
if /i "%~1"=="/quiet"  set "QUIET=1"
if /i "%~1"=="/quiet"  set "NOPULL=1"
if /i "%~1"=="/nopull" set "NOPULL=1"
if /i "%~1"=="/pull"   goto :pull
if defined NOPULL goto :begin

rem git pull はこのファイル自身を書き換えうる。cmd.exe はバッチを実行
rem しながら少しずつ読むため、実行中に書き換わると途中から壊れる。
rem そのため一時フォルダへ写し、そちらに取得を任せる（update.bat と同じ）。
copy /y "%~f0" "%TEMP%\bcards-shortcuts.bat" >nul
if errorlevel 1 goto :begin
"%TEMP%\bcards-shortcuts.bat" /pull "%HERE%"
exit /b

:pull
set "SRC=%~2"
echo 最新版を取得しています...
cd /d "%SRC%\..\.." 2>nul
if errorlevel 1 goto :pull_done
git rev-parse --show-toplevel >nul 2>&1
if errorlevel 1 goto :pull_no_git
git pull
if not errorlevel 1 goto :pull_done
rem 追跡先が未設定だと引数なしの git pull は止まる。origin から明示的に取る。
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do git pull origin "%%b"
goto :pull_done

:pull_no_git
echo   （git が使えないため、いまディスクにある版で作ります）

:pull_done
echo.
rem 取得後の版で作り直す。ここで呼ぶのは書き換わったあとのファイル。
call "%SRC%\create-desktop-shortcuts.bat" /nopull
exit /b

:begin
set "LOG=%HERE%\ショートカット作成ログ.txt"

rem 作り方。既定はショートカット（.lnk）。同期ソフトに消される場合だけ
rem バッチ（.bat）へ切り替える。:verify を参照。
set "KIND="

>"%LOG%" echo === デスクトップにショートカットを作ります ===

echo ============================================
echo  デスクトップにショートカットを作ります
echo ============================================
echo.

rem --------------------------------------------------------------------
rem どの複製の、どの版を動かしているのかを最初に出す。
rem
rem 実テストで、画面の文言が以前のままであることに双方が長く気づけなかった。
rem 複製が2つあると、更新したほうと押しているほうが食い違う。
rem --------------------------------------------------------------------
set "REV="
for /f "delims=" %%v in ('git -C "%HERE%" rev-parse --short HEAD 2^>nul') do set "REV=%%v"
if not defined REV set "REV=不明"
call :say "場所: %HERE%"
call :say "版:   %REV%"
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
if not defined DESKTOP call :from_registry
if not defined DESKTOP set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" goto :no_desktop

call :say "デスクトップ: %DESKTOP%"
call :make_all "%DESKTOP%"

rem 場所の取得を誤っていても画面に出るよう、素の場所にも置いておく。
rem （同じ場所なら二重に作らない）
set "PLAIN=%USERPROFILE%\Desktop"
if /i "%PLAIN%"=="%DESKTOP%" goto :verify
if not exist "%PLAIN%" goto :verify
call :say "念のためこちらにも: %PLAIN%"
call :make_all "%PLAIN%"

rem --------------------------------------------------------------------
rem 作った直後ではなく、少し待ってから数える。
rem
rem iCloud Drive はショートカット（.lnk）を同期の対象として扱わず、
rem デスクトップに置いた直後に取り除くことがある。作成そのものは成功する
rem ため、その場で数えると 7 個あるように見えて、数秒後には消えている。
rem 消えていたら、同じ名前・同じ飛び先のバッチ（.bat）で作り直す。
rem バッチはただのファイルなので同期ソフトに取り除かれない。
rem --------------------------------------------------------------------
:verify
ping -n 5 127.0.0.1 >nul 2>&1
call :count "%DESKTOP%"
if not "%MADE%"=="0" goto :done

call :say "ショートカットが残りませんでした。同期ソフトの制限とみて、バッチ形式で作り直します。"
set "KIND=bat"
call :make_all "%DESKTOP%"
if /i "%PLAIN%"=="%DESKTOP%" goto :recount
if not exist "%PLAIN%" goto :recount
call :make_all "%PLAIN%"

:recount
ping -n 3 127.0.0.1 >nul 2>&1
call :count "%DESKTOP%"
if "%MADE%"=="0" goto :none_made

:done
call :say "デスクトップに「名刺システム」を置きました。"
echo.
echo ============================================
echo.
echo  デスクトップのアイコンは「名刺システム」1つだけです。
echo  開くと、やることを番号で選べます。
echo.
echo  見当たらないときは、デスクトップで F5 を押してください。
echo  それでも出ないときは、デスクトップを右クリック
echo  →「表示」→「デスクトップ アイコンの表示」を確認してください。
echo.
echo  はじめてのときは 1 から順に。3 と 4 は何度往復しても構いません。
echo.
echo  記録: "%LOG%"
echo ============================================
echo.
if defined QUIET exit /b 0
rem 画面に出ないときの切り分けのため、置いた場所そのものを開く。
explorer "%DESKTOP%"
pause
exit /b 0

:none_made
call :say "[エラー] ショートカットが1つも残りませんでした。"
echo.
echo ============================================
echo  上の「デスクトップ:」の場所をエクスプローラーで直接開いて、
echo  その行と、次の記録をそのまま共有してください。
echo    "%LOG%"
echo ============================================
echo.
if defined QUIET exit /b 1
explorer "%DESKTOP%"
pause
exit /b 1

:no_desktop
echo [エラー] デスクトップのフォルダが見つかりません: "%DESKTOP%"
pause
exit /b 1


rem --------------------------------------------------------------------
rem 画面と記録の両方に出す。うまくいかないときに後から追えるようにする。
rem --------------------------------------------------------------------
:say
echo %~1
>>"%LOG%" echo %~1
exit /b 0

rem --------------------------------------------------------------------
rem GetFolderPath が空を返したときの控え。レジストリにも同じ値がある。
rem --------------------------------------------------------------------
:from_registry
for /f "usebackq tokens=2,*" %%a in (`reg query "HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders" /v Desktop 2^>nul`) do set "DESKTOP=%%b"
exit /b 0

rem --------------------------------------------------------------------
rem 残っている数を数える。.lnk と .bat のどちらでも数える。
rem --------------------------------------------------------------------
:count
set "MADE=0"
for %%f in ("%~1\名刺システム.lnk") do set /a MADE+=1
for %%f in ("%~1\名刺システム.bat") do set /a MADE+=1
exit /b 0

rem --------------------------------------------------------------------
rem 指定した場所へ一式を作る
rem --------------------------------------------------------------------
:make_all
set "TARGET=%~1"

rem 自分が前に作った分だけ消す。`名刺 ` で始まるものに限るので、
rem 利用者が置いた他のショートカットには触れない。
if exist "%TARGET%\名刺 *.lnk" del /q "%TARGET%\名刺 *.lnk"
if exist "%TARGET%\名刺 *.bat" del /q "%TARGET%\名刺 *.bat"
if exist "%TARGET%\名刺システム.lnk" del /q "%TARGET%\名刺システム.lnk"
if exist "%TARGET%\名刺システム.bat" del /q "%TARGET%\名刺システム.bat"

rem 以前の版はデスクトップに「名刺システム」フォルダを作り、その中へ
rem 入れていた。画面から見えず分かりにくかったため直接置く形に変えた。
rem 古いほうのショートカットを消し、空になったらフォルダも片付ける
rem （rd は空のときだけ消えるので、中身が残っていれば触らない）。
if exist "%TARGET%\名刺システム\*.lnk" del /q "%TARGET%\名刺システム\*.lnk"
if exist "%TARGET%\名刺システム" rd "%TARGET%\名刺システム" 2>nul

rem デスクトップに置くのは1つだけ。やることは menu.bat の中で番号で選ぶ。
rem 以前はやることの数だけ並べていた（7～8個）。実テストで「デスクトップが
rem 雑然としてしまった」という報告になった。フォルダに入れると今度は画面から
rem 見えなくなる（それも実テストで報告があった）ので、1つだけ直接置く。
call :make "名刺システム" "menu.bat"
exit /b 0

:make
if /i "%KIND%"=="bat" goto :make_bat
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut('%TARGET%\%~1.lnk'); $s.TargetPath='%HERE%\%~2'; $s.WorkingDirectory='%HERE%'; $s.IconLocation='%SystemRoot%\System32\imageres.dll,76'; $s.Save()"
if errorlevel 1 goto :make_failed
call :say "  作成: %~1"
exit /b 0

rem 同期ソフトが .lnk を受け付けないときの形。飛び先を呼ぶだけの
rem バッチを置く。見た目の名前と動きは .lnk と同じ。
:make_bat
>"%TARGET%\%~1.bat" echo @echo off
>>"%TARGET%\%~1.bat" echo cd /d "%HERE%"
>>"%TARGET%\%~1.bat" echo call "%HERE%\%~2"
if errorlevel 1 goto :make_failed
call :say "  作成: %~1"
exit /b 0

:make_failed
call :say "  [失敗] %~1"
exit /b 0
