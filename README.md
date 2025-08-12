# 漢方AI問診 v11a（UI復元版）

- v11a期の「1画面問診＋右サイド初心者ガイド」UIを復元
- 画像は **舌/顔/体・むくみ/爪** をカテゴリ別に保存・表示
- AI助言は OpenAI API をセットした時のみ有効（未設定時はルールベース）

## 環境変数（Render -> Environment）
- BASIC_AUTH_USERNAME=admin（任意）
- BASIC_AUTH_PASSWORD=changeme（任意）
- FLASK_SECRET=任意
- OPENAI_API_KEY=sk-... （任意）
- OPENAI_MODEL=gpt-4o-mini（任意）

## 起動
- Render: Procfile で `gunicorn app:app` が動きます
- ローカル: `pip install -r requirements.txt && python app.py`
