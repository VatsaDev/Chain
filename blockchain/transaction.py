# blockchain/transaction.py

import hashlib
import json
from typing import List, Dict, Any, TYPE_CHECKING # Added TYPE_CHECKING

# Import utils if needed elsewhere, but TXID calculation is self-contained now
# from .utils import ...

# Added TYPE_CHECKING guard for TransactionInput import if needed elsewhere
# (Not strictly necessary here as it's defined in the same file, but good practice)
if TYPE_CHECKING:
     from .transaction import TransactionInput # Type hint for class defined later

# --- Constants ---
# Special ID for coinbase transaction inputs (representing no previous output)
COINBASE_TX_ID = "0" * 64
# Special index to indicate a coinbase input (standard practice)
COINBASE_OUTPUT_INDEX = -1

# --- Transaction Input Class ---
class TransactionInput:
    """Represents a reference to an output from a previous transaction."""
    def __init__(self, transaction_id: str, output_index: int, unlock_script: Dict[str, str]):
        """
        Args:
            transaction_id: The ID (hash) of the transaction containing the UTXO being spent.
                            Use COINBASE_TX_ID for coinbase inputs.
            output_index: The index (0-based) of the specific output in the referenced transaction.
                            Use COINBASE_OUTPUT_INDEX for coinbase inputs.
            unlock_script: Data required to unlock the referenced output.
                           For standard P2PKH (Pay-to-Public-Key-Hash) style, this typically
                           contains {'signature': hex_signature, 'public_key': hex_public_key}.
                           For coinbase transactions, this can contain arbitrary data (miner tag, block height).
        """
        self.transaction_id = transaction_id
        self.output_index = output_index
        self.unlock_script = unlock_script # e.g., {'signature': '...', 'public_key': '...'} or {'data': '...'}

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the input to a dictionary."""
        return {
            "transaction_id": self.transaction_id,
            "output_index": self.output_index,
            "unlock_script": self.unlock_script, # Assumes content is JSON serializable
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransactionInput':
        """Deserializes an input from a dictionary."""
        # Ensure unlock_script is loaded correctly (it should be a dict)
        unlock_script = data.get('unlock_script', {})
        if not isinstance(unlock_script, dict):
             # Handle cases where it might be None or wrong type if loaded from old data
             print(f"Warning: Invalid unlock_script format in from_dict for input referencing {data.get('transaction_id')}, using empty dict.")
             unlock_script = {}
        return cls(
            data['transaction_id'],
            data['output_index'],
            unlock_script
        )

# --- Transaction Output Class ---
class TransactionOutput:
    """Represents an amount of coins locked to a specific condition (address)."""
    def __init__(self, amount: float, lock_script: str):
        """
        Args:
            amount: The value of coins in this output (e.g., Satoshis or fractional coins).
            lock_script: The condition required to spend this output.
                         For simple P2PKH style, this is the recipient's address.
        """
        # Add basic validation
        if amount < 0:
             raise ValueError("Transaction output amount cannot be negative")
        self.amount = amount
        self.lock_script = lock_script # Recipient Address (in simple model)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the output to a dictionary."""
        return {
            "amount": self.amount,
            "lock_script": self.lock_script,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransactionOutput':
        """Deserializes an output from a dictionary."""
        return cls(
            data['amount'],
            data['lock_script']
        )

# --- Transaction Class ---
class Transaction:
    """Represents a transfer of value, consisting of inputs and outputs."""
    def __init__(self, tx_inputs: List[TransactionInput], tx_outputs: List[TransactionOutput], tx_id: str = None):
        """
        Initializes a transaction.

        Args:
            tx_inputs: A list of TransactionInput objects.
            tx_outputs: A list of TransactionOutput objects.
            tx_id: Optional pre-calculated transaction ID (used when loading from data).
                   If None, the ID will be calculated based on inputs and outputs.
        """
        if not tx_inputs:
             raise ValueError("Transaction must have at least one input (even for coinbase)")
        if not tx_outputs:
             raise ValueError("Transaction must have at least one output")

        self.inputs = tx_inputs
        self.outputs = tx_outputs
        # Calculate or use provided tx_id *after* inputs/outputs are assigned
        self.transaction_id = tx_id if tx_id else self._calculate_transaction_id(self.inputs, self.outputs)

    @staticmethod
    def _is_coinbase_data(tx_inputs: List[TransactionInput]) -> bool:
        """
        Static method to check if the provided input data represents a coinbase transaction.
        A coinbase transaction has exactly one input, referencing the special null transaction ID and index.
        """
        return (
            len(tx_inputs) == 1 and
            tx_inputs[0].transaction_id == COINBASE_TX_ID and
            tx_inputs[0].output_index == COINBASE_OUTPUT_INDEX
        )

    @staticmethod
    def _calculate_transaction_id(tx_inputs: List[TransactionInput], tx_outputs: List[TransactionOutput]) -> str:
        """
        Calculates the transaction ID (hash) based on inputs and outputs.
        Uses different data for coinbase vs regular transactions to ensure uniqueness for coinbase.
        This is a static method to avoid dependency on 'self' during initialization.
        """
        if Transaction._is_coinbase_data(tx_inputs):
            # Coinbase TXID calculation: Include full input data (with unique unlock script)
            # This ensures each coinbase tx has a unique ID based on block-specific data within its script
            tx_data = {
                "inputs": [inp.to_dict() for inp in tx_inputs], # Includes unlock_script
                "outputs": [out.to_dict() for out in tx_outputs],
            }
        else:
            # Regular TXID calculation: Hash only input *references* and outputs.
            # Signatures (in unlock_script) are NOT part of the TXID calculation for regular transactions.
            tx_data = {
                "inputs": [{"transaction_id": inp.transaction_id, "output_index": inp.output_index} for inp in tx_inputs],
                "outputs": [out.to_dict() for out in tx_outputs],
            }

        # Use compact, sorted JSON for a deterministic byte representation before hashing
        tx_string = json.dumps(tx_data, sort_keys=True, separators=(',', ':')).encode('utf-8')
        return hashlib.sha256(tx_string).hexdigest()

    # --- Instance Methods ---

    def is_coinbase(self) -> bool:
        """Checks if this transaction instance is a coinbase transaction."""
        # This method can now safely use self.inputs after initialization is complete
        return self._is_coinbase_data(self.inputs)

    def get_data_to_sign(self) -> str:
         """
         Creates a deterministic string representation of the transaction's core components
         (input references and all outputs) used for signing the inputs.
         Excludes unlock scripts (signatures).
         """
         tx_data = {
            "inputs": [{"transaction_id": inp.transaction_id, "output_index": inp.output_index} for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
         }
         # Use compact, sorted JSON string as the message to be signed
         return json.dumps(tx_data, sort_keys=True, separators=(',',':'))

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the entire transaction to a dictionary."""
        # Ensure transaction_id exists (should always be true after __init__)
        if not hasattr(self, 'transaction_id') or not self.transaction_id:
             print("Warning: Recalculating tx_id in to_dict. This shouldn't normally happen.")
             self.transaction_id = self._calculate_transaction_id(self.inputs, self.outputs)

        return {
            "transaction_id": self.transaction_id,
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        """Deserializes a transaction from a dictionary."""
        try:
            inputs = [TransactionInput.from_dict(inp) for inp in data.get('inputs', [])]
            outputs = [TransactionOutput.from_dict(out) for out in data.get('outputs', [])]

            # Use the transaction_id directly from the dictionary data.
            # DO NOT recalculate it here, as that would change the ID if inputs/outputs were represented differently.
            tx_id_from_data = data.get('transaction_id')
            if not tx_id_from_data:
                 raise ValueError("Transaction data must include 'transaction_id'")

            # Sanity check: Recalculate based on loaded data and compare (optional, for debugging)
            # calculated_id = cls._calculate_transaction_id(inputs, outputs)
            # if calculated_id != tx_id_from_data:
            #      print(f"Warning: TXID mismatch in from_dict for {tx_id_from_data[:10]}. Loaded={tx_id_from_data}, Calculated={calculated_id}")

            return cls(inputs, outputs, tx_id=tx_id_from_data)
        except KeyError as e:
             raise ValueError(f"Missing required field in transaction data: {e}")
        except Exception as e:
             raise ValueError(f"Error deserializing transaction: {e}")
