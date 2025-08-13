
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

# 設問票と主訴マップ
with (APP_DIR / "ai_kampo_questionnaire.json").open("r", encoding="utf-8") as f:
    QUESTIONNAIRE = json.load(f)
with (APP_DIR / "complaint_map.json").open("r", encoding="utf-8") as f:
    COMPLAINT_MAP = json.load(f)

app = Flask(__name__)

def now_iso() -> str:
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).isoformat(timespec="seconds")

def read_all_records() -> List[Dict[str, Any]]:
    recs = []
    for p in DATA_DIR.glob("*.json"):
        try:
            with p.open("r", encoding="utf-8") as f:
                recs.append(json.load(f))
        except Exception:
            continue
    recs.sort(key=lambda x: x.get("submitted_at",""), reverse=True)
    return recs

# ---- 1段目：主訴から候補プールを作る ----
def build_candidate_pool_from_complaint(text: str) -> List[str]:
    t = text or ""
    pool: List[str] = []
    seen = set()
    for domain, spec in COMPLAINT_MAP.items():
        kws = spec.get("keywords", [])
        if any(kw in t for kw in kws):
            for f in spec.get("prefer", []):
                if f not in seen:
                    pool.append(f)
                    seen.add(f)
    if not pool:
        # 何もマッチしなかった場合のデフォルト
        defaults = ["補中益気湯","六君子湯","桂枝茯苓丸","葛根湯","荊芥連翹湯","清上防風湯","平胃散","半夏瀉心湯"]
        for f in defaults:
            if f not in seen:
                pool.append(f); seen.add(f)
    return pool[:8]

