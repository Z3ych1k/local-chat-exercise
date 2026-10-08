// Adapted from the upstream Flask chat example. JSON-framed POST streaming avoids
// EventSource reconnections issuing another paid request and preserves newlines.
const $ = (id) => document.getElementById(id);
const csrf = document.querySelector('meta[name="csrf-token"]').content;
let currentChat = null, connected = false, busy = false, preferredModel = "";

function notice(message) { $("notice").textContent = message; $("notice").hidden = !message; }
async function api(path, method = "GET", body) {
  const response = await fetch(path, {method, headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: body === undefined ? undefined : JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "操作未完成，請稍後再試。");
  return data;
}
function availability() {
  const ready = connected && $("model").options.length && $("model").value;
  for (const id of ["new-chat", "message", "send", "reload-models"]) $(id).disabled = busy || !ready;
  for (const id of ["model", "delete-chat", "save-instructions"]) $(id).disabled = busy || (id === "model" && !connected);
  $("composer-hint").textContent = busy ? "正在回答…對話會自動儲存" : ready ? "Enter 傳送，Shift + Enter 換行" : "等待擁有人設定伺服器憑證及模型";
  document.querySelectorAll(".chat-item").forEach(button => button.disabled = busy);
}
async function loadModels() {
  $("model").replaceChildren();
  try {
    const data = await api("/api/models");
    notice("");
    const preferred = localStorage.getItem("local-chat-model") || preferredModel;
    for (const model of data.models) $("model").add(new Option(model.name, model.id));
    if (data.models.some(model => model.id === preferred)) $("model").value = preferred;
  } catch (error) { notice(error.message); }
  availability();
}
async function refreshServer() {
  const status = await api("/api/status");
  connected = status.connected; preferredModel = status.preferred_model;
  const fastgpt = status.provider === "fastgpt";
  $("account-label").textContent = connected ? "伺服器憑證已設定" : "等待首次設定";
  $("account-note").textContent = !connected ? "儲存設定後即可直接對話" : status.mode === "chatgpt" ? "使用擁有人的 ChatGPT 方案額度" : fastgpt ? "使用伺服器的 FastGPT 應用" : "使用伺服器的 OpenAI API Key";
  $("instructions-panel").hidden = fastgpt; $("fastgpt-note").hidden = !fastgpt;
  document.querySelector(".model-label").textContent = fastgpt ? "APP" : "MODEL";
  $("privacy-note").textContent = `本地紀錄不等於離線回答，問題及相關對話會傳送至 ${fastgpt ? "FastGPT" : "OpenAI"}。`;
  $("model").replaceChildren();
  if (connected) await loadModels();
  else {
    $("model").add(new Option("等待伺服器設定", ""));
    if (status.mode === "chatgpt") notice("請由擁有人在伺服器完成一次授權，完成後重新整理本頁即可提問。");
  }
  $("setup-panel").hidden = connected || status.mode !== "api_key";
  if (!connected && status.mode === "api_key") {
    $("welcome").hidden = true; $("conversation").hidden = true;
  } else if (!currentChat) $("welcome").hidden = false;
  document.querySelector(".composer-area").hidden = !connected && status.mode === "api_key";
  await refreshChats(); availability();
}
async function refreshChats() {
  const {chats} = await api("/api/chats");
  $("chat-count").textContent = chats.length;
  $("chat-list").replaceChildren();
  for (const chat of chats) {
    const button = document.createElement("button");
    button.className = "chat-item" + (chat.id === currentChat ? " active" : "");
    button.textContent = chat.title; button.title = chat.title; button.disabled = busy;
    button.addEventListener("click", () => run(() => openChat(chat.id)));
    $("chat-list").append(button);
  }
  if (!chats.length) { const p = document.createElement("p"); p.className = "quiet"; p.textContent = "還未有對話，開始聊聊吧。"; $("chat-list").append(p); }
}
function showMessage(role, text, state = "complete") {
  const article = document.createElement("article"); article.className = "message " + role;
  const label = document.createElement("div"); label.className = "message-label";
  const icon = document.createElement("span"); icon.textContent = role === "user" ? "你" : "L";
  label.append(icon, document.createTextNode(role === "user" ? "你" : "LOCAL CHAT"));
  const content = document.createElement("div"); content.className = "message-content"; content.textContent = text;
  article.append(label, content);
  if (state !== "complete") { const note = document.createElement("div"); note.className = "message-status"; note.textContent = state === "pending" ? "回答中…" : "回答未完成，已保留收到的文字。"; article.append(note); }
  $("messages").append(article); return content;
}
async function openChat(id) {
  const chat = await api("/api/chats/" + id); currentChat = id;
  $("welcome").hidden = true; $("conversation").hidden = false;
  $("chat-title").textContent = chat.title; $("instructions").value = chat.instructions;
  $("export").href = `/api/chats/${id}/export`; $("messages").replaceChildren();
  for (const message of chat.messages) showMessage(message.role, message.content, message.status);
  await refreshChats(); scrollChat();
}
function scrollChat() { $("conversation").scrollTop = $("conversation").scrollHeight; }
async function newChat() { const chat = await api("/api/chats", "POST", {}); await openChat(chat.id); $("message").focus(); }
async function run(action) { try { await action(); } catch (error) { notice(error.message || "操作未完成。"); } }
$("setup-form").addEventListener("submit", event => {
  event.preventDefault();
  run(async () => {
    const body = {provider: $("provider").value, api_key: $("api-key").value,
                  base_url: $("base-url").value.trim(), app_id: $("app-id").value.trim()};
    const fields = ["save-key", "api-key", "provider", "base-url", "app-id"];
    for (const id of fields) $(id).disabled = true;
    notice(body.provider === "fastgpt" ? "正在測試 FastGPT 應用，可能需要稍等…" : "正在驗證 API Key…");
    try {
      await api("/api/setup", "POST", body);
      $("api-key").value = ""; notice("已保存伺服器憑證，所有客戶端現在可直接對話。");
      await refreshServer();
    } finally { for (const id of fields) $(id).disabled = false; }
  });
});
$("provider").onchange = () => {
  const fastgpt = $("provider").value === "fastgpt";
  $("fastgpt-fields").hidden = !fastgpt;
  $("base-url").required = fastgpt; $("app-id").required = fastgpt;
  $("key-label").textContent = fastgpt ? "FastGPT API Key" : "OpenAI API Key";
  $("api-key").placeholder = fastgpt ? "FastGPT 的 API Key" : "sk-…";
  $("setup-billing").textContent = fastgpt ? "驗證會發送一條短測試訊息，可能消耗少量 FastGPT 額度。模型及回答方式在 FastGPT 應用內設定。" : "OpenAI API 按使用量獨立計費，不使用 ChatGPT／Codex 訂閱額度。";
};
$("new-chat").onclick = () => run(newChat);
$("reload-models").onclick = () => run(loadModels);
$("model").onchange = () => localStorage.setItem("local-chat-model", $("model").value);
$("save-instructions").onclick = () => run(async () => { await api(`/api/chats/${currentChat}`, "PATCH", {instructions: $("instructions").value}); notice("已儲存回答指示，下次提問時生效。"); });
$("delete-chat").onclick = () => run(async () => { if (!confirm("刪除這段對話？此操作無法復原。")) return; await api(`/api/chats/${currentChat}`, "DELETE", {}); currentChat = null; $("conversation").hidden = true; $("welcome").hidden = false; await refreshChats(); });
for (const button of document.querySelectorAll("[data-prompt]")) button.onclick = () => { if (!connected) { notice("請由擁有人完成伺服器授權，再重新整理本頁。"); return; } $("message").value = button.dataset.prompt.replaceAll("\\n", "\n"); $("message").focus(); };
$("message").addEventListener("keydown", event => { if (event.key === "Enter" && !event.shiftKey && !event.isComposing) { event.preventDefault(); if (!$("send").disabled) $("message-form").requestSubmit(); } });
$("message-form").addEventListener("submit", event => {
  event.preventDefault(); if (busy || !connected) return;
  const message = $("message").value.trim(); if (!message) return;
  run(async () => {
    notice(""); busy = true; availability();
    let accepted = false;
    try {
      if (!currentChat) await newChat();
      const response = await fetch(`/api/chats/${currentChat}/messages`, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRF-Token": csrf}, body: JSON.stringify({message, model: $("model").value})});
      if (!response.ok) { const data = await response.json(); throw new Error(data.error || "請求未完成。"); }
      accepted = true; $("message").value = ""; showMessage("user", message);
      const output = showMessage("assistant", ""); output.classList.add("typing");
      const reader = response.body.getReader(), decoder = new TextDecoder();
      let buffer = "", finished = false;
      try {
        while (true) {
          const chunk = await reader.read(); buffer += decoder.decode(chunk.value || new Uint8Array(), {stream: !chunk.done});
          let boundary;
          while ((boundary = buffer.indexOf("\n\n")) !== -1) {
            const frame = buffer.slice(0, boundary); buffer = buffer.slice(boundary + 2);
            if (!frame.startsWith("data: ")) continue;
            const data = JSON.parse(frame.slice(6));
            if (data.type === "delta") { output.textContent += data.text; scrollChat(); }
            if (data.type === "error") notice(data.message);
            if (data.type === "done") finished = true;
          }
          if (chunk.done) break;
        }
        if (!finished) notice("連線中斷，請重新整理確認已儲存的對話。");
      } finally { output.classList.remove("typing"); reader.releaseLock(); }
    } finally {
      busy = false; availability();
      if (accepted) await openChat(currentChat);
      $("message").focus();
    }
  });
});
run(refreshServer);
