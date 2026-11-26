"""模型來源與路由
- 預設本地模型優先。
- 雲端模型只有在你同意後才會用到：用 /model cloud 切換，或本地失敗時詢問你。
- API key 只從「環境變數、data\\keys.env、/key 輸入」取得；不寫進程式、不顯示、不傳給模型。
"""
import os
import getpass
from openai import OpenAI

HERE = os.path.dirname(os.path.abspath(__file__))
USB = os.path.dirname(HERE)
DATA_DIR = os.path.abspath(os.environ.get("AGENT_DATA_DIR", os.path.join(USB, "data")))
KEY_FILE = os.path.abspath(os.environ.get("AGENT_KEY_FILE", os.path.join(DATA_DIR, "keys.env")))

CLOUD_PRESETS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "key_name": "GROQ_API_KEY",
    },
}


def read_key(name):
    """先找環境變數，再找 keys.env（每行 名稱=值）。"""
    if os.environ.get(name):
        return os.environ[name].strip()
    try:
        with open(KEY_FILE, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                if k.strip() == name:
                    return v.strip().strip('"').strip("'")
    except OSError:
        pass
    return ""


def redact(err, secret=""):
    """錯誤訊息可能夾帶 key，顯示前一律遮掉並截短。"""
    text = str(err)
    if secret:
        text = text.replace(secret, "***")
    return text[:300]


class Provider:
    def __init__(self, name, kind, base_url, model, key=""):
        self.name, self.kind, self.base_url, self.model, self.key = name, kind, base_url, model, key

    @property
    def label(self):
        return f"本地 {self.model}" if self.kind == "local" else f"雲端 {self.name}（{self.model}）"


def local_provider():
    return Provider(
        "local", "local",
        os.environ.get("LOCAL_BASE_URL", "http://127.0.0.1:11434/v1"),
        os.environ.get("LOCAL_MODEL", "qwen3:4b"),
    )


def cloud_provider():
    """依環境變數 AGENT_CLOUD 建立雲端來源：groq（預設）、custom、off。"""
    which = os.environ.get("AGENT_CLOUD", "groq").strip().lower()
    if which == "off":
        return None
    if which == "custom":
        base_url = os.environ.get("AGENT_CLOUD_URL", "").strip()
        model = os.environ.get("AGENT_CLOUD_MODEL", "").strip()
        key_name = os.environ.get("AGENT_CLOUD_KEY_NAME", "AGENT_CLOUD_KEY").strip()
        name = "custom"
    elif which in CLOUD_PRESETS:
        preset = CLOUD_PRESETS[which]
        base_url, key_name, name = preset["base_url"], preset["key_name"], which
        model = os.environ.get("AGENT_CLOUD_MODEL", preset["model"]).strip()
    else:
        return None
    if not base_url.startswith("https://") or not model:
        return None  # 雲端一律要求 https，避免 key 以明碼傳送
    return Provider(name, "cloud", base_url, model, read_key(key_name))


def describe_cloud(p):
    if p is None:
        return "雲端模型：未啟用（只使用本地）"
    if not p.key:
        return f"雲端模型：{p.name} 尚未設定 key（需要時輸入 /key；不設定就只用本地）"
    return f"雲端模型：{p.name}（{p.model}）已設定，需要你同意才會使用"


class Router:
    def __init__(self):
        self.local = local_provider()
        self.cloud = cloud_provider()
        self.prefer = "local"
        self.session_ok = False   # 本次執行是否已同意傳送到雲端
        self.task_ok = False      # 本次任務是否已同意
        self.task_denied = False
        self.used = []

    # ----- 顯示 -----
    def banner_lines(self):
        mode = "雲端優先" if self.prefer == "cloud" else "本地優先"
        return [f"模型：{mode}｜{self.local.label}", describe_cloud(self.cloud)]

    def status(self):
        lines = [f"目前偏好：{'雲端' if self.prefer == 'cloud' else '本地'}",
                 f"本地：{self.local.label}", describe_cloud(self.cloud)]
        if self.cloud:
            lines.append("雲端使用同意：" + ("本次執行已同意" if self.session_ok else "需要時會先問你"))
        return "\n".join(lines)

    def used_label(self):
        return "｜".join(self.used) if self.used else "（沒有呼叫模型）"

    # ----- 切換與設定 -----
    def switch(self, target):
        if target == "local":
            self.prefer, self.session_ok = "local", False
            print("已切換為本地優先；雲端的同意也已收回。")
            return
        if not self.cloud:
            print("目前沒有啟用雲端模型。")
            return
        if not self.cloud.key:
            print("還沒有設定雲端 API key，請先輸入 /key。")
            return
        print(f"切換到雲端後，之後的對話內容（包含這次已讀取的檔案與網頁內容）都會傳送到 {self.cloud.name}。")
        print("如果不想送出先前的內容，請先輸入 /reset 清除記憶。")
        if input("確定切換嗎？(y/n)：").strip().lower() in ("y", "yes", "是"):
            self.prefer, self.session_ok = "cloud", True
            print(f"已切換為雲端優先（{self.cloud.label}）。雲端失敗時會自動退回本地。")
        else:
            print("已取消。")

    def ask_key(self):
        if not self.cloud:
            print("目前沒有啟用雲端模型。")
            return
        key = getpass.getpass(f"貼上 {self.cloud.name} 的 API key（輸入時不會顯示，只保存在這次執行的記憶體）：").strip()
        if key:
            self.cloud.key = key
            print("已設定。")
        else:
            print("沒有輸入，已取消。")

    # ----- 呼叫 -----
    def begin_task(self):
        self.used, self.task_ok, self.task_denied = [], False, False

    def _cloud_ok(self):
        if self.session_ok or self.task_ok:
            return True
        if self.task_denied:
            return False
        p = self.cloud
        print(f"\n  可以改用雲端 {p.name}（{p.model}）。")
        print("  注意：對話內容（包含已讀取的檔案與網頁內容）會傳送到該服務。")
        while True:
            ans = input("  允許嗎？ y=這次任務允許 / a=本次執行都允許 / n=不要：").strip().lower()
            if ans in ("y", "yes", "是"):
                self.task_ok = True
                return True
            if ans in ("a", "all", "全部"):
                self.session_ok = True
                return True
            if ans in ("n", "no", "否"):
                self.task_denied = True
                return False

    def chat(self, messages, tools):
        order = ["cloud", "local"] if self.prefer == "cloud" else ["local", "cloud"]
        problems, failed_before = [], False
        for name in order:
            p = self.local if name == "local" else self.cloud
            if p is None:
                continue
            if p.kind == "cloud":
                if not p.key:
                    problems.append("雲端：尚未設定 API key（輸入 /key 設定）")
                    continue
                if not self._cloud_ok():
                    problems.append("雲端：你沒有允許傳送到雲端")
                    continue
            if failed_before:
                print(f"  [備援] 改試 {p.label}")
            try:
                client = OpenAI(base_url=p.base_url, api_key=p.key or "none", max_retries=0, timeout=600)
                resp = client.chat.completions.create(model=p.model, messages=messages, tools=tools)
            except Exception as e:
                msg = redact(e, p.key)
                print(f"  [{p.label}] 呼叫失敗：{msg}")
                problems.append(f"{p.label}：{msg}")
                failed_before = True
                continue
            if p.label not in self.used:
                self.used.append(p.label)
            return resp
        raise RuntimeError("所有模型來源都失敗了。" + "；".join(problems))
