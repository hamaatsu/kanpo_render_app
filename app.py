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

def make_constitution_text(pattern, sex):
    jk = pattern["八綱"]
    qxs = pattern["気血水"]
    parts = []
    if jk["実虚"] == "kyo":
        parts.append("エネルギーが不足しやすい（虚証）。無理せず“補う”ことが合います。")
    elif jk["実虚"] == "jitsu":
        parts.append("張りや停滞が出やすい（実証）。“巡らせて余分をさばく”ことが合います。")
    if jk["寒熱"] == "kan":
        parts.append("冷えがベース。温めると楽になりやすい体質。")
    elif jk["寒熱"] == "netsu":
        parts.append("熱がこもりやすい。口渇・ほてりが出やすい体質。")
    if qxs["気"] == "deficiency":
        parts.append("気虚：だるさ・息切れ・食後の眠気。")
    elif qxs["気"] == "stagnation":
        parts.append("気滞：張る・ため息・ストレスで悪化。")
    elif qxs["気"] == "rebellion":
        parts.append("気逆：のぼせ・げっぷ・逆流。")
    if qxs["血"] == "deficiency":
        if sex=="male":
            parts.append("血虚：乾燥・めまい・不眠が出やすい。")
        else:
            parts.append("血虚：乾燥・めまい・不眠、月経量少が出やすい。")
    elif qxs["血"] == "stasis":
        if sex=="male":
            parts.append("瘀血：刺す痛み・しこり・暗紫舌に注意。")
        else:
            parts.append("瘀血：刺す痛み・月経痛・塊・暗紫舌に注意。")
    if qxs["水"] == "retention":
        parts.append("水滞/痰湿：むくみ・頭重・雨天悪化・軟便。")
        # if 寒なら湿冷へ
        if jk["寒熱"]=="kan":
            parts.append("とくに“湿冷”の傾向があり、冷たい飲食を控えると安定しやすい。")
    elif qxs["水"] == "deficiency":
        parts.append("津液不足：口や皮膚の乾燥、便秘気味。")
    if not parts:
        parts.append("大きな偏りは少なく、生活リズムを整えるだけでも改善が見込めます。")
    return " ".join(parts)

def diet_and_lifestyle(qi, xue, sui, jk, sex):
    # 薬膳食材・生活アドバイス・話題ネタを返す
    food = []
    life = []
    topics = []

    if qi=="deficiency":
        food += ["米（おかゆ）","山芋","かぼちゃ","鶏肉","うなぎ","なつめ","ハチミツ"]
        life += ["朝は温かい汁物を少量でも","過労・夜更かしを避ける","深呼吸＋軽い散歩で“気”を補う"]
        topics += ["午後にぐったりしやすいのは“気のガス欠”のサイン","食後の眠気は脾の弱りの目安"]
    if qi=="stagnation":
        food += ["陳皮（みかん皮）","ジャスミン茶","ミント","香味野菜（ねぎ・しそ）","柑橘"]
        life += ["こまめな深呼吸と肩回し","詰め込み過ぎない予定管理","香りを生活に取り入れる"]
        topics += ["“ため息が増える/胸脇が張る”は気滞の典型","PMS悪化や肩こりと繋がりやすい"]
    if qi=="rebellion":
        food += ["生姜湯（少量）","山楂（さんざし）","消化の良い温食"]
        life += ["早食いしない・食後すぐ横にならない","上半身の冷え/緊張を緩めるストレッチ"]
        topics += ["げっぷ・しゃっくり・逆流は“気の上衝”"]
    if xue=="deficiency":
        if sex=="male":
            food += ["レバー","赤身肉","黒ごま","ほうれん草","クコの実","黒豆"]
        else:
            food += ["レバー","赤身肉","黒ごま","ほうれん草","クコの実","黒豆","なつめ"]
        life += ["睡眠時間の確保（成長ホルモンの時間帯）","急な減量や偏食を避ける"]
        topics += ["爪の縦線・乾燥は血の不足サイン","目の疲れ・立ちくらみも関連"]
    if xue=="stasis":
        food += ["玉ねぎ","酢の物","黒きくらげ","納豆","サーモン"]
        life += ["同一姿勢を続けない","軽い有酸素運動で巡り改善","冷えを溜めない服装"]
        topics += ["“刺すような固定痛”は瘀血のヒント","肩こり・頭痛・しこりと関連"]
    if sui=="retention":
        food += ["はと麦（ヨクイニン）","冬瓜","きゅうり（夏）","とうもろこしのひげ茶","黒豆茶"]
        life += ["冷たい飲食を控え温かいお茶を少量ずつ","軽く汗ばむ運動・半身浴"]
        topics += ["“天気で悪化・頭重・むくみ”は水の偏り","舌の歯痕・腫大が手掛かり"]
    if sui=="deficiency":
        food += ["白きくらげ","梨のコンポート","れんこん","麦門冬茶（むぎもんどう）","はちみつレモン（温）"]
        life += ["夜更かしを避ける（津液を消耗）","乾燥した季節は加湿"]
        topics += ["皮膚・口・咽の乾燥は“津液不足”","便がコロコロになりやすい"]

    if jk=="kan":
        food += ["生姜","ねぎ","シナモン（少量）"]
        life += ["腹巻き・足首を冷やさない","冷房直風を避ける"]
    if jk=="netsu":
        food += ["豆腐","緑豆","セロリ","きゅうり（夏）","大根","麦茶"]
        life += ["辛味・アルコール過多を控える","室内のこまめな換気と水分補給"]

    # 重複排除
    food = list(dict.fromkeys(food))
    life = list(dict.fromkeys(life))
    topics = list(dict.fromkeys(topics))
    return food, life, topics

