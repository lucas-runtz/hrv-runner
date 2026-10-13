# HRV-Runner: the whole workflow in one place. Takes a reading from the
# Arduino, saves the daily log entry, and shows trends plus a
# Claude-generated recovery assessment.

import csv
import datetime
import os
import queue
import re
import threading
import time
from pathlib import Path

import pandas as pd
import serial
from flask import Flask, jsonify, render_template_string, request

from stats import check_anomaly
from ai_recovery import build_recent_context, build_prompt, get_claude_assessment

PORT = "COM3"  # change this if your Arduino shows up on a different port
BAUD = 115200
CSV_FILE = os.path.join(os.path.dirname(__file__), "hrv_data.csv")
CSV_HEADER = ["timestamp", "rmssd_ms", "beats", "bpm", "feel",
              "sleep_hours", "miles", "duration_min", "rpe", "training_load"]
NUMERIC_COLUMNS = CSV_HEADER[1:]
CACHE_TTL_SECONDS = 3600
SESSION_SECONDS = 60
# The API key is saved in your home folder, outside the project, so it can
# never end up in a git commit.
KEY_FILE = Path.home() / ".hrv-runner" / "api_key"

app = Flask(__name__)

# In-memory cache so refreshing the page doesn't trigger a new API call
# every time. Cleared whenever a new reading is saved.
_assessment_cache = {"text": None, "timestamp": 0}

# ---- Live Arduino state ----------------------------------------------------
# A background thread owns the serial port and keeps _live up to date.
# The page reads it through /api/status.

_state_lock = threading.Lock()
_commands = queue.Queue()
BEAT_LINE = re.compile(r"Beat (\d+)\s+RR:\s*(\d+)ms\s+RMSSD:\s*([\d.]+)")

def new_live(connection, message):
    return {"connection": connection, "phase": "waiting", "message": message,
            "beats": 0, "rr": None, "rmssd": None, "started": None, "result": None}

_live = new_live("disconnected", "Looking for the Arduino...")

def update_live(**fields):
    with _state_lock:
        _live.update(fields)

def handle_line(line):
    beat = BEAT_LINE.match(line)
    if beat:
        number, rr, rmssd = int(beat.group(1)), int(beat.group(2)), float(beat.group(3))
        with _state_lock:
            # Beat numbers dropping back down means the Arduino began a new reading
            if _live["started"] is None or number < _live["beats"]:
                _live["started"] = time.time()
            _live.update(phase="measuring",
                         message="Measuring. Hold still with light, steady pressure.",
                         beats=number, rr=rr, rmssd=rmssd, result=None)
    elif line.startswith("RMSSD:"):
        # Final summary line, e.g. RMSSD:108.6,beats:60,bpm:68
        try:
            parts = dict(item.split(":") for item in line.split(","))
            result = {"rmssd": float(parts["RMSSD"]), "beats": int(parts["beats"]),
                      "bpm": int(parts["bpm"])}
        except (ValueError, KeyError):
            return
        update_live(phase="complete",
                    message="Reading complete. Add today's details and save.",
                    result=result)
    elif line.startswith("Hub not responding"):
        update_live(phase="error", message=line)
    elif line.startswith("Ready."):
        with _state_lock:
            _live.update(new_live("connected",
                                  "Arduino ready. Rest your finger on the sensor and hold still."))

def serial_worker():
    while True:
        try:
            ser = serial.Serial(PORT, BAUD, timeout=1)
        except serial.SerialException:
            update_live(connection="disconnected",
                        message=f"Arduino not found on {PORT}. Plug it in and close anything else "
                                "using the port (Serial Monitor, logger.py).")
            time.sleep(3)
            continue

        with _state_lock:
            _live.update(new_live("connected",
                                  "Connected. The Arduino is restarting, then rest your finger on the sensor."))
        try:
            while True:
                while not _commands.empty():
                    ser.write(_commands.get_nowait())
                line = ser.readline().decode(errors="ignore").strip()
                if line:
                    handle_line(line)
        except (serial.SerialException, OSError):
            update_live(connection="disconnected",
                        message="Lost connection to the Arduino. Trying to reconnect...")
        finally:
            ser.close()
        time.sleep(3)

# ---- Data ------------------------------------------------------------------

