import os
import sys
import tempfile

# Testler kendi geçici veri klasörünü kullanır: gerçek ayarlar / vakalar asla değişmez.
os.environ["OSINT_DATA_DIR"] = tempfile.mkdtemp(prefix="osint-test-")
os.environ.pop("PANEL_TOKEN", None)
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "panel"))
