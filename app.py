# -*- coding: utf-8 -*-
import os, json, uuid, datetime
from pathlib import Path
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, send_from_directory, abort
from werkzeug.utils import secure_filename

# Config
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

def check_auth(username, password):
    return username == BASIC_AUTH_USERNAME and password == BASIC_AUTH_PASSWORD

def authenticate():
    from flask import Response
    return Response("Auth required", 401, {"WWW-Authenticate": 'Basic realm="Restricted"'} )

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

def heuristic(form):
    # Read form values
    jitsu_kyo = form.get("jitsu_kyo","")
    kan_netsu = form.get("kan_netsu","")
    hyo_ri = form.get("hyo_ri","")

    qi = form.get("qi","normal")
    xue = form.get("xue","normal")
    sui = form.get("sui","normal")

    # pulse, face, tongue
    pulse_strength = form.get("pulse_strength","")  # strong/normal/weak
    pulse_rate = form.get("pulse_rate","")          # rapid/normal/slow
    pulse_quality = form.get("pulse_quality","")    # wiry/slippery/rough/none

    face_color = form.get("face_color","")          # pale/red/sallow/dark

    tongue_color = form.get("tongue_color","")
    tongue_body = form.get("tongue_body","")
    tongue_coat = form.get("tongue_coat","")
    tongue_moisture = form.get("tongue_moisture","")

    candidates, rationale = [], []

    # Basic axes
    if jitsu_kyo == "kyo" and kan_netsu == "kan":
        if qi == "deficiency" and sui in ("retention","deficiency"):
            candidates += ["真武湯", "補中益気湯"]
            rationale.append("虚＋寒＋気虚＋水の偏り → 温中・補気・利水")
        elif qi == "deficiency":
            candidates += ["人参湯", "六君子湯"]
            rationale.append("虚＋寒＋気虚 → 温中・補気")
    if jitsu_kyo == "kyo" and kan_netsu == "netsu":
        if qi == "deficiency":
            candidates += ["竹葉石膏湯", "清暑益気湯"]
            rationale.append("虚＋熱＋気虚 → 清熱・補気")
        if xue == "deficiency":
            candidates += ["当帰芍薬散"]
            rationale.append("虚熱＋血虚 → 補血滋陰")
    if jitsu_kyo == "jitsu" and xue == "stasis":
        candidates += ["桂枝茯苓丸", "桃核承気湯"]
        rationale.append("実＋瘀血 → 活血化瘀")
    if sui == "retention" and kan_netsu == "kan":
        candidates += ["五苓散"]
        rationale.append("水滞＋寒 → 利水調整")

    # Pulse modifiers
    if pulse_strength == "weak":
        if "補中益気湯" not in candidates: candidates.append("補中益気湯")
        rationale.append("脈が弱 → 虚傾向、補気を考慮")
    if pulse_rate == "rapid":
        rationale.append("数脈 → 熱傾向")
    if pulse_quality == "wiry":
        if "逍遙散" not in candidates: candidates.append("逍遙散")
        rationale.append("弦脈 → 肝気鬱結/気滞傾向")
    if face_color == "pale":
        if "当帰芍薬散" not in candidates and xue!="stasis":
            candidates.append("当帰芍薬散")
            rationale.append("顔面蒼白 → 血虚傾向")

    # Tongue hints
    if tongue_color == "pale" and tongue_body in ("scalloped","swollen"):
        if "六君子湯" not in candidates: candidates.append("六君子湯")
        rationale.append("淡舌＋歯痕/腫大 → 脾気虚・水滞傾向")
    if tongue_coat == "yellow":
        rationale.append("黄苔 → 熱・湿熱傾向")

    # cleanup
    seen = set()
    dedup = []
    for c in candidates:
        if c not in seen:
            dedup.append(c); seen.add(c)
    candidates = dedup[:3]

    pattern = {
        "八綱": {"実虚": jitsu_kyo, "寒熱": kan_netsu, "表裏": hyo_ri},
        "気血水": {"気": qi, "血": xue, "水": sui},
        "視診補助": {
            "脈": {"力": pulse_strength, "速さ": pulse_rate, "性状": pulse_quality},
            "顔色": face_color,
            "舌": {"色": tongue_color, "体": tongue_body, "苔": tongue_coat, "湿": tongue_moisture},
        }
    }
    return {
        "pattern": pattern,
        "candidates": candidates or ["条件が少なく候補を絞り切れませんでした"],
        "rationale": " / ".join(rationale) or "情報不足のため一般的候補を提示",
        "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
    }

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    rec_id = str(uuid.uuid4())

    # Handle optional uploads
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
    pre = heuristic(form)

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
        "ai_preassessment": pre,
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
