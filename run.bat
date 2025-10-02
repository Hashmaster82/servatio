@echo off
setlocal

:: Path to the current directory
set "SCRIPT_DIR=%~dp0"

:: Check if the folder is a Git repository
if not exist ".git" (
    echo Repository not found. Skipping update.
    echo Starting application...
    python app.py
    goto :eof
)

echo Checking for updates...

:: Fetch latest changes from remote
git fetch origin

:: Compare local HEAD with remote master branch
git diff --quiet HEAD origin/master
if errorlevel 1 (
    echo Updates detected. Pulling latest changes...
    git pull origin master
    if errorlevel 1 (
        echo Failed to update. Starting application anyway.
    ) else (
        echo Update completed successfully.
    )
) else (
    echo No updates available.
)

echo.
echo Starting Servatio...
python app.py

pause