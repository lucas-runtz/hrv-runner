import os
import pandas as pd
from sklearn.linear_model import LinearRegression

CSV_FILE = os.path.join(os.path.dirname(__file__), "hrv_data.csv")

# Minimum number of complete rows (with both training load and HRV) required to run a regression
# Safeguard against running a regression on too few data points, which would give unreliable results
MIN_ROWS_FOR_REGRESSION = 10

# Minimum number of complete rows including sleep, needed before adding sleep as a second variable
MIN_ROWS_WITH_SLEEP = 15


def run_regression():
    df = pd.read_csv(CSV_FILE)

    df["training_load"] = pd.to_numeric(df["training_load"], errors="coerce")
    df["sleep_hours"] = pd.to_numeric(df["sleep_hours"], errors="coerce")
    df["rmssd_ms"] = pd.to_numeric(df["rmssd_ms"], errors="coerce")

    usable = df.dropna(subset=["training_load", "rmssd_ms"])

    if len(usable) < MIN_ROWS_FOR_REGRESSION:
        print(f"Only {len(usable)} complete rows logged. Need at least "
              f"{MIN_ROWS_FOR_REGRESSION} for a regression to be meaningful.")
        return

    X = usable[["training_load"]]
    y = usable["rmssd_ms"]

    model = LinearRegression()
    model.fit(X, y)

    load_coef = model.coef_[0]
    r_squared = model.score(X, y)

    print(f"Rows used: {len(usable)}")
    # Coefficient indicates how much HRV changes per unit of training load, R-squared indicates how much of the variation in HRV is explained by training load alone
    print(f"Training load coefficient: {load_coef:.3f} "
          f"(HRV change per +1 unit of training load)")
    print(f"R-squared: {r_squared:.3f} "
          f"(fraction of HRV variation explained by training load alone)")

    # Separate check for sleep since it started being logged later, so fewer rows have it filled in
    usable_with_sleep = df.dropna(subset=["training_load", "sleep_hours", "rmssd_ms"])
    print(f"\nRows with sleep data: {len(usable_with_sleep)}")

    if len(usable_with_sleep) < MIN_ROWS_WITH_SLEEP:
        remaining = MIN_ROWS_WITH_SLEEP - len(usable_with_sleep)
        print(f"Need {remaining} more complete rows with sleep to add it to the regression.")
        return

    X2 = usable_with_sleep[["training_load", "sleep_hours"]]
    y2 = usable_with_sleep["rmssd_ms"]

    model2 = LinearRegression()
    model2.fit(X2, y2)

    load_coef2, sleep_coef2 = model2.coef_
    r_squared2 = model2.score(X2, y2)

    print(f"\nTraining load + sleep:")
    print(f"Training load coefficient: {load_coef2:.3f}")
    print(f"Sleep coefficient: {sleep_coef2:.3f} (HRV change per +1 hour of sleep)")
    print(f"R-squared: {r_squared2:.3f}")


if __name__ == "__main__":
    run_regression()