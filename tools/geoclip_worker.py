"""GeoCLIP sıcak çalışan süreç: model bir kez yüklenir, sonra stdin'den gelen her görsel yolu için tahmin yapar.

Giriş  (satır): {"path": "/abs/foto.jpg", "top_k": 10}
Çıkış  (satır): {"top": [[lat, lon, prob], ...]}  ya da  {"error": "..."}
İlk satır olarak {"ready": true, "device": "mps"} yazılır.
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import torch  # noqa: E402
from geoclip import GeoCLIP  # noqa: E402


def main():
    model = GeoCLIP()
    device = "cpu"
    if torch.backends.mps.is_available():
        try:
            model = model.to("mps")
            device = "mps"
        except Exception:
            model = model.to("cpu")
    model.eval()
    print(json.dumps({"ready": True, "device": device}), flush=True)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            with torch.no_grad():
                gps, prob = model.predict(req["path"], top_k=int(req.get("top_k", 10)))
            top = [[float(g[0]), float(g[1]), float(p)] for g, p in zip(gps.tolist(), prob.tolist())]
            print(json.dumps({"top": top}), flush=True)
        except Exception as e:  # tek görseldeki hata süreci öldürmesin
            print(json.dumps({"error": f"{type(e).__name__}: {e}"[:300]}), flush=True)


if __name__ == "__main__":
    main()
