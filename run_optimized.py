#!/usr/bin/env python3
"""
优化后的主程序启动脚本
可以选择使用优化版本或原版本
"""
import sys
import os
import argparse
from pathlib import Path

# 添加src目录到Python路径
src_path = Path(__file__).parent / "src"
sys.path.insert(0, str(src_path))


def run_optimized():
    """运行优化版本"""
    try:
        from src.main_app import main
        import asyncio
        asyncio.run(main())
    except ImportError as e:
        print(f"优化版本依赖缺失: {e}")
        print("请安装依赖: pip install -r requirements_optimized.txt")
        print("或使用原版本: python run_optimized.py --legacy")
        sys.exit(1)
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)


def run_legacy():
    """运行原版本"""
    try:
        from src.main_run import main
        main()
    except Exception as e:
        print(f"启动失败: {e}")
        sys.exit(1)


def check_dependencies():
    """检查依赖"""
    required_packages = [
        ('python-dotenv', 'dotenv'),
        ('lark-oapi', 'lark_oapi'),
        ('httpx', 'httpx'),
        ('aiohttp', 'aiohttp'),
        ('pandas', 'pandas'),
        ('numpy', 'numpy')
    ]

    # psutil在Windows上可能有问题，作为可选依赖
    optional_packages = [
        ('psutil', 'psutil')
    ]

    missing_packages = []
    missing_optional = []

    for package_name, import_name in required_packages:
        try:
            __import__(import_name)
        except ImportError:
            missing_packages.append(package_name)

    for package_name, import_name in optional_packages:
        try:
            __import__(import_name)
        except ImportError:
            missing_optional.append(package_name)

    if missing_packages:
        print("缺少以下必需依赖包:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\n请运行: pip install -r requirements_optimized.txt")
        return False

    if missing_optional:
        print("缺少以下可选依赖包 (不影响核心功能):")
        for package in missing_optional:
            print(f"  - {package}")

    return True


def main():
    parser = argparse.ArgumentParser(description='库存管理系统启动器')
    parser.add_argument(
        '--legacy',
        action='store_true',
        help='使用原版本启动（不使用优化功能）'
    )
    parser.add_argument(
        '--check-deps',
        action='store_true',
        help='检查依赖包是否完整'
    )
    parser.add_argument(
        '--config',
        type=str,
        help='指定配置文件路径（.env文件）'
    )

    args = parser.parse_args()

    # 检查依赖
    if args.check_deps:
        if check_dependencies():
            print("所有依赖包都已安装")
        return

    # 设置配置文件环境变量
    if args.config:
        os.environ['CONFIG_FILE'] = args.config

    print("=== 二牛库存管理AI助手 ===")

    if args.legacy:
        print("使用原版本启动...")
        run_legacy()
    else:
        print("使用优化版本启动...")
        if not check_dependencies():
            print("\n依赖检查失败，自动切换到原版本...")
            run_legacy()
        else:
            run_optimized()


if __name__ == "__main__":
    main()