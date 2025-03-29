from typing import Dict, Tuple, Optional, List, TYPE_CHECKING
import copy

# Assuming transaction.py is accessible
from .transaction import TransactionOutput, TransactionInput, Transaction, COINBASE_TX_ID, COINBASE_OUTPUT_INDEX

UTXOKey = Tuple[str, int] # (transaction_id, output_index)

class UTXOSet:
    """Manages the set of Unspent Transaction Outputs."""

    def __init__(self):
        # Stores UTXOKey -> TransactionOutput
        self.utxos: Dict[UTXOKey, TransactionOutput] = {}

    def find_utxos_for_address(self, address: str) -> Dict[UTXOKey, TransactionOutput]:
        """Finds all UTXOs belonging to a specific address."""
        found = {}
        for utxo_key, utxo_output in self.utxos.items():
            if utxo_output.lock_script == address:
                found[utxo_key] = utxo_output
        return found

    def get_balance(self, address: str) -> float:
        """Calculates the total balance for a given address."""
        utxos = self.find_utxos_for_address(address)
        return sum(output.amount for output in utxos.values())

    def add_utxo(self, tx_id: str, index: int, output: TransactionOutput):
        """Adds a new UTXO to the set."""
        key = (tx_id, index)
        if key in self.utxos:
            print(f"Warning: UTXO {key} already exists in the set. Overwriting.")
        self.utxos[key] = output

    def remove_utxo(self, tx_id: str, index: int) -> Optional[TransactionOutput]:
        """Removes a UTXO from the set when it's spent."""
        key = (tx_id, index)
        return self.utxos.pop(key, None) # Return the removed UTXO or None if not found

    def get_utxo(self, tx_id: str, index: int) -> Optional[TransactionOutput]:
         """Gets a specific UTXO without removing it."""
         key = (tx_id, index)
         return self.utxos.get(key, None)


    def update_from_block(self, block: 'Block'): # Needs Block type hint
        """Updates the UTXO set based on the transactions in a new block."""
        # print(f"Updating UTXO set from Block {block.index}...")
        for tx in block.transactions:
            # 1. Remove spent UTXOs (inputs)
            if not tx.is_coinbase(): # Coinbase inputs are special, don't reference real UTXOs
                for i, inp in enumerate(tx.inputs):
                    removed = self.remove_utxo(inp.transaction_id, inp.output_index)
                    # if removed is None:
                        # This should have been caught during validation, but good to check
                        # print(f"  Warning: Input UTXO ({inp.transaction_id}, {inp.output_index}) for tx {tx.transaction_id} not found during update!")

            # 2. Add new UTXOs (outputs)
            for i, out in enumerate(tx.outputs):
                self.add_utxo(tx.transaction_id, i, out)
        # print(f"UTXO set size after Block {block.index}: {len(self.utxos)}")


    def rebuild(self, chain: 'Chain'): # Needs Chain type hint
        """Rebuilds the UTXO set from the genesis block."""
        print("Rebuilding UTXO set from chain...")
        self.utxos.clear()
        for block in chain.blocks:
            self.update_from_block(block)
        print(f"UTXO set rebuilt. Size: {len(self.utxos)}")

    def __len__(self) -> int:
         return len(self.utxos)

    def get_copy(self) -> 'UTXOSet':
         """Returns a deep copy of the UTXO set, useful for validation."""
         new_set = UTXOSet()
         new_set.utxos = copy.deepcopy(self.utxos) # Ensure outputs are copied too
         return new_set
