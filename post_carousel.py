#!/usr/bin/env python3
"""Instagramカルーセル投稿（Instagram API with Instagram Login / 標準ライブラリのみ）

使い方
  1) トークンを環境変数に入れる（入力は画面に表示されません。履歴にも残りません）
       read -s IG_TOKEN; export IG_TOKEN
  2) ドライラン（投稿はしない。URLと設定の確認だけ。トークン不要）
       python3 post_carousel.py --caption caption.txt URL1 URL2 URL3
  3) 実際に投稿する
       python3 post_carousel.py --caption caption.txt URL1 URL2 URL3 --publish

前提
  - 画像は JPEG のみ・公開URL（https）に置く
  - 1枚目の比率が全体の比率になる（4:5 = 1080x1350 を想定）
  - 投稿は「--publish」を付けたときだけ実行（SNS投稿は人が確認するポイント）

daily_post.py からは publish_carousel() を呼ぶ（失敗は PostError）。
  RetryLater は「まだ投稿されていない。次の実行でコンテナから作り直せばよい」失敗（再試行待ち）。

API呼び出しの回数（1投稿）: コンテナ作成3 + 状態確認 最大5×3 + カルーセル作成1 + 状態確認 最大5
  + 公開 最大3 + パーマリンク1 = 最少10回・最多28回。コンテナIDは保存せず、毎回作り直す。
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://graph.instagram.com/v25.0"
RATE_LIMIT_CODE = 4          # Application request limit reached（アプリ全体の呼び出し上限）
MEDIA_NOT_READY_CODE = 9007  # Media ID is not available（公開できる状態になっていない）
STATUS_WAITS = (10, 10, 15, 20, 30)  # 状態確認の前に待つ秒数。確認は最大5回（合計85秒）
PUBLISH_RETRY_WAITS = (30, 60)       # 公開が 9007 のとき、この間隔で最大2回やり直す
RATE_LIMIT_COOLDOWN_MIN = 60         # 上限に達したら、少なくともこの分数は投稿しない


class PostError(Exception):
    """投稿処理の失敗（メッセージにトークンは含めない）"""


class ApiError(PostError):
    """APIがエラーを返した（code は Instagram のエラーコード。読めなければ None）"""

    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


class RetryLater(PostError):
    """投稿されていないことが確かな失敗。次の実行で、コンテナから作り直してやり直す（再試行待ち）。
    cooldown_min: 0より大きければ、その分数のあいだ、どの行も投稿しない（上限はアプリ全体にかかるため）"""

    def __init__(self, message, cooldown_min=0):
        super().__init__(message)
        self.cooldown_min = cooldown_min


def error_code(body):
    try:
        return json.loads(body).get("error", {}).get("code")
    except (ValueError, AttributeError):
        return None


def call(method, path, token, params=None):
    url = f"{BASE}/{path}"
    data = None
    if method == "GET" and params:
        url += "?" + urllib.parse.urlencode(params)
    if method == "POST":
        data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Authorization": f"Bearer {token}"},  # トークンはURLに載せない
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        message = f"APIエラー {e.code}: {body[:600]}"
        code = error_code(body)
        if code == RATE_LIMIT_CODE:
            raise RetryLater(message, cooldown_min=RATE_LIMIT_COOLDOWN_MIN)
        raise ApiError(message, code)
    except urllib.error.URLError as e:
        raise PostError(f"通信エラー: {e.reason}")


def check_url(url):
    """公開URLが JPEG として取得できるかを事前確認する。"""
    if not url.startswith("https://"):
        raise PostError(f"https のURLを指定してください: {url}")
    if not url.lower().split("?")[0].endswith((".jpg", ".jpeg")):
        raise PostError(f"JPEG（.jpg / .jpeg）のURLだけ使えます: {url}")
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            ctype = r.headers.get("Content-Type", "")
            if "image/jpeg" not in ctype:
                raise PostError(f"Content-Type が image/jpeg ではありません（{ctype}）: {url}")
    except urllib.error.HTTPError as e:
        raise PostError(f"画像を取得できません（HTTP {e.code}）。公開設定を確認してください: {url}")
    except urllib.error.URLError as e:
        print(f"  [警告] 事前確認できませんでした（{e.reason}）: {url}")


def wait_finished(container_id, token):
    """status_code が FINISHED になるまで、間隔を空けて最大 len(STATUS_WAITS) 回だけ確認する。
    間に合わなければ、このコンテナは使わず、次の実行で作り直す。"""
    for wait in STATUS_WAITS:
        time.sleep(wait)
        st = call("GET", container_id, token, {"fields": "status_code"}).get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise PostError(f"コンテナが {st} になりました: {container_id}")
    raise RetryLater(f"コンテナの準備が {sum(STATUS_WAITS)} 秒で終わりませんでした: {container_id}")


def publish(container_id, token, user_id):
    """media_publish を呼ぶ。9007（まだ公開できない）のときだけ、間隔を空けてやり直す。
    9007 は「公開されていない」という応答なので、やり直しても二重投稿にはならない。"""
    for wait in (*PUBLISH_RETRY_WAITS, None):
        try:
            return call("POST", f"{user_id}/media_publish", token, {"creation_id": container_id})
        except RetryLater as e:
            # 公開の呼び出しで上限に達した。公開されたか確かめられないため、人が確認する（エラー扱い）
            raise PostError(f"{e}（公開の呼び出しで上限に達しました）") from e
        except ApiError as e:
            if e.code != MEDIA_NOT_READY_CODE and "Media ID is not available" not in str(e):
                raise
            if wait is None:
                raise RetryLater(f"公開できる状態になりませんでした: {e}") from e
            print(f"  公開できる状態ではありません。{wait}秒後にやり直します")
            time.sleep(wait)


def publish_carousel(urls, caption, token, user_id="me", before_publish=None):
    """カルーセルを投稿してパーマリンクを返す。

    before_publish: 公開（media_publish）を呼ぶ直前に実行される関数。
    これ以降の失敗は「投稿済みかもしれない」状態になるため、呼び出し側が区別に使う。
    """
    children = []
    for i, u in enumerate(urls, 1):
        r = call("POST", f"{user_id}/media", token, {"image_url": u, "is_carousel_item": "true"})
        children.append(r["id"])
        print(f"  画像{i} コンテナ作成: OK")
    for c in children:
        wait_finished(c, token)

    r = call("POST", f"{user_id}/media", token, {
        "media_type": "CAROUSEL", "children": ",".join(children), "caption": caption})
    parent = r["id"]
    wait_finished(parent, token)
    print("カルーセル作成: OK")

    if before_publish:
        before_publish()
    media_id = publish(parent, token, user_id)["id"]
    try:
        return call("GET", media_id, token, {"fields": "permalink"}).get("permalink", "(取得できませんでした)")
    except PostError:
        return "(投稿は完了。パーマリンクは取得できませんでした)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("urls", nargs="+", help="画像の公開URL（2〜10枚・投稿順）")
    ap.add_argument("--caption", required=True, help="キャプションのテキストファイル")
    ap.add_argument("--user-id", default=os.environ.get("IG_USER_ID", "me"))
    ap.add_argument("--publish", action="store_true", help="指定したときだけ実際に投稿する")
    a = ap.parse_args()

    token = os.environ.get("IG_TOKEN")
    if a.publish and not token:
        sys.exit("環境変数 IG_TOKEN がありません。先に: read -s IG_TOKEN; export IG_TOKEN")
    if not 2 <= len(a.urls) <= 10:
        sys.exit("カルーセルは 2〜10 枚です")
    caption = open(a.caption, encoding="utf-8").read().strip()

    try:
        print("画像URLを確認中...")
        for u in a.urls:
            check_url(u)

        print(f"\n--- 投稿内容 ---\n枚数: {len(a.urls)}\nキャプション({len(caption)}文字):\n{caption}\n")
        if not a.publish:
            print("ドライラン完了（投稿していません）。投稿するには --publish を付けて再実行してください。")
            return
        link = publish_carousel(a.urls, caption, token, a.user_id)
    except PostError as e:
        sys.exit(str(e))
    print(f"\n投稿しました: {link}")


if __name__ == "__main__":
    main()