def load_data():
    if os.path.isfile(CSV_FILE):
        df = pd.read_csv(CSV_FILE)
    else:
        df = pd.DataFrame(columns=CSV_HEADER)
    df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed", errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    for column in NUMERIC_COLUMNS:
        # A bad cell becomes a gap instead of breaking the whole dashboard
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
        else:
            df[column] = float("nan")
    return df

def to_list(series, digits=None):
    values = []
    for value in series.tolist():
        if pd.isna(value):
            values.append(None)
        else:
            values.append(round(value, digits) if digits is not None else value)
    return values

def to_number(value):
    try:
        return float(str(value).strip())
    except ValueError:
        return None

def fmt(value):
    if value is None:
        return ""
    return str(int(value)) if float(value).is_integer() else str(value)

def append_row(row):
    new_file = not os.path.isfile(CSV_FILE) or os.path.getsize(CSV_FILE) == 0
    needs_newline = False
    if not new_file:
        # If the file doesn't end in a newline, the new row would stick to the last one
        with open(CSV_FILE, "rb") as f:
            f.seek(-1, os.SEEK_END)
            needs_newline = f.read(1) not in (b"\n", b"\r")
    with open(CSV_FILE, "a", newline="") as f:
        if needs_newline:
            f.write("\n")
        writer = csv.writer(f)
        if new_file:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

def saved_api_key():
    try:
        return KEY_FILE.read_text().strip()
    except OSError:
        return ""

# A key entered in the app wins; the ANTHROPIC_API_KEY environment variable
# still works as a fallback.
def get_api_key():
    return saved_api_key() or os.getenv("ANTHROPIC_API_KEY", "").strip()

def save_api_key(key):
    KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(key)
    try:
        os.chmod(KEY_FILE, 0o600)  # owner-only where the OS supports it
    except OSError:
        pass

