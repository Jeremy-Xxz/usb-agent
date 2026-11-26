# USB 隨身 Agent

放在隨身碟上、插上 Windows 電腦就能用的本地 AI 檔案整理助理。
模型在本機執行，不需要網路、不需要 API key。

## 目前版本：v0.5.0

- 本地模型（llama.cpp + Qwen 4B GGUF），免安裝
- 檔案整理：列出、讀取、建立資料夾、移動／改名、移到回收區
- 每個動作都先提案、確認後才執行
- `/undo` 復原上一批操作（移動、回收、寫入檔案都能復原）
- 寫程式／改檔案：`write_file`、`edit_file`；寫入前顯示差異並逐項確認，原檔自動備份到 `_backup\`，`.py`／`.json` 會做語法檢查
- 連續對話（有記憶）
- 上網查資料：搜尋（ddgs）、讀網頁、存成 Markdown 筆記
- 雲端備援：預設只用本地；需要你同意才會把對話送到雲端（Groq），並顯示每次回答用了哪個模型
- 寫入防護：寫入一律逐項確認（不接受「全部同意」）；agent 無法修改自己的程式、`start.bat`、備份與復原紀錄；`/undo` 不會蓋掉你寫入後自己改過的內容
- 網路安全防護：網路內容只當資料；禁止連到本機與內網；讀過網路內容後，檔案操作一律逐項確認

## USB 結構

```
E:\
├─ start.bat           啟動檔（雙擊）
├─ my-agent\           程式碼（本 repo 管理的部分）
│  ├─ launcher.py      啟動模型、等待就緒、執行 Agent
│  ├─ local_agent.py   Agent 核心
│  ├─ providers.py     模型來源、雲端同意、API key 處理
│  └─ web_tools.py     搜尋、抓網頁、HTML 轉文字
├─ runtime\
│  ├─ llama\           llama.cpp（llama-server.exe）
│  └─ python\          嵌入式 Python（已安裝 openai 套件）
├─ models\model.gguf   本地模型
├─ notes\              筆記（save_note 存放處，不在版本控制內）
├─ data\               設定與 API key（agent 無法讀取，不在版本控制內）
└─ workspace\          預設的整理資料夾
```

`runtime\`、`models\`、`workspace\`、`notes\`、`data\` 不在版本控制內（見 `.gitignore`）。

## 使用方式

1. 插上 USB，雙擊 `start.bat`（也可以把要整理的資料夾拖到 `start.bat` 上）
2. 等模型載入（從 USB 第一次載入約 1～2 分鐘）
3. 選擇要整理的資料夾，直接按 Enter 使用 `workspace`
4. 輸入任務，例如：`列出所有檔案，建議怎麼分類`

指令：`/help` 說明、`/model` 查看或切換模型、`/key` 輸入雲端 key、`/reset` 清除記憶、`/undo` 復原上次整理、`/quit` 離開。

## 安裝搜尋套件（v0.3 起，只需一次）

```
E:\runtime\python\python.exe -m pip install ddgs
```

## 雲端模型（選用）

預設只用本地模型。要啟用雲端備援，到 Groq 取得 API key，再用下列**任一種**方式提供：

1. 啟動後輸入 `/key` 貼上（不會顯示，只存在這次執行的記憶體，最安全）
2. 環境變數 `GROQ_API_KEY`
3. 檔案 `E:\data\keys.env`，內容一行：`GROQ_API_KEY=你的key`（明碼存放，隨身碟遺失就等於 key 外洩；建議放進 VeraCrypt 加密區）

使用規則：

- 本地失敗時，會先問你要不要改用雲端；`/model cloud` 可主動切到雲端（會提醒你哪些內容會被送出）
- 每次回答後會顯示 `[使用模型]`，可以確認資料有沒有離開電腦
- agent 本身無法讀取 `data\` 資料夾，key 不會出現在對話裡

### 改用其他雲端供應商

不一定要用 Groq。任何支援 OpenAI 相容格式的服務都能接，在 `E:\data\keys.env` 寫入（範例，網址與模型名稱請以該服務的文件為準）：

```
AGENT_CLOUD=custom
AGENT_CLOUD_URL=https://服務的網址/v1
AGENT_CLOUD_MODEL=模型名稱
AGENT_CLOUD_KEY=你的key
```

網址必須是 https。也可以不寫 `AGENT_CLOUD_KEY`，啟動後用 `/key` 輸入。想完全停用雲端，寫 `AGENT_CLOUD=off`。

## 環境變數（選用）

以下設定除了環境變數，雲端相關的（`AGENT_CLOUD*`）也可以寫在 `data\keys.env`。

| 名稱 | 用途 |
|---|---|
| `AGENT_CTX` | 模型上下文長度，預設 16384（記憶體不足可改 8192） |
| `AGENT_REGION` | 搜尋地區，例如 `tw-tzh`；不設就用套件預設 |
| `AGENT_NOTES_DIR` | 筆記資料夾，預設是 USB 根目錄下的 `notes\` |
| `AGENT_SERVER_ARGS` | 傳給 llama-server 的額外參數 |
| `LOCAL_MODEL` | 本地模型名稱 |
| `GROQ_API_KEY` | Groq 的 API key（也可用 `/key` 或 `data\keys.env`） |
| `AGENT_CLOUD` | `groq`（預設）、`custom`、`off`（完全停用雲端） |
| `AGENT_CLOUD_MODEL` | 覆寫雲端模型名稱，預設 `openai/gpt-oss-120b` |
| `AGENT_CLOUD_URL` / `AGENT_CLOUD_KEY_NAME` | `custom` 時使用，網址必須是 https，且支援 OpenAI 相容格式 |
| `AGENT_KEY_FILE` | key 檔案位置，預設 `data\keys.env` |

## 更新程式

```
cd E:\
git pull
```

## 版本紀錄

- **v0.5.0**：`write_file`、`edit_file`、差異預覽、自動備份、寫入可 `/undo`、`read_file` 支援 offset、agent 自我保護

- **v0.4.1**：雲端相關設定（`AGENT_CLOUD`、`AGENT_CLOUD_URL`、`AGENT_CLOUD_MODEL`、`AGENT_CLOUD_KEY_NAME`）也可以寫在 `data\keys.env`，不必設環境變數

- **v0.4.0**：雲端備援與模型切換（`/model`、`/key`）、雲端使用需經同意、顯示使用的模型、`data\` 保護

- **v0.3.1**：啟動第一時間顯示版本與網路連線狀態（利用模型載入的等待時間檢查）

- **v0.3.0**：web_search、fetch_page、save_note；網路內容安全防護；上下文預設改為 16384

- **v0.2.0**：USB 版啟動器、繁體中文介面、選擇資料夾、連續對話、移動／回收／復原
- **v0.1.0**：本地模型加讀檔工具的最小原型

## 規劃中

- v0.5.1 受限的指令執行（`run_command`：白名單、逾時、逐次確認）
- v0.6 長期記憶
