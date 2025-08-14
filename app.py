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

# 問診票（JSON定義に従ってフォームを描画）
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
# チェック式 → 単一ラベル集計（初心者向けUIをAI用に要約）
# ----------------------------------------------------------------------
def _winner(scores: Dict[str, int], tie_label: str) -> str:
    if not scores:
        return tie_label
    mx = max(scores.values())
    if mx <= 0:
        return tie_label
    winners = [k for k, v in scores.items() if v == mx]
    return winners[0] if len(winners) == 1 else tie_label

def derive_kyojitsu(signs: List[str]) -> str:
    kyo = {"疲れやすい/だるい","声が小さい","息切れしやすい","食欲がない","冷えやすい"}
    jitsu = {"いらいら/怒りっぽい","痛みが強い/局所的","体力はある","便秘がち","舌苔が厚い"}
    scores = {"虚": 0, "実": 0}
    for s in signs or []:
        if s in kyo: scores["虚"] += 1
        if s in jitsu: scores["実"] += 1
    return _winner(scores, "中間／不明")

def derive_kanetsu(signs: List[str]) -> str:
    kan = {"冷えると悪化","温めると楽","冷たい飲食を好む"}
    netsu = {"顔が赤い/ほてる","喉が渇く","発汗多い/口渇"}
    scores = {"寒": 0, "熱": 0}
    for s in signs or []:
        if s in kan: scores["寒"] += 1
        if s in netsu: scores["熱"] += 1
    return _winner(scores, "中間／不明")

def derive_hyori(signs: List[str]) -> str:
    hyo = {"悪寒/発熱/頭痛（かぜ様）","首肩こり","表在の痛み"}
    ri  = {"腹部症状が主","慢性/深部の不調","冷えが下腹にある"}
    scores = {"表": 0, "裏": 0}
    for s in signs or []:
        if s in hyo: scores["表"] += 1
        if s in ri:  scores["裏"] += 1
    return _winner(scores, "中間／不明")

def derive_kqs_main(buckets: Dict[str, List[str]]) -> str:
    patterns = {
        "気虚": buckets.get("qixu_signs", []) or [],
        "気滞": buckets.get("qitai_signs", []) or [],
        "瘀血": buckets.get("oketsu_signs", []) or [],
        "血虚": buckets.get("kekkyos_signs", []) or [],
        "水滞": buckets.get("suitai_signs", []) or [],
        "陰虚": buckets.get("inkyo_signs", []) or [],
    }
    scores = {k: len(v) for k, v in patterns.items()}
    return _winner(scores, "不明")


