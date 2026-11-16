"""USB 隨身 Agent 核心（檔案整理）
用法：python local_agent.py [要整理的資料夾]
USB 版請改用 launcher.py（會自動啟動本地模型）。
"""
import os
import sys
import json
import re
import shutil
from datetime import datetime
from openai import OpenAI

VERSION = "0.2.0"

MAX_STEPS = 10            # 單次任務最多呼叫幾輪工具
MAX_TOOL_OUTPUT = 3000    # 工具回傳字數上限，避免塞爆小模型的記憶
MAX_HISTORY_CHARS = 8000  # 對話歷史上限，超過就丟掉最舊的回合
TRASH_DIR = "_trash"
LOG_FILE = "_agent_log.jsonl"

# ---------- 模型來源（依優先順序，前面失敗才換下一個）----------
PROVIDERS = [
    {
        "name": "local",
        "base_url": os.environ.get("LOCAL_BASE_URL", "http://127.0.0.1:11434/v1"),
        "api_key": "local",
        "model": os.environ.get("LOCAL_MODEL", "qwen3:4b"),
    }
]
if os.environ.get("GROQ_API_KEY"):  # 有設 key 才啟用線上備援
    PROVIDERS.append(
        {
            "name": "groq",
            "base_url": "https://api.groq.com/openai/v1",
            "api_key": os.environ["GROQ_API_KEY"],
            "model": "openai/gpt-oss-120b",
        }
    )

SYSTEM_PROMPT = (
    "你是檔案整理助理，一律使用繁體中文回答。\n"
    "你只能透過提供的工具操作檔案。所有路徑都是相對於工作資料夾的相對路徑，工作資料夾本身寫成 . 。\n"
    "規則：\n"
    "1. 動手前先用 list_dir 了解現況，需要時用 read_file 看內容。\n"
    "2. 要移動或改名時，先簡短說明整理計畫，再逐一呼叫工具；使用者會逐項確認。\n"
    "3. 不可以刪除檔案；不需要的檔案用 trash_file 移到回收區。\n"
    "4. 不確定時先問使用者，不要猜。\n"
    "5. 工具回傳錯誤或使用者拒絕時，說明原因並調整做法，不要重複同樣的呼叫。"
)


def _tool(name, desc, props, required):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": desc,
            "parameters": {
                "type": "object",
                "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
                "required": required,
            },
        },
    }


TOOLS = [
    _tool("list_dir", "列出資料夾內的檔案與子資料夾（含大小）", {"path": "資料夾路徑，工作資料夾用 ."}, ["path"]),
    _tool("read_file", "讀取文字檔內容（只讀前面一段）", {"path": "檔案路徑"}, ["path"]),
    _tool("make_dir", "建立資料夾", {"path": "新資料夾路徑"}, ["path"]),
    _tool("move_file", "移動檔案或資料夾，也可用來改名（目的地不可已存在）",
          {"src": "來源路徑", "dst": "目的地完整路徑（含檔名）"}, ["src", "dst"]),
    _tool("trash_file", "把檔案或資料夾移到回收區 _trash（可復原），用來取代刪除", {"path": "路徑"}, ["path"]),
]


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def chat(messages):
    """依序嘗試各個模型來源，失敗就換下一個。"""
    for p in PROVIDERS:
        try:
            client = OpenAI(base_url=p["base_url"], api_key=p["api_key"], max_retries=0, timeout=600)
            return client.chat.completions.create(model=p["model"], messages=messages, tools=TOOLS)
        except Exception as e:
            print(f"  [{p['name']}] 呼叫失敗：{e}")
    raise RuntimeError("所有模型來源都失敗了，請確認本地模型有在執行。")


