@echo off
echo Starting build process...

rem 设置环境变量
set PYTHONPATH=%PYTHONPATH%;%CD%
set CONDA_PREFIX=D:\ProgramData\Anaconda3
set PATH=%PATH%;%CONDA_PREFIX%;%CONDA_PREFIX%\Library\bin;%CONDA_PREFIX%\DLLs

rem 创建spec文件
echo Creating spec file...
echo # -*- mode: python ; coding: utf-8 -*- > run.spec
echo. >> run.spec
echo import os >> run.spec
echo import sys >> run.spec
echo from PyInstaller.utils.hooks import collect_data_files, collect_submodules >> run.spec
echo. >> run.spec
echo # 获取 Conda 环境路径 >> run.spec
echo conda_prefix = r'D:\ProgramData\Anaconda3' >> run.spec
echo. >> run.spec
echo block_cipher = None >> run.spec
echo. >> run.spec
echo # 收集所有子模块 >> run.spec
echo hidden_imports = collect_submodules('lark_oapi') + [ >> run.spec
echo     'pandas', >> run.spec
echo     'numpy', >> run.spec
echo     'httpx', >> run.spec
echo     'python-dotenv', >> run.spec
echo     'pathlib', >> run.spec
echo     'asyncio', >> run.spec
echo     'threading', >> run.spec
echo     'logging', >> run.spec
echo     'ctypes', >> run.spec
echo     'win32api', >> run.spec
echo     'win32con', >> run.spec
echo ] >> run.spec
echo. >> run.spec
echo # 收集数据文件 >> run.spec
echo datas = [ >> run.spec
echo     ('.env', '.'), >> run.spec
echo ] >> run.spec
echo. >> run.spec
echo # 添加源代码文件 >> run.spec
echo src_files = [] >> run.spec
echo for root, dirs, files in os.walk('src'): >> run.spec
echo     for file in files: >> run.spec
echo         if file.endswith('.py'): >> run.spec
echo             target_dir = os.path.relpath(root, '.') >> run.spec
echo             src_files.append((os.path.join(root, file), target_dir)) >> run.spec
echo datas.extend(src_files) >> run.spec
echo. >> run.spec
echo # 添加必要的DLL文件 >> run.spec
echo binaries = [ >> run.spec
echo     (os.path.join(conda_prefix, 'vcruntime140.dll'), '.'), >> run.spec
echo     (os.path.join(conda_prefix, 'python310.dll'), '.'), >> run.spec
echo ] >> run.spec
echo. >> run.spec
echo a = Analysis( >> run.spec
echo     ['run.py'], >> run.spec
echo     pathex=['.', 'src'], >> run.spec
echo     binaries=binaries, >> run.spec
echo     datas=datas, >> run.spec
echo     hiddenimports=hidden_imports, >> run.spec
echo     hookspath=[], >> run.spec
echo     hooksconfig={}, >> run.spec
echo     runtime_hooks=[], >> run.spec
echo     excludes=[], >> run.spec
echo     win_no_prefer_redirects=False, >> run.spec
echo     win_private_assemblies=False, >> run.spec
echo     cipher=block_cipher, >> run.spec
echo     noarchive=False, >> run.spec
echo ) >> run.spec
echo. >> run.spec
echo pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher) >> run.spec
echo. >> run.spec
echo exe = EXE( >> run.spec
echo     pyz, >> run.spec
echo     a.scripts, >> run.spec
echo     a.binaries, >> run.spec
echo     a.zipfiles, >> run.spec
echo     a.datas, >> run.spec
echo     [], >> run.spec
echo     name='inventory_management', >> run.spec
echo     debug=True, >> run.spec
echo     bootloader_ignore_signals=False, >> run.spec
echo     strip=False, >> run.spec
echo     upx=True, >> run.spec
echo     upx_exclude=[], >> run.spec
echo     runtime_tmpdir=None, >> run.spec
echo     console=True, >> run.spec
echo     disable_windowed_traceback=False, >> run.spec
echo     argv_emulation=False, >> run.spec
echo     target_arch=None, >> run.spec
echo     codesign_identity=None, >> run.spec
echo     entitlements_file=None, >> run.spec
echo ) >> run.spec

rem 清理之前的构建
rmdir /s /q build dist

rem 执行打包命令
echo Building executable...
pyinstaller --clean run.spec

echo Build process completed.
pause 