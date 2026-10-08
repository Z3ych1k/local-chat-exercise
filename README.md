# Local Chat Exercise

Docker 裡的共享網頁聊天程式。首次打開網頁時輸入 OpenAI API Key，伺服器驗證後存到本地；其他能連入的裝置即可直接提問，毋須逐部登入。聊天紀錄保存在伺服器的 `data/chat.sqlite3`，支援延續對話、回答指示、串流回答、匯出及刪除。

改自 [OpenAI Python quickstart 的 chat-basic 範例](https://github.com/openai/openai-quickstart-python/tree/ec8890d101bdc17d66512d94a76b5e7131d188a1/examples/chat-basic)。原版用記憶體中的全域 history；此 exercise 改為 Responses API、SQLite、共享伺服器憑證、Docker Compose 和測試。`upstream/` 保存原檔，`UPSTREAM.json` 記錄 commit 與 SHA256；MIT 授權。

## 帳號與存放方式

預設 `AUTH_MODE=api_key`。首次進入網頁會顯示設定介面：輸入 Key → 伺服器向 OpenAI 驗證 → 以 0600 權限儲存在 `data/api-key.json` → 顯示聊天。已有憑證時不再顯示設定頁；客戶端不能覆寫已保存的 Key。重啟或更新容器後仍可使用。

一般 OpenAI API Key 的 API 使用量獨立計費，不能扣 ChatGPT／Codex 訂閱額度。若要使用 ChatGPT 方案，明確改為 `AUTH_MODE=chatgpt`，並由擁有人執行下面的一次性授權流程；它是另一種憑證，不是可以貼入設定欄的 API Key。兩種模式不會自動互相切換。方案模式須以實際授權、可用模型及回答確認是否獲支援。

所有憑證均留在伺服器掛載的 `data/`。ChatGPT 模式使用 `data/credentials.json` 並自動更新 token。沒有憑證寫入原始碼、Docker 映像或回傳網頁；`data/` 和 `.env` 排除於 Git 及 Docker build。

這是共享空間：能訪問聊天網頁的裝置均可查看、匯出和刪除全部聊天，並消耗擁有人授權的額度。請只讓信任的裝置連入，例如自己的 ZeroTier 網絡；Compose 預設只綁定本機。它不是多人帳號服務，也沒有離線模型。問題和相關對話會傳送至 OpenAI。

## 本機測試（不用 Docker）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest -v
.venv/bin/python app.py
```

聊天頁面：`http://127.0.0.1:8080`。在首次設定介面輸入自己的 OpenAI API Key，即可開始；沒有 Key 時仍可執行離線測試，但不會有真實模型回答。

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

啟動後進入 `http://127.0.0.1:8080`，首次設定頁輸入 API Key。Key 直接存入掛載資料夾；其他客戶端重新整理後就能聊天。8080 是聊天；1455 只供可選的 ChatGPT 方案授權回呼，綁在主機 127.0.0.1。容器重啟及更新不會刪除 `data/`。

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

`auth.py` 處理 PKCE、state、nonce、JWT 驗證、token 更新及可用模型；`setup_account.py` 只供擁有人在終端設定憑證。`static/chat.js` 處理網頁互動。此版本只做文字對話，沒有執行 shell 或其他工具的 agent loop。

如要更換已保存的 Key，可先停止容器，執行 `set_api_key.py` 在伺服器終端輸入新 Key，再啟動。此管理操作不開放給網頁客戶端。

## 文件

- [ChatGPT 與 API 分開計費](https://help.openai.com/en/articles/9039756-managing-billing-settings-on-chatgpt-web-and-platform)
- [官方模型與 Responses 呼叫](https://developers.openai.com/siwc/token-sharing-open-source/models-and-inference)
- [官方授權與 PKCE](https://developers.openai.com/siwc/token-sharing-open-source/sign-in)
- [遠端主機憑證處理](https://developers.openai.com/siwc/token-sharing-open-source/self-hosted-vms)
- [方案使用預覽限制](https://developers.openai.com/siwc/token-sharing-open-source/preview-limitations)
- [GitHub Codespaces 配額](https://docs.github.com/en/billing/concepts/product-billing/github-codespaces)
- [GitHub Container Registry](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

這是 OpenAI 範例的個人 exercise 改版，並非 OpenAI 官方產品。
