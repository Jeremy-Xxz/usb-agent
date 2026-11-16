# USB 隨身 Agent

放在隨身碟上、插上 Windows 電腦就能用的本地 AI 檔案整理助理。
模型在本機執行，不需要網路、不需要 API key。

## 目前版本：v0.2.0

- 本地模型（llama.cpp + Qwen 4B GGUF），免安裝
- 檔案整理：列出、讀取、建立資料夾、移動／改名、移到回收區
- 每個動作都先提案、確認後才執行
- `/undo` 復原上一批操作
- 連續對話（有記憶）

## USB 結構

```
E:\
├─ start.bat           啟動檔（雙擊）
├─ my-agent\           程式碼（本 repo 管理的部分）
│  ├─ launcher.py      啟動模型、等待就緒、執行 Agent
│  └─ local_agent.py   Agent 核心
├─ runtime\
│  ├─ llama\           llama.cpp（llama-server.exe）
│  └─ python\          嵌入式 Python（已安裝 openai 套件）
├─ models\model.gguf   本地模型
└─ workspace\          預設的整理資料夾
```

`runtime\`、`models\`、`workspace\` 不在版本控制內（見 `.gitignore`）。

## 使用方式

1. 插上 USB，雙擊 `start.bat`（也可以把要整理的資料夾拖到 `start.bat` 上）
2. 等模型載入（從 USB 第一次載入約 1～2 分鐘）
3. 選擇要整理的資料夾，直接按 Enter 使用 `workspace`
4. 輸入任務，例如：`列出所有檔案，建議怎麼分類`

指令：`/help` 說明、`/reset` 清除記憶、`/undo` 復原上次整理、`/quit` 離開。

## 環境變數（選用）

| 名稱 | 用途 |
|---|---|
| `AGENT_CTX` | 模型上下文長度，預設 8192 |
| `AGENT_SERVER_ARGS` | 傳給 llama-server 的額外參數 |
| `LOCAL_MODEL` | 本地模型名稱 |
| `GROQ_API_KEY` | 設定後啟用線上備援 |

## 更新程式

```
cd E:\
git pull
```

## 版本紀錄

- **v0.2.0**：USB 版啟動器、繁體中文介面、選擇資料夾、連續對話、移動／回收／復原
- **v0.1.0**：本地模型加讀檔工具的最小原型

## 規劃中

- v0.3 查資料（搜尋、抓網頁、存筆記）
- v0.4 線上備援與模型路由
- v0.5 寫程式（差異預覽、受限的指令執行）
- v0.6 長期記憶
