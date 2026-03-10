import os
import csv
import json
import uuid
import shutil
import base64
import hashlib
import datetime
from flask import (Flask, render_template, request, redirect, url_for,
                   session, flash, jsonify, send_file, send_from_directory)
from werkzeug.utils import secure_filename

# Load .env file
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'liberty-emporium-secret-2026')

# ── Paths ────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
INVENTORY_FILE = os.path.join(BASE_DIR, 'inventory.csv')
UPLOAD_FOLDER  = os.path.join(BASE_DIR, 'uploads')
BACKUP_FOLDER  = os.path.join(BASE_DIR, 'backups')
ADS_FOLDER     = os.path.join(BASE_DIR, 'ads')
USERS_FILE     = os.path.join(BASE_DIR, 'users.json')
PENDING_FILE   = os.path.join(BASE_DIR, 'pending_users.json')

for d in [UPLOAD_FOLDER, BACKUP_FOLDER, ADS_FOLDER]:
    os.makedirs(d, exist_ok=True)

# ── Config ───────────────────────────────────────────────────────────────────
STORE_NAME    = 'Liberty Emporium & Thrift'
DEMO_MODE     = os.environ.get('DEMO_MODE', 'false').lower() == 'true'
CONTACT_EMAIL = os.environ.get('CONTACT_EMAIL', 'alexanderjay70@gmail.com')
ALLOWED_EXT   = {'jpg', 'jpeg', 'png', 'gif', 'webp'}
MAX_BACKUPS   = 20

CATEGORIES = ['Furniture','Electronics','Clothing','Jewelry','Home Decor',
              'Books','Kitchen','Toys','Tools','Collectibles','Art','Miscellaneous']
CONDITIONS = ['New','Like New','Good','Fair','Poor']
STATUSES   = ['Available','Sold','Reserved','Pending']

ADMIN_USER  = 'admin'
ADMIN_PASS  = os.environ.get('ADMIN_PASSWORD', 'admin123')
ADMIN_EMAIL = 'alexanderjay70@gmail.com'

# ── Helpers ──────────────────────────────────────────────────────────────────
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT

def hash_password(pw):
    return hashlib.sha256(pw.encode()).hexdigest()

def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)

def save_users(users):
    with open(USERS_FILE, 'w') as f:
        json.dump(users, f, indent=2)

def load_pending():
    if not os.path.exists(PENDING_FILE):
        return []
    with open(PENDING_FILE) as f:
        return json.load(f)

def save_pending(pending):
    with open(PENDING_FILE, 'w') as f:
        json.dump(pending, f, indent=2)

