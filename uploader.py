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


def get_access_token() -> str:
    token = os.environ.get("TIKTOK_ACCESS_TOKEN") or os.environ.get("ACCESS_TOKEN")
    if not token:
        print("エラー: TIKTOK_ACCESS_TOKEN または ACCESS_TOKEN を設定してください。", file=sys.stderr)
        sys.exit(1)
    return token.strip()


def calc_chunk_params(file_size: int) -> tuple[int, int]:
    """
    ファイルサイズから chunk_size と total_chunk_count を計算する。
    - 5MB未満: 1チャンクで全体送信
    - 5MB以上: 10MBチャンク（最終チャンクは端数可、最大128MB）
    """
    if file_size < CHUNK_MIN_BYTES:
        return file_size, 1
    chunk_size = min(CHUNK_DEFAULT_BYTES, CHUNK_MAX_BYTES)
    total_chunk_count = (file_size + chunk_size - 1) // chunk_size
    if total_chunk_count > MAX_CHUNKS:
        # チャンク数が1000を超える場合は chunk_size を大きくする
        chunk_size = (file_size + MAX_CHUNKS - 1) // MAX_CHUNKS
        chunk_size = max(chunk_size, CHUNK_MIN_BYTES)
        chunk_size = min(chunk_size, CHUNK_MAX_BYTES)
        total_chunk_count = (file_size + chunk_size - 1) // chunk_size
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

    publish_id, upload_url = init_upload(access_token, file_size, chunk_size, total_chunk_count)
    print(f"初期化完了 publish_id={publish_id}")

    with open(path, "rb") as f:
        for i in range(total_chunk_count):
            start = i * chunk_size
            end = min(start + chunk_size, file_size) - 1
            chunk_data = f.read(chunk_size)
            if len(chunk_data) == 0:
                break
            upload_chunk(upload_url, chunk_data, start, end, file_size)
            print(f"  チャンク {i + 1}/{total_chunk_count} 送信済み (bytes {start}-{end})")

    print("アップロード完了。TikTok のインボックスで編集・投稿を完了してください。")
    return publish_id


def main() -> None:
    parser = argparse.ArgumentParser(description="TikTok Content Posting API で MP4 をアップロード")
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


if __name__ == "__main__":
    main()
