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
        # 完全AI駆動のため API キーは必須
        return {"error": "OPENAI_API_KEY is not set. This app requires an API key for full AI-driven assessment."}
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        sys_prompt = (
            "あなたは漢方薬局のベテラン薬剤師です。"
            "入力の問診（主訴、八綱、気血水、舌・脈・顔色、生活）を総合して証を推定し、"
            "Top3の漢方薬候補を選定してください。"
            "各候補には『主訴との関係』を1行で明記し、患者向け説明（3〜6文）、"
            "薬膳（推奨/控え）、生活アドバイス、面談で深掘りすべきポイント、受診目安（赤旗）を含めてください。"
            "必ずTop3のうち最低1つは主訴に直接対応する処方にしてください。"
            "男性には妊娠関連の注意は出さないでください。"
            "出力は必ずJSON（candidates[], chosen, axes, qxs, patient_summary, complaint_sections, diet, lifestyle 等）。"
        )

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps({"form": form}, ensure_ascii=False)}
            ],
        )
        content = resp.choices[0].message.content

        # 1) LLM応答をJSONとして受ける（失敗時は生テキスト保持）
        try:
            raw = json.loads(content)
        except Exception:
            raw = {"llm_text": content}

        # 2) テンプレートが期待する形へ“正規化”
        cands_norm = []
        for it in (raw.get("candidates") or []):
            name = it.get("name", "")
            score = it.get("score", 1.0)
            pharmacist_tip = it.get("pharmacist_tip", "")
            patient_explain = it.get("patient_explain", "")
            watch = it.get("watch", "")
            reason = it.get("reason", "")
            cands_norm.append({
                "name": name,
                "score": score,
                "pharmacist_tip": pharmacist_tip,
                "script": {"explain": patient_explain, "watch": watch},
                "lifestyle": it.get("lifestyle", []),
                "foods_good": it.get("foods_good", []),
                "foods_avoid": it.get("foods_avoid", []),
                "counsel_points": it.get("counsel_points", []),
                "ai_reason": reason,
            })

        assessment = {
            "chosen": raw.get("chosen", (cands_norm[0]["name"] if cands_norm else "")),
            "candidates": cands_norm,
            "axes": raw.get("axes", {}),
            "qxs": raw.get("qxs", {}),
            "patient_summary": raw.get("patient_summary", ""),
            "chief_note": raw.get("chief_note", ""),
            "diet": raw.get("diet", []),
            "lifestyle": raw.get("lifestyle", []),
            "topics": raw.get("topics", []),
            "complaint_sections": raw.get("complaint_sections", []),
            "llm_raw": raw,  # デバッグ用に原文も保持
        }

        # 3) 妊娠関連の注意を男性からは削除（安全策）
        sex = str(form.get("gender", "")).lower()
        if sex not in ["female", "woman", "女性", "女"]:
            import re as _re
            def _strip_preg(s: str) -> str:
                return _re.sub(r"妊娠中[^。]*。?", "", s or "")
            assessment["patient_summary"] = _strip_preg(assessment.get("patient_summary", ""))
            for c in assessment["candidates"]:
                if isinstance(c.get("script"), dict):
                    c["script"]["watch"] = _strip_preg(c["script"].get("watch", ""))

        # 4) 空配列・空文字の安全補完
        assessment["candidates"] = assessment.get("candidates") or []
        assessment["diet"] = assessment.get("diet") or []
        assessment["lifestyle"] = assessment.get("lifestyle") or []
        assessment["complaint_sections"] = assessment.get("complaint_sections") or []

        # 5) 成功ログ（Render Logs で確認用）
        try:
            print(
                "[LLM ASSESS OK]",
                json.dumps(
                    {"chosen": assessment["chosen"], "cand_count": len(assessment["candidates"])},
                    ensure_ascii=False,
                ),
            )
        except Exception:
            pass

        return assessment

    except Exception as e:
        # 例外発生時はログ出力してエラー情報を返す
        try:
            print("[LLM ASSESS ERROR]", repr(e))
        except Exception:
            pass
        return {"error": f"{type(e).__name__}: {e}"}


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
