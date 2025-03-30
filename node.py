import os
import time
import threading
import random
import logging # Use logging
from typing import Optional, List, Dict, Any

# Blockchain components
# Use relative imports assuming node.py is at the project root
# and blockchain components are in a 'blockchain' subdirectory.
from blockchain.wallet import Wallet
from blockchain.consensus import Consensus # ProofOfWork is usually passed in
from blockchain.chain import Chain
from blockchain.utxo import UTXOSet
from blockchain.mempool import Mempool
from blockchain.block import Block
from blockchain.transaction import Transaction
from blockchain import miner
from blockchain import utils

# Networking components
# Assuming network components are in a 'network' subdirectory
from network.p2p import P2PNode
from network.message import MessageType, create_message, parse_message

# Constants
CHAIN_FILE_PREFIX = "chain_data_node_" # Define prefix here or pass in

class Node:
    """Represents a node in the blockchain network with P2P and API capabilities."""
    def __init__(self, host: str, port: int, node_id: str, consensus: Consensus, bootstrap_peers: List[tuple[str, int]] = [], chain_file_base: str = CHAIN_FILE_PREFIX):
        self.id = node_id
        self.consensus = consensus
        self.mempool = Mempool()
        self.chain_file = f"{chain_file_base}{self.id}.json" # Construct full path

        # Load/Create Chain
        loaded_chain = Chain.load_from_file(self.chain_file, self.consensus) if os.path.exists(self.chain_file) else None
        self.chain = loaded_chain if loaded_chain else Chain(self.consensus)
        self.chain_lock = threading.Lock() # Protect chain and UTXO set access

        # Initialize UTXO Set
        self.utxo_set = UTXOSet()
        with self.chain_lock: # Ensure consistent state during rebuild
             self.utxo_set.rebuild(self.chain)

        # --- Wallet Management ---
        # Stores wallets generated/managed by this node instance
        # Key: address (str), Value: Wallet object
        # TODO: Persist/Load managed wallets for real use
        self.managed_wallets: Dict[str, Wallet] = {}
        self.node_wallet = self._create_or_load_node_wallet() # Node's own mining/operational wallet
        # -----------------------------

        # Initialize P2P Networking
        self.p2p_node = P2PNode(host, port, self.id, self._handle_network_message)
        self.bootstrap_peers = bootstrap_peers

        # Mining control
        self.is_mining = False
        self.mining_thread: Optional[threading.Thread] = None
        self.stop_mining_flag = threading.Event()

        logging.info(f"Node {self.id} initialized. Node Wallet Addr: {self.node_wallet.get_address()}. Chain: {len(self.chain.blocks)}. UTXOs: {len(self.utxo_set)}")


    # --- Wallet Management Methods ---
    def _create_or_load_node_wallet(self) -> Wallet:
        # Basic: Creates a new primary wallet every time.
        # For persistence: Check if a primary key file exists, load it, otherwise generate&save.
        logging.info(f"Node {self.id}: Generating primary node wallet...")
        wallet = Wallet()
        self.managed_wallets[wallet.get_address()] = wallet # Store it
        logging.info(f"Node {self.id}: Primary Wallet Address: {wallet.get_address()}")
        # logging.info(f"Node {self.id}: Primary Wallet Private Key: {wallet.private_key_hex} <-- DO NOT LOG IN PRODUCTION") # Security risk
        return wallet

    def create_managed_wallet(self) -> Wallet:
        """Creates a new wallet, stores it IN MEMORY, and returns it."""
        wallet = Wallet()
        # Use lock if multiple threads might call this (e.g., multiple API requests)
        # For simple Flask, GIL might suffice, but lock is safer.
        with self.chain_lock: # Reuse chain_lock for simplicity or add dedicated wallet_lock
             self.managed_wallets[wallet.get_address()] = wallet
        logging.info(f"Node {self.id}: Created managed wallet: {wallet.get_address()}")
        return wallet

    def get_managed_wallet(self, address: str) -> Optional[Wallet]:
        """Retrieves a stored managed wallet by address."""
        with self.chain_lock: # Protect read access if create uses lock
             return self.managed_wallets.get(address)

    def get_all_managed_wallet_addresses(self) -> List[str]:
        """Returns addresses of all wallets managed by this node."""
        with self.chain_lock:
             # Return list of keys including the primary node wallet
             return list(self.managed_wallets.keys())

    # --- Mining Methods ---
    def _mining_loop(self):
        logging.info(f"Node {self.id}: Mining thread started (Reward Addr: {self.node_wallet.get_address()[:10]}...).")
        while not self.stop_mining_flag.is_set():
            new_block = None
            # Acquire lock only when accessing shared chain/utxo state
            with self.chain_lock:
                 current_utxo_copy = self.utxo_set.get_copy()
                 last_block_copy = self.chain.get_last_block() # Get latest block info

            if not last_block_copy:
                 logging.error(f"Node {self.id}: Mining loop error - No last block found.")
                 time.sleep(5); continue # Wait before retrying

            # Mine outside the lock - takes time
            new_block = miner.mine_new_block(
                self.mempool, # Assume mempool is reasonably thread-safe for reads
                current_utxo_copy, # Miner validates against this snapshot
                self.chain, # Only needs last_block info, doesn't modify
                self.node_wallet.get_address(),
                self.consensus
            )

            if self.stop_mining_flag.is_set(): break

            if new_block:
                # Attempt to add block (requires lock)
                block_added = False
                with self.chain_lock:
                     block_added = self.chain.add_block(new_block, self.utxo_set) # Validate and add

                if block_added:
                    logging.info(f"Node {self.id}: Added mined block {new_block.index} (Tx:{len(new_block.transactions)}, Hash:{new_block.hash[:10]})")
                    block_msg = create_message(MessageType.NEW_BLOCK, payload=new_block.to_dict())
                    self.p2p_node.broadcast(block_msg)
                    mined_tx_ids = [tx.transaction_id for tx in new_block.transactions if not tx.is_coinbase()]
                    self.mempool.remove_transactions(mined_tx_ids)
                else:
                    logging.warning(f"Node {self.id}: Mined block {new_block.index} rejected by own chain. Discarding.")
            else:
                # No block mined (e.g., no txs in mempool), wait before next attempt
                if not self.stop_mining_flag.wait(random.uniform(2.0, 5.0)): continue
                else: break # Stop flag was set during wait

        logging.info(f"Node {self.id}: Mining thread finished.")

    def start_mining(self):
        if self.is_mining: logging.info(f"Node {self.id}: Already mining."); return
        self.is_mining = True
        self.stop_mining_flag.clear()
        self.mining_thread = threading.Thread(target=self._mining_loop, daemon=True)
        self.mining_thread.start()
        logging.info(f"Node {self.id}: Started mining.")

    def stop_mining(self):
        if not self.is_mining or not self.mining_thread: logging.info(f"Node {self.id}: Not mining."); return
        logging.info(f"Node {self.id}: Signaling mining thread to stop...")
        self.stop_mining_flag.set()
        self.mining_thread.join(timeout=2.0)
        if self.mining_thread.is_alive(): logging.warning(f"Node {self.id}: Mining thread join timed out.")
        self.is_mining = False; self.mining_thread = None
        logging.info(f"Node {self.id}: Mining stopped.")

    # --- Network Message Handling ---
    def _handle_network_message(self, peer_addr_tuple: tuple[str, int], message: Dict[str, Any]):
        peer_id_str = f"{peer_addr_tuple[0]}:{peer_addr_tuple[1]}"
        try:
            msg_type_val = message.get("type")
            payload = message.get("payload")
            msg_type = MessageType(msg_type_val) if msg_type_val is not None else None
            # logging.debug(f"Node {self.id}: Rcvd msg type {msg_type} from {peer_id_str}")

            # --- Handle NEW_TRANSACTION ---
            if msg_type == MessageType.NEW_TRANSACTION and payload:
                tx = Transaction.from_dict(payload)
                if self.mempool.add_transaction(tx):
                     # Basic gossip
                     tx_msg = create_message(MessageType.NEW_TRANSACTION, payload=payload)
                     self.p2p_node.broadcast(tx_msg, exclude_peer=peer_addr_tuple)

            # --- Handle NEW_BLOCK ---
            elif msg_type == MessageType.NEW_BLOCK and payload:
                block = Block.from_dict(payload)
                # logging.info(f"Node {self.id}: Rcvd block {block.index} from {peer_id_str}. Validating...")
                block_accepted = False
                with self.chain_lock:
                     block_accepted = self.chain.add_block(block, self.utxo_set)
                if block_accepted:
                     logging.info(f"Node {self.id}: Accepted block {block.index} from {peer_id_str}. (Hash:{block.hash[:10]})")
                     tx_ids = [tx.transaction_id for tx in block.transactions if not tx.is_coinbase()]
                     self.mempool.remove_transactions(tx_ids)
                     # Basic gossip
                     block_msg = create_message(MessageType.NEW_BLOCK, payload=payload)
                     self.p2p_node.broadcast(block_msg, exclude_peer=peer_addr_tuple)

            # --- Handle GET_PEERS ---
            elif msg_type == MessageType.GET_PEERS:
                 peer_list = self.p2p_node.get_peer_list()
                 peer_list_str = [f"{host}:{port}" for host, port in peer_list]
                 response = create_message(MessageType.SEND_PEERS, payload={"peers": peer_list_str})
                 self.p2p_node.send_message(peer_addr_tuple, response)

            # --- Handle SEND_PEERS ---
            elif msg_type == MessageType.SEND_PEERS and payload and "peers" in payload:
                 for peer_str in payload["peers"]:
                      try: host, port_str = peer_str.split(':'); port = int(port_str); self.p2p_node.connect_to_peer(host, port)
                      except: pass # Ignore errors

            # --- Handle PING/PONG ---
            elif msg_type == MessageType.PING:
                 self.p2p_node.send_message(peer_addr_tuple, create_message(MessageType.PONG))
            elif msg_type == MessageType.PONG: pass # Liveness check response

            # --- Handle Balance/UTXO Queries ---
            elif msg_type == MessageType.GET_UTXOS and payload and "address" in payload:
                 req_address = payload["address"]
                 with self.chain_lock: utxos = self.utxo_set.find_utxos_for_address(req_address)
                 utxos_payload = {f"{txid}:{idx}": out.to_dict() for (txid, idx), out in utxos.items()}
                 resp = create_message(MessageType.SEND_UTXOS, payload={"address": req_address, "utxos": utxos_payload})
                 self.p2p_node.send_message(peer_addr_tuple, resp)

            elif msg_type == MessageType.GET_ALL_BALANCES:
                  with self.chain_lock: balances = self.get_all_balances() # Use internal method
                  resp = create_message(MessageType.SEND_ALL_BALANCES, payload={"balances": balances})
                  self.p2p_node.send_message(peer_addr_tuple, resp)

        except Exception as e:
            logging.error(f"Node {self.id}: Error handling msg from {peer_id_str}: {e}")
            import traceback; traceback.print_exc()

    # --- Transaction Creation via API (Using Managed Wallet) ---
    def create_transaction_from_managed_wallet(
        self, sender_address: str, recipient_address: str, amount: float, fee: float
    ) -> Optional[Transaction]:
        """Creates a transaction using a wallet MANAGED BY THIS NODE."""
        sender_wallet = self.get_managed_wallet(sender_address) # Read access to dict
        if not sender_wallet:
            logging.error(f"Node {self.id}: Sender wallet {sender_address} not managed by this node.")
            return None

        logging.info(f"Node {self.id}: Creating tx {amount} from managed {sender_address[:10]} -> {recipient_address[:10]}...")
        tx = None
        # Lock needed for reading UTXO set state during tx creation
        with self.chain_lock:
             # create_transaction uses the private key stored in the Wallet object
             tx = sender_wallet.create_transaction(recipient_address, amount, fee, self.utxo_set)
        return tx

    # --- Transaction Submission/Broadcast ---
    def submit_and_broadcast_transaction(self, transaction: Transaction) -> bool:
         """Adds a valid transaction to the mempool and broadcasts it."""
         if self.mempool.add_transaction(transaction): # Basic validation inside
              tx_msg = create_message(MessageType.NEW_TRANSACTION, payload=transaction.to_dict())
              self.p2p_node.broadcast(tx_msg)
              logging.info(f"Node {self.id}: Tx {transaction.transaction_id[:10]} added to mempool and broadcast.")
              return True
         else:
              logging.warning(f"Node {self.id}: Tx {transaction.transaction_id[:10]} rejected by mempool.")
              return False

    # --- Query Methods ---
    def get_balance(self, address: Optional[str] = None) -> float:
        target_address = address if address else self.node_wallet.get_address()
        with self.chain_lock: balance = self.utxo_set.get_balance(target_address)
        return balance

    def get_all_balances(self) -> Dict[str, float]:
        balances = {}
        with self.chain_lock:
            known_addresses = set(out.lock_script for out in self.utxo_set.utxos.values())
            for addr in known_addresses:
                balances[addr] = self.utxo_set.get_balance(addr) # get_balance re-iterates but is safe within lock
        return balances

    def get_status(self) -> Dict[str, Any]:
         with self.chain_lock:
              chain_len = len(self.chain.blocks)
              utxo_count = len(self.utxo_set)
         mempool_size = len(self.mempool)
         peer_count = len(self.p2p_node.peers) # Read access likely ok without lock if P2PNode manages its own
         node_balance = self.get_balance(self.node_wallet.get_address()) # Use own method

         return {
              "node_id": self.id,
              "node_address": self.node_wallet.get_address(),
              "is_mining": self.is_mining,
              "chain_length": chain_len,
              "mempool_size": mempool_size,
              "utxo_count": utxo_count,
              "peer_count": peer_count,
              "node_balance": node_balance,
              "managed_wallet_count": len(self.managed_wallets) # How many wallets this node created/stores
         }

    # --- Lifecycle Methods ---
    def start(self):
        logging.info(f"Node {self.id}: Starting P2P network...")
        self.p2p_node.start()
        time.sleep(1)
        logging.info(f"Node {self.id}: Connecting to bootstrap peers: {self.bootstrap_peers}")
        for host, port in self.bootstrap_peers:
             self.p2p_node.connect_to_peer(host, port)

    def stop(self):
        logging.info(f"Node {self.id}: Stopping...")
        self.stop_mining()
        self.p2p_node.stop()
        self.save_chain() # Save chain state on stop
        logging.info(f"Node {self.id}: Stopped.")

    def save_chain(self):
         logging.info(f"Node {self.id}: Saving chain to {self.chain_file}...")
         with self.chain_lock:
              self.chain.save_to_file(self.chain_file)
         logging.info(f"Node {self.id}: Chain saved.")
