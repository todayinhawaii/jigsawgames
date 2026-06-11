import os
import json
import stripe
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, request, jsonify

app = Flask(__name__)

# Stripe config - same pattern as fab.games!!
stripe.api_key = os.environ.get('STRIPE_SECRET_KEY')
STRIPE_PRICE_ID = os.environ.get('STRIPE_PRICE_ID') or os.environ.get('STRIPE_JIGSAW_PRICE_ID') or 'price_1TgXljRszIkvwb2pYi75vBvK'
STRIPE_WEBHOOK_SECRET = os.environ.get('STRIPE_WEBHOOK_SECRET', '')

# Supabase config
SUPABASE_URL = os.environ.get('SUPABASE_URL')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY')
SUPABASE_SERVICE_KEY = os.environ.get('SUPABASE_SERVICE_KEY')
BASE_URL = os.environ.get('BASE_URL', 'https://www.jigsaw.games')

def supabase_request(method, path, data=None, use_service_key=False):
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    key = SUPABASE_SERVICE_KEY if use_service_key else SUPABASE_ANON_KEY
    headers = {
        'apikey': key,
        'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json',
        'Prefer': 'return=representation'
    }
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as res:
            return json.loads(res.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Supabase error: {e.read().decode()}")
        return None

# ── PAGES ─────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'jigsaw_games_index.html')

@app.route('/admin')
def admin():
    return send_from_directory('.', 'jigsaw_admin.html')

@app.route('/join')
def join():
    return send_from_directory('.', 'jigsaw_join.html')

@app.route('/success')
def success():
    return send_from_directory('.', 'jigsaw_success.html')

@app.route('/login')
def login():
    return send_from_directory('.', 'jigsaw_login.html')

# ── CONFIG ────────────────────────────────────────
@app.route('/api/config')
def config():
    return jsonify({
        'supabase_url': SUPABASE_URL,
        'supabase_anon_key': SUPABASE_ANON_KEY,
    })

# ── REGISTER ─────────────────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    name  = data.get('name', '').strip()
    if not email or '@' not in email:
        return jsonify({'ok': False, 'msg': 'Invalid email'})
    trial_end = (datetime.utcnow() + timedelta(days=30)).isoformat()
    existing = supabase_request('GET',
        f"members?email=eq.{urllib.parse.quote(email)}&select=*",
        use_service_key=True)
    if existing and len(existing) > 0:
        return jsonify({'ok': True, 'existing': True})
    supabase_request('POST', 'members', {
        'email': email,
        'name': name,
        'status': 'trial',
        'trial_end': trial_end,
        'plan': 'free_trial',
        'subscription_status': 'trialing'
    }, use_service_key=True)
    return jsonify({'ok': True})

# ── STRIPE CHECKOUT ───────────────────────────────
@app.route('/api/create-checkout', methods=['POST'])
def create_checkout():
    data = request.get_json()
    email = data.get('email', '').strip().lower()
    # Use client-provided price or configured price - never empty!!
    price = data.get('price_id') or STRIPE_PRICE_ID
    print(f'CHECKOUT: email={email} price={price}', flush=True)
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='subscription',
            customer_email=email,
            line_items=[{'price': price, 'quantity': 1}],
            subscription_data={'trial_period_days': 30},
            success_url=BASE_URL + '/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=BASE_URL + '/join',
            allow_promotion_codes=True,
        )
        return jsonify({'ok': True, 'url': session.url})
    except Exception as e:
        print(f'STRIPE ERROR: {e}', flush=True)
        return jsonify({'ok': False, 'error': str(e)})

# ── STRIPE WEBHOOK ────────────────────────────────
@app.route('/api/webhook', methods=['POST'])
def webhook():
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    try:
        if STRIPE_WEBHOOK_SECRET:
            event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        else:
            event = json.loads(payload)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        email = session.get('customer_email', '').lower()
        customer_id = session.get('customer')
        existing = supabase_request('GET',
            f"members?email=eq.{urllib.parse.quote(email)}&select=*",
            use_service_key=True)
        if existing and len(existing) > 0:
            supabase_request('PATCH',
                f"members?email=eq.{urllib.parse.quote(email)}",
                {'status': 'active', 'subscription_status': 'active',
                 'stripe_customer': customer_id},
                use_service_key=True)
        else:
            supabase_request('POST', 'members', {
                'email': email,
                'status': 'active',
                'subscription_status': 'active',
                'stripe_customer': customer_id
            }, use_service_key=True)

    elif event['type'] == 'customer.subscription.deleted':
        sub = event['data']['object']
        customer_id = sub.get('customer')
        supabase_request('PATCH',
            f"members?stripe_customer=eq.{customer_id}",
            {'status': 'cancelled', 'subscription_status': 'cancelled'},
            use_service_key=True)

    return jsonify({'ok': True})

# ── STATIC ────────────────────────────────────────
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
