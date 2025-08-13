from flask import Flask, render_template, request, redirect, url_for
import ai_logic

app = Flask(__name__)

records = []

@app.route('/')
def index():
    return render_template('index.html', records=records)

@app.route('/new', methods=['GET', 'POST'])
def new():
    if request.method == 'POST':
        form_data = request.form.to_dict()
        result = ai_logic.process(form_data)
        records.append(result)
        return redirect(url_for('index'))
    return render_template('new.html')

@app.route('/detail/<int:record_id>')
def detail(record_id):
    record = records[record_id]
    return render_template('detail.html', record=record)

if __name__ == '__main__':
    app.run(debug=True)
