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

# AI settings (optional)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
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
            return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="Restricted"'} )
        return f(*args, **kwargs)
    return decorated

def safe_list(d, key):
    v = d.get(key, [])
    if isinstance(v, list):
        return v
    return []

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
        if jk["寒熱"]=="kan":
            parts.append("とくに“湿冷”の傾向があり、冷たい飲食を控えると安定しやすい。")
    elif qxs["水"] == "deficiency":
        parts.append("津液不足：口や皮膚の乾燥、便秘気味。")
    if not parts:
        parts.append("大きな偏りは少なく、生活リズムを整えるだけでも改善が見込めます。")
    return " ".join(parts)

def diet_and_lifestyle(qi, xue, sui, jk, sex):
    food, life, topics = [], [], []
    if qi=="deficiency":
        food += ["米（おかゆ）","山芋","かぼちゃ","鶏肉","うなぎ","なつめ","ハチミツ"]
        life += ["朝は温かい汁物を少量でも","過労・夜更かしを避ける","深呼吸＋軽い散歩で“気”を補う"]
        topics += ["午後にぐったりしやすいのは“気のガス欠”","食後の眠気は脾の弱り"]
    if qi=="stagnation":
        food += ["陳皮（みかん皮）","ジャスミン茶","ミント","香味野菜（ねぎ・しそ）","柑橘"]
        life += ["こまめな深呼吸と肩回し","詰め込み過ぎない予定","香りを生活に取り入れる"]
        topics += ["ため息増加・胸脇のつかえは気滞の典型"]
    if qi=="rebellion":
        food += ["生姜湯（少量）","山楂（さんざし）","消化の良い温食"]
        life += ["早食いしない・食後すぐ横にならない","上半身の緊張を緩める"]
        topics += ["げっぷ・しゃっくり・逆流＝気の上衝"]
    if xue=="deficiency":
        if sex=="male":
            food += ["レバー","赤身肉","黒ごま","ほうれん草","クコの実","黒豆"]
        else:
            food += ["レバー","赤身肉","黒ごま","ほうれん草","クコの実","黒豆","なつめ"]
        life += ["睡眠確保","急な減量や偏食を避ける"]
        topics += ["爪の縦線・乾燥は血虚のサイン"]
    if xue=="stasis":
        food += ["玉ねぎ","酢の物","黒きくらげ","納豆","サーモン"]
        life += ["同一姿勢を続けない","軽い有酸素運動","冷えをためない"]
        topics += ["刺す固定痛・暗紫舌は瘀血のヒント"]
    if sui=="retention":
        food += ["はと麦（ヨクイニン）","冬瓜","とうもろこしのひげ茶","黒豆茶"]
        life += ["冷飲を控え温かいお茶を少量ずつ","軽く汗ばむ運動・半身浴"]
        topics += ["天気で悪化・頭重・むくみ＝水の偏り"]
    if sui=="deficiency":
        food += ["白きくらげ","梨のコンポート","れんこん","麦門冬茶","はちみつレモン（温）"]
        life += ["夜更かしを避ける","乾燥季は加湿"]
        topics += ["皮膚・口・咽の乾燥＝津液不足"]
    if jk=="kan":
        food += ["生姜","ねぎ","シナモン（少量）"]
        life += ["腹巻き・足首を冷やさない","冷房直風を避ける"]
    if jk=="netsu":
        food += ["豆腐","緑豆","セロリ","きゅうり（夏）","大根","麦茶"]
        life += ["辛味・アルコール過多を控える","こまめに水分補給"]
    food = list(dict.fromkeys(food)); life = list(dict.fromkeys(life)); topics = list(dict.fromkeys(topics))
    return food, life, topics

def parse_chief(ch):
    s = (ch or "").strip()
    parts = {
        "area":{"head":0,"throat":0,"abdomen":0,"stomach":0,"chest":0},
        "nature":{"pain":0,"stuck":0,"diarrhea":0,"constipation":0,"nausea":0,"bloat":0,"dizzy":0},
        "context":{"rain":0,"meal":0,"meat":0,"cold_drink":0,"night":0,"stress":0}
    }
    if "頭" in s: parts["area"]["head"]+=1
    if "喉" in s or "のど" in s: parts["area"]["throat"]+=1
    if "腹" in s or "お腹" in s: parts["area"]["abdomen"]+=1
    if "胃" in s: parts["area"]["stomach"]+=1
    if "胸" in s: parts["area"]["chest"]+=1
    if "痛" in s: parts["nature"]["pain"]+=1
    if "詰" in s or "つまる" in s or "つっか" in s: parts["nature"]["stuck"]+=1
    if "下痢" in s: parts["nature"]["diarrhea"]+=1
    if "便秘" in s: parts["nature"]["constipation"]+=1
    if "吐き気" in s or "ムカムカ" in s: parts["nature"]["nausea"]+=1
    if "張" in s or "膨満" in s or "ガス" in s: parts["nature"]["bloat"]+=1
    if "めまい" in s: parts["nature"]["dizzy"]+=1
    if "雨" in s or "気圧" in s or "低気圧" in s: parts["context"]["rain"]+=1
    if "食後" in s or "食べて" in s or "食事" in s: parts["context"]["meal"]+=1
    if "肉" in s: parts["context"]["meat"]+=1
    if "冷たい" in s or "冷飲" in s: parts["context"]["cold_drink"]+=1
    if "夜" in s or "寝" in s: parts["context"]["night"]+=1
    if "ストレス" in s or "緊張" in s: parts["context"]["stress"]+=1
    return parts

