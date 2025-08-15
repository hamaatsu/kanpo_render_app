# 漢方相談AIフォーム（Flask）

薬剤師が問診しながら入力し、AI（OpenAI）で解析するシンプルなWebアプリです。Renderにデプロイできます。

## ローカル実行

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=YOUR_KEY
export OPENAI_MODEL=gpt-4o-mini
python app.py
```

## Renderデプロイ

- 本リポジトリをGitHubにPush
- Renderで「New +」→ Web Service → リポジトリ選択
- Build Command: `pip install -r requirements.txt`
- Start Command: `gunicorn app:app`
- Env Vars: `OPENAI_API_KEY` を追加（必須）

## 注意
- アプリ内での判定ロジックは最小限。フォームの生データをプロンプトに渡し、**AIが判定**します。
- モデル出力はJSON固定。パースできない場合は生出力を表示します。
- 必要に応じて `SYSTEM_PROMPT` を調整してください。
