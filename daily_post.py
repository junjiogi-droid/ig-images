#!/usr/bin/env python3
"""日次投稿：承認済みの1行を、投稿予定日時の順に1件だけ投稿する（GitHub Actions から1日2回）。

流れ
  1. シートの受け口(list_approved)から「承認済み・未投稿・予定時刻が来ている」先頭1行を取得
     → 無ければ何も投稿せず正常終了
  2. 投稿前に「投稿中」へ更新（成功した実行だけが続行。二重投稿の防止）
  3. PNG→JPEG(1080x1350, quality 95) → オーダーメモ画像 → AI生成メタデータ付与
  4. 一時ブランチ(画像3枚だけ)へ push → Raw URL で配信を確認
  5. Instagram へ投稿 →「投稿済」へ更新
  6. 一時ブランチを削除（成功・失敗にかかわらず）

失敗時は「エラー」にして止まる。「投稿中」「エラー」の行は自動では再投稿されない。

使い方
  python3 daily_post.py             # ドライラン（取得して内容を表示するだけ。状態も変えない）
  python3 daily_post.py --publish   # 実際に投稿する

環境変数（GitHub Secrets から渡す。値は表示しない）
  GAS_URL, GAS_SECRET … シートの受け口のURLと合言葉
  IG_TOKEN            … Instagram のアクセストークン（--publish のときだけ必須）
  GITHUB_REPOSITORY   … owner/repo（Actions が自動で設定）
  IG_USER_ID          … 省略時 me
"""
import argparse
import base64
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import add_ai_metadata
import make_post
import post_carousel
from post_carousel import PostError

MAX_TIPS = 5
MAX_TIP_LEN = 40
MARKER = b"trainedAlgorithmicMedia"


# ---------- シートの受け口 ----------
def gas(url, secret, payload, retries=2):
    body = json.dumps({**payload, "secret": secret}).encode()
    last = None
    for i in range(retries + 1):
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "text/plain;charset=utf-8"})
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                return json.load(r)
        except (urllib.error.URLError, json.JSONDecodeError, TimeoutError) as e:
            last = e
            time.sleep(3 * (i + 1))
    raise PostError(f"シートの受け口に接続できません: {type(last).__name__}")


def set_status(url, secret, front_id, status, note="", claim=False):
    """状態更新。完了・エラーへの更新は、すでにその状態なら成功扱い（再試行しても安全）。
    「投稿中」への更新（claim）は、すでに投稿中なら別の実行が先に取ったということなので失敗扱い。"""
    res = gas(url, secret, {"action": "update_status", "front_id": front_id,
                            "status": status, "note": note})
    if not claim and res.get("error") == "conflict" and res.get("current") == status:
        return {"ok": True, "status": status}
    return res


# ---------- 内容の検証 ----------
def validate(row):
    caption = (row.get("caption") or "").strip()
    tips = [t.strip() for t in (row.get("memo") or "").splitlines() if t.strip()]
    if not caption:
        raise PostError("キャプションが空です（シートに入力してください）")
    if "AI生成" not in caption:
        raise PostError("キャプションに「AI生成」の表記がありません")
    if len(caption) > 2200:
        raise PostError("キャプションが2200文字を超えています")
    if not tips:
        raise PostError("オーダーメモが空です（1行1項目で入力してください）")
    if len(tips) > MAX_TIPS or any(len(t) > MAX_TIP_LEN for t in tips):
        raise PostError(f"オーダーメモは{MAX_TIPS}項目以内・各{MAX_TIP_LEN}文字以内にしてください")
    return caption, tips


# ---------- 画像 ----------
def build_images(row, tips, workdir):
    """PNG→JPEG(1080x1350)、オーダーメモ画像、AIメタデータ付与。出力先のパス3つを投稿順に返す。"""
    raw = workdir / "raw"
    out = workdir / "out"
    raw.mkdir()
    out.mkdir()
    (raw / "front.png").write_bytes(base64.b64decode(row["front_b64"]))
    (raw / "side.png").write_bytes(base64.b64decode(row["side_b64"]))

    make_post.fit(raw / "front.png").save(raw / "1_front.jpg", quality=95)
    make_post.fit(raw / "side.png").save(raw / "2_side.jpg", quality=95)
    make_post.info_card({"style": row["style"], "color": row["color"]}, tips, raw / "3_info.jpg")

    paths = []
    for name in ("1_front.jpg", "2_side.jpg", "3_info.jpg"):
        add_ai_metadata.inject(raw / name, out / name)
        data = (out / name).read_bytes()
        if MARKER not in data:
            raise PostError(f"AIメタデータの埋め込みに失敗しました: {name}")
        paths.append(out / name)

    from PIL import Image
    for p in paths:
        if Image.open(p).size != (make_post.W, make_post.H):
            raise PostError(f"画像サイズが {make_post.W}x{make_post.H} ではありません: {p.name}")
    return paths


