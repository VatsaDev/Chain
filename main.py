import time
import os
import argparse
import sys
import threading
import logging

from typing import Optional

# Import Flask components
from flask import Flask, request, jsonify

# Import necessary blockchain components
from node import Node # Assuming node.py is at the root level
from blockchain.consensus import ProofOfWork
# Wallet class needed for type hinting if used directly, but likely not needed here
# from blockchain.wallet import Wallet

# --- Configuration Defaults ---
DEFAULT_DIFFICULTY = 4
DEFAULT_BASE_P2P_PORT = 5000 # Base for P2P
DEFAULT_BASE_API_PORT = 5050 # Base for API
CHAIN_FILE_PREFIX = "chain_data_node_"

# --- Global variable to hold the running node instance ---
current_node: Optional[Node] = None # Use Optional typing

# --- Flask App Setup ---
flask_app = Flask(__name__)

# --- Logging Setup ---
# Configure root logger
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout) # Ensure logs go to console
    ]
)
# Optionally silence Werkzeug (Flask's server) logs if too verbose
# logging.getLogger('werkzeug').setLevel(logging.ERROR)


# --- API Endpoints ---

@flask_app.route('/status', methods=['GET'])
def get_status():
    """Returns the current status of the node."""
    if not current_node: return jsonify({"error": "Node not initialized"}), 503
    try: return jsonify(current_node.get_status()), 200
    except Exception as e: logging.error(f"API /status Error: {e}", exc_info=True); return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/balance/<address>', methods=['GET'])
def get_address_balance(address: str):
    """Returns the balance for a specific address."""
    if not current_node: return jsonify({"error": "Node not initialized"}), 503
    try:
        # Basic validation - adjust if addresses have prefixes/checksums later
        if not address or not isinstance(address, str) or len(address) != 64:
             return jsonify({"error": "Invalid address format (expected 64 hex chars)"}), 400
        balance = current_node.get_balance(address)
        return jsonify({"address": address, "balance": balance}), 200
    except Exception as e: logging.error(f"API /balance/{address} Error: {e}", exc_info=True); return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/all-balances', methods=['GET'])
def get_all_node_balances():
    """Returns all balances known by this node's UTXO set."""
    if not current_node: return jsonify({"error": "Node not initialized"}), 503
    try: return jsonify(current_node.get_all_balances()), 200
    except Exception as e: logging.error(f"API /all-balances Error: {e}", exc_info=True); return jsonify({"error": "Internal server error"}), 500

# --- Wallet and Transaction API ---

@flask_app.route('/create-wallet', methods=['POST'])
def api_create_wallet():
    """Generates a new wallet managed by the node and returns its address."""
    if not current_node: return jsonify({"error": "Node not initialized"}), 503
    try:
        new_wallet = current_node.create_managed_wallet()
        logging.info(f"API: Created new managed wallet via API: {new_wallet.get_address()}")
        # IMPORTANT: DO NOT return the private key in a real application API!
        return jsonify({
            "message": "Wallet created successfully (Managed by Node)",
            "address": new_wallet.get_address(),
        }), 201
    except Exception as e:
        logging.error(f"API /create-wallet Error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error during wallet creation"}), 500

@flask_app.route('/wallets', methods=['GET'])
def api_list_managed_wallets():
    """Lists the addresses of all wallets managed by this node."""
    if not current_node: return jsonify({"error": "Node not initialized"}), 503
    try:
        addresses = current_node.get_all_managed_wallet_addresses()
        return jsonify({"managed_wallets": addresses}), 200
    except Exception as e: logging.error(f"API /wallets Error: {e}", exc_info=True); return jsonify({"error": "Internal server error"}), 500

@flask_app.route('/create-transaction', methods=['POST'])
def api_create_transaction():
    """
    Creates and submits a transaction using a wallet MANAGED BY THIS NODE as the sender.
    Expects JSON: {"sender": "<sender_address>", "recipient": "<recipient_address>", "amount": <float>, "fee": <float>}
    """
    if not current_node: return jsonify({"error": "Node not initialized"}), 503

    data = request.get_json(silent=True)
    if not data: return jsonify({"error": "Invalid request: Could not parse JSON data"}), 400
    logging.debug(f"API /create-transaction received data: {data}") # Debug log

    # --- Input Validation ---
    sender_addr = data.get("sender")
    recipient_addr = data.get("recipient")
    amount_str = data.get("amount")
    fee_str = data.get("fee")

    if not sender_addr or not isinstance(sender_addr, str) or len(sender_addr) != 64: return jsonify({"error": "Invalid or missing 'sender' address"}), 400
    if not recipient_addr or not isinstance(recipient_addr, str) or len(recipient_addr) != 64: return jsonify({"error": "Invalid or missing 'recipient' address"}), 400
    try: amount = float(amount_str); assert amount > 0
    except: return jsonify({"error": "Invalid or missing 'amount' (must be positive number)"}), 400
    try: fee = float(fee_str); assert fee >= 0
    except: return jsonify({"error": "Invalid or missing 'fee' (must be non-negative number)"}), 400
    # --- End Validation ---

    logging.info(f"API: Received tx request: {amount} from managed {sender_addr[:10]} -> {recipient_addr[:10]} (fee: {fee})")

    try:
        # Use the node's method which finds the managed wallet and uses its key
        tx = current_node.create_transaction_from_managed_wallet(
            sender_addr, recipient_addr, amount, fee
        )

        if not tx:
            # Reason should be logged by the node method
            logging.warning(f"API: Transaction creation failed for sender {sender_addr[:10]}.")
            # Check if wallet exists first for better error message
            if not current_node.get_managed_wallet(sender_addr):
                 return jsonify({"error": f"Sender address '{sender_addr}' not managed by this node."}), 400
            else:
                 # Likely insufficient funds if wallet exists
                 return jsonify({"error": "Transaction creation failed (likely insufficient funds)"}), 400

        # If transaction created, submit it to mempool and broadcast
        submitted = current_node.submit_and_broadcast_transaction(tx)

        if submitted:
            return jsonify({"message": "Transaction created and broadcast successfully", "transaction_id": tx.transaction_id}), 202
        else:
            # Mempool rejection reason should be logged
            return jsonify({"error": "Transaction created but rejected by mempool"}), 400

    except Exception as e:
        logging.error(f"API /create-transaction Error: {e}", exc_info=True)
        return jsonify({"error": "Internal server error during transaction processing"}), 500


