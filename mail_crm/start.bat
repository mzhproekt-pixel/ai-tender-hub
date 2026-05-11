@echo off
REM Mail CRM — запуск веб-интерфейса в один клик.
REM При первом запуске создаёт виртуальное окружение и ставит зависимости.

setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo === Первый запуск: создаю виртуальное окружение ===
    python -m venv .venv
    if errorlevel 1 (
        echo.
        echo Не удалось создать venv. Убедитесь, что Python установлен:
        echo https://www.python.org/downloads/
        echo При установке отметьте "Add Python to PATH".
        pause
        exit /b 1
    )
    call ".venv\Scripts\activate.bat"
    echo === Устанавливаю зависимости (минуту-две) ===
    python -m pip install --upgrade pip
    pip install -r requirements.txt
) else (
    call ".venv\Scripts\activate.bat"
)

echo.
echo ============================================================
echo  Открой в браузере: http://127.0.0.1:5000
echo  Для остановки сервера: закрой это окно или нажми Ctrl+C
echo ============================================================
echo.

REM Открыть браузер через 2 секунды после старта сервера
start "" /b cmd /c "timeout /t 2 >nul && start http://127.0.0.1:5000/settings"

python -m web.app

pause
