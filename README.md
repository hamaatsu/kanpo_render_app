# 漢方AI問診 v3（初心者モード・1画面・体質説明・単一方剤）
- フォーム上でチェックを入れると、右のバッジに「実/虚・寒/熱・表/裏・気血水」がリアルタイム反映
- 送信すると 1剤のみ提案＋体質説明＋読み上げスクリプトを表示

## Render
Build: `pip install -r requirements.txt`
Start: `waitress-serve --host=0.0.0.0 --port=$PORT app:app`
Env: BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD / FLASK_SECRET
