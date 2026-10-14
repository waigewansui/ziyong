"""
足球竞猜智能推荐 - 桌面窗口版
"""
import os
import sys
import time
import socket
import subprocess

# 强制 UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE_DIR)
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

STREAMLIT_PORT = 8501
APP_URL = f"http://localhost:{STREAMLIT_PORT}"
streamlit_proc = None


def is_port_open(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1)
        return s.connect_ex(('127.0.0.1', port)) == 0


def start_streamlit():
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app.py",
            "--server.port", str(STREAMLIT_PORT),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


def wait_for_streamlit(timeout=30):
    start = time.time()
    while time.time() - start < timeout:
        if is_port_open(STREAMLIT_PORT):
            time.sleep(1)
            return True
        time.sleep(0.5)
    return False


def on_closed():
    global streamlit_proc
    if streamlit_proc and streamlit_proc.poll() is None:
        streamlit_proc.terminate()
        try:
            streamlit_proc.wait(timeout=5)
        except Exception:
            streamlit_proc.kill()


if __name__ == "__main__":
    if not is_port_open(STREAMLIT_PORT):
        streamlit_proc = start_streamlit()
        if not wait_for_streamlit(timeout=30):
            print("[ERROR] Streamlit timeout")
            if streamlit_proc:
                streamlit_proc.kill()
            sys.exit(1)

    window = webview.create_window(
        title="足球竞猜智能推荐",
        url=APP_URL,
        width=1400,
        height=900,
        min_size=(900, 600),
        confirm_close=False,
    )
    window.events.closed += on_closed
    webview.start()