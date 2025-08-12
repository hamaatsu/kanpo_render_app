import os
from flask import Flask, render_template, request, redirect, url_for
from openai import OpenAI
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
USE_AI = True if OPENAI_API_KEY else False

if USE_AI:
    client = OpenAI(api_key=OPENAI_API_KEY)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/submit', methods=['POST'])
def submit():
    chief_complaint = request.form.get('chief_complaint')
    sex = request.form.get('sex')
    photo_files = {}
    for field in ['face_photo', 'tongue_photo', 'nail_photo']:
        file = request.files.get(field)
        if file and file.filename != "":
            filename = secure_filename(file.filename)
            path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(path)
            photo_files[field] = path

    advice = "AI未設定のため、ルールベースでのアドバイスです。"
    if USE_AI:
        prompt = f"""
        あなたは漢方カウンセラーです。主訴に直結する実践的アドバイスを日本語でJSON形式で返してください。
        主訴: {chief_complaint}
        性別: {sex}
        写真情報: {list(photo_files.keys())}
        """
        try:
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7
            )
            advice = response.choices[0].message.content
        except Exception as e:
            advice = f"AIエラー: {str(e)}"

    return render_template('result.html', 
                           chief_complaint=chief_complaint,
                           sex=sex,
                           photos=photo_files,
                           advice=advice)

if __name__ == '__main__':
    app.run(debug=True)
