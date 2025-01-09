@echo off
echo Starting secure build process...

rem 安装必要的包
pip install pyinstaller

rem 清理之前的构建
rmdir /s /q build dist
del /s /q *.spec

rem 直接使用pyinstaller命令打包
echo Building executable...
pyinstaller --noconfirm --onefile ^
    --add-data ".env;." ^
    --add-data "src;src" ^
    --hidden-import pandas ^
    --hidden-import numpy ^
    --hidden-import lark_oapi ^
    --hidden-import httpx ^
    --hidden-import python-dotenv ^
    --hidden-import pathlib ^
    --hidden-import asyncio ^
    --hidden-import threading ^
    --hidden-import logging ^
    --hidden-import time ^
    --hidden-import win32api ^
    --hidden-import win32con ^
    --hidden-import pythoncom ^
    --hidden-import pywintypes ^
    --name inventory_management ^
    run.py

echo Build process completed.
pause 