# --- Flask Runner & Main Node Start ---
def run_flask_app(host: str, port: int):
    """Runs the Flask app."""
    try:
        logging.info(f"Starting Flask API server on http://{host}:{port}")
        # Set threaded=True if needed, but Flask dev server is single-threaded by default
        flask_app.run(host=host, port=port, debug=False, use_reloader=False) # Important: use_reloader=False
    except OSError as e: logging.error(f"!!! Flask API Error on port {port}: {e}")
    except Exception as e: logging.error(f"!!! Flask API Error: {e}")

def start_node_process(my_index: int, all_ips: list[str], base_p2p_port: int, base_api_port: int, difficulty: int):
    global current_node
    if my_index >= len(all_ips):
        logging.error(f"Index {my_index} out of bounds for IP list {all_ips}")
        sys.exit(1)

    # Determine network configuration
    my_ip = all_ips[my_index]
    listen_host = "0.0.0.0" # Listen on all interfaces
    p2p_port = base_p2p_port + my_index
    api_port = base_api_port + my_index
    node_id = f"Node-{my_index+1}_{my_ip}_P2P:{p2p_port}_API:{api_port}"
    chain_file_base = CHAIN_FILE_PREFIX # Pass base prefix to Node

    bootstrap_peers = [(ip, base_p2p_port + i) for i, ip in enumerate(all_ips) if i != my_index]

    logging.info(f"--- Initializing {node_id} ---")
    logging.info(f"  P2P Listen: {listen_host}:{p2p_port}, API Listen: {listen_host}:{api_port}")
    logging.info(f"  Bootstrap Peers: {bootstrap_peers}")
    logging.info(f"  Chain File Base: {chain_file_base}{node_id}.json")
    logging.info(f"  Difficulty: {difficulty}")

    chain_file_path = f"{chain_file_base}{node_id}.json"
    if os.path.exists(chain_file_path):
        logging.info(f"  Removing existing chain file: {chain_file_path}")
        try: os.remove(chain_file_path)
        except OSError as e: logging.warning(f"Could not remove chain file: {e}")

    # Create node instance
    consensus = ProofOfWork(difficulty=difficulty)
    node = Node(
        host=listen_host, port=p2p_port, node_id=node_id, consensus=consensus,
        bootstrap_peers=bootstrap_peers, chain_file_base=chain_file_base # Pass base prefix
    )
    current_node = node

    # Start Flask API thread
    api_thread = threading.Thread(target=run_flask_app, args=(listen_host, api_port), daemon=True)
    api_thread.start()

    # Start Node P2P/Mining
    try:
        node.start() # Start P2P listener & bootstrap connections
        time.sleep(3) # Allow time for connections/API server to bind
        node.start_mining() # Start the mining thread

        logging.info(f"\n--- {node.id} Running (P2P on {p2p_port}, API on {api_port}) ---")
        logging.info("--- Press Ctrl+C to stop ---")
        while True: time.sleep(60) # Keep main thread alive

    except KeyboardInterrupt: logging.info(f"\n--- Stopping {node.id} ---")
    finally:
        if current_node: current_node.stop() # Calls save_chain inside
        logging.info(f"--- {node.id} Stopped ---")

# --- Argparse and Main Execution ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run a P2P Blockchain Node with API.")
    parser.add_argument("--index", type=int, required=True, help="Index (0, 1, 2...)")
    parser.add_argument("--ips", nargs='+', required=True, help="List of ALL node IPs/hostnames")
    parser.add_argument("-d", "--difficulty", type=int, default=DEFAULT_DIFFICULTY, help=f"PoW difficulty (default: {DEFAULT_DIFFICULTY})")
    parser.add_argument("--p2p-port", type=int, default=DEFAULT_BASE_P2P_PORT, help=f"Base P2P port (default: {DEFAULT_BASE_P2P_PORT})")
    parser.add_argument("--api-port", type=int, default=DEFAULT_BASE_API_PORT, help=f"Base API port (default: {DEFAULT_BASE_API_PORT})")
    args = parser.parse_args()

    cleaned_ips = [ip.split(':')[0] for ip in args.ips]
    if args.index >= len(cleaned_ips):
        print(f"Error: Index {args.index} out of bounds for IP list {cleaned_ips}")
        sys.exit(1)

    start_node_process(
        my_index=args.index, all_ips=cleaned_ips, base_p2p_port=args.p2p_port,
        base_api_port=args.api_port, difficulty=args.difficulty
    )
