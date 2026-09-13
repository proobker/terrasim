@echo off
setlocal
cd /d "%~dp0"

echo [terrasim] starting dev servers...

if not exist "backend\.venv\Scripts\python.exe" (
  echo [terrasim] first run: creating backend venv...
  pushd backend
  call uv sync
  popd
)

if not exist "frontend\node_modules" (
  echo [terrasim] first run: installing frontend deps...
  pushd frontend
  call npm install
  popd
)

start "terrasim-backend" cmd /k "cd /d ""%~dp0backend"" && uv run uvicorn app.main:app --reload --port 8000"
start "terrasim-frontend" cmd /k "cd /d ""%~dp0frontend"" && npm run dev"

echo.
echo terrasim is starting:
echo   backend  http://127.0.0.1:8000/api/health
echo   frontend http://localhost:5173
echo Close the two "terrasim-*" windows to stop.
endlocal