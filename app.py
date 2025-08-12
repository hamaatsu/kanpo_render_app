# -*- coding: utf-8 -*-
import os, json, uuid, datetime, re
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, Response
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = APP_DIR / "uploads"
DATA_DIR = APP_DIR / "data"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DATA_DIR.mkdir(exist_ok=True, parents=True)

BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "admin")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "changeme")
SECRET_KEY = os.getenv("FLASK_SECRET", "dev")

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

def check_auth(u, p):
    return u == BASIC_AUTH_USERNAME and p == BASIC_AUTH_PASSWORD

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm=\"Restricted\"'} )
        return f(*args, **kwargs)
    return decorated

# ===== ヘルパ =====
def parse_chief(s):
    s = (s or "").strip()
    meta = {"throat":0,"head":0,"abdomen":0,"diarrhea":0,"constipation":0,"rain":0,"stuck":0,"pain":0}
    if "喉" in s or "のど" in s: meta["throat"]+=1
    if "頭" in s: meta["head"]+=1
    if "腹" in s or "お腹" in s: meta["abdomen"]+=1
    if "痛" in s: meta["pain"]+=1
    if "詰" in s or "つま" in s: meta["stuck"]+=1
    if "下痢" in s: meta["diarrhea"]+=1
    if "便秘" in s: meta["constipation"]+=1
    if "雨" in s or "気圧" in s or "低気圧" in s: meta["rain"]+=1
    return meta

def rule_advice(chief, sex):
    m = parse_chief(chief)
    if m["throat"] and m["stuck"]:
        return {
            "title":"喉のつかえ（梅核気/気滞＋痰湿）",
            "background":"ストレスや湿気で“気”が滞り、痰が絡むと喉の異物感が出ます。",
            "try_first":["温かい飲み物（生姜湯/ほうじ茶）","首肩ストレッチ","軽い発声（ハミング）"],
            "foods_good":["陳皮","生姜","紫蘇","はと麦"], "foods_avoid":["冷飲","油こい/乳製品多め"],
            "lifestyle":["除湿の活用","長時間前屈スマホを減らす"],
            "points":["合谷","列缺","天突"], "kampo_hint":"半夏厚朴湯を用いることあり",
            "careful":["嚥下困難・呼吸苦・発熱は受診"]
        }
    if m["head"] and m["pain"] and m["rain"]:
        return {
            "title":"雨の日の頭痛（湿×気滞）",
            "background":"湿で水の巡りが停滞し、首肩の張りと気の滞りが頭痛に。",
            "try_first":["はと麦茶（温）","首肩を温め軽く回す","湯船で軽く発汗"],
            "foods_good":["はと麦","生姜"], "foods_avoid":["冷飲","甘い/脂っこい"],
            "lifestyle":["気圧アプリで事前対策"], "points":["合谷","風池","太陽"],
            "careful":["突然の激痛/神経症状は受診"]
        }
    if m["diarrhea"]:
        return {
            "title":"下痢（脾胃の弱り/冷え・湿）",
            "background":"消化の火力が落ちている状態。冷飲や脂こい食で悪化。",
            "try_first":["白湯を少量ずつ","温かい汁物から食べ始める"],
            "foods_good":["山芋","大根","陳皮","生姜"], "foods_avoid":["氷飲料","揚げ物"],
            "lifestyle":["食後5〜10分の散歩"], "points":["中脘","足三里"],
            "careful":["血便/発熱は受診"]
        }
    if m["constipation"]:
        return {
            "title":"便秘（乾燥/気滞）","background":"水分不足と運動不足、気の停滞で悪化。",
            "try_first":["起床白湯","黒ごま・海藻を少量","腹式呼吸"], "foods_good":["黒ごま","海藻","きのこ"],
            "foods_avoid":["辛味過多","冷飲"], "lifestyle":["毎日同時刻のトイレ習慣"], "points":["天枢","大腸兪"],
            "careful":["血便/体重減少は受診"]
        }
    return None

def ai_generate_advice(patient, axes, qxs, vis, chosen_formula):
    if not OPENAI_API_KEY:
        return None, "APIキー未設定のためルールベースで対応"
    try:
        from openai import OpenAI
        # proxies など余計な引数は渡さない
        client = OpenAI(api_key=OPENAI_API_KEY)

        # ---- ここから安全なプロンプト組み立て（f文字列で {} を使わない）----
        chief = patient.get('chief_complaint', '')
        sex_ = patient.get('sex', '')

        prompt = (
            "あなたは漢方相談のカウンセラーです。以下の主訴と体質所見から、"
            "主訴に直結するアドバイスを日本語でJSON出力してください。\n"
            "制約：結論先出し・即実践できる提案・過度に一般論にせず主訴に寄り添う。"
            "男性の場合は月経言及なし。\n\n"
            "[入力]\n"
            f"主訴: {chief}\n"
            f"性別: {sex_}\n"
            f"八綱: {axes}\n"
            f"気血水: {qxs}\n"
            f"視診: {vis}\n"
            f"選定方剤: {chosen_formula}\n\n"
            "[出力JSONスキーマ]\n"
            "{{\n"
            '  "title": "短い見出し",\n'
            '  "background": "背景説明（1-2文）",\n'
            '  "try_first": ["まず試すこと", "..."],\n'
            '  "foods_good": ["合う食材", "..."],\n'
            '  "foods_avoid": ["避けたい食材", "..."],\n'
            '  "lifestyle": ["生活の工夫", "..."],\n'
            '  "points": ["ツボ名", "..."],\n'
            '  "kampo_hint": "（任意）方剤のヒント/注意",\n'
            '  "careful": ["受診目安など"]\n'
            "}}\n"
        )
        # ---- ここまで ----

        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": "あなたは安全で実践的な漢方カウンセラーです。"},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
        )
        txt = resp.choices[0].message.content.strip()

        m = re.search(r'\{.*\}', txt, re.S)
        if m:
            data = json.loads(m.group(0))
            return data, "AI生成成功"
        else:
            return None, "AI応答を解析できませんでした"
    except Exception as e:
        return None, f"AIエラー: {e}"


