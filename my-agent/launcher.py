"""USB 版啟動器：顯示版本 → 啟動本地模型 → 檢查網路 → 執行 Agent → 結束時關閉模型"""
import os
import sys
import time
import subprocess
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)  # 嵌入式 Python 不一定會自動加入腳本資料夾
USB = os.path.dirname(HERE)

PORT = 8080
LLAMA = os.path.join(USB, "runtime", "llama", "llama-server.exe")
MODEL = os.path.join(USB, "models", "model.gguf")
WORKSPACE = os.path.join(USB, "workspace")
CTX = os.environ.get("AGENT_CTX", "16384")  # 模型一次能看的長度，越大越吃記憶體（要和 local_agent.py 一致）

# local_agent 在匯入時就會讀這些環境變數，所以要先設定
os.environ["LOCAL_BASE_URL"] = f"http://127.0.0.1:{PORT}/v1"
os.environ.setdefault("LOCAL_MODEL", "model")

try:
    import local_agent
    import web_tools
except ImportError as e:
    print(f"缺少必要套件或檔案：{e}")
    print(r"請確認已執行：E:\runtime\python\python.exe -m pip install openai")
    input("按 Enter 結束...")
    sys.exit(1)


def print_header():
    line = "=" * 46
    print(line)
    print(f"  USB 隨身 Agent  v{local_agent.VERSION}")
    print(line)


def healthy():
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def start_server():
    cmd = [LLAMA, "-m", MODEL, "--port", str(PORT), "--jinja", "-c", CTX]
    cmd += os.environ.get("AGENT_SERVER_ARGS", "").split()  # 額外參數，例如 --reasoning-budget 0
    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


def stop_server(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


def report_network():
    online = web_tools.check_online()
    os.environ["AGENT_ONLINE"] = "1" if online else "0"  # 讓 Agent 畫面沿用，不用再檢查一次
    if online:
        print("網路連線：已連線")
    else:
        print("網路連線：未連線（離線模式：只能使用本地功能，查資料無法使用）")


def main():
    preset = sys.argv[1] if len(sys.argv) > 1 else None
    print_header()
    for path, name in ((LLAMA, "llama-server.exe"), (MODEL, "model.gguf")):
        if not os.path.isfile(path):
            print(f"找不到 {name}：{path}")
            return

    proc = None
    try:
        if healthy():
            print("偵測到模型伺服器已在執行，直接使用。")
            report_network()
        else:
            print("正在啟動本地模型……（從 USB 第一次載入可能需要 1～2 分鐘）")
            proc = start_server()
            report_network()  # 利用模型載入的時間檢查網路
            t0 = time.time()
            while not healthy():
                if proc.poll() is not None:
                    print(f"\n模型伺服器異常結束（代碼 {proc.returncode}）。可能是記憶體不足或檔案損毀。")
                    return
                if time.time() - t0 > 600:
                    print("\n等待超過 10 分鐘，已放棄。")
                    return
                print(f"\r  載入中… 已等待 {int(time.time() - t0)} 秒", end="", flush=True)
                time.sleep(2)
            print(f"\r模型已就緒（耗時 {int(time.time() - t0)} 秒）。          ")

        local_agent.run(WORKSPACE, preset)
    finally:
        stop_server(proc)


if __name__ == "__main__":
    main()
