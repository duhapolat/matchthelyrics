@echo off
rem Ilk kurulum: Python 3.13 sanal ortami + NVIDIA CUDA'li PyTorch + diger paketler.
cd /d "%~dp0"
where ffmpeg >nul 2>nul || (
  echo ffmpeg bulunamadi. Kur:  winget install Gyan.FFmpeg
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.13 -m venv .venv || exit /b 1
".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install torch==2.8.0 torchaudio==2.8.0 --index-url https://download.pytorch.org/whl/cu128 || exit /b 1
".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
".venv\Scripts\python.exe" -c "import torch; print('CUDA:', torch.cuda.is_available())"
echo Kurulum tamam. start.bat ile baslat.
pause
