# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, uuid, datetime as dt
from pathlib import Path
from typing import Any, Dict, List
from flask import Flask, render_template, request, redirect, url_for, abort

# ----------------------------------------------------------------------
# 基本設定（データ保存先など）
# ----------------------------------------------------------------------
APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/kanpo_ai"))
UPLOAD_DIR = DATA_ROOT / "uploads"
DATA_DIR = DATA_ROOT / "data"
for d in (DATA_ROOT, UPLOAD_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# 問診票（※変更不要：このファイル定義に従ってフォームを描画・収集）
with (APP_DIR / "ai_kampo_questionnaire.json").open("r", encoding="utf-8") as f:
    QUESTIONNAIRE = json.load(f)

app = Flask(__name__)


# ----------------------------------------------------------------------
# ユーティリティ
# ----------------------------------------------------------------------
def now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"

def read_all_records() -> List[Dict[str, Any]]:
    recs: List[Dict[str, Any]] = []
    for p in DATA_DIR.glob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                recs.append(json.load(f))
        except Exception:
            continue
    recs.sort(key=lambda x: x.get("submitted_at", ""), reverse=True)
    return recs


# ----------------------------------------------------------------------
# LLM によるワンショット評価（AI主体）
#   - ルール系（主訴キーワード→候補プール / 再ランク / 簡易スコア）は全廃
#   - 問診全体（form）だけを渡し、最終JSONを受け取る
#   - テンプレートが期待するキー名に正規化
# ----------------------------------------------------------------------
def llm_assess_full(form: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY is not set. This app requires an API key for full AI-driven assessment."}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # ---- JSON強制＆スキーマ付きプロンプト ----
        sys_prompt = (
    "あなたは漢方薬局のベテラン薬剤師です。"
    "入力の問診（主訴、八綱、気血水、舌・脈・顔色、生活）を総合して証を推定し、"
    "Top3の漢方薬候補を選定してください。"
    "各候補には『主訴との関係』を1行で明記し、患者向け説明は3〜4文に制限、"
    "薬膳（推奨/控え 各1〜3個）、生活アドバイス（3〜5個）、赤旗（1〜3個）を含めてください。"
    "出力は【厳密にJSONのみ】。余計な文字やマークダウンは禁止。"
    "スキーマは次の通り：{"
    '"chosen":"string","candidates":[{"name":"string","score":number,"pharmacist_tip":"string","reason":"string","patient_explain":"string","lifestyle":["string"],"foods_good":["string"],"foods_avoid":["string"],"counsel_points":["string"],"watch":"string"}],'
    '"axes":{"jitsu_kyo":"string","kan_netsu":"string","hyo_ri":"string"},'
    '"qxs":{"qi":"string","xue":"string","sui":"string"},'
    '"patient_summary":"string","chief_note":"string","diet":["string"],"lifestyle":["string"],"topics":["string"],'
    '"complaint_sections":[{"title":"string","background":"string","do":["string"],"foods_good":["string"],"foods_avoid":["string"],"points":["string"],"acupoints":["string"],"danger":["string"]}]}'
)


        payload = {"form": form}
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        resp = client.chat.completions.create(
    model=model,
    temperature=0.2,
    max_tokens=1800, 
    response_format={"type": "json_object"},
    messages=[ ... ],
)

        content = resp.choices[0].message.content or ""

# まず通常パース
try:
    raw = json.loads(content)
except Exception:
    # 失敗 → JSON修復プロンプトでリトライ（1回だけ）
    try:
        fix = client.chat.completions.create(
            model=model, temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system",
                 "content": "あなたはJSON整形ツールです。入力はJSONになりかけのテキストです。"
                            "無効部分を修復し、指定スキーマに合致する単一のJSONのみを出力してください。"
                            "余計なテキストは禁止。"},
                {"role": "user", "content": content}
            ]
        )
        fixed = fix.choices[0].message.content or ""
        raw = json.loads(fixed)
        print("[LLM JSON FIXED]", len(fixed))
    except Exception:
        # それでもダメなら最後の救済：{} 抽出
        start, end = content.find("{"), content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                raw = json.loads(content[start:end+1])
            except Exception:
                raw = {"llm_text": content}
        else:
            raw = {"llm_text": content}

