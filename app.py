
# -*- coding: utf-8 -*-
import os, json, uuid, datetime, re
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, abort
from markupsafe import escape

APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/kanpo_ai"))
UPLOAD_DIR = DATA_ROOT / "uploads"
DATA_DIR = DATA_ROOT / "data"
for d in (UPLOAD_DIR, DATA_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Load questionnaire
QUESTIONNAIRE_PATH = APP_DIR / "ai_kampo_questionnaire.json"
with QUESTIONNAIRE_PATH.open(encoding="utf-8") as f:
    QUESTIONNAIRE = json.load(f)

app = Flask(__name__)

# --- Helpers ---
def now_iso():
    return datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc).isoformat()

def read_records():
    items = []
    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            items.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            continue
    return items

def save_record(rec):
    rid = rec["id"]
    (DATA_DIR / f"{rid}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

def _filter_script_for_sex(script, sex):
    if not isinstance(script, dict):
        return script
    w = script.get("watch", "") or ""
    if (sex or "").lower() not in ["female", "woman", "女性", "女"]:
        w = re.sub(r"妊娠中[^。]*。?", "", w)
    return {**script, "watch": w.strip()}

def call_openai_assess(payload):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None, "OPENAI_API_KEY is missing"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        system = (
            "あなたは漢方薬局のベテラン薬剤師です。"
            "与えられた問診（八綱：寒熱/虚実/表裏＋気血水＋舌診＋脈診＋顔色＋主訴）を総合評価して『証』を決定し、"
            "漢方薬の候補Top3をJSONで返してください。"
            "必ず以下の構造で、JSONのみを出力:
"
            "{\n"
            "  \"axes\": { \"jitsu_kyo\": \"虚|実|中間\", \"kan_netsu\": \"寒|熱|中間\", \"hyo_ri\": \"表|裏|不明\" },\n"
            "  \"qxs\": { \"qi\": \"deficiency|stagnation|rebellion|normal\", \"xue\": \"deficiency|stasis|normal\", \"sui\": \"retention|deficiency|normal\" },\n"
            "  \"candidates\": [\n"
            "    { \"name\": \"...\", \"reason\": \"主訴と証に基づく理由\", \"patient_explain\": \"3-6文のやさしい説明\", \"foods_good\":[], \"foods_avoid\":[], \"lifestyle\":[], \"counsel_points\":[] },\n"
            "    { ... },\n"
            "    { ... }\n"
            "  ],\n"
            "  \"chosen\": \"上位の方剤名\",\n"
            "  \"patient_summary\": \"主訴に直結する3-6文の説明（今日からの具体策を含む）\",\n"
            "  \"red_flags\": [\"受診を勧めるべきサイン\"],\n"
            "  \"topics\": [\"会話のきっかけ\"],\n"
            "  \"diet\": [\"薬膳食材\"],\n"
            "  \"lifestyle\": [\"日常生活のアドバイス\"]\n"
            "}\n"
            "制約: 必ず候補は3つ。男性には妊娠関連の注意は出さない。"
        )
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        messages = [
            {"role":"system", "content": system},
            {"role":"user", "content": json.dumps(payload, ensure_ascii=False)}
        ]
        resp = client.chat.completions.create(model=model, temperature=0.3, messages=messages)
        content = resp.choices[0].message.content
        try:
            data = json.loads(content)
        except Exception:
            # Try to extract JSON via regex
            import re as _re
            m = _re.search(r'\{[\s\S]*\}', content)
            if m:
                data = json.loads(m.group(0))
            else:
                return None, f"LLM returned non-JSON: {content[:200]}"
        return data, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"

# --- Routes ---
@app.route("/")
def index():
    return render_template("index.html", questionnaire=QUESTIONNAIRE)

@app.route("/submit", methods=["POST"])
def submit():
    form = request.form.to_dict()
    # Build payload for AI from questionnaire keys only
    answers = {}
    for sec in QUESTIONNAIRE.get("sections", []):
        for q in sec.get("questions", []):
            qid = q.get("id")
            if not qid: 
                continue
            answers[qid] = form.get(qid, "")

    rec_id = str(uuid.uuid4())
    sex = answers.get("gender","")
    payload = {
        "meta": {
            "id": rec_id,
            "submitted_at": now_iso()
        },
        "patient": {
            "name": answers.get("name",""),
            "age": answers.get("age",""),
            "sex": answers.get("gender",""),
            "region": answers.get("region","")
        },
        "chief_complaint": answers.get("chief_complaint",""),
        "onset": answers.get("onset",""),
        "hakkou": {
            "cold_heat": answers.get("cold_heat",""),
            "kyo_jitsu": answers.get("kyo_jitsu",""),
            "hyou_ri": answers.get("hyou_ri","")
        },
        "qxs_input": {
            "ki_deficiency": answers.get("ki_deficiency",""),
            "ki_stagnation": answers.get("ki_stagnation",""),
            "blood_color": answers.get("blood_color",""),
            "lip_nail_color": answers.get("lip_nail_color",""),
            "menstrual_info": answers.get("menstrual_info","") if sex in ["女性","female","Female"] else "",
            "water_retention": answers.get("water_retention","")
        },
        "tongue": {
            "color": answers.get("tongue_color",""),
            "coating": answers.get("tongue_coating",""),
            "shape": answers.get("tongue_shape","")
        },
        "pulse": {
            "quality": answers.get("pulse_quality","")
        },
        "face": {
            "color": answers.get("face_color","")
        },
        "lifestyle": {
            "sleep": answers.get("sleep",""),
            "appetite": answers.get("appetite",""),
            "bowel": answers.get("bowel",""),
            "sweating": answers.get("sweating","")
        },
        "pain": answers.get("pain","")
    }

    ai_data, err = call_openai_assess(payload)
    assessment = {}
    if ai_data and isinstance(ai_data, dict):
        # Filter pregnancy notes for male
        if (sex or "").lower() not in ["female","woman","女性","女"]:
            if "patient_summary" in ai_data and isinstance(ai_data["patient_summary"], str):
                ai_data["patient_summary"] = re.sub(r"妊娠中[^。]*。?", "", ai_data["patient_summary"])
            for c in ai_data.get("candidates", []):
                if isinstance(c, dict) and "patient_explain" in c:
                    c["patient_explain"] = re.sub(r"妊娠中[^。]*。?", "", c.get("patient_explain",""))
        assessment = ai_data
    else:
        # Fallback minimal assessment
        cc = payload["chief_complaint"]
        candidates = []
        if "肩" in cc or "首" in cc:
            candidates = [
                {"name":"葛根湯","reason":"項背部のこわばりと悪寒に。","patient_explain":"首肩のこわばりに対応します。体を温めて巡りを助けます。","foods_good":["生姜","ねぎ"],"foods_avoid":["冷飲"],"lifestyle":["温罨法","軽い体操"],"counsel_points":["寒気の有無","発汗の有無"]},
                {"name":"疎経活血湯","reason":"慢性の肩こりや冷えで悪化。","patient_explain":"血行を促し、こわばりを和らげます。","foods_good":["黒きくらげ"],"foods_avoid":[],"lifestyle":["入浴"],"counsel_points":[]},
                {"name":"桂枝茯苓丸","reason":"瘀血所見がある肩こりに。","patient_explain":"血の滞りをさばきます。","foods_good":["玉ねぎ","酢"],"foods_avoid":[],"lifestyle":["適度な運動"],"counsel_points":[]}
            ]
        else:
            candidates = [
                {"name":"六君子湯","reason":"胃もたれ・食欲不振に。","patient_explain":"胃腸を助けます。","foods_good":["山芋"],"foods_avoid":["冷飲"],"lifestyle":["少量頻回"],"counsel_points":[]},
                {"name":"補中益気湯","reason":"だるさと気虚に。","patient_explain":"気を補います。","foods_good":["鶏肉","なつめ"],"foods_avoid":[],"lifestyle":["休息"],"counsel_points":[]},
                {"name":"当帰芍薬散","reason":"むくみ・冷えに。","patient_explain":"血と水のバランスを整えます。","foods_good":["黒豆"],"foods_avoid":[],"lifestyle":["保温"],"counsel_points":[]}
            ]
        assessment = {
            "axes":{"jitsu_kyo":"chukan","kan_netsu":"neutral","hyo_ri":"unknown"},
            "qxs":{"qi":"normal","xue":"normal","sui":"normal"},
            "candidates": candidates,
            "chosen": candidates[0]["name"],
            "patient_summary":"主訴に合わせて生活と食事を整えましょう。",
            "diet":["山芋","なつめ","黒きくらげ"],
            "lifestyle":["体を冷やさない","軽い運動"],
            "topics":["生活リズムの見直し"]
        }

    # Compose record
    record = {
        "id": rec_id,
        "submitted_at": payload["meta"]["submitted_at"],
        "patient": {
            "name": payload["patient"]["name"],
            "age": payload["patient"]["age"],
            "sex": payload["patient"]["sex"],
            "region": payload["patient"]["region"],
            "chief_complaint": payload["chief_complaint"]
        },
        "ai_assessment": assessment,
        "payload": payload
    }
    save_record(record)
    return redirect(url_for("detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
def detail(rec_id):
    p = DATA_DIR / f"{escape(rec_id)}.json"
    if not p.exists():
        abort(404)
    data = json.loads(p.read_text(encoding="utf-8"))
    return render_template("detail.html", data=data)

@app.route("/admin")
def admin():
    items = read_records()
    return render_template("admin.html", items=items)

# Healthcheck
@app.route("/healthz")
def healthz():
    return "ok", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=True)
