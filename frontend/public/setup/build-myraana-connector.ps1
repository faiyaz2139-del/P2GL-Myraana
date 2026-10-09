$ErrorActionPreference = "Stop"
python -m pip install --requirement requirements.txt
pyinstaller --clean --noconfirm --onedir --name MyraanaConnector myraana-connector.py
Write-Host "Unsigned preview build created in dist\MyraanaConnector."