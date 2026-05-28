@echo off
chcp 65001 > nul
title PonoMedia 毎日営業パイプライン（全業種）

cd /d "%~dp0"

set PYTHON=C:\Python314\python.exe
set LOGFILE=%~dp0output\daily_run.log

echo ============================================================ >> "%LOGFILE%"
echo  実行開始: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

echo [1/5] 介護 >> "%LOGFILE%"
"%PYTHON%" run_pipeline.py --rank-filter A,B --max-facilities 50 --form-only >> "%LOGFILE%" 2>&1

echo [2/5] 保育 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry hoiku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [3/5] 建設 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry kensetsu --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [4/5] 薬局 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry yakkyoku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [5/5] 飲食 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry inshoku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [6/6] 承認キュー自動処理 >> "%LOGFILE%"
"%PYTHON%" auto_approver.py >> "%LOGFILE%" 2>&1

echo  実行終了: %date% %time% >> "%LOGFILE%"
echo. >> "%LOGFILE%"
