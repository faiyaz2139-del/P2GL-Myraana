$ErrorActionPreference = "Stop"
python -m pip install --requirement requirements.txt
pyinstaller --clean --noconfirm --onedir --windowed --name MyraanaConnector --add-data "printer_discovery.py;." myraana-connector.py
Write-Host "Unsigned preview build created in dist\MyraanaConnector."
