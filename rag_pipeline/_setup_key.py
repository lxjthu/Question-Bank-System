"""
API Key 配置对话框 —— 由「一键启动_AI出题.bat」调用。
退出码：0 = 已保存或跳过（可以继续），1 = 用户取消。
"""
import sys
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

ENV_FILE = Path(__file__).parent.parent / ".env"
PLACEHOLDER = "sk-your-key-here"


def read_current_key() -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("DEEPSEEK_API_KEY="):
            return line.split("=", 1)[1].strip()
    return ""


def write_key(key: str) -> None:
    ENV_FILE.write_text(
        f"# DeepSeek API Key\n"
        f"# 申请地址: https://platform.deepseek.com/\n"
        f"DEEPSEEK_API_KEY={key}\n",
        encoding="utf-8",
    )


class KeyDialog(tk.Tk):
    def __init__(self, current_key: str):
        super().__init__()
        self.result: str | None = None
        self._build_ui(current_key)

    def _build_ui(self, current_key: str) -> None:
        self.title("AI题库生成系统 - 配置 API Key")
        self.resizable(False, False)
        self.configure(bg="#f0f4f8")

        # 居中
        w, h = 500, 240
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        # 标题区
        tk.Label(
            self, text="DeepSeek API Key 配置",
            font=("微软雅黑", 14, "bold"), bg="#f0f4f8", fg="#1a1a2e",
        ).pack(pady=(22, 2))
        tk.Label(
            self,
            text="申请地址：https://platform.deepseek.com/",
            font=("微软雅黑", 9), bg="#f0f4f8", fg="#666",
        ).pack()

        # 输入框行
        row = tk.Frame(self, bg="#f0f4f8")
        row.pack(pady=16, padx=36, fill="x")

        init_val = (
            current_key
            if current_key and current_key != PLACEHOLDER
            else "sk-"
        )
        self._key_var = tk.StringVar(value=init_val)
        self._masked = True

        self._entry = tk.Entry(
            row, textvariable=self._key_var,
            show="*", font=("Consolas", 11),
            relief="solid", bd=1,
        )
        self._entry.pack(side="left", fill="x", expand=True, ipady=5)
        self._entry.icursor("end")

        self._toggle_btn = tk.Button(
            row, text="显示", width=5, font=("微软雅黑", 9),
            relief="flat", bg="#dde3ea", cursor="hand2",
            command=self._toggle_mask,
        )
        self._toggle_btn.pack(side="left", padx=(8, 0), ipady=5)

        # 按钮行
        btn_row = tk.Frame(self, bg="#f0f4f8")
        btn_row.pack(pady=6)

        tk.Button(
            btn_row, text="  确  定  ", font=("微软雅黑", 10),
            bg="#1a73e8", fg="white", relief="flat", cursor="hand2",
            command=self._on_ok,
        ).pack(side="left", padx=10, ipady=5)

        tk.Button(
            btn_row, text="  取  消  ", font=("微软雅黑", 10),
            bg="#dde3ea", fg="#333", relief="flat", cursor="hand2",
            command=self._on_cancel,
        ).pack(side="left", padx=10, ipady=5)

        self.bind("<Return>", lambda _e: self._on_ok())
        self.bind("<Escape>", lambda _e: self._on_cancel())
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._entry.focus_set()

    def _toggle_mask(self) -> None:
        self._masked = not self._masked
        self._entry.config(show="*" if self._masked else "")
        self._toggle_btn.config(text="显示" if self._masked else "隐藏")

    def _on_ok(self) -> None:
        key = self._key_var.get().strip()
        if not key or key in ("sk-", PLACEHOLDER):
            messagebox.showwarning("提示", "请输入有效的 API Key", parent=self)
            return
        if not key.startswith("sk-"):
            if not messagebox.askyesno(
                "确认",
                f"输入的 Key 不以「sk-」开头，确认保存？\n\n{key[:20]}...",
                parent=self,
            ):
                return
        self.result = key
        self.destroy()

    def _on_cancel(self) -> None:
        self.result = None
        self.destroy()


def main() -> None:
    current_key = read_current_key()

    # 已有有效 Key → 询问是否重新输入
    if current_key and current_key != PLACEHOLDER:
        root = tk.Tk()
        root.withdraw()
        want_change = messagebox.askyesno(
            "AI题库生成系统",
            f"已检测到已保存的 API Key：\n\n{current_key[:8]}{'*' * 20}\n\n"
            f"是否重新输入？\n选「否」将直接使用已保存的 Key 启动。",
        )
        root.destroy()
        if not want_change:
            sys.exit(0)  # 使用现有 Key，继续启动

    # 弹出输入对话框
    dialog = KeyDialog(current_key)
    dialog.mainloop()

    if dialog.result is None:
        sys.exit(1)  # 用户取消

    write_key(dialog.result)

    # 保存成功提示
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("保存成功", "API Key 已保存，即将启动系统...", parent=root)
    root.destroy()

    sys.exit(0)


if __name__ == "__main__":
    main()
