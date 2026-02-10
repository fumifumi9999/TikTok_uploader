"""
TikTok Content Posting API でローカルの MP4 をアップロードするスクリプト。

使い方:
  python uploader.py path/to/video.mp4
  または
  ACCESS_TOKEN=xxx python uploader.py path/to/video.mp4

環境変数:
  TIKTOK_ACCESS_TOKEN または ACCESS_TOKEN: ユーザーアクセストークン（video.upload スコープ必須）
"""

import argparse
import os
import sys

import requests

# チャンク制約: 5MB〜64MB（最終チャンクは最大128MB）
CHUNK_MIN_BYTES = 5 * 1024 * 1024   # 5 MB
CHUNK_MAX_BYTES = 64 * 1024 * 1024  # 64 MB
CHUNK_DEFAULT_BYTES = 10 * 1024 * 1024  # 10 MB
MAX_CHUNKS = 1000
INIT_API = "https://open.tiktokapis.com/v2/post/publish/inbox/video/init/"
DIRECT_POST_API = "https://open.tiktokapis.com/v2/post/publish/video/init/"



# .env ファイルから環境変数を読み込むために dotenv を使う
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv が無ければ何もしない（グレースフルデグレード）


def refresh_access_token() -> str | None:
    """refresh_token を使って新しい access_token を取得し .env に保存する。"""
    from dotenv import dotenv_values
    env = dotenv_values('.env')
    refresh_token = env.get("TIKTOK_REFRESH_TOKEN")
    client_key = env.get("TIKTOK_CLIENT_KEY")
    client_secret = env.get("TIKTOK_CLIENT_SECRET")
    if not refresh_token or not client_key or not client_secret:
        return None

    resp = requests.post(
        "https://open.tiktokapis.com/v2/oauth/token/",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=30,
    )
    data = resp.json()
    new_token = data.get("access_token")
    if not new_token:
        return None

    from auth import save_env_value
    save_env_value("TIKTOK_ACCESS_TOKEN", new_token)
    if "refresh_token" in data:
        save_env_value("TIKTOK_REFRESH_TOKEN", data["refresh_token"])
    print("トークンを自動更新しました。")
    return new_token


