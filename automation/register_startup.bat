@echo off
chcp 65001 > nul
title スタートアップ登録

cd /d "%~dp0"

echo ============================================================
echo  PonoMedia 営業承認サーバー — PC起動時の自動起動を登録します
echo ============================================================
echo.

set STARTUP_DIR=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
set TARGET=%STARTUP_DIR%\PonoMedia_ApproverServer.bat

echo 登録先: %TARGET%
echo.

(
echo @echo off
echo cd /d "%~dp0"
echo start "PonoMedia 営業承認サーバー" /min "%~dp0start_server.bat"
) > "%TARGET%"

if %errorlevel% == 0 (
    echo [成功] スタートアップに登録しました。
    echo 次回PC起動時からサーバーが自動的に起動します。
    echo.
    echo 解除する場合は以下のファイルを削除してください:
    echo %TARGET%
) else (
    echo [失敗] 登録に失敗しました。管理者権限で実行してみてください。
)

echo.
pause
