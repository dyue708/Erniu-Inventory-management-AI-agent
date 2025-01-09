from setuptools import setup
from setuptools.extension import Extension
from Cython.Build import cythonize
import os

# 获取所有Python源文件
def get_py_files():
    py_files = []
    for root, dirs, files in os.walk('src'):
        for file in files:
            if file.endswith('.py'):
                full_path = os.path.join(root, file)
                py_files.append(full_path)
    return py_files

# 创建Extension对象列表
extensions = [
    Extension(
        f"{os.path.splitext(file)[0].replace(os.path.sep, '.')}",
        [file],
        extra_compile_args=["/O2"] if os.name == 'nt' else ["-O2"],
    )
    for file in get_py_files()
]

setup(
    name='inventory_management',
    ext_modules=cythonize(
        extensions,
        compiler_directives={
            'language_level': 3,
            'embedsignature': True,
            'binding': True,
        },
    ),
    zip_safe=False,
) 