def chief_to_advice(ch, sex):
    meta = parse_chief(ch)
    if meta["area"]["throat"]>0 and meta["nature"]["stuck"]>0:
        ctx = "雨天で悪化" if meta["context"]["rain"]>0 else ""
        advice = {
            "title": "喉が詰まる感じ（梅核気/気滞＋痰湿）",
            "background": "ストレスや湿気で“気”の巡りが滞り、痰が絡むと喉に異物感が出やすくなります。" + (" 雨の日は湿気で悪化しやすい傾向があります。" if ctx else ""),
            "try_first": ["温かい飲み物を少しずつ（生姜湯/ほうじ茶）","深呼吸とゆっくりの発声練習（ハミング）","首肩ストレッチで力みを抜く","強い香辛料や冷飲を避ける"],
            "foods_good": ["陳皮","生姜","紫蘇","はと麦","ねぎ"],
            "foods_avoid": ["冷たい飲み物","油っこい食事","乳製品多め"],
            "lifestyle": ["湿度を上げすぎない/除湿を活用","スマホ前屈を減らす（頸部の圧迫軽減）","気分転換の散歩"],
            "points": ["合谷","列缺","天突"],
            "careful": ["呼吸困難/嚥下困難/発熱を伴う場合は受診を優先"],
            "kampo_hint": "半夏厚朴湯：気の巡りと痰を整え、咽喉の異物感に用いられることがあります。"
        }
        return advice
    if meta["area"]["head"]>0 and meta["nature"]["pain"]>0 and meta["context"]["rain"]>0:
        return {
            "title":"天気・雨の日の頭痛（湿×気滞）",
            "background":"湿気で水の巡りが停滞し、首肩の張りや気の滞りが頭痛の引き金に。",
            "try_first":["はと麦茶を温かく少量ずつ","首肩を温める/軽く回す","湯船で発汗を促す"],
            "foods_good":["はと麦","生姜","黒豆茶"],
            "foods_avoid":["冷たい飲み物","甘味・脂質過多"],
            "lifestyle":["低気圧アプリで事前対策","気圧変化日の残業や飲酒を控える"],
            "points":["合谷","風池","太陽"],
            "careful":["神経学的異常/突然の激痛は受診"]
        }
    if meta["nature"]["diarrhea"]>0 and (meta["context"]["meat"]>0 or meta["context"]["meal"]>0):
        return {
            "title":"肉料理後の下痢（脾虚＋湿）",
            "background":"消化力が落ち、脂っこい食事や量が負担に。湿が増えると下痢が起きやすい。",
            "try_first":["温飲（白湯/ほうじ茶）","肉は薄切り・よく火を通す","生姜や陳皮を少量添える","食後は5〜10分の散歩"],
            "foods_good":["山芋","生姜","陳皮","大根","白菜"],
            "foods_avoid":["冷飲","霜降りや揚げ物","生野菜サラダ"],
            "lifestyle":["食べる順番は汁物→主菜→炭水化物","寝る直前の食事は避ける"],
            "points":["中脘","足三里","関元"],
            "careful":["血便/発熱/激しい腹痛を伴う場合は受診"]
        }
    if meta["nature"]["diarrhea"]>0 and meta["context"]["cold_drink"]>0:
        return {
            "title":"冷飲後の下痢（陽虚/脾胃の冷え）",
            "background":"内臓が冷やされると消化機能が低下し下痢に。",
            "try_first":["常温〜温かい飲み物へ","腹巻き・腰回りを温める"],
            "foods_good":["生姜","ねぎ","にら","味噌汁"],
            "foods_avoid":["氷入り飲料","アイス"],
            "lifestyle":["冷房の直風を避ける","足湯で温める"],
            "points":["中脘","神闕（へそ温罨法）"],
            "careful":["脱水に注意。長引く場合は受診"]
        }
    if meta["nature"]["constipation"]>0:
        return {
            "title":"便秘（乾燥/瘀血/気滞）",
            "background":"水分不足や運動不足、気の巡り低下で停滞。",
            "try_first":["起床白湯","ごま/海藻/オリーブ油を少量","寝る前の腹式呼吸"],
            "foods_good":["黒ごま","寒天","海藻","きのこ"],
            "foods_avoid":["辛味・アルコール過多","冷飲"],
            "lifestyle":["毎日同時刻のトイレ習慣","軽い運動"],
            "points":["天枢","大腸愈"],
            "careful":["便に血/体重減少/発熱は受診"]
        }
    return None

