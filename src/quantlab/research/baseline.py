import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

def regression_baselines(y: pd.Series, train_end: int):
    y = pd.to_numeric(y, errors="coerce").dropna().reset_index(drop=True)
    if train_end <= 0 or train_end >= len(y):
        raise ValueError("train_end musi dzielić serię na niepusty train i test.")
    train, test = y.iloc[:train_end], y.iloc[train_end:]
    preds = {
        "zero_return": np.zeros(len(test)),
        "historical_mean": np.full(len(test), train.mean()),
    }
    return {
        name: {
            "mae": float(mean_absolute_error(test, pred)),
            "rmse": float(np.sqrt(mean_squared_error(test, pred))),
            "test_observations": int(len(test)),
        }
        for name, pred in preds.items()
    }
