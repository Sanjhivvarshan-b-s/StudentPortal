from flask import Flask, render_template, request, redirect, session, url_for
import sqlite3

app = Flask(__name__)
app.secret_key = 'super_secret_key'

# --- DATABASE SETUP ---
def get_db():
    conn = sqlite3.connect('school.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS classrooms (id INTEGER PRIMARY KEY, subject TEXT, teacher TEXT)')
    conn.execute('CREATE TABLE IF NOT EXISTS questions (id INTEGER PRIMARY KEY, classroom_id INTEGER, text TEXT, votes INTEGER)')
    conn.execute('CREATE TABLE IF NOT EXISTS enrollments (id INTEGER PRIMARY KEY, user_id INTEGER, classroom_id INTEGER)')
    conn.execute('CREATE TABLE IF NOT EXISTS votes (user_id INTEGER, question_id INTEGER, PRIMARY KEY (user_id, question_id))')
    
    # Dummy Data
    if conn.execute('SELECT count(*) FROM users').fetchone()[0] == 0:
        print("Creating dummy data...")
        conn.execute("INSERT INTO users (username, password, role) VALUES ('admin', 'admin123', 'admin')")
        conn.execute("INSERT INTO users (username, password, role) VALUES ('student', '1234', 'student')")
        conn.execute("INSERT INTO users (username, password, role) VALUES ('teacher', 'teach123', 'teacher')")
        conn.execute("INSERT INTO classrooms (subject, teacher) VALUES ('Math 101', 'teacher')")
        conn.commit()
    conn.close()

# --- LOGIN ---
@app.route('/', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username = ? AND password = ?', (username, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['username'] = user['username']
            if user['role'] == 'admin': return redirect('/admin')
            elif user['role'] == 'teacher': return redirect('/teacher')
            else: return redirect('/dashboard')
        else:
            return "Wrong password!"
    return render_template('login.html')

# --- ADMIN DASHBOARD ---
@app.route('/admin')
def admin_dashboard():
    if session.get('role') != 'admin': return redirect('/')
    
    conn = get_db()
    classes = conn.execute('SELECT * FROM classrooms').fetchall()
    students = conn.execute("SELECT * FROM users WHERE role='student'").fetchall()
    teachers = conn.execute("SELECT * FROM users WHERE role='teacher'").fetchall()
    questions = conn.execute('''
        SELECT questions.*, classrooms.subject AS class_subject
        FROM questions
        JOIN classrooms ON questions.classroom_id = classrooms.id
        ORDER BY questions.id DESC
    ''').fetchall()
    conn.close()
    return render_template('admin.html', classes=classes, students=students, teachers=teachers, questions=questions)

# --- ADMIN: CREATE ---
@app.route('/add_student', methods=['POST'])
def add_student():
    if session.get('role') != 'admin': return redirect('/')
    username = request.form['username']
    password = request.form['password']
    
    conn = get_db()
    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'student')", (username, password))
    conn.commit()
    conn.close()
    return redirect('/admin')

@app.route('/add_teacher', methods=['POST'])
def add_teacher():
    if session.get('role') != 'admin': return redirect('/')
    username = request.form['username']
    password = request.form['password']
    conn = get_db()
    conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, 'teacher')", (username, password))
    conn.commit()
    conn.close()
    return redirect('/admin')

@app.route('/add_course', methods=['POST'])
def add_course():
    if session.get('role') != 'admin': return redirect('/')
    subject = request.form['subject']
    teacher_username = request.form.get('teacher_username')
    conn = get_db()
    conn.execute("INSERT INTO classrooms (subject, teacher) VALUES (?, ?)", (subject, teacher_username or ''))
    conn.commit()
    conn.close()
    return redirect('/admin')

@app.route('/enroll_student', methods=['POST'])
def enroll_student():
    if session.get('role') != 'admin': return redirect('/')
    user_id = request.form['student_id']
    class_id = request.form['class_id']
    
    conn = get_db()
    existing = conn.execute('SELECT * FROM enrollments WHERE user_id=? AND classroom_id=?', (user_id, class_id)).fetchone()
    if not existing:
        conn.execute('INSERT INTO enrollments (user_id, classroom_id) VALUES (?, ?)', (user_id, class_id))
        conn.commit()
    conn.close()
    return redirect('/admin')

