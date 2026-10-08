"""Owner enters an API key in the server terminal; it is never echoed or logged."""
import getpass
import os
from pathlib import Path
from auth import private_write


def main():
    directory = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = getpass.getpass("OpenAI API Key（輸入不會顯示）: ").strip()
    if not key or any(character.isspace() for character in key):
        raise SystemExit("未保存：憑證為空或包含空白。")
    private_write(directory / "api-key.json", key)
    print("已在伺服器保存 API Key。設定 AUTH_MODE=api_key 並重新啟動容器後生效。")


if __name__ == "__main__":
    main()
