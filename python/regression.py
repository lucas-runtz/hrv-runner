import os
import pandas as pd
from sklearn.linear_model import LinearRegression

CSV_FILE = os.path.join(os.path.dirname(__file__), "hrv_data.csv")
MIN_ROWS_FOR_REGRESSION = 10


def run_regression():
    df = pd.read_csv(CSV_FILE)

    df["training_load"] = pd.to_numeric(df["training_load"], errors="coerce")
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
    print(f"Training load coefficient: {load_coef:.3f} "
          f"(HRV change per +1 unit of training load)")
    print(f"R-squared: {r_squared:.3f} "
          f"(fraction of HRV variation explained by training load alone)")


if __name__ == "__main__":
    run_regression()