# ---------- 一時ブランチへの配置 ----------
def git(*args, stdin=None):
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "ig-bot", "GIT_AUTHOR_EMAIL": "ig-bot@users.noreply.github.com",
           "GIT_COMMITTER_NAME": "ig-bot", "GIT_COMMITTER_EMAIL": "ig-bot@users.noreply.github.com"}
    p = subprocess.run(["git", *args], input=stdin, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise PostError(f"git {args[0]} に失敗しました: {p.stderr.strip()[:300]}")
    return p.stdout.strip()


def push_temp_branch(paths, branch):
    """画像だけを含む1コミットを作り、一時ブランチとして push する（作業ツリーは触らない）。"""
    entries = []
    for p in paths:
        sha = git("hash-object", "-w", str(p))
        entries.append(f"100644 blob {sha}\t{p.name}")
    tree = git("mktree", stdin="\n".join(entries) + "\n")
    commit = git("commit-tree", tree, "-m", f"temporary images for {branch}")
    git("push", "origin", f"{commit}:refs/heads/{branch}")


def delete_temp_branch(branch):
    try:
        git("push", "origin", "--delete", branch)
        print(f"一時ブランチを削除しました: {branch}")
    except PostError as e:
        print(f"[警告] 一時ブランチの削除に失敗しました。手動で削除してください: {branch} / {e}")


def wait_public(urls, timeout=120):
    """Raw URL が JPEG で取得でき、AIメタデータが残っていることを確認する。"""
    deadline = time.time() + timeout
    for u in urls:
        while True:
            try:
                post_carousel.check_url(u)
                with urllib.request.urlopen(u, timeout=60) as r:
                    if MARKER not in r.read():
                        raise PostError(f"配信された画像にAIメタデータがありません: {u}")
                break
            except PostError as e:
                if "メタデータ" in str(e) or time.time() > deadline:
                    raise
                time.sleep(5)


# ---------- 本体 ----------
def run(row, args, gas_url, gas_secret, token):
    front_id = row["front_id"]
    repo = os.environ.get("GITHUB_REPOSITORY")
    if not repo:
        raise PostError("GITHUB_REPOSITORY がありません")

    # 投稿前に「投稿中」へ更新する。成功した実行だけが続行する（二重投稿の防止）
    try:
        claim = set_status(gas_url, gas_secret, front_id, "投稿中", "自動投稿を開始", claim=True)
    except PostError as e:
        print(f"「投稿中」への更新に失敗したため投稿しません: {e}")
        return 1
    if not claim.get("ok"):
        print(f"この行は他で処理中、または対象外です（{claim.get('error')}）。何もしません。")
        return 0

    branch = f"tmp-{time.strftime('%Y%m%d%H%M%S')}-{front_id[:6]}"
    branched = False
    state = {"publishing": False}
    try:
        caption, tips = validate(row)
        with tempfile.TemporaryDirectory() as td:
            paths = build_images(row, tips, pathlib.Path(td))
            push_temp_branch(paths, branch)
            branched = True
            urls = [f"https://raw.githubusercontent.com/{repo}/{branch}/{p.name}" for p in paths]
            wait_public(urls)
            link = post_carousel.publish_carousel(
                urls, caption, token, args.user_id,
                before_publish=lambda: state.update(publishing=True))
    except Exception as e:  # noqa: BLE001 失敗は必ず「エラー」にして止める
        note = f"失敗: {e}"
        if state["publishing"]:
            note += "（公開処理中の失敗。Instagramに投稿されていないか確認してください）"
        print(note)
        try:
            set_status(gas_url, gas_secret, front_id, "エラー", note[:400])
        except PostError:
            print("[警告] 「エラー」への更新もできませんでした。行は「投稿中」のまま残ります。")
        return 1
    finally:
        if branched:
            delete_temp_branch(branch)

    print(f"投稿しました: {link}")
    for _ in range(3):
        res = set_status(gas_url, gas_secret, front_id, "投稿済", link)
        if res.get("ok"):
            return 0
        time.sleep(5)
    print("[重要] 投稿は成功しましたが「投稿済」に更新できませんでした。行は「投稿中」のままです"
          "（自動では再投稿されません）。シートを手で更新してください。")
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--publish", action="store_true", help="指定したときだけ実際に投稿する")
    ap.add_argument("--user-id", default=os.environ.get("IG_USER_ID", "me"))
    args = ap.parse_args()

    gas_url, gas_secret = os.environ.get("GAS_URL"), os.environ.get("GAS_SECRET")
    if not gas_url or not gas_secret:
        sys.exit("GAS_URL / GAS_SECRET が設定されていません")
    token = os.environ.get("IG_TOKEN")
    if args.publish and not token:
        sys.exit("IG_TOKEN が設定されていません")

    try:
        res = gas(gas_url, gas_secret, {"action": "list_approved", "limit": 1,
                                        "include_images": args.publish})
    except PostError as e:
        sys.exit(str(e))
    if not res.get("ok"):
        sys.exit(f"シートの受け口がエラーを返しました: {res.get('error')}")
    for s in res.get("skipped", []):
        print(f"[スキップ] {s.get('front_id', '')[:8]}…: {s.get('reason')}")

    rows = res.get("rows", [])
    if not rows:
        print("承認済みの未投稿行がありません。何も投稿しません。")
        return 0
    row = rows[0]
    print(f"対象: {row['date']} {row['style']} / {row['color']} / {row['outfit']}"
          f"（予定: {row.get('scheduled') or '未設定'}）")

    if not args.publish:
        try:
            caption, tips = validate(row)
            print(f"内容チェック: OK（キャプション{len(caption)}文字・メモ{len(tips)}項目）")
        except PostError as e:
            print(f"内容チェック: NG … {e}")
        print("ドライラン完了（投稿も状態の更新もしていません）。")
        return 0
    return run(row, args, gas_url, gas_secret, token)


if __name__ == "__main__":
    sys.exit(main())
