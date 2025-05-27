@echo off
echo 🚀 Starting YouTube Video Downloader Server...

REM Check if Docker is running
docker info >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker is not running. Please start Docker Desktop first.
    pause
    exit /b 1
)

REM Create necessary directories
if not exist "downloads" mkdir downloads
if not exist "logs" mkdir logs

REM Build and start the container
echo 📦 Building Docker container...
docker-compose build

echo 🔧 Starting server...
docker-compose up -d

REM Wait for service to be ready
echo ⏳ Waiting for server to be ready...
set /a counter=0
:wait_loop
if %counter% geq 30 goto timeout
curl -s http://localhost:8000/health >nul 2>&1
if errorlevel 1 (
    timeout /t 2 /nobreak >nul
    set /a counter+=1
    goto wait_loop
)

echo ✅ Server is ready!
echo 🌐 Server running at: http://localhost:8000
echo 📊 Health check: http://localhost:8000/health
echo 📁 Downloads folder: ./downloads
echo 📜 View logs: docker-compose logs -f
echo 🛑 Stop server: run stop_server.bat
pause
goto end

:timeout
echo ❌ Server failed to start. Check logs with: docker-compose logs
pause
exit /b 1

:end
