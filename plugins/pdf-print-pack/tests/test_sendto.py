#!/usr/bin/env python3
"""install-sendto.ps1 的测试：安装/卸载「发送到 → 省纸打印」。

直接运行：python tests/test_sendto.py
非 Windows 或没有 PowerShell 时自动跳过（退出码 0）。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
INSTALLER = os.path.abspath(os.path.join(
    HERE, "..", "tools", "install-sendto.ps1"))


def powershell() -> str | None:
    if os.name != "nt":
        return None
    for name in ("powershell", "powershell.exe", "pwsh"):
        found = shutil.which(name)
        if found:
            return found
    return None


def run_installer(send_to_dir: str, extra=None):
    shell = powershell()
    return subprocess.run(
        [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", INSTALLER, "-SendToDir", send_to_dir, *list(extra or [])],
        capture_output=True, text=True, encoding="utf-8", errors="replace")


def read_text_any_encoding(path: str) -> str:
    """安装脚本按 OEM 编码写出 .cmd，这里用多种编码兜底读取。"""
    for enc in ("gbk", "utf-8", "latin-1"):
        try:
            return open(path, encoding=enc).read()
        except UnicodeDecodeError:
            continue
    return open(path, encoding="utf-8", errors="replace").read()


def test_sendto_install_and_remove():
    shell = powershell()
    if shell is None:
        print("  SKIP  test_sendto_install_and_remove（非 Windows 或没有 PowerShell）")
        return
    with tempfile.TemporaryDirectory() as td:
        send_to = os.path.join(td, "SendTo")
        os.makedirs(send_to, exist_ok=True)
        target = os.path.join(send_to, "省纸打印.cmd")

        proc = run_installer(send_to)
        assert proc.returncode == 0, (proc.stdout, proc.stderr)
        assert os.path.exists(target), proc.stdout

        content = read_text_any_encoding(target)
        # 用与编码无关的 ASCII 标记校验内容
        assert "pack.py" in content, content[:200]
        assert "%*" in content, "应透传选中的文件（%*）"
        assert "pause" in content, "跑完应停在窗口里显示省纸账"
        assert "PYTHONIOENCODING=utf-8" in content

        proc2 = run_installer(send_to, ["-Remove"])
        assert proc2.returncode == 0, (proc2.stdout, proc2.stderr)
        assert not os.path.exists(target)

        # 重复卸载不报错
        proc3 = run_installer(send_to, ["-Remove"])
        assert proc3.returncode == 0


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  PASS  {name}")
            except Exception as exc:
                failed += 1
                print(f"  FAIL  {name}: {exc}")
    raise SystemExit(1 if failed else 0)
