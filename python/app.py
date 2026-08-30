# Creates HRV dashboard with charts and recovery assessment using Flask, pandas, and Chart.js.
# Requires ANTHROPIC_API_KEY environment variable for recovery assessment.

from flask import Flask, render_template_string
import pandas as pd
import os
import json
import time
from stats import check_anomaly
from ai_recovery import load_hrv_data, build_recent_context, build_prompt, get_claude_assessment

CSV_FILE = os.path.join(os.path.dirname(__file__), "hrv_data.csv")
CACHE_TTL_SECONDS = 3600

app = Flask(__name__)

# In-memory cache so refreshing the page doesn't trigger a new API call
# every time. Resets when the Flask server restarts.
_assessment_cache = {"text": None, "timestamp": 0}

def load_data():
    df = pd.read_csv(CSV_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")
    df["training_load"] = pd.to_numeric(df["training_load"], errors="coerce")
    return df

# Returns the cached assessment if still fresh; otherwise builds a new
# prompt using the shared ai_recovery logic and calls the Claude API.
def get_assessment():
    now = time.time()
    if _assessment_cache["text"] and (now - _assessment_cache["timestamp"] < CACHE_TTL_SECONDS):
        return _assessment_cache["text"]

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return "Set ANTHROPIC_API_KEY to enable the recovery assessment."

    df = load_hrv_data(CSV_FILE)
    if len(df) < 2:
        return "Log a few more mornings to unlock the recovery assessment."

    context = build_recent_context(df)
    anomaly_readout = check_anomaly(CSV_FILE)
    prompt = build_prompt(context, anomaly_readout)

    try:
        text = get_claude_assessment(prompt, api_key)
        _assessment_cache["text"] = text
        _assessment_cache["timestamp"] = now
        return text
    except Exception as e:
        return f"Assessment unavailable: {e}"

@app.route("/")
def dashboard():
    df = load_data()

    labels = df["timestamp"].dt.strftime("%b %d").tolist()
    rmssd = df["rmssd_ms"].round(1).tolist()
    load = df["training_load"].fillna(0).round(0).tolist()
    feel = df["feel"].tolist()

    latest_rmssd = round(df["rmssd_ms"].iloc[-1], 1)
    baseline = round(df[pd.to_numeric(df["feel"], errors="coerce") >= 4]["rmssd_ms"].mean(), 1)
    delta = round(latest_rmssd - baseline, 1)
    latest_load = df["training_load"].iloc[-1]
    latest_load_str = "—" if pd.isna(latest_load) else f"{int(latest_load)}"
    days_logged = len(df)

    assessment = get_assessment()

    html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>HRV-Runner Dashboard</title>
<style>
  :root {{
    --bg: #ffffff; --card: #f7f7f5; --border: rgba(11,11,11,0.10);
    --text: #0b0b0b; --text2: #52514e; --muted: #898781;
    --blue: #2a78d6; --coral: #d85a30;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #1a1a19; --card: #232322; --border: rgba(255,255,255,0.10);
      --text: #f0efec; --text2: #c3c2b7; --muted: #898781;
      --blue: #3987e5; --coral: #eb6834;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; padding: 32px 24px; background: var(--bg); color: var(--text);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  }}
  .wrap {{ max-width: 920px; margin: 0 auto; }}
  h1 {{ font-size: 22px; font-weight: 500; margin: 0 0 4px; }}
  .sub {{ color: var(--text2); font-size: 14px; margin: 0 0 28px; }}
  .cards {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin-bottom: 24px; }}
  .card {{ background: var(--card); border-radius: 8px; padding: 16px; }}
  .card .label {{ font-size: 13px; color: var(--muted); margin-bottom: 6px; }}
  .card .value {{ font-size: 24px; font-weight: 500; }}
  .card .delta {{ font-size: 13px; margin-top: 4px; color: var(--text2); }}
  .delta.up {{ color: var(--blue); }}
  .delta.down {{ color: var(--coral); }}
  .assessment {{ background: var(--card); border-left: 3px solid var(--blue); border-radius: 8px; padding: 16px 20px; margin-bottom: 32px; }}
  .assessment .label {{ font-size: 13px; color: var(--muted); margin-bottom: 8px; }}
  .assessment .text {{ font-size: 15px; line-height: 1.6; color: var(--text); }}
  .section {{ margin-bottom: 32px; }}
  .section h2 {{ font-size: 15px; font-weight: 500; color: var(--text2); margin: 0 0 12px; }}
  .chart-wrap {{ position: relative; height: 220px; background: var(--card); border-radius: 8px; padding: 16px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>HRV-Runner Dashboard</h1>
  <p class="sub">{days_logged} mornings logged · updated automatically</p>

  <div class="cards">
    <div class="card">
      <div class="label">Latest HRV (RMSSD)</div>
      <div class="value">{latest_rmssd} ms</div>
      <div class="delta {'up' if delta >= 0 else 'down'}">{'+' if delta >= 0 else ''}{delta} ms vs baseline</div>
    </div>
    <div class="card">
      <div class="label">Personal baseline</div>
      <div class="value">{baseline} ms</div>
      <div class="delta">good-feeling days avg</div>
    </div>
    <div class="card">
      <div class="label">Latest training load</div>
      <div class="value">{latest_load_str}</div>
      <div class="delta">duration × RPE</div>
    </div>
    <div class="card">
      <div class="label">Days logged</div>
      <div class="value">{days_logged}</div>
      <div class="delta">since Jul 13</div>
    </div>
  </div>

  <div class="assessment">
    <div class="label">Recovery Assessment</div>
    <div class="text">{assessment}</div>
  </div>

  <div class="section">
    <h2>Morning HRV over time</h2>
    <div class="chart-wrap"><canvas id="rmssdChart" role="img" aria-label="Line chart of morning RMSSD in milliseconds over time"></canvas></div>
  </div>

  <div class="section">
    <h2>Previous day's training load</h2>
    <div class="chart-wrap"><canvas id="loadChart" role="img" aria-label="Bar chart of training load, duration times perceived effort"></canvas></div>
  </div>

  <div class="section">
    <h2>Subjective feel score</h2>
    <div class="chart-wrap"><canvas id="feelChart" role="img" aria-label="Line chart of daily subjective feel score, 1 to 5"></canvas></div>
  </div>
</div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.js"></script>
<script>
const labels = {json.dumps(labels)};
const rmssd = {json.dumps(rmssd)};
const load = {json.dumps(load)};
const feel = {json.dumps(feel)};
const isDark = matchMedia('(prefers-color-scheme: dark)').matches;
const ink = isDark ? '#c3c2b7' : '#52514e';
const grid = isDark ? '#2c2c2a' : '#e1e0d9';
const blue = isDark ? '#3987e5' : '#2a78d6';
const coral = isDark ? '#eb6834' : '#d85a30';

// Shared chart scale options for consistent styling
const commonScales = {{
  x: {{ ticks: {{ color: ink, font: {{ size: 11 }}, maxRotation: 45, autoSkip: true }}, grid: {{ display: false }} }},
  y: {{ ticks: {{ color: ink, font: {{ size: 11 }} }}, grid: {{ color: grid }} }}
}};

new Chart(document.getElementById('rmssdChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{ data: rmssd, borderColor: blue, backgroundColor: blue + '1a', fill: true, tension: 0.25, pointRadius: 3, pointBackgroundColor: blue, borderWidth: 2 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: commonScales }}
}});

new Chart(document.getElementById('loadChart'), {{
  type: 'bar',
  data: {{ labels, datasets: [{{ data: load, backgroundColor: coral, borderRadius: 3 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: commonScales }}
}});

new Chart(document.getElementById('feelChart'), {{
  type: 'line',
  data: {{ labels, datasets: [{{ data: feel, borderColor: blue, backgroundColor: blue + '1a', fill: true, tension: 0.25, pointRadius: 3, pointBackgroundColor: blue, borderWidth: 2 }}] }},
  options: {{ responsive: true, maintainAspectRatio: false, plugins: {{ legend: {{ display: false }} }}, scales: {{ ...commonScales, y: {{ ...commonScales.y, min: 0, max: 6}} }} }}
}});
</script>
</body>
</html>
"""
    return render_template_string(html)

if __name__ == "__main__":
    app.run(debug=True)