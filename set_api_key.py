"""Owner enters an API key in the server terminal; it is never echoed or logged."""
import getpass
import json
import os
from pathlib import Path
from auth import private_write
from app import fastgpt_url


def main():
    directory = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = Path(os.environ.get("OPENAI_API_KEY_FILE", directory / "api-key.json"))
    saved = json.loads(path.read_text()) if path.exists() else ""
    settings = saved if isinstance(saved, dict) else {"provider": "openai"}
    provider = input(f"API 服務 openai／fastgpt [{settings['provider']}]: ").strip() or settings["provider"]
    if provider not in {"openai", "fastgpt"}:
        raise SystemExit("未保存：服務必須是 openai 或 fastgpt。")
    if provider == "fastgpt":
        try:
            base_url = fastgpt_url(input(f"FastGPT API 地址 [{settings.get('base_url', '')}]: ").strip() or settings.get("base_url", ""))
        except ValueError as error:
            raise SystemExit(str(error)) from error
        app_id = input(f"FastGPT App ID [{settings.get('app_id', '')}]: ").strip() or settings.get("app_id", "")
        if not app_id or len(app_id) > 250 or any(c.isspace() for c in app_id):
            raise SystemExit("未保存：App ID 無效。")
    key = getpass.getpass(f"{provider} API Key（輸入不會顯示）: ").strip()
    if not key or any(character.isspace() for character in key):
        raise SystemExit("未保存：憑證為空或包含空白。")
    value = {"provider": provider, "base_url": base_url, "app_id": app_id, "api_key": key} if provider == "fastgpt" else key
    private_write(path, value)
    print("已保存 API 設定（此終端操作未驗證連線）。設定 AUTH_MODE=api_key 並重新啟動容器後生效。")


if __name__ == "__main__":
    main()