def get_access_token() -> str:
    from dotenv import dotenv_values
    env = dotenv_values('.env')
    token = env.get("TIKTOK_ACCESS_TOKEN") or os.environ.get("TIKTOK_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not token:
        print("エラー: TIKTOK_ACCESS_TOKEN または ACCESS_TOKEN を設定してください。", file=sys.stderr)
        sys.exit(1)
    return token.strip()


def calc_chunk_params(file_size: int) -> tuple[int, int]:
    """
    ファイルサイズから chunk_size と total_chunk_count を計算する。
    TikTok API仕様: total_chunk_count = floor(video_size / chunk_size)
    最終チャンクに端数が加算される（最大128MBまで許容）。
    """
    if file_size <= CHUNK_MAX_BYTES:
        return file_size, 1
    chunk_size = CHUNK_DEFAULT_BYTES  # 10 MB
    total_chunk_count = file_size // chunk_size  # floor除算（TikTok API仕様）
    return chunk_size, total_chunk_count


def init_upload(access_token: str, video_size: int, chunk_size: int, total_chunk_count: int) -> tuple[str, str]:
    """アップロード初期化。publish_id と upload_url を返す。"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    body = {
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        }
    }
    resp = requests.post(INIT_API, headers=headers, json=body, timeout=30)
    data = resp.json()

    err = data.get("error", {})
    if err.get("code") != "ok":
        msg = err.get("message", resp.text)
        raise RuntimeError(f"初期化失敗: {err.get('code', 'unknown')} - {msg}")

    info = data.get("data", {})
    publish_id = info.get("publish_id")
    upload_url = info.get("upload_url")
    if not publish_id or not upload_url:
        raise RuntimeError("レスポンスに publish_id または upload_url がありません")

    return publish_id, upload_url


def upload_chunk(upload_url: str, data: bytes, first_byte: int, last_byte: int, total_size: int) -> int:
    """
    1チャンクを PUT で送信。期待される HTTP ステータスは 206（継続）または 201（完了）。
    返り値はレスポンスの Content-Range から得たアップロード済みバイト数（last_byte + 1）。
    """
    headers = {
        "Content-Type": "video/mp4",
        "Content-Length": str(len(data)),
        "Content-Range": f"bytes {first_byte}-{last_byte}/{total_size}",
    }
    resp = requests.put(upload_url, headers=headers, data=data, timeout=120)
    if resp.status_code not in (206, 201):
        raise RuntimeError(f"アップロード失敗: HTTP {resp.status_code} - {resp.text[:500]}")

    # Content-Range: bytes 0-{UPLOADED_BYTES}/{TOTAL}
    cr = resp.headers.get("Content-Range", "")
    if cr.startswith("bytes "):
        part = cr[6:].split("/")[0]  # "0-12345"
        if "-" in part:
            uploaded_end = int(part.split("-")[1]) + 1
            return uploaded_end
    return last_byte + 1


def upload_file(access_token: str, path: str) -> str:
    """
    ローカル MP4 を TikTok Content Posting API でアップロードする。
    戻り値: publish_id（ステータス確認用）。
    """
    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    file_size = os.path.getsize(path)
    if file_size <= 0:
        raise ValueError("空のファイルはアップロードできません")

    chunk_size, total_chunk_count = calc_chunk_params(file_size)
    print(f"ファイル: {path} ({file_size:,} bytes)")
    print(f"チャンク: {chunk_size:,} bytes × {total_chunk_count} リクエスト")

    try:
        publish_id, upload_url = init_upload(access_token, file_size, chunk_size, total_chunk_count)
    except RuntimeError as e:
        if "access_token" in str(e).lower() or "invalid" in str(e).lower() or "expired" in str(e).lower():
            print("トークン期限切れの可能性があります。リフレッシュを試みます...")
            new_token = refresh_access_token()
            if new_token:
                access_token = new_token
                publish_id, upload_url = init_upload(access_token, file_size, chunk_size, total_chunk_count)
            else:
                raise RuntimeError("トークンの自動更新に失敗しました。uv run auth.py で再認証してください。") from e
        else:
            raise
    print(f"初期化完了 publish_id={publish_id}")

    with open(path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            if i == total_chunk_count - 1:
                chunk_data = f.read()  # 最終チャンク: 残り全バイト
            else:
                chunk_data = f.read(chunk_size)
            end = start + len(chunk_data) - 1
            upload_chunk(upload_url, chunk_data, start, end, file_size)
            print(f"  チャンク {i + 1}/{total_chunk_count} 送信済み (bytes {start}-{end})")

    print("アップロード完了。TikTok のインボックスで編集・投稿を完了してください。")
    return publish_id


def init_direct_post(access_token: str, video_size: int, chunk_size: int, total_chunk_count: int,
                     post_info: dict) -> tuple[str, str]:
    """Direct Post 初期化。publish_id と upload_url を返す。"""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    body = {
        "post_info": post_info,
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": video_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunk_count,
        },
    }
    resp = requests.post(DIRECT_POST_API, headers=headers, json=body, timeout=30)
    data = resp.json()

    err = data.get("error", {})
    if err.get("code") != "ok":
        msg = err.get("message", resp.text)
        raise RuntimeError(f"初期化失敗: {err.get('code', 'unknown')} - {msg}")

    info = data.get("data", {})
    publish_id = info.get("publish_id")
    upload_url = info.get("upload_url")
    if not publish_id or not upload_url:
        raise RuntimeError("レスポンスに publish_id または upload_url がありません")

    return publish_id, upload_url


def go_public(access_token: str, path: str) -> str:
    """ローカル MP4 を TikTok に直接公開する。戻り値: publish_id。"""
    # --- 動画パラメータ（ここを編集して投稿設定を変更） ---
    title = "千葉に住んでいる宇宙人から来た存在 #shorts #雑学"                                    # 動画のタイトル/説明文
    privacy_level = "SELF_ONLY"                    # 公開範囲: PUBLIC_TO_EVERYONE / FOLLOWER_OF_CREATOR / MUTUAL_FOLLOW_FRIENDS / SELF_ONLY（未審査アプリはSELF_ONLYのみ）
    disable_duet = False                           # デュエットを無効にする
    disable_stitch = False                         # スティッチを無効にする
    disable_comment = False                        # コメントを無効にする
    video_cover_timestamp_ms = 1000                # カバー画像の位置（ミリ秒）
    brand_content_toggle = False                   # ブランドコンテンツとして表示
    brand_organic_toggle = False                   # ブランドオーガニックとして表示
    # -----------------------------------------------

    post_info = {
        "title": title,
        "privacy_level": privacy_level,
        "disable_duet": disable_duet,
        "disable_stitch": disable_stitch,
        "disable_comment": disable_comment,
        "video_cover_timestamp_ms": video_cover_timestamp_ms,
        "brand_content_toggle": brand_content_toggle,
        "brand_organic_toggle": brand_organic_toggle,
    }

    path = os.path.abspath(path)
    if not os.path.isfile(path):
        raise FileNotFoundError(f"ファイルが見つかりません: {path}")

    file_size = os.path.getsize(path)
    if file_size <= 0:
        raise ValueError("空のファイルはアップロードできません")

    chunk_size, total_chunk_count = calc_chunk_params(file_size)
    print(f"ファイル: {path} ({file_size:,} bytes)")
    print(f"チャンク: {chunk_size:,} bytes × {total_chunk_count} リクエスト")
    print(f"モード: 直接公開 (Direct Post)")

    try:
        publish_id, upload_url = init_direct_post(access_token, file_size, chunk_size, total_chunk_count, post_info)
    except RuntimeError as e:
        if "access_token" in str(e).lower() or "invalid" in str(e).lower() or "expired" in str(e).lower():
            print("トークン期限切れの可能性があります。リフレッシュを試みます...")
            new_token = refresh_access_token()
            if new_token:
                access_token = new_token
                publish_id, upload_url = init_direct_post(access_token, file_size, chunk_size, total_chunk_count, post_info)
            else:
                raise RuntimeError("トークンの自動更新に失敗しました。uv run auth.py で再認証してください。") from e
        else:
            raise
    print(f"初期化完了 publish_id={publish_id}")

    with open(path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            if i == total_chunk_count - 1:
                chunk_data = f.read()  # 最終チャンク: 残り全バイト
            else:
                chunk_data = f.read(chunk_size)
            end = start + len(chunk_data) - 1
            upload_chunk(upload_url, chunk_data, start, end, file_size)
            print(f"  チャンク {i + 1}/{total_chunk_count} 送信済み (bytes {start}-{end})")

    print("直接公開完了。TikTok に投稿されました。")
    return publish_id


def main_uploading_from_smartphone() -> None:
    parser = argparse.ArgumentParser(description="TikTok Content Posting API で MP4 をアップロード（インボックス）")
    parser.add_argument("video", help="アップロードする MP4 ファイルのパス")
    parser.add_argument("--token", "-t", help="アクセストークン（未指定時は環境変数を使用）")
    args = parser.parse_args()

    access_token = (args.token or "").strip() or get_access_token()
    try:
        publish_id = upload_file(access_token, args.video)
        print(f"publish_id（ステータス確認用）: {publish_id}")
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok Content Posting API で MP4 を直接公開")
    parser.add_argument("video", help="アップロードする MP4 ファイルのパス")
    parser.add_argument("--token", "-t", help="アクセストークン（未指定時は環境変数を使用）")
    args = parser.parse_args()

    access_token = (args.token or "").strip() or get_access_token()
    try:
        publish_id = go_public(access_token, args.video)
        print(f"publish_id（ステータス確認用）: {publish_id}")
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()