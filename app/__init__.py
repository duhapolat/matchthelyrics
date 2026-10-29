import os
import warnings

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
warnings.filterwarnings("ignore", message=".*forced_align has been deprecated.*")
warnings.filterwarnings("ignore", message=".*unauthenticated requests to the HF Hub.*")
