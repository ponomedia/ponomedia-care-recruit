@echo off
chcp 65001 > nul
title PonoMedia 毎日営業パイプライン（全業種）

cd /d "%~dp0"

set PYTHON=C:\Python314\python.exe
set LOGFILE=%~dp0output\daily_run.log

echo ============================================================ >> "%LOGFILE%"
echo  実行開始: %date% %time% >> "%LOGFILE%"
echo ============================================================ >> "%LOGFILE%"

echo [1/7] 介護 >> "%LOGFILE%"
"%PYTHON%" run_pipeline.py --rank-filter A,B --max-facilities 50 --form-only >> "%LOGFILE%" 2>&1

echo [2/7] 保育 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry hoiku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [3/7] 建設 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry kensetsu --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [4/7] 薬局 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry yakkyoku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [5/7] 飲食 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry inshoku --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [6/7] 物流・運送 >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry butsuryu --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [7/7] 清掃・ビルメン >> "%LOGFILE%"
"%PYTHON%" run_industry_pipeline.py --industry seisou --rank-filter A,B --max-facilities 30 --form-only >> "%LOGFILE%" 2>&1

echo [承認キュー] 自動処理 >> "%LOGFILE%"
"%PYTHON%" auto_approver.py >> "%LOGFILE%" 2>&1

echo  実行終了: %date% %time% >> "%LOGFILE%"
echo. >> "%LOGFILE%"
