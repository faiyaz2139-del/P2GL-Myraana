#!/usr/bin/env python3
"""Print2Go file connector. Writes authorized PDF files. NEVER triggers printing.
Requires Python 3.10+, HTTPS site URL, server CONNECTOR_SECRET shared locally.
Site privacy must allow this machine's authenticated access; owner-private Sites
can block requests before this API. See setup guide. No passwords are logged.
"""
import os, json, time, uuid, pathlib, urllib.request, hashlib, tempfile
url = os.environ.get('PRINT2GO_URL', '').rstrip('/')
secret = os.environ.get('CONNECTOR_SECRET', '')
destination = pathlib.Path(os.environ.get('PRINT2GO_FOLDER', '')).expanduser()
if not url.startswith('https://') or not secret or not os.environ.get('PRINT2GO_FOLDER'):
    raise SystemExit('Set PRINT2GO_URL (HTTPS), CONNECTOR_SECRET and PRINT2GO_FOLDER.')
destination.mkdir(parents=True, exist_ok=True)
headers = {'Authorization': 'Bearer ' + secret, 'Content-Type': 'application/json'}
ack, seen = [], set()
def request(path, data=None):
    req = urllib.request.Request(url + '/api/connector/' + path, data=json.dumps(data).encode() if data is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as response:
        if 'application/pdf' in response.headers.get('Content-Type', ''):
            return response.read()
        return json.load(response)
while True:
    try:
        with tempfile.TemporaryFile(dir=destination) as f:
            f.write(b'write-test'); f.flush()
        payload = {'timestamp': int(time.time()*1000), 'nonce': str(uuid.uuid4()), 'destination': str(destination.resolve()), 'writable': True, 'capabilities': ['pdf-hot-folder'], 'handoffs': ack}
        result = request('', payload); ack = []
        for job in result['jobs']:
            identity = (job['id'], job['generation'], job['file']['sha'])
            if identity in seen: continue
            content = request('file/' + job['id'])
            if hashlib.sha256(content).hexdigest() != job['file']['sha']:
                raise ValueError('Production PDF checksum mismatch.')
            final = destination / (job['id'] + '-g' + str(job['generation']) + '.pdf')
            temporary = final.with_suffix('.part')
            temporary.write_bytes(content)
            if hashlib.sha256(temporary.read_bytes()).hexdigest() != job['file']['sha']:
                raise ValueError('Destination checksum mismatch.')
            os.replace(temporary, final)
            ack.append({'jobId': job['id'], 'sha': job['file']['sha'], 'generation': job['generation'], 'fileId': job['file']['id']})
            seen.add(identity)
        print('Shop heartbeat saved. Authorized files staged; no printing performed.')
    except Exception:
        print('Connection or destination unavailable. Check setup and retry. No printing performed.')
    time.sleep(15)
