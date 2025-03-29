import time
import os
import argparse
import sys
import threading # Need threading to keep main alive

# Import necessary components
from node import Node # Assuming node.py is at the root level
from blockchain.consensus import ProofOfWork

# Configuration Defaults
DEFAULT_DIFFICULTY = 4 # Adjust for testing speed (3 or 4 is usually fast enough)
DEFAULT_BASE_PORT = 5000
CHAIN_FILE_PREFIX = "chain_data_node_" # Prefix for chain save files

def start_node(my_index: int, all_ips: list[str], base_port: int, difficulty: int):
    """Initializes and starts a single blockchain node."""

    if my_index >= len(all_ips):
        print(f"Error: Index {my_index} is out of bounds for IP list of size {len(all_ips)}")
        sys.exit(1)

    # Determine network configuration for this node
    my_ip = all_ips[my_index] # The IP address this node *should* use (informational)
    listen_host = "0.0.0.0" # Listen on all interfaces
    listen_port = base_port + my_index
    node_id = f"Node-{my_index+1}_{my_ip}:{listen_port}" # More descriptive ID
    chain_file = f"{CHAIN_FILE_PREFIX}{node_id}.json"

    # Identify peers (all other IPs/ports in the list)
    bootstrap_peers = []
    for i, ip in enumerate(all_ips):
        if i != my_index:
            peer_port = base_port + i
            bootstrap_peers.append((ip, peer_port))

    print(f"--- Initializing {node_id} ---")
    print(f"  Listen Address: {listen_host}:{listen_port}")
    print(f"  Bootstrap Peers: {bootstrap_peers}")
    print(f"  Chain File: {chain_file}")
    print(f"  Difficulty: {difficulty}")

    # Clean previous chain file for a fresh start (optional)
    if os.path.exists(chain_file):
        print(f"  Removing existing chain file: {chain_file}")
        try:
            os.remove(chain_file)
        except OSError as e:
            print(f"  Warning: Could not remove existing chain file: {e}")


    # Create consensus mechanism
    consensus = ProofOfWork(difficulty=difficulty)

    # Create and start the node
    node = Node(
        host=listen_host,
        port=listen_port,
        node_id=node_id,
        consensus=consensus,
        bootstrap_peers=bootstrap_peers,
        chain_file=chain_file # Pass the file path
    )

    try:
        node.start() # Start P2P listener and connect to peers
        time.sleep(2) # Allow time for connections
        node.start_mining() # Start the mining thread

        # Keep the main thread alive while the node runs in background threads
        print(f"\n--- {node.id} Running (Press Ctrl+C to stop) ---")
        while True:
            # Maybe add some periodic status printing or user interaction here
            time.sleep(30)
            with node.chain_lock: # Access shared data safely
                chain_len = len(node.chain.blocks)
                utxo_count = len(node.utxo_set)
            mempool_size = len(node.mempool)
            peer_count = len(node.p2p_node.peers)
            balance = node.get_balance() # get_balance should handle its own locking
            print(f"Status {node.id}: Chain={chain_len} Mem={mempool_size} UTXOs={utxo_count} Bal={balance:.4f} Peers={peer_count}")

    except KeyboardInterrupt:
        print(f"\n--- Stopping {node.id} ---")
    finally:
        node.stop() # Gracefully stop mining and networking
        # Saving chain should happen within node.stop() or be called explicitly here if needed
        # node.save_chain(chain_file) # Saving might already be in stop
        print(f"--- {node.id} Stopped ---")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a P2P Blockchain Node.")

    parser.add_argument("--index", type=int, required=True,
                        help="Index of this node (0, 1, 2, ...) corresponding to its position in the --ips list")
    parser.add_argument("--ips", nargs='+', required=True,
                        help="List of ALL node hostnames or IPs in the network (e.g., --ips 192.168.1.101 192.168.1.102 ...)")
    parser.add_argument("-d", "--difficulty", type=int, default=DEFAULT_DIFFICULTY,
                        help=f"Proof-of-Work difficulty (leading zeros) (default: {DEFAULT_DIFFICULTY})")
    parser.add_argument("-p", "--port", type=int, default=DEFAULT_BASE_PORT,
                        help=f"Base port number for nodes (actual port will be base_port + index) (default: {DEFAULT_BASE_PORT})")

    args = parser.parse_args()

    # Basic cleaning of IPs (remove potential ports added by mistake)
    cleaned_ips = []
    for ip_arg in args.ips:
         # Simple check, might need refinement for hostnames vs IPs
         if ':' in ip_arg and not any(c in ip_arg for c in 'abcdefghijklmnopqrstuvwxyz'): # Rough check if it might be IPv6 or hostname:port
             ip_part = ip_arg.split(':')[0]
             cleaned_ips.append(ip_part)
         else:
             cleaned_ips.append(ip_arg)


    start_node(
        my_index=args.index,
        all_ips=cleaned_ips,
        base_port=args.port,
        difficulty=args.difficulty
    )