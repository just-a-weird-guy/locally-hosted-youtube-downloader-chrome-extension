@echo off
echo 🛑 Stopping YouTube Video Downloader Server...
docker-compose down

echo ✅ Server stopped successfully!
echo 💡 To remove all data: docker-compose down -v
echo 💡 To remove images: docker system prune
pause