# ----------------------------------------------------------------------
# LLM（AI）判定：5項目スキーマで短く・堅牢に
# ----------------------------------------------------------------------
def llm_assess_full(form: Dict[str, Any]) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "OPENAI_API_KEY is not set. このアプリはAI判定にAPIキーが必須です。"}
    try:
        from openai import OpenAI
        # Gunicornのtimeoutより短めに（サーバで落ちる前に制御）
        client = OpenAI(api_key=api_key, timeout=55.0)

        # LLM には要約ラベル（hakkou_* / kqs_main）を主に参照させる
        sys_prompt = (
    "あなたは漢方医学の専門家です。以下の問診（主訴・八綱・気血水・舌診・脈診・顔色・生活・年齢・性別）を総合解析し、"
    "症例ごとにゼロから文章を生成して提案します。テンプレ文や定型の差し替えは使用しません。"
    "解析手順は次の通り："
    "1) 入力を統合して証を決定（八綱＋気血水＋舌脈顔色の整合）"
    "2) 証に適合し、かつ主訴の改善に直結する漢方薬候補を3種類選定（主訴適合に加点）"
    "3) 候補ごとに『選定理由（証と主訴）』『患者向け説明（3〜6文）』を生成"
    "4) 主訴に直結する行動提案（薬膳・生活）を必ず出す（症状のトリガーや天候/時間帯などの条件を反映）"
    "5) 赤旗（受診目安）も主訴に応じて具体化"
    "6) 出力は必ず有効なJSONオブジェクトのみ（マークダウンや余計な文字は出力しない）"
    "7) 男性には妊娠関連の注意は含めない。"
    "出力スキーマは次の通り："
    "{"
      "\"chosen\":\"string\","
      "\"candidates\":[{"
        "\"name\":\"string\","
        "\"score\": number,"
        "\"pharmacist_tip\":\"string\","
        "\"reason\":\"string\","
        "\"patient_explain\":\"string\","
        "\"lifestyle\":[\"string\"],"
        "\"foods_good\":[\"string\"],"
        "\"foods_avoid\":[\"string\"],"
        "\"counsel_points\":[\"string\"],"
        "\"watch\":\"string\""
      "}],"
      "\"axes\":{\"jitsu_kyo\":\"string\",\"kan_netsu\":\"string\",\"hyo_ri\":\"string\"},"
      "\"qxs\":{\"qi\":\"string\",\"xue\":\"string\",\"sui\":\"string\"},"
      "\"patient_summary\":\"string\","
      "\"chief_note\":\"string\","
      "\"diet\":[\"string\"],"
      "\"lifestyle\":[\"string\"],"
      "\"topics\":[\"string\"],"
      "\"complaint_sections\":[{"
        "\"title\":\"string\","
        "\"background\":\"string\","
        "\"do\":[\"string\"],"
        "\"foods_good\":[\"string\"],"
        "\"foods_avoid\":[\"string\"],"
        "\"points\":[\"string\"],"
        "\"acupoints\":[\"string\"],"
        "\"danger\":[\"string\"]"
      "}]"
    "}"
    "要件："
    "- complaint_sections は必ず1件以上を返し、主訴に直結する具体策を含めること。"
    "- 候補3種のうち最低1つは主訴に直接対応する処方にすること。"
)


        payload = {"form": form}
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

        resp = client.chat.completions.create(
            model=model,
            temperature=0.2,
            max_tokens=900,  # 短く速く
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}
            ],
        )
        content = resp.choices[0].message.content or ""

        # --- JSONパース（壊れた場合は {} 抜き出しで救済）
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

        # --- 正規化（テンプレが読む形）
        cands_norm: List[Dict[str, Any]] = []
        for it in (raw.get("candidates") or []):
            cands_norm.append({
                "name": it.get("name", ""),
                "score": 1.0,
                "pharmacist_tip": "",
                "script": {"explain": it.get("why_fit", ""), "watch": ""},
                "lifestyle": [],
                "foods_good": [],
                "foods_avoid": [],
                "counsel_points": [],
                "ai_reason": it.get("why_fit", ""),
            })

        # --- フォールバック（空にならないよう最低1件）
        if not cands_norm:
            cands_norm = [{
                "name": "補中益気湯",
                "score": 1.0,
                "pharmacist_tip": "",
                "script": {"explain": "AI応答が不完全だったため暫定候補を表示しています。最終判断は薬剤師が行います。", "watch": ""},
                "lifestyle": [], "foods_good": [], "foods_avoid": [], "counsel_points": [],
                "ai_reason": "暫定候補"
            }]

        assessment = {
            "chosen": (cands_norm[0]["name"] if cands_norm else ""),
            "candidates": cands_norm,
            "axes": {"sho": raw.get("sho", "")},
            "qxs": {},
            "patient_summary": f"証：{raw.get('sho','')}",
            "chief_note": raw.get("selection_advice", ""),
            "diet": raw.get("diet_good", []) or [],
            "lifestyle": raw.get("lifestyle", []) or [],
            "topics": [],
            "complaint_sections": [],
            "llm_raw": raw,
        }

        # --- 妊娠関連の注意を男性から除去（安全策）
        sex = str(form.get("gender", "")).lower()
        if sex not in ["female", "woman", "女性", "女"]:
            import re as _re
            def _strip_preg(s: str) -> str:
                return _re.sub(r"妊娠中[^。]*。?", "", s or "")
            assessment["patient_summary"] = _strip_preg(assessment.get("patient_summary", ""))
            if isinstance(assessment.get("chief_note"), str):
                assessment["chief_note"] = _strip_preg(assessment["chief_note"])

        # --- 成功ログ
        try:
            print("[LLM ASSESS OK]", json.dumps(
                {"chosen": assessment["chosen"], "cand_count": len(assessment["candidates"])},
                ensure_ascii=False))
        except Exception:
            pass

        return assessment

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        if "Timeout" in msg or "timed out" in msg:
            msg = "AI応答が時間内に完了しませんでした（タイムアウト）。もう一度お試しください。"
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
    return render_template("index.html", q=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    # 問診の収集（JSON定義に沿って値を拾う）
    data: Dict[str, Any] = {}
    for sec in QUESTIONNAIRE.get("sections", []):
        for q in sec.get("questions", []):
            qid = q.get("id")
            qtype = q.get("type")
            if not qid:
                continue
            if qtype == "boolean":
                data[qid] = (request.form.get(qid) == "on")
            elif qtype == "checkboxes":
                data[qid] = request.form.getlist(qid)  # ← 複数チェック対応
            else:
                val = request.form.get(qid, "")
                data[qid] = (val.strip() if isinstance(val, str) else val)

    # チェック → 単一ラベルに要約（AIはこのラベル中心に参照）
    data["hakkou_jitsu_kyo"] = derive_kyojitsu(data.get("kyojitsu_signs", []))
    data["hakkou_kan_netsu"] = derive_kanetsu(data.get("kanetsu_signs", []))
    data["hakkou_hyo_ri"]    = derive_hyori(data.get("hyori_signs", []))
    data["kqs_main"] = derive_kqs_main({
        "qixu_signs":   data.get("qixu_signs", []),
        "qitai_signs":  data.get("qitai_signs", []),
        "oketsu_signs": data.get("oketsu_signs", []),
        "kekkyos_signs":data.get("kekkyos_signs", []),
        "suitai_signs": data.get("suitai_signs", []),
        "inkyo_signs":  data.get("inkyo_signs", []),
    })

    rec_id = str(uuid.uuid4())

    # AI判定
    assessment = llm_assess_full(data)

    # エラー時でもテンプレが壊れない最小スキーマ
    if "error" in assessment:
        assessment = {
            "chosen": "",
            "candidates": [],
            "axes": {"sho": ""},
            "qxs": {},
            "patient_summary": "",
            "chief_note": assessment["error"],  # 画面上部に理由表示
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
    # ローカル実行用。Render では gunicorn を使います。
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)