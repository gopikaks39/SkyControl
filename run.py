"""Start SkyControl on http://127.0.0.1:5000 (frontend and API on the same origin).

Reads an optional .env file. On first launch, if no accounts exist and no
account passwords are provided in the environment, it asks you to create the
controller and supervisor passwords.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
env = ROOT / '.env'
if env.exists():
    for line in env.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

if __name__ == '__main__':
    from backend.database import connect, init_db
    init_db()
    with connect() as db:
        ready = db.execute('SELECT COUNT(*) FROM users').fetchone()[0] >= 1
    has_env = os.getenv('SKYCONTROL_SUPERVISOR_PASSWORD') and (
        os.getenv('SKYCONTROL_CONTROLLER_PASSWORD') or os.getenv('SKYCONTROL_DEMO_PASSWORD'))
    if not ready and not has_env:
        from setup_accounts import main
        main()
    import uvicorn
    host = os.getenv('SKYCONTROL_HOST', '0.0.0.0')
    port = int(os.getenv('SKYCONTROL_PORT', '5000'))
    print(f'SkyControl: http://127.0.0.1:{port}')
    uvicorn.run('backend.app:app', host=host, port=port)
