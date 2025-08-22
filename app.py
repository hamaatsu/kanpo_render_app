# -*- coding: utf-8 -*-
import os
import json
import re
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash

# ---------- Config ----------
MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")  # 任意（Azure/OpenRouter等）
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret")  # セッション/flash用

# === inventory.json の読み込み ===
APP_DIR = Path(__file__).resolve().parent
INVENTORY_PATH = APP_DIR / "inventory.json"
try:
    with INVENTORY_PATH.open("r", encoding="utf-8") as f:
        _inv = json.load(f)
    ALLOWED_FORMULAS = list(dict.fromkeys(_inv.get("allowed_formulas", [])))
except Exception:
    ALLOWED_FORMULAS = []

# ---------- OpenAI client (new SDK) ----------
try:
    from openai import OpenAI
    _client_kwargs = {"api_key": OPENAI_API_KEY}
    if OPENAI_BASE_URL:
        _client_kwargs["base_url"] = OPENAI_BASE_URL
    client = OpenAI(**_client_kwargs)
except Exception:
    client = None


# ---------- Prompt builder ----------
SYSTEM_PROMPT = """あなたは経験豊富な日本の漢方薬剤師です。出力は常に日本語。

入力として患者のフォーム回答（年齢、性別、主症状、急性/慢性、気血水、八綱分類、舌診、脈診、生活・安全情報）が与えられます。

【方針（重要）】
- 症状優先/証優先の重み付けを数値で行う：
  - 急性：症状70％・証30％
  - 慢性：症状30％・証70％
- 候補3剤の内訳：
  1つ目＝症状優先、2つ目＝証優先、3つ目＝折衷（総合点上位）
- 日本国内で使用可能な薬局製剤または保険適応漢方処方「のみ」を用いる。中医学の通称や国外限定名は不可。曖昧なら日本で一般的な名称に置き換える。
- 安全性（妊娠・授乳・併用薬・アレルギー）に抵触する処方は候補から除外し、その旨を safety_notes に明記。
- 候補に挙げてよい方剤は user から渡す allowed_formulas の中だけです。必ずその中から選び、名称は完全一致で出力してください。

【追加制約】
- 「症状優先」に選ぶ候補は、**日本の保険適応または一般的効能効果として主訴に合致**する処方のみとする（例：頭痛に適応がない処方は不可）。
- 「証優先」「折衷」は適応外でもよいが、臨床的妥当性を短く明記する。
- 各候補には "japan_indication_ok": true|false と "age_sex_considerations": "〜" を必ず含める。
- トップレベルに "patient_meta": {"name":"","age":0,"gender":""} を必ず含める（年齢・性別の考慮を反映）。

【あなたのタスク】
1) フォーム回答を根拠に、主症状と急性/慢性を再確認（矛盾があれば指摘）。
2) 気血水を6分類（気虚/気滞/血虚/瘀血/水滞/津液不足）で判定（正常は出力から除外してよい）。
3) 八綱分類（表or裏、寒or熱、虚or実）を判定し、「表熱実」などのラベルを生成。
4) 処方スコアリング（0〜1）：
   - symptom_fit（主症状・急性/慢性に対する一致度）
   - constitution_fit（気血水＋八綱に対する一致度）
   - safety（禁忌がなければ1.0、禁忌があれば0.0）
   - total = symptom_fit*症状重み + constitution_fit*証重み
   - 各候補に "priority_basis": 「症状優先」「証優先」「折衷」を付与。
5) 総合点の高いものから3剤を選び、各剤に100〜200文字の根拠（症状＋証の両面）を記載。3剤は上記内訳ルールを満たすこと。
6) 候補3つから1剤に絞る薬剤師向けアドバイス（季節/症状強度/体力/安全性の観点）。
7) 薬膳材料を5つ提案（各30文字以内、国内で入手容易）。
8) ツボのアドバイス（80〜100文字、経穴名＋位置＋押し方を1段落）。
9) アロマのアドバイス（80〜100文字、精油3種・香り特性・使い方を1段落）。
10) 妊娠・授乳、既往薬、アレルギー等からの禁忌/注意があれば safety_notes に簡潔に明記。
11) すべてを以下のJSONで返答（余計な文章・コードブロックや解説は不要）:

{
  "patient_meta": {"name":"", "age":0, "gender":""},
  "main_symptom": "",
  "acute_or_chronic": "急性|慢性",
  "kiketsusui": ["気滞","血虚"],
  "hakkou": {"hyou_ura":"表|裏", "kan_netsu":"寒|熱", "kyo_jitsu":"虚|実", "label":"表熱実"},
  "kampo_candidates": [
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"症状優先",
      "japan_indication_ok": true,
      "age_sex_considerations": ""
    },
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"証優先",
      "japan_indication_ok": false,
      "age_sex_considerations": ""
    },
    {
      "name":"", 
      "rationale":"", 
      "scores":{"symptom_fit":0.00,"constitution_fit":0.00,"safety":1.00,"total":0.00},
      "priority_basis":"折衷",
      "japan_indication_ok": false,
      "age_sex_considerations": ""
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
  "acupoints_advice": "",
  "aroma_advice": "",
  "safety_notes": "",
  "confidence": 0.85
}
"""

