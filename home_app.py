import os
from flask import Flask, render_template, request, send_file, session, redirect, url_for
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
import pdfplumber
import docx
import google.generativeai as genai
from fpdf import FPDF

# Configure Gemini API
genai.configure(api_key="AIzaSyDLs4jDhMVdFibW6f__a36DGo1MpWhtRY4")
model = genai.GenerativeModel("models/gemini-1.5-pro")

# App setup
app = Flask(__name__)
app.secret_key = 'a_combined_secret_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# File settings
app.config['UPLOAD_FOLDER_HOME'] = 'uploads_home/'
app.config['UPLOAD_FOLDER_QUIZ'] = 'uploads_quiz/'
app.config['GENERATED_FOLDER'] = 'generated_questions/'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'txt', 'docx'}

os.makedirs(app.config['UPLOAD_FOLDER_HOME'], exist_ok=True)
os.makedirs(app.config['UPLOAD_FOLDER_QUIZ'], exist_ok=True)
os.makedirs(app.config['GENERATED_FOLDER'], exist_ok=True)


# User Model
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)


# Helper functions
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def extract_text_from_file(file_path):
    ext = file_path.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        with pdfplumber.open(file_path) as pdf:
            return ''.join([page.extract_text() for page in pdf.pages if page.extract_text()])
    elif ext == 'docx':
        return ' '.join([p.text for p in docx.Document(file_path).paragraphs])
    elif ext == 'txt':
        with open(file_path, 'r') as file:
            return file.read()
    return None


def generate_questions(input_text, num_questions, difficulty, question_type):
    prompt = f"""
    You are an AI assistant helping the user generate {question_type} questions based on the following text:
    '{input_text}'
    Please generate {num_questions} {question_type} questions from the text at a {difficulty} difficulty level.

    For Fill in the Blanks, provide the question with underscores and the answer in brackets at the end.
    For MCQs: Question + four options (A, B, C, D), mark correct option like "[C]".
    For Short Answers: Question followed by concise answer in parentheses.

    Separate each question with '##---##'.
    """
    response = model.generate_content(prompt).text.strip()
    return [q.strip() for q in response.split('##---##') if q.strip()]


def generate_quiz_mcqs(input_text, num_questions, difficulty):
    prompt = f"""
    Generate {num_questions} MCQs from this text at {difficulty} level:

    '{input_text}'

    Format:
    Question: ...
    A) ...
    B) ...
    C) ...
    D) ...
    Correct Answer: A/B/C/D

    Separate each MCQ with '##---##'
    """
    response = model.generate_content(prompt).text.strip()
    mcqs_raw = response.split('##---##')
    mcqs_data = []
    for mcq_raw in mcqs_raw:
        lines = mcq_raw.strip().split('\n')
        if len(lines) >= 6 and lines[0].startswith("Question:"):
            question = lines[0].split("Question:")[1].strip()
            options = {}
            correct_answer = None
            for line in lines[1:]:
                if line.startswith("A)"):
                    options['A'] = line[2:].strip()
                elif line.startswith("B)"):
                    options['B'] = line[2:].strip()
                elif line.startswith("C)"):
                    options['C'] = line[2:].strip()
                elif line.startswith("D)"):
                    options['D'] = line[2:].strip()
                elif line.startswith("Correct Answer:"):
                    correct_answer = line.split("Correct Answer:")[1].strip()
            if question and len(options) == 4 and correct_answer in ['A', 'B', 'C', 'D']:
                mcqs_data.append({'question': question, 'options': options, 'correct_answer': correct_answer})
    return mcqs_data


# Authentication helpers
def is_logged_in():
    return 'user_id' in session


# Routes
@app.route('/')
def index():
    return render_template('index.html')


@app.route('/help')
def help():
    return render_template('help.html')


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        if User.query.filter_by(username=username).first():
            return "Username already exists."
        user = User(username=username, password=generate_password_hash(password))
        db.session.add(user)
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('signup.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('index'))
        return "Invalid credentials."
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('index'))


