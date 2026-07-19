from flask import Flask, render_template, request, redirect, url_for, session, flash
import os
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.security import generate_password_hash, check_password_hash
from flask_mail import Mail, Message
import base64
import filetype
import uuid
from datetime import datetime


# ── App Setup ──────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "replace_with_a_strong_secret_key")

# ── Firebase ───────────────────────────────────────────────────────────────
import os
import json

firebase_credentials = os.environ.get("FIREBASE_CREDENTIALS")

if firebase_credentials:
    cred_dict = json.loads(firebase_credentials)
    cred = credentials.Certificate(cred_dict)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    cred = credentials.Certificate(os.path.join(BASE_DIR, "serviceAccountKey.json"))

if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)
db = firestore.client()
users_ref    = db.collection("users")
products_ref = db.collection("products")
orders_ref   = db.collection("orders")

# ── Flask-Mail (Gmail SMTP) ────────────────────────────────────────────────
# Fill in your Gmail and App Password below.
# To create a Gmail App Password:
#   Google Account → Security → 2-Step Verification → App Passwords
app.config['MAIL_SERVER']   = 'smtp.gmail.com'
app.config['MAIL_PORT']     = 587
app.config['MAIL_USE_TLS']  = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD")
app.config['MAIL_DEFAULT_SENDER'] = os.environ.get("MAIL_USERNAME")  # ← change
mail = Mail(app)

# ── Helpers ────────────────────────────────────────────────────────────────
ADMIN_EMAIL = "venkatavijaykumarkareti@gmail.com"   # The one account that gets admin role

def is_admin():
    return session.get('role') == 'admin'

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user' not in session or not is_admin():
            flash("Admin access only.", "danger")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def send_order_email(user_email, user_name, order_id, items, total):
    """Send order confirmation email to the customer."""
    try:
        rows = ""
        for item in items:
            rows += f"""
            <tr>
              <td style="padding:8px;border:1px solid #ddd">{item['name']}</td>
              <td style="padding:8px;border:1px solid #ddd">{item['quantity']}</td>
              <td style="padding:8px;border:1px solid #ddd">₹{item['price']:.2f}</td>
              <td style="padding:8px;border:1px solid #ddd">₹{item['price']*item['quantity']:.2f}</td>
            </tr>"""

        html_body = f"""
        <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px;border:1px solid #eee;border-radius:8px">
          <h2 style="color:#2ecc71;text-align:center">🎉 Order Confirmed!</h2>
          <p>Hi <strong>{user_name}</strong>,</p>
          <p>Thank you for shopping with us! Your order has been placed successfully.</p>
          <p><strong>Order ID:</strong> {order_id}</p>
          <p><strong>Date:</strong> {datetime.now().strftime('%d %b %Y, %I:%M %p')}</p>
          <table style="width:100%;border-collapse:collapse;margin:16px 0">
            <tr style="background:#f8f8f8">
              <th style="padding:8px;border:1px solid #ddd;text-align:left">Item</th>
              <th style="padding:8px;border:1px solid #ddd">Qty</th>
              <th style="padding:8px;border:1px solid #ddd">Price</th>
              <th style="padding:8px;border:1px solid #ddd">Subtotal</th>
            </tr>
            {rows}
          </table>
          <p style="text-align:right;font-size:18px"><strong>Total: ₹{total:.2f}</strong></p>
          <hr>
          <p style="color:#888;font-size:12px;text-align:center">Thank you for your purchase! Questions? Reply to this email.</p>
        </div>"""

        msg = Message(
            subject=f"Order Confirmation #{order_id[:8].upper()}",
            recipients=[user_email],
            html=html_body
        )
        mail.send(msg)
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ══════════════════════════════════════════════════════════════════════════
#  AUTH ROUTES
# ══════════════════════════════════════════════════════════════════════════

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name     = request.form['name'].strip()
        email    = request.form['email'].strip().lower()
        password = request.form['password']

        if users_ref.document(email).get().exists:
            flash("Email already registered!", "warning")
            return redirect(url_for('signup'))

        role = 'admin' if email == ADMIN_EMAIL else 'user'
        users_ref.document(email).set({
            'name':     name,
            'email':    email,
            'password': generate_password_hash(password),
            'role':     role,
            'cart':     []
        })
        flash("Account created! Please log in.", "success")
        return redirect(url_for('login'))

    return render_template('signup.html')


