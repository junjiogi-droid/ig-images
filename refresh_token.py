#!/usr/bin/env python3
"""Instagram 長期トークンの更新（公式: GET https://graph.instagram.com/refresh_access_token）

- トークンは環境変数 IG_TOKEN から読む。画面にもログにも出さない
- 画面に出すのは「あと何日有効か」と「トークンの文字列が変わったか」だけ
- 新しい文字列が発行された場合は、失われないよう、クリップボード(pbcopy)へ自動でコピーする
  （画面には表示しない。パスワード管理ツールと GitHub の Secrets に貼り替えること）
- 更新できる条件: 発行から24時間以上で、期限が切れていないこと（有効期間は更新から60日）

使い方（自分のターミナルで）
  read -s IG_TOKEN; export IG_TOKEN     # トークンを貼り付けて Enter（画面には出ません）
  python3 refresh_token.py
  unset IG_TOKEN
"""
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

URL = os.environ.get("IG_REFRESH_URL", "https://graph.instagram.com/refresh_access_token")


def main():
    token = os.environ.get("IG_TOKEN")
    if not token:
        sys.exit("環境変数 IG_TOKEN がありません。先に: read -s IG_TOKEN; export IG_TOKEN")
    if not shutil.which("pbcopy"):
        sys.exit("pbcopy が見つかりません。新しいトークンを安全に受け取れないため、更新を中止しました。")

    query = urllib.parse.urlencode({"grant_type": "ig_refresh_token", "access_token": token})
    try:
        with urllib.request.urlopen(f"{URL}?{query}", timeout=60) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace").replace(token, "***")
        sys.exit(f"更新に失敗しました（HTTP {e.code}）: {body[:300]}")
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        sys.exit(f"更新に失敗しました: {type(e).__name__}")

    new = data.get("access_token")
    expires = data.get("expires_in")
    if not new or not isinstance(expires, (int, float)):
        sys.exit("想定外の応答です（access_token または expires_in がありません）。")

    days = round(expires / 86400)
    print(f"更新に成功しました。あと約 {days} 日有効です。")
    if new == token:
        print("トークンの文字列: 変わっていません（有効期限だけが延びました）。Secrets の貼り替えは不要です。")
    else:
        subprocess.run(["pbcopy"], input=new.encode(), check=True)
        print("トークンの文字列: 【新しくなりました】新しいトークンをクリップボードにコピーしました（画面には表示していません）。")
        print("  → いますぐパスワード管理ツールに貼り付けて保存し、GitHub の Secrets（IG_TOKEN）も貼り替えてください。")


if __name__ == "__main__":
    main()
