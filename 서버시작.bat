@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
title IQC 대시보드 서버
cd /d "%~dp0"

REM ============================================================
REM  내부정도관리(IQC) 웹 대시보드 - 서버 시작 (더블클릭 실행)
REM  - 파이썬을 자동 탐색(py 런처 / PATH / 표준 설치경로)하고,
REM    프로젝트 전용 가상환경(venv)을 만들어 그 안에서 실행합니다.
REM    → 시스템 PATH가 깨져 있어도 한 번 venv가 만들어지면 이후엔 안정 동작.
REM  - DB는 구글드라이브 밖 로컬(C:\iqc-data)에 저장하여 동기화 충돌 방지
REM ============================================================

set "IQC_DATABASE_URI=sqlite:///C:/iqc-data/iqc.sqlite3"
set "IQC_PORT=5000"
set "DBFILE=C:\iqc-data\iqc.sqlite3"
if not exist "C:\iqc-data" mkdir "C:\iqc-data"

REM ===== 1) 이미 만들어 둔 venv가 있으면 그대로 사용 =====
set "PY="
if exist "venv\Scripts\python.exe" (
  "venv\Scripts\python.exe" -c "import sys" 1>nul 2>nul && set "PY=venv\Scripts\python.exe"
)
if defined PY goto :haspy

REM ===== 2) venv가 없으면 '기반 파이썬'을 찾는다 =====
set "BASEPY="
REM  (a) py 런처 우선 (Windows 스토어 별칭 문제 회피)
py -3 -c "import sys" 1>nul 2>nul && set "BASEPY=py -3"
REM  (b) PATH 의 python (깨진 별칭이면 이 테스트에서 걸러짐)
if not defined BASEPY ( python -c "import sys" 1>nul 2>nul && set "BASEPY=python" )
REM  (c) 표준 설치 경로 직접 탐색
if not defined BASEPY (
  for %%V in (313 312 311 310) do (
    if not defined BASEPY if exist "%LocalAppData%\Programs\Python\Python%%V\python.exe" set "BASEPY=%LocalAppData%\Programs\Python\Python%%V\python.exe"
    if not defined BASEPY if exist "C:\Python%%V\python.exe" set "BASEPY=C:\Python%%V\python.exe"
  )
)
if not defined BASEPY goto :nopy

echo [최초 실행] 프로젝트 전용 가상환경(venv)을 생성합니다...
!BASEPY! -m venv venv
if errorlevel 1 goto :venvfail
set "PY=venv\Scripts\python.exe"

:haspy
REM ===== 3) 의존성 설치 (flask/waitress 없을 때만) =====
"%PY%" -c "import flask, waitress" 1>nul 2>nul
if errorlevel 1 (
  echo [최초 실행] 필요한 라이브러리를 설치합니다. 잠시만 기다려 주세요...
  "%PY%" -m pip install --upgrade pip
  "%PY%" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo [오류] 라이브러리 설치에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 실행하세요.
    pause
    exit /b 1
  )
)

REM ===== 4) DB 초기화 (DB 파일이 없을 때만) =====
if not exist "%DBFILE%" (
  echo [최초 실행] 데이터베이스를 초기화합니다...
  "%PY%" -m flask --app run.py seed
)

echo.
echo ============================================================
echo   IQC 대시보드 서버 실행 중  ^(이 창을 닫으면 서버가 종료됩니다^)
echo   - 이 PC에서      : http://127.0.0.1:%IQC_PORT%
echo   - 다른 PC에서    : http://[이 PC의 IP주소]:%IQC_PORT%
echo     ^(IP 확인: 명령프롬프트에서  ipconfig  - IPv4 주소^)
echo   - 방화벽에서 %IQC_PORT% 포트 인바운드 허용이 필요할 수 있습니다.
echo ============================================================
echo.

"%PY%" serve.py

echo.
echo 서버가 종료되었습니다.
pause
exit /b 0

:nopy
echo.
echo ============================================================
echo  [오류] 실행 가능한 파이썬(Python)을 찾지 못했습니다.
echo ------------------------------------------------------------
echo  Python 3.10 이상을 설치해야 합니다.
echo   1) 잠시 후 열리는 다운로드 페이지에서 Windows 설치파일을 받아 실행
echo   2) 설치 첫 화면에서 아래 항목을 '반드시 체크'
echo         [v] Add python.exe to PATH
echo   3) 설치 완료 후 이 창을 닫고 '서버시작.bat' 을 다시 더블클릭
echo ============================================================
echo.
start "" "https://www.python.org/downloads/windows/"
pause
exit /b 1

:venvfail
echo.
echo [오류] 가상환경(venv) 생성에 실패했습니다.
echo   파이썬 설치가 손상되었을 수 있습니다. Python 을 재설치한 뒤 다시 시도하세요.
echo   (설치 시 'Add python.exe to PATH' 체크)
pause
exit /b 1
