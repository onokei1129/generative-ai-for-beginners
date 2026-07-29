@echo off
rem tesseract が使えるか（日本語データも含めて）確かめる共通処理。
rem 他のバッチから call して使う。使える場合は exit /b 0、駄目なら exit /b 1。
rem
rem setlocal は使わない。PATH を補ったとき、呼び出し元にも効かせる必要があるため。
rem
rem よくある詰まりどころ:
rem  ・本体は入っているが PATH に無い（Add to PATH の入れ忘れ／エクスプローラが
rem    古い環境変数を保持している）→ 既定のインストール先を探して補う
rem  ・本体だけ入って日本語データが無い → 読めないままOCRが走るので止める

where tesseract >nul 2>&1
if not errorlevel 1 goto :langcheck

rem PATH に無い。既定のインストール先を探す。
rem ProgramFiles(x86) は括弧を含むため、いったん変数へ移してから使う。
set "TESSPF=%ProgramFiles%"
set "TESSPF86=%ProgramFiles(x86)%"
set "TESSDIR="
for %%d in (
    "%TESSPF%\Tesseract-OCR"
    "%TESSPF86%\Tesseract-OCR"
    "%LOCALAPPDATA%\Programs\Tesseract-OCR"
    "%LOCALAPPDATA%\Tesseract-OCR"
) do if not defined TESSDIR if exist "%%~d\tesseract.exe" set "TESSDIR=%%~d"

if not defined TESSDIR (
    echo [エラー] tesseract が見つかりません。
    echo.
    echo   https://github.com/UB-Mannheim/tesseract/wiki からインストールしてください。
    echo   ・未署名のため Windows が「発行元不明」と警告します（tesseract 公式wikiが
    echo     案内している標準のWindows版です）
    echo   ・最初に出る Installer Language は「インストーラの表示言語」です。
    echo     日本語はありません。English のまま進めてください。
    echo   ・Choose Components の画面で
    echo     Additional language data ^(download^) の左の [+] を展開し、
    echo     Japanese と Japanese ^(vertical^) にチェックを入れてください。
    echo.
    exit /b 1
)

echo tesseract は入っていますが、PATH に登録されていません。
echo   見つけた場所: %TESSDIR%
echo   この実行に限り、一時的に PATH へ追加して続行します。
echo.
echo   毎回この表示が出る場合は、次のどちらかで解消します。
echo     ・Windows からサインアウトして入り直す
echo       （エクスプローラが古い環境変数を保持しているため）
echo     ・環境変数 PATH に上記のフォルダを追加する
echo.
set "PATH=%PATH%;%TESSDIR%"

:langcheck
set "HASJPN="
set "HASVERT="
for /f "delims=" %%l in ('tesseract --list-langs 2^>^&1') do (
    if "%%l"=="jpn" set "HASJPN=1"
    if "%%l"=="jpn_vert" set "HASVERT=1"
)

if not defined HASJPN (
    echo [エラー] tesseract は入っていますが、日本語データ ^(jpn^) がありません。
    echo.
    echo   これが無いと日本語を読めず、仕分けも精度測定も正しく動きません。
    echo.
    echo   入れ方は2通りあります。
    echo.
    echo   A^) インストーラで入れる
    echo     1. インストーラをもう一度実行する（上書きで構いません）
    echo     2. Choose Components の画面で
    echo        Additional language data ^(download^) の左の [+] を押して展開する
    echo        ※畳まれているので、展開しないと言語一覧が見えません
    echo     3. J まで送って Japanese と Japanese ^(vertical^) にチェック
    echo.
    echo   B^) ファイルを直接置く（確実）
    echo     https://github.com/tesseract-ocr/tessdata から
    echo       jpn.traineddata  と  jpn_vert.traineddata
    echo     を保存し、下記の tessdata フォルダに入れる。
    echo.
    echo   いま入っている言語と、その置き場所:
    tesseract --list-langs 2>&1
    echo.
    exit /b 1
)

if not defined HASVERT (
    echo [注意] 縦書き用データ ^(jpn_vert^) がありません。
    echo   横書きは読めますが、縦書きの名刺の精度が落ちます。
    echo   Japanese ^(vertical^) の追加をお勧めします。
    echo.
)

exit /b 0
