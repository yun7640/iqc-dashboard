@echo off
chcp 65001 >nul
title IQC 대시보드 자동시작 등록
cd /d "%~dp0"

REM ============================================================
REM  서버 PC 로그온 시 IQC 대시보드 서버를 자동 실행하도록 등록
REM  ※ 반드시 '관리자 권한으로 실행' 하세요 (파일 우클릭 - 관리자 권한으로 실행)
REM ============================================================

set "TASKNAME=IQC-Dashboard-Server"

echo 자동시작 작업을 등록합니다: %TASKNAME%
schtasks /create /tn "%TASKNAME%" /tr "\"%~dp0서버시작.bat\"" /sc onlogon /rl highest /f

if errorlevel 1 (
  echo.
  echo [실패] 등록에 실패했습니다.
  echo   1^) 이 파일을 우클릭 - '관리자 권한으로 실행' 하세요.
  echo   2^) 그래도 안 되면 아래 명령을 관리자 명령프롬프트에서 직접 실행하세요:
  echo      schtasks /create /tn "%TASKNAME%" /tr "\"%~dp0서버시작.bat\"" /sc onlogon /rl highest /f
) else (
  echo.
  echo [완료] 다음 로그인부터 서버가 자동으로 실행됩니다.
  echo.
  echo  - 지금 바로 시작하려면 '서버시작.bat' 을 더블클릭하세요.
  echo  - 자동시작 해제:  schtasks /delete /tn "%TASKNAME%" /f
)
echo.
pause
