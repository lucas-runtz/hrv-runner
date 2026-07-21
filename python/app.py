from flask import Flask, render_template_string
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import base64
import os

CSV_FILE = os.path.join(os.path.dirname(__file__), "hrv_data.csv")

app = Flask(__name__)

def make_dashboard_image():
    df = pd.read_csv(CSV_FILE)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    fig, axes = plt.subplots(3, 1, figsize=(12, 9), sharex=True)

    axes[0].plot(df["timestamp"], df["rmssd_ms"], color="#1B4FD8", marker="o", linewidth=2)
    axes[0].set_ylabel("RMSSD (ms)")
    axes[0].set_title("Morning HRV Over Time")

    axes[1].bar(df["timestamp"], df["training_load"].fillna(0), color="#1A7A4A", alpha=0.7, width=0.5)
    axes[1].set_ylabel("Training Load")
    axes[1].set_title("Previous Day's Training Load (duration x RPE)")

    axes[2].plot(df["timestamp"], df["feel"], color="#B45309", marker="o")
    axes[2].set_ylabel("Feel (1-5)")
    axes[2].set_title("Subjective Feel Score")
    axes[2].set_ylim(0, 6)

    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode("utf-8")

@app.route("/")
def dashboard():
    img_data = make_dashboard_image()
    html = f"""
    <html>
    <head><title>HRV Runner Dashboard</title></head>
    <body style="font-family: sans-serif; text-align: center; padding: 40px;">
        <h1>HRV Runner Dashboard</h1>
        <img src="data:image/png;base64,{img_data}" style="max-width: 90%;">
    </body>
    </html>
    """
    return render_template_string(html)

if __name__ == "__main__":
    app.run(debug=True)