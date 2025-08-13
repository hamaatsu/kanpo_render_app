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

def now_iso() -> str:
    return dt.datetime.utcnow().isoformat() + "Z"

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

def build_complaint_profile(text: str) -> dict:
    """Map chief complaint text to domain via COMPLAINT_MAP."""
    t = text or ""
    prof = {"domain":"general","tags":[]}
    for dom, spec in COMPLAINT_MAP.items():
        if any(kw in t for kw in spec.get("keywords", [])):
            prof["domain"] = dom
            break
    return prof

def complaint_rerank(assessment: dict, form: dict) -> dict:
    """Ensure at least one domain-prefer formula is in Top3 and boost them strongly."""
    try:
        prof = build_complaint_profile(form.get("chief_complaint",""))
        dom = prof.get("domain","general")
        mapping = COMPLAINT_MAP.get(dom, {})
        prefer = mapping.get("prefer", [])
        if not assessment:
            return assessment
        cands = assessment.get("candidates") or []
        boosted = []
        seen = set()
        for c in cands:
            s = float(c.get("score", 0))
            if c.get("name") in prefer:
                s += 6.0
                c["ai_reason"] = (c.get("ai_reason") or "") + "（主訴に直接対応）"
            boosted.append((s, c))
            seen.add(c.get("name"))
        if prefer and all(name not in seen for name in prefer):
            ins = {
                "name": prefer[0],
                "score": 6.0,
                "pharmacist_tip": "主訴に直接対応する処方。",
                "script": {"explain": ""},
                "lifestyle": [],
                "foods_good": [],
                "foods_avoid": [],
                "counsel_points": [],
                "ai_reason": "主訴に基づく優先候補"
            }
            boosted.append((6.0, ins))
        boosted.sort(key=lambda x: x[0], reverse=True)
        cands2 = [c for _, c in boosted][:3]
        assessment["candidates"] = cands2
        if cands2:
            assessment["chosen"] = cands2[0]["name"]
        # dermatology defaults
        if dom == "dermatology":
            diet = list({*assessment.get("diet", []), *mapping.get("diet", [])})
            avoid = mapping.get("avoid", [])
            ls = list({*assessment.get("lifestyle", []), "辛味・油の摂り過ぎを控える", "十分な睡眠", "肌への強い刺激を避ける"})
            assessment["diet"] = diet + (["（控える）"] + avoid if avoid else [])
            assessment["lifestyle"] = ls
            assessment["chief_note"] = "主訴（皮膚症状）を最優先に再ランクしました。"
        return assessment
    except Exception:
        return assessment

