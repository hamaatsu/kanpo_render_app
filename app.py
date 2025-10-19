# ===== 必要なimport =====
import os, json, traceback
from flask import Flask, render_template, request, jsonify
from openai import OpenAI

app = Flask(__name__)
client = OpenAI()

# ====== トップ画面（今の index.html を返す）======
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# ====== 開発中のキャッシュ無効化（任意。不要なら削除OK）======
@app.after_request
def add_no_cache_headers(resp):
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["Expires"] = "0"
    return resp

# ====== 許可方剤（allowlist）の読み込み。inventory.json があれば優先 ======
def load_allowed_formulas():
    try:
        with open("inventory.json", "r", encoding="utf-8") as f:
            obj = json.load(f)
            arr = obj.get("allowed_formulas") or obj.get("allowed") or []
            if isinstance(arr, list) and arr:
                return arr
    except Exception:
        pass
    # フォールバック（あなたが以前提示した104処方）
    return [
        "安中散料","黄連解毒湯","黄連湯","黄耆建中湯","温経湯","温清飲","加味帰脾湯","加味逍遙散料",
        "葛根湯","甘麦大棗湯","帰脾湯","牛車腎気丸料","啓脾湯","桂枝加黄耆湯","桂枝加竜骨牡蛎湯",
        "桂枝加苓朮附湯","桂枝加芍薬大黄湯","桂枝加芍薬湯","桂枝人参湯","桂枝湯","桂枝茯苓丸料",
        "桂枝茯苓丸料加ヨク苡仁","荊芥連翹湯","五積散料","五淋散料","五苓散料","呉茱萸湯","香蘇散料",
        "三黄瀉心湯","三物黄_湯","酸棗仁湯","四逆散料","四物湯","滋陰降火湯","滋陰至宝湯","治打撲一方",
        "七物降下湯","柴胡加竜骨牡蛎湯","柴胡桂枝乾姜湯","柴胡桂枝湯","柴朴湯","柴苓湯","十全大補湯",
        "十味敗毒湯","潤腸湯","女神散料","小建中湯","小柴胡湯","小承気湯","小青竜湯","消風散料",
        "神秘湯","人参湯","人参養栄湯","清暑益気湯","清上防風湯","清上ケン痛湯","清心蓮子飲","清肺湯",
        "疎経活血湯","大黄牡丹皮湯","大建中湯","大柴胡湯","知柏地黄丸料","竹茹温胆湯","猪苓湯",
        "猪苓湯合四物湯","調胃承気湯","通導散料","釣藤散料","桃核承気湯","当帰飲子","当帰建中湯",
        "当帰四逆加呉茱萸生姜湯","当帰湯","当帰芍薬散料","二陳湯","二朮湯","白虎加人参湯","麦門冬湯",
        "八味地黄丸料","半夏厚朴湯","半夏白朮天麻湯","半夏瀉心湯","平胃散料","補中益気湯","防風通聖散料",
        "防已黄耆湯","麻子仁丸料","抑肝散料","抑肝散料加陳皮半夏","竜胆瀉肝湯","苓桂朮甘湯","苓姜朮甘湯",
        "六君子湯","炙甘草湯","芍薬甘草湯","茵陳五苓散料","茵陳蒿湯","茯苓飲合半夏厚朴湯",
        "キュウ帰調血飲","キュウ帰調血飲第一加減","キュウ帰膠艾湯","ヨク苡仁湯"
    ]

ALLOWED = load_allowed_formulas()