def load_inventory():
    if not os.path.exists(INVENTORY_FILE):
        return []
    with open(INVENTORY_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        products = list(reader)
    for p in products:
        imgs = [i.strip() for i in p.get('Images','').split(',') if i.strip()]
        p['image_list'] = imgs
        p['valid_images'] = [i for i in imgs if os.path.exists(os.path.join(UPLOAD_FOLDER, i))]
    return products

def save_inventory(products):
    fieldnames = ['SKU','Title','Description','Category','Condition','Price',
                  'Cost Paid','Status','Date Added','Images','Section','Shelf']
    _backup_inventory()
    with open(INVENTORY_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(products)

def _backup_inventory():
    if not os.path.exists(INVENTORY_FILE):
        return
    ts = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    dst = os.path.join(BACKUP_FOLDER, f'inventory_{ts}.csv')
    shutil.copy2(INVENTORY_FILE, dst)
    backups = sorted(
        [f for f in os.listdir(BACKUP_FOLDER) if f.endswith('.csv')],
        reverse=True
    )
    for old in backups[MAX_BACKUPS:]:
        os.remove(os.path.join(BACKUP_FOLDER, old))

def get_stats():
    products = load_inventory()
    pending  = load_pending()
    total_value = sum(float(p.get('Price') or 0) for p in products)
    return {
        'total':         len(products),
        'available':     sum(1 for p in products if p.get('Status') == 'Available'),
        'sold':          sum(1 for p in products if p.get('Status') == 'Sold'),
        'reserved':      sum(1 for p in products if p.get('Status') == 'Reserved'),
        'total_value':   total_value,
        'pending_users': len(pending),
    }

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('username') != ADMIN_USER:
            flash('Admin access required.', 'error')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated

def ctx():
    return dict(store_name=STORE_NAME, demo_mode=DEMO_MODE,
                demo_contact_email=CONTACT_EMAIL, stats=get_stats(),
                demo_username=ADMIN_USER, demo_password=ADMIN_PASS)

# ── Auth Routes ───────────────────────────────────────────────────────────────
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        password = request.form.get('password','')
        # Admin check
        if username == ADMIN_USER and password == ADMIN_PASS:
            session['logged_in'] = True
            session['username']  = ADMIN_USER
            session['is_guest']  = False
            session.permanent    = True
            app.permanent_session_lifetime = datetime.timedelta(hours=8)
            flash('Welcome back, Admin!', 'success')
            return redirect(url_for('dashboard'))
        # Regular user check
        users = load_users()
        if username in users and users[username]['password'] == hash_password(password):
            session['logged_in'] = True
            session['username']  = username
            session['is_guest']  = False
            session.permanent    = True
            app.permanent_session_lifetime = datetime.timedelta(hours=8)
            flash(f'Welcome, {username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html', **ctx())

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out.', 'success')
    return redirect(url_for('login'))

@app.route('/guest')
def guest():
    session['logged_in'] = True
    session['username']  = 'guest'
    session['is_guest']  = True
    return redirect(url_for('dashboard'))

@app.route('/signup', methods=['GET','POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username','').strip()
        email    = request.form.get('email','').strip()
        password = request.form.get('password','')
        if not username or not password:
            flash('Username and password are required.', 'error')
        elif username == ADMIN_USER:
            flash('That username is reserved.', 'error')
        else:
            users   = load_users()
            pending = load_pending()
            if username in users or any(p['username'] == username for p in pending):
                flash('Username already exists or is pending.', 'error')
            else:
                pending.append({
                    'username':  username,
                    'email':     email,
                    'password':  hash_password(password),
                    'requested': datetime.date.today().isoformat()
                })
                save_pending(pending)
                flash('Account request submitted! Wait for admin approval.', 'success')
                return redirect(url_for('login'))
    return render_template('signup.html', **ctx())

# ── Dashboard ─────────────────────────────────────────────────────────────────
@app.route('/')
@login_required
def dashboard():
    products = load_inventory()
    return render_template('dashboard.html', products=products, **ctx())

# ── Products ──────────────────────────────────────────────────────────────────
@app.route('/product/<sku>')
@login_required
def view_product(sku):
    products = load_inventory()
    product  = next((p for p in products if p['SKU'] == sku), None)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('product.html', product=product, **ctx())

@app.route('/new', methods=['GET','POST'])
@login_required
def new_product():
    if session.get('is_guest'):
        flash('Guests cannot add products.', 'error')
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        sku = request.form.get('sku','').strip().upper()
        if not sku:
            flash('SKU is required.', 'error')
            return render_template('edit_with_ai.html', product={},
                                   categories=CATEGORIES, conditions=CONDITIONS,
                                   statuses=STATUSES, **ctx())
        products = load_inventory()
        if any(p['SKU'] == sku for p in products):
            flash('SKU already exists.', 'error')
            return render_template('edit_with_ai.html', product={},
                                   categories=CATEGORIES, conditions=CONDITIONS,
                                   statuses=STATUSES, **ctx())
        # Handle images
        images = []
        for file in request.files.getlist('images'):
            if file and allowed_file(file.filename):
                ext      = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{sku}_{uuid.uuid4().hex[:8]}.{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                images.append(filename)
        product = {
            'SKU':        sku,
            'Title':      request.form.get('title','').strip(),
            'Description':request.form.get('description','').strip(),
            'Category':   request.form.get('category','').strip(),
            'Condition':  request.form.get('condition','Good'),
            'Price':      request.form.get('price','0'),
            'Cost Paid':  request.form.get('cost_paid','') if session.get('username') == ADMIN_USER else '',
            'Status':     request.form.get('status','Available'),
            'Date Added': datetime.date.today().isoformat(),
            'Images':     ','.join(images),
            'Section':    request.form.get('section','').strip(),
            'Shelf':      request.form.get('shelf','').strip(),
        }
        products.append(product)
        save_inventory(products)
        flash(f'Product {sku} created!', 'success')
        return redirect(url_for('view_product', sku=sku))
    return render_template('edit_with_ai.html', product={},
                           categories=CATEGORIES, conditions=CONDITIONS,
                           statuses=STATUSES, **ctx())

@app.route('/edit/<sku>', methods=['GET','POST'])
@login_required
def edit_product(sku):
    if session.get('is_guest'):
        flash('Guests cannot edit products.', 'error')
        return redirect(url_for('dashboard'))
    products = load_inventory()
    idx      = next((i for i, p in enumerate(products) if p['SKU'] == sku), None)
    if idx is None:
        flash('Product not found.', 'error')
        return redirect(url_for('dashboard'))
    product = products[idx]
    if request.method == 'POST':
        for file in request.files.getlist('images'):
            if file and allowed_file(file.filename):
                ext      = file.filename.rsplit('.', 1)[1].lower()
                filename = f"{sku}_{uuid.uuid4().hex[:8]}.{ext}"
                file.save(os.path.join(UPLOAD_FOLDER, filename))
                existing = [i.strip() for i in product.get('Images','').split(',') if i.strip()]
                existing.append(filename)
                product['Images'] = ','.join(existing)
        product['Title']       = request.form.get('title', product['Title']).strip()
        product['Description'] = request.form.get('description', product.get('Description','')).strip()
        product['Category']    = request.form.get('category', product.get('Category','')).strip()
        product['Condition']   = request.form.get('condition', product.get('Condition','Good'))
        product['Price']       = request.form.get('price', product.get('Price','0'))
        product['Status']      = request.form.get('status', product.get('Status','Available'))
        product['Section']     = request.form.get('section', product.get('Section','')).strip()
        product['Shelf']       = request.form.get('shelf', product.get('Shelf','')).strip()
        if session.get('username') == ADMIN_USER:
            product['Cost Paid'] = request.form.get('cost_paid', product.get('Cost Paid',''))
        products[idx] = product
        save_inventory(products)
        flash('Product updated!', 'success')
        return redirect(url_for('view_product', sku=sku))
    return render_template('edit_with_ai.html', product=product,
                           categories=CATEGORIES, conditions=CONDITIONS,
                           statuses=STATUSES, **ctx())

@app.route('/delete/<sku>', methods=['POST'])
@login_required
def delete_product(sku):
    if session.get('is_guest'):
        flash('Guests cannot delete products.', 'error')
        return redirect(url_for('dashboard'))
    products = load_inventory()
    products = [p for p in products if p['SKU'] != sku]
    save_inventory(products)
    flash('Product deleted.', 'success')
    return redirect(url_for('dashboard'))

# ── Images ────────────────────────────────────────────────────────────────────
@app.route('/uploads/<filename>')
def serve_upload(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/delete-image/<sku>', methods=['POST'])
@login_required
def delete_image(sku):
    filename = request.form.get('filename')
    products = load_inventory()
    idx      = next((i for i, p in enumerate(products) if p['SKU'] == sku), None)
    if idx is not None and filename:
        imgs = [i.strip() for i in products[idx].get('Images','').split(',') if i.strip()]
        if filename in imgs:
            imgs.remove(filename)
            products[idx]['Images'] = ','.join(imgs)
            save_inventory(products)
            filepath = os.path.join(UPLOAD_FOLDER, filename)
            if os.path.exists(filepath):
                os.remove(filepath)
    return redirect(url_for('edit_product', sku=sku))

@app.route('/edit-image/<sku>')
@login_required
def edit_image(sku):
    products = load_inventory()
    product  = next((p for p in products if p['SKU'] == sku), None)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('image_editor.html', product=product, **ctx())

@app.route('/save-image/<sku>', methods=['POST'])
@login_required
def save_image(sku):
    data      = request.json
    image_data= data.get('image_data','')
    filename  = data.get('filename','')
    if image_data and filename:
        header, encoded = image_data.split(',', 1)
        img_bytes = base64.b64decode(encoded)
        filepath  = os.path.join(UPLOAD_FOLDER, filename)
        with open(filepath, 'wb') as f:
            f.write(img_bytes)
        return jsonify({'success': True})
    return jsonify({'success': False})

# ── AI Analysis ───────────────────────────────────────────────────────────────
@app.route('/ai-analyze', methods=['POST'])
@login_required
def ai_analyze():
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return jsonify({'error': 'AI feature not configured. ANTHROPIC_API_KEY missing.'})
    file = request.files.get('image')
    if not file:
        return jsonify({'error': 'No image provided.'})
    img_bytes = file.read()

    # Re-encode via Pillow to ensure valid JPEG — fixes phone HEIC/HEIF and large images
    try:
        from PIL import Image as _Img
        import io as _io
        _pil = _Img.open(_io.BytesIO(img_bytes))
        # Auto-rotate based on EXIF
        try:
            from PIL import ExifTags as _ET
            exif = _pil._getexif()
            if exif:
                orient_key = next((k for k, v in _ET.TAGS.items() if v == 'Orientation'), None)
                if orient_key and orient_key in exif:
                    rot = {3:180, 6:270, 8:90}.get(exif[orient_key])
                    if rot:
                        _pil = _pil.rotate(rot, expand=True)
        except Exception:
            pass
        _pil = _pil.convert('RGB')
        # Resize if too large (phones take huge photos)
        if max(_pil.size) > 1600:
            _pil.thumbnail((1600, 1600), _Img.LANCZOS)
        buf = _io.BytesIO()
        _pil.save(buf, format='JPEG', quality=85)
        img_bytes = buf.getvalue()
    except Exception:
        pass  # If Pillow fails just use original bytes

    img_b64      = base64.b64encode(img_bytes).decode('utf-8')
    content_type = 'image/jpeg'
    try:
        import urllib.request as ur
        import json as _json
        payload = {
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 1024,
            'messages': [{
                'role': 'user',
                'content': [
                    {'type': 'image', 'source': {'type': 'base64', 'media_type': content_type, 'data': img_b64}},
                    {'type': 'text', 'text': (
                        'Analyze this thrift store item photo. Respond ONLY with valid JSON:\n'
                        '{"title":"short product name","category":"one of: Furniture/Electronics/Clothing/'
                        'Jewelry/Home Decor/Books/Kitchen/Toys/Tools/Collectibles/Art/Miscellaneous",'
                        '"condition":"one of: New/Like New/Good/Fair/Poor",'
                        '"description":"2-3 sentence description",'
                        '"suggested_price":numeric_value}'
                    )}
                ]
            }]
        }
        req = ur.Request(
            'https://api.anthropic.com/v1/messages',
            data=_json.dumps(payload).encode(),
            headers={
                'x-api-key': api_key,
                'anthropic-version': '2023-06-01',
                'content-type': 'application/json'
            }
        )
        with ur.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
        text = result['content'][0]['text'].strip()
        # Strip markdown fences if present
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return jsonify(_json.loads(text))
    except Exception as e:
        return jsonify({'error': str(e)})

# ── Price Tag ─────────────────────────────────────────────────────────────────
@app.route('/price-tag/<sku>')
@login_required
def price_tag(sku):
    products = load_inventory()
    product  = next((p for p in products if p['SKU'] == sku), None)
    if not product:
        flash('Product not found.', 'error')
        return redirect(url_for('dashboard'))
    return render_template('price_tag.html', product=product, **ctx())

# ── Ad Generator ──────────────────────────────────────────────────────────────
@app.route('/ads')
@login_required
def ad_generator():
    products = load_inventory()
    return render_template('ad_generator.html', products=products, **ctx())

@app.route('/generate-ads', methods=['POST'])
@login_required
def generate_ads():
    # Accept both JSON (from ad_generator.html JS) and form POST
    if request.is_json:
        data          = request.get_json()
        product_list  = data.get('products', [])
        color_theme   = data.get('style', 'red_gold')
        all_products  = load_inventory()
        sku_map       = {p['SKU']: p for p in all_products}
        selected = []
        for item in product_list[:10]:
            sku = item.get('sku','')
            if sku in sku_map:
                selected.append(sku_map[sku])
        use_json_response = True
    else:
        selected_skus = request.form.getlist('selected_products')
        color_theme   = request.form.get('color_theme', 'red_gold')
        products      = load_inventory()
        selected      = [p for p in products if p['SKU'] in selected_skus][:10]
        use_json_response = False
    generated     = []

    themes = {
        'red_gold':      ((139,0,0),    (255,215,0),   (180,20,20)),
        'orange_yellow': ((200,80,0),   (255,237,0),   (230,110,0)),
        'navy_white':    ((0,31,91),    (255,255,255), (0,60,140)),
        'brown_gold':    ((74,44,10),   (201,168,76),  (100,60,20)),
    }
    bg_color, accent_color, header_color = themes.get(color_theme, themes['red_gold'])

    try:
        from PIL import Image, ImageDraw, ImageFont
        use_pillow = True
    except ImportError:
        use_pillow = False

    for p in selected:
        if use_pillow:
            filename = f"ad_{p['SKU']}_{uuid.uuid4().hex[:6]}.jpg"
            filepath = os.path.join(ADS_FOLDER, filename)

            W, H = 800, 600
            img  = Image.new('RGB', (W, H), bg_color)
            draw = ImageDraw.Draw(img)

            # Header bar
            draw.rectangle([0, 0, W, 90], fill=header_color)
            # Footer bar
            draw.rectangle([0, H-60, W, H], fill=header_color)

            # Try to load a font, fall back to default
            try:
                font_lg = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', 36)
                font_md = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf', 28)
                font_sm = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 20)
                font_xs = ImageFont.truetype('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 16)
            except:
                font_lg = ImageFont.load_default()
                font_md = font_lg
                font_sm = font_lg
                font_xs = font_lg

            # Store name in header
            store_text = STORE_NAME
            bbox = draw.textbbox((0,0), store_text, font=font_lg)
            tw = bbox[2] - bbox[0]
            draw.text(((W-tw)//2, 22), store_text, fill=accent_color, font=font_lg)

            # ── AI-generated headline & tagline ─────────────────────
            ai_headline = p.get('Title', '')[:40]
            ai_tagline  = f"{p.get('Condition','')} · {p.get('Category','')}"
            api_key = os.environ.get('ANTHROPIC_API_KEY')
            if api_key:
                try:
                    import urllib.request as _ur
                    import json as _json
                    _payload = {
                        'model': 'claude-haiku-4-5-20251001',
                        'max_tokens': 120,
                        'messages': [{'role': 'user', 'content':
                            f'''Write a short punchy Facebook Marketplace ad for this thrift store item.
Title: {p.get("Title","")}
Category: {p.get("Category","")}
Condition: {p.get("Condition","")}
Price: ${p.get("Price","0")}
Description: {p.get("Description","")[:200]}

Respond ONLY with JSON: {{"headline":"max 8 words","tagline":"max 12 words"}}'''
                        }]
                    }
                    _req = _ur.Request(
                        'https://api.anthropic.com/v1/messages',
                        data=_json.dumps(_payload).encode(),
                        headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
                    )
                    with _ur.urlopen(_req, timeout=15) as _resp:
                        _result = _json.loads(_resp.read())
                    _text = _result['content'][0]['text'].strip()
                    if _text.startswith('```'): _text = _text.split('```')[0] if '```' in _text else _text
                    _ai = _json.loads(_text)
                    ai_headline = _ai.get('headline', ai_headline)[:40]
                    ai_tagline  = _ai.get('tagline',  ai_tagline)[:50]
                except:
                    pass  # Fall back to product title if AI fails

            # ── Product image (EXIF auto-rotate) ─────────────────────
            img_y_start = 100
            img_area_h  = 270
            if p.get('valid_images'):
                try:
                    from PIL.ExifTags import TAGS
                    prod_img_path = os.path.join(UPLOAD_FOLDER, p['valid_images'][0])
                    prod_img = Image.open(prod_img_path)
                    # Auto-rotate based on EXIF orientation
                    try:
                        exif = prod_img._getexif()
                        if exif:
                            orientation_key = next((k for k,v in TAGS.items() if v == 'Orientation'), None)
                            if orientation_key and orientation_key in exif:
                                orientation = exif[orientation_key]
                                rotations = {3:180, 6:270, 8:90}
                                if orientation in rotations:
                                    prod_img = prod_img.rotate(rotations[orientation], expand=True)
                    except:
                        pass
                    prod_img = prod_img.convert('RGB')
                    prod_img.thumbnail((340, img_area_h))
                    px = (W - prod_img.width) // 2
                    py = img_y_start + (img_area_h - prod_img.height) // 2
                    img.paste(prod_img, (px, py))
                except:
                    pass

            # ── AI Headline ───────────────────────────────────────────
            bbox  = draw.textbbox((0,0), ai_headline, font=font_md)
            tw    = bbox[2] - bbox[0]
            # Word wrap if too wide
            if tw > W - 40:
                words = ai_headline.split()
                mid   = len(words) // 2
                line1 = ' '.join(words[:mid])
                line2 = ' '.join(words[mid:])
                b1 = draw.textbbox((0,0), line1, font=font_md)
                b2 = draw.textbbox((0,0), line2, font=font_md)
                draw.text(((W-(b1[2]-b1[0]))//2, 382), line1, fill=accent_color, font=font_md)
                draw.text(((W-(b2[2]-b2[0]))//2, 414), line2, fill=accent_color, font=font_md)
                price_y = 448
            else:
                draw.text(((W-tw)//2, 390), ai_headline, fill=accent_color, font=font_md)
                price_y = 430

            # ── Price badge ───────────────────────────────────────────
            price_text = f"${p.get('Price','0.00')}"
            badge_w, badge_h = 200, 56
            bx = (W - badge_w) // 2
            draw.rounded_rectangle([bx, price_y, bx+badge_w, price_y+badge_h], radius=12, fill=accent_color)
            bbox  = draw.textbbox((0,0), price_text, font=font_lg)
            tw    = bbox[2] - bbox[0]
            th    = bbox[3] - bbox[1]
            draw.text((bx+(badge_w-tw)//2, price_y+(badge_h-th)//2 - 2), price_text, fill=bg_color, font=font_lg)

            # ── AI Tagline ────────────────────────────────────────────
            bbox   = draw.textbbox((0,0), ai_tagline, font=font_xs)
            tw     = bbox[2] - bbox[0]
            draw.text(((W-tw)//2, price_y + badge_h + 8), ai_tagline, fill=accent_color, font=font_xs)

            # Footer
            product_url = f"https://edclawd.pythonanywhere.com/product/{p['SKU']}"
            footer = f"125 W Swannanoa Ave, Liberty NC 27298  |  View: {product_url}"
            bbox   = draw.textbbox((0,0), footer, font=font_xs)
            tw     = bbox[2] - bbox[0]
            draw.text(((W-tw)//2, H-42), footer, fill=accent_color, font=font_xs)

            img.save(filepath, 'JPEG', quality=90)
        else:
            # HTML fallback
            filename = f"ad_{p['SKU']}_{uuid.uuid4().hex[:6]}.html"
            filepath = os.path.join(ADS_FOLDER, filename)
            bg  = '#{:02x}{:02x}{:02x}'.format(*bg_color)
            acc = '#{:02x}{:02x}{:02x}'.format(*accent_color)
            html = f"""<!DOCTYPE html><html><head><meta charset="UTF-8">
<style>body{{margin:0;font-family:Georgia,serif;background:{bg};color:{acc};text-align:center;padding:20px}}
.store{{font-size:1.4rem;font-weight:bold;padding-bottom:8px;margin-bottom:12px}}
.price{{font-size:2rem;font-weight:bold;border:3px solid {acc};display:inline-block;padding:8px 20px;border-radius:8px;margin:10px 0}}
</style></head><body>
<div class="store">✨ {STORE_NAME} ✨</div>
<div class="title">{p.get('Title','')}</div>
<div class="price">${p.get('Price','0.00')}</div>
<div>📍 Asheboro, NC</div></body></html>"""
            with open(filepath, 'w') as f:
                f.write(html)

        # ── Build HTML wrapper with JPEG + clickable button ──────
        product_url  = f"https://edclawd.pythonanywhere.com/product/{p['SKU']}"
        html_filename = filename.replace('.jpg', '.html') if filename.endswith('.jpg') else filename
        html_filepath = os.path.join(ADS_FOLDER, html_filename)
        bg_hex  = '#{:02x}{:02x}{:02x}'.format(*bg_color)
        acc_hex = '#{:02x}{:02x}{:02x}'.format(*accent_color)
        hdr_hex = '#{:02x}{:02x}{:02x}'.format(*header_color)
        img_tag = f'<img src="/ads/{filename}" style="width:100%;display:block;">' if filename.endswith('.jpg') else ''
        html_content = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body {{ margin:0; padding:0; background:#1a1a1a; display:flex; justify-content:center; align-items:center; min-height:100vh; font-family:Georgia,serif; }}
  .ad-wrap {{ max-width:800px; width:100%; background:{bg_hex}; border-radius:12px; overflow:hidden; box-shadow:0 8px 32px rgba(0,0,0,0.5); }}
  .ad-img {{ width:100%; display:block; }}
  .ad-footer {{ background:{hdr_hex}; padding:1rem 1.5rem; display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.75rem; }}
  .ad-address {{ color:{acc_hex}; font-size:0.85rem; }}
  .view-btn {{
    background:{acc_hex}; color:{bg_hex}; border:none; padding:0.75rem 1.75rem;
    border-radius:8px; font-size:1rem; font-weight:bold; cursor:pointer;
    text-decoration:none; display:inline-block; transition:opacity 0.2s;
  }}
  .view-btn:hover {{ opacity:0.85; }}
</style>
</head>
<body>
  <div class="ad-wrap">
    {img_tag}
    <div class="ad-footer">
      <div class="ad-address">📍 125 W Swannanoa Ave, Liberty NC 27298</div>
      <a href="{product_url}" class="view-btn" target="_blank">🛍️ View Product</a>
    </div>
  </div>
</body>
</html>"""
        with open(html_filepath, 'w') as hf:
            hf.write(html_content)

        generated.append({'filename': html_filename, 'product_title': p.get('Title',''), 'type': 'html'})

    if use_json_response:
        return jsonify({'success': True, 'files': generated})
    return render_template('ads.html', generated=[g['filename'] for g in generated], **ctx())


@app.route('/ads/<filename>')
def view_ad(filename):
    return send_from_directory(ADS_FOLDER, filename)

@app.route('/download-ad/<filename>')
@login_required
def download_ad(filename):
    return send_from_directory(ADS_FOLDER, filename, as_attachment=True)

# ── Listing Generator ───────────────────────────────────────────────────────
@app.route('/listing-generator')
@login_required
def listing_generator():
    products = load_inventory()
    return render_template('listing_generator.html', products=products, **ctx())

@app.route('/generate-listing', methods=['POST'])
@login_required
def generate_listing():
    data     = request.get_json()
    product  = data.get('product', {})
    platform = data.get('platform', 'facebook')
    api_key  = os.environ.get('ANTHROPIC_API_KEY')

    title     = product.get('title', '')
    price     = product.get('price', '0')
    category  = product.get('category', '')
    condition = product.get('condition', '')
    desc      = product.get('description', '')
    sku       = product.get('sku', '')
    product_url = 'https://edclawd.pythonanywhere.com/product/' + sku
    store_info  = 'Liberty Emporium & Thrift\n125 W Swannanoa Ave, Liberty NC 27298\nView item: ' + product_url

    platform_prompts = {
        'facebook': (
            'Write a Facebook Marketplace listing for this thrift store item.\n'
            'Title: ' + title + ' | Price: $' + price + ' | Category: ' + category + ' | Condition: ' + condition + '\n'
            'Description: ' + desc + '\n'
            'Store: Liberty Emporium & Thrift, 125 W Swannanoa Ave, Liberty NC 27298\n'
            'View online: ' + product_url + '\n\n'
            'Respond ONLY with JSON (no markdown):\n'
            '{"title":"catchy listing title max 60 chars","price":"$' + price + '","condition":"' + condition + '","description":"3-4 sentences friendly tone end with store address and product link","location":"Liberty, NC 27298"}'
        ),
        'craigslist': (
            'Write a Craigslist for-sale listing for this thrift store item.\n'
            'Title: ' + title + ' | Price: $' + price + ' | Category: ' + category + ' | Condition: ' + condition + '\n'
            'Description: ' + desc + '\n'
            'Store: Liberty Emporium & Thrift, 125 W Swannanoa Ave, Liberty NC 27298\n'
            'View online: ' + product_url + '\n\n'
            'Respond ONLY with JSON (no markdown):\n'
            '{"title":"listing title max 70 chars","price":"$' + price + '","condition":"","description":"3-5 sentences practical tone include address and link","location":"Liberty, NC 27298"}'
        ),
        'instagram': (
            'Write an Instagram caption for selling this thrift store item.\n'
            'Title: ' + title + ' | Price: $' + price + ' | Category: ' + category + ' | Condition: ' + condition + '\n'
            'Description: ' + desc + '\n'
            'Store: Liberty Emporium & Thrift, 125 W Swannanoa Ave, Liberty NC 27298\n'
            'View online: ' + product_url + '\n\n'
            'Respond ONLY with JSON (no markdown):\n'
            '{"title":"","price":"$' + price + '","condition":"","description":"Engaging caption with emojis price condition store address product link and 5 hashtags","location":""}'
        ),
    }

    prompt = platform_prompts.get(platform, platform_prompts['facebook'])

    if not api_key:
        fallback_desc = desc + '\n\n' + store_info
        return jsonify({'title': title, 'price': '$' + price, 'condition': condition,
                        'description': fallback_desc, 'location': 'Liberty, NC 27298'})
    try:
        import urllib.request as _ur
        import json as _json
        payload = {
            'model': 'claude-haiku-4-5-20251001',
            'max_tokens': 500,
            'messages': [{'role': 'user', 'content': prompt}]
        }
        req = _ur.Request(
            'https://api.anthropic.com/v1/messages',
            data=_json.dumps(payload).encode(),
            headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'}
        )
        with _ur.urlopen(req, timeout=30) as resp:
            result = _json.loads(resp.read())
        text = result['content'][0]['text'].strip()
        if text.startswith('```'):
            text = text.split('\n', 1)[1].rsplit('```', 1)[0].strip()
        return jsonify(_json.loads(text))
    except Exception as e:
        return jsonify({'error': str(e)})

# ── Jay Resume / About Page ──────────────────────────────────────────────────
@app.route('/contact')
def contact():
    return render_template('jay_resume.html')

# ── Seasonal Sale (stub) ──────────────────────────────────────────────────────
SALE_FILE = os.path.join(BASE_DIR, 'sale_state.json')

def load_sale():
    if not os.path.exists(SALE_FILE):
        return {'active': False}
    with open(SALE_FILE) as f:
        return json.load(f)

@app.route('/seasonal-sale', methods=['GET','POST'])
@login_required
@admin_required
def seasonal_sale():
    sale_state = load_sale()
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'activate':
            sale_state = {
                'active': True,
                'category': request.form.get('category',''),
                'discount_percent': int(request.form.get('discount_percent', 10))
            }
        else:
            sale_state = {'active': False}
        with open(SALE_FILE, 'w') as f:
            json.dump(sale_state, f)
        flash('Sale settings updated!', 'success')
    return render_template('seasonal_sale.html', sale_state=sale_state,
                           categories=CATEGORIES, **ctx())

# ── Export ────────────────────────────────────────────────────────────────────
@app.route('/export')
@login_required
def export_inventory():
    return send_file(INVENTORY_FILE, as_attachment=True, download_name='inventory.csv')

# ── Admin – Users ─────────────────────────────────────────────────────────────
@app.route('/admin/users')
@login_required
@admin_required
def admin_users():
    users   = load_users()
    pending = load_pending()
    return render_template('admin_users.html', users=users, pending=pending, **ctx())

@app.route('/admin/approve/<username>', methods=['POST'])
@login_required
@admin_required
def approve_user(username):
    pending = load_pending()
    user    = next((p for p in pending if p['username'] == username), None)
    if user:
        users = load_users()
        users[username] = {'password': user['password'], 'email': user.get('email','')}
        save_users(users)
        pending = [p for p in pending if p['username'] != username]
        save_pending(pending)
        flash(f'User {username} approved!', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/reject/<username>', methods=['POST'])
@login_required
@admin_required
def reject_user(username):
    pending = [p for p in load_pending() if p['username'] != username]
    save_pending(pending)
    flash(f'User {username} rejected.', 'success')
    return redirect(url_for('admin_users'))

@app.route('/admin/remove/<username>', methods=['POST'])
@login_required
@admin_required
def remove_user(username):
    users = load_users()
    users.pop(username, None)
    save_users(users)
    flash(f'User {username} removed.', 'success')
    return redirect(url_for('admin_users'))

# ── Admin – Backups ───────────────────────────────────────────────────────────
@app.route('/admin/backups')
@login_required
@admin_required
def admin_backups():
    files = sorted(os.listdir(BACKUP_FOLDER), reverse=True)
    backups = []
    for f in files:
        if f.endswith('.csv'):
            path = os.path.join(BACKUP_FOLDER, f)
            stat = os.stat(path)
            backups.append({
                'filename': f,
                'size':     stat.st_size,
                'modified': datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            })
    return render_template('admin_backups.html', backups=backups, **ctx())

@app.route('/admin/backups/download/<filename>')
@login_required
@admin_required
def download_backup(filename):
    return send_from_directory(BACKUP_FOLDER, filename, as_attachment=True)

@app.route('/admin/backups/restore/<filename>', methods=['POST'])
@login_required
@admin_required
def restore_backup(filename):
    src = os.path.join(BACKUP_FOLDER, filename)
    if os.path.exists(src):
        shutil.copy2(src, INVENTORY_FILE)
        flash(f'Inventory restored from {filename}!', 'success')
    return redirect(url_for('admin_backups'))

@app.route('/admin/backups/manual', methods=['POST'])
@login_required
@admin_required
def manual_backup():
    _backup_inventory()
    flash('Manual backup created!', 'success')
    return redirect(url_for('admin_backups'))

# ── Debug ─────────────────────────────────────────────────────────────────────
@app.route('/debug')
@login_required
@admin_required
def debug():
    info = {
        'store_name':       STORE_NAME,
        'base_dir':         BASE_DIR,
        'inventory_file':   INVENTORY_FILE,
        'inventory_exists': os.path.exists(INVENTORY_FILE),
        'upload_folder':    UPLOAD_FOLDER,
        'anthropic_key_set':bool(os.environ.get('ANTHROPIC_API_KEY')),
        'demo_mode':        DEMO_MODE,
        'python_version':   __import__('sys').version,
    }
    return jsonify(info)

# ── Context processor ─────────────────────────────────────────────────────────
@app.context_processor
def inject_globals():
    return dict(
        store_name=STORE_NAME,
        demo_mode=DEMO_MODE,
        demo_contact_email=CONTACT_EMAIL,
        stats=get_stats(),
        sale_state=load_sale(),
    )

if __name__ == '__main__':
    app.run(debug=True)
