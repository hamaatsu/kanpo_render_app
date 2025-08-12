from flask import Flask, render_template, request, jsonify
import json

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/suggest', methods=['POST'])
def suggest():
    data = request.json
    symptoms = data.get('symptoms', [])
    suggestions = [f"提案: {s}" for s in symptoms]
    return jsonify({"suggestions": suggestions})

if __name__ == '__main__':
    app.run(debug=True)