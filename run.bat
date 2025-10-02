@echo off
setlocal

cd /d "%~dp0"

echo.
echo =================================
echo   Servatio — Резервное копирование
echo =================================
echo.

:: Проверяем, установлен ли Git
git --version >nul 2>&1
if %errorlevel% equ 0 (
    echo Проверка обновлений...
    git fetch --quiet origin main 2>nul
    if %errorlevel% equ 0 (
        :: Сравниваем локальный HEAD с origin/main
        for /f %%H in ('git rev-parse HEAD') do set LOCAL=%%H
        for /f %%R in ('git rev-parse origin/main') do set REMOTE=%%R

        if NOT "%LOCAL%"=="%REMOTE%" (
            echo.
            echo 🔔 Доступна новая версия Servatio!
            echo Текущая версия: %LOCAL:~0,7%
            echo Новая версия:    %REMOTE:~0,7%
            echo.
            set /p UPDATE="Хотите обновиться? (y/n): "
            if /i "%UPDATE%"=="y" (
                echo.
                echo Обновление...
                git reset --hard origin/main --quiet
                if %errorlevel% equ 0 (
                    echo ✅ Обновление завершено. Перезапуск...
                    echo.
                    timeout /t 2 /nobreak >nul
                    goto :run
                ) else (
                    echo ❌ Не удалось применить обновление.
                    echo.
                )
            ) else (
                echo Обновление пропущено.
                echo.
            )
        ) else (
            echo ✅ У вас последняя версия.
            echo.
        )
    ) else (
        echo ⚠️ Не удалось проверить обновления (нет подключения или репозиторий недоступен).
        echo.
    )
) else (
    echo ⚠️ Git не установлен — проверка обновлений пропущена.
    echo Установите Git для автоматических обновлений: https://git-scm.com/
    echo.
)

:run
:: Проверяем, есть ли servatio.py
if not exist "app.py" (
    echo ❌ Файл servatio.py не найден!
    echo Убедитесь, что вы запускаете скрипт из папки проекта.
    echo.
    pause
    exit /b 1
)

:: Проверяем Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python не найден!
    echo Установите Python 3.8+: https://www.python.org/downloads/
    echo.
    pause
    exit /b 1
)

echo Запуск Servatio...
echo.
python app.py