# https://docs.google.com/spreadsheets/d/1DLJvWZ1ZWLNd6gV4CnebDsE-PnqTPLZs_yVVGEKvATs/edit?gid=0#gid=0
from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app, cors_allowed_origins='*')

# --- Google Sheets setup ---
SCOPES = ['https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = 'service_account.json'
creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
sheets = build('sheets', 'v4', credentials=creds).spreadsheets()
SPREADSHEET_ID = '1DLJvWZ1ZWLNd6gV4CnebDsE-PnqTPLZs_yVVGEKvATs'
GROUP_RANGE   = 'Groups!A2:C'    # group_id, group_name, singers(comma-separated)
RESULTS_RANGE = 'Results!A2:D'   # append: group_id, group_name, votes_yes

# --- In‐memory state ---
current_group = None        # the dict {id,name,singers}
votes = {}                  # judge_id → 'yes'/'no'
enabled_judges = set(['1','2','3','4'])

# --- Routes ---
@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/judge/<jid>')
def judge(jid):
    return render_template('judge.html', judge_id=jid)

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/')
def index():
    return render_template('dashboard.html')

# --- Socket.IO handlers ---
@socketio.on('get_groups')
def on_get_groups():
    resp = sheets.values().get(spreadsheetId=SPREADSHEET_ID, range=GROUP_RANGE).execute()
    data = resp.get('values', [])
    groups = [
        {'id': r[0], 'name': r[1], 'singers': r[2].split(',')}
        for r in data if len(r) >= 3
    ]
    emit('groups', groups)

@socketio.on('select_group')
def on_select_group(g):
    global current_group, votes
    # auto‐save previous if any
    if current_group:
        yes = sum(1 for v in votes.values() if v == 'yes')
        sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RESULTS_RANGE,
            valueInputOption='RAW',
            body={'values': [[current_group['id'], current_group['name'], yes]]}
        ).execute()
    current_group = g
    votes = {}
    emit('group_changed', g, broadcast=True)

@socketio.on('vote')
def on_vote(d):
    global votes
    jid, v = d.get('judge_id'), d.get('vote')
    if not current_group:
        return
    if jid in enabled_judges:
        votes[jid] = v
        yes = sum(1 for x in votes.values() if x == 'yes')
        emit('vote_update', {'count': yes}, broadcast=True)

@socketio.on('toggle_judge')
def on_toggle(d):
    jid = d.get('judge_id')
    if jid in enabled_judges:
        enabled_judges.remove(jid)
    else:
        enabled_judges.add(jid)
    emit('judge_toggled',
         {'judge_id': jid, 'enabled': jid in enabled_judges},
         broadcast=True)

@socketio.on('reset_votes')
def on_reset_votes():
    """Just reset everything (no saving)."""
    global current_group, votes
    current_group = None
    votes = {}
    emit('all_reset', broadcast=True)

@socketio.on('save_and_reset')
def on_save_and_reset():
    """Save current result, then reset."""
    global current_group, votes
    # use HK time zone
    import datetime
    timestamp = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    if current_group:
        yes = sum(1 for v in votes.values() if v == 'yes')
        sheets.values().append(
            spreadsheetId=SPREADSHEET_ID,
            range=RESULTS_RANGE,
            valueInputOption='RAW',
            body={'values': [[timestamp, current_group['id'], current_group['name'], yes]]}
        ).execute()
    current_group = None
    votes = {}
    emit('all_reset', broadcast=True)
    
@socketio.on('force_refresh')
def on_force_refresh(data):
    tgt = data.get('target')
    if tgt == 'judges':
        emit('do_refresh', broadcast=True, include_self=False)
    elif tgt == 'dashboard':
        emit('do_refresh_dashboard', broadcast=True)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000)