@app.route('/', methods=['GET', 'POST'])
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email    = request.form['email'].strip().lower()
        password = request.form['password']

        doc = users_ref.document(email).get()
        if not doc.exists:
            flash("User not found. Please sign up first.", "danger")
            return redirect(url_for('login'))

        data = doc.to_dict()
        if not check_password_hash(data['password'], password):
            flash("Incorrect password.", "danger")
            return redirect(url_for('login'))

        session['user']  = email
        session['name']  = data.get('name', 'User')
        session['role']  = data.get('role', 'user')

        if session['role'] == 'admin':
            return redirect(url_for('admin_dashboard'))
        return redirect(url_for('shop'))

    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ══════════════════════════════════════════════════════════════════════════
#  ADMIN ROUTES
# ══════════════════════════════════════════════════════════════════════════

@app.route('/admin')
@admin_required
def admin_dashboard():
    products = [{'id': d.id, **d.to_dict()} for d in products_ref.stream()]
    orders   = [{'id': d.id, **d.to_dict()} for d in orders_ref.order_by('created_at', direction=firestore.Query.DESCENDING).stream()]
    return render_template('admin_dashboard.html', products=products, orders=orders, name=session['name'])


@app.route('/admin/add_product', methods=['GET', 'POST'])
@admin_required
def add_product():
    if request.method == 'POST':
        name        = request.form['name'].strip()
        description = request.form['description'].strip()
        price       = float(request.form['price'])
        stock       = int(request.form['stock'])

        image_data = image_type = None
        if 'image' in request.files and request.files['image'].filename:
            from PIL import Image
            import io
            file = request.files['image']
            img = Image.open(file)
            img = img.convert('RGB')
            img.thumbnail((600, 600))  # resize to max 600x600
            buffer = io.BytesIO()
            img.save(buffer, format='JPEG', quality=70)
            img_bytes = buffer.getvalue()
            image_type = 'jpeg'
            image_data = base64.b64encode(img_bytes).decode('utf-8')

        products_ref.add({
            'name':        name,
            'description': description,
            'price':       price,
            'stock':       stock,
            'image_data':  image_data,
            'image_type':  image_type,
            'created_at':  datetime.utcnow()
        })
        flash(f"Product '{name}' added!", "success")
        return redirect(url_for('admin_dashboard'))

    return render_template('add_product.html', name=session['name'])


@app.route('/admin/edit_product/<product_id>', methods=['GET', 'POST'])
@admin_required
def edit_product(product_id):
    doc = products_ref.document(product_id).get()
    if not doc.exists:
        flash("Product not found.", "danger")
        return redirect(url_for('admin_dashboard'))

    product = {'id': doc.id, **doc.to_dict()}

    if request.method == 'POST':
        updates = {
            'name':        request.form['name'].strip(),
            'description': request.form['description'].strip(),
            'price':       float(request.form['price']),
            'stock':       int(request.form['stock']),
        }
        if 'image' in request.files and request.files['image'].filename:
            file       = request.files['image']
            img_bytes  = file.read()
            kind = filetype.guess(img_bytes)
            image_type = kind.extension if kind else "jpeg"
            updates['image_data'] = base64.b64encode(img_bytes).decode('utf-8')
            updates['image_type'] = image_type

        products_ref.document(product_id).update(updates)
        flash("Product updated!", "success")
        return redirect(url_for('admin_dashboard'))

    return render_template('edit_product.html', product=product, name=session['name'])


@app.route('/admin/delete_product/<product_id>', methods=['POST'])
@admin_required
def delete_product(product_id):
    products_ref.document(product_id).delete()
    flash("Product deleted.", "info")
    return redirect(url_for('admin_dashboard'))


# ══════════════════════════════════════════════════════════════════════════
#  USER / SHOP ROUTES
# ══════════════════════════════════════════════════════════════════════════

@app.route('/shop')
@login_required
def shop():
    products = [{'id': d.id, **d.to_dict()} for d in products_ref.stream()]
    return render_template('shop.html', products=products, name=session['name'])


