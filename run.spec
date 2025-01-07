# -*- mode: python ; coding: utf-8 -*- 
 
import os 
import sys 
from PyInstaller.utils.hooks import collect_data_files, collect_submodules 
 
# 获取 Conda 环境路径 
conda_prefix = r'D:\ProgramData\Anaconda3' 
 
block_cipher = None 
 
# 收集所有子模块 
hidden_imports = collect_submodules('lark_oapi') + [ 
    'pandas', 
    'numpy', 
    'httpx', 
    'python-dotenv', 
    'pathlib', 
    'asyncio', 
    'threading', 
    'logging', 
    'ctypes', 
    'win32api', 
    'win32con', 
] 
 
# 收集数据文件 
datas = [ 
    ('.env', '.'), 
] 
 
# 添加源代码文�?
src_files = [] 
for root, dirs, files in os.walk('src'): 
    for file in files: 
        if file.endswith('.py'): 
            target_dir = os.path.relpath(root, '.') 
            src_files.append((os.path.join(root, file), target_dir)) 
datas.extend(src_files) 
 
# 添加必要的DLL文件 
binaries = [ 
    (os.path.join(conda_prefix, 'vcruntime140.dll'), '.'), 
    (os.path.join(conda_prefix, 'python310.dll'), '.'), 
] 
 
a = Analysis( 
    ['run.py'], 
    pathex=['.', 'src'], 
    binaries=binaries, 
    datas=datas, 
    hiddenimports=hidden_imports, 
    hookspath=[], 
    hooksconfig={}, 
    runtime_hooks=[], 
    excludes=[], 
    win_no_prefer_redirects=False, 
    win_private_assemblies=False, 
    cipher=block_cipher, 
    noarchive=False, 
) 
 
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher) 
 
exe = EXE( 
    pyz, 
    a.scripts, 
    a.binaries, 
    a.zipfiles, 
    a.datas, 
    [], 
    name='inventory_management', 
    debug=True, 
    bootloader_ignore_signals=False, 
    strip=False, 
    upx=True, 
    upx_exclude=[], 
    runtime_tmpdir=None, 
    console=True, 
    disable_windowed_traceback=False, 
    argv_emulation=False, 
    target_arch=None, 
    codesign_identity=None, 
    entitlements_file=None, 
) 
