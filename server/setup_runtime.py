"""One-time owner OAuth setup, run locally on the VM through an SSH loopback tunnel."""
import argparse
import os
from google_auth_oauthlib.flow import InstalledAppFlow
from runtime_api import runtime_store
from vault_drive import GoogleDriveAdapter, VaultDrive


def main():
    parser = argparse.ArgumentParser(description='Connect the VM to the owner Google Drive account')
    parser.add_argument('--client', required=True, help='Path to an OAuth Desktop client JSON (never commit)')
    args = parser.parse_args()
    os.umask(0o077)
    flow = InstalledAppFlow.from_client_secrets_file(args.client, scopes=['https://www.googleapis.com/auth/drive'])
    # SSH: -L 8765:127.0.0.1:8765. Open the printed Google URL in your own browser.
    credentials = flow.run_local_server(host='127.0.0.1', port=8765, open_browser=False,
        access_type='offline', prompt='consent', timeout_seconds=300,
        success_message='Google Drive connected. You can close this page.')
    if not credentials.refresh_token:
        raise RuntimeError('Google did not issue offline access; repeat setup with consent.')
    vault = VaultDrive(GoogleDriveAdapter.from_adc(credentials))  # Verifies owner before saving.
    vault.close()
    import json
    runtime_store().put_secret('google-oauth', json.loads(credentials.to_json()))
    print('Owner Drive access encrypted and saved. No credentials were printed.')


if __name__ == '__main__':
    main()
