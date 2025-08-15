# -*- coding: utf-8 -*-
import os
import json
import re
from flask import Flask, render_template, request, redirect, url_for, flash

# ---------- Config ----------
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # 任意。Azure/OpenRouter等を使うなら設定
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")  # セッション/flash用

# ---------- OpenAI client (new SDK) ----------
# 2024以降の新SDKを想定
try:
    from openai import OpenAI
    _client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        _client_kwargs["base_url"] = OPENAI_BASE_URL
    client = OpenAI(**_client_kwargs)
except Exception as e:
    client = None


# ---------- Prompt builder ----------
SYSTEM_PROMPT = """あなたは経験豊富な日本の漢方薬剤師です。出力は常に日本語。

入力として患者のフォーム回答（主症状、急性/慢性、気血水、八綱分類、舌診、脈診、生活・安全情報）が与えられます。

【方針（重要）】
- 症状優先/証優先の重み付けを数値で行う：
  - 急性：症状70％・証30％
  - 慢性：症状30％・証70％
- 候補3剤の内訳：
  1つ目＝症状優先、2つ目＝証優先、3つ目＝折衷（総合点上位）
- 日本国内で使用可能な薬局製剤または保険適応漢方処方「のみ」を用いる。中医学の通称や国外限定名は不可。曖昧なら日本で一般的な名称に置き換える。
- 安全性（妊娠・授乳・併用薬・アレルギー）に抵触する処方は候補から除外し、その旨を safety_notes に明記。

【あなたのタスク】
1) フォーム回答を根拠に、主症状と急性/慢性を再確認（矛盾があれば指摘）。
2) 気血水を6分類（気虚/気滞/血虚/瘀血/水滞/津液不足）で判定（正常は出力から除外してよい）。
3) 八綱分類（表or裏、寒or熱、虚or実）を判定し、「表熱虚」などのラベルを生成。
4) 処方スコアリング（内部想定の候補群に対し0〜1で算出）：
   - symptom_fit（主症状・急性/慢性に対する一致度）
   - constitution_fit（気血水＋八綱に対する一致度）
   - safety（禁忌がなければ1.0、禁忌があれば0.0）
   - total = symptom_fit*症状重み + constitution_fit*証重み
5) 総合点の高いものから3剤を選び、各剤に100〜200文字の根拠（症状＋証の両面）を記載。3剤は上記内訳ルールを満たすこと。
6) 候補3つから1剤に絞る薬剤師向けアドバイス（季節/症状強度/体力/安全性の観点）。
7) 薬膳材料を5つ提案（各30文字以内、国内で入手容易）。
8) 主症状への具体アドバイス（100文字以内）。
9) 生活上のアドバイス（100文字以内）。
10) 妊娠・授乳、既往薬、アレルギー等からの禁忌/注意があれば safety_notes に簡潔に明記。
11) すべてを以下のJSONで返答（余計な文章・コードブロックや解説は不要）:

{
  "main_symptom": "",
  "acute_or_chronic": "急性|慢性",
  "kiketsusui": ["気滞","血虚"], 
  "hakkou": {"hyou_ura":"表|裏", "kan_netsu":"寒|熱", "kyo_jitsu":"虚|実", "label":"表熱実"},
  "kampo_candidates": [
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"症状優先"
    },
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"証優先"
    },
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"折衷"
    }
  ],
  "pharmacist_selection_advice": "",
  "yakuzen_ingredients": [
    {"name":"", "effect":""},
    {"name":"", "effect":""},
    {"name":"", "effect":""},
    {"name":"", "effect":""},
    {"name":"", "effect":""}
  ],
  "advice_for_main_symptom": "",
  "lifestyle_advice": "",
  "safety_notes": "",
  "confidence": 0.85
}
"""

def build_user_prompt(form_data: dict) -> str:
    # 可読性のためにJSONそのものを渡す
    return "以下が患者フォームの生データです。これにもとづいて上記タスクを実行してください。\n\n" + json.dumps(form_data, ensure_ascii=False, indent=2)


def call_openai(messages):
    if client is None or not OPENAI_API_KEY:
        raise RuntimeError("OpenAIクライアントが初期化されていません。OPENAI_API_KEY を環境変数に設定してください。")

    # Chat Completions API（互換性重視）
    resp = client.chat.completions.create(
        model=MODEL,
        temperature=0.4,
        messages=messages,
    )
    return resp.choices[0].message.content


def safe_json_extract(s: str):
    """モデル出力から最初のJSONオブジェクトを抽出してparseする。"""
    if not s:
        return None
    # コードフェンス除去
    s_clean = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.MULTILINE)
    # 最初の { ... } を抜き出す
    match = re.search(r"\{.*\}", s_clean, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    # そのままトライ
    try:
        return json.loads(s_clean)
    except Exception:
        return None


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    form_data = request.form.to_dict(flat=False)  # チェックボックス等の複数値対応
    # 単一値を整形
    normalized = {}
    for k, v in form_data.items():
        if len(v) == 1:
            normalized[k] = v[0]
        else:
            normalized[k] = v  # 複数選択は配列のまま

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(normalized)},
        ]
        raw = call_openai(messages)
        parsed = safe_json_extract(raw)
        if not parsed:
            flash("AIの出力をJSONとして解釈できませんでした。生出力を表示します。", "warning")
            return render_template("detail.html", raw_output=raw, result=None, form=normalized)
        return render_template("detail.html", result=parsed, raw_output=None, form=normalized)

    except Exception as e:
        flash(f"エラー: {e}", "danger")
        return redirect(url_for("index"))


# health check
@app.route("/health")
def health():
    return {"status": "ok"}


if __name__ == "__main__":
    # 本番は gunicorn を推奨（Render想定）
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8000)), debug=True)
