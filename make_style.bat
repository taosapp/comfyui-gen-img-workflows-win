@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 936 >nul
rem Python 3.15 起默认 UTF-8 模式，与本文件强制成 936 的控制台对不上，
rem 会让脚本的中文输出变乱码。把 stdout 钉到 GBK，与 bat 自身保持一致。
set "PYTHONIOENCODING=gbk:replace"
cd /d "%~dp0"

rem ================================================================
rem  从风格参考图反推提示词（Windows 双击版）
rem
rem  用法：直接双击本文件
rem
rem  前置：ComfyUI 必须先启动（先双击 start_comfyui.bat，等它打印出地址）
rem  放图：input\style_refs\风格名\1.png   -> styles\风格名.txt
rem        input\style_refs\风格名.png     -> styles\风格名.txt
rem
rem  想改端口：先 set COMFY_PORT=8191 再跑，或改下面的默认值
rem            （本机若同时开着 ComfyUI Desktop，它会占住 8188，改用 8191）
rem
rem  【维护须知】本文件必须是 GBK(936) 编码，中文才不乱码。
rem    改内容请改这个源再转码，不要用编辑器直接存成 UTF-8。
rem ================================================================

if not defined COMFY_PORT set "COMFY_PORT=8188"

rem ---------- 找 python：conda 环境优先，其次 PATH ----------
set "PYEXE="

if defined CONDA_PREFIX if exist "%CONDA_PREFIX%\python.exe" set "PYEXE=%CONDA_PREFIX%\python.exe"

if not defined PYEXE (
    for %%R in (
        "%USERPROFILE%\miniconda3\envs\comfyui"
        "%USERPROFILE%\anaconda3\envs\comfyui"
        "%USERPROFILE%\Miniconda3\envs\comfyui"
        "%LOCALAPPDATA%\miniconda3\envs\comfyui"
        "%ProgramData%\miniconda3\envs\comfyui"
        "C:\miniconda3\envs\comfyui"
    ) do (
        if not defined PYEXE if exist "%%~R\python.exe" set "PYEXE=%%~R\python.exe"
    )
)

if not defined PYEXE for /f "delims=" %%I in ('where python.exe 2^>nul') do (
    if not defined PYEXE set "PYEXE=%%I"
)

if not defined PYEXE (
    echo [错误] 找不到 python.exe。
    echo         装一个 conda 环境 comfyui，或把 python 加进 PATH。
    goto :end
)

echo ================================================================
echo  反推风格提示词
echo ================================================================
echo  解释器   !PYEXE!
echo  端口     !COMFY_PORT!
echo.

if not exist "scripts\gen_style_from_images.py" (
    echo [错误] 找不到 scripts\gen_style_from_images.py
    echo        本文件要放在 ComfyUI 根目录（与 main.py 同级）。
    goto :end
)

rem ---------- 先问写入还是只预览，避免跑两遍白等 ----------
set "WRITEARG="
choice /c yn /m "要直接写入 styles\ 吗（N = 只预览不写）"
if errorlevel 2 goto :preview
set "WRITEARG=--write"
echo.
echo [写入模式] 生成后直接写到 styles\，不满意的删掉对应 txt 即可。
goto :run

:preview
echo.
echo [预览模式] 只打印不写文件。

:run
echo.
"!PYEXE!" "scripts\gen_style_from_images.py" --port !COMFY_PORT! !WRITEARG!

if errorlevel 1 (
    echo.
    echo ----------------------------------------------------------------
    echo  上面报错了。最常见的两个原因：
    echo    1. ComfyUI 还没启动 -- 先双击 start_comfyui.bat，等它打印地址
    echo    2. 端口连到了别的实例 -- ComfyUI Desktop 会占住 8188，
    echo       那就 set COMFY_PORT=8191 再跑本文件（ComfyUI 也要用同端口启动）
    echo ----------------------------------------------------------------
)

:end
echo.
pause
