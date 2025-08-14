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
            "各候補には『主訴との関係』を1行で明記し、患者向け説明（3〜6文）、"
            "薬膳（推奨/控え）、生活アドバイス、面談で深掘りすべきポイント、受診目安（赤旗）を含めてください。"
            "必ずTop3のうち最低1つは主訴に直接対応する処方にしてください。"
            "男性には妊娠関連の注意は出さないでください。"
            "出力は【厳密にJSONのみ】で、余計なテキストやマークダウンは禁止します。"
            "以下のスキーマに完全準拠してください。"
            "{"
            '"chosen":"string",'
            '"candidates":[{"name":"string","score":number,"pharmacist_tip":"string","reason":"string","patient_explain":"string",'
            '"lifestyle":["string"],"foods_good":["string"],"foods_avoid":["string"],"counsel_points":["string"],"watch":"string"}],'
            '"axes":{"jitsu_kyo":"string","kan_netsu":"string","hyo_ri":"string"},'
            '"qxs":{"qi":"string","xue":"string","sui":"string"},'
            '"patient_summary":"string","chief_note":"string","diet":["string"],"lifestyle":["string"],"topics":["string"],'
            '"complaint_sections":[{"title":"string","background":"string","do":["string"],"foods_good":["string"],"foods_avoid":["string"],"points":["string"],"acupoints":["string"],"danger":["string"]}]'
            "}"
        )

        payload = {"form": form}
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=1200,
            # ★ JSONモードをON（対応モデル：gpt-4o/4o-mini など）
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
        )
        content = resp.choices[0].message.content or ""

        # ---- まず素直にJSONとして読む。失敗時は再パースを試みる ----
        try:
            raw = json.loads(content)
        except Exception:
            start, end = content.find("{"), content.rfind("}")
            if start != -1 and end != -1 and end > start:
                try:
                    raw = json.loads(content[start:end+1])
                except Exception:
                    raw = {"llm_text": content}
            else:
                raw = {"llm_text": content}

        # ---- candidates が空なら暫定候補を自動補完（UI空洞化防止）----
        if not raw.get("candidates"):
            chief = str(form.get("chief_complaint", "")).strip()
            fallback_name = "六君子湯" if any(k in chief for k in ["胃","むかむか","食欲","膨満","げっぷ","ゲップ"]) else "補中益気湯"
            raw["candidates"] = [{
                "name": fallback_name, "score": 6.0,
                "pharmacist_tip": "問診からの暫定候補（自動補完）。",
                "reason": "主訴に近い症状に対応する一般的な処方。",
                "patient_explain": "AI応答が空だったため、問診内容から暫定候補を自動補完しています。最終判断は薬剤師が行います。",
                "lifestyle": [], "foods_good": [], "foods_avoid": [], "counsel_points": [], "watch": ""
            }]
            raw.setdefault("chosen", fallback_name)
            raw["chief_note"] = (raw.get("chief_note") or "") + "（AI応答が空だったため暫定候補を補完）"
            # デバッグ用に生テキストを短くログ出し
            try:
                print("[LLM RAW EMPTY]", content[:400])
            except Exception:
                pass

        # ---- テンプレートが読む形に正規化 ----
        cands_norm = []
        for it in (raw.get("candidates") or []):
            cands_norm.append({
                "name": it.get("name", ""),
                "score": it.get("score", 1.0),
                "pharmacist_tip": it.get("pharmacist_tip", ""),
                "script": {"explain": it.get("patient_explain", ""), "watch": it.get("watch", "")},
                "lifestyle": it.get("lifestyle", []) or [],
                "foods_good": it.get("foods_good", []) or [],
                "foods_avoid": it.get("foods_avoid", []) or [],
                "counsel_points": it.get("counsel_points", []) or [],
                "ai_reason": it.get("reason", ""),
            })

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
