# -*- coding: utf-8 -*-
import os, json, uuid, datetime
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

def make_constitution_text(pattern):
    jk = pattern["八綱"]
    qxs = pattern["気血水"]
    parts = []
    if jk["実虚"] == "kyo":
        parts.append("体力・エネルギーがやや不足しやすい（虚証）傾向。無理より“補う”戦略が合います。")
    elif jk["実虚"] == "jitsu":
        parts.append("停滞や張りが出やすい（実証）傾向。巡らせて余分は捌く戦略が合います。")
    if jk["寒熱"] == "kan":
        parts.append("冷えがベースにあり、温めると楽になりやすい体質。")
    elif jk["寒熱"] == "netsu":
        parts.append("熱がこもりやすく、口渇やほてりが出やすい体質。")
    if qxs["気"] == "deficiency":
        parts.append("気虚（エネルギー不足）のサイン：だるさ・息切れ・食後の眠気が出やすい。")
    elif qxs["気"] == "stagnation":
        parts.append("気滞（ストレス停滞）のサイン：張る・ため息・PMSなどが出やすい。")
    elif qxs["気"] == "rebellion":
        parts.append("気逆（上逆）のサイン：のぼせ・げっぷ・逆流などが出やすい。")
    if qxs["血"] == "deficiency":
        parts.append("血虚の傾向：乾燥・めまい・不眠、月経量少が出やすい。")
    elif qxs["血"] == "stasis":
        parts.append("瘀血の傾向：刺す痛み・月経痛・しこり・暗紫舌に注意。")
    if qxs["水"] == "retention":
        parts.append("水滞/痰湿の傾向：むくみ・頭重・雨天悪化・軟便が出やすい。")
    elif qxs["水"] == "deficiency":
        parts.append("津液不足の傾向：口や皮膚の乾燥、便秘気味が出やすい。")
    if not parts:
        parts.append("大きな偏りは少なく、生活リズムを整えるだけでも改善が見込めます。")
    return " ".join(parts)

