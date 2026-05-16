#!/usr/bin/env python3
"""
Node Discovery & Configuration Tool
Helps you discover network addresses and configure peer nodes for sync.
"""

import socket
import subprocess
import os
import sys
from pathlib import Path

def get_local_ips():
    """Get all local IP addresses of this machine."""
    ips = []
    try:
        # Get hostname
        hostname = socket.gethostname()
        
        # Get IP from hostname
        try:
            local_ip = socket.gethostbyname(hostname)
            ips.append(('hostname', hostname, local_ip))
        except:
            pass
        
        # Try to get all interface IPs
        try:
            result = subprocess.run(['ip', 'addr'], capture_output=True, text=True)
            for line in result.stdout.split('\n'):
                if 'inet ' in line and 'scope' in line:
                    parts = line.strip().split()
                    if len(parts) > 1:
                        ip_addr = parts[1].split('/')[0]
                        if not ip_addr.startswith('127.'):
                            ips.append(('interface', 'eth/wlan', ip_addr))
        except:
            pass
        
        # Add localhost
        ips.append(('localhost', 'loopback', '127.0.0.1'))
        
    except Exception as e:
        print(f"Error discovering IPs: {e}")
    
    return ips

def test_node_connectivity(ip, port=5000):
    """Test if a node is reachable."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex((ip, port))
        sock.close()
        return result == 0
    except:
        return False

def load_current_config():
    """Load current sync configuration."""
    config = {}
    config_file = '.env.sync'
    
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        config[key.strip()] = value.strip()
        except:
            pass
    
    return config

def save_config(config):
    """Save configuration to .env.sync file."""
    config_file = '.env.sync'
    
    with open(config_file, 'w') as f:
        f.write("""# Distributed Sync Configuration
# 
# Specify peer nodes that this instance should sync with.
# Format: IP:PORT or HOSTNAME:PORT (comma-separated)

""")
        
        for key in ['SYNC_PEERS', 'SYNC_INTERVAL_SEC', 'SYNC_TIMEOUT_SEC', 'SYNC_LOCAL_URL', 'NODE_ID', 'SYNC_STATE_FILE']:
            if key in config:
                f.write(f"{key}={config[key]}\n")
            else:
                if key == 'SYNC_PEERS':
                    f.write(f"{key}=\n")
                elif key == 'SYNC_INTERVAL_SEC':
                    f.write(f"{key}=5\n")
                elif key == 'SYNC_TIMEOUT_SEC':
                    f.write(f"{key}=10\n")
                elif key == 'SYNC_LOCAL_URL':
                    f.write(f"{key}=http://127.0.0.1:5000\n")
                elif key == 'NODE_ID':
                    f.write(f"{key}=\n")
                elif key == 'SYNC_STATE_FILE':
                    f.write(f"{key}=.sync_state.json\n")

def main():
    print("\n" + "=" * 70)
    print("DISTRIBUTED SYNC - NODE DISCOVERY & CONFIGURATION")
    print("=" * 70 + "\n")
    
    # Show local IPs
    print("📡 YOUR MACHINE'S NETWORK ADDRESSES:")
    print("─" * 70)
    
    ips = get_local_ips()
    for source, label, ip in ips:
        status = "✓ Reachable" if test_node_connectivity(ip) else "✗ Not reachable"
        print(f"  {ip:20s} ({label:15s}) {status}")
    
    print("\n" + "─" * 70)
    print("Choose one of the above IPs for SYNC_LOCAL_URL (how peers reach you)")
    print("Default: http://127.0.0.1:5000 (localhost only)\n")
    
    # Show current config
    print("⚙️  CURRENT SYNC CONFIGURATION:")
    print("─" * 70)
    
    config = load_current_config()
    peers = config.get('SYNC_PEERS', '').strip()
    local_url = config.get('SYNC_LOCAL_URL', 'http://127.0.0.1:5000').strip()
    node_id = config.get('NODE_ID', '').strip()
    sync_interval = config.get('SYNC_INTERVAL_SEC', '5').strip()
    
    print(f"  Local URL (SYNC_LOCAL_URL):  {local_url}")
    print(f"  Node ID (NODE_ID):           {node_id or '(auto-detected from hostname)'}")
    print(f"  Sync Interval:               {sync_interval} seconds")
    if peers:
        print(f"  Peer Nodes (SYNC_PEERS):")
        for peer in peers.split(','):
            peer = peer.strip()
            if peer:
                ip_part = peer.split(':')[0]
                reachable = "✓" if test_node_connectivity(ip_part) else "✗"
                print(f"    {reachable} {peer}")
    else:
        print(f"  Peer Nodes (SYNC_PEERS):     (none configured)")
    
    print("\n" + "─" * 70)
    print("CONFIGURATION OPTIONS:")
    print("─" * 70)
    print("""
1. CONFIGURE MANUALLY
   Edit: .env.sync
   Set SYNC_PEERS=ip1:5000,ip2:5000,ip3:5000

2. CONFIGURE VIA SCRIPT (Interactive)
   python node_discovery.py --configure

3. TEST CONNECTIVITY TO PEER
   python node_discovery.py --test-peer 10.49.210.216:5000

4. START SYNC WITH CURRENT CONFIG
   python sync.py
   (reads SYNC_PEERS from .env.sync)

5. ENVIRONMENT VARIABLE OVERRIDE
   SYNC_PEERS="10.49.210.216:5000,10.49.210.76:5000" python sync.py
""")
    
    print("=" * 70 + "\n")
    
    # Interactive mode
    if len(sys.argv) > 1:
        if sys.argv[1] == '--configure':
            print("📝 INTERACTIVE CONFIGURATION")
            print("─" * 70 + "\n")
            
            local_url_input = input(f"Enter SYNC_LOCAL_URL [{local_url}]: ").strip()
            if local_url_input:
                config['SYNC_LOCAL_URL'] = local_url_input
            
            node_id_input = input(f"Enter NODE_ID [{node_id or 'auto'}]: ").strip()
            if node_id_input:
                config['NODE_ID'] = node_id_input
            
            peers_input = input("Enter SYNC_PEERS (comma-separated, e.g., 10.49.210.216:5000,10.49.210.76:5000): ").strip()
            if peers_input:
                config['SYNC_PEERS'] = peers_input
                
                # Test connectivity
                print("\n🔍 Testing connectivity to peer nodes...")
                for peer in peers_input.split(','):
                    peer = peer.strip()
                    if peer:
                        ip_part = peer.split(':')[0]
                        port = peer.split(':')[1] if ':' in peer else '5000'
                        try:
                            port = int(port)
                            if test_node_connectivity(ip_part, port):
                                print(f"  ✓ {peer} - REACHABLE")
                            else:
                                print(f"  ✗ {peer} - NOT REACHABLE (may be offline)")
                        except:
                            print(f"  ✗ {peer} - INVALID FORMAT")
            
            save_config(config)
            print("\n✓ Configuration saved to .env.sync\n")
            
        elif sys.argv[1] == '--test-peer' and len(sys.argv) > 2:
            peer = sys.argv[2]
            ip_part = peer.split(':')[0]
            port = int(peer.split(':')[1]) if ':' in peer else 5000
            
            print(f"Testing {peer}...")
            if test_node_connectivity(ip_part, port):
                print(f"✓ {peer} is REACHABLE")
            else:
                print(f"✗ {peer} is NOT REACHABLE")

if __name__ == '__main__':
    main()