# --- NEW: DELETE STUDENT ---
@app.route('/delete_student/<int:user_id>')
def delete_student(user_id):
    if session.get('role') != 'admin': return redirect('/')
    conn = get_db()
    
    # 1. Delete the user
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    # 2. Cleanup: Delete their enrollments
    conn.execute('DELETE FROM enrollments WHERE user_id = ?', (user_id,))
    # 3. Cleanup: Delete their votes
    conn.execute('DELETE FROM votes WHERE user_id = ?', (user_id,))
    
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('admin_dashboard'))

# --- NEW: DELETE COURSE ---
@app.route('/delete_course/<int:class_id>')
def delete_course(class_id):
    if session.get('role') != 'admin': return redirect('/')
    conn = get_db()
    
    # 1. Delete the course
    conn.execute('DELETE FROM classrooms WHERE id = ?', (class_id,))
    # 2. Cleanup: Delete questions inside that course
    conn.execute('DELETE FROM questions WHERE classroom_id = ?', (class_id,))
    # 3. Cleanup: Delete student enrollments for this course
    conn.execute('DELETE FROM enrollments WHERE classroom_id = ?', (class_id,))
    
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('admin_dashboard'))


# --- STUDENT & CLASSROOM (No changes here) ---
@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session: return redirect('/')
    conn = get_db()
    my_classes = conn.execute('''
        SELECT classrooms.* FROM classrooms
        JOIN enrollments ON classrooms.id = enrollments.classroom_id
        WHERE enrollments.user_id = ?
    ''', (session['user_id'],)).fetchall()
    conn.close()
    return render_template('dashboard.html', classes=my_classes)

@app.route('/class/<int:class_id>')
def classroom(class_id):
    if 'user_id' not in session: return redirect('/')
    conn = get_db()
    classroom_data = conn.execute('SELECT * FROM classrooms WHERE id = ?', (class_id,)).fetchone()
    if not classroom_data: return "Class not found or deleted", 404
    if session.get('role') == 'teacher' and classroom_data['teacher'] != session.get('username'):
        conn.close()
        return "Forbidden", 403
    
    user_id = session['user_id']
    questions = conn.execute('''
        SELECT questions.*, 
        CASE WHEN votes.user_id IS NOT NULL THEN 1 ELSE 0 END as has_voted
        FROM questions
        LEFT JOIN votes ON questions.id = votes.question_id AND votes.user_id = ?
        WHERE questions.classroom_id = ? 
        ORDER BY questions.votes DESC
    ''', (user_id, class_id)).fetchall()
    
    conn.close()
    return render_template('classroom.html', classroom=classroom_data, questions=questions)

@app.route('/ask/<int:class_id>', methods=['POST'])
def ask(class_id):
    text = request.form['question_text']
    if text:
        conn = get_db()
        conn.execute('INSERT INTO questions (classroom_id, text, votes) VALUES (?, ?, 0)', (class_id, text))
        conn.commit()
        conn.close()
    return redirect(url_for('classroom', class_id=class_id))

@app.route('/upvote/<int:class_id>/<int:q_id>')
def upvote(class_id, q_id):
    user_id = session['user_id']
    conn = get_db()
    existing_vote = conn.execute('SELECT * FROM votes WHERE user_id=? AND question_id=?', (user_id, q_id)).fetchone()
    if not existing_vote:
        conn.execute('INSERT INTO votes (user_id, question_id) VALUES (?, ?)', (user_id, q_id))
        conn.execute('UPDATE questions SET votes = votes + 1 WHERE id = ?', (q_id,))
        conn.commit()
    conn.close()
    return redirect(url_for('classroom', class_id=class_id))

@app.route('/logout')
def logout():
    session.clear()
    return redirect('/')

# --- TEACHER DASHBOARD ---
@app.route('/teacher')
def teacher_dashboard():
    if session.get('role') != 'teacher': return redirect('/')
    conn = get_db()
    my_classes = conn.execute('SELECT * FROM classrooms WHERE teacher = ?', (session.get('username'),)).fetchall()
    my_questions = conn.execute('''
        SELECT questions.*, classrooms.subject AS class_subject
        FROM questions
        JOIN classrooms ON questions.classroom_id = classrooms.id
        WHERE classrooms.teacher = ?
        ORDER BY questions.id DESC
    ''', (session.get('username'),)).fetchall()
    conn.close()
    return render_template('teacher.html', classes=my_classes, questions=my_questions)

if __name__ == '__main__':
    init_db()
    print("🚀 App running! Login as admin/admin123")
    app.run(debug=True)