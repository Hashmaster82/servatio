@echo off
setlocal

echo.
echo ================================
echo  Установка зависимостей Servatio
echo ================================
echo.

:: Проверяем, установлен ли Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python не найден!
    echo Пожалуйста, установите Python 3.8 или новее с https://www.python.org/downloads/
    echo Убедитесь, что Python добавлен в PATH.
    echo.
    pause
    exit /b 1
)

:: Проверяем наличие requirements.txt
if not exist "requirements.txt" (
    echo ❌ Файл requirements.txt не найден в текущей папке.
    echo Запускайте этот скрипт из папки проекта Servatio.
    echo.
    pause
    exit /b 1
)

echo Установка зависимостей из requirements.txt...
echo.

:: Устанавливаем зависимости
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

if %errorlevel% equ 0 (
    echo.
    echo ✅ Все зависимости успешно установлены!
    echo Теперь вы можете запустить Servatio командой:
    echo      python app.py
) else (
    echo.
    echo ❌ Произошла ошибка при установке зависимостей.
    echo Проверьте подключение к интернету и повторите попытку.
)

echo.
pause