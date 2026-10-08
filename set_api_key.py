"""Owner enters an API key in the server terminal; it is never echoed or logged."""
import getpass
import os
from pathlib import Path
import secrets


def main():
    directory = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = getpass.getpass("OpenAI API Key（輸入不會顯示）: ").strip()
    if not key or any(character.isspace() for character in key):
        raise SystemExit("未保存：憑證為空或包含空白。")
    path = directory / "api-key.txt"
    temp = path.with_name(path.name + "." + secrets.token_hex(8) + ".tmp")
    try:
        with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
            file.write(key)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)
    print("已在伺服器保存 API Key。設定 AUTH_MODE=api_key 並重新啟動容器後生效。")


if __name__ == "__main__":
    main()
