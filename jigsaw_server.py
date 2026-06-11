from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
import os, stripe, json
from supabase import create_client

app = Flask(__name__)
CORS(app)

# ── CONFIG ────────────────────────────────────────
SUPABASE_URL   = os.environ.get('SUPABASE_URL','')
SUPABASE_KEY   = os.environ.get('SUPABASE_ANON_KEY','')
SUPABASE_SVC   = os.environ.get('SUPABASE_SERVICE_KEY','')
STRIPE_KEY     = os.environ.get('STRIPE_SECRET_KEY','')
STRIPE_PRICE   = os.environ.get('STRIPE_JIGSAW_PRICE_ID','') or os.environ.get('STRIPE_PRICE_ID','') or 'price_1TgXljRszIkvwb2pYi75vBvK'
STRIPE_WEBHOOK = os.environ.get('STRIPE_WEBHOOK_SECRET','')
BASE_URL       = os.environ.get('BASE_URL','https://www.jigsaw.games')

stripe.api_key = STRIPE_KEY

def supabase_client(service=False):
    key = SUPABASE_SVC if service else SUPABASE_KEY
    return create_client(SUPABASE_URL, key)

# ── CONFIG API ───────────────────────────────────────
@app.route('/api/config')
def config():
    return jsonify({'supabase_url':SUPABASE_URL,'supabase_anon_key':SUPABASE_KEY})

# ── REGISTER (Free Trial) ─────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        sb = supabase_client()
        res = sb.auth.sign_up({
            'email': data['email'],
            'password': data['password'],
            'options': {'data': {'name': data.get('name',''), 'plan': 'free_trial'}}
        })
        if res.user:
            # Create member record with free trial
            from datetime import datetime, timedelta
            trial_end = (datetime.utcnow() + timedelta(days=30)).isoformat()
            sb.table('members').upsert({
                'id': res.user.id,
                'email': data['email'],
                'name': data.get('name',''),
                'plan': 'free_trial',
                'trial_end': trial_end,
                'subscription_status': 'trialing'
            }).execute()
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Could not create account'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── STRIPE CHECKOUT ───────────────────────────────
@app.route('/api/create-checkout', methods=['POST'])
def create_checkout():
    try:
        data = request.json
        # Use env var or hardcoded fallback - cannot be empty!!
    price_id = STRIPE_PRICE or 'price_1TgXljRszIkvwb2pYi75vBvK'
    print(f'CHECKOUT: using price_id={price_id}', flush=True)
    session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='subscription',
            customer_email=data.get('email'),
            line_items=[{'price': price_id, 'quantity': 1}],
            subscription_data={'trial_period_days': 30},
            success_url=BASE_URL + '/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=BASE_URL + '/join',
            metadata={'name': data.get('name',''), 'email': data.get('email','')}
        )
        return jsonify({'ok': True, 'url': session.url})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── STRIPE WEBHOOK ────────────────────────────────
@app.route('/api/webhook', methods=['POST'])
def webhook():
    payload = request.data
    sig = request.headers.get('Stripe-Signature','')
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

    sb = supabase_client(service=True)

    if event['type'] in ['checkout.session.completed',
                          'customer.subscription.created',
                          'customer.subscription.updated']:
        obj = event['data']['object']
        email = obj.get('customer_email') or obj.get('metadata',{}).get('email','')
        status = obj.get('status','active')
        if email:
            sb.table('members').update({
                'subscription_status': status,
                'plan': 'paid',
                'stripe_customer_id': obj.get('customer','')
            }).eq('email', email).execute()

    elif event['type'] == 'customer.subscription.deleted':
        obj = event['data']['object']
        cust_id = obj.get('customer','')
        if cust_id:
            sb.table('members').update({
                'subscription_status': 'cancelled',
                'plan': 'free'
            }).eq('stripe_customer_id', cust_id).execute()

    return jsonify({'ok': True})

# ── PAGES ─────────────────────────────────────────
@app.route('/')
def index():
    # Always serve main index - handles both mobile and desktop
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

# ── STATIC ────────────────────────────────────────
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