def score_and_choose(form):
    jitsu_kyo = form.get("jitsu_kyo","")
    kan_netsu = form.get("kan_netsu","")
    hyo_ri = form.get("hyo_ri","")
    qi = form.get("qi","normal")
    xue = form.get("xue","normal")
    sui = form.get("sui","normal")
    sex = form.get("sex","")
    chief = form.get("chief_complaint","")

    # 視診
    pulse_strength = form.get("pulse_strength","")
    pulse_rate = form.get("pulse_rate","")
    pulse_quality = form.get("pulse_quality","")
    face_color = form.get("face_color","")
    tongue_color = form.get("tongue_color","")
    tongue_body = form.get("tongue_body","")
    tongue_coat = form.get("tongue_coat","")
    tongue_moisture = form.get("tongue_moisture","")

    # ルールベーススコア
    formulas = { "補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0 }
    reasons = []

    if jitsu_kyo == "kyo":
        formulas["補中益気湯"] += 2; formulas["六君子湯"] += 1; reasons.append("虚証→補気・健脾")
    if jitsu_kyo == "jitsu":
        formulas["桂枝茯苓丸"] += 1; reasons.append("実証→瘀血/鬱滞考慮")
    if kan_netsu == "kan":
        formulas["人参湯"] += 1; formulas["真武湯"] += 2; reasons.append("寒→温中・温陽")
    if kan_netsu == "netsu":
        formulas["竹葉石膏湯"] += 2; reasons.append("熱→清熱・生津")
    if qi == "deficiency":
        formulas["補中益気湯"] += 3; formulas["六君子湯"] += 2; formulas["人参湯"] += 1; reasons.append("気虚→補気")
    if qi == "stagnation":
        formulas["逍遙散"] += 2; reasons.append("気滞→疏肝解鬱")
    if xue == "deficiency":
        formulas["当帰芍薬散"] += 2; reasons.append("血虚→補血")
    if xue == "stasis":
        formulas["桂枝茯苓丸"] += 3; reasons.append("瘀血→活血")
    if sui == "retention":
        formulas["五苓散"] += 3; formulas["六君子湯"] += 1; reasons.append("水滞→利水")
    if sui == "deficiency":
        formulas["竹葉石膏湯"] += 1

    if pulse_strength == "weak": formulas["補中益気湯"] += 1
    if pulse_rate == "rapid": formulas["竹葉石膏湯"] += 1
    if pulse_quality == "wiry": formulas["逍遙散"] += 1
    if face_color == "pale": formulas["当帰芍薬散"] += 1
    if tongue_color == "pale" and tongue_body in ("scalloped","swollen"):
        formulas["六君子湯"] += 2; reasons.append("淡舌＋歯痕/腫大→脾気虚・水滞")
    if tongue_coat == "yellow": formulas["竹葉石膏湯"] += 1
    if tongue_moisture == "wet": formulas["五苓散"] += 1

    # 簡易主訴処理（v5と同様の辞書だが中で完結）
    def kw(ch):
        s = (ch or "").lower()
        m = []
        if any(w in s for w in ["むくみ","浮腫","はれる"]): m.append("むくみ")
        if any(w in s for w in ["頭痛","片頭痛","こめかみ"]): m.append("頭痛")
        if any(w in s for w in ["肩こり","首こり","肩が張"]): m.append("肩こり")
        if any(w in s for w in ["眠れ","寝つけ","中途覚醒","夢が多い"]): m.append("不眠")
        if any(w in s for w in ["下痢","くだ"]): m.append("下痢")
        if any(w in s for w in ["便秘","硬い便","出にくい"]): m.append("便秘")
        if any(w in s for w in ["ほてり","のぼせ","口渇"]): m.append("ほてり")
        if any(w in s for w in ["冷え","寒気","手足が冷"]): m.append("冷え")
        if any(w in s for w in ["生理痛","月経痛","pms"]): m.append("月経痛")
        if any(w in s for w in ["胃もたれ","もたれ","膨満","ガス"]): m.append("もたれ")
        return m
    chief_kws = kw(chief)
    chief_rules = []
    complaint_map = {
        "頭痛":[("桂枝茯苓丸",1),("逍遙散",1)],
        "肩こり":[("桂枝茯苓丸",2),("逍遙散",1)],
        "便秘":[("桂枝茯苓丸",1)],
        "下痢":[("六君子湯",1),("人参湯",1),("真武湯",1)],
        "もたれ":[("六君子湯",2)],
        "むくみ":[("五苓散",3),("当帰芍薬散",1)],
        "冷え":[("真武湯",2),("人参湯",1)],
        "ほてり":[("竹葉石膏湯",2)],
        "不眠":[("逍遙散",1)],
        "月経痛":[("桂枝茯苓丸",3),("当帰芍薬散",1)]
    }
    for k in chief_kws:
        for f, add in complaint_map.get(k, []):
            formulas[f] += add
            chief_rules.append(f"{k}→{f}+{add}")

    chosen, score = max(formulas.items(), key=lambda x: x[1])

    scripts = {
        "補中益気湯":{"explain":"体のエネルギー（気）を補い、だるさや食欲低下を立て直します。","lifestyle":"朝は温かい汁物やお粥を少量でも。冷飲と夜更しは控えめに。","watch":"のぼせや動悸、発疹が出たら中止して相談。2〜4週で評価。"},
        "六君子湯":{"explain":"胃腸の働きを助け、気を補います。食後のもたれや軟便傾向に。","lifestyle":"温かく消化のよい食事。生もの・冷飲・甘味の摂り過ぎは控えめに。","watch":"腹痛や下痢が強まる場合は中止して相談。2〜3週で評価。"},
        "人参湯":{"explain":"お腹を内側から温め、胃腸機能を支えます。冷えでお腹を壊しやすい方に。","lifestyle":"常温〜温かい飲み物。下腹と足首を冷やさない。","watch":"発熱・のぼせが強い時は合わないことがあります。"},
        "真武湯":{"explain":"体を温めて水の巡りを整えます。冷え・むくみ・軟便やめまいに。","lifestyle":"冷飲を控え、ぬるめの入浴や腹巻きで下腹部を温める。","watch":"便秘や口渇が強い時は別処方が合う場合あり。"},
        "五苓散":{"explain":"余分な水をさばきます。むくみ・頭重・天気で悪化するだるさに。","lifestyle":"温かいお茶を少しずつ。軽い発汗を促す運動も。","watch":"口渇や便秘が強い時は別の調整が必要な場合あり。"},
        "当帰芍薬散":{"explain":"血を養い水の滞りをさばきます。冷え・ふらつき・むくみ傾向に。","lifestyle":"無理なダイエットは避け、鉄とたんぱく質を意識。","watch":"出血傾向がある場合は使用前に相談。"},
        "逍遙散":{"explain":"気の巡りを良くし、ストレス由来の張り・情緒の波を和らげます。","lifestyle":"深呼吸・軽いストレッチ・香りのあるお茶（ジャスミン/ミント）。","watch":"イライラが強すぎる・発熱がある時は別処方検討。"},
        "桂枝茯苓丸":{"explain":"血の滞りをさばきます。下腹部の張り・固定痛・肩こりに。","lifestyle":"体を冷やさない・適度な運動で巡りを助ける。","watch":"妊娠中は原則用いません。出血傾向は医師に相談。"},
        "竹葉石膏湯":{"explain":"熱をさましつつ消耗を補います。ほてり・口渇・だるさが同時にある時に。","lifestyle":"水分はこまめに。辛味の強い香辛料は控えめに。","watch":"冷えが強い日は合いにくいことがあります。"}
    }

    # 体質テキスト
    constitution_description = make_constitution_text({"八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
                                                        "気血水":{"気":qi,"血":xue,"水":sui}}, sex)

    # 薬膳・生活・話題
    food, life, topics = diet_and_lifestyle(qi, xue, sui, kan_netsu, sex)

    pattern = {
        "八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
        "気血水":{"気":qi,"血":xue,"水":sui},
        "視診補助":{"脈":{"力":pulse_strength,"速さ":pulse_rate,"性状":pulse_quality},
                  "顔色":face_color,
                  "舌":{"色":tongue_color,"体":tongue_body,"苔":tongue_coat,"湿":tongue_moisture}}
    }

    # 主訴メモ
    if len(chief.strip())>0:
        chief_note = "主訴にも配慮して選定しています。"
    else:
        chief_note = "主訴の記載がないため体質中心で選定しています。"

    return {
        "chosen": chosen,
        "reasons": reasons,
        "script": scripts.get(chosen, {}),
        "pattern": pattern,
        "constitution": constitution_description,
        "diet": food,
        "lifestyle": life,
        "topics": topics,
        "chief_note": chief_note,
        "chief_raw": chief
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
