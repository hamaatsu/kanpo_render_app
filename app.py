# -*- coding: utf-8 -*-
import os, json, uuid, datetime, re
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response, abort
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

def requires_auth(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not (auth.username == BASIC_AUTH_USERNAME and auth.password == BASIC_AUTH_PASSWORD):
            return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="Restricted"'})
        return f(*args, **kwargs)
    return decorated

# ---------------- 主訴→アドバイス辞書 ----------------
def build_complaint_profiles():
    # pattern: dict with title, background, do, avoid, foods_good, foods_avoid, points, acupoints, danger, formula_bias list
    P = []

    def add(keys, title, background, do, avoid, foods_good, foods_avoid, points, acupoints, danger, bias):
        P.append({
            "keys": keys, "title": title, "background": background, "do": do, "avoid": avoid,
            "foods_good": foods_good, "foods_avoid": foods_avoid, "points": points, "acupoints": acupoints,
            "danger": danger, "bias": bias
        })

    add(
        keys=[r"雨|気圧|天気.*頭痛|雨の日に.*頭"],
        title="天気・雨の日の頭痛（湿×気滞）",
        background=["湿気で水の巡りが滞ると頭重・頭痛が出やすい。首肩のこわばり（気滞）も関与。"],
        do=["はと麦茶/とうもろこしのひげ茶を温かく少量ずつ","首肩を温めストレッチ","入浴はぬるめで長めに汗を少し"],
        avoid=["冷たい飲み物・生もの過多","長時間の同一姿勢"],
        foods_good=["はと麦","生姜","黒豆","冬瓜","陳皮"],
        foods_avoid=["乳製品過多","油もの・甘味のとり過ぎ"],
        points=["気象の悪化前日に水分は“こまめに＋温かく”","PC作業は45分毎に肩回し"],
        acupoints=["合谷","風池","太陽"],
        danger=["麻痺・ろれつ障害・突然の激烈頭痛→緊急受診"],
        bias=[("五苓散",2),("逍遙散",1)]
    )

    add(
        keys=[r"肉.*下痢|焼?肉.*下痢|ステーキ.*下痢"],
        title="肉料理後の下痢（脾虚＋湿）",
        background=["脂とたんぱくの消化負担で脾が弱く、水分が滞って下痢に。"],
        do=["肉は薄切り・よく火を通す・量は控えめ","温かい飲み物（食中/食後）","食後10分の軽い散歩","生姜・山椒・陳皮など香味を少量"],
        avoid=["脂の多い部位（霜降り等）","冷たい飲み物","生野菜サラダの大量摂取"],
        foods_good=["生姜","陳皮","山椒","山芋","白米粥","かぼちゃ","鶏むね蒸し"],
        foods_avoid=["霜降り牛","背脂多い豚","アイス/冷飲"],
        points=["頻度・量・部位と症状の相関を記録","まずは“量の半分＋温飲”から再挑戦"],
        acupoints=["中脘","足三里","関元（温罨法）"],
        danger=["血便・発熱・激しい腹痛を伴う場合は受診"],
        bias=[("六君子湯",2),("人参湯",1),("真武湯",1)]
    )

    add(
        keys=[r"冷たい.*(飲|食).*下痢|アイス.*下痢|氷.*下痢"],
        title="冷飲食での下痢（陽虚・脾腎陽虚）",
        background=["冷えで消化の火が弱り、腸が過敏に動いてしまう。"],
        do=["常温〜温かい飲み物","腹巻き・下腹部保温","温かいスープを先に少量"],
        avoid=["氷入りドリンク・アイス","冷房の直風"],
        foods_good=["生姜","ねぎ","シナモン（少量）","根菜スープ"],
        foods_avoid=["サラダ大量","冷麺"],
        points=["夏でも内側は冷えやすい体質がある"],
        acupoints=["中脘","関元","気海"],
        danger=["嘔吐・高熱・血便は受診"],
        bias=[("真武湯",2),("人参湯",2)]
    )

    add(
        keys=[r"便秘|出にくい|硬い便|コロコロ"],
        title="便秘（乾燥/瘀血/気滞の見極め）",
        background=["乾燥（津液不足）、滞り（瘀血/気滞）で出にくい。"],
        do=["起床白湯","ごま・海藻・オリーブ油少量","規則的な排便時間の習慣化"],
        avoid=["冷え","水分不足","我慢の癖"],
        foods_good=["黒ごま","海藻","オートミール","プルーン","れんこん"],
        foods_avoid=["辛味過多","冷飲"],
        points=["刺す固定痛や黒便は注意"],
        acupoints=["天枢","気海","大巨"],
        danger=["便に血・激痛・やせる→受診"],
        bias=[("桂枝茯苓丸",1)]
    )

    add(
        keys=[r"逆流|胸やけ|ゲップ|吐き気"],
        title="逆流感・胸やけ（気逆＋胃不和）",
        background=["気が上へ突き上げる（気逆）＋消化停滞。"],
        do=["少量で回数を増やす","食後すぐ横にならない","口当たりの優しい温食"],
        avoid=["早食い","脂っこい・甘い・アルコール過多"],
        foods_good=["山楂","生姜湯（少量）","大根おろし"],
        foods_avoid=["揚げ物","クリーム系"],
        points=["就寝2時間前は食べない"],
        acupoints=["内関","中脘"],
        danger=["嚥下障害・体重減少・出血は受診"],
        bias=[("六君子湯",1)]
    )

    add(
        keys=[r"肩こり|首こり|肩が張"],
        title="肩こり（気滞＋瘀血）",
        background=["ストレスや同一姿勢で巡りが滞る。"],
        do=["肩甲骨はがし運動","温湿布","深い呼吸"],
        avoid=["長時間の同一姿勢"],
        foods_good=["陳皮","ジャスミン茶","玉ねぎ","酢の物"],
        foods_avoid=["冷飲","甘味過多"],
        points=["45分に1回立つ"],
        acupoints=["肩井","風池","合谷"],
        danger=["片側の脱力・しびれは受診"],
        bias=[("桂枝茯苓丸",2),("逍遙散",1)]
    )

    add(
        keys=[r"不眠|寝つけ|中途覚醒|夢が多い"],
        title="不眠（心血不足/肝熱/陰虚の鑑別）",
        background=["心を養う血の不足、ストレスでの肝の高ぶり、潤い不足で熱がこもる等。"],
        do=["就寝前のスマホ制限","ぬるめ入浴","百会の呼吸法"],
        avoid=["夕方以降のカフェイン","刺激の強い動画"],
        foods_good=["なつめ","百合根","クコの実","温かいミルク風（乳糖不耐は注意）"],
        foods_avoid=["唐辛子過多","夜食"],
        points=["昼間の日光と運動を少し"],
        acupoints=["神門","内関","安眠"],
        danger=["抑うつが強い/自傷念慮は専門受診"],
        bias=[("逍遙散",1)]
    )

    return P

COMPLAINT_PROFILES = build_complaint_profiles()

# ---------------- 体質説明・薬膳 ----------------
def constitution_text(axes, qxs, sex):
    parts = []
    if axes.get("実虚") == "kyo":
        parts.append("エネルギー不足（虚証）傾向。まず“補う”ことが合います。")
    elif axes.get("実虚") == "jitsu":
        parts.append("停滞が出やすい（実証）傾向。余分をさばき巡らせると楽です。")
    if axes.get("寒熱") == "kan":
        parts.append("冷えがベース。温めると楽になりやすい体質。")
    elif axes.get("寒熱") == "netsu":
        parts.append("熱がこもりやすい。口渇・ほてりが出やすい体質。")
    if qxs.get("気") == "deficiency":
        parts.append("気虚：だるさ・息切れ・食後の眠気。")
    elif qxs.get("気") == "stagnation":
        parts.append("気滞：張る・ため息・ストレスで悪化。")
    elif qxs.get("気") == "rebellion":
        parts.append("気逆：のぼせ・げっぷ・逆流。")
    if qxs.get("血") == "deficiency":
        parts.append("血虚：乾燥・めまい・不眠" + ("" if sex=="male" else "、月経量少") + "。")
    elif qxs.get("血") == "stasis":
        parts.append("瘀血：刺す痛み・" + ("" if sex=="male" else "月経痛・") + "しこり・暗紫舌に注意。")
    if qxs.get("水") == "retention":
        parts.append("水滞/痰湿：むくみ・頭重・雨天悪化・軟便。")
    elif qxs.get("水") == "deficiency":
        parts.append("津液不足：口や皮膚の乾燥、便秘気味。")
    return " ".join(parts) if parts else "大きな偏りは少なく、生活リズムの調整で改善が見込めます。"

def diet_life_topics(qi, xue, sui, coldheat, sex):
    food, life, topics = [], [], []
    if qi=="deficiency":
        food += ["米（おかゆ）","山芋","かぼちゃ","鶏肉","うなぎ","なつめ","ハチミツ"]
        life += ["朝は温かい汁物を少量でも","過労・夜更かしを避ける"]
        topics += ["午後にぐったりは“気のガス欠”"]
    if qi=="stagnation":
        food += ["陳皮","ジャスミン茶","ミント","香味野菜"]
        life += ["深呼吸・肩回し・予定を詰め込まない"]
        topics += ["ため息・胸脇の張りは気滞のサイン"]
    if xue=="deficiency":
        food += ["レバー","赤身肉","黒ごま","ほうれん草","クコの実"] + ([] if sex=="male" else ["なつめ"])
        life += ["睡眠の確保","極端な減量は避ける"]
        topics += ["爪の縦線・乾燥＝血不足のヒント"]
    if xue=="stasis":
        food += ["玉ねぎ","酢の物","黒きくらげ","納豆","サーモン"]
        life += ["同一姿勢を避ける","軽い有酸素運動"]
        topics += ["“刺す固定痛”は瘀血の手がかり"]
    if sui=="retention":
        food += ["はと麦","冬瓜","とうもろこしのひげ茶","黒豆茶"]
        life += ["冷飲を控え温かい茶を少量ずつ","軽く汗ばむ運動"]
        topics += ["天気で悪化・頭重・むくみ＝水の偏り"]
    if sui=="deficiency":
        food += ["白きくらげ","梨のコンポート","れんこん","麦門冬茶","はちみつレモン（温）"]
        life += ["夜更かしは潤いを消耗","加湿"]
        topics += ["乾燥で咽・皮膚トラブル"]
    if coldheat=="kan":
        food += ["生姜","ねぎ","シナモン（少量）"]
    if coldheat=="netsu":
        food += ["豆腐","緑豆","セロリ","大根","麦茶"]
    # dedupe preserving order
    def dedup(seq):
        out=[]; seen=set()
        for x in seq:
            if x not in seen:
                seen.add(x); out.append(x)
        return out
    return dedup(food), dedup(life), dedup(topics)

# ---------------- スコアリングと選択 ----------------
def parse_checkboxes(form):
    return {
        "jitsu_kyo": form.get("jitsu_kyo",""),
        "kan_netsu": form.get("kan_netsu",""),
        "hyo_ri": form.get("hyo_ri",""),
        "qi": form.get("qi","normal"),
        "xue": form.get("xue","normal"),
        "sui": form.get("sui","normal"),
    }

def apply_complaint_bias(chief):
    s = (chief or "").lower()
    applied = []
    bias_map = {}  # formula -> points
    for prof in COMPLAINT_PROFILES:
        hit = False
        for pat in prof["keys"]:
            if re.search(pat, s):
                hit = True; break
        if hit:
            applied.append(prof)
            for f, add in prof["bias"]:
                bias_map[f] = bias_map.get(f,0) + add
    return applied, bias_map

def image_presence_notes(uploads, sex):
    notes = []
    if uploads.get("tongue"): notes.append("舌の写真あり：色・歯痕・苔の厚さを確認。歯痕/腫大は脾虚・水滞傾向。")
    if uploads.get("face"): notes.append("顔写真あり：蒼白/紅/黄/暗の偏りを確認。")
    if uploads.get("nails"): notes.append("爪写真あり：割れ・縦線（血虚）や黒ずみ（瘀血）を確認。")
    if uploads.get("body"): notes.append("体の写真あり：むくみや冷えの分布、皮膚の乾湿を確認。")
    # 男性への月経表現省略は別で実施
    return notes

def score_and_choose(form, uploads, sex):
    checks = parse_checkboxes(form)
    qi=checks["qi"]; xue=checks["xue"]; sui=checks["sui"]
    jitsu_kyo=checks["jitsu_kyo"]; kan_netsu=checks["kan_netsu"]; hyo_ri=checks["hyo_ri"]
    chief = form.get("chief_complaint","")

    # base scores
    formulas = { "補中益気湯":0,"六君子湯":0,"人参湯":0,"真武湯":0,"五苓散":0,"当帰芍薬散":0,"逍遙散":0,"桂枝茯苓丸":0,"竹葉石膏湯":0 }
    reasons = []

    if jitsu_kyo=="kyo": formulas["補中益気湯"]+=2; formulas["六君子湯"]+=1; reasons.append("虚証→補気・健脾")
    if jitsu_kyo=="jitsu": formulas["桂枝茯苓丸"]+=1; reasons.append("実証→瘀血/鬱滞考慮")
    if kan_netsu=="kan": formulas["人参湯"]+=1; formulas["真武湯"]+=2; reasons.append("寒→温中・温陽")
    if kan_netsu=="netsu": formulas["竹葉石膏湯"]+=2; reasons.append("熱→清熱・生津")
    if qi=="deficiency": formulas["補中益気湯"]+=3; formulas["六君子湯"]+=2; formulas["人参湯"]+=1; reasons.append("気虚→補気")
    if qi=="stagnation": formulas["逍遙散"]+=2; reasons.append("気滞→疏肝解鬱")
    if xue=="deficiency": formulas["当帰芍薬散"]+=2; reasons.append("血虚→補血")
    if xue=="stasis": formulas["桂枝茯苓丸"]+=3; reasons.append("瘀血→活血")
    if sui=="retention": formulas["五苓散"]+=3; formulas["六君子湯"]+=1; reasons.append("水滞→利水")
    if sui=="deficiency": formulas["竹葉石膏湯"]+=1

    # visual finds nudges via notes text (optional fields)
    for field,kw,fm,add in [
        ("tongue_note","歯痕","六君子湯",1),
        ("tongue_note","腫大","六君子湯",1),
        ("tongue_note","黄苔","竹葉石膏湯",1),
        ("tongue_note","無苔","竹葉石膏湯",1),
        ("face_note","蒼白","当帰芍薬散",1),
        ("face_note","紅","竹葉石膏湯",1),
    ]:
        note = (form.get(field,"") or "").lower()
        if kw in note:
            formulas[fm] += add

    # chief complaint bias
    applied_profiles, bias_map = apply_complaint_bias(chief)
    for f,add in bias_map.items():
        formulas[f] = formulas.get(f,0)+add
    if applied_profiles:
        reasons.append("主訴による補正：" + " / ".join([p["title"] for p in applied_profiles]))

    chosen = max(formulas.items(), key=lambda x: x[1])[0]

    # scripts for chosen formula
    scripts = {
        "補中益気湯":{"explain":"体のエネルギー（気）を補い、だるさや食欲低下を立て直します。","lifestyle":"朝は温かい汁物やお粥を少量でも。冷飲と夜更しは控えめに。","watch":"のぼせ・動悸・発疹が出たら中止して相談。2〜4週で再評価。"},
        "六君子湯":{"explain":"胃腸の働きを助け、気を補います。食後のもたれや軟便傾向に。","lifestyle":"温かく消化のよい食事。生もの・冷飲・甘味の摂り過ぎは控えめに。","watch":"腹痛・下痢が強まる場合は中止して相談。2〜3週で評価。"},
        "人参湯":{"explain":"お腹を内側から温め、胃腸機能を支えます。冷えでお腹を壊しやすい方に。","lifestyle":"常温〜温かい飲み物。下腹と足首を冷やさない。","watch":"発熱・のぼせが強い時は合わないことがあります。"},
        "真武湯":{"explain":"体を温めて水の巡りを整えます。冷え・むくみ・軟便やめまいに。","lifestyle":"冷飲を控え、ぬるめ入浴や腹巻きで下腹部を温める。","watch":"便秘や口渇が強い時は別処方が合う場合あり。"},
        "五苓散":{"explain":"余分な水をさばきます。むくみ・頭重・天気で悪化するだるさに。","lifestyle":"温かいお茶を少しずつ。軽い発汗を促す運動も。","watch":"口渇や便秘が強い時は別の調整が必要な場合あり。"},
        "当帰芍薬散":{"explain":"血を養い水の滞りをさばきます。冷え・ふらつき・むくみ傾向に。","lifestyle":"無理なダイエットは避け、鉄とたんぱく質を意識。","watch":"出血傾向がある場合は使用前に相談。"},
        "逍遙散":{"explain":"気の巡りを良くし、ストレス由来の張り・情緒の波を和らげます。","lifestyle":"深呼吸・軽いストレッチ・香りのあるお茶（ジャスミン/ミント）。","watch":"イライラが強すぎる・発熱がある時は別処方検討。"},
        "桂枝茯苓丸":{"explain":"血の滞りをさばきます。下腹部の張り・固定痛・肩こりに。","lifestyle":"体を冷やさない・適度な運動で巡りを助ける。","watch":"妊娠中は原則用いません。出血傾向は医師に相談。"},
        "竹葉石膏湯":{"explain":"熱をさましつつ消耗を補います。ほてり・口渇・だるさが同時にある時に。","lifestyle":"水分はこまめに。辛味の強い香辛料は控えめに。","watch":"冷えが強い日は合いにくいことがあります。"}
    }

    # ランキング作成（上位3つ）
    ranked = sorted(formulas.items(), key=lambda x: x[1], reverse=True)
    top3 = [name for name,score in ranked[:3]]

    # 薬剤師向けの選択基準メモ（簡潔）
    pharmacist_tips = {
        "補中益気湯": "だるさ強い・食欲低下・息切れ。脈弱／舌淡で虚の所見が明確なら第一候補。",
        "六君子湯": "胃もたれ・食欲不振・軟便傾向。気虚＋痰湿（舌苔厚・胸脇つかえ）なら。",
        "人参湯": "冷えで腹痛/下痢。温めると楽。寒が強く、虚寒の胃腸症状に寄るときに。",
        "真武湯": "冷え＋むくみ＋めまい/軟便。腎陽虚寄りや水滞が前景のケースに。",
        "五苓散": "口渇・尿少・むくみ・頭重。天候で悪化、二日酔い、水分偏在の訴えに。",
        "当帰芍薬散": "冷え・貧血傾向・むくみ・ふらつき。産後/月経不順で虚が前景なら◎。",
        "逍遙散": "ストレスで張る・情緒不安定・胸脇苦満。PMSや更年期の気滞に。",
        "桂枝茯苓丸": "下腹部の抵抗・固定痛・肩こり・シミ/瘀斑。実寄りの瘀血徴候で。",
        "竹葉石膏湯": "ほてり・口渇・だるさ同時。清熱と津液補充が要るときに。"
    }

    candidates = []
    for name, score in ranked[:3]:
        candidates.append({
            "name": name,
            "score": score,
            "script": scripts.get(name, {}),
            "pharmacist_tip": pharmacist_tips.get(name, "")
        })

    axes = {"実虚": jitsu_kyo, "寒熱": kan_netsu, "表裏": hyo_ri}
    qxs = {"気": qi, "血": xue, "水": sui}

    constitution = constitution_text(axes, qxs, sex)
    food, life, topics = diet_life_topics(qi, xue, sui, kan_netsu, sex)
    img_notes = image_presence_notes(uploads, sex)

    # 主訴別アドバイス最終生成（複数ヒットもまとめ表示）
    complaint_sections = []
    for prof in applied_profiles:
        complaint_sections.append({
            "title": prof["title"],
            "background": prof["background"],
            "do": prof["do"],
            "avoid": prof["avoid"],
            "foods_good": prof["foods_good"],
            "foods_avoid": prof["foods_avoid"],
            "points": prof["points"],
            "acupoints": prof["acupoints"],
            "danger": prof["danger"]
        })

    return {
        "chosen": candidates[0]["name"] if candidates else None,
        "candidates": candidates,
        "reasons": reasons,
        "script": scripts.get(chosen, {}),
        "axes": axes, "qxs": qxs,
        "constitution": constitution,
        "diet": food, "lifestyle": life, "topics": topics,
        "chief_note": "主訴を優先してアドバイス・方剤を補正しています。" if applied_profiles else "主訴の記載が薄いため体質中心で提案しています。",
        "chief_raw": chief,
        "complaint_sections": complaint_sections,
        "image_notes": img_notes
    }

# ---------------- AI再ランク＆助言生成 ----------------
def ai_rerank_and_advice(form, sex, assessment):
    """
    OPENAI_API_KEY が設定されていれば、LLMで candidates を再ランクし、
    理由・薬膳・生活・面談ポイントを生成して返す。
    キーが無い場合はそのまま返す（後方互換）。
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return assessment

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        # 入力を要約してプロンプト作成
        axes = assessment.get("axes",{})
        qxs = assessment.get("qxs",{})
        candidates = assessment.get("candidates",[])
        chief = form.get("chief_complaint","").strip()
        age = form.get("age",""); region = form.get("region","")

        sys_prompt = (
            "あなたは漢方薬局のベテラン薬剤師です。"
            "以下の情報（主訴・体質軸・候補）を踏まえて、候補を再ランクし、"
            "各候補について1)選定理由、2)薬膳食材（推奨/控える）、3)生活アドバイス、4)面談の掘り下げポイントを日本語で簡潔に出力します。"
            "薬機法に配慮し断定表現を避け、一般向け助言は安全側で。"
        )

        user = {
            "patient": {
                "sex": sex, "age": age, "region": region,
                "chief_complaint": chief,
                "axes": axes, "qxs": qxs
            },
            "candidates": [c["name"] for c in candidates]
        }

        # モデル名はデプロイ環境で調整可能に。無ければデフォルト。
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        response = client.chat.completions.create(
            model=model,
            temperature=0.3,
            messages=[
                {"role":"system","content":sys_prompt},
                {"role":"user","content":json.dumps(user, ensure_ascii=False)}
            ]
        )
        content = response.choices[0].message.content

        # ざっくりJSONを期待しつつ、失敗時はテキストをそのまま格納
        parsed = None
        try:
            parsed = json.loads(content)
        except Exception:
            parsed = {"llm_notes": content}

        # 期待するフォーマット例：
        # { "reranked": [{"name":"補中益気湯","reason":"..."},{"name":"六君子湯","reason":"..."}],
        #   "advice": { "<方剤>": {"foods_good":[...],"foods_avoid":[...],"lifestyle":[...],"counsel_points":[...] } } }
        reranked = parsed.get("reranked") if isinstance(parsed, dict) else None
        advice = parsed.get("advice") if isinstance(parsed, dict) else {}

        if reranked:
            # 既存 candidates をスコア付け直し
            score_map = {c["name"]: c["score"] for c in candidates}
            new_cands = []
            for i, item in enumerate(reranked):
                name = item.get("name")
                base_score = score_map.get(name, 0)
                new_cands.append({
                    "name": name,
                    "score": base_score + max(0, 3 - i),  # 上位ほど少し加点
                    "script": next((c["script"] for c in candidates if c["name"]==name), {}),
                    "pharmacist_tip": next((c["pharmacist_tip"] for c in candidates if c["name"]==name), ""),
                    "ai_reason": item.get("reason","")
                })
            # 助言をマージ
            for c in new_cands:
                adv = advice.get(c["name"], {})
                c["foods_good"] = adv.get("foods_good", [])
                c["foods_avoid"] = adv.get("foods_avoid", [])
                c["lifestyle"] = adv.get("lifestyle", [])
                c["counsel_points"] = adv.get("counsel_points", [])
            assessment["candidates"] = new_cands
            assessment["chosen"] = new_cands[0]["name"] if new_cands else assessment.get("chosen")

        assessment["llm_raw"] = parsed
        return assessment
    except Exception as e:
        # 失敗時はそのまま返す
        assessment["llm_error"] = str(e)
        return assessment

# ---------------- ルーティング ----------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())

    form = request.form.to_dict()
    sex = form.get("sex","")
    # 画像を使わない前提：uploadsは空
    uploads = {"tongue": [], "face": [], "body": [], "nails": []}

    # ルールベースで候補作成
    assessment = score_and_choose(form, uploads, sex)

    # LLMで再ランク＆助言生成（環境変数があれば）
    assessment = ai_rerank_and_advice(form, sex, assessment)

    record = {
        "id": rec_id,
        "submitted_at": datetime.datetime.utcnow().isoformat() + "Z",
        "patient": {
            "name": form.get("name",""),
            "age": form.get("age",""),
            "sex": sex,
            "region": form.get("region",""),
            "chief_complaint": form.get("chief_complaint","")
        },
        "ai_assessment": assessment
    }
    (DATA_DIR / f"{rec_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return redirect(url_for("detail", rec_id=rec_id))


@app.route("/record/<rec_id>")
@requires_auth
def detail(rec_id):
    p = DATA_DIR / f"{rec_id}.json"
    if not p.exists(): abort(404)
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