# Returns the cached assessment if still fresh; otherwise builds a new
# prompt using the shared ai_recovery logic and calls the Claude API.
def get_assessment():
    now = time.time()
    if _assessment_cache["text"] and (now - _assessment_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _assessment_cache["text"]

    api_key = get_api_key()
    if not api_key:
        return "Add your Anthropic API key below to enable the recovery assessment."
    df = load_data()
    if len(df) < 2:
        return "Log a few more mornings to unlock the recovery assessment."

    try:
        context = build_recent_context(df)
        prompt = build_prompt(context, check_anomaly(CSV_FILE))
        text = get_claude_assessment(prompt, api_key)
        _assessment_cache["text"] = text
        _assessment_cache["timestamp"] = now
        return text
    except Exception as e:
        return f"Assessment unavailable: {e}"

# ---- API used by the page --------------------------------------------------

@app.route("/api/status")
def api_status():
    with _state_lock:
        data = dict(_live)
    started = data.pop("started")
    data["elapsed"] = round(time.time() - started) if started and data["phase"] == "measuring" else 0
    return jsonify(data)

@app.route("/api/reset", methods=["POST"])
def api_reset():
    # The firmware restarts its reading when it receives "r"
    _commands.put(b"r")
    with _state_lock:
        _live.update(new_live(_live["connection"], "Restarted. Rest your finger on the sensor."))
    return jsonify(ok=True)

@app.route("/api/save", methods=["POST"])
def api_save():
    form = request.get_json(silent=True) or {}

    feel = to_number(form.get("feel"))
    if feel not in (1, 2, 3, 4, 5):
        return jsonify(ok=False, error="Feel score must be a whole number from 1 to 5."), 400
    sleep = to_number(form.get("sleep"))
    miles = to_number(form.get("miles"))
    duration = to_number(form.get("duration"))
    rpe = to_number(form.get("rpe"))
    if rpe is not None and not 1 <= rpe <= 10:
        return jsonify(ok=False, error="Effort (RPE) must be between 1 and 10."), 400

    # Same formula as logger.py: duration x RPE, blank if either is missing
    load = fmt(duration * rpe) if duration is not None and rpe is not None else ""

    with _state_lock:
        result = _live["result"]
        if not result:
            return jsonify(ok=False, error="There's no finished reading to save yet."), 400
        row = [datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%S.%f"), result["rmssd"], result["beats"],
               result["bpm"], int(feel), fmt(sleep), fmt(miles), fmt(duration), fmt(rpe), load]
        append_row(row)
        _live.update(new_live(_live["connection"], "Saved. Remove your finger to finish."))

    _assessment_cache["text"] = None  # next page load re-runs the assessment with today's reading
    _commands.put(b"r")               # get the Arduino ready for the next reading
    return jsonify(ok=True)

@app.route("/api/key", methods=["POST", "DELETE"])
def api_key():
    if request.method == "DELETE":
        KEY_FILE.unlink(missing_ok=True)
        _assessment_cache["text"] = None
        return jsonify(ok=True)

    form = request.get_json(silent=True) or {}
    key = str(form.get("key", "")).strip()
    if not key.startswith("sk-ant-") or len(key) < 20:
        return jsonify(ok=False, error="That doesn't look like an Anthropic API key. It should start with sk-ant-."), 400
    try:
        save_api_key(key)
    except OSError as e:
        return jsonify(ok=False, error=f"Couldn't save the key: {e}"), 500
    _assessment_cache["text"] = None  # next page load uses the new key
    return jsonify(ok=True)

# ---- Page ------------------------------------------------------------------

TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>HRV-Runner Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Manrope:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #eaf0f5; --panel: #ffffff; --panel2: #f3f7fa; --line: rgba(18,32,47,0.09);
    --ink: #12202f; --ink2: #475a6e; --muted: #66758a;
    --hrv: #0b9488; --load: #7357e8; --feel: #d98206; --sleep: #2a74d9;
    --good: #0b9488; --warn: #d9482b;
    --btn-bg: #0b7f78; --btn-ink: #ffffff;
    --shadow: 0 1px 2px rgba(18,32,47,0.06), 0 8px 24px rgba(18,32,47,0.05);
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #08121d; --panel: #101f31; --panel2: #0c1928; --line: rgba(255,255,255,0.08);
      --ink: #e8eef5; --ink2: #aebccc; --muted: #8394a8;
      --hrv: #3fd6c8; --load: #a28cff; --feel: #f5b84a; --sleep: #6aaaff;
      --good: #3fd6c8; --warn: #ff7a5c;
      --btn-bg: #3fd6c8; --btn-ink: #06222b;
      --shadow: 0 1px 2px rgba(0,0,0,0.3), 0 8px 24px rgba(0,0,0,0.25);
    }
  }
  * { box-sizing: border-box; }
  [hidden] { display: none !important; }
  body {
    margin: 0; padding: 28px 24px 56px; background: var(--bg); color: var(--ink);
    font-family: "Manrope", "Segoe UI", -apple-system, BlinkMacSystemFont, sans-serif;
    -webkit-font-smoothing: antialiased;
  }
  .wrap { max-width: 980px; margin: 0 auto; }
  button, input { font-family: inherit; }
  :focus-visible { outline: 2px solid var(--hrv); outline-offset: 2px; }

  .top { display: flex; align-items: center; gap: 14px; margin-bottom: 24px; }
  .top svg { width: 46px; height: 46px; color: var(--hrv); flex-shrink: 0; }
  .top h1 { font-size: clamp(34px, 6vw, 54px); font-weight: 800; letter-spacing: -0.035em; line-height: 1; margin: 0; white-space: nowrap; }
  .top .sub { margin-left: auto; font-size: 13px; color: var(--muted); }

  /* Hero: the one dark, dramatic element on the page */
  .hero {
    position: relative; overflow: hidden; border-radius: 20px; padding: 32px 36px 0;
    color: #eef4fa; margin-bottom: 20px;
    background:
      radial-gradient(900px 340px at 88% -10%, rgba(63,214,200,0.28), transparent 60%),
      radial-gradient(600px 300px at 0% 120%, rgba(115,87,232,0.30), transparent 60%),
      linear-gradient(160deg, #0f2540 0%, #0a1a2e 100%);
    box-shadow: var(--shadow);
  }
  .hero-top { display: flex; justify-content: space-between; align-items: flex-start; gap: 24px; position: relative; z-index: 1; }
  .hero-label { font-size: 15px; color: #a9bdd1; margin: 0 0 6px; }
  .hero-num { display: flex; align-items: baseline; gap: 8px; line-height: 1; }
  .hero-num .n { font-size: clamp(64px, 11vw, 104px); font-weight: 300; letter-spacing: -0.04em; font-variant-numeric: tabular-nums; }
  .hero-num .u { font-size: 22px; color: #a9bdd1; font-weight: 500; }
  .pill {
    display: inline-block; margin-top: 14px; padding: 6px 14px; border-radius: 999px;
    font-size: 14px; font-weight: 600; background: rgba(255,255,255,0.08); color: #dbe6f1;
  }
  .pill.up { background: rgba(63,214,200,0.16); color: #5eeadc; }
  .pill.down { background: rgba(255,122,92,0.16); color: #ff9a82; }
  .ecg { position: absolute; right: -10px; top: 20px; width: min(58%, 520px); height: 150px; opacity: 0.95; z-index: 0; }
  .ecg path {
    fill: none; stroke: #ff4d4d; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round;
    stroke-dasharray: 1000; stroke-dashoffset: 1000;
    animation: pulse 4.5s ease-in-out infinite;
    filter: drop-shadow(0 0 6px rgba(255,77,77,0.65));
  }
  /* Draws left to right, holds, then wipes away in the same direction and starts again */
  @keyframes pulse {
    0% { stroke-dashoffset: 1000; }
    55% { stroke-dashoffset: 0; }
    80% { stroke-dashoffset: 0; }
    100% { stroke-dashoffset: -1000; }
  }
  @media (prefers-reduced-motion: reduce) { .ecg path { animation: none; stroke-dashoffset: 0; } }
  .stats { display: grid; grid-template-columns: repeat(3, 1fr); margin-top: 30px; border-top: 1px solid rgba(255,255,255,0.10); position: relative; z-index: 1; }
  .stat { padding: 18px 0 20px; }
  .stat + .stat { padding-left: 24px; border-left: 1px solid rgba(255,255,255,0.10); }
  .stat .k { font-size: 13px; color: #9fb3c7; margin-bottom: 4px; }
  .stat .v { font-size: 24px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .stat .d { font-size: 12px; color: #8fa5ba; margin-top: 2px; }

  .panel { background: var(--panel); border-radius: 16px; padding: 22px 26px; margin-bottom: 20px; box-shadow: var(--shadow); border: 1px solid var(--line); }
  .panel-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; gap: 12px; }
  .panel-head h2, .chart-card h2 { font-size: 16px; font-weight: 700; margin: 0; letter-spacing: -0.005em; }
  .conn { font-size: 12px; font-weight: 600; padding: 4px 12px; border-radius: 999px; background: var(--panel2); color: var(--muted); border: 1px solid var(--line); white-space: nowrap; }
  .conn.ok { color: var(--good); }
  .conn.off { color: var(--warn); }
  .conn::before { content: ""; display: inline-block; width: 7px; height: 7px; border-radius: 50%; background: currentColor; margin-right: 7px; }
  .reading-msg { font-size: 15px; line-height: 1.55; color: var(--ink2); margin-bottom: 12px; }
  .progress { height: 8px; border-radius: 4px; background: var(--panel2); overflow: hidden; margin-bottom: 14px; }
  .progress .bar { height: 100%; width: 0; background: linear-gradient(90deg, var(--hrv), var(--sleep)); border-radius: 4px; transition: width 0.5s linear; }
  .live { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 12px; }
  .live > div { background: var(--panel2); border-radius: 12px; padding: 12px 14px; }
  .live .k { display: block; font-size: 12px; color: var(--muted); margin-bottom: 2px; }
  .live .v { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; }
  .result { font-size: 15px; font-weight: 600; margin-bottom: 14px; }
  .fields { display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; margin-bottom: 14px; }
  .fields label { font-size: 12px; color: var(--muted); display: flex; flex-direction: column; gap: 5px; }
  input {
    padding: 9px 10px; border-radius: 10px; border: 1px solid var(--line);
    background: var(--panel2); color: var(--ink); font-size: 14px; width: 100%;
  }
  input::placeholder { color: var(--muted); }
  button {
    background: var(--btn-bg); color: var(--btn-ink); border: 0; border-radius: 10px;
    padding: 9px 16px; font-size: 14px; font-weight: 600; cursor: pointer;
  }
  button:hover { filter: brightness(1.08); }
  button.secondary { background: transparent; color: var(--ink2); border: 1px solid var(--line); font-weight: 500; }
  button.linkbtn { background: none; border: 0; padding: 0; color: var(--hrv); font-size: 12px; font-weight: 600; cursor: pointer; }
  button:disabled { opacity: 0.6; cursor: default; }
  .hint .linkbtn { margin-left: 8px; }
  .actions { display: flex; gap: 10px; align-items: center; }
  .error { color: var(--warn); font-size: 13px; margin-top: 8px; }

  .assessment { background: linear-gradient(135deg, color-mix(in srgb, var(--hrv) 14%, var(--panel)), var(--panel) 70%); }
  .assessment .text { font-size: 18px; line-height: 1.6; font-weight: 500; max-width: 68ch; }
  .keyform { display: flex; gap: 10px; margin-top: 14px; }
  .keyform input { flex: 1; }
  .hint { font-size: 12px; color: var(--muted); margin-top: 12px; line-height: 1.5; }

  .charts { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }
  .chart-card { background: var(--panel); border-radius: 16px; padding: 20px 22px 18px; box-shadow: var(--shadow); border: 1px solid var(--line); }
  .chart-card.wide { grid-column: 1 / -1; }
  .chart-card .note { font-size: 13px; color: var(--muted); margin: 3px 0 12px; }
  .chart-wrap { position: relative; height: 230px; }
  .chart-card.wide .chart-wrap { height: 270px; }
  .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 8px; vertical-align: baseline; }

  @media (max-width: 760px) {
    body { padding: 18px 14px 40px; }
    .top .sub { display: none; }
    .hero { padding: 24px 20px 0; }
    .ecg { opacity: 0.35; width: 90%; }
    .stats { grid-template-columns: 1fr; }
    .stat + .stat { padding-left: 0; border-left: 0; border-top: 1px solid rgba(255,255,255,0.10); }
    .fields { grid-template-columns: repeat(2, 1fr); }
    .live { grid-template-columns: 1fr; }
    .charts { grid-template-columns: 1fr; }
    .keyform { flex-direction: column; }
  }
</style>
</head>
<body>
<div class="wrap">
  <div class="top">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 12h4l2-6 4 12 2-6h6"/></svg>
    <h1>HRV-Runner</h1>
  </div>

  <section class="hero">
    <svg class="ecg" viewBox="0 0 600 150" preserveAspectRatio="none" aria-hidden="true">
      <path pathLength="1000" d="M0,80 H110 L124,72 L138,80 H190 L202,90 L216,18 L232,128 L246,80 H300 L316,68 L334,80 H420 L432,90 L446,36 L460,116 L472,80 H600"/>
    </svg>
    <div class="hero-top">
      <div>
        <p class="hero-label">Latest morning HRV</p>
        <div class="hero-num"><span class="n">{{ latest_value }}</span><span class="u">ms</span></div>
        <span class="pill {{ delta_class }}">{{ delta_text }}</span>
      </div>
    </div>
    <div class="stats">
      <div class="stat">
        <div class="k">Personal baseline</div>
        <div class="v">{{ baseline }}</div>
        <div class="d">average on days you felt good</div>
      </div>
      <div class="stat">
        <div class="k">Latest training load</div>
        <div class="v">{{ latest_load }}</div>
        <div class="d">run minutes × effort</div>
      </div>
      <div class="stat">
        <div class="k">Days logged</div>
        <div class="v">{{ days_logged }}</div>
        <div class="d">{{ since_text }}</div>
      </div>
    </div>
  </section>

  <section class="panel">
    <div class="panel-head">
      <h2>Today's reading</h2>
      <div class="conn" id="conn">Connecting...</div>
    </div>
    <div class="reading-msg" id="msg"></div>
    <div class="progress" id="progress" hidden><div class="bar" id="bar"></div></div>
    <div class="live" id="live" hidden>
      <div><span class="k">Beats counted</span><span class="v" id="beats">0</span></div>
      <div><span class="k">Last beat interval</span><span class="v" id="rr">-</span></div>
      <div><span class="k">HRV so far</span><span class="v" id="rmssd">-</span></div>
    </div>
    <form id="logform" hidden>
      <div class="result" id="result"></div>
      <div class="fields">
        <label>How do you feel? (1-5)<input name="feel" type="number" min="1" max="5" step="1" required></label>
        <label>Hours of sleep<input name="sleep" type="number" min="0" max="24" step="0.1"></label>
        <label>Miles yesterday<input name="miles" type="number" min="0" step="0.1"></label>
        <label>Run minutes yesterday<input name="duration" type="number" min="0" step="1"></label>
        <label>Effort, 1-10 (RPE)<input name="rpe" type="number" min="1" max="10" step="1"></label>
      </div>
      <div class="actions">
        <button type="submit" id="save">Save reading</button>
        <button type="button" class="secondary" id="discard">Discard and retake</button>
      </div>
      <div class="error" id="error"></div>
    </form>
    <div class="actions" id="restartRow">
      <button type="button" class="secondary" id="restart">Restart reading</button>
    </div>
  </section>

  <section class="panel assessment">
    <div class="panel-head"><h2>Recovery assessment</h2></div>
    <div class="text">{{ assessment }}</div>
    {% if has_key %}
    <div class="hint">
      Using API key ending in {{ key_hint }} ({{ 'saved on this computer' if key_saved else 'from your environment' }}).
      <button type="button" class="linkbtn" id="changekey">Change</button>{% if key_saved %}
      <button type="button" class="linkbtn" id="removekey">Remove</button>{% endif %}
    </div>
    {% endif %}
    <form class="keyform" id="keyform" {% if has_key %}hidden{% endif %}>
      <input name="key" type="password" placeholder="Paste your Anthropic API key (sk-ant-...)" autocomplete="off" required>
      <button type="submit" id="savekey">Save key</button>
    </form>
    <div class="error" id="keyerror"></div>
    {% if not has_key %}
    <div class="hint">Get a key at console.anthropic.com. It is stored only on this computer, in your home folder, never in the project.</div>
    {% endif %}
  </section>

  <div class="charts">
    <section class="chart-card wide">
      <h2><span class="swatch" style="background: var(--hrv)"></span>Morning HRV</h2>
      <p class="note">{{ range_text }}. The dashed line is your personal baseline.</p>
      <div class="chart-wrap"><canvas id="rmssdChart" role="img" aria-label="Line chart of morning HRV in milliseconds over time, with a dashed personal baseline"></canvas></div>
    </section>

    <section class="chart-card">
      <h2><span class="swatch" style="background: var(--load)"></span>Previous day's training load</h2>
      <p class="note">Run minutes times effort (RPE). The latest day is highlighted.</p>
      <div class="chart-wrap"><canvas id="loadChart" role="img" aria-label="Bar chart of training load, duration times perceived effort"></canvas></div>
    </section>

    <section class="chart-card">
      <h2><span class="swatch" style="background: var(--feel)"></span>How you felt</h2>
      <p class="note">1 is rough, 5 is great.</p>
      <div class="chart-wrap"><canvas id="feelChart" role="img" aria-label="Line chart of daily subjective feel score, 1 to 5"></canvas></div>
    </section>

    <section class="chart-card wide">
      <h2><span class="swatch" style="background: var(--sleep)"></span>Sleep</h2>
      <p class="note">Hours per night. Gaps are days before sleep was logged.</p>
      <div class="chart-wrap"><canvas id="sleepChart" role="img" aria-label="Line chart of hours of sleep per night"></canvas></div>
    </section>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const SESSION_SECONDS = {{ session_seconds }};
const $ = (id) => document.getElementById(id);

// Live reading panel: polls the server, which polls the Arduino
async function refresh() {
  let s;
  try {
    s = await (await fetch('/api/status')).json();
  } catch (e) {
    $('conn').textContent = 'Dashboard server not responding';
    $('conn').className = 'conn off';
    return;
  }
  const connected = s.connection === 'connected';
  $('conn').textContent = connected ? 'Arduino connected' : 'Arduino not connected';
  $('conn').className = 'conn ' + (connected ? 'ok' : 'off');
  $('msg').textContent = s.message || '';

  const measuring = s.phase === 'measuring';
  const complete = s.phase === 'complete';
  $('progress').hidden = !measuring;
  $('bar').style.width = Math.min(100, (s.elapsed / SESSION_SECONDS) * 100) + '%';
  $('live').hidden = !(measuring || complete);
  $('beats').textContent = s.beats;
  $('rr').textContent = s.rr ? s.rr + ' ms' : '-';
  $('rmssd').textContent = s.rmssd !== null ? s.rmssd + ' ms' : '-';
  $('logform').hidden = !complete;
  $('restartRow').hidden = complete;
  if (complete && s.result) {
    $('result').textContent = 'HRV ' + s.result.rmssd + ' ms from ' + s.result.beats + ' beats (sensor BPM ' + s.result.bpm + ')';
  }
}

async function restart() {
  await fetch('/api/reset', { method: 'POST' });
  refresh();
}
$('restart').addEventListener('click', restart);
$('discard').addEventListener('click', restart);

$('logform').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('error').textContent = '';
  $('save').disabled = true;
  $('save').textContent = 'Saving...';
  const data = Object.fromEntries(new FormData(e.target).entries());
  const res = await fetch('/api/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  });
  const out = await res.json();
  if (out.ok) {
    location.reload();
  } else {
    $('error').textContent = out.error;
    $('save').disabled = false;
    $('save').textContent = 'Save reading';
  }
});

// API key: saved from the page so nobody has to edit the script
$('keyform').addEventListener('submit', async (e) => {
  e.preventDefault();
  $('keyerror').textContent = '';
  $('savekey').disabled = true;
  const res = await fetch('/api/key', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(Object.fromEntries(new FormData(e.target).entries()))
  });
  const out = await res.json();
  if (out.ok) {
    location.reload();
  } else {
    $('keyerror').textContent = out.error;
    $('savekey').disabled = false;
  }
});
if ($('changekey')) $('changekey').addEventListener('click', () => { $('keyform').hidden = false; });
if ($('removekey')) $('removekey').addEventListener('click', async () => {
  await fetch('/api/key', { method: 'DELETE' });
  location.reload();
});

setInterval(refresh, 1000);
refresh();

// Charts: colors come from the CSS variables so light and dark stay in sync
const css = getComputedStyle(document.documentElement);
const token = (name) => css.getPropertyValue(name).trim();
const labels = {{ labels|tojson }};
const rmssd = {{ rmssd|tojson }};
const load = {{ load|tojson }};
const feel = {{ feel|tojson }};
const sleep = {{ sleep|tojson }};
const baselineValue = {{ baseline_num|tojson }};
const cHrv = token('--hrv'), cLoad = token('--load'), cFeel = token('--feel'), cSleep = token('--sleep');
const ink2 = token('--ink2'), muted = token('--muted');
const gridColor = token('--line');

// Turn "#rrggbb" into rgba() so the area fills can fade out
function withAlpha(hex, alpha) {
  const n = parseInt(hex.slice(1), 16);
  return 'rgba(' + (n >> 16) + ',' + ((n >> 8) & 255) + ',' + (n & 255) + ',' + alpha + ')';
}
// Area fill that fades from the line color to transparent
function fade(color) {
  return (context) => {
    const area = context.chart.chartArea;
    if (!area) return withAlpha(color, 0.15);
    const g = context.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom);
    g.addColorStop(0, withAlpha(color, 0.35));
    g.addColorStop(1, withAlpha(color, 0));
    return g;
  };
}

Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
Chart.defaults.color = ink2;
Chart.defaults.plugins.tooltip.backgroundColor = '#0f2236';
Chart.defaults.plugins.tooltip.titleColor = '#ffffff';
Chart.defaults.plugins.tooltip.bodyColor = '#d5e1ee';
Chart.defaults.plugins.tooltip.padding = 10;
Chart.defaults.plugins.tooltip.cornerRadius = 8;
Chart.defaults.plugins.tooltip.displayColors = false;

// Show about 8 dates, but always the first and the very last one
const tickStep = Math.max(1, Math.ceil(labels.length / 8));
function tickLabel(index) {
  const last = labels.length - 1;
  if (index === last) return labels[index];
  if (index % tickStep !== 0) return '';
  if (last - index < tickStep / 2) return '';
  return labels[index];
}

function scales(extraY) {
  return {
    x: { ticks: { color: muted, font: { size: 11 }, maxRotation: 0, autoSkip: false, callback: (value, index) => tickLabel(index) }, grid: { display: false }, border: { display: false } },
    y: Object.assign({ ticks: { color: muted, font: { size: 11 }, padding: 6 }, grid: { color: gridColor }, border: { display: false } }, extraY || {})
  };
}
function options(unit, extraY) {
  return {
    responsive: true, maintainAspectRatio: false,
    layout: { padding: { right: 14 } },
    interaction: { mode: 'index', intersect: false },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (item) => (item.dataset.label || '') + ': ' + item.formattedValue + unit } }
    },
    scales: scales(extraY)
  };
}
// Make the latest point stand out
function lastPoint(values, size) {
  return values.map((v, i) => (i === values.length - 1 ? size : 0));
}

