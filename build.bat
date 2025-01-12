@echo off
echo Starting build process...

rem 清理之前的构建
rmdir /s /q build dist

rem 执行打包命令
echo Building executable...
pyinstaller --clean run.spec

echo Build process completed.
pause 