#!/usr/bin/env python3
"""MailAssist 自动同步与部署脚本 (本地 -> 阿里云).

用于本地代码修改后，一键无感同步到阿里云服务器并平滑重启远程服务。
自动排除本地缓存文件与数据库，避免覆盖远程运行数据。
"""

import os
import sys
import subprocess
import tempfile
import tarfile
from pathlib import Path

REMOTE_HOST = os.environ.get("ALIYUN_HOST", "aliyun")
REMOTE_DIR = os.environ.get("ALIYUN_DIR", "/root/mail_assist")

# 需要同步的文件与目录
INCLUDE_ITEMS = [
    "mail_assist",
    "config",
    "tests",
    "deploy",
    "run.py",
    "requirements.txt",
    "README.md"
]

# 忽略同步的文件与文件夹规则
EXCLUDE_PATTERNS = {
    "__pycache__",
    ".pytest_cache",
    ".git",
    "venv",
    ".env",
    "data"  # 核心保护：不覆盖服务器上的 SQLite 数据库与已处理记录！
}


def should_exclude(tarinfo: tarfile.TarInfo) -> bool:
    """过滤不需要同步的文件/目录."""
    parts = Path(tarinfo.name).parts
    for p in parts:
        if p in EXCLUDE_PATTERNS or p.endswith(".pyc"):
            return True
    return False


def main():
    print("=" * 60)
    print(f"🚀 MailAssist 本地代码同步 -> 阿里云服务器 ({REMOTE_HOST})")
    print("=" * 60)

    base_dir = Path(__file__).resolve().parent

    # 1. 测试 SSH 联通性
    print(f"[*] 检查与远程主机 [{REMOTE_HOST}] 的连接...")
    test_cmd = ["ssh", "-o", "ConnectTimeout=5", REMOTE_HOST, "echo OK"]
    try:
        res = subprocess.run(test_cmd, capture_output=True, text=True, check=True)
        if "OK" not in res.stdout:
            raise RuntimeError("SSH 握手返回异常")
        print("    SSH 连接畅通！")
    except Exception as e:
        print(f"\n[错误] 无法连接到远程主机 {REMOTE_HOST}: {e}")
        print("请确认本地 ~/.ssh/config 中配置了 Host aliyun，或服务器网络可用。")
        sys.exit(1)

    # 2. 确保远程目标目录存在
    print(f"[*] 确保远程目录存在: {REMOTE_DIR}")
    subprocess.run(["ssh", REMOTE_HOST, f"mkdir -p {REMOTE_DIR}"], check=True)

    # 3. 打包本地源码 (过滤缓存与数据库)
    print("[*] 正在打包本地代码增量 (自动排除缓存与本地数据库)...")
    with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
        tmp_tar_path = tmp.name

    try:
        with tarfile.open(tmp_tar_path, "w:gz") as tar:
            for item in INCLUDE_ITEMS:
                full_path = base_dir / item
                if full_path.exists():
                    tar.add(str(full_path), arcname=item, filter=lambda ti: None if should_exclude(ti) else ti)

        # 4. 上传并远程解压
        print(f"[*] 正在推送更新至 {REMOTE_HOST}:{REMOTE_DIR} ...")
        with open(tmp_tar_path, "rb") as f:
            proc = subprocess.Popen(
                ["ssh", REMOTE_HOST, f"tar -xzf - -C {REMOTE_DIR}"],
                stdin=f,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = proc.communicate()
            if proc.returncode != 0:
                print(f"[错误] 解压推送失败: {stderr.decode()}")
                sys.exit(1)

        print("    代码同步完成！")

    finally:
        if os.path.exists(tmp_tar_path):
            try:
                os.remove(tmp_tar_path)
            except Exception:
                pass

    # 5. 检查并自动重启远程 Systemd 服务
    print("[*] 检查远程守护服务状态...")
    check_service = subprocess.run(
        ["ssh", REMOTE_HOST, "systemctl is-active mail_assist || true"],
        capture_output=True,
        text=True
    )
    status = check_service.stdout.strip()
    if status == "active":
        print("    检测到远程 mail_assist 服务正在运行，正在平滑重启服务以生效...")
        subprocess.run(["ssh", REMOTE_HOST, "systemctl restart mail_assist"], check=True)
        print("🎉 [成功] 阿里云上的 MailAssist 服务已成功重启并载入最新代码！")
    else:
        print(f"ℹ️  [提示] 代码已就绪。远程服务当前状态为 [{status or '未启动'}]。")
        print("    若已配置 systemd，可登录服务器执行: systemctl start mail_assist")

    print("=" * 60)
    print("✅ 一键同步完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
