
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, json, uuid, datetime as dt, traceback
from pathlib import Path
from typing import Any, Dict, List
from flask import Flask, render_template, request, redirect, url_for, abort

APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/kanpo_ai"))
DATA_DIR = DATA_ROOT / "data"
for d in (DATA_ROOT, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ===== Flask =====
app = Flask(__name__, static_folder="static", static_url_path="/static")

# ===== Data files =====
with (APP_DIR / "ai_kampo_questionnaire.json").open("r", encoding="utf-8") as f:
    QUESTIONNAIRE = json.load(f)
with (APP_DIR / "complaint_map.json").open("r", encoding="utf-8") as f:
    COMPLAINT_MAP = json.load(f)

# ===== OpenAI client (v1) =====
from openai import OpenAI
import httpx
def create_openai_client():
    api_key = os.getenv("OPENAI_API_KEY")
    proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
    if proxy:
        return OpenAI(api_key=api_key, http_client=httpx.Client(proxies=proxy, follow_redirects=True))
    return OpenAI(api_key=api_key)

# ===== Helpers =====
def build_complaint_profile(text: str) -> Dict[str, Any]:
    t = (text or "").strip()
    for dom, spec in COMPLAINT_MAP.items():
        kws = spec.get("keywords", [])
        if any(kw in t for kw in kws):
            return {"domain": dom, "prefer": spec.get("prefer", [])}
    return {"domain": "general", "prefer": []}

def build_candidate_pool_from_complaint(text: str) -> List[str]:
    return build_complaint_profile(text).get("prefer", [])[:5]

def infer_constitution(form: Dict[str, Any]) -> Dict[str, bool]:
    # 最低限のフラグ（八綱・気血水）
    cold_heat = str(form.get("cold_heat",""))
    kyo_jitsu = str(form.get("kyo_jitsu",""))
    return {
        "cold": cold_heat.startswith("冷"),
        "heat": cold_heat.startswith("暑") or "ほて" in cold_heat,
        "weak": kyo_jitsu.startswith("虚"),
        "strong": kyo_jitsu.startswith("実"),
    }

def stage2_llm_selection(pool: List[str], form: Dict[str, Any]) -> Dict[str, Any]:
    """LLM使用（APIキーがある場合）/ ルールベース（フォールバック）"""
    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        try:
            client = create_openai_client()
            sys_prompt = (
                "あなたは漢方薬局のベテラン薬剤師です。"
                "ステージ1の候補（allowed_candidates）から、体質（八綱/気血水/舌/脈/生活）と主訴を加味してTop3を選定。"
                "各候補には短い理由（主訴との関係）を付けてください。JSONで返します。"
            )
            payload = {
                "form": form,
                "allowed_candidates": pool,
                "complaint_profile": build_complaint_profile(form.get('chief_complaint','')),
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
                })
            chosen = parsed.get("chosen") or (cands[0]["name"] if cands else (pool[0] if pool else ""))
            return {
                "chosen": chosen,
                "candidates": cands,
                "patient_summary": parsed.get("patient_summary",""),
                "complaint_sections": parsed.get("complaint_sections", []),
                "foods_good": parsed.get("foods_good", []),
                "foods_avoid": parsed.get("foods_avoid", []),
                "topics": parsed.get("topics", []),
                "chief_note": parsed.get("chief_note",""),
            }
        except Exception as e:
            print("LLM stage failed:", e)
            traceback.print_exc()

    # ---- ルールベース ----
    flags = infer_constitution(form)
    base = ["補中益気湯","六君子湯","当帰芍薬散","五苓散","真武湯","人参湯",
            "清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"]
    scores = {n:0.0 for n in base}
    if flags["cold"]:
        for n in ["人参湯","真武湯","補中益気湯"]: scores[n]+=2.0
    if flags["heat"]:
        for n in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"]: scores[n]+=2.0
    if flags["weak"]:
        for n in ["補中益気湯","六君子湯","当帰芍薬散"]: scores[n]+=1.2
    for n in pool: scores[n] = scores.get(n,0)+3.0
    top = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
    cands = [{"name": n, "score": s, "ai_reason":"体質と主訴からの推定", "script":{"explain":""}} for n,s in top]
    return {"chosen": (top[0][0] if top else ""), "candidates": cands}

def read_all_records() -> List[Dict[str, Any]]:
    recs = []
    for p in sorted(DATA_DIR.glob("*.json")):
        try:
            recs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    recs.sort(key=lambda r: r.get("submitted_at",""), reverse=True)
    return recs

# ===== Routes =====
@app.route("/")
def index():
    return render_template("index.html", q=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    try:
        form = {}
        for k, v in request.form.items():
            if isinstance(v, str) and v.lower() in ("true","on","1","yes"):
                form[k] = True
            else:
                form[k] = v
        form["chief_complaint"] = request.form.get("chief_complaint","")

        pool = build_candidate_pool_from_complaint(form.get("chief_complaint",""))
        assessment = stage2_llm_selection(pool, form)
    except Exception as e:
        print("ERROR in /submit:", e)
        traceback.print_exc()
        assessment = {"chosen":"", "candidates":[], "patient_summary":"", "complaint_sections":[]}

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
