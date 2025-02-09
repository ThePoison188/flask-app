import os
import sqlite3
import random
import spacy
import nltk
import PyPDF2
import docx
from flask import Flask, render_template, request, redirect

app = Flask(__name__)

# Configure upload folder
UPLOAD_FOLDER = 'uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['ALLOWED_EXTENSIONS'] = {'txt', 'pdf', 'docx'}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Load NLP model
nlp = spacy.load('en_core_web_sm')

# Download WordNet
nltk.download('wordnet')
nltk.download('omw-1.4')


# Initialize the database
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS flashcards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            term TEXT NOT NULL,
            definition TEXT NOT NULL,
            UNIQUE(term, definition)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS quiz_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            user_answer TEXT NOT NULL,
            correct_answer TEXT NOT NULL,
            is_correct BOOLEAN NOT NULL
        )
    ''')

    conn.commit()
    conn.close()


init_db()


# Function to check allowed file types
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# File parsing functions
def parse_pdf(file_path):
    with open(file_path, 'rb') as f:
        reader = PyPDF2.PdfReader(f)
        return "\n".join([page.extract_text() or "" for page in reader.pages])


def parse_docx(file_path):
    doc = docx.Document(file_path)
    return "\n".join([para.text for para in doc.paragraphs])


def parse_txt(file_path):
    with open(file_path, 'r', encoding='utf-8') as file:
        return file.read()


# Save uploaded file to database
def save_file(filename):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('INSERT OR IGNORE INTO files (filename) VALUES (?)', (filename,))
    conn.commit()
    conn.close()


# Generate flashcards
def generate_flashcards(text):
    from nltk.corpus import wordnet

    doc = nlp(text)
    flashcards = {}

    for np in doc.noun_chunks:
        term = np.text.strip()
        if term and term not in flashcards:
            synsets = wordnet.synsets(term)
            definition = synsets[0].definition() if synsets else "Definition not found."
            flashcards[term] = definition

    return flashcards


# Save flashcards to database
def save_flashcards(flashcards):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    for term, definition in flashcards.items():
        cursor.execute('INSERT OR IGNORE INTO flashcards (term, definition) VALUES (?, ?)', (term, definition))
    conn.commit()
    conn.close()


# Generate quiz questions
def generate_quiz(text):
    doc = nlp(text)
    quiz = []

    sentences = [sent.text for sent in doc.sents]
    keywords = [np.text for np in doc.noun_chunks]

    for sentence in sentences:
        for keyword in keywords:
            if keyword in sentence:
                blank_sentence = sentence.replace(keyword, "___")
                choices = random.sample(keywords, min(3, len(keywords)))
                if keyword not in choices:
                    choices.append(keyword)
                random.shuffle(choices)

                quiz.append((blank_sentence, keyword, choices))
                break

    return quiz


# Save quiz results to database
@app.route('/submit_quiz', methods=['POST'])
def submit_quiz():
    user_answers = request.form
    results = []

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    for question, correct_answer in request.form.items():
        user_answer = user_answers[question]
        is_correct = user_answer == correct_answer
        results.append((question, user_answer, correct_answer, is_correct))

        cursor.execute('''
            INSERT INTO quiz_results (question, user_answer, correct_answer, is_correct)
            VALUES (?, ?, ?, ?)
        ''', (question, user_answer, correct_answer, is_correct))

    conn.commit()
    conn.close()

    return render_template('quiz_results.html', results=results)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/dashboard')
def dashboard():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute('SELECT filename FROM files')
    files = [row[0] for row in cursor.fetchall()]

    cursor.execute('SELECT term, definition FROM flashcards')
    flashcards = dict(cursor.fetchall())

    conn.close()

    return render_template('dashboard.html', files=files, flashcards=flashcards)


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.url)

    file = request.files['file']

    if file and allowed_file(file.filename):
        filename = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
        file.save(filename)
        save_file(file.filename)

        text = parse_pdf(filename) if filename.endswith('.pdf') else \
            parse_docx(filename) if filename.endswith('.docx') else \
                parse_txt(filename)

        flashcards = generate_flashcards(text)
        save_flashcards(flashcards)

        quiz = generate_quiz(text)

        return render_template('dashboard.html', text=text, flashcards=flashcards, quiz=quiz)

    return 'File type not allowed'


if __name__ == "__main__":
    app.run(debug=True)