const hrvSets = [{
  label: 'HRV', data: rmssd, borderColor: cHrv, backgroundColor: fade(cHrv), fill: true,
  tension: 0.35, borderWidth: 2.5, spanGaps: true,
  pointRadius: lastPoint(rmssd, 5), pointHoverRadius: 6,
  pointBackgroundColor: cHrv, pointBorderColor: token('--panel'), pointBorderWidth: 2
}];
if (baselineValue !== null) {
  hrvSets.push({
    label: 'Baseline', data: labels.map(() => baselineValue), borderColor: muted, borderDash: [6, 6],
    borderWidth: 1.5, pointRadius: 0, pointHoverRadius: 0, fill: false
  });
}
new Chart($('rmssdChart'), { type: 'line', data: { labels, datasets: hrvSets }, options: options(' ms') });

new Chart($('loadChart'), {
  type: 'bar',
  data: { labels, datasets: [{
    label: 'Training load', data: load,
    backgroundColor: (c) => withAlpha(cLoad, c.dataIndex === load.length - 1 ? 1 : 0.55),
    borderRadius: 6, borderSkipped: false, maxBarThickness: 22
  }] },
  options: options('')
});

new Chart($('feelChart'), {
  type: 'line',
  data: { labels, datasets: [{
    label: 'Feel', data: feel, borderColor: cFeel, backgroundColor: fade(cFeel), fill: true,
    tension: 0.3, borderWidth: 2.5, spanGaps: true,
    pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: cFeel, pointBorderColor: token('--panel'), pointBorderWidth: 1.5
  }] },
  options: options(' / 5', { min: 0, max: 6, ticks: { stepSize: 1, color: muted, font: { size: 11 }, padding: 6, callback: (v) => (v >= 1 && v <= 5 ? v : '') } })
});

