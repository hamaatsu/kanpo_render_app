# -*- coding: utf-8 -*-
import os, json, uuid, datetime, re
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, Response, abort
from werkzeug.utils import secure_filename

APP_DIR = Path(__file__).resolve().parent
DATA_ROOT = Path(os.getenv("DATA_ROOT", "/tmp/kanpo_ai"))
UPLOAD_DIR = DATA_ROOT / "uploads"
DATA_DIR = DATA_ROOT / "data"
UPLOAD_DIR.mkdir(exist_ok=True, parents=True)
DATA_DIR.mkdir(exist_ok=True, parents=True)

BASIC_AUTH_USERNAME = os.getenv("BASIC_AUTH_USERNAME", "admin")
BASIC_AUTH_PASSWORD = os.getenv("BASIC_AUTH_PASSWORD", "changeme")
SECRET_KEY = os.getenv("FLASK_SECRET", "dev")


# --- 性別に応じた注意文フィルタ（男性では妊娠関連を非表示） ---
import re as _re_mod
def _filter_script_for_sex(script, sex):
    if not isinstance(script, dict):
        return script
    w = script.get("watch","") or ""
    if (sex or "").lower() not in ["female","woman","女性","女"]:
        w = _re_mod.sub(r"妊娠中[^。]*。?", "", w)
    return {**script, "watch": w.strip()}
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

# --- LLMで候補を抽出（トップ5まで） ---
def llm_pick_candidates(form, sex, axes, qxs, allowed_formulas):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return [], None  # キーが無ければ未実行
    try:
        from openai import OpenAI
        import json as _json
        client = OpenAI(api_key=api_key)

        user = {
            "sex": sex,
            "age": form.get("age",""),
            "region": form.get("region",""),
            "chief": form.get("chief_complaint",""),
            "axes": axes,
            "qxs": qxs,
            "allowed_formulas": list(allowed_formulas)
        }

        sys_prompt = (
            "あなたは漢方薬局のベテラン薬剤師です。"
            "候補リストを再評価し、必要なら並べ替え、"
            "各候補の 理由・薬膳（推奨/控え）・生活・面談深掘り をJSONで返してください。"
            "さらに『患者向け体質説明』は主訴に直結する形で、初心者薬剤師がそのまま読み上げられる3〜6文で作ってください。"
            "説明は (1)主訴に対して何を整える方針か、(2)なぜその証が主訴に関係するのか、(3)今日からできる具体策、の順で。"
            "男性には妊娠関連の注意は出さないでください。"
        )

        user = {"sex": sex, "chief": chief, "axes": axes, "qxs": qxs,
                "candidates": [c.get("name") for c in candidates if isinstance(c, dict)]}

        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        resp = client.chat.completions.create(
            model=model, temperature=0.3,
            messages=[{"role":"system","content":sys_prompt},
                      {"role":"user","content":_json.dumps(user, ensure_ascii=False)}]
        )
        content = resp.choices[0].message.content

        try:
            parsed = _json.loads(content)
        except Exception:
            parsed = {"llm_text": content}

        reranked = parsed.get("reranked") if isinstance(parsed, dict) else None
        advice   = parsed.get("advice")   if isinstance(parsed, dict) else {}
        patient_summary = parsed.get("patient_summary") if isinstance(parsed, dict) else ""

        if reranked:
            base_map = {c.get("name"): c for c in candidates if isinstance(c, dict)}
            new = []
            for i, item in enumerate(reranked):
                name = item.get("name")
                if not name: continue
                base = base_map.get(name, {})
                script = _filter_script_for_sex(base.get("script", {}), sex)
                new.append({
                    "name": name,
                    "score": base.get("score", 0) + max(0, 3 - i),
                    "script": script,
                    "pharmacist_tip": base.get("pharmacist_tip",""),
                    "ai_reason": item.get("reason",""),
                    "foods_good": (advice.get(name, {}) or {}).get("foods_good", []),
                    "foods_avoid": (advice.get(name, {}) or {}).get("foods_avoid", []),
                    "lifestyle":  (advice.get(name, {}) or {}).get("lifestyle", []),
                    "counsel_points": (advice.get(name, {}) or {}).get("counsel_points", [])
                })
            if new:
                assessment["candidates"] = new
                assessment["chosen"] = new[0]["name"]

        if patient_summary:
            if (sex or "").lower() not in ["female","woman","女性","女"]:
                import re as __re
                patient_summary = __re.sub(r"妊娠中[^。]*。?", "", patient_summary)
            assessment["patient_summary"] = patient_summary

        assessment["llm_raw"] = parsed
        return assessment

    except Exception as e:
        assessment["llm_error"] = f"{type(e).__name__}: {e}"
        return assessment

# ---------------- ルーティング ----------------
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())
    uploads = {"tongue": [], "face": [], "body": [], "nails": []}
    # proper mapping
    pairs = [("tongue_images","tongue"),("face_images","face"),("body_images","body"),("nails_images","nails")]
    for field,key in pairs:
        files = request.files.getlist(field)
        for f in files:
            if not f or not getattr(f, "filename", ""): continue
            fname = f"{rec_id}_{secure_filename(f.filename)}"
            f.save(str(UPLOAD_DIR / fname))
            uploads[key].append(f"/uploads/{fname}")

    form = request.form.to_dict()
    sex = form.get("sex","")
    assessment = score_and_choose(form, uploads, sex)
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
        "ai_assessment": assessment,
        "inspection_uploads": uploads,
        "inspection_notes": {
            "tongue_note": form.get("tongue_note",""),
            "face_note": form.get("face_note",""),
            "body_note": form.get("body_note",""),
            "nails_note": form.get("nails_note","")
        }
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
