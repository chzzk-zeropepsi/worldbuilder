@echo off
REM ASCII only (cp949 safe)
cd /d %~dp0
if not exist .venv (
  python -m venv .venv
  call .venv\Scripts\activate
  pip install -r requirements.txt
) else (
  call .venv\Scripts\activate
)
cd server
uvicorn main:app --port 8770 --reload
