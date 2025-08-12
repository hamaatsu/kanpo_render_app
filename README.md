# 漢方AI v11c（Render用フル一式）

- Flask + waitress 起動
- OpenAI は環境変数 OPENAI_API_KEY があればAI助言を生成。未設定ならルールベース。
- Basic認証: BASIC_AUTH_USERNAME / BASIC_AUTH_PASSWORD（未設定は admin / changeme）

## Render 設定
- Start Command: `waitress-serve --host=0.0.0.0 --port=$PORT app:app`
- Environment:
  - (任意) OPENAI_API_KEY
  - (任意) OPENAI_MODEL 例: gpt-4o-mini
  - (任意) BASIC_AUTH_USERNAME, BASIC_AUTH_PASSWORD

## デプロイ手順
1. この一式をGitHubにコミット
2. Render のサービスで Clear build cache & deploy
3. `/` → フォーム入力 → 送信 → `/record/<id>` で結果表示
