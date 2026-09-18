import os
import re
import sqlite3
import cloudinary
import cloudinary.uploader
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, session
from dotenv import load_dotenv
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)

cloudinary.config(
    cloud_name = os.environ.get("CLOUD_NAME"),
    api_key = os.environ.get("API_KEY"),
    api_secret = os.environ.get("API_SECRET")
)

app.secret_key = 'super_secret_key_change_in_production'

UPLOAD_FOLDER = os.path.join('static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
DATABASE = 'lost_and_found.db'

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_db_connection():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with app.app_context():
        conn = get_db_connection()
        conn.execute('''
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                report_type TEXT NOT NULL,
                category TEXT NOT NULL,
                location TEXT NOT NULL,
                description TEXT NOT NULL,
                phone_number TEXT,
                who_has_it TEXT,
                photo_path TEXT,
                reported_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                status TEXT DEFAULT 'Active'
            )
        ''')
        conn.commit()
        conn.close()

# Ensure upload directory exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()

@app.route('/')
def index():
    conn = get_db_connection()
    items = conn.execute('SELECT * FROM items WHERE status = "Active"').fetchall()
    conn.close()

    lost_items = []
    found_items = []
    
    current_time = datetime.now()

    for item in items:
        try:
            reported_date = datetime.strptime(item['reported_date'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            reported_date = datetime.strptime(item['reported_date'].split('.')[0], '%Y-%m-%d %H:%M:%S')

        days_passed = (current_time - reported_date).days
        action_required = days_passed > 30

        item_dict = dict(item)
        item_dict['days_passed'] = days_passed
        item_dict['action_required'] = action_required

        if item['report_type'] == 'Lost':
            lost_items.append(item_dict)
        elif item['report_type'] == 'Found':
            found_items.append(item_dict)

    # Retrieve saved form data if returning from a validation error
    form_data = session.pop('form_data', {})

    return render_template('index.html', lost_items=lost_items, found_items=found_items, form_data=form_data)

@app.route('/submit', methods=['POST'])
def submit():
    # Convert form data to a dictionary so we can save it if validation fails
    form_data = request.form.to_dict()
    
    report_type = form_data.get('report_type')
    category = form_data.get('category')
    location = form_data.get('location')
    description = form_data.get('description')
    phone_number = form_data.get('phone_number')
    who_has_it = form_data.get('who_has_it') if report_type == 'Found' else None

    has_error = False

    if report_type == 'Lost':
        if not description:
            flash('Description is required for lost items.', 'error')
            form_data.pop('description', None)
            has_error = True
        if not phone_number:
            flash('Phone number is required for lost items.', 'error')
            form_data.pop('phone_number', None)
            has_error = True
    elif report_type == 'Found':
        if not location:
            flash('Location is required for found items.', 'error')
            form_data.pop('location', None)
            has_error = True
        if not who_has_it:
            flash('Please specify who currently has the item.', 'error')
            form_data.pop('who_has_it', None)
            has_error = True

    if phone_number and not has_error:
        clean_phone = re.sub(r'[\s\-()]', '', phone_number)
        if not re.match(r'^[0-9]{10}$', clean_phone):
            flash('Invalid phone number format. Please enter a valid 10-digit number.', 'error')
            # Remove the faulty phone number so the user has to type it again, but keep everything else
            form_data.pop('phone_number', None)
            has_error = True

    photo_path = None
    # Only attempt to upload the image if the text fields passed validation
    if 'photo' in request.files and not has_error:
        file = request.files['photo']
        if file and file.filename != '':
            if not allowed_file(file.filename):
                flash('Invalid photo format. Only PNG, JPG, JPEG, and GIF are allowed.', 'error')
                has_error = True
            else:
                try:
                    upload_result = cloudinary.uploader.upload(file, resource_type="image")
                    photo_path = upload_result.get('secure_url')
                except Exception as e:
                    print("Cloudinary Upload Error:", e)
                    # This will now print the EXACT error from Cloudinary (e.g. missing API keys)
                    flash(f'Cloudinary Error: {str(e)}', 'error')
                    has_error = True

    if has_error:
        # Save valid inputs into session before redirecting
        session['form_data'] = form_data
        return redirect(url_for('index'))

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO items (report_type, category, location, description, phone_number, who_has_it, photo_path)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (report_type, category, location, description, phone_number, who_has_it, photo_path))
    conn.commit()
    conn.close()

    flash('Item reported successfully!', 'success')
    return redirect(url_for('index'))

@app.route('/resolve/<int:item_id>', methods=['POST'])
def resolve(item_id):
    action = request.form.get('action')
    conn = get_db_connection()
    if action == 'resolve':
        conn.execute('UPDATE items SET status = "Resolved" WHERE id = ?', (item_id,))
    elif action == 'delete':
        item = conn.execute('SELECT photo_path FROM items WHERE id = ?', (item_id,)).fetchone()
        if item and item['photo_path']:
            if not item['photo_path'].startswith('http'):
                file_path = os.path.join('static', item['photo_path'])
                if os.path.exists(file_path):
                    os.remove(file_path)
        conn.execute('DELETE FROM items WHERE id = ?', (item_id,))
    conn.commit()
    conn.close()
    
    flash('Item updated successfully.', 'success')
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)