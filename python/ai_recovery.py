import os
import pandas as pd
import anthropic
from stats import check_anomaly

CSV_FILE = r"C:\Users\Lucas\OneDrive\Desktop\hrv-runner\python\hrv_data.csv"
WINDOW = 14
GOOD_FEEL_THRESHOLD = 4
MIN_BASELINE_ROWS = 5


def load_hrv_data(csv_path):
    df = pd.read_csv(csv_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp")


def parse_numeric(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def build_recent_context(df, window=WINDOW, good_feel_threshold=GOOD_FEEL_THRESHOLD):
    if len(df) == 0:
        raise ValueError("HRV data is empty.")

    recent = df.tail(window)
    today = recent.iloc[-1]
    history = recent.iloc[:-1]

    baseline_candidates = history.copy()
    baseline_candidates["feel"] = pd.to_numeric(baseline_candidates["feel"], errors="coerce")
    good_days = baseline_candidates[baseline_candidates["feel"] >= good_feel_threshold]
    baseline_rows = good_days if len(good_days) >= MIN_BASELINE_ROWS else history
    baseline_source = (
        f"recent good-feeling days (feel >= {good_feel_threshold})"
        if len(good_days) >= MIN_BASELINE_ROWS
        else "recent days (not enough high-feel days logged yet)"
    )

    baseline_rmssd = pd.to_numeric(baseline_rows["rmssd_ms"], errors="coerce")
    baseline_mean = baseline_rmssd.mean()
    baseline_std = baseline_rmssd.std()

    return {
        "timestamp": today["timestamp"],
        "today_rmssd": parse_numeric(today["rmssd_ms"]),
        "baseline_mean": baseline_mean,
        "baseline_std": baseline_std,
        "baseline_source": baseline_source,
        "today_feel": parse_numeric(today["feel"]),
        "today_miles": parse_numeric(today.get("miles", "")),
        "today_duration": parse_numeric(today.get("duration_min", "")),
        "today_rpe": parse_numeric(today.get("rpe", "")),
        "today_training_load": parse_numeric(today.get("training_load", "")),
    }


def format_training_context(context):
    training_load = context["today_training_load"]
    if training_load is None or pd.isna(training_load):
        training_load_text = "No training load recorded for the previous day."
    else:
        training_load_text = f"Previous day training load: {training_load:.1f}."

    feel_text = (
        f"Today's subjective feel score is {context['today_feel']:.0f}/5."
        if context["today_feel"] is not None and not pd.isna(context["today_feel"])
        else "No subjective feel score recorded for today."
    )

    run_details = []
    if context["today_miles"] is not None and not pd.isna(context["today_miles"]):
        run_details.append(f"distance {context['today_miles']:.1f} miles")
    if context["today_duration"] is not None and not pd.isna(context["today_duration"]):
        run_details.append(f"duration {context['today_duration']:.0f} min")
    if context["today_rpe"] is not None and not pd.isna(context["today_rpe"]):
        run_details.append(f"RPE {context['today_rpe']:.0f}")

    run_text = (
        "Previous day run details: " + ", ".join(run_details) + "."
        if run_details
        else "No previous-day run details were recorded."
    )

    return training_load_text + " " + feel_text + " " + run_text


def build_prompt(context, anomaly_readout):
    baseline_mean = context["baseline_mean"]
    baseline_std = context["baseline_std"]

    baseline_text = (
        f"Baseline average RMSSD from {context['baseline_source']}: {baseline_mean:.1f} ms"
        if baseline_mean is not None and not pd.isna(baseline_mean)
        else "Baseline average RMSSD could not be calculated from recent data."
    )

    baseline_variability = (
        f"Baseline RMSSD standard deviation: {baseline_std:.1f} ms."
        if baseline_std is not None and not pd.isna(baseline_std)
        else "Baseline RMSSD variability is not available."
    )

    return f"""You are helping interpret HRV recovery data for a runner. Review the following and give a short, direct recovery assessment grounded in the specific numbers.

Today's RMSSD: {context['today_rmssd']:.1f} ms
{baseline_text}
{baseline_variability}
Statistical readout: {anomaly_readout}
{format_training_context(context)}

Give a 2-3 sentence recovery assessment, stating whether today should be treated as a recovery day, easy training, or normal training. Reason about my personal trend, not generic population ranges."""


def get_claude_assessment(prompt, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text.strip()


def main():
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Please set the ANTHROPIC_API_KEY environment variable before running this script."
        )

    df = load_hrv_data(CSV_FILE)
    context = build_recent_context(df)
    anomaly_readout = check_anomaly(CSV_FILE)
    prompt = build_prompt(context, anomaly_readout)
    assessment = get_claude_assessment(prompt, api_key)

    print(assessment)

if __name__ == "__main__":
    main()