@app.route('/generate_test', methods=['POST'])
def generate_combined_test():
    if not is_logged_in():
        return redirect(url_for('login'))

    if 'file' not in request.files:
        return "No file part"
    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER_HOME'], filename)
        file.save(file_path)
        text = extract_text_from_file(file_path)
        if not text:
            return "Could not extract text."

        generated_questions = {}

        # Fill in the blanks
        fib_num = int(request.form['fib_num_questions'])
        if fib_num > 0:
            fib_diff = request.form['fib_difficulty']
            generated_questions['fill_in_the_blanks'] = generate_questions(text, fib_num, fib_diff, "fill in the blank")

        # MCQs
        mcq_num = int(request.form['mcq_num_questions'])
        if mcq_num > 0:
            mcq_diff = request.form['mcq_difficulty']
            generated_questions['mcqs'] = generate_questions(text, mcq_num, mcq_diff, "multiple choice")

        # Short Answers
        short_num = int(request.form['short_answer_num_questions'])
        if short_num > 0:
            short_diff = request.form['short_answer_difficulty']
            generated_questions['short_answers'] = generate_questions(text, short_num, short_diff, "short answer")

        if not generated_questions:
            return "No questions generated."

        all_questions = []
        for qlist in generated_questions.values():
            all_questions.extend(qlist)
        download_data = "|||".join(all_questions)

        return render_template('generated_test.html', generated_questions=generated_questions,
                               download_data=download_data)
    return "Invalid file"


@app.route('/download/<file_type>')
def download_combined_file(file_type):
    data = request.args.get('data')
    if not data:
        return "No data to download."

    questions = data.split("|||")

    if file_type == 'pdf':
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        for q in questions:
            pdf.multi_cell(0, 10, q)
            pdf.ln()
        path = os.path.join(app.config['GENERATED_FOLDER'], 'generated_questions.pdf')
        pdf.output(path)
        return send_file(path, as_attachment=True, mimetype='application/pdf',
                        download_name='generated_questions.pdf')

    elif file_type == 'txt':
        path = os.path.join(app.config['GENERATED_FOLDER'], 'generated_questions.txt')
        with open(path, 'w') as f:
            f.write("\n\n".join(questions))
        return send_file(path, as_attachment=True, mimetype='text/plain',
                        download_name='generated_questions.txt')

    return "Invalid format."


@app.route('/quiz')
def quiz_form():
    return render_template('quiz.html')


@app.route('/generate_mcqs', methods=['POST'])
def generate_quiz():
    if not is_logged_in():
        return redirect(url_for('login'))

    if 'file' not in request.files:
        return "No file"
    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER_QUIZ'], filename)
        file.save(path)
        text = extract_text_from_file(path)
        if not text:
            return "Error reading file"
        num = int(request.form['num_questions'])
        diff = request.form['difficulty']
        mcqs = generate_quiz_mcqs(text, num, diff)
        session['quiz_questions'] = mcqs
        session['score'] = 0
        session['current_question'] = 0
        return render_template('quiz_attempt.html', question=mcqs[0], question_number=1,
                               total_questions=len(mcqs))
    return "Invalid format"


@app.route('/submit_answer', methods=['POST'])
def submit_quiz_answer():
    if 'quiz_questions' not in session:
        return "Session expired"

    questions = session['quiz_questions']
    idx = session['current_question']
    user_ans = request.form.get('answer')
    if user_ans == questions[idx]['correct_answer']:
        session['score'] += 1
    session['current_question'] += 1

    if session['current_question'] < len(questions):
        return render_template('quiz_attempt.html',
                               question=questions[session['current_question']],
                               question_number=session['current_question'] + 1,
                               total_questions=len(questions))
    else:
        score = session['score']
        total = len(questions)
        session.pop('quiz_questions', None)
        session.pop('score', None)
        session.pop('current_question', None)
        return render_template('quiz_results.html', score=score, total_questions=total, all_questions=questions)


if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(debug=True)