# ====== SYSTEM プロンプト（日本語・JSON厳守・ハルシ防止）======
SYSTEM_PROMPT = """
あなたは薬局の漢方相談を支援するAI薬剤師です。下記の制約を厳守して回答してください。

【出力形式】
- 必ず JSON 1オブジェクトのみを返す（前後の説明文やコードブロックは禁止）
- スキーマ：
{
  "formula_symptom": {"name": "方剤名", "reason": "120〜200字の根拠"},
  "formula_sho":     {"name": "方剤名", "reason": "120〜200字の根拠"},
  "formula_mixed":   {"name": "方剤名", "reason": "120〜200字の根拠"},
  "pharmacist_advice": "患者指導コメント（生活・服薬・注意点など200〜300字）"
}

【選方ルール】
- 候補は必ず allowlist（allowed_formulas）内から選ぶ。リスト外は選ばない。
- 1つ目（formula_symptom）は症状（主訴）への適合を最優先。
- 2つ目（formula_sho）は証（体質％）への適合を最優先。
- 3つ目（formula_mixed）は症状・証・安全性・体力のバランスで折衷案。
- 同一患者に3剤すべてが全く同じになることは避ける（重複回避）。
- それぞれの reason には「症状のキーワード」「証（気虚・気滞・瘀血・水滞・陰陽など）」「安全面の配慮」を簡潔に含める。
- 指導コメントには、生活指導（食事・睡眠・冷え/のぼせ対策）、服薬タイミング、想定副作用/禁忌（妊娠・出血傾向など）を含める。

【安全】
- 妊娠/授乳/抗凝固薬/消化性潰瘍などのリスクが疑われる場合は、reason/コメント内で簡潔に注意喚起。
- 迷う場合はよりマイルドな方剤を優先。

【厳守】
- JSON以外の文字を出力しない。
"""

# ====== ユーザー（患者）情報 → プロンプト整形 ======
def build_user_prompt(payload: dict) -> str:
    """
    フロントから送られる JSON:
    {
      "name": "...", "age": 34, "gender": "女性",
      "chief": {
        "selections": [
          {"category":"婦人科・月経","symptoms":["月経痛","PMS"]},
          {"category":"痛み・筋骨格","symptoms":["肩こり"]}
        ],
        "detail": "自由記入..."
      },
      "constitution": {"気虚体質":40, "血虚体質":20, ...}  # 任意（無い場合あり）
    }
    """
    name = payload.get("name") or ""
    age = payload.get("age")
    gender = payload.get("gender") or ""

    # 主訴（カテゴリ別）
    chief = payload.get("chief") or {}
    selections = chief.get("selections") or []
    detail = (chief.get("detail") or "").strip()

    # 体質％
    constitution = payload.get("constitution") or {}

    # 人が読みやすい文章も用意（モデルに状況を伝えるため）
    chief_lines = []
    for item in selections:
        cat = item.get("category") or ""
        syms = item.get("symptoms") or []
        if syms:
            chief_lines.append(f"- {cat}: {', '.join(syms)}")
    chief_text = "\n".join(chief_lines) if chief_lines else "-（未選択）"

    const_lines = [f"- {k}: {v}%" for k, v in constitution.items()]
    const_text = "\n".join(const_lines) if const_lines else "-（データなし）"

    # allowed_formulas は明示的に与えて、モデルの選択肢を限定
    allow_json = json.dumps(ALLOWED, ensure_ascii=False)

    user_prompt = f"""
【患者情報】
- 氏名: {name}
- 年齢: {age}
- 性別: {gender}

【主訴（複数カテゴリ可）】
{chief_text}
- 自由記入: {detail}

【証（体質％）】
{const_text}

【allowed_formulas（この中からのみ選ぶ）】
{allow_json}

上記の情報をもとに、SYSTEM仕様どおりの JSON を1オブジェクトで返してください。
""".strip()

    return user_prompt

# ====== OpenAI 呼び出し ======
def call_openai(messages):
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    resp = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.0,
        top_p=1.0,
        response_format={"type": "json_object"},
        max_tokens=900
    )
    return resp.choices[0].message.content

def safe_json(content: str):
    try:
        return json.loads(content)
    except Exception:
        return {"error": "LLMのJSON解析に失敗しました", "raw": content}

# ====== /analyze：フロントからの送信を受け→3剤＋コメントを返す ======
@app.route("/analyze", methods=["POST"])
def analyze():
    # JSON/フォームの両対応
    try:
        data = request.get_json() if request.is_json else request.form.to_dict()
    except Exception as e:
        return jsonify({"error": f"データ受信エラー: {str(e)}"}), 400

    try:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_prompt(data)},
        ]
        raw = call_openai(messages)
        parsed = safe_json(raw)

        # 念のため allowed 外の方剤をフィルタ（安全網）
        if isinstance(parsed, dict):
            for key in ("formula_symptom","formula_sho","formula_mixed"):
                if parsed.get(key) and parsed[key].get("name") not in ALLOWED:
                    parsed[key]["name"] = ""
                    parsed[key]["reason"] = "allowed_formulas外だったため無効化"

        return jsonify(parsed)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"サーバ処理エラー: {str(e)}"}), 500
