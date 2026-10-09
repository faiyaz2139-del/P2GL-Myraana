$ErrorActionPreference = "Stop"
python -m pip install --upgrade pyinstaller pywin32
pyinstaller --clean --noconfirm --onedir --name MyraanaConnector myraana-connector.py
Write-Host "Unsigned preview build created in dist\MyraanaConnector."