# ── Cart ──────────────────────────────────────────────────────────────────

@app.route('/cart/add/<product_id>', methods=['POST'])
@login_required
def add_to_cart(product_id):
    qty = int(request.form.get('quantity', 1))
    doc = products_ref.document(product_id).get()
    if not doc.exists:
        flash("Product not found.", "danger")
        return redirect(url_for('shop'))

    product = doc.to_dict()
    if product['stock'] < qty:
        flash("Not enough stock!", "warning")
        return redirect(url_for('shop'))

    user_doc  = users_ref.document(session['user']).get()
    cart      = user_doc.to_dict().get('cart', [])

    # If item already in cart, increase quantity
    found = False
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] += qty
            found = True
            break
    if not found:
        cart.append({
            'product_id': product_id,
            'name':       product['name'],
            'price':      product['price'],
            'quantity':   qty
        })

    users_ref.document(session['user']).update({'cart': cart})
    flash(f"'{product['name']}' added to cart!", "success")
    return redirect(url_for('shop'))


@app.route('/cart')
@login_required
def view_cart():
    user_doc = users_ref.document(session['user']).get()
    cart     = user_doc.to_dict().get('cart', [])
    total    = sum(i['price'] * i['quantity'] for i in cart)
    return render_template('cart.html', cart=cart, total=total, name=session['name'])


@app.route('/cart/remove/<product_id>', methods=['POST'])
@login_required
def remove_from_cart(product_id):
    user_doc = users_ref.document(session['user']).get()
    cart     = [i for i in user_doc.to_dict().get('cart', []) if i['product_id'] != product_id]
    users_ref.document(session['user']).update({'cart': cart})
    flash("Item removed from cart.", "info")
    return redirect(url_for('view_cart'))


@app.route('/cart/update/<product_id>', methods=['POST'])
@login_required
def update_cart(product_id):
    qty      = int(request.form.get('quantity', 1))
    user_doc = users_ref.document(session['user']).get()
    cart     = user_doc.to_dict().get('cart', [])
    for item in cart:
        if item['product_id'] == product_id:
            item['quantity'] = max(1, qty)
            break
    users_ref.document(session['user']).update({'cart': cart})
    return redirect(url_for('view_cart'))


# ── Checkout / Place Order ─────────────────────────────────────────────────

@app.route('/checkout', methods=['POST'])
@login_required
def checkout():
    user_doc  = users_ref.document(session['user']).get()
    user_data = user_doc.to_dict()
    cart      = user_data.get('cart', [])

    if not cart:
        flash("Your cart is empty!", "warning")
        return redirect(url_for('view_cart'))

    # Validate stock for every item
    for item in cart:
        prod = products_ref.document(item['product_id']).get()
        if not prod.exists or prod.to_dict()['stock'] < item['quantity']:
            flash(f"'{item['name']}' is out of stock or insufficient quantity.", "danger")
            return redirect(url_for('view_cart'))

    total    = sum(i['price'] * i['quantity'] for i in cart)
    order_id = str(uuid.uuid4())

    # Save order
    orders_ref.document(order_id).set({
        'order_id':   order_id,
        'user_email': session['user'],
        'user_name':  session['name'],
        'items':      cart,
        'total':      total,
        'status':     'confirmed',
        'created_at': datetime.utcnow()
    })

    # Deduct stock
    for item in cart:
        prod_ref = products_ref.document(item['product_id'])
        prod_data = prod_ref.get().to_dict()
        prod_ref.update({'stock': prod_data['stock'] - item['quantity']})

    # Clear cart
    users_ref.document(session['user']).update({'cart': []})

    # Send confirmation email
    email_sent = False
    #email_sent = send_order_email(session['user'], session['name'], order_id, cart, total)

    return render_template('order_success.html',
                           order_id=order_id,
                           items=cart,
                           total=total,
                           name=session['name'],
                           email_sent=email_sent)


@app.route('/my_orders')
@login_required
def my_orders():
    orders = []
    for doc in orders_ref.where('user_email', '==', session['user']).order_by('created_at', direction=firestore.Query.DESCENDING).stream():
        orders.append({'id': doc.id, **doc.to_dict()})
    return render_template('my_orders.html', orders=orders, name=session['name'])




if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
