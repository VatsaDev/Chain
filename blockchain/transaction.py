import json
from typing import List, Dict, Any
from .utils import calculate_tx_hash # Import the specific hash function

# Special ID for coinbase transaction inputs
COINBASE_TX_ID = "0" * 64
COINBASE_OUTPUT_INDEX = -1 # Special index indicate coinbase input

class TransactionInput:
    def __init__(self, transaction_id: str, output_index: int, unlock_script: Dict[str, str]):
        self.transaction_id = transaction_id
        self.output_index = output_index
        self.unlock_script = unlock_script # dict: {'signature': hex, 'public_key': hex} or coinbase data

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "output_index": self.output_index,
            "unlock_script": self.unlock_script,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransactionInput':
        return cls(data['transaction_id'], data['output_index'], data['unlock_script'])


class TransactionOutput:
    def __init__(self, amount: float, lock_script: str):
        self.amount = amount
        self.lock_script = lock_script # Recipient Address

    def to_dict(self) -> Dict[str, Any]:
        return {
            "amount": self.amount,
            "lock_script": self.lock_script,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TransactionOutput':
        return cls(data['amount'], data['lock_script'])


class Transaction:
    def __init__(self, tx_inputs: List[TransactionInput], tx_outputs: List[TransactionOutput], tx_id: str = None):
        self.inputs = tx_inputs
        self.outputs = tx_outputs
        self.transaction_id = tx_id if tx_id else self._compute_txid()

    def _compute_txid(self) -> str:
        """Computes the transaction ID (hash of its contents)."""
        # Prepare data specifically for TXID calculation (input refs, output data)
        input_refs = [{"transaction_id": inp.transaction_id, "output_index": inp.output_index} for inp in self.inputs]
        output_data = [out.to_dict() for out in self.outputs]
        return calculate_tx_hash(input_refs, output_data)

    def get_data_to_sign(self) -> str:
         """
         Creates a deterministic string representation of the transaction
         (excluding unlock scripts) used for signing inputs.
         """
         tx_data = {
            "inputs": [{"transaction_id": inp.transaction_id, "output_index": inp.output_index} for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
         }
         return json.dumps(tx_data, sort_keys=True) # Use JSON for canonical representation

    def is_coinbase(self) -> bool:
        return len(self.inputs) == 1 and self.inputs[0].transaction_id == COINBASE_TX_ID

    def to_dict(self) -> Dict[str, Any]:
        return {
            "transaction_id": self.transaction_id,
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Transaction':
        inputs = [TransactionInput.from_dict(inp) for inp in data['inputs']]
        outputs = [TransactionOutput.from_dict(out) for out in data['outputs']]
        return cls(inputs, outputs, tx_id=data['transaction_id'])
