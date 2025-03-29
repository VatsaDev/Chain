import time
import threading
import random
from typing import Optional, List, Dict, Any

# Blockchain components
from blockchain.wallet import Wallet
from blockchain.consensus import Consensus, ProofOfWork
from blockchain.chain import Chain
from blockchain.utxo import UTXOSet
from blockchain.mempool import Mempool
from blockchain.block import Block
from blockchain.transaction import Transaction
from blockchain import miner # Import the miner module/functions

# Networking components
from network.p2p import P2PNode
from network.message import MessageType, create_message, parse_message

class Node:
    """Represents a node in the blockchain network with P2P capabilities."""
    def __init__(self, host: str, port: int, node_id: str, consensus: Consensus, bootstrap_peers: List[tuple[str, int]] = [], chain_file: Optional[str] = None):
        self.id = node_id
        self.wallet = Wallet() # Each node has its own wallet
        self.consensus = consensus
        self.mempool = Mempool()

        # Load chain or create new one
        loaded_chain = Chain.load_from_file(chain_file, self.consensus) if chain_file else None
        self.chain = loaded_chain if loaded_chain else Chain(self.consensus)
        self.chain_lock = threading.Lock() # Protect chain and UTXO set access

        # Initialize UTXO set and rebuild it from the loaded/created chain
        self.utxo_set = UTXOSet()
        with self.chain_lock: # Ensure consistent state during rebuild
             self.utxo_set.rebuild(self.chain)

        # Initialize P2P Networking
        self.p2p_node = P2PNode(host, port, self.id, self._handle_network_message)
        self.bootstrap_peers = bootstrap_peers

        # Mining control
        self.is_mining = False
        self.mining_thread: Optional[threading.Thread] = None
        self.stop_mining_flag = threading.Event()

        print(f"Node {self.id} initialized. Address: {self.wallet.get_address()}. Chain len: {len(self.chain.blocks)}. UTXOs: {len(self.utxo_set)}")

    def start(self):
        """Starts the node's P2P network listener and connects to bootstrap peers."""
        print(f"Node {self.id}: Starting...")
        self.p2p_node.start()
        time.sleep(1) # Allow listener to start
        for host, port in self.bootstrap_peers:
             if (host, port) != (self.p2p_node.host, self.p2p_node.port):
                  self.p2p_node.connect_to_peer(host, port)
        # TODO: Add periodic peer discovery/sync


    def stop(self):
        """Stops the node's mining and network activity gracefully."""
        print(f"Node {self.id}: Stopping...")
        self.stop_mining()
        self.p2p_node.stop()
        # Save chain state on shutdown
        # Consider adding chain_file attribute to Node or passing it here
        # self.save_chain(f"chain_data_{self.id}.json")
        print(f"Node {self.id}: Stopped.")

    # --- Mining Control ---
    def _mining_loop(self):
        """The actual mining process running in a separate thread."""
        print(f"Node {self.id}: Mining thread started.")
        while not self.stop_mining_flag.is_set():
            # Acquire lock to safely access chain state (last block) and UTXO set
            with self.chain_lock:
                 # Make copies or ensure miner doesn't modify originals during PoW
                 current_utxo_copy = self.utxo_set.get_copy()
                 # Pass necessary chain info (or the chain itself if miner is careful)
                 last_block_copy = self.chain.get_last_block() # Assume Block is immutable enough

            if not last_block_copy:
                 print(f"Node {self.id}: Mining loop error - No last block found.")
                 time.sleep(5) # Wait before retrying
                 continue

            # Mine a new block (miner function should be thread-safe or operate on copies)
            # print(f"Miner {self.id} attempting to mine block {last_block_copy.index + 1}...")
            new_block = miner.mine_new_block(
                self.mempool, # Assume mempool access is thread-safe enough or locked internally if needed
                current_utxo_copy, # Miner validates against this snapshot
                self.chain, # Pass chain for last block info, miner shouldn't modify it
                self.wallet.get_address(),
                self.consensus
            )

            if self.stop_mining_flag.is_set(): break

            if new_block:
                # Block found, now try to add it to the main chain (requires lock)
                print(f"Node {self.id}: Mined potential block {new_block.index}. Hash: {new_block.hash[:10]}")
                with self.chain_lock:
                     success = self.chain.add_block(new_block, self.utxo_set) # Validate and add to main chain/UTXO

                if success:
                    print(f"Node {self.id}: Added locally mined block {new_block.index} to chain.")
                    # Broadcast the valid block
                    block_msg_str = create_message(MessageType.NEW_BLOCK, payload=new_block.to_dict())
                    self.p2p_node.broadcast(block_msg_str)
                    # Clear relevant transactions from own mempool
                    mined_tx_ids = [tx.transaction_id for tx in new_block.transactions if not tx.is_coinbase()]
                    self.mempool.remove_transactions(mined_tx_ids)
                else:
                    print(f"Node {self.id}: Locally mined block {new_block.index} rejected by own chain (fork? stale?). Discarding.")
            else:
                # No transactions or miner decided not to mine, wait
                if not self.stop_mining_flag.wait(random.uniform(2.0, 5.0)): # Wait random time
                     continue
                else:
                     break # Stop flag was set

        print(f"Node {self.id}: Mining thread finished.")

    def start_mining(self):
        if not self.is_mining:
            self.is_mining = True
            self.stop_mining_flag.clear()
            self.mining_thread = threading.Thread(target=self._mining_loop, daemon=True)
            self.mining_thread.start()
            print(f"Node {self.id}: Started mining.")

    def stop_mining(self):
        if self.is_mining and self.mining_thread:
            # print(f"Node {self.id}: Signaling mining thread to stop...")
            self.stop_mining_flag.set()
            self.mining_thread.join(timeout=2.0) # Short timeout
            if self.mining_thread.is_alive():
                 print(f"Node {self.id}: Warning - Mining thread join timed out.")
            self.is_mining = False
            self.mining_thread = None
            print(f"Node {self.id}: Mining stopped.")

    # --- Network Message Handling ---
    def _handle_network_message(self, peer_id: str, message: Dict[str, Any]):
        """Callback function passed to P2PNode to handle received messages."""
        try:
            msg_type_val = message.get("type")
            payload = message.get("payload")
            msg_type = MessageType(msg_type_val) if msg_type_val is not None else None
            # print(f"Node {self.id}: Received msg type {msg_type} from {peer_id}")

            if msg_type == MessageType.NEW_TRANSACTION:
                if payload:
                    tx = Transaction.from_dict(payload)
                    # Add to mempool (basic validation happens inside)
                    if self.mempool.add_transaction(tx):
                         # Optionally re-broadcast to other peers (simple gossip)
                         # Avoid broadcast storms - maybe only broadcast if not seen before
                         tx_msg = create_message(MessageType.NEW_TRANSACTION, payload=payload)
                         # Need peer's tuple address to exclude, P2P class could provide this in handler
                         # self.p2p_node.broadcast(tx_msg, exclude_peer=?)
                         pass

            elif msg_type == MessageType.NEW_BLOCK:
                if payload:
                    block = Block.from_dict(payload)
                    print(f"Node {self.id}: Received block {block.index} (Hash: {block.hash[:10]}...) from {peer_id}. Validating...")
                    with self.chain_lock: # Lock for validation and potential update
                         success = self.chain.add_block(block, self.utxo_set)
                    if success:
                         print(f"Node {self.id}: Accepted block {block.index} from {peer_id}.")
                         # Remove txs from mempool
                         tx_ids_in_block = [tx.transaction_id for tx in block.transactions if not tx.is_coinbase()]
                         self.mempool.remove_transactions(tx_ids_in_block)
                         # Re-broadcast valid block (simple gossip)
                         block_msg = create_message(MessageType.NEW_BLOCK, payload=payload)
                          # Need peer's tuple address to exclude
                         # self.p2p_node.broadcast(block_msg, exclude_peer=?)
                         pass
                    # else: print(f"Node {self.id}: Rejected block {block.index} from {peer_id}.")

            elif msg_type == MessageType.GET_PEERS:
                 # Send back own list of known peers
                 peer_list = self.p2p_node.get_peer_list()
                 # Convert tuples to strings for JSON is safer
                 peer_list_str = [f"{host}:{port}" for host, port in peer_list]
                 response = create_message(MessageType.SEND_PEERS, payload={"peers": peer_list_str})
                 # Need peer's tuple address to send back
                 # self.p2p_node.send_message(peer_addr, response)
                 print(f"Node {self.id}: TODO - Implement sending peer list back to {peer_id}")


            elif msg_type == MessageType.SEND_PEERS:
                 # Received a list of peers, try connecting to new ones
                 if payload and "peers" in payload:
                      received_peers = payload["peers"]
                      for peer_str in received_peers:
                           try:
                                host, port_str = peer_str.split(':')
                                port = int(port_str)
                                # Avoid connecting to self or existing connections (checked in connect_to_peer)
                                self.p2p_node.connect_to_peer(host, port)
                           except (ValueError, IndexError):
                                print(f"Node {self.id}: Received invalid peer format '{peer_str}' from {peer_id}")

            elif msg_type == MessageType.PING:
                 # Respond with Pong
                 pong_msg = create_message(MessageType.PONG)
                  # Need peer's tuple address to send back
                 # self.p2p_node.send_message(peer_addr, pong_msg)
                 # print(f"Node {self.id}: TODO - Send PONG back to {peer_id}")
                 pass # PONG response not fully implemented here

            elif msg_type == MessageType.PONG:
                 # print(f"Node {self.id}: Received PONG from {peer_id}")
                 pass # Can use this to track peer liveness

            # TODO: Implement GET_BLOCKS / SEND_BLOCKS for synchronization

        except Exception as e:
            print(f"Node {self.id}: Error handling message from {peer_id}: {e}")
            import traceback
            traceback.print_exc()


    # --- User Actions ---
    def create_and_submit_transaction(self, recipient_address: str, amount: float, fee: float) -> Optional[Transaction]:
        """Creates a transaction using the node's wallet and broadcasts it."""
        # print(f"Node {self.id}: Creating transaction: {amount} -> {recipient_address[:10]}...")
        # Acquire lock to ensure UTXO set isn't modified during creation
        with self.chain_lock:
             tx = self.wallet.create_transaction(recipient_address, amount, fee, self.utxo_set)

        if tx:
            if self.mempool.add_transaction(tx): # Add to own mempool
                 tx_msg = create_message(MessageType.NEW_TRANSACTION, payload=tx.to_dict())
                 self.p2p_node.broadcast(tx_msg) # Broadcast to network
                 print(f"Node {self.id}: Transaction {tx.transaction_id[:10]} submitted and broadcast.")
                 return tx
            else:
                 print(f"Node {self.id}: Failed to add own transaction {tx.transaction_id[:10]} to mempool.")
                 return None
        else:
            # print(f"Node {self.id}: Failed to create transaction.")
            return None

    def get_balance(self, address: Optional[str] = None) -> float:
        target_address = address if address else self.wallet.get_address()
        with self.chain_lock: # Access UTXO set safely
            balance = self.utxo_set.get_balance(target_address)
        return balance

    def save_chain(self, path: str):
         with self.chain_lock:
              self.chain.save_to_file(path)