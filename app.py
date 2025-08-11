
# -*- coding:utf-8 -*-
import os, json, uuid, datetime, re
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort, Response
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"; DATA_DIR.mkdir(exist_ok=True, parents=True)
UPLOAD_DIR = APP_DIR / "uploads"; UPLOAD_DIR.mkdir(exist_ok=True, parents=True)

BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "admin")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "changeme")
SECRET_KEY = os.getenv("FLASK_SECRET", "dev")

app = Flask(__name__); app.config["SECRET_KEY"] = SECRET_KEY

def check_auth(u,p): return (u==BASIC_AUTH_USERNAME and p==BASIC_AUTH_PASSWORD)
def requires_auth(f):
    @wraps(f)
    def _wrap(*a, **k):
        au = request.authorization
        if not au or not check_auth(au.username, au.password):
            return Response("Auth req", 401, {"WWW-Authenticate": 'Basic realm="Restricted"'})
        return f(*a, **k)
    return _wrap

# ---------- 体質説明 ----------
def constitution_text(jk, qxs, sex):
    parts=[]
    if jk.get("実虚")=="kyo": parts.append("エネルギーが不足しやすい（虚証）。補って立て直す方針。")
    elif jk.get("実虚")=="jitsu": parts.append("張りや滞りが出やすい（実証）。巡らせて余分をさばく方針。")
    if jk.get("寒熱")=="kan": parts.append("冷えが基調。温めると楽になりやすい体質。")
    elif jk.get("寒熱")=="netsu": parts.append("熱がこもりやすい傾向。口渇・ほてりが出やすい。")
    if qxs.get("気")=="deficiency": parts.append("気虚：だるさ・息切れ・食後の眠気。")
    elif qxs.get("気")=="stagnation": parts.append("気滞：張る・ため息・ストレスで悪化。")
    elif qxs.get("気")=="rebellion": parts.append("気逆：のぼせ・げっぷ・逆流。")
    if qxs.get("血")=="deficiency":
        parts.append("血虚：乾燥・めまい・不眠" + ("" if sex=="male" else "、月経量少") + "が出やすい。")
    elif qxs.get("血")=="stasis":
        parts.append("瘀血：刺す痛み・しこり・暗紫舌" + ("" if sex=="male" else "・月経痛") + "に注意。")
    if qxs.get("水")=="retention":
        parts.append("水滞/痰湿：むくみ・頭重・雨天悪化・軟便。")
    elif qxs.get("水")=="deficiency":
        parts.append("津液不足：乾燥・口渇・コロコロ便。")
    if not parts: parts.append("大きな偏りは少なく、生活リズムの調整で整えやすい体質。")
    return " ".join(parts)

