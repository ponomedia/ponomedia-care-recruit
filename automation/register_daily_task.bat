@echo off
chcp 65001 > nul
title PonoMedia 毎日12:50 タスク登録（管理者）

cd /d "%~dp0"

:: 管理者権限チェック・自動昇格
net session > nul 2>&1
if %errorlevel% neq 0 (
    echo 管理者権限が必要です。昇格して再実行します...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

echo ============================================================
echo  PonoMedia 毎日営業パイプライン — タスクスケジューラ登録
echo ============================================================
echo.

set TASK_NAME=PonoMedia_DailyPipeline
set XML_PATH=%~dp0PonoMedia_DailyPipeline.xml

:: 既存タスクを削除して再登録
schtasks /delete /tn "%TASK_NAME%" /f > nul 2>&1

schtasks /create /tn "%TASK_NAME%" /xml "%XML_PATH%" /f

if %errorlevel% == 0 (
    echo.
    echo [成功] タスクを登録しました。
    echo   タスク名: %TASK_NAME%
    echo   実行時刻: 毎日 12:50
    echo   ログ出力: output\daily_run.log
    echo.
    echo 確認・変更: Win+R → taskschd.msc
    echo.
    set /p RUNTEST="今すぐテスト実行しますか？ (y/n): "
    if /i "%RUNTEST%"=="y" (
        schtasks /run /tn "%TASK_NAME%"
        echo テスト実行を開始しました。output\daily_run.log で確認できます。
    )
) else (
    echo [失敗] タスク登録に失敗しました。
)

echo.
pause
