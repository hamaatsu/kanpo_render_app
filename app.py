
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, uuid, datetime as dt
from pathlib import Path
from typing import Any, Dict, List
from flask import Flask, render_template, request, redirect, url_for, abort

APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/kanpo_ai"))
UPLOAD_DIR = DATA_ROOT / "uploads"
DATA_DIR = DATA_ROOT / "data"
for d in (DATA_ROOT, UPLOAD_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Load questionnaire and complaint map
with (APP_DIR / "ai_kampo_questionnaire.json").open("r", encoding="utf-8") as f:
    QUESTIONNAIRE = json.load(f)
COMPLAINT_MAP = json.loads((APP_DIR/"complaint_map.json").read_text(encoding="utf-8"))

app = Flask(__name__)

# --- Constitution extraction (simple) ---
def infer_constitution(form: Dict[str, Any]) -> Dict[str, bool]:
    flags = {
        "heat": str(form.get("cold_heat","")).startswith("暑") or "ほて" in str(form.get("cold_heat","")),
        "cold": str(form.get("cold_heat","")).startswith("冷"),
        "weak": str(form.get("kyo_jitsu","")).startswith("虚"),
        "strong": str(form.get("kyo_jitsu","")).startswith("実"),
        "qi_def": bool(form.get("ki_deficiency")),
        "qi_stag": bool(form.get("ki_stagnation")),
        "xue_def": bool(form.get("blood_def")),
        "yu_xue": bool(form.get("yu_xue")),
        "sui_ret": bool(form.get("sui_ret")),
    }
    return flags

def build_complaint_profile(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    for dom, spec in COMPLAINT_MAP.items():
        if any(kw in t for kw in spec.get("keywords", [])):
            return {"domain": dom, "prefer": spec.get("prefer", [])}
    return {"domain": "general", "prefer": []}

def build_candidate_pool_from_complaint(text: str) -> List[str]:
    prof = build_complaint_profile(text)
    return prof.get("prefer", [])[:5]

# --- Stage 2 (LLM optional) ---
def stage2_llm_selection(pool: List[str], form: Dict[str, Any]) -> Dict[str, Any]:
    """If OPENAI_API_KEY is set, ask LLM to score; otherwise fall back to rule-based scoring."""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)
            sys_prompt = (
                "あなたは漢方薬局のベテラン薬剤師です。"
                "【二段階選定】ステージ1の候補（allowed_candidates）から、"
                "体質（八綱/気血水/舌/脈/生活）と主訴を加味してTop3を選定。"
                "各候補には『主訴との関係』を1行で。JSONで返すこと。"
                "男性には妊娠関連の注意は出さないでください。"
            )
            payload = {
                "form": form,
                "allowed_candidates": pool,
                "complaint_profile": build_complaint_profile(form.get("chief_complaint","")),
                "constitution_flags": infer_constitution(form)
            }
            model = os.getenv("OPENAI_MODEL","gpt-4o-mini")
            resp = client.chat.completions.create(
                model=model, temperature=0.2,
                messages=[{"role":"system","content":sys_prompt},
                          {"role":"user","content":json.dumps(payload, ensure_ascii=False)}]
            )
            content = resp.choices[0].message.content
            parsed = json.loads(content)
            cands = []
            for it in (parsed.get("candidates") or []):
                cands.append({
                    "name": it.get("name",""),
                    "score": float(it.get("score", 1.0)),
                    "ai_reason": it.get("ai_reason") or "",
                    "script": it.get("script") or {"explain": ""},
                    "lifestyle": it.get("lifestyle") or [],
                    "foods_good": it.get("foods_good") or [],
                    "foods_avoid": it.get("foods_avoid") or [],
                    "counsel_points": it.get("counsel_points") or []
                })
            if not cands and pool:
                cands = [{"name": n, "score": 1.0, "ai_reason": "主訴からの候補", "script": {"explain": ""},
                          "lifestyle": [], "foods_good": [], "foods_avoid": [], "counsel_points": []} for n in pool[:3]]
            chosen = parsed.get("chosen") or (cands[0]["name"] if cands else "")
            assessment = {
                "chosen": chosen,
                "candidates": cands,
                "patient_summary": parsed.get("patient_summary",""),
                "complaint_sections": parsed.get("complaint_sections", []),
                "foods_good": parsed.get("foods_good", []),
                "foods_avoid": parsed.get("foods_avoid", []),
                "topics": parsed.get("topics", []),
                "chief_note": parsed.get("chief_note",""),
            }
            return assessment
        except Exception as e:
            # Fall through to rule-based if LLM fails
            print("LLM stage failed:", e)

    # --- Rule-based fallback ---
    flags = infer_constitution(form)
    base = ["補中益気湯","六君子湯","当帰芍薬散","五苓散","真武湯","人参湯","竹葉石膏湯",
            "清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"]
    scores = {n:0.0 for n in base}
    if flags["cold"]:
        for n in ["人参湯","真武湯","補中益気湯"]: scores[n]+=2.0
    if flags["heat"]:
        for n in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","竹葉石膏湯","温清飲"]: scores[n]+=2.0
    if flags["weak"]:
        for n in ["補中益気湯","六君子湯","当帰芍薬散"]: scores[n]+=1.5
    if flags["sui_ret"]:
        for n in ["五苓散","真武湯","六君子湯"]: scores[n]+=1.2
    if flags["yu_xue"]:
        for n in ["温清飲","当帰芍薬散"]: scores[n]+=1.0

    # Ensure pool items are boosted
    for n in pool: scores[n] = scores.get(n,0)+3.5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top3 = [n for n,_ in ranked[:3]]
    scripts = {
        "補中益気湯":"疲れやすい・倦怠感などの気虚に。",
        "六君子湯":"胃もたれ・食欲低下の気虚＋痰湿に。",
        "当帰芍薬散":"冷え・むくみ・立ちくらみ傾向に。",
        "五苓散":"口渇・尿少・むくみ・頭重に。",
        "真武湯":"冷え＋めまい・むくみの水滞に。",
        "人参湯":"冷えによる腹痛/下痢などの虚寒に。",
        "竹葉石膏湯":"ほてり・口渇・だるさ同時のときに。",
        "清上防風湯":"顔のブツブツ・赤み・炎症に。",
        "荊芥連翹湯":"ニキビ・吹き出物などの化膿傾向に。",
        "十味敗毒湯":"化膿性の皮膚症状・湿疹・蕁麻疹に。",
        "消風散":"かゆみの強い湿疹、湿熱＆風熱に。",
        "黄連解毒湯":"強い熱感・赤み・炎症に。",
        "温清飲":"血熱＋瘀血傾向の皮膚症状に。"
    }
    cands = [{
        "name": n,
        "score": scores.get(n,0.0),
        "ai_reason": "体質と主訴からの推定",
        "script": {"explain": scripts.get(n,"")},
        "lifestyle": [],
        "foods_good": [],
        "foods_avoid": [],
        "counsel_points": []
    } for n in top3]
    assessment = {"chosen": top3[0] if top3 else "", "candidates": cands}
    return assessment

def read_all_records() -> List[Dict[str, Any]]:
    recs = []
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    recs.sort(key=lambda r: r.get("submitted_at",""), reverse=True)
    return recs

@app.route("/")
def index():
    return render_template("index.html", q=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    # Collect form
    form = {k: (v if v != "true" else True) for k,v in request.form.items()}
    # chief complaint plain text
    form["chief_complaint"] = request.form.get("chief_complaint","")
    pool = build_candidate_pool_from_complaint(form.get("chief_complaint",""))
    assessment = stage2_llm_selection(pool, form)
    # build record
    rec_id = uuid.uuid4().hex[:10]
    record = {
        "id": rec_id,
        "submitted_at": dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
        "patient": {
            "name": form.get("name",""),
            "age": form.get("age",""),
            "sex": form.get("sex",""),
            "region": form.get("region",""),
            "chief_complaint": form.get("chief_complaint","")
        },
        "assessment": assessment,
        "form": form
    }
    (DATA_DIR/f"{rec_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("record_detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
def record_detail(rec_id):
    p = DATA_DIR/f"{rec_id}.json"
    if not p.exists():
        abort(404)
    return render_template("detail.html", data=json.loads(p.read_text(encoding="utf-8")))

@app.route("/admin")
def admin():
    return render_template("admin.html", recs=read_all_records())

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT","5000")), debug=False)