# Fallback assessment when no OpenAI or error
def simple_assess(form: Dict[str, Any]) -> Dict[str, Any]:
    chief = (form.get("chief_complaint") or "").lower()
    kyo = "虚" if ("疲" in chief or str(form.get("kyo_jitsu","")).startswith("虚")) else "中間"
    heat = "寒" if str(form.get("cold_heat","")).startswith("冷") else ("熱" if "ほて" in str(form.get("cold_heat","")) else "中間")
    qi = "気滞" if ("張" in chief or form.get("ki_stagnation")) else ("気虚" if form.get("ki_deficiency") else "正常")
    xue = "瘀血" if form.get("yu_xue") else ("血虚" if form.get("blood_def") else "正常")
    sui = "水滞" if form.get("sui_ret") else "正常"

    formulas = {"葛根湯":0,"疎経活血湯":0,"川芎茶調散":0,"釣藤散":0,"桂枝茯苓丸":0,
                "補中益気湯":0,"六君子湯":0,"当帰芍薬散":0,"五苓散":0,"真武湯":0,"人参湯":0,"竹葉石膏湯":0,
                "清上防風湯":0,"荊芥連翹湯":0,"十味敗毒湯":0,"消風散":0,"黄連解毒湯":0,"温清飲":0}
    if "肩" in chief:
        for k in ["葛根湯","疎経活血湯","川芎茶調散","釣藤散","桂枝茯苓丸"]:
            formulas[k] += 3
    # skin keywords
    if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]):
        for k in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"]:
            formulas[k] += 6
    if qi=="気虚": formulas["補中益気湯"] += 2
    if xue=="瘀血": formulas["桂枝茯苓丸"] += 2
    if sui=="水滞": formulas["五苓散"] += 2
    if heat=="熱": formulas["竹葉石膏湯"] += 2

    ranked = sorted(formulas.items(), key=lambda x: x[1], reverse=True)
    top3 = [k for k,_ in ranked[:3]]
    scripts = {
        "葛根湯":"首肩のこわばりなど、急性の筋肉の張りに。体を温めて巡りを助けます。",
        "疎経活血湯":"慢性的なこわばりや冷えで悪化する痛みに。血行促進をねらいます。",
        "川芎茶調散":"肩こりを伴う頭痛・気象病に。気血の巡りを助けます。",
        "釣藤散":"肩こり＋頭痛・めまい・イライラに。中高年の上衝に。",
        "桂枝茯苓丸":"刺すような痛み・しこり・瘀斑。瘀血傾向のときに。",
        "補中益気湯":"疲れやすい・食欲低下などの気虚に。",
        "六君子湯":"胃もたれ・軟便の気虚＋痰湿に。",
        "当帰芍薬散":"冷え・むくみ・立ちくらみ傾向に。",
        "五苓散":"口渇・尿少・むくみ・頭重に。",
        "真武湯":"冷え＋めまい・むくみの水滞に。",
        "人参湯":"冷えによる腹痛/下痢などの虚寒に。",
        "竹葉石膏湯":"ほてり・口渇・だるさ同時のときに。",
        "清上防風湯":"顔のブツブツ・赤み・炎症に。余分な熱をさまし皮膚の炎症を鎮めます。",
        "荊芥連翹湯":"ニキビ・吹き出物などの化膿傾向に。",
        "十味敗毒湯":"化膿性の皮膚症状・湿疹・蕁麻疹に。",
        "消風散":"かゆみの強い湿疹、湿熱＆風熱に。",
        "黄連解毒湯":"強い熱感・赤み・炎症に。",
        "温清飲":"血熱＋瘀血傾向の皮膚症状に。"
    }
    cands = []
    for i, name in enumerate(top3):
        cands.append({
            "name": name,
            "score": ranked[i][1],
            "pharmacist_tip": scripts.get(name,""),
            "script": {"explain": scripts.get(name,""), "watch": ""},
            "lifestyle": ["辛味・油の摂り過ぎを控える" if name in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"] else "温かい飲み物",
                           "十分な睡眠"],
            "foods_good": ["はとむぎ","緑豆","ドクダミ茶"] if name in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"] else ["ねぎ","しょうが","玉ねぎ"],
            "foods_avoid": ["揚げ物","辛味の強い料理","甘味過多"] if name in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"] else ["冷たい飲料","甘味過多"],
            "counsel_points": ["睡眠・食事・月経と皮膚の関係"] if name in ["清上防風湯","荊芥連翹湯","十味敗毒湯","消風散","黄連解毒湯","温清飲"] else ["痛みの質・時間帯","冷え/天候での増悪"]
        })
    assessment = {
        "chosen": cands[0]["name"] if cands else "",
        "candidates": cands,
        "axes": {"jitsu_kyo": kyo, "kan_netsu": heat, "hyo_ri": str(form.get('hyou_ri',''))},
        "qxs": {"qi": qi, "xue": xue, "sui": sui},
        "patient_summary": f"体のバランスとしては『{kyo}・{heat}』傾向で、気血水では『{qi}/{xue}/{sui}』が示唆されます。主訴を重視して提案しています。",
        "chief_note": "主訴を優先してスコア補正しています。",
        "diet": ["はとむぎ","緑豆","ドクダミ茶"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["生姜スープ","陳皮茶","玉ねぎ"],
        "lifestyle": ["十分な睡眠","肌への強い刺激を避ける"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["45分に1回立つ","首肩の温罨法","深い呼吸"],
        "topics": ["皮膚と食事・睡眠の関係"] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else ["気のめぐりと肩こり","睡眠と回復力"],
        "complaint_sections": [{
            "title":"主訴に直結するアドバイス",
            "background":"皮膚の炎症と皮脂バランス・睡眠不足・食事（油/糖）が関連。",
            "do":["十分な睡眠","洗顔はこすらずぬるま湯","汗をかいたら早めに洗う"],
            "foods_good":["はとむぎ","緑豆","ドクダミ茶","セロリ","大根"],
            "foods_avoid":["揚げ物","辛味","甘味過多","アルコール"],
            "points":["メイク/整髪料の刺激チェック","月経周期との関連確認"],
            "acupoints":["合谷","曲池","太衝"],
            "danger":["高熱を伴う広範囲発疹","蜂窩織炎を疑う痛み/腫れ"]
        }] if any(kw in chief for kw in ["ぶつぶつ","ブツブツ","にきび","ﾆｷﾋﾞ","ニキビ","発疹","湿疹","肌荒れ","赤み"]) else [{
            "title":"主訴に直結するアドバイス",
            "background":"巡りの低下や冷えが背景にあります。",
            "do":["肩甲骨はがし","温湿布","深呼吸"],
            "foods_good":["陳皮","生姜","ねぎ"],
            "foods_avoid":["冷たい飲料","脂っこいもの"],
            "points":["長時間の同一姿勢を避ける","湯船で温める"],
            "acupoints":["肩井","風池","合谷"],
            "danger":["片側の脱力/しびれが出たら受診"]
        }]
    }
    assessment = complaint_rerank(assessment, form)
    return assessment

def call_openai(form: Dict[str, Any], sex: str) -> Dict[str, Any]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return simple_assess(form)
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        sys_prompt = (
            "あなたは漢方薬局のベテラン薬剤師です。"
            "【最重要】主訴（chief_complaint）を最優先に評価し、必ず候補Top3のうち最低1つは主訴に直接対応する処方を含めてください。"
            "問診（八綱：寒熱・虚実・表裏、気血水、舌・脈・顔色、主訴、生活）を総合し、証を決定してください。"
            "出力は JSON。各候補には『主訴との関係』を明記。患者向け説明は3〜6文、平易な日本語で。薬膳（推奨/控え）、生活、面談深掘り、赤旗（受診目安）も含める。"
            "男性には妊娠関連の注意は出さないでください。"
            "皮膚症状の場合（complaint_profile.domain=dermatology）は、清上防風湯/荊芥連翹湯/十味敗毒湯/消風散/黄連解毒湯/温清飲などから最低1つを候補に含めること。"
        )
        user_payload = {
            "form": form,
            "complaint_profile": build_complaint_profile(form.get("chief_complaint",""))
        }
        model = os.getenv("OPENAI_MODEL","gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model, temperature=0.3,
            messages=[{"role":"system","content":sys_prompt},
                      {"role":"user","content":json.dumps(user_payload, ensure_ascii=False)}]
        )
        content = resp.choices[0].message.content
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"llm_text": content}
        cands = []
        for it in (parsed.get("candidates") or []):
            name = it.get("name","")
            cands.append({
                "name": name,
                "score": it.get("score", 1.0),
                "pharmacist_tip": it.get("pharmacist_tip",""),
                "script": {"explain": it.get("patient_explain",""), "watch": it.get("watch","")},
                "lifestyle": it.get("lifestyle", []),
                "foods_good": it.get("foods_good", []),
                "foods_avoid": it.get("foods_avoid", []),
                "counsel_points": it.get("counsel_points", []),
                "ai_reason": it.get("reason","")
            })
        assessment = {
            "chosen": (cands[0]["name"] if cands else ""),
            "candidates": cands,
            "axes": parsed.get("axes", {}),
            "qxs": parsed.get("qxs", {}),
            "patient_summary": parsed.get("patient_summary",""),
            "chief_note": parsed.get("chief_note",""),
            "diet": parsed.get("diet", []),
            "lifestyle": parsed.get("lifestyle", []),
            "topics": parsed.get("topics", []),
            "complaint_sections": parsed.get("complaint_sections", []),
            "llm_raw": parsed
        }
        # remove pregnancy warnings for non-female
        if (sex or "").lower() not in ["female","woman","女性","女"]:
            def _strip_preg(text: str) -> str:
                import re as _re
                return _re.sub(r"妊娠中[^。]*。?", "", text or "")
            assessment["patient_summary"] = _strip_preg(assessment.get("patient_summary",""))
            for c in assessment["candidates"]:
                if isinstance(c.get("script"), dict):
                    c["script"]["watch"] = _strip_preg(c["script"].get("watch",""))
        assessment = complaint_rerank(assessment, form)
        return assessment
    except Exception as e:
        ass = simple_assess(form)
        ass["llm_error"] = f"{type(e).__name__}: {e}"
        return ass

@app.route("/")
def index():
    return render_template("index.html", q=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    data = {}
    for sec in QUESTIONNAIRE["sections"]:
        for q in sec["questions"]:
            val = request.form.get(q["id"], "").strip()
            if q["type"] == "boolean":
                data[q["id"]] = (request.form.get(q["id"]) == "on")
            else:
                data[q["id"]] = val
    rec_id = str(uuid.uuid4())
    sex = data.get("gender","")
    assessment = call_openai(data, sex)

    record = {
        "id": rec_id,
        "submitted_at": now_iso(),
        "patient": {
            "name": data.get("name",""),
            "age": data.get("age",""),
            "sex": data.get("gender",""),
            "region": data.get("region",""),
            "chief_complaint": data.get("chief_complaint",""),
        },
        "ai_assessment": assessment,
        "raw": data
    }
    with (DATA_DIR/f"{rec_id}.json").open("w", encoding="utf-8") as f:
        json.dump(record, f, ensure_ascii=False, indent=2)
    return redirect(url_for("detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
def detail(rec_id: str):
    p = DATA_DIR/f"{rec_id}.json"
    if not p.exists():
        abort(404)
    with p.open("r", encoding="utf-8") as f:
        record = json.load(f)
    return render_template("detail.html", data=record)

@app.route("/admin")
def admin():
    recs = read_all_records()
    return render_template("admin.html", recs=recs)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=False)
