"""
TikTok OAuth 2.0 認可コードフローでアクセストークンを取得し .env に保存するスクリプト。

使い方:
  uv run auth.py
"""

import http.server
import urllib.parse
import webbrowser
import re

import requests
from dotenv import dotenv_values

ENV_FILE = ".env"
PORT = 3000
REDIRECT_URI = "https://treasurable-joyce-uncrossable.ngrok-free.dev"


def load_client_credentials() -> tuple[str, str]:
    env = dotenv_values(ENV_FILE)
    client_key = env.get("TIKTOK_CLIENT_KEY", "")
    client_secret = env.get("TIKTOK_CLIENT_SECRET", "")
    if not client_key or not client_secret:
        raise RuntimeError(f"{ENV_FILE} に TIKTOK_CLIENT_KEY / TIKTOK_CLIENT_SECRET を設定してください")
    return client_key, client_secret


def exchange_code(client_key: str, client_secret: str, code: str) -> dict:
    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    return resp.json()


def save_env_value(key: str, value: str) -> None:
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        content = f.read()

    pattern = rf"^#?\s*{key}=.*$"
    replacement = f"{key}={value}"
    if re.search(pattern, content, re.MULTILINE):
        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
    else:
        content = content.rstrip("\n") + f"\n{replacement}\n"

    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def save_tokens(token_data: dict) -> None:
    save_env_value("TIKTOK_ACCESS_TOKEN", token_data["access_token"])
    if "refresh_token" in token_data:
        save_env_value("TIKTOK_REFRESH_TOKEN", token_data["refresh_token"])


def main() -> None:
    client_key, client_secret = load_client_credentials()

    auth_url = (
        "https://www.tiktok.com/v2/auth/authorize/"
        f"?client_key={client_key}"
        "&scope=user.info.basic,video.upload,video.publish"
        "&response_type=code"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI, safe='')}"
    )

    print(f"ブラウザで認可ページを開きます...")
    print(f"URL: {auth_url}\n")
    webbrowser.open(auth_url)

    print(f"localhost:{PORT} でコールバックを待機中...\n")

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            qs = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(qs)

            if "code" in params:
                code = params["code"][0]
                print(f"認可コード取得: {code[:10]}...")

                token_data = exchange_code(client_key, client_secret, code)
                access_token = token_data.get("access_token")

                if access_token:
                    save_tokens(token_data)
                    result["ok"] = True
                    msg = "アクセストークンとリフレッシュトークンを .env に保存しました。このページを閉じてください。"
                    print(f"\n{msg}")
                else:
                    result["ok"] = False
                    error = token_data.get("error", "unknown")
                    desc = token_data.get("error_description", str(token_data))
                    msg = f"トークン取得失敗: {error} - {desc}"
                    print(f"\n{msg}")
            elif "error" in params:
                result["ok"] = False
                msg = f"認可エラー: {params.get('error', ['unknown'])[0]} - {params.get('error_description', [''])[0]}"
                print(f"\n{msg}")
            else:
                msg = "不明なリクエスト"
                print(f"\n{msg}")

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"<html><body><h2>{msg}</h2></body></html>".encode())

        def log_message(self, format, *args):
            pass  # ログ抑制

    server = http.server.HTTPServer(("", PORT), Handler)
    server.handle_request()  # 1リクエストだけ処理して終了

    if result.get("ok"):
        print("完了。uv run uploader.py 1.mp4 でアップロードできます。")
    else:
        print("トークン取得に失敗しました。")


if __name__ == "__main__":
    main()