from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import os, pandas as pd
from pymongo import MongoClient
from bson.objectid import ObjectId
from extensions import mongo

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret'
app.config["MONGO_URI"] = "mongodb://localhost:27017/excel_data"
mongo.init_app(app)
app.config['UPLOAD_FOLDER'] = 'uploads'

client = MongoClient('mongodb://localhost:27017/')
db = client['excel_data']
users_collection = db['users']
files_collection = db['files']

login_manager = LoginManager(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, user_dict):
        self.id = str(user_dict['_id'])
        self.username = user_dict['username']
        self.password_hash = user_dict['password_hash']

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

@login_manager.user_loader
def load_user(user_id):
    user_data = users_collection.find_one({'_id': ObjectId(user_id)})
    if user_data:
        return User(user_data)
    return None

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if users_collection.find_one({'username': username}):
            flash('Username already exists.')
            return redirect(url_for('register'))

        password_hash = generate_password_hash(password)
        user_id = users_collection.insert_one({
            'username': username,
            'password_hash': password_hash,
            'preferred_theme': 'theme-bluegreen'  # default theme
        }).inserted_id

        flash('Registered successfully. Please login.')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        user_data = users_collection.find_one({'username': username})

        if user_data:
            user = User(user_data)
            if user.check_password(password):
                login_user(user)
                flash('Login successful.')
                return redirect(url_for('dashboard'))

        flash('Invalid username or password.')
    return render_template('login.html')

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        uploaded_file = request.files['file']
        if uploaded_file.filename.endswith('.csv'):
            df = pd.read_csv(uploaded_file)
            data = df.to_dict(orient='records')
            columns = list(df.columns)
            return render_template('upload.html', data=data, columns=columns, chart_title="Uploaded Chart")
        else:
            flash("Only CSV files allowed.")
            return redirect(url_for('upload'))

    return render_template('upload.html', data=None, columns=None, chart_title="")

@app.route('/dashboard')
@login_required
def dashboard():
    user = users_collection.find_one({'_id': ObjectId(current_user.id)})
    display_name = user.get('display_name') or user['username']
    profile_pic = user.get('profile_pic', '')
    theme = user.get('preferred_theme', 'theme-bluegreen')

    files = files_collection.find({'user_id': ObjectId(current_user.id)}).sort('_id', -1)
    file_list = [{
        'filename': f.get('filename', 'unknown'),
        'uploaded_at': f.get('_id').generation_time.strftime('%Y-%m-%d %H:%M:%S')
    } for f in files]

    return render_template(
        "dashboard.html",
        file_list=file_list,
        display_name=display_name,
        profile_pic=profile_pic,
        theme=theme,
        data=None
    )

@app.route('/delete/<filename>', methods=['POST'])
@login_required
def delete_file(filename):
    user_id = ObjectId(current_user.id)
    result = files_collection.delete_one({'user_id': user_id, 'filename': filename})
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(filepath):
        os.remove(filepath)

    flash("File deleted successfully!" if result.deleted_count else "File not found.")
    return redirect(url_for('dashboard'))

@app.route('/update-theme', methods=['POST'])
@login_required
def update_theme():
    theme = request.json.get('theme')
    if theme:
        users_collection.update_one(
            {'_id': ObjectId(current_user.id)},
            {'$set': {'preferred_theme': theme}}
        )
        return jsonify({"message": "Theme updated"})
    return jsonify({"message": "No theme provided"}), 400

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Logged out successfully.')
    return redirect(url_for('login'))

@app.route('/profile', methods=['GET', 'POST'])
@login_required
def profile():
    user_id = ObjectId(current_user.id)
    user = users_collection.find_one({'_id': user_id})
    update_data = {}

    if request.method == 'POST':
        email = request.form.get('email')
        display_name = request.form.get('display_name')
        bio = request.form.get('bio')

        if email: update_data['email'] = email
        if display_name: update_data['display_name'] = display_name
        if bio: update_data['bio'] = bio

        pic = request.files.get('profile_pic')
        if pic and pic.filename:
            filename = secure_filename(pic.filename)
            filepath = os.path.join('static/uploads', filename)
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            pic.save(filepath)
            update_data['profile_pic'] = filename

        old = request.form.get('current_password')
        new = request.form.get('new_password')
        confirm = request.form.get('confirm_password')

        if old or new or confirm:
            if not check_password_hash(user['password_hash'], old):
                flash('Incorrect current password')
                return redirect(url_for('profile'))
            if new != confirm:
                flash('New passwords do not match')
                return redirect(url_for('profile'))
            update_data['password_hash'] = generate_password_hash(new)

        if update_data:
            users_collection.update_one({'_id': user_id}, {'$set': update_data})
            flash('Profile updated successfully')
            return redirect(url_for('profile'))

    uploaded_files = files_collection.count_documents({'user_id': user_id})
    join_date = user['_id'].generation_time.strftime('%Y-%m-%d %H:%M:%S')

    return render_template('profile.html',
                           username=user.get('username', ''),
                           email=user.get('email', ''),
                           display_name=user.get('display_name', ''),
                           bio=user.get('bio', ''),
                           profile_pic=user.get('profile_pic', ''),
                           dark_mode=user.get('dark_mode', False),
                           files_uploaded=uploaded_files,
                           join_date=join_date)

if __name__ == '__main__':
    app.run(debug=True)