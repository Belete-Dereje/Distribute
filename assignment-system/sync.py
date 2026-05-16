import argparse
import json
import logging
import os
import time
from datetime import datetime, timezone

import requests


def load_env_file(filename='.env.sync'):
    """Load environment variables from .env.sync file."""
    config = {}
    if os.path.exists(filename):
        try:
            with open(filename, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        except Exception as e:
            logging.warning(f'Failed to read {filename}: {e}')
    return config


# Load configuration: environment variables override .env.sync file
_file_config = load_env_file()
LOCAL = os.environ.get('SYNC_LOCAL_URL') or _file_config.get('SYNC_LOCAL_URL', 'http://127.0.0.1:5000')
SYNC_INTERVAL = int(os.environ.get('SYNC_INTERVAL_SEC') or _file_config.get('SYNC_INTERVAL_SEC', '5'))
STATE_FILE = os.environ.get('SYNC_STATE_FILE') or _file_config.get('SYNC_STATE_FILE', '.sync_state.json')
REQUEST_TIMEOUT = int(os.environ.get('SYNC_TIMEOUT_SEC') or _file_config.get('SYNC_TIMEOUT_SEC', '10'))


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def normalize_peer(value):
    peer = value.strip()
    if not peer:
        return ''
    if peer.startswith('http://') or peer.startswith('https://'):
        return peer.rstrip('/')
    return f"http://{peer.rstrip('/')}"


def load_state(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception as exc:
        logging.warning('Failed to read sync state %s: %s', path, exc)
        return {}


def save_state(path, state):
    temp_path = f"{path}.tmp"
    with open(temp_path, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, sort_keys=True)
    os.replace(temp_path, path)


def count_records(sync_payload):
    data = sync_payload.get('data', {})
    if not isinstance(data, dict):
        return 0
    return sum(len(rows) for rows in data.values() if isinstance(rows, list))


def sync_once(peer_url, last_since):
    params = {'since': last_since} if last_since else None
    remote_resp = requests.get(f"{peer_url}/sync/data", params=params, timeout=REQUEST_TIMEOUT)
    remote_resp.raise_for_status()

    remote_payload = remote_resp.json()
    if not isinstance(remote_payload, dict):
        raise ValueError('Peer response is not a JSON object')

    if 'data' not in remote_payload:
        # Backward compatibility for old peers returning raw table map.
        remote_payload = {
            'data': remote_payload,
            'node_id': peer_url,
            'server_time': utc_now_iso(),
        }

    merge_payload = {
        'data': remote_payload.get('data', {}),
        'node_id': remote_payload.get('node_id'),
        'server_time': remote_payload.get('server_time'),
    }

    local_resp = requests.post(f"{LOCAL}/sync/update", json=merge_payload, timeout=REQUEST_TIMEOUT)
    local_resp.raise_for_status()

    applied_at = remote_payload.get('server_time') or utc_now_iso()
    return {
        'peer_node_id': remote_payload.get('node_id') or peer_url,
        'applied_since': applied_at,
        'records_sent': count_records(remote_payload),
        'merge_response': local_resp.json() if local_resp.content else {},
    }


def parse_args():
    parser = argparse.ArgumentParser(description='Incremental peer sync worker')
    parser.add_argument('peers', nargs='*', help='Peer hosts, e.g. 10.49.210.216:5000')
    return parser.parse_args()


def get_peers(args):
    peers = list(args.peers)
    # Environment variable override
    env_peers = os.environ.get('SYNC_PEERS', '').strip()
    if env_peers:
        peers.extend([p.strip() for p in env_peers.split(',') if p.strip()])
    # Config file fallback
    file_peers = _file_config.get('SYNC_PEERS', '').strip()
    if file_peers and not env_peers and not args.peers:
        peers.extend([p.strip() for p in file_peers.split(',') if p.strip()])
    normalized = [normalize_peer(p) for p in peers if normalize_peer(p)]
    deduped = []
    seen = set()
    for p in normalized:
        if p not in seen:
            deduped.append(p)
            seen.add(p)
    return deduped


def main():
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s %(levelname)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    args = parse_args()
    peers = get_peers(args)
    
    # Show configuration source
    if os.environ.get('SYNC_PEERS'):
        logging.info('Using SYNC_PEERS from environment variable')
    elif _file_config.get('SYNC_PEERS'):
        logging.info('Using SYNC_PEERS from .env.sync configuration file')
    elif args.peers:
        logging.info('Using SYNC_PEERS from command-line arguments')
    else:
        # Preserve old defaults when no peers are passed
        peers = [normalize_peer('10.49.210.216:5000'), normalize_peer('10.49.210.76:5000')]
        logging.info('Using default peer list (none configured)')

    sync_state = load_state(STATE_FILE)
    logging.info('Syncing with peers=%s every %ss', peers, SYNC_INTERVAL)
    logging.info('Local node URL: %s', LOCAL)

    while True:
        for peer in peers:
            peer_state = sync_state.get(peer, {})
            since = peer_state.get('last_successful_since')

            try:
                result = sync_once(peer, since)
                peer_state['last_successful_since'] = result['applied_since']
                peer_state['last_successful_at'] = utc_now_iso()
                peer_state['last_error'] = None
                sync_state[peer] = peer_state
                save_state(STATE_FILE, sync_state)

                merge_summary = result.get('merge_response', {}).get('summary', {})
                inserted = merge_summary.get('inserted', 0)
                updated = merge_summary.get('updated', 0)
                skipped = merge_summary.get('skipped', 0)
                logging.info(
                    'Peer %s ok: sent=%s inserted=%s updated=%s skipped=%s since=%s',
                    peer,
                    result.get('records_sent', 0),
                    inserted,
                    updated,
                    skipped,
                    peer_state['last_successful_since'],
                )
            except requests.RequestException as exc:
                peer_state['last_error'] = f'network_error: {exc}'
                peer_state['last_error_at'] = utc_now_iso()
                sync_state[peer] = peer_state
                save_state(STATE_FILE, sync_state)
                logging.error('Peer %s sync failed (network): %s', peer, exc)
            except Exception as exc:
                peer_state['last_error'] = f'unexpected_error: {exc}'
                peer_state['last_error_at'] = utc_now_iso()
                sync_state[peer] = peer_state
                save_state(STATE_FILE, sync_state)
                logging.exception('Peer %s sync failed (unexpected)', peer)

        time.sleep(SYNC_INTERVAL)


if __name__ == '__main__':
    main()