new Chart($('sleepChart'), {
  type: 'line',
  data: { labels, datasets: [{
    label: 'Sleep', data: sleep, borderColor: cSleep, backgroundColor: fade(cSleep), fill: true,
    tension: 0.3, borderWidth: 2.5, spanGaps: true,
    pointRadius: 3, pointHoverRadius: 6, pointBackgroundColor: cSleep, pointBorderColor: token('--panel'), pointBorderWidth: 1.5
  }] },
  options: options(' h', { min: 0, max: 10 })
});
</script>
</body>
</html>
"""

@app.route("/")
def dashboard():
    df = load_data()
    has_data = not df.empty

    latest = df["rmssd_ms"].iloc[-1] if has_data else None
    latest = None if latest is None or pd.isna(latest) else round(latest, 1)
    good_days = df[df["feel"] >= 4]["rmssd_ms"].dropna()
    baseline = round(good_days.mean(), 1) if len(good_days) else None
    if latest is None or baseline is None:
        delta_text, delta_class = "no baseline yet", ""
    else:
        delta = latest - baseline
        delta_text = f"{delta:+.1f} ms vs baseline"
        delta_class = "up" if delta >= 0 else "down"

    latest_load = df["training_load"].iloc[-1] if has_data else None
    since_text = f"since {df['timestamp'].min():%b %d}" if has_data else "no readings yet"

    range_text = f"{df['timestamp'].min():%b %d} to {df['timestamp'].max():%b %d}" if has_data else "No readings yet"
    key = get_api_key()
    return render_template_string(
        TEMPLATE,
        range_text=range_text,
        has_key=bool(key),
        key_hint=key[-4:],
        key_saved=bool(saved_api_key()),
        labels=df["timestamp"].dt.strftime("%b %d").tolist(),
        rmssd=to_list(df["rmssd_ms"], 1),
        load=to_list(df["training_load"].fillna(0), 0),
        feel=to_list(df["feel"]),
        sleep=to_list(df["sleep_hours"]),
        latest_value="-" if latest is None else f"{latest}",
        baseline_num=baseline,
        baseline="-" if baseline is None else f"{baseline} ms",
        delta_text=delta_text,
        delta_class=delta_class,
        latest_load="-" if latest_load is None or pd.isna(latest_load) else f"{latest_load:.0f}",
        days_logged=len(df),
        since_text=since_text,
        assessment=get_assessment(),
        session_seconds=SESSION_SECONDS,
    )

if __name__ == "__main__":
    threading.Thread(target=serial_worker, daemon=True).start()
    # No debug reloader: it would start a second process that fights over the serial port
    app.run(debug=False)