# （この下に続く “candidates が空なら暫定補完 … / 正規化 …” は今まで通りでOK）

        assessment = {
            "chosen": raw.get("chosen", (cands_norm[0]["name"] if cands_norm else "")),
            "candidates": cands_norm,
            "axes": raw.get("axes", {}),
            "qxs": raw.get("qxs", {}),
            "patient_summary": raw.get("patient_summary", ""),
            "chief_note": raw.get("chief_note", ""),
            "diet": raw.get("diet", []) or [],
            "lifestyle": raw.get("lifestyle", []) or [],
            "topics": raw.get("topics", []) or [],
            "complaint_sections": raw.get("complaint_sections", []) or [],
            "llm_raw": raw,
        }

        # ---- 男性から妊娠注意を除去 ----
        sex = str(form.get("gender", "")).lower()
        if sex not in ["female", "woman", "女性", "女"]:
            import re as _re
            def _strip_preg(s: str) -> str:
                return _re.sub(r"妊娠中[^。]*。?", "", s or "")
            assessment["patient_summary"] = _strip_preg(assessment.get("patient_summary", ""))
            for c in assessment["candidates"]:
                if isinstance(c.get("script"), dict):
                    c["script"]["watch"] = _strip_preg(c["script"].get("watch", ""))

        # ---- 成功ログ ----
        try:
            print("[LLM ASSESS OK]", json.dumps(
                {"chosen": assessment["chosen"], "cand_count": len(assessment["candidates"])},
                ensure_ascii=False))
        except Exception:
            pass

        return assessment

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "insufficient_quota" in msg or "429" in msg:
            msg = "OpenAIのAPI残高が0のため、回答を生成できません。Billing > Overview からクレジットを追加してください。"
        try:
            print("[LLM ASSESS ERROR]", repr(e))
        except Exception:
            pass
        return {"error": msg}



# ----------------------------------------------------------------------
# ルーティング
# ----------------------------------------------------------------------
@app.route("/")
def index():
    # トップ：問診票の描画
    return render_template("index.html", q=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    # 問診の収集（問診票定義に沿って値を拾う）
    data: Dict[str, Any] = {}
    for sec in QUESTIONNAIRE.get("sections", []):
        for q in sec.get("questions", []):
            qid = q.get("id")
            qtype = q.get("type")
            if not qid:
                continue
            if qtype == "boolean":
                data[qid] = (request.form.get(qid) == "on")
            else:
                val = request.form.get(qid, "")
                data[qid] = (val.strip() if isinstance(val, str) else val)

    rec_id = str(uuid.uuid4())

    # ★ AI一本化：問診全体を LLM へ
    assessment = llm_assess_full(data)

    # エラー時でもテンプレートが壊れないよう最小スキーマを付与
    if "error" in assessment:
        assessment = {
            "chosen": "",
            "candidates": [],
            "axes": {},
            "qxs": {},
            "patient_summary": "",
            "chief_note": assessment["error"],  # 画面上部に理由が見えるように
            "diet": [],
            "lifestyle": [],
            "topics": [],
            "complaint_sections": [],
            "llm_raw": {"error": assessment["error"]},
        }

    record = {
        "id": rec_id,
        "submitted_at": now_iso(),
        "patient": {
            "name": data.get("name", ""),
            "age": data.get("age", ""),
            "sex": data.get("gender", ""),
            "region": data.get("region", ""),
            "chief_complaint": data.get("chief_complaint", ""),
        },
        "ai_assessment": assessment,
        "raw": data,
    }
    with (DATA_DIR / f"{rec_id}.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)

    return redirect(url_for("detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
def detail(rec_id: str):
    p = DATA_DIR / f"{rec_id}.json"
    if not p.exists():
        abort(404)
    with p.open("r", encoding="utf-8") as f:
        record = json.load(f)
    return render_template("detail.html", data=record)

@app.route("/admin")
def admin():
    recs = read_all_records()
    return render_template("admin.html", recs=recs)


# ----------------------------------------------------------------------
# エントリポイント
# ----------------------------------------------------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
