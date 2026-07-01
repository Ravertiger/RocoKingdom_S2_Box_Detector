@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

title Roco Box Detector — Build EXE

echo ============================================================
echo   Roco Box Detector — PyInstaller 编译脚本
echo ============================================================
echo.

cd /d "%~dp0"

:: ── Step 1: Check Python ─────────────────────────────────────
echo [1/4] 检查 Python 环境...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do echo         已检测: Python %%v
echo.

:: ── Step 2: Install dependencies ─────────────────────────────
echo [2/4] 安装/更新依赖...
python -m pip install --upgrade pip -q
python -m pip install -r roco_box_detector\requirements.txt -q
if %errorlevel% neq 0 (
    echo [ERROR] 依赖安装失败
    pause
    exit /b 1
)
echo         依赖安装完成

python -m pip install pyinstaller -q
echo         PyInstaller 安装完成
echo.

:: ── Step 3: Clean previous build ─────────────────────────────
echo [3/4] 清理旧构建与缓存...
if exist "dist\RocoBoxDetector.exe" (
    del /q "dist\RocoBoxDetector.exe"
    echo         已删除旧的 dist\RocoBoxDetector.exe
)
if exist "dist\RocoBoxDetector" (
    rmdir /s /q "dist\RocoBoxDetector"
    echo         已删除旧的 dist\RocoBoxDetector
)
if exist "build" (
    rmdir /s /q "build"
    echo         已删除旧的 build 缓存
)
:: Clean PyInstaller cache
if exist "%userprofile%\AppData\Roaming\pyinstaller" (
    rmdir /s /q "%userprofile%\AppData\Roaming\pyinstaller"
    echo         已清理 PyInstaller 缓存
)
:: Clean __pycache__ dirs
for /d /r "roco_box_detector" %%d in (__pycache__) do (
    if exist "%%d" rmdir /s /q "%%d"
)
echo.

:: ── Step 4: Build with PyInstaller ───────────────────────────
echo [4/4] 开始编译 EXE（可能需要几分钟）...
echo.

pyinstaller --clean --noconfirm --log-level=WARN roco_box_detector\build.spec

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] 编译失败，请检查上方错误信息
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   编译成功！
echo   输出文件: dist\RocoBoxDetector.exe （单文件，无需安装）
echo.
echo   提示:
echo   - 将 config.json / templates 放 exe 同目录可覆盖内置配置
echo   - 首次启动需解压到临时目录（1~3 秒）
echo   - 添加图标: 将 icon.ico 放入 roco_box_detector\ 目录
echo ============================================================
echo.

:: ── Open output folder ──────────────────────────────────────
start "" "dist"

pause
