#!/usr/bin/env python3
"""
Test runner: feeds the task to terminal.py via stdin
"""
import subprocess
import sys
import threading
import time

task = '帮我在桌面创建一个文件夹，生成一个关于MCP协议的报告放在里面，给我word，要使用浏览器代理搜索\n'

proc = subprocess.Popen(
    [sys.executable, r"D:\软件\XianRenZhangAgent\terminal.py"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    cwd=r"D:\软件\XianRenZhangAgent",
    env={"PYTHONIOENCODING": "utf-8"},
)

def feeder():
    time.sleep(2)  # Wait for init
    proc.stdin.write(task.encode("utf-8"))
    proc.stdin.flush()
    time.sleep(30)  # Let it run for 30 seconds
    proc.stdin.close()

t = threading.Thread(target=feeder, daemon=True)
t.start()

for line in proc.stdout:
    try:
        print(line.decode("utf-8", errors="replace"), end="")
    except:
        print(repr(line))

proc.wait()
print(f"\nExit code: {proc.returncode}")
