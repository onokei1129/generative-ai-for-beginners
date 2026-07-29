@echo off
rem tesseract が使えるか（日本語データも含めて）確かめる共通処理。
rem 他のバッチから call して使う。使える場合は exit /b 0、駄目なら exit /b 1。
rem
rem 本体だけ入っていて日本語データが無い状態がよくある。その場合は
rem 「入っているのに読めない」ままOCRが走り、結果がおかしくなるので、
rem ここで止めて入れ方を案内する。

setlocal

where tesseract >nul 2>&1
if errorlevel 1 (
    echo [エラー] tesseract が見つかりません。
    echo.
    echo   https://github.com/UB-Mannheim/tesseract/wiki からインストールしてください。
    echo   ・未署名のため Windows が「発行元不明」と警告します（tesseract 公式wikiが
    echo     案内している標準のWindows版です）
    echo   ・インストーラで Add to PATH にチェックを入れてください
    echo   ・入れたあとは、この画面を閉じて開き直してください（PATHの反映に必要）
    echo.
    exit /b 1
)

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
    echo   入れ方:
    echo     1. インストーラをもう一度実行する（上書きで構いません）
    echo     2. Choose Components の画面で
    echo        Additional language data ^(download^) の左の [+] を押して展開する
    echo        ※畳まれているので、展開しないと言語一覧が見えません
    echo     3. J まで送って Japanese と Japanese ^(vertical^) にチェック
    echo     4. そのまま進める
    echo.
    echo   入れたあとは、この画面を閉じて開き直してください。
    echo.
    echo   いま入っている言語:
    tesseract --list-langs 2>&1
    echo.
    exit /b 1
)

if not defined HASVERT (
    echo [注意] 縦書き用データ ^(jpn_vert^) がありません。
    echo   横書きは読めますが、縦書きの名刺の精度が落ちます。
    echo   インストーラの Japanese ^(vertical^) を追加することをお勧めします。
    echo.
)

exit /b 0