# ---- 2段目：簡易スコアリング（OpenAIキーがあれば将来置換可） ----
def simple_assess(form: Dict[str, Any]) -> Dict[str, Any]:
    chief = (form.get("chief_complaint") or "")
    kyo = "虚" if ("疲" in chief or str(form.get("kyo_jitsu","")).startswith("虚")) else "中間"
    heat = "寒" if str(form.get("cold_heat","")).startswith("冷") else ("熱" if "ほて" in str(form.get("cold_heat","")) else "中間")
    qi = "気滞" if ("張" in chief or form.get("ki_stagnation")) else ("気虚" if form.get("ki_deficiency") else "正常")
    xue = "瘀血" if form.get("yu_xue") else ("血虚" if form.get("blood_def") else "正常")
    sui = "水滞" if form.get("sui_ret") else "正常"

    # 候補群
    pool = build_candidate_pool_from_complaint(chief)
    # 各方剤のベース点
    formulas = {name: 0 for name in pool}
    # ドメイン別ブースト（皮膚→熱/油/睡眠など）
    skin_set = {"清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"}
    if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]):
        for k in formulas:
            if k in skin_set:
                formulas[k] += 6
    if qi == "気虚":
        formulas["補中益気湯"] = formulas.get("補中益気湯", 0) + 2
    if xue == "瘀血":
        formulas["桂枝茯苓丸"] = formulas.get("桂枝茯苓丸", 0) + 2
    if sui == "水滞":
        formulas["五苓散"] = formulas.get("五苓散", 0) + 2
    if heat == "熱":
        formulas["竹葉石膏湯"] = formulas.get("竹葉石膏湯", 0) + 2

    ranked = sorted(formulas.items(), key=lambda x: x[1], reverse=True)
    top3 = [k for k,_ in ranked[:3]]

    explain_map = {
        "清上防風湯":"顔のブツブツ・赤み・炎症に。熱をさまし皮膚の炎症を鎮めます。",
        "荊芥連翹湯":"ニキビ・吹き出物などの化膿傾向に。",
        "十味敗毒湯":"化膿性の皮膚症状・湿疹・蕁麻疹に。",
        "消風散":"かゆみの強い湿疹に。ジュクジュクにも。",
        "黄連解毒湯":"強い熱感・赤み・のぼせ傾向に。",
        "温清飲":"血熱＋瘀血の皮膚傾向に。",
        "補中益気湯":"疲れやすい・食欲低下などの気虚に。",
        "六君子湯":"胃もたれ・軟便の気虚＋痰湿に。",
        "桂枝茯苓丸":"刺すような痛み・しこり・瘀斑。瘀血傾向のときに。",
        "葛根湯":"首肩のこわばりなど急性の張りに。温めて巡りを助けます。",
        "五苓散":"口渇・尿少・むくみ・頭重に。",
        "竹葉石膏湯":"ほてり・口渇・だるさ同時のときに。",
        "半夏瀉心湯":"みぞおちのつかえ・胃腸不和に。",
        "平胃散":"胃もたれ・舌苔厚い・湿の停滞に。"
    }

    def candidate_block(name: str, score: float) -> Dict[str, Any]:
        skin = name in skin_set
        foods_good = ["はとむぎ","緑豆","ドクダミ茶"] if skin else ["ねぎ","しょうが","玉ねぎ"]
        foods_avoid = ["揚げ物","辛味の強い料理","甘味過多"] if skin else ["冷たい飲料","甘味過多"]
        lifestyle = (["辛味・油の摂り過ぎを控える","十分な睡眠"] if skin else
                     ["温かい飲み物","十分な睡眠"])
        return {
            "name": name,
            "score": float(score),
            "pharmacist_tip": "主訴と体質を加味した候補です。",
            "script": {"explain": explain_map.get(name, ""), "watch": ""},
            "lifestyle": lifestyle,
            "foods_good": foods_good,
            "foods_avoid": foods_avoid,
            "counsel_points": (["睡眠・食事・月経と皮膚の関係"] if skin else ["痛みの質・時間帯","冷え/天候での増悪"]),
            "ai_reason": "ルールベースの簡易スコアリング"
        }

    cands = [candidate_block(n, s) for n,s in ranked[:3]]
    assessment = {
        "chosen": cands[0]["name"] if cands else "",
        "candidates": cands,
        "axes": {"jitsu_kyo": kyo, "kan_netsu": heat, "hyo_ri": str(form.get('hyou_ri',''))},
        "qxs": {"qi": qi, "xue": xue, "sui": sui},
        "patient_summary": f"体のバランスは『{kyo}・{heat}』傾向。気血水では『{qi}/{xue}/{sui}』が示唆されます。主訴を優先して候補を提示しています。",
        "chief_note": "主訴を優先してスコア補正しています。",
        "diet": (["はとむぎ","緑豆","ドクダミ茶"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["生姜スープ","陳皮茶","玉ねぎ"]),
        "lifestyle": (["十分な睡眠","肌への強い刺激を避ける"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["45分に1回立つ","首肩の温罨法","深い呼吸"]),
        "topics": (["皮膚と食事・睡眠の関係"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["気のめぐりと肩こり","睡眠と回復力"])
    }
    return assessment

@app.get("/")
def index():
    return render_template("index.html", q=QUESTIONNAIRE)

@app.post("/submit")
def submit():
    data: Dict[str, Any] = {}
    # 受け取れるものは全て文字列なので型を合わせる
    for sec in QUESTIONNAIRE.get("sections", []):
        for q in sec.get("questions", []):
            qid = q.get("id")
            if not qid:
                continue
            if q.get("type") == "boolean":
                data[qid] = (request.form.get(qid) == "on")
            else:
                val = (request.form.get(qid) or "").strip()
                data[qid] = val
    rec_id = str(uuid.uuid4())
    assessment = simple_assess(data)
    record = {
        "id": rec_id,
        "submitted_at": now_iso(),
        "patient": {
            "name": data.get("name",""),
            "age": data.get("age",""),
            "sex": data.get("gender",""),
            "region": data.get("region",""),
            "chief_complaint": data.get("chief_complaint","")
        },
        "ai_assessment": assessment,
        "raw": data
    }
    with (DATA_DIR / f"{rec_id}.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return redirect(url_for("detail", rec_id=rec_id))

@app.get("/record/<rec_id>")
def detail(rec_id: str):
    p = DATA_DIR / f"{rec_id}.json"
    if not p.exists():
        abort(404)
    with p.open("r", encoding="utf-8") as f:
        record = json.load(f)
    return render_template("detail.html", data=record)

@app.get("/admin")
def admin():
    recs = read_all_records()
    return render_template("admin.html", recs=recs)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
