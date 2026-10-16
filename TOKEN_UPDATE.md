# Instagram トークンの更新手順（月1回・約30日おき）

1. ターミナルで `cd ~/Downloads/ig-hair-pipeline && read -s IG_TOKEN; export IG_TOKEN` を実行し、パスワード管理ツールの現在のトークンを貼って Enter（画面には出ない）
2. `python3 refresh_token.py` を実行する →「新しくなりました」と出れば、新トークンはクリップボードに入っている（画面には出ない）
3. **ほかをコピーせず**、パスワード管理ツールの値を貼り替えて保存する
4. GitHub の Settings → Secrets → Actions で `IG_TOKEN` の鉛筆（Update）を押し、貼り替えて保存する
5. `unset IG_TOKEN` を実行し、GitHub の Settings → Variables の `TOKEN_REFRESHED_ON` を今日の日付（例 2026-11-15）に書き換える