def build_user_prompt(form_data: dict) -> str:
    # 氏名・年齢・性別を明示し、AIが確実に参照できるようにする
    patient_meta = {
        "name": form_data.get("name") or form_data.get("氏名") or "",
        "age": int(form_data.get("age") or 0),
        "gender": form_data.get("gender") or form_data.get("sex") or form_data.get("性別") or "",
    }
    payload = {
        "form": form_data,
        "patient_meta": patient_meta,
        "allowed_formulas": ALLOWED_FORMULAS,
        "instruction": (
            "候補に挙げてよい方剤は allowed_formulas の中だけ。"
            "名称は完全一致で返答。"
            "3剤の内訳ルール（症状優先/証優先/折衷）を必ず満たす。"
            "症状優先は日本の適応に合致すること。"
        )
    }
    return "以下のJSONを読み取り、タスクを実行してください。\n\n" + json.dumps(payload, ensure_ascii=False, indent=2)


def call_openai(messages):
    if client is None or not OPENAI_API_KEY:
        raise RuntimeError("OpenAIクライアントが初期化されていません。OPENAI_API_KEY を環境変数に設定してください。")
    # Chat Completions API
    resp = client.chat.completions.create(
        model=MODEL,
        messages=messages,
    )
    return resp.choices[0].message.content


def safe_json_extract(s: str):
    """モデル出力から最初のJSONオブジェクトを抽出してparseする。"""
    if not s:
        return None
    s_clean = re.sub(r"^```(?:json)?|```$", "", s.strip(), flags=re.MULTILINE)
    match = re.search(r"\{.*\}", s_clean, flags=re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except Exception:
            pass
    try:
        return json.loads(s_clean)
    except Exception:
        return None


def filter_candidates_to_allowlist(parsed: dict, allowed: list[str]):
    """LLM出力の候補を allowlist でふるいにかける。除外された名前を返す。"""
    if not parsed or not isinstance(parsed, dict):
        return parsed, []
    if not allowed:
        return parsed, []

    dropped = []
    cands = parsed.get("kampo_candidates")
    if isinstance(cands, list):
        kept = []
        for c in cands:
            name = (c or {}).get("name")
            if name in allowed:
                kept.append(c)
            else:
                if name:
                    dropped.append(name)
        parsed["kampo_candidates"] = kept
    return parsed, dropped


# ---------- Routes ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    form_data = request.form.to_dict(flat=False)  # チェックボックス等の複数値対応
    normalized = {}
    for k, v in form_data.items():
        normalized[k] = v[0] if len(v) == 1 else v

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

        # allowlist 安全網
        parsed, dropped = filter_candidates_to_allowlist(parsed, ALLOWED_FORMULAS)
        if dropped:
            flash("許可リスト外の処方を除外しました: " + "、".join(dropped), "warning")
        if not parsed.get("kampo_candidates"):
            flash("候補が全てリスト外だったか、生成に失敗しました。主訴や証の記載をもう少し詳しくして再度お試しください。", "warning")

        # patient_meta が欠けていたらフォームから補完（画面表示のため）
        pm = parsed.get("patient_meta") or {}
        if not isinstance(pm, dict):
            pm = {}
        if not pm.get("name"):   pm["name"] = normalized.get("name") or normalized.get("氏名") or ""
        if not pm.get("age"):    pm["age"] = int(normalized.get("age") or 0)
        if not pm.get("gender"): pm["gender"] = normalized.get("gender") or normalized.get("sex") or normalized.get("性別") or ""
        parsed["patient_meta"] = pm

        # --- 主訴優先は必ず適応OKに揃える（サーバ側の保険） ---
        cands = parsed.get("kampo_candidates") or []
        # 「症状優先」の候補を探す
        sym_idx = next((i for i, c in enumerate(cands) if (c or {}).get("priority_basis") == "症状優先"), None)
        if sym_idx is not None:
            sym_ok = bool((cands[sym_idx] or {}).get("japan_indication_ok"))
            if not sym_ok:
                # 適応OKの候補を探して先頭に
                swap_idx = next((i for i, c in enumerate(cands) if bool((c or {}).get("japan_indication_ok"))), None)
                if swap_idx is not None:
                    cands[0], cands[swap_idx] = cands[swap_idx], cands[0]
                    cands[0]["priority_basis"] = "症状優先"
                    parsed["kampo_candidates"] = cands
                else:
                    flash("注意：主訴に対する日本の適応に合致する候補が得られませんでした。入力内容をご確認ください。", "warning")

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