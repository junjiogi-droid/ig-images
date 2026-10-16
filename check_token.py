#!/usr/bin/env python3
"""Instagram トークンの見張り（毎週 GitHub Actions から実行。投稿はしない）

確認すること
  1. トークンが今も使えるか（読み取りだけの API を1回呼ぶ）
  2. 最後に更新した日（変数 TOKEN_REFRESHED_ON）から、期限（60日）まで何日残っているか

失敗（終了コード1）にする条件 → GitHub から失敗の通知メールが届く
  - トークンが使えない
  - 変数 TOKEN_REFRESHED_ON が無い／日付として読めない
  - 残り日数が WARN_DAYS（14日）以下、または期限切れ

環境変数: IG_TOKEN（Secrets）, TOKEN_REFRESHED_ON（変数, 例 2026-10-16）
トークンは画面にもログにも出さない。
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.request

LIFETIME_DAYS = 60   # 長期トークンの有効期間（Meta公式ドキュメント）
WARN_DAYS = 14       # 期限のこの日数前から警告（失敗）にする
API = os.environ.get("IG_API_BASE", "https://graph.instagram.com/v25.0")
JST = datetime.timezone(datetime.timedelta(hours=9))


def check_alive(token):
    req = urllib.request.Request(f"{API}/me?fields=username",
                                 headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace").replace(token, "***")
        return f"トークンが使えません（HTTP {e.code}）: {body[:200]}"
    except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
        return f"確認できませんでした（{type(e).__name__}）。時間をおいて再実行してください"
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", help="テスト用: 今日の日付（YYYY-MM-DD）")
    a = ap.parse_args()

    token = os.environ.get("IG_TOKEN")
    if not token:
        sys.exit("IG_TOKEN が設定されていません（Secrets を確認してください）")

    problems = []
    err = check_alive(token)
    if err:
        problems.append(err)

    today = datetime.date.fromisoformat(a.today) if a.today else datetime.datetime.now(JST).date()
    raw = (os.environ.get("TOKEN_REFRESHED_ON") or "").strip()
    try:
        refreshed = datetime.date.fromisoformat(raw)
    except ValueError:
        problems.append("変数 TOKEN_REFRESHED_ON が未設定、または日付（YYYY-MM-DD）として読めません")
        refreshed = None

    if refreshed:
        remaining = LIFETIME_DAYS - (today - refreshed).days
        if remaining <= 0:
            problems.append(f"トークンの期限（更新から{LIFETIME_DAYS}日）を過ぎています。再ログインが必要な可能性があります")
        elif remaining <= WARN_DAYS:
            problems.append(f"トークンの期限まであと {remaining} 日です。TOKEN_UPDATE.md の手順で更新してください")
        else:
            print(f"期限まであと {remaining} 日です（最終更新 {refreshed}）。")

    if not err:
        print("トークンは有効です。")
    if problems:
        for p in problems:
            print(f"::error::{p}")
        sys.exit(1)


if __name__ == "__main__":
    main()
