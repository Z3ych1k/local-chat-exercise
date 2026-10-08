# Local Chat Exercise

Docker 裡的共享網頁聊天程式。首次打開網頁時選擇 OpenAI 或 FastGPT 並輸入 API 設定，伺服器驗證後存到本地；其他能連入的裝置即可直接提問，毋須逐部登入。聊天紀錄保存在伺服器的 `data/chat.sqlite3`，支援延續對話、回答指示、串流回答、匯出及刪除。

改自 [OpenAI Python quickstart 的 chat-basic 範例](https://github.com/openai/openai-quickstart-python/tree/ec8890d101bdc17d66512d94a76b5e7131d188a1/examples/chat-basic)。原版用記憶體中的全域 history；此 exercise 改為 Responses API、SQLite、共享伺服器憑證、Docker Compose 和測試。`upstream/` 保存原檔，`UPSTREAM.json` 記錄 commit 與 SHA256；MIT 授權。

## 已驗證範圍

截至 2026-10-08，以下是實際完成的驗證，沒有把模擬測試當成帳號或 NAS 的成功證據。

| 項目 | 結果及範圍 |
| --- | --- |
| Mac 本地網頁 | Python 3.14.7，以 `python app.py` 啟動；首次設定、真實回答及本地聊天紀錄已確認。測試服務現已按要求關停 |
| 學校 MaaS／FastGPT | 已用學校服務的真實 Key 完成首次驗證與串流聊天；憑證以 0600 權限保存在本地 |
| 自動測試 | 11 項通過，涵蓋 CSRF／Host 檢查、SDK 請求格式、對話上下文、設定與紀錄保留、串流失敗及 OAuth 驗證邏輯；使用假的憑證及回應 |
| Linux Docker | GitHub Actions 已確認映像建置、容器啟動、網頁／健康檢查及重啟後 SQLite 資料保留；沒有在 CI 中使用真實 API Key |
| 官方 OpenAI／ChatGPT 方案 | 已實作及模擬測試；尚未完成真實 OpenAI Key 或 ChatGPT 方案授權的回答驗證 |
| fnOS／NAS | 尚未部署；ZeroTier、NAS 資料夾權限及真實容器內 API 連線仍待現場測試 |
| 可下載映像 | 已提供手動發布 workflow，但尚未發布 GHCR 映像；目前可下載原始碼，用 `compose.yaml` 建置。ARM64 映像亦未實測 |

實際成功的呼叫是「OpenAI Python SDK → 學校 FastGPT 的相容接口 → 應用回覆」，並不是直接向官方 OpenAI 服務取得回答。私密設定、App ID 和聊天內容不包含在此原始碼中。

## 局限性

- **共享使用，沒有個人帳號或權限分隔。** 所有能連入的裝置都可讀取、匯出、刪除全部對話，並使用同一 Key 的額度。首次設定也沒有管理員登入，應在只有擁有人能訪問的環境完成；不適合直接開放公網。
- **本地保存不等於加密或離線。** Key 和聊天資料以未加密檔案保存；0600 檔案權限不能代替磁碟加密。伺服器管理員、備份或取得磁碟資料的人可能讀取它們。問題及上下文會送到所選 API 服務，對方仍可能按其政策記錄資料。程式本身沒有 HTTPS，對外訪問需另行配置受信任網絡或 HTTPS 入口。
- **每次只處理一個模型回答。** 另一個同時發送的請求會收到 409，沒有排隊功能。Docker 的 Gunicorn 必須維持一個 worker；鎖是程序內的，增加 worker 不會得到全域並行限制。沒有每位使用者的速率或額度上限，服務端限速及費用仍由 API 平台決定。
- **只支援文字對話。** 沒有圖片、文件上傳、語音、工具執行或 agent loop；回答以純文字顯示。FastGPT 的知識庫引用卡片、工作流變數、工具事件和會話管理沒有同步到本地介面。
- **上下文及設定有邊界。** 每次發送完整的成功對話上下文，沒有自動摘要或按 token 截短，長對話可能超出模型上限或增加用量。單次問題上限 16,000 字，整個 JSON 請求上限 64 KiB。FastGPT 的模型、提示詞及知識庫由其應用控制，本地不能覆寫；OpenAI 模型列表也不保證每個模型都支援此程式的 Responses 呼叫。
- **Key 維護由擁有人處理。** 客戶端不能修改已保存的設定；換 Key／服務需在伺服器終端執行 `set_api_key.py`，該終端操作不會驗證 Key。Key 過期、額度用盡或 FastGPT 工作流改動仍會使回答失敗。首次 FastGPT 驗證會發送一條真實短訊息，可能消耗額度。
- **環境與版本相容性仍需實測。** Mac 本地預覽已改用不 fork 的啟動方式，以避開此次 Gunicorn／系統代理崩潰。Linux CI 不代表所有 NAS、CPU 架構或 FastGPT 部署版本可用；`python app.py` 供本地測試，正式容器採 Gunicorn。

## 與 Exercise 目標的對照

已涵蓋安裝依賴、修改小程式、用 SDK 發送 API 請求、探索非串流／串流和多輪對話，以及使用學校 MaaS 的 API 地址與憑證。Docker、共享 GUI、SQLite 和 CI 是延伸功能。

如果課程要求直接呼叫官方 OpenAI，還需以真正的 OpenAI API Key 補做驗證；目前學校 MaaS 的成功呼叫不能替代這項證據。README 的文件連結與程式說明也不能代替使用者本人閱讀及理解 API。提交格式及評分仍以課程要求為準。

## 帳號與存放方式

預設 `AUTH_MODE=api_key`。首次進入網頁會顯示設定介面：選擇服務並輸入設定 → 伺服器驗證連線 → 以 0600 權限儲存在 `data/api-key.json` → 顯示聊天。已有憑證時不再顯示設定頁；客戶端不能覆寫已保存的 Key。重啟或更新容器後仍可使用。

一般 OpenAI API Key 的 API 使用量獨立計費，不能扣 ChatGPT／Codex 訂閱額度。若要使用 ChatGPT 方案，明確改為 `AUTH_MODE=chatgpt`，並由擁有人執行下面的一次性授權流程；它是另一種憑證，不是可以貼入設定欄的 API Key。兩種模式不會自動互相切換。方案模式須以實際授權、可用模型及回答確認是否獲支援。

所有憑證均留在伺服器掛載的 `data/`。ChatGPT 模式使用 `data/credentials.json` 並自動更新 token。沒有憑證寫入原始碼、Docker 映像或回傳網頁；`data/` 和 `.env` 排除於 Git 及 Docker build。

這是共享空間：能訪問聊天網頁的裝置均可查看、匯出和刪除全部聊天，並消耗擁有人授權的額度。請只讓信任的裝置連入，例如自己的 ZeroTier 網絡；Compose 預設只綁定本機。它不是多人帳號服務，也沒有離線模型。問題和相關對話會傳送至你選擇的 OpenAI 或 FastGPT 服務。

## FastGPT 設定

首次設定頁選「FastGPT」，填 API 地址、API Key 和 App ID：

- API 地址以服務的文件為準，通常為 `https://你的服務地址/api/v1`。以 `/api` 結尾時自動補 `/v1`，也接受完整 `/api/v1/chat/completions` 地址。
- 在 FastGPT 應用「發布渠道 → API」取得 Key；App ID 可在應用詳情網址找到。本程式把 App ID 單獨放在請求內容。
- 儲存前會發送「連線測試：請只回答 OK。」來驗證應用，可能消耗少量額度。失敗不保存，成功以 0600 權限保存到 `data/api-key.json`。舊版 OpenAI Key 檔案仍可使用。
- 模型、知識庫、工作流及回答指示由 FastGPT 應用設定。此網頁顯示 FastGPT 應用，隱藏本地回答指示。
- 使用 Chat Completions 及串流文字回答，不傳 `chatId`，每次以本地 SQLite 的成功對話提供上下文。FastGPT 仍可能按其服務設定記錄請求。
- 目前沒有同步 FastGPT 的引用卡片、文件上傳或工作流變數；適用一般文字對話應用。
- 若 FastGPT 也在 Docker 裡，地址須可由聊天容器訪問；容器中的 `localhost` 指容器本身。

參考 [FastGPT API 發布](https://doc.fastgpt.cn/zh-CN/guide/build/publish/openapi) 及 [API 文件介紹](https://doc.fastgpt.cn/zh-CN/openapi/intro)。4.15 起以服務自己生成的 API 文件為準，部署版本差異需以真實連線確認。

## 本機測試（不用 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest -v
.venv/bin/python app.py
```

聊天頁面：`http://127.0.0.1:8080`。在首次設定介面輸入 OpenAI 或 FastGPT 設定，即可開始；沒有 Key 時仍可執行離線測試，但不會有真實模型回答。

Mac 本地測試請用上述 `python app.py`，不要以 Gunicorn 啟動。Gunicorn 的 fork 子程序與 macOS 系統代理讀取不相容，可在第一次 API 請求時令 Python 崩潰。本地 Flask 服務不使用 fork 或自動重載；Docker 在 Linux 容器內使用 Gunicorn。修改程式後需重新啟動本地服務。

只有 ChatGPT 方案模式才需要：先設定 `AUTH_MODE=chatgpt` 再啟動，另開終端，在同一資料夾執行：

```bash
.venv/bin/python setup_account.py
```

在擁有人電腦的瀏覽器開啟終端顯示的官方 OpenAI URL，完成一次授權。成功後重新整理聊天頁面即可選擇模型及提問；沒有登入按鈕。授權連結十分鐘後過期，失敗可重新執行設定。重新設定時先等所有回答完成。

## Docker Compose

在專案根目錄：

```bash
cp .env.example .env
mkdir -p data
# Linux 上讓容器 UID 10001 可以寫入掛載資料夾：
sudo chown 10001:10001 data
chmod 700 data
docker compose up -d --build
```

啟動後進入 `http://127.0.0.1:8080`，首次設定頁選擇 OpenAI 或 FastGPT 並輸入設定。Key 直接存入掛載資料夾；其他客戶端重新整理後就能聊天。8080 是聊天；1455 只供可選的 ChatGPT 方案授權回呼，綁在主機 127.0.0.1。容器重啟及更新不會刪除 `data/`。

若使用自訂 UID/GID，在 `.env` 設定 `CHAT_UID`、`CHAT_GID` 並讓 `data/` 的擁有人一致。Mac Docker Desktop 通常不需 Linux 的 chown 步驟。

## 日後 fnOS／ZeroTier 部署

目前先測試，未部署 fnOS。日後在 `.env` 設 `CHAT_BIND_IP` 為 NAS 的 ZeroTier IP，並把同一 IP 加進 `CHAT_HOSTS`，例如：

```dotenv
CHAT_BIND_IP=10.147.17.10
CHAT_HOSTS=127.0.0.1,localhost,10.147.17.10
AUTH_MODE=api_key
```

正式聊天網址會是 `http://NAS_ZEROTIER_IP:8080`；API Key 模式直接在網頁完成首次設定。只有使用 `AUTH_MODE=chatgpt` 才需要下面的 SSH 流程。首次授權的 127.0.0.1 callback 會到達擁有人的電腦，因此先在擁有人電腦建立 SSH 轉發，再於 NAS 執行 setup：

```bash
ssh -L 1455:127.0.0.1:1455 NAS_USER@NAS_ZEROTIER_IP
# 在上述 NAS 終端進入專案資料夾：
docker compose exec chat python setup_account.py
```

打開輸出的官方 URL，完成授權後關閉 SSH。之後伺服器自行更新憑證，日常聊天不需要 SSH 或再次登入。如果授權被撤銷或 refresh token 失效，擁有人須重新設定一次。

## GitHub 測試及 Docker 映像

- `Test and build` workflow：每次 push 執行離線測試，實際 build／啟動 Docker、檢查網頁與健康狀態，以及重啟後 SQLite 保留資料。
- `Publish private Docker image` workflow：手動執行後產生 `linux/amd64`、`linux/arm64` 映像。新 GitHub Container Registry 套件預設 private；發布後確認其權限。
- 所有 CI 測試使用假的回應及憑證，不需要上傳 ChatGPT token。CI 通過不代表你的帳號已獲方案使用權限。
- `.devcontainer/` 可在 GitHub Codespaces 開啟。Codespaces 是有配額的開發環境，並非永久免費主機。需要一次性 loopback 授權時，把 1455 轉發到擁有人電腦；日常 GUI 用 8080。

映像完成發布後，在 NAS 用 GitHub 的 `read:packages` token 登入 `ghcr.io`（請在終端的 Password 提示輸入，勿放入檔案或指令歷史）：

```bash
docker login ghcr.io -u Z3ych1k
docker compose -f compose.image.yaml pull
docker compose -f compose.image.yaml up -d

```

`compose.image.yaml` 和 `.env`、`data/` 放在同一資料夾。若不使用映像，也可 clone 私人 repo 後用 `compose.yaml` 在 NAS build。

## Exercise 的 API 程式

核心位於 `app.py` 的 `send_message()`：從 SQLite 讀取完整 history，呼叫官方 OpenAI Python SDK 的 `client.responses.create(...)`，設定 `instructions`、`input`、`store=False`、`stream=True`，逐段回傳文字；收到 `response.completed` 才標記成功。失敗或中斷仍保留問題及收到的文字。

FastGPT 分支改用 `client.chat.completions.create(...)`，傳入 `appId` 和完整對話、逐段回傳文字，收到結束原因才標記成功。測試透過真實 SDK 和假的 HTTP transport 驗證路徑、請求格式、串流及錯誤處理；不消耗真實額度。

`auth.py` 處理 PKCE、state、nonce、JWT 驗證、token 更新及可用模型；`setup_account.py` 只供擁有人在終端設定憑證。`static/chat.js` 處理網頁互動。此版本只做文字對話，沒有執行 shell 或其他工具的 agent loop。

如要更換已保存的 Key，可先停止容器，執行 `set_api_key.py` 在伺服器終端選擇服務並輸入新設定（FastGPT 同時輸入地址和 App ID），再啟動。此管理操作不開放給網頁客戶端。

## 文件

- [ChatGPT 與 API 分開計費](https://help.openai.com/en/articles/9039756-managing-billing-settings-on-chatgpt-web-and-platform)
- [官方模型與 Responses 呼叫](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [官方授權與 PKCE](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [遠端主機憑證處理](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [方案使用預覽限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [GitHub Codespaces 配額](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

這是 OpenAI 範例的個人 exercise 改版，並非 OpenAI 官方產品。
