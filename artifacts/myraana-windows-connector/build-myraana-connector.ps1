$ErrorActionPreference = "Stop"
python -m pip install --requirement requirements.txt
pyinstaller --clean --noconfirm --onedir --windowed --name MyraanaConnector --add-data "printer_discovery.py;." --add-data "fiery_hold.py;." --hidden-import pystray._win32 --hidden-import pystray._util.win32 --hidden-import PIL.Image --hidden-import PIL.ImageDraw --hidden-import six myraana-connector.py
Write-Host "Unsigned connector build created in dist\MyraanaConnector."