class Agent:
    def __init__(self, root):
        self.root = os.path.realpath(root)
        self.batch = ""
        self.auto = False
        self.reset()

    def reset(self):
        self.messages = [{"role": "system", "content": SYSTEM_PROMPT + f"\n工作資料夾：{self.root}"}]

    # ---------- 安全 ----------
    def safe_path(self, p):
        """路徑必須在工作資料夾之內，否則拒絕。"""
        full = os.path.realpath(os.path.join(self.root, p))
        root_n, full_n = os.path.normcase(self.root), os.path.normcase(full)
        try:
            inside = os.path.commonpath([root_n, full_n]) == root_n
        except ValueError:  # 不同磁碟機
            inside = False
        if not inside:
            raise PermissionError("路徑超出工作資料夾範圍，已拒絕")
        return full

    def rel(self, full):
        return os.path.relpath(full, self.root)

    def confirm(self, text):
        if self.auto:
            print(f"  [自動同意] {text}")
            return True
        print(f"  [提案] {text}")
        while True:
            ans = input("  執行嗎？ y=是 / n=否 / a=本輪全部同意：").strip().lower()
            if ans in ("y", "yes", "是"):
                return True
            if ans in ("a", "all", "全部"):
                self.auto = True
                return True
            if ans in ("n", "no", "否"):
                return False

    # ---------- 工具 ----------
    def t_list_dir(self, path):
        p = self.safe_path(path)
        if not os.path.isdir(p):
            return f"錯誤：不是資料夾：{path}"
        rows = []
        for name in sorted(os.listdir(p), key=str.lower):
            if name == LOG_FILE:
                continue
            full = os.path.join(p, name)
            if os.path.isdir(full):
                rows.append(f"[資料夾] {name}")
            else:
                rows.append(f"{name}  ({fmt_size(os.path.getsize(full))})")
        if not rows:
            return "（空資料夾）"
        extra = ""
        if len(rows) > 200:
            rows, extra = rows[:200], "\n…（只顯示前 200 項）"
        return "\n".join(rows) + extra

    def t_read_file(self, path):
        p = self.safe_path(path)
        if not os.path.isfile(p):
            return f"錯誤：找不到檔案：{path}"
        with open(p, "rb") as f:
            head = f.read(2048)
        if b"\x00" in head:
            return "這是二進位檔案（例如圖片、PDF、壓縮檔），無法當文字讀取。"
        with open(p, encoding="utf-8", errors="replace") as f:
            text = f.read(MAX_TOOL_OUTPUT)
        return text + ("\n…（內容過長，只顯示前面一段）" if len(text) >= MAX_TOOL_OUTPUT else "")

    def t_make_dir(self, path):
        p = self.safe_path(path)
        if os.path.exists(p):
            return f"資料夾已存在：{path}"
        if not self.confirm(f"建立資料夾 {self.rel(p)}"):
            return "使用者拒絕了這個操作，請改問使用者想怎麼做。"
        os.makedirs(p)
        return f"已建立資料夾：{self.rel(p)}"

    def _move(self, src, dst, label="移動"):
        s, d = self.safe_path(src), self.safe_path(dst)
        if s == self.root:
            raise ValueError("不能移動工作資料夾本身")
        if not os.path.exists(s):
            raise FileNotFoundError(f"找不到：{src}")
        if os.path.exists(d):
            raise FileExistsError(f"目的地已存在：{dst}")
        if os.path.isdir(s) and os.path.normcase(d).startswith(os.path.normcase(s) + os.sep):
            raise ValueError("不能把資料夾移到它自己裡面")
        if not self.confirm(f"{label} {self.rel(s)}  →  {self.rel(d)}"):
            return "使用者拒絕了這個操作，請不要重試同一項，改問使用者想怎麼做。"
        os.makedirs(os.path.dirname(d), exist_ok=True)
        shutil.move(s, d)
        self.log_move(s, d)
        return f"已完成：{self.rel(s)} → {self.rel(d)}"

    def t_move_file(self, src, dst):
        return self._move(src, dst)

    def t_trash_file(self, path):
        s = self.safe_path(path)
        name = os.path.basename(s)
        target = os.path.join(TRASH_DIR, name)
        if os.path.exists(os.path.join(self.root, target)):
            stem, ext = os.path.splitext(name)
            target = os.path.join(TRASH_DIR, f"{stem}_{datetime.now():%H%M%S}{ext}")
        return self._move(path, target, label="移到回收區")

    def run_tool(self, name, args):
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return f"錯誤：沒有這個工具：{name}"
        if not isinstance(args, dict):
            return "錯誤：工具參數格式不正確"
        try:
            return str(fn(**args))[:MAX_TOOL_OUTPUT]
        except TypeError:
            return "錯誤：工具參數不正確，請檢查參數名稱"
        except Exception as e:
            return f"錯誤：{e}"

    # ---------- 復原紀錄 ----------
    def log_move(self, s, d):
        rec = {"batch": self.batch, "src": s, "dst": d, "undone": False}
        with open(os.path.join(self.root, LOG_FILE), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def undo(self):
        path = os.path.join(self.root, LOG_FILE)
        if not os.path.exists(path):
            print("沒有可復原的紀錄。")
            return
        with open(path, encoding="utf-8") as f:
            recs = [json.loads(line) for line in f if line.strip()]
        pending = [r for r in recs if not r["undone"]]
        if not pending:
            print("沒有可復原的紀錄。")
            return
        batch = pending[-1]["batch"]
        todo = [r for r in pending if r["batch"] == batch]
        print(f"將復原上一批共 {len(todo)} 個操作（{batch}）：")
        for r in todo:
            print(f"  {self.rel(r['dst'])}  →  {self.rel(r['src'])}")
        if input("確定復原？(y/n)：").strip().lower() not in ("y", "yes", "是"):
            print("已取消。")
            return
        for r in reversed(todo):
            try:
                src, dst = self.safe_path(r["src"]), self.safe_path(r["dst"])
                if os.path.exists(src):
                    print(f"  略過（原位置已有檔案）：{self.rel(src)}")
                    continue
                os.makedirs(os.path.dirname(src), exist_ok=True)
                shutil.move(dst, src)
                r["undone"] = True
            except Exception as e:
                print(f"  失敗：{e}")
        with open(path, "w", encoding="utf-8") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        if len(self.messages) > 1:
            self.messages.append({"role": "user", "content": "（系統通知：使用者已復原上一批檔案操作，檔案位置已改變，請重新用 list_dir 確認。）"})
        print("復原完成。（先前建立的空資料夾不會被刪除）")

    # ---------- 對話 ----------
    def trim(self):
        def size():
            total = 0
            for m in self.messages:
                total += len(m.get("content") or "")
                total += sum(len(json.dumps(tc, ensure_ascii=False)) for tc in m.get("tool_calls", []))
            return total

        trimmed = False
        while size() > MAX_HISTORY_CHARS:
            idx = next((i for i in range(2, len(self.messages)) if self.messages[i]["role"] == "user"), None)
            if idx is None:
                break
            del self.messages[1:idx]
            trimmed = True
        if trimmed:
            print("  （較早的對話已省略，以節省模型記憶）")

    def ask(self, goal):
        self.batch = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.auto = False
        self.messages.append({"role": "user", "content": goal})
        self.trim()
        for _ in range(MAX_STEPS):
            msg = chat(self.messages).choices[0].message
            text = re.sub(r"<think>.*?</think>", "", msg.content or "", flags=re.S).strip()
            entry = {"role": "assistant", "content": text}
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in msg.tool_calls
                ]
            self.messages.append(entry)

            if not msg.tool_calls:
                return text or "（模型沒有回應內容）"
            if text:
                print(f"\nAgent：{text}")

            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = None
                print(f"  [工具] {call.function.name}({args})")
                output = self.run_tool(call.function.name, args)
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": output})
        return "（已達單次任務的步數上限，先停在這裡。輸入「繼續」可以讓我接著做。）"


