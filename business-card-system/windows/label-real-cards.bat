@echo off
setlocal
cd /d "%~dp0..\app"

echo ============================================
echo  ラベル入力（実際の名刺）
echo ============================================
echo.

if not exist ".venv\Scripts\python.exe" (
    echo [エラー] セットアップがまだです。
    echo   先に「セットアップ」を実行してください。
    echo.
    pause
    exit /b 1
)

if not exist "poc\real-cards" (
    echo [エラー] 名刺のフォルダがありません: %CD%\poc\real-cards
    echo.
    echo   先に「名刺を仕分ける」を実行するか、
    echo   このフォルダを作って名刺の画像を入れてください。
    echo.
    pause
    exit /b 1
)

echo 対象: %CD%\poc\real-cards
echo.
echo ブラウザが自動で開きます。開かない場合は
echo   http://127.0.0.1:8100/
echo を手で開いてください。
echo.
echo 【注意】OCRの読み取り結果を、あらかじめ入力欄に入れてあります。
echo   画像と見比べて、間違っているところを直してください。
echo   薄い黄色の欄は「未確認」です。一度触れば確認済みになります。
echo   未確認のまま残すと、精度が実際より良く出てしまいます。
echo.
echo 終了するときは、この黒い画面で Ctrl-C を押すか、ウィンドウを閉じてください。
echo.

.venv\Scripts\python poc\label.py .\poc\real-cards

echo.
pause
