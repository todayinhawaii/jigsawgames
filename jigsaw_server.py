from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
import os, stripe, json
from supabase import create_client

app = Flask(__name__)
CORS(app)

# ── CONFIG ────────────────────────────────────────
SUPABASE_URL  = os.environ.get('SUPABASE_URL','')
SUPABASE_KEY  = os.environ.get('SUPABASE_ANON_KEY','')
STRIPE_KEY    = os.environ.get('STRIPE_SECRET_KEY','')
STRIPE_PRICE  = os.environ.get('STRIPE_JIGSAW_PRICE_ID','')  # new price for jigsaw.games
STRIPE_WEBHOOK= os.environ.get('STRIPE_WEBHOOK_SECRET','')
BASE_URL      = os.environ.get('BASE_URL','https://www.jigsaw.games')

stripe.api_key = STRIPE_KEY

def supabase():
    return create_client(SUPABASE_URL, SUPABASE_KEY)

# ── CONFIG API ────────────────────────────────────
@app.route('/api/config')
def config():
    return jsonify({'supabase_url':SUPABASE_URL,'supabase_anon_key':SUPABASE_KEY})

# ── REGISTER (Free Trial) ─────────────────────────
@app.route('/api/register', methods=['POST'])
def register():
    try:
        data = request.json
        sb = supabase()
        res = sb.auth.sign_up({
            'email': data['email'],
            'password': data['password'],
            'options': {'data': {'name': data.get('name',''), 'plan': 'free_trial', 'site': 'jigsaw.games'}}
        })
        if res.user:
            return jsonify({'ok': True})
        return jsonify({'ok': False, 'error': 'Could not create account'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── STRIPE CHECKOUT ───────────────────────────────
@app.route('/api/create-checkout', methods=['POST'])
def create_checkout():
    try:
        data = request.json
        session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            mode='subscription',
            customer_email=data.get('email'),
            line_items=[{'price': STRIPE_PRICE, 'quantity': 1}],
            subscription_data={'trial_period_days': 30},
            success_url=BASE_URL + '/success?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=BASE_URL + '/join',
            metadata={'name': data.get('name',''), 'site': 'jigsaw.games'}
        )
        return jsonify({'ok': True, 'url': session.url})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)})

# ── PAGES ─────────────────────────────────────────
@app.route('/')
def index():
    return send_from_directory('.', 'jigsaw_games_index.html')

@app.route('/join')
def join():
    return send_from_directory('.', 'jigsaw_join.html')

@app.route('/success')
def success():
    return send_from_directory('.', 'jigsaw_success.html')

@app.route('/login')
def login():
    return send_from_directory('.', 'jigsaw_login.html')

# ── PUZZLE IMAGES ─────────────────────────────────
@app.route('/puzzle<int:num>-landscape.jpg')
def puzzle_landscape(num):
    return send_from_directory('.', f'puzzle{num}-landscape.jpg')

@app.route('/puzzle<int:num>-portrait.jpg')
def puzzle_portrait(num):
    return send_from_directory('.', f'puzzle{num}-portrait.jpg')

# ── STATIC ────────────────────────────────────────
@app.route('/<path:filename>')
def static_files(filename):
    return send_from_directory('.', filename)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
