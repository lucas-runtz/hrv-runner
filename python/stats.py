import pandas as pd

def check_anomaly(csv_path, window=14, threshold=1.5):
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp")

    if len(df) < 5:
        return "Not enough data to detect anomalies. Please log more HRV data."

    recent = df.tail(window)
    today = recent.iloc[-1]
    history = recent.iloc[:-1]

    mean = history["rmssd_ms"].mean()
    std = history["rmssd_ms"].std()

    if std == 0 or pd.isna(std):
        return "Not enough variation in recent data to calculate anomaly score."

    z_score = (today["rmssd_ms"] - mean) / std

    if z_score <= -threshold:
        return f"Anomaly detected: today's HRV ({today['rmssd_ms']}ms) is {abs(z_score):.1f} standard deviations below your recent average ({mean:.1f}ms)."
    else:
        return f"No anomaly. Today's HRV ({today['rmssd_ms']}ms) is {z_score:.2f} standard deviations from your recent average ({mean:.1f}ms)."