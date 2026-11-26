"""網路工具：搜尋、抓網頁、HTML 轉純文字
只用標準函式庫抓網頁；搜尋用 ddgs 套件（pip install ddgs）。
"""
import os
import re
import socket
import ipaddress
import urllib.request
from urllib.parse import urlparse
from html.parser import HTMLParser

MAX_DOWNLOAD = 1_500_000  # 最多下載 1.5MB
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (compatible; USB-Agent/0.3)"


# ---------- 搜尋 ----------
def search(query, max_results=5):
    try:
        from ddgs import DDGS
    except ImportError:
        raise RuntimeError("尚未安裝搜尋套件。請在 USB 的 Python 執行：python.exe -m pip install ddgs")
    kwargs = {"max_results": max_results}
    region = os.environ.get("AGENT_REGION")  # 例如 tw-tzh；不設就用套件預設
    if region:
        kwargs["region"] = region
    try:
        raw = DDGS(timeout=10).text(query, **kwargs)
    except Exception as e:
        raise RuntimeError(f"搜尋失敗（可能沒有網路，或被搜尋服務暫時限流）：{e}")
    return [
        {"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", "")}
        for r in raw
        if r.get("href")
    ]


# ---------- 安全：禁止連到本機與內部網路 ----------
def check_url(url):
    u = urlparse(url)
    if u.scheme not in ("http", "https"):
        raise ValueError("只支援 http / https 網址")
    host = u.hostname
    if not host:
        raise ValueError("網址格式不正確")
    port = u.port or (443 if u.scheme == "https" else 80)
    try:
        infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise ValueError("無法解析網域名稱，請確認網址和網路連線")
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if getattr(ip, "ipv4_mapped", None):
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            raise PermissionError("不允許連線到本機或內部網路位址")


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """每一次轉址都重新檢查，避免被導向內部網路。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------- HTML → 純文字 ----------
_BLOCK = {"p", "div", "br", "li", "ul", "ol", "tr", "section", "article", "pre",
          "blockquote", "table", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt"}
_ALWAYS_SKIP = {"script", "style", "noscript", "svg", "template", "iframe"}
_STRICT_SKIP = _ALWAYS_SKIP | {"nav", "footer", "aside", "form"}


class _Extractor(HTMLParser):
    def __init__(self, skip):
        super().__init__(convert_charrefs=True)
        self.skip = skip
        self.depth = 0
        self.parts = []
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.skip:
            self.depth += 1
        elif tag == "title":
            self._in_title = True
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.skip:
            self.depth = max(0, self.depth - 1)
        elif tag == "title":
            self._in_title = False
        elif tag in _BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self.depth == 0:
            self.parts.append(data)


def _extract(html, skip):
    p = _Extractor(skip)
    p.feed(html)
    p.close()
    lines = []
    for line in "".join(p.parts).splitlines():
        line = re.sub(r"[ \t\u00a0\u3000]+", " ", line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return re.sub(r"\s+", " ", p.title).strip(), "\n".join(lines)


def html_to_text(html):
    """回傳 (標題, 內文)。先用嚴格模式去掉導覽列等，內容太少就改用寬鬆模式。"""
    title, text = _extract(html, _STRICT_SKIP)
    if len(text) < 200:
        title2, text2 = _extract(html, _ALWAYS_SKIP)
        if len(text2) > len(text):
            title, text = title2 or title, text2
    return title, text


def _decode(raw, content_type):
    m = re.search(r"charset=([\w\-]+)", content_type or "", re.I)
    if not m:
        m = re.search(rb"<meta[^>]+charset=[\"']?([\w\-]+)", raw[:4096], re.I)
        enc = m.group(1).decode("ascii", "ignore") if m else "utf-8"
    else:
        enc = m.group(1)
    try:
        return raw.decode(enc, errors="replace")
    except LookupError:
        return raw.decode("utf-8", errors="replace")


# ---------- 抓網頁 ----------
def fetch_text(url):
    """抓網頁並回傳 (標題, 純文字)。"""
    check_url(url)
    opener = urllib.request.build_opener(_SafeRedirect)
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8"}
    )
    with opener.open(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "")
        raw = r.read(MAX_DOWNLOAD)
    kind = ctype.split(";")[0].strip().lower()
    if kind in ("text/html", "application/xhtml+xml", ""):
        return html_to_text(_decode(raw, ctype))
    if kind.startswith("text/"):
        return "", _decode(raw, ctype).strip()
    raise ValueError(f"不支援的內容格式：{kind or '未知'}（目前只能讀網頁與純文字）")