def ai_generate_advice(patient, axes, qxs, vis, chosen_formula):
    if not OPENAI_API_KEY:
        return None, "APIキー未設定のためルールベースで対応"
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)  # ※ proxiesは指定しない（v1系）
        prompt = f"""
あなたは**主訴最優先**の漢方相談カウンセラーです。以下の情報から、
「主訴の背景→まず試す→食材（良い/避ける）→生活→ツボ→受診目安」を**簡潔に**、
かつ**主訴にピンポイント**で日本語JSON出力してください。
制約：結論先出し／一般論は避ける／体質は補足に回す／男性に月経の言及はしない。

[入力]
主訴: {patient.get('chief_complaint','')}
性別: {patient.get('sex','')}
八綱: {axes}
気血水: {qxs}
視診: {vis}
選定方剤: {chosen_formula}

[出力JSONスキーマ]
{{
  "title": "短い見出し",
  "background": "背景説明（1-2文）",
  "try_first": ["まず試すこと", "..."],
  "foods_good": ["合う食材", "..."],
  "foods_avoid": ["避けたい食材", "..."],
  "lifestyle": ["生活の工夫", "..."],
  "points": ["ツボ名", "..."],
  "kampo_hint": "（任意）方剤のヒント/注意",
  "careful": ["受診目安など"]
}}
"""
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role":"system","content":"あなたは安全で実践的な漢方カウンセラーです。"},
                {"role":"user","content":prompt}
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
    jitsu_kyo = form.get("jitsu_kyo","chukan")
    kan_netsu = form.get("kan_netsu","neutral")
    hyo_ri = form.get("hyo_ri","unknown")
    qi = form.get("qi","normal")
    xue = form.get("xue","normal")
    sui = form.get("sui","normal")
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

    formulas = { "補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0,"半夏厚朴湯":0 }
    reasons = []

    if jitsu_kyo == "kyo":
        formulas["補中益気湯"] += 2; formulas["六君子湯"] += 1; reasons.append("虚証→補気・健脾")
    if jitsu_kyo == "jitsu":
        formulas["桂枝茯苓丸"] += 1; reasons.append("実証→瘀血/鬱滞")
    if kan_netsu == "kan":
        formulas["人参湯"] += 1; formulas["真武湯"] += 2; reasons.append("寒→温中・温陽")
    if kan_netsu == "netsu":
        formulas["竹葉石膏湯"] += 2; reasons.append("熱→清熱・生津")
    if qi == "deficiency":
        formulas["補中益気湯"] += 3; formulas["六君子湯"] += 2; formulas["人参湯"] += 1; reasons.append("気虚→補気")
    if qi == "stagnation":
        formulas["逍遙散"] += 2; formulas["半夏厚朴湯"] += 1; reasons.append("気滞→疏肝/行気")
    if xue == "deficiency":
        formulas["当帰芍薬散"] += 2; reasons.append("血虚→補血")
    if xue == "stasis":
        formulas["桂枝茯苓丸"] += 3; reasons.append("瘀血→活血")
    if sui == "retention":
        formulas["五苓散"] += 3; formulas["六君子湯"] += 1; formulas["半夏厚朴湯"] += 1; reasons.append("水滞→利水/化痰")
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

    meta = parse_chief(chief)
    if meta["area"]["throat"]>0 and meta["nature"]["stuck"]>0:
        formulas["半夏厚朴湯"] += 3; formulas["逍遙散"] += 1; reasons.append("喉の異物感→半夏厚朴湯")
        if meta["context"]["rain"]>0: formulas["五苓散"] += 1; reasons.append("雨→湿の関与")
    if meta["area"]["head"]>0 and meta["nature"]["pain"]>0 and meta["context"]["rain"]>0:
        formulas["五苓散"] += 2; formulas["逍遙散"] += 1; reasons.append("雨で頭痛→湿×気滞")
    if meta["nature"]["diarrhea"]>0 and (meta["context"]["meat"]>0 or meta["context"]["meal"]>0):
        formulas["六君子湯"] += 2; formulas["人参湯"] += 1; reasons.append("食後下痢→健脾/温中")

    chosen, score = max(formulas.items(), key=lambda x: x[1])

    scripts = {
        "補中益気湯":{"explain":"体のエネルギー（気）を補い、だるさや食欲低下を立て直します。","lifestyle":"朝は温かい汁物やお粥を少量でも。冷飲と夜更しは控えめに。","watch":"のぼせ・動悸・発疹が出たら中止し相談。"},
        "六君子湯":{"explain":"胃腸の働きを助け、気を補います。もたれや軟便傾向に。","lifestyle":"温かく消化の良い食事。冷飲・甘味の摂り過ぎは控えめに。","watch":"腹痛や下痢が強まる場合は中止して相談。"},
        "人参湯":{"explain":"お腹を温め、胃腸を支えます。冷えでお腹を壊しやすい方に。","lifestyle":"常温〜温かい飲み物。下腹と足首を冷やさない。","watch":"発熱・ほてりが強い時は不向き。"},
        "真武湯":{"explain":"体を温め水の巡りを整えます。冷え・むくみ・軟便やめまいに。","lifestyle":"冷飲を控え、ぬるめ入浴や腹巻きで下腹を温める。","watch":"口渇/便秘が強い時は別処方検討。"},
        "五苓散":{"explain":"余分な水をさばきます。むくみ・頭重・天気で悪化するだるさに。","lifestyle":"温かいお茶を少しずつ。軽い発汗を促す運動も。","watch":"口渇や便秘が強い時は別の調整が必要。"},
        "当帰芍薬散":{"explain":"血を養い水の滞りをさばきます。冷え・ふらつき・むくみ傾向に。","lifestyle":"無理なダイエットは避け、鉄とタンパク質を意識。","watch":"出血傾向がある場合は使用前に相談。"},
        "逍遙散":{"explain":"気の巡りを良くし、ストレス由来の張り・情緒の波を和らげます。","lifestyle":"深呼吸・軽いストレッチ・香りのあるお茶。","watch":"発熱や強い怒りがある時は別処方検討。"},
        "桂枝茯苓丸":{"explain":"血の滞りをさばきます。固定痛や肩こりに。","lifestyle":"冷えをためない・適度に動く。","watch":"妊娠中は原則用いません。出血傾向は医師に相談。"},
        "竹葉石膏湯":{"explain":"熱をさましつつ消耗を補います。ほてり・口渇・だるさが同時にある時に。","lifestyle":"水分はこまめに。辛味過多は控えめに。","watch":"冷えが強い日は不向き。"},
        "半夏厚朴湯":{"explain":"気の巡りと痰を整え、喉の詰まり感・つかえ（梅核気）に。","lifestyle":"温飲・軽い発声・首肩のリラックスを。","watch":"呼吸苦/嚥下困難/発熱があれば医療機関へ。"}
    }

    constitution_description = make_constitution_text({"八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
                                                        "気血水":{"気":qi,"血":xue,"水":sui}}, sex)

    food, life, topics = diet_and_lifestyle(qi, xue, sui, kan_netsu, sex)

    pattern = {
        "八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
        "気血水":{"気":qi,"血":xue,"水":sui},
        "視診補助":{"脈":{"力":pulse_strength,"速さ":pulse_rate,"性状":pulse_quality},
                  "顔色":face_color,
                  "舌":{"色":tongue_color,"体":tongue_body,"苔":tongue_coat,"湿":tongue_moisture}}
    }

    chief_advice = chief_to_advice(chief, sex)
    ai_advice, ai_note = ai_generate_advice(
        {"chief_complaint":chief,"sex":sex},
        pattern["八綱"], pattern["気血水"], pattern["視診補助"], chosen
    )

    return {
        "chosen": chosen,
        "reasons": reasons,
        "script": scripts.get(chosen, {}),
        "pattern": pattern,
        "constitution": constitution_description,
        "diet": food,
        "lifestyle": life,
        "topics": topics,
        "chief_note": "主訴を最優先で解析しています。",
        "chief_raw": chief,
        "chief_rule_advice": chief_advice,
        "chief_ai_advice": ai_advice,
        "chief_ai_status": ai_note if ai_note else ""
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())
    uploads = {"tongue": [], "face": [], "body": [], "nails": []}
    field_map = {"tongue_images":"tongue","face_images":"face","body_images":"body","nails_images":"nails"}
    for field, key in field_map.items():
        files = request.files.getlist(field)
        for f in files:
            if not f or not getattr(f, "filename", ""):
                continue
            fname = f"{rec_id}_{key}_{secure_filename(f.filename)}"
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