# ---------- 介面 ----------
def set_title(t):
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW(t)
    except Exception:
        pass


def pick_root(default_root, preset=None):
    cand = (preset or "").strip().strip('"')
    while True:
        if not cand:
            print(f"\n要整理哪個資料夾？直接按 Enter 使用預設的 {default_root}")
            cand = input("資料夾路徑（可直接把資料夾拖進視窗）：").strip().strip('"') or default_root
        if os.path.dirname(os.path.abspath(cand)) == os.path.abspath(cand):
            print("不建議直接選整個磁碟機，請選一個資料夾。")
            cand = ""
            continue
        if os.path.isdir(cand):
            return cand
        if cand == default_root:
            os.makedirs(cand, exist_ok=True)
            return cand
        print(f"找不到這個資料夾：{cand}")
        cand = ""


def banner(root):
    line = "=" * 46
    print(line)
    print(f"  USB 隨身 Agent  v{VERSION}")
    print(line)
    print(f"工作資料夾：{root}")
    print("模型來源：" + " → ".join(f"{p['name']}（{p['model']}）" for p in PROVIDERS))
    print("指令：/help 說明　/reset 清除記憶　/undo 復原上次整理　/quit 離開")


HELP = """可用指令：
  /reset  清除對話記憶，重新開始
  /undo   復原上一批移動、改名、回收的操作
  /quit   離開
其他輸入都會當成任務交給 Agent，例如：
  列出所有檔案，建議怎麼分類
  把所有 .jpg 移到 圖片 資料夾
移動、建立資料夾等動作，每一項都會先問你確認。"""


def run(default_root, preset=None):
    set_title(f"USB 隨身 Agent v{VERSION}")
    root = pick_root(default_root, preset)
    agent = Agent(root)
    banner(agent.root)
    while True:
        try:
            text = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        cmd = text.lower()
        if cmd in ("/quit", "/exit", "/q"):
            break
        if cmd == "/help":
            print(HELP)
            continue
        if cmd == "/reset":
            agent.reset()
            print("已清除對話記憶。")
            continue
        if cmd == "/undo":
            agent.undo()
            continue
        n = len(agent.messages)
        try:
            print("\nAgent：" + agent.ask(text))
        except KeyboardInterrupt:
            del agent.messages[n:]
            print("\n（已中斷這個任務）")
        except Exception as e:
            del agent.messages[n:]
            print(f"\n發生錯誤：{e}")


if __name__ == "__main__":
    run(os.getcwd(), sys.argv[1] if len(sys.argv) > 1 else None)