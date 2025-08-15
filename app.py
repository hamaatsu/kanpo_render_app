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

入力として患者のフォーム回答（主症状、急性/慢性、気血水、八綱分類の回答、舌診、脈診、生活・安全情報）が与えられます。
あなたのタスク：
1) フォーム回答を根拠に、主症状、急性/慢性を再確認（矛盾があれば指摘）。
2) 気血水を6分類（気虚/気滞/血虚/瘀血/水滞/津液不足）で判定（正常もあり）。
3) 八綱分類（表or裏、寒or熱、虚or実）を判定し、「表寒虚」などのラベルを生成。
4) 以上を踏まえ、漢方薬の候補を3つ提案し、各候補に100〜200文字の根拠を記載。
   ※ なるべく「主症状（標治）」と「体質（本治）」の両面を根拠に含める。
   ※ 慢性の場合は、症状よりも証に適した処方を優先する
   ※ 必ず日本国内で使用可能な薬局製剤または保険適応漢方処方名のみを使用する。
      中医学での処方名や国外限定処方名は使用しない。
      複数の呼び名がある場合は、日本で一般的な名称に置き換える。
5) 候補3つから1剤に絞る際の薬剤師向けアドバイスを簡潔に提示（季節/症状の強さ/安全性などの観点）。
6) 薬膳材料を5つ提案し、各30文字以内で理由（効能）を付記。日本で入手容易なもの。
7) 主症状に対する具体的アドバイス（100文字以内）。
8) 生活上のアドバイス（100文字以内）。
9) 妊娠・授乳、既往薬、アレルギー等からの禁忌/注意があれば短く注意喚起。
10) すべてを以下のJSONで返答（余計な文章・コードブロックや解説は不要）:

{
  "main_symptom": "...",
  "acute_or_chronic": "急性|慢性",
  "kiketsusui": ["気虚", "血虚", "水滞"],  // 正常な要素は含めない
  "hakkou": {"hyou_ura":"表|裏", "kan_netsu":"寒|熱", "kyo_jitsu":"虚|実", "label":"表熱虚"},
  "kampo_candidates": [
    {"name":"", "rationale":""},
    {"name":"", "rationale":""},
    {"name":"", "rationale":""}
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
  "confidence": 0.0
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
