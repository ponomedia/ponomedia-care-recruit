@echo off
chcp 65001 > nul
title PonoMedia 営業承認サーバー

cd /d "%~dp0"

echo ============================================================
echo  PonoMedia 営業承認サーバー（自動再起動モード）
echo ============================================================
echo  このウィンドウを閉じるとサーバーが止まります。
echo  最小化して使ってください。
echo  終了する場合はこのウィンドウを閉じてください。
echo ============================================================
echo.

:LOOP
echo [%date% %time%] サーバー起動中...
python approver_server.py
echo.
echo [%date% %time%] サーバーが停止しました。3秒後に再起動します...
echo  （意図的に終了した場合はこのウィンドウを閉じてください）
timeout /t 3 /nobreak > nul
echo.
goto LOOP
