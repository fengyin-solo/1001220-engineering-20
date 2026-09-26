#!/usr/bin/env python3
"""准备后端 Python 运行环境（.venv）并安装依赖。

dev-up.sh 与 backend/run.sh 共用，保证两条启动路径行为一致。分级回退：
  1. 已有可用的 backend/.venv -> 直接装依赖；
  2. 标准库 venv + ensurepip 可用（Debian 需 apt install python3-venv）-> python3 -m venv；
  3. 能联网下载 get-pip.py -> 先把 pip/virtualenv 引导到 .bootstrap，再用 virtualenv 建 venv；
每一步失败都给出可操作的报错，而不是裸栈。
"""
from __future__ import annotations

import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / "backend" / ".venv"
PY = VENV / "bin" / "python"
REQUIREMENTS = ROOT / "backend" / "requirements.txt"
BOOTSTRAP = ROOT / "backend" / ".bootstrap"
GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"


def run(cmd: list[str], **kwargs) -> int:
    print("  $", " ".join(str(c) for c in cmd))
    return subprocess.call([str(c) for c in cmd], **kwargs)


def venv_healthy() -> bool:
    if not PY.exists():
        return False
    return (
        subprocess.call(
            [str(PY), "-c", "import pip"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        == 0
    )


def stdlib_venv_usable() -> bool:
    return subprocess.call(
        [sys.executable, "-c", "import venv, ensurepip"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) == 0


def create_with_stdlib() -> bool:
    print("→ 用标准库 venv 创建 backend/.venv")
    return run([sys.executable, "-m", "venv", VENV]) == 0


def create_with_get_pip() -> bool:
    """ensurepip 缺失（常见于 Debian 精简镜像）时，用 get-pip.py 引导 virtualenv 再建环境。"""
    if BOOTSTRAP.exists():
        import shutil

        shutil.rmtree(BOOTSTRAP)
    BOOTSTRAP.mkdir(parents=True)
    print("→ ensurepip 不可用，从 bootstrap.pypa.io 引导 pip（需要网络）")
    try:
        with urllib.request.urlopen(GET_PIP_URL, timeout=20) as resp:
            script = resp.read()
        get_pip = BOOTSTRAP / "get-pip.py"
        get_pip.write_bytes(script)
    except OSError as exc:
        print(f"  下载 {GET_PIP_URL} 失败：{exc}", file=sys.stderr)
        return False
    if run([sys.executable, str(get_pip), "--target", BOOTSTRAP]) != 0:
        return False
    # 引导出的 pip 只落在 BOOTSTRAP 目录里，用 PYTHONPATH 调它安装 virtualenv
    env = dict(os.environ, PYTHONPATH=str(BOOTSTRAP))
    if subprocess.call(
        [sys.executable, "-m", "pip", "install", "-q", "virtualenv", "--target", BOOTSTRAP],
        env=env,
    ) != 0:
        print("  virtualenv 安装失败", file=sys.stderr)
        return False
    if subprocess.call(
        [sys.executable, "-m", "virtualenv", VENV], env=env
    ) != 0:
        return False
    return venv_healthy()


def main() -> int:
    if venv_healthy():
        print("→ backend/.venv 已可用，跳过创建")
    elif stdlib_venv_usable():
        if not create_with_stdlib() or not venv_healthy():
            print("✘ python3 -m venv 创建失败", file=sys.stderr)
            return 1
    else:
        hint = (
            "✘ 无法创建后端虚拟环境：当前 Python 缺少 venv/ensurepip。\n"
            "  推荐修复：Debian/Ubuntu 执行  apt install python3-venv\n"
            "  （已尝试在线引导 pip 也失败时，请检查网络后重试，或手工安装 python3-venv）"
        )
        if not create_with_get_pip():
            print(hint, file=sys.stderr)
            return 1

    print("→ 安装/校验 backend/requirements.txt")
    code = run([PY, "-m", "pip", "install", "-q", "-r", REQUIREMENTS])
    if code != 0:
        print("✘ 后端依赖安装失败，请查看上方 pip 输出", file=sys.stderr)
        return 1
    print("✔ 后端 Python 环境就绪")
    return 0


if __name__ == "__main__":
    sys.exit(main())