# ---------- 主訴解析 & 主訴別アドバイス ----------
def parse_chief(chief:str, sex:str):
    s = (chief or "").strip()
    s_low = s.lower()
    adv=None

    def pack(label, background, first, foods_good, foods_avoid, points, tsubo, danger, note=None):
        return {
            "label": label, "background": background, "first": first,
            "foods_good": foods_good, "foods_avoid": foods_avoid,
            "points": points, "tsubo": tsubo, "danger": danger, "note": note
        }

    # 雨の日頭痛/天気頭痛
    if re.search(r"(雨|気圧|天気).*(頭痛|頭がいた|頭が痛|片頭痛)", s):
        adv = pack(
            "天気頭痛（湿×気滞）",
            "雨や気圧変化で“湿”が重くなり、肩首〜こめかみの巡りが悪化して痛みが出ます。",
            ["温かいはと麦茶/生姜紅茶を少しずつ","首肩を温めて肩回し30秒×3","合谷・風池・太陽を各30秒×3"],
            ["はと麦","生姜","紫蘇","陳皮","玉ねぎ","黒酢"],
            ["冷たい飲料・甘いカフェドリンク","長時間同一姿勢"],
            ["就寝前のスマホを減らす","朝に肩甲骨ストレッチ"],
            ["合谷（手背）","風池（後頭部）","太陽（こめかみ）"],
            "ろれつ障害・麻痺・激しい嘔吐を伴う頭痛は速やかに受診"
        )

    # 肉を食べる→下痢（例示の主訴）
    if adv is None and re.search(r"(肉|焼き肉|ステーキ|豚|牛|鶏).*(下痢|くだす|ゆるい|軟便)", s):
        adv = pack(
            "肉料理後の下痢（脾虚＋湿）",
            "脂やたんぱくの消化に胃腸（脾）が追いつかず、湿が溜まって下痢に。",
            ["肉は薄切りを<少量>から","温かい飲み物で食べる（冷水は避ける）","食後10分の軽い散歩"],
            ["生姜","山椒","陳皮","山芋","白粥","かぼちゃ","ねぎ","大根おろし"],
            ["脂の多い部位","揚げ物","冷たい飲料","生野菜サラダ"],
            ["よく噛む（30回）","夜遅い食事は避ける","食前に白湯を一口"],
            ["中脘（臍上2寸）を温める","足三里の指圧"],
            "血便・発熱・強い腹痛を伴う場合は医療機関へ",
            "鶏むね・ヒレなど脂の少ない部位からテストすると良い"
        )

    # 冷たいもので下痢
    if adv is None and re.search(r"(冷たい|アイス|氷|かき氷).*(下痢|くだす|軟便)", s):
        adv = pack(
            "冷飲食で下痢（陽虚）",
            "内側の冷え（陽虚）で消化火が弱く、冷飲食で腸が緩みます。",
            ["常温〜温かい飲み物に切替","腹巻き・首足首を冷やさない"],
            ["生姜","桂皮（少量）","葱","温かいスープ"],
            ["氷入り飲料・アイス","冷房の直風"],
            ["夕方までに温かい食事を1回入れる"],
            ["中脘・関元の温罨法"],
            "発熱・血便・激しい腹痛は受診"
        )

    # 便秘
    if adv is None and re.search(r"(便秘|出にくい|硬い便)", s):
        adv = pack(
            "便秘（瘀血・乾燥・気滞）",
            "乾燥や巡りの悪さが背景。",
            ["起床後の白湯200ml","ごま・海藻・オリーブ油少量追加","腹式呼吸"],
            ["胡麻","海藻","プルーン","キウイ","れんこん"],
            ["辛い揚げ物の連発","夜更かし"],
            ["就寝前の骨盤回し"],
            ["天枢（臍横2寸）マッサージ"],
            "血便・体重減少の便秘は受診"
        )

    # デフォルト
    if adv is None and s:
        adv = pack(
            "主訴に沿ったセルフケア",
            "主訴を和らげる基本方針をまとめました。",
            ["温かい飲み物を少しずつ","姿勢をこまめに変える","睡眠リズムを揃える"],
            [],[],[],[],""
        )
    return adv

# ---------- 薬膳ネイティブ（体質連動） ----------
def qxs_diet(qi, xue, sui, kan, sex):
    food=[]; life=[]; topic=[]
    if qi=="deficiency":
        food += ["米（おかゆ）","山芋","かぼちゃ","鶏肉","なつめ","はちみつ"]; life += ["朝は温かい汁物を少量でも","過労と夜更かし回避"]
        topic += ["午後のだるさは“気のガス欠”"]
    if xue=="deficiency":
        base = ["レバー","赤身肉","黒ごま","ほうれん草","クコの実","黒豆"]; 
        food += base; life += ["睡眠の確保・偏食を避ける"]; topic += ["爪の縦線・乾燥は血不足のヒント"]
    if xue=="stasis":
        food += ["玉ねぎ","黒きくらげ","酢の物","納豆"]; life += ["同一姿勢を続けない"]
    if sui=="retention":
        food += ["はと麦","冬瓜","とうもろこしのひげ茶","黒豆茶"]; life += ["冷飲を控え、軽く汗ばむ運動"]
        topic += ["天気で悪化・頭重・むくみは水の偏り"]
    if sui=="deficiency":
        food += ["白きくらげ","梨のコンポート","れんこん"]; life += ["加湿と夜更かし回避"]
    if kan=="kan":
        food += ["生姜","ねぎ"]; life += ["腹巻き・直風を避ける"]
    if kan=="netsu":
        food += ["豆腐","大根","麦茶"]; life += ["辛味・アルコール控えめ"]
    # uniq
    food=list(dict.fromkeys(food)); life=list(dict.fromkeys(life)); topic=list(dict.fromkeys(topic))
    return food, life, topic