def score_and_choose(form):
    # read axes from hidden
    jitsu_kyo = form.get("jitsu_kyo","")
    kan_netsu = form.get("kan_netsu","")
    hyo_ri = form.get("hyo_ri","")
    qi = form.get("qi","normal")
    xue = form.get("xue","normal")
    sui = form.get("sui","normal")
    sex = form.get("sex","")
    # vis
    pulse_strength = form.get("pulse_strength","")
    pulse_rate = form.get("pulse_rate","")
    pulse_quality = form.get("pulse_quality","")
    face_color = form.get("face_color","")
    tongue_color = form.get("tongue_color","")
    tongue_body = form.get("tongue_body","")
    tongue_coat = form.get("tongue_coat","")
    tongue_moisture = form.get("tongue_moisture","")

    formulas = { "補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0 }
    reasons = []

    if jitsu_kyo == "kyo":
        formulas["補中益気湯"] += 2; formulas["六君子湯"] += 1; reasons.append("虚証 → 補気・健脾")
    if jitsu_kyo == "jitsu":
        formulas["桂枝茯苓丸"] += 1; reasons.append("実証 → 瘀血/鬱滞考慮")
    if kan_netsu == "kan":
        formulas["人参湯"] += 1; formulas["真武湯"] += 2; reasons.append("寒 → 温中・温陽")
    if kan_netsu == "netsu":
        formulas["竹葉石膏湯"] += 2; reasons.append("熱 → 清熱・生津")

    if qi == "deficiency":
        formulas["補中益気湯"] += 3; formulas["六君子湯"] += 2; formulas["人参湯"] += 1; reasons.append("気虚 → 補気")
    if qi == "stagnation":
        formulas["逍遙散"] += 2; reasons.append("気滞 → 疏肝解鬱")
    if xue == "deficiency":
        formulas["当帰芍薬散"] += 2; reasons.append("血虚 → 補血")
    if xue == "stasis":
        formulas["桂枝茯苓丸"] += 3; reasons.append("瘀血 → 活血")
    if sui == "retention":
        formulas["五苓散"] += 3; formulas["六君子湯"] += 1; reasons.append("水滞 → 利水")
    if sui == "deficiency":
        formulas["竹葉石膏湯"] += 1

    # vis adjustments
    if pulse_strength == "weak": formulas["補中益気湯"] += 1
    if pulse_rate == "rapid": formulas["竹葉石膏湯"] += 1
    if pulse_quality == "wiry": formulas["逍遙散"] += 1
    if face_color == "pale": formulas["当帰芍薬散"] += 1
    if tongue_color == "pale" and tongue_body in ("scalloped","swollen"):
        formulas["六君子湯"] += 2; reasons.append("淡舌＋歯痕/腫大 → 脾気虚・水滞")
    if tongue_coat == "yellow": formulas["竹葉石膏湯"] += 1
    if tongue_moisture == "wet": formulas["五苓散"] += 1

    chosen, score = max(formulas.items(), key=lambda x: x[1])
    scripts = {
        "補中益気湯":{"explain":"体のエネルギー（気）を補い、だるさや食欲低下を立て直します。","lifestyle":"朝は温かい汁物やお粥を少量でも。冷飲と夜更しは控えめに。","watch":"のぼせや動悸、発疹が出たら中止して相談。2〜4週で評価。"},
        "六君子湯":{"explain":"胃腸の働きを助け、気を補います。食後のもたれや軟便傾向に。","lifestyle":"温かく消化のよい食事。生もの・冷飲・甘味の摂り過ぎは控えめに。","watch":"腹痛や下痢が強まる場合は中止して相談。2〜3週で評価。"},
        "人参湯":{"explain":"お腹を内側から温め、胃腸機能を支えます。冷えでお腹を壊しやすい方に。","lifestyle":"常温〜温かい飲み物。下腹と足首を冷やさない。","watch":"発熱・のぼせが強い時は合わないことがあります。"},
        "真武湯":{"explain":"体を温めて水の巡りを整えます。冷え・むくみ・軟便やめまいに。","lifestyle":"冷飲を控え、ぬるめの入浴や腹巻きで下腹部を温める。","watch":"便秘や口渇が強い時は別処方が合う場合あり。"},
        "五苓散":{"explain":"余分な水をさばきます。むくみ・頭重・天気で悪化するだるさに。","lifestyle":"温かいお茶を少しずつ。軽い発汗を促す運動も。","watch":"口渇や便秘が強い時は別の調整が必要な場合あり。"},
        "当帰芍薬散":{"explain":"血を養い水の滞りをさばきます。冷え・ふらつき・むくみ・月経不調に。","lifestyle":"無理なダイエットは避け、鉄とたんぱく質を意識。","watch":"出血傾向がある場合は使用前に相談。"},
        "逍遙散":{"explain":"気の巡りを良くし、ストレス由来の張り・PMSを和らげます。","lifestyle":"深呼吸・軽いストレッチ・香りのあるお茶（ジャスミン/ミント）。","watch":"イライラが強すぎる・発熱がある時は別処方検討。"},
        "桂枝茯苓丸":{"explain":"血の滞りをさばきます。下腹部の張り・月経痛・しこり・肩こりに。","lifestyle":"体を冷やさない・適度な運動で巡りを助ける。","watch":"妊娠中は原則用いません。出血傾向は医師に相談。"},
        "竹葉石膏湯":{"explain":"熱をさましつつ消耗を補います。ほてり・口渇・だるさが同時にある時に。","lifestyle":"水分はこまめに。辛味の強い香辛料は控えめに。","watch":"冷えが強い日は合いにくいことがあります。"}
    }
    # 男性の場合、月経関連表現を除去・言い換え
    if sex == "male":
        if "当帰芍薬散" in scripts:
            scripts["当帰芍薬散"]["explain"] = "血を養い水の滞りをさばきます。冷え・ふらつき・むくみ・めまい傾向に。"
        if "逍遙散" in scripts:
            scripts["逍遙散"]["explain"] = "気の巡りを良くし、ストレス由来の張りや情緒の波を和らげます。"
        if "桂枝茯苓丸" in scripts:
            scripts["桂枝茯苓丸"]["explain"] = "血の滞りをさばきます。下腹部の張り・肩こり・固定痛に。"

    pattern = {
        "八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
        "気血水":{"気":qi,"血":xue,"水":sui},
        "視診補助":{"脈":{"力":pulse_strength,"速さ":pulse_rate,"性状":pulse_quality},
                  "顔色":face_color,
                  "舌":{"色":tongue_color,"体":tongue_body,"苔":tongue_coat,"湿":tongue_moisture}}
    }
    interview_guide = {
        "必ず聞く":[
            "主訴の始まり・経過（いつから/悪化・軽減要因）",
            "寒熱感（冷え・ほてり）と時間帯差",
            "食欲・消化（食後のもたれ/便通/ガス）",
            "睡眠（入眠/中途覚醒/夢の多さ）",
            "（女性のみ）月経周期/関連症状",
            "ストレス・運動・飲酒・カフェイン"
        ],
        "視るポイント":["顔色（蒼白/紅/黄/暗）","舌（色/体/苔/湿）","脈（力/速さ/性状）","下腹・四肢の冷え/むくみ"],
        "危険サイン（要医療受診）":["激痛/高熱/胸痛/呼吸困難","急速な体重減少/血便・黒色便/大量の不正出血","意識障害・けいれん・新規の重度頭痛"]
    }
    constitution_description = make_constitution_text(pattern)
    return {
        "chosen": chosen,
        "score": score,
        "reasons": reasons,
        "script": scripts.get(chosen, {}),
        "pattern": pattern,
        "interview_guide": interview_guide,
        "constitution": constitution_description
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())
    uploads = {"tongue": [], "face": [], "body": [], "nails": []}
    for field in ["tongue_images","face_images","body_images","nails_images"]:
        files = request.files.getlist(field)
        key = field.split("_")[0]
        for f in files:
            if not f or not getattr(f, "filename", ""):
                continue
            fname = f"{rec_id}_{secure_filename(f.filename)}"
            save_path = UPLOAD_DIR / fname
            f.save(str(save_path))
            uploads[key].append(f"/uploads/{fname}")

    form = request.form.to_dict()
    assessment = score_and_choose(form)

    record = {
        "id": rec_id,
        "submitted_at": datetime.datetime.utcnow().isoformat() + "Z",
        "patient": {
            "name": form.get("name",""),
            "age": form.get("age",""),
            "sex": form.get("sex",""),
            "region": form.get("region",""),
            "chief_complaint": form.get("chief_complaint","")
        },
        "ai_assessment": assessment,
        "inspection_uploads": uploads
    }
    (DATA_DIR / f"{rec_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("detail", rec_id=rec_id))

@app.route("/record/<rec_id>")
@requires_auth
def detail(rec_id):
    p = DATA_DIR / f"{rec_id}.json"
    if not p.exists():
        abort(404)
    data = json.loads(p.read_text(encoding="utf-8"))
    return render_template("detail.html", data=data)

@app.route("/admin")
@requires_auth
def admin():
    items = []
    for p in sorted(DATA_DIR.glob("*.json"), reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
            items.append({
                "id": d.get("id",""),
                "submitted_at": d.get("submitted_at",""),
                "name": d.get("patient",{}).get("name",""),
                "chief": d.get("patient",{}).get("chief_complaint","")
            })
        except Exception:
            continue
    return render_template("admin.html", items=items[:200])

@app.route("/uploads/<path:filename>")
@requires_auth
def uploads_route(filename):
    return send_from_directory(str(UPLOAD_DIR), filename)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)
