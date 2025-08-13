
from flask import Flask, render_template, request, jsonify
import json

app = Flask(__name__)

with open("complaint_map.json", encoding="utf-8") as f:
    complaint_map = json.load(f)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/stage1", methods=["POST"])
def stage1():
    data = request.get_json()
    complaint = data.get("complaint")
    if complaint in complaint_map:
        return jsonify({
            "stage": 1,
            "complaint": complaint,
            "candidates": complaint_map[complaint]["候補漢方"],
            "description": complaint_map[complaint]["説明"]
        })
    else:
        return jsonify({"stage": 1, "candidates": [], "description": "該当なし"})

@app.route("/stage2", methods=["POST"])
def stage2():
    data = request.get_json()
    selected_candidates = data.get("candidates", [])
    hachi_ko = data.get("hachi_ko")
    kiketsusui = data.get("kiketsusui")
    tongue = data.get("tongue")
    pulse = data.get("pulse")
    # 本来はここで分類ロジックに基づき絞り込み
    refined = selected_candidates[:5]
    return jsonify({"stage": 2, "refined_candidates": refined})

@app.route("/stage3", methods=["POST"])
def stage3():
    data = request.get_json()
    final_candidates = data.get("final_candidates", [])
    complaint = data.get("complaint")
    # 主訴を重視したアドバイス生成（簡易版）
    advice = f"{complaint}の症状に対しては、生活習慣の見直し（食事時間・ストレス軽減）や温かい飲み物の摂取が有効です。"
    return jsonify({"stage": 3, "final_candidates": final_candidates, "advice": advice})

if __name__ == "__main__":
    app.run(debug=True)
