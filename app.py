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
    # フォールバック（ご提示の104処方。名称は変更していません）
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
# 許可リストの厳格適用スイッチ（既定OFF=減らさない）
ENFORCE_ALLOWED = os.getenv("ENFORCE_ALLOWED", "false").lower() == "true"

# ====== SYSTEM プロンプト（日本語・JSON厳守・ハルシ防止）======
SYSTEM_PROMPT = """
あなたは薬剤師であり、漢方の専門家として問診データをもとに、
症状主体・証主体・折衷案の3つの観点から最適な漢方薬を提案してください。

出力は必ず **有効なJSON形式のみ** で返してください。
説明文や補足文、日本語の前置きなどは一切出力してはいけません。
【厳守】JSON以外の文字を出力しない。

出力フォーマットは以下の通りです。

{
  "formula_symptom": {
    "name": "症状に基づく最適な漢方薬名（allowed_formulasから選ぶ）",
    "reason": "なぜそれが選ばれたのか。患者の証と症状の両方を踏まえて具体的に説明。例：『あなたの証は気滞で、ストレスや胸のつかえがあるため、気の巡りを整える加味逍遙散を選びました。』妊婦禁忌の場合のみ『妊婦禁忌』と明記。",
    "is_contraindicated_pregnancy": true または false
  },
  "formula_sho": {
    "name": "証（体質）に基づく最適な漢方薬名（allowed_formulasから選ぶ）",
    "reason": "体質判定結果をもとに、どのような証に対応しているか、なぜこの処方が合うのかを具体的に説明。例：『あなたの証は血虚で、顔色の悪さや疲れやすさがあるため、血を補う四物湯を選びました。』妊婦禁忌の場合のみ『妊婦禁忌』と明記。",
    "is_contraindicated_pregnancy": true または false
  },
  "formula_mixed": {
    "name": "症状と証の折衷から導かれる漢方薬名（allowed_formulasから選ぶ）",
    "reason": "症状と証の両方を考慮したうえで、全体のバランスから最も妥当と判断した理由を説明。例：『気虚とストレスの両方が関係しているため、気を補いながら気の巡りを整える補中益気湯を選びました。』妊婦禁忌の場合のみ『妊婦禁忌』と明記。",
    "is_contraindicated_pregnancy": true または false
  },
  "guidance": {
    "療養の要点": "漢方薬剤師としての専門的な養生指導。一般的な助言（例：睡眠を取りましょう）は避け、処方の薬効・証に基づく具体的な方法を述べる。例：『冷たい飲食を避け、温かい汁物を中心にする』『気滞傾向があるため、深呼吸や軽い運動で気を巡らせる』など。",
    "おすすめ薬膳食材": [
      {"name": "食材名", "reason": "選定理由（処方や証との関連を具体的に）"},
      {"name": "食材名", "reason": "選定理由"},
      {"name": "食材名", "reason": "選定理由"},
      {"name": "食材名", "reason": "選定理由"},
      {"name": "食材名", "reason": "選定理由"}
    ]
  }
}

【出力安定化ルール】
- 同じ入力には同じ出力を返すこと。
- 複数候補が同等の場合は allowed_formulas リスト内でインデックスが小さい方を採用。
- 妊婦禁忌の処方（例：桃核承気湯、桂枝茯苓丸、防風通聖散、大黄牡丹皮湯、大柴胡湯など）の場合のみ reason に「妊婦禁忌」と明記する。
- JSON以外の文字を絶対に出力しない。

+さらに次を厳守すること：
- 体質スコアのうち **50点以上の軸（上位軸）** を必ず考慮し、reason に **「どの軸（例：陽熱・水滞・気虚）」に対して薬効が対応するか** を明記する。
- 「症状優先」でも、**上位軸と明らかに矛盾する処方**は選ばない（選ぶ場合はその矛盾をどう担保するかを具体的に説明）。
- 「折衷案」は **上位1〜2軸** を同時にカバーする処方を第一候補とする（例：陽熱＋水滞）。

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
      "constitution": {"気虚体質":60, "血虚体質":40, ...}  # 0〜100 の体質スコア（任意）
    }
    """
    name = payload.get("name") or ""
    age = payload.get("age")
    gender = payload.get("gender") or ""

    # 主訴（カテゴリ別）
    chief = payload.get("chief") or {}
    selections = chief.get("selections") or []
    detail = (chief.get("detail") or "").strip()

    # 体質スコア（0〜100）
    constitution = payload.get("constitution") or {}

    # 人が読みやすい文章（モデルに状況を伝えるため）
    chief_lines = []
    for item in selections:
        cat = item.get("category") or ""
        syms = item.get("symptoms") or []
        if syms:
            chief_lines.append(f"- {cat}: {', '.join(syms)}")
    chief_text = "\n".join(chief_lines) if chief_lines else "-（未選択）"

    # ←← ここを“％”から「点」に変更
    const_lines = [f"- {k}: {v}点" for k, v in constitution.items()]
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

【証（体質スコア 0〜100）】
{const_text}
（※上位軸＝スコア50点以上を最優先で考慮してください）

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

        # 許可リスト外の処方を無効化するかはスイッチで制御（既定OFF）
        if isinstance(parsed, dict) and ENFORCE_ALLOWED:
            for key in ("formula_symptom","formula_sho","formula_mixed"):
                if parsed.get(key) and parsed[key].get("name") not in ALLOWED:
                    parsed[key]["name"] = ""
                    parsed[key]["reason"] = "allowed_formulas外だったため無効化"

        return jsonify(parsed)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": f"サーバ処理エラー: {str(e)}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)), debug=True)
