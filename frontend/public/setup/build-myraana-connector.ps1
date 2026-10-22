$ErrorActionPreference = "Stop"
python -m pip install --requirement requirements.txt
pyinstaller --clean --noconfirm --onedir --windowed --name MyraanaConnector --add-data "printer_discovery.py;." --add-data "fiery_hold.py;." myraana-connector.py
Write-Host "Unsigned connector build created in dist\MyraanaConnector."
