import json
import time
import copy
from typing import List, Set, Optional, Tuple, TYPE_CHECKING

from .block import Block
from .consensus import Consensus, ProofOfWork
from .transaction import Transaction, TransactionInput, TransactionOutput, COINBASE_TX_ID
from .utils import verify, public_key_to_address, calculate_merkle_root # Added merkle root import

if TYPE_CHECKING:
    from utxo import UTXOSet, UTXOKey

BLOCK_REWARD = 50.0 # Define block reward constant here or pass it in

class Chain:
    """Represents the blockchain: a sequence of blocks."""
    def __init__(self, consensus: Consensus):
        self.blocks: List[Block] = []
        self.consensus: Consensus = consensus
        # Genesis block creation should not depend on external state
        self._create_genesis_block()

    def _create_genesis_block(self):
        """Creates the first block in the chain."""
        if not self.blocks:
            # print("Creating Genesis Block...")
            # Genesis transactions are often special, maybe pre-funding accounts or just a marker
            # Here, a simple coinbase-like marker transaction
            genesis_coinbase_input = TransactionInput(COINBASE_TX_ID, -1, {"data": "Genesis Block Marker"})
            # You could pre-fund an address here if desired
            genesis_output = TransactionOutput(0.0, "genesis_reward_address_placeholder")
            genesis_tx = Transaction(tx_inputs=[genesis_coinbase_input], tx_outputs=[genesis_output])

            timestamp = time.time() # Or a fixed known timestamp like Bitcoin's
            merkle_root = calculate_merkle_root([genesis_tx.transaction_id])
            previous_hash = "0" * 64 # Use full length hash

            # Mine the genesis block (nonce might be 0 or require finding)
            nonce = self.consensus.prove(0, timestamp, previous_hash, merkle_root)

            genesis_block = Block(
                index=0,
                transactions=[genesis_tx],
                timestamp=timestamp,
                previous_hash=previous_hash,
                merkle_root=merkle_root,
                nonce=nonce,
            )
            self.blocks.append(genesis_block)
            # print(f"Genesis block created. Hash: {genesis_block.hash[:10]}...")

    def get_last_block(self) -> Optional[Block]:
        return self.blocks[-1] if self.blocks else None

    def add_block(self, block: Block, utxo_set: 'UTXOSet') -> bool:
        """
        Validates and adds a block, updating the provided UTXO set.
        Returns True if added, False otherwise.
        """
        last_block = self.get_last_block()

        # --- Basic Header and Link Validation ---
        if last_block:
             if block.previous_hash != last_block.hash:
                  # print(f"Block {block.index} validation failed: Previous hash mismatch.")
                  return False
             if block.index != last_block.index + 1:
                  # print(f"Block {block.index} validation failed: Index out of sequence.")
                  return False
        elif block.index != 0: # If no last block, only index 0 is allowed
             print("Block validation failed: Received non-genesis block for empty chain.")
             return False
        elif block.previous_hash != "0" * 64: # Genesis must point to zero hash
             print("Block validation failed: Genesis block previous_hash is not zero.")
             return False

        if not self.consensus.validate_block_header(block):
            # print(f"Block {block.index} validation failed: Invalid header (PoW/Hash).")
            return False

        # --- Transaction Validation ---
        if not block.transactions:
             print(f"Block {block.index} validation failed: Block has no transactions (must have coinbase).")
             return False

        # Check Merkle Root
        recalculated_merkle_root = calculate_merkle_root([tx.transaction_id for tx in block.transactions])
        if block.merkle_root != recalculated_merkle_root:
             # print(f"Block {block.index} validation failed: Merkle root mismatch.")
             return False

        # Validate individual transactions against a temporary UTXO set state
        temp_utxo_set = utxo_set.get_copy()
        total_fees = 0.0
        coinbase_tx_count = 0

        for i, tx in enumerate(block.transactions):
            if tx.is_coinbase():
                coinbase_tx_count += 1
                if i != 0:
                     print(f"Block {block.index} validation failed: Coinbase tx not first.")
                     return False
                # TODO: Add coinbase transaction validation (e.g., reward amount)
                continue # Skip regular validation for coinbase

            # Regular transaction validation against temporary UTXO set
            is_valid, tx_fee = self.validate_transaction(tx, temp_utxo_set, check_not_in_set=False) # Expect inputs to exist initially
            if not is_valid:
                 print(f"Block {block.index} validation failed: Invalid transaction {tx.transaction_id[:10]}...")
                 return False

            total_fees += tx_fee
            # Update temp UTXO set for next tx validation within the same block
            for inp in tx.inputs:
                 temp_utxo_set.remove_utxo(inp.transaction_id, inp.output_index)
            for out_idx, out in enumerate(tx.outputs):
                 temp_utxo_set.add_utxo(tx.transaction_id, out_idx, out)

        # Final structural checks
        if coinbase_tx_count != 1:
             print(f"Block {block.index} validation failed: Found {coinbase_tx_count} coinbase transactions.")
             return False

        # TODO: Validate coinbase amount against BLOCK_REWARD + total_fees

        # --- If all valid, commit changes ---
        utxo_set.update_from_block(block) # Update the *real* UTXO set
        self.blocks.append(block)
        # print(f"Block {block.index} added to chain. UTXOs: {len(utxo_set)}")
        return True

    def validate_transaction(self, transaction: Transaction, utxo_set: 'UTXOSet', check_not_in_set: bool = True) -> Tuple[bool, float]:
        """
        Validates a single non-coinbase transaction against the provided UTXO set.
        Returns: Tuple (is_valid: bool, fee: float)
        """
        if transaction.is_coinbase(): return False, 0.0 # Should not be called for coinbase

        total_input_value = 0.0
        spent_utxo_keys: List[UTXOKey] = [] # Track spent UTXOs within this tx to prevent double spending *same* UTXO

        try:
            data_to_sign = transaction.get_data_to_sign()
        except Exception as e:
             print(f"Error creating data to sign for tx {transaction.transaction_id[:10]}: {e}")
             return False, 0.0

        # Validate Inputs
        if not transaction.inputs: return False, 0.0 # Must have inputs
        for i, inp in enumerate(transaction.inputs):
            utxo_key = (inp.transaction_id, inp.output_index)

            # Prevent spending the same UTXO twice in one transaction
            if utxo_key in spent_utxo_keys:
                 print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Input {i} references UTXO {utxo_key} already spent in this transaction.")
                 return False, 0.0

            spent_utxo = utxo_set.get_utxo(inp.transaction_id, inp.output_index)
            if spent_utxo is None:
                # print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Input {i} references non-existent/spent UTXO {utxo_key}.")
                return False, 0.0 # Input UTXO must exist

            # Verify Signature and Ownership
            if not isinstance(inp.unlock_script, dict) or \
               'signature' not in inp.unlock_script or \
               'public_key' not in inp.unlock_script:
                 print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Input {i} unlock_script invalid format.")
                 return False, 0.0

            pub_key_hex = inp.unlock_script['public_key']
            signature_hex = inp.unlock_script['signature']
            derived_address = public_key_to_address(pub_key_hex)

            if spent_utxo.lock_script != derived_address:
                 print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Input {i} pubkey does not match UTXO address {spent_utxo.lock_script[:10]} != {derived_address[:10]}.")
                 return False, 0.0

            if not verify(pub_key_hex, data_to_sign, signature_hex):
                print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Input {i} invalid signature.")
                return False, 0.0

            total_input_value += spent_utxo.amount
            spent_utxo_keys.append(utxo_key) # Mark as spent for this transaction

        # Validate Outputs
        if not transaction.outputs: return False, 0.0 # Must have outputs
        total_output_value = 0.0
        for i, out in enumerate(transaction.outputs):
            if out.amount < 0:
                print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Output {i} has negative amount {out.amount}.")
                return False, 0.0
            total_output_value += out.amount

        # Check Value Conservation (allow for potential float inaccuracies)
        fee = round(total_input_value - total_output_value, 8)
        if fee < 0:
             print(f"Validation Error (Tx: {transaction.transaction_id[:10]}): Output value ({total_output_value:.8f}) > Input value ({total_input_value:.8f}).")
             return False, 0.0 # Cannot spend more than you have

        # All checks passed
        return True, fee

    # --- Persistence ---
    def save_to_file(self, path: str):
        try:
            data = {"chain": [block.to_dict() for block in self.blocks]}
            with open(path, 'w') as f:
                json.dump(data, f, indent=2)
            # print(f"Chain saved to {path}")
        except IOError as e:
            print(f"Error saving chain to {path}: {e}")

    @classmethod
    def load_from_file(cls, path: str, consensus: Consensus) -> Optional['Chain']:
        try:
            with open(path, 'r') as f:
                data = json.load(f)

            chain = cls(consensus) # Create instance with empty blocks
            chain.blocks = [Block.from_dict(block_data) for block_data in data.get('chain', [])]

            if not chain.blocks:
                 print(f"Warning: Loaded chain file {path} was empty or invalid. Starting fresh.")
                 chain._create_genesis_block() # Ensure genesis if file was bad
            elif chain.blocks[0].index != 0 or chain.blocks[0].previous_hash != "0"*64:
                 print(f"Warning: Loaded chain file {path} has invalid genesis. Starting fresh.")
                 chain.blocks = [] # Clear invalid blocks
                 chain._create_genesis_block() # Create proper genesis

            # print(f"Chain loaded from {path}. Length: {len(chain.blocks)}")
            # UTXO set needs separate rebuilding after load
            return chain
        except FileNotFoundError:
            return None
        except (IOError, json.JSONDecodeError, TypeError, KeyError) as e:
            print(f"Error loading or parsing chain from {path}: {e}. Starting fresh.")
            # Fallback to creating a new chain if loading fails badly
            chain = cls(consensus)
            return chain
