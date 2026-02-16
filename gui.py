"""TikTok アップローダー GUI（Tkinter）"""

import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from uploader import upload_file, go_public


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("TikTok Uploader")
        self.geometry("480x260")
        self.resizable(False, False)

        self.video_path = tk.StringVar()

        # ファイル選択
        frame_file = tk.Frame(self)
        frame_file.pack(fill="x", padx=16, pady=(20, 8))

        tk.Label(frame_file, text="動画ファイル:").pack(side="left")
        tk.Entry(frame_file, textvariable=self.video_path, width=36).pack(side="left", padx=(8, 4))
        tk.Button(frame_file, text="参照...", command=self._browse).pack(side="left")

        # アップロードモード選択
        self.mode = tk.StringVar(value="inbox")
        frame_mode = tk.Frame(self)
        frame_mode.pack(fill="x", padx=16, pady=4)
        tk.Radiobutton(frame_mode, text="インボックス送信", variable=self.mode, value="inbox").pack(side="left")
        tk.Radiobutton(frame_mode, text="直接公開", variable=self.mode, value="direct").pack(side="left", padx=(16, 0))

        # アップロードボタン
        self.btn_upload = tk.Button(self, text="アップロード", width=20, height=2, command=self._on_upload)
        self.btn_upload.pack(pady=16)

        # ステータス表示
        self.status = tk.StringVar(value="動画を選択してください")
        tk.Label(self, textvariable=self.status, fg="gray").pack()

    def _browse(self):
        path = filedialog.askopenfilename(filetypes=[("MP4 ファイル", "*.mp4"), ("すべて", "*.*")])
        if path:
            self.video_path.set(path)
            self.status.set("準備完了")

    def _on_upload(self):
        path = self.video_path.get().strip()
        if not path:
            messagebox.showwarning("警告", "動画ファイルを選択してください。")
            return

        self.btn_upload.config(state="disabled")
        self.status.set("アップロード中...")
        threading.Thread(target=self._do_upload, args=(path,), daemon=True).start()

    def _do_upload(self, path: str):
        try:
            if self.mode.get() == "direct":
                publish_id = go_public(path)
            else:
                publish_id = upload_file(path)
            self.after(0, self._on_success, publish_id)
        except Exception as e:
            self.after(0, self._on_error, str(e))

    def _on_success(self, publish_id: str):
        self.btn_upload.config(state="normal")
        self.status.set(f"完了 (publish_id: {publish_id})")
        messagebox.showinfo("完了", f"アップロード完了\npublish_id: {publish_id}")

    def _on_error(self, msg: str):
        self.btn_upload.config(state="normal")
        self.status.set("エラーが発生しました")
        messagebox.showerror("エラー", msg)


if __name__ == "__main__":
    App().mainloop()