def score_and_choose(form):
    # 軽量版スコア
    jitsu_kyo = form.get("jitsu_kyo","chukan")
    kan_netsu = form.get("kan_netsu","neutral")
    qi = form.get("qi","normal"); xue = form.get("xue","normal"); sui=form.get("sui","normal")
    sex = form.get("sex","")
    chief = form.get("chief_complaint","")

    pulse_strength = form.get("pulse_strength","")
    pulse_rate = form.get("pulse_rate","")
    pulse_quality = form.get("pulse_quality","")
    face_color = form.get("face_color","")
    tongue_color = form.get("tongue_color","")
    tongue_body = form.get("tongue_body","")
    tongue_coat = form.get("tongue_coat","")
    tongue_moisture = form.get("tongue_moisture","")

    formulas = {"補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0,"半夏厚朴湯":0}
    reasons = []

    if jitsu_kyo=="kyo": formulas["補中益気湯"]+=2; formulas["六君子湯"]+=1; reasons.append("虚→補気")
    if kan_netsu=="kan": formulas["人参湯"]+=1; formulas["真武湯"]+=2; reasons.append("寒→温める")
    if qi=="deficiency": formulas["補中益気湯"]+=3; formulas["六君子湯"]+=2; reasons.append("気虚")
    if qi=="stagnation": formulas["逍遙散"]+=2; formulas["半夏厚朴湯"]+=1; reasons.append("気滞")
    if xue=="deficiency": formulas["当帰芍薬散"]+=2; reasons.append("血虚")
    if xue=="stasis": formulas["桂枝茯苓丸"]+=3; reasons.append("瘀血")
    if sui=="retention": formulas["五苓散"]+=3; formulas["六君子湯"]+=1; reasons.append("水滞")
    if sui=="deficiency": formulas["竹葉石膏湯"]+=1

    if tongue_color=="pale" and tongue_body in ("scalloped","swollen"): formulas["六君子湯"]+=2; reasons.append("淡舌＋歯痕/腫大")

    meta = parse_chief(chief)
    if meta["throat"] and meta["stuck"]:
        formulas["半夏厚朴湯"]+=3; reasons.append("喉のつかえ→半夏厚朴湯")
    if meta["head"] and meta["pain"] and meta["rain"]:
        formulas["五苓散"]+=2; formulas["逍遙散"]+=1; reasons.append("雨頭痛→五苓散")

    chosen = max(formulas, key=lambda k: formulas[k])

    pattern = {
        "八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":"unknown"},
        "気血水":{"気":qi,"血":xue,"水":sui},
        "視診補助":{"脈":{"力":pulse_strength,"速さ":pulse_rate,"性状":pulse_quality},
                     "顔色":face_color,"舌":{"色":tongue_color,"体":tongue_body,"苔":tongue_coat,"湿":tongue_moisture}}
    }

    # 主訴アドバイス
    rule = rule_advice(chief, sex)
    ai, note = ai_advice({"chief_complaint":chief,"sex":sex}, pattern["八綱"], pattern["気血水"], pattern["視診補助"], chosen)

    return {"chosen":chosen,"reasons":reasons,"pattern":pattern,"chief_rule":rule,"chief_ai":ai,"chief_ai_status":note}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())
    uploads = {"tongue": [], "face": [], "body": [], "nails": []}
    field_map = {"tongue_images":"tongue","face_images":"face","body_images":"body","nails_images":"nails"}
    for field,key in field_map.items():
        for f in request.files.getlist(field):
            if not f or not getattr(f,"filename",""): continue
            fname = f"{rec_id}_{key}_{secure_filename(f.filename)}"
            path = UPLOAD_DIR/fname
            f.save(str(path))
            uploads[key].append(f"/uploads/{fname}")
    form = request.form.to_dict()
    assess = score_and_choose(form)
    record = {
        "id":rec_id,"submitted_at":datetime.datetime.utcnow().isoformat()+"Z",
        "patient":{"name":form.get("name",""),"age":form.get("age",""),"sex":form.get("sex",""),
                   "region":form.get("region",""),"chief_complaint":form.get("chief_complaint","")},
        "inspection_uploads":uploads,"ai_assessment":assess
    }
    (DATA_DIR/f"{rec_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
@requires_auth
def detail(rec_id):
    p = DATA_DIR/f"{rec_id}.json"
    if not p.exists(): abort(404)
    data = json.loads(p.read_text(encoding="utf-8"))
    return render_template("detail.html", data=data)

@app.route("/admin")
@requires_auth
def admin():
    items=[]
    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            items.append({"id":d["id"],"submitted_at":d["submitted_at"],
                          "name":d["patient"]["name"],"chief":d["patient"]["chief_complaint"]})
        except Exception: pass
    return render_template("admin.html", items=items[:200])

@app.route("/uploads/<path:filename>")
@requires_auth
def uploads_route(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=True)