# ---------- スコアリング & 処方候補 ----------
def score_and_choose(form):
    jitsu_kyo=form.get("jitsu_kyo",""); kan_netsu=form.get("kan_netsu",""); hyo_ri=form.get("hyo_ri","")
    qi=form.get("qi","normal"); xue=form.get("xue","normal"); sui=form.get("sui","normal")
    sex=form.get("sex",""); chief=form.get("chief_complaint","")

    pulse_strength=form.get("pulse_strength",""); pulse_rate=form.get("pulse_rate",""); pulse_quality=form.get("pulse_quality","")
    face_color=form.get("face_color",""); tongue_color=form.get("tongue_color",""); tongue_body=form.get("tongue_body",""); tongue_coat=form.get("tongue_coat",""); tongue_moisture=form.get("tongue_moisture","")

    formulas={"補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0}
    reasons=[]

    if jitsu_kyo=="kyo": formulas["補中益気湯"]+=2; formulas["六君子湯"]+=1; reasons.append("虚証→補気")
    if jitsu_kyo=="jitsu": formulas["桂枝茯苓丸"]+=1
    if kan_netsu=="kan": formulas["人参湯"]+=1; formulas["真武湯"]+=2
    if kan_netsu=="netsu": formulas["竹葉石膏湯"]+=2
    if qi=="deficiency": formulas["補中益気湯"]+=3; formulas["六君子湯"]+=2; reasons.append("気虚→補気")
    if qi=="stagnation": formulas["逍遙散"]+=2
    if xue=="deficiency": formulas["当帰芍薬散"]+=2
    if xue=="stasis": formulas["桂枝茯苓丸"]+=3
    if sui=="retention": formulas["五苓散"]+=3; formulas["六君子湯"]+=1
    if sui=="deficiency": formulas["竹葉石膏湯"]+=1

    if pulse_strength=="weak": formulas["補中益気湯"]+=1
    if pulse_rate=="rapid": formulas["竹葉石膏湯"]+=1
    if pulse_quality=="wiry": formulas["逍遙散"]+=1
    if face_color=="pale": formulas["当帰芍薬散"]+=1
    if tongue_color=="pale" and tongue_body in ("scalloped","swollen"): formulas["六君子湯"]+=2; reasons.append("淡舌＋歯痕/腫大→脾気虚・水滞")
    if tongue_coat=="yellow": formulas["竹葉石膏湯"]+=1
    if tongue_moisture=="wet": formulas["五苓散"]+=1

    # 主訴の加点（より直接）
    s=(chief or "").lower()
    if re.search(r"(雨|気圧|天気).*(頭痛|いた|痛)", s): formulas["五苓散"]+=2; formulas["逍遙散"]+=1; reasons.append("天気頭痛→利水＋疏肝")
    if re.search(r"(肉|焼き肉|豚|牛|鶏).*(下痢|くだ)", s): formulas["六君子湯"]+=2; formulas["人参湯"]+=1; reasons.append("肉食後の下痢→健脾温中")
    if re.search(r"(冷たい|氷|アイス).*(下痢|くだ)", s): formulas["人参湯"]+=2; formulas["真武湯"]+=1; reasons.append("冷飲食で下痢→温中温陽")
    if re.search(r"(便秘|硬い便|出にく)", s): formulas["桂枝茯苓丸"]+=1

    chosen, score = max(formulas.items(), key=lambda x: x[1])

    scripts = {
        "補中益気湯":{"explain":"体のエネルギー（気）を補い、だるさや食欲低下を立て直します。","lifestyle":"朝は温かい汁物やお粥を少量でも。冷飲と夜更しは控えめに。","watch":"のぼせ・動悸が出たら中止して相談。"},
        "六君子湯":{"explain":"胃腸の働きを助け、気を補います。食後のもたれや軟便傾向に。","lifestyle":"温かく消化のよい食事。生もの・冷飲・甘味の摂り過ぎは控えめに。","watch":"腹痛や下痢が強まる場合は中止。"},
        "人参湯":{"explain":"お腹を内側から温め、胃腸機能を支えます。冷えでお腹を壊しやすい方に。","lifestyle":"常温〜温かい飲み物。下腹と足首を冷やさない。","watch":"発熱・のぼせが強い時は避ける。"},
        "真武湯":{"explain":"体を温めて水の巡りを整えます。冷え・むくみ・軟便やめまいに。","lifestyle":"冷飲を控え、ぬるめ入浴で温める。","watch":"便秘や口渇が強い時は別処方を検討。"},
        "五苓散":{"explain":"余分な水をさばきます。むくみ・頭重・天気で悪化するだるさに。","lifestyle":"温かいお茶を少しずつ。軽い発汗を促す運動も。","watch":"口渇や便秘が強い時は別調整が必要。"},
        "当帰芍薬散":{"explain":"血を養い水の滞りをさばきます。冷え・ふらつき・むくみ傾向に。","lifestyle":"鉄とたんぱく質を意識。","watch":"出血傾向は医師へ。"},
        "逍遙散":{"explain":"気の巡りを良くし、ストレス由来の張り・情緒の波を和らげます。","lifestyle":"深呼吸・軽いストレッチ・香りのあるお茶。","watch":"高熱時は適さないことがあります。"},
        "桂枝茯苓丸":{"explain":"血の滞りをさばきます。固定痛・肩こり・塊に。","lifestyle":"体を冷やさず適度な運動。","watch":"妊娠中は原則用いない。"},
        "竹葉石膏湯":{"explain":"熱をさましつつ消耗を補います。ほてり・口渇・だるさが同時にある時に。","lifestyle":"水分はこまめに。辛味の強い香辛料は控えめに。","watch":"冷えが強い日は合いにくい。"},
    }

    constitution = constitution_text({"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri}, {"気":qi,"血":xue,"水":sui}, sex)
    diet, lifestyle, topics = qxs_diet(qi, xue, sui, kan_netsu, sex)
    chief_adv = parse_chief(chief, sex)

    pattern = {
        "八綱":{"実虚":jitsu_kyo,"寒熱":kan_netsu,"表裏":hyo_ri},
        "気血水":{"気":qi,"血":xue,"水":sui},
        "視診補助":{"脈":{"力":pulse_strength,"速さ":pulse_rate,"性状":pulse_quality},
                 "顔色":face_color,
                 "舌":{"色":tongue_color,"体":tongue_body,"苔":tongue_coat,"湿":tongue_moisture}}
    }
    return {
        "chosen": chosen,"reasons": reasons,"script": scripts.get(chosen,{}),
        "pattern": pattern,"constitution": constitution,
        "diet": diet,"lifestyle": lifestyle,"topics": topics,
        "chief_raw": chief,"chief_advice": chief_adv
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())
    uploads = {"tongue": [],"face": [],"body": [],"nails": []}
    for field in ["tongue_images","face_images","body_images","nails_images"]:
        files = request.files.getlist(field)
        key=field.split("_")[0]
        for f in files:
            if not getattr(f,"filename",None): continue
            fname = f"{rec_id}_{secure_filename(f.filename)}"
            f.save(str(UPLOAD_DIR/fname))
            uploads[key].append(f"/uploads/{fname}")
    form = request.form.to_dict()
    assess = score_and_choose(form)
    record = {
        "id": rec_id,
        "submitted_at": datetime.datetime.utcnow().isoformat()+"Z",
        "patient": {"name": form.get("name",""),"age": form.get("age",""),"sex": form.get("sex",""),
                    "region": form.get("region",""),"chief_complaint": form.get("chief_complaint","")},
        "ai_assessment": assess,
        "inspection_uploads": uploads
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
            d=json.loads(p.read_text(encoding="utf-8"))
            items.append({"id": d["id"],"submitted_at": d["submitted_at"],
                          "name": d["patient"]["name"],"chief": d["patient"]["chief_complaint"]})
        except Exception: pass
    return render_template("admin.html", items=items[:200])

@app.route("/uploads/<path:fn>")
@requires_auth
def uploads(fn):
    return send_from_directory(str(UPLOAD_DIR), fn)

if __name__=="__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=True)
