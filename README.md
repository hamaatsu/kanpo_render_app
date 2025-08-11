# 漢方AI問診（Renderデプロイ用）

## 使い方（Render）
1. GitHubで新規リポジトリを作成（PrivateでOK）
2. このフォルダ内のファイルをGitHubにアップロード（Zipをドラッグ＆ドロップでOK）
3. Renderダッシュボード → New → Web Service → GitHubを接続 → このリポジトリを選択
4. 設定のポイント
   - Region: Singapore（日本に近い）
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `waitress-serve --host=0.0.0.0 --port=$PORT app:app`
   - Environment Variables:
     - BASIC_AUTH_USERNAME=admin
     - BASIC_AUTH_PASSWORD=（強いパスワード）
     - FLASK_SECRET=（ランダム文字列）
5. デプロイ完了後、発行URLへアクセス（/admin は認証あり）

### 保存について
- Freeプランは再デプロイでuploads/dataが消える可能性があります。
- 本番運用する場合はRenderのPersistent Diskを有効化するか、S3等に保存するよう改修してください。

## ローカル実行
```
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # 値を設定
python app.py
# → http://localhost:5000
```
