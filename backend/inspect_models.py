from pathlib import Path
import sys
import joblib

try:
    import sklearn._loss._loss as sklearn_loss
    sys.modules["_loss"] = sklearn_loss
    print("_loss compatibility patch: OK")
except Exception as e:
    print("_loss compatibility patch failed:", e)

MODEL_DIR = Path(__file__).resolve().parents[1] / "models"

print("MODEL DIRECTORY:", MODEL_DIR)
print("=" * 80)

model_files = sorted(MODEL_DIR.glob("*.joblib"))

for path in model_files:
    print(f"\nMODEL: {path.name}")

    try:
        obj = joblib.load(path)

        print("TOP LEVEL TYPE:", type(obj))

        if isinstance(obj, dict):
            print("DICT KEYS:", list(obj.keys()))

            for key, value in obj.items():
                print(f"  [{key}]")
                print("    TYPE:", type(value))

                if hasattr(value, "feature_names_in_"):
                    print(
                        "    FEATURES:",
                        list(value.feature_names_in_)
                    )

                if hasattr(value, "n_features_in_"):
                    print(
                        "    N_FEATURES:",
                        value.n_features_in_
                    )

                if isinstance(value, (str, int, float, bool, list, tuple)):
                    text = str(value)

                    if len(text) < 500:
                        print("    VALUE:", text)

        else:
            if hasattr(obj, "feature_names_in_"):
                print(
                    "FEATURES:",
                    list(obj.feature_names_in_)
                )

            if hasattr(obj, "n_features_in_"):
                print(
                    "N_FEATURES:",
                    obj.n_features_in_
                )

    except Exception as e:
        print("LOAD ERROR:", repr(e))

    print("-" * 80)