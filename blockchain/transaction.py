import json
import hashlib

class TransactionInput:

    def __init__(self, transaction_id, output_index, unlock_script):
        self.transaction_id = transaction_id  # UTXO ref
        self.output_index = output_index
        self.unlock_script = unlock_script

    def to_dict(self):
        
        return {
            "transaction_id": self.transaction_id,
            "output_index": self.output_index,
            "unlock_script": self.unlock_script,
        }

class TransactionOutput:

    def __init__(self, amount, lock_script):
        self.amount = amount  
        self.lock_script = lock_script

    def to_dict(self):
        
        return {
            "amount": self.amount,
            "lock_script": self.lock_script,
        }

class Transaction:

    def __init__(self, inputs, outputs):
        self.inputs = inputs
        self.outputs = outputs
        self.transaction_id = self.compute_txid()  # unique hash of TX

    def compute_txid(self):

        tx_data = json.dumps({
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
        }, sort_keys=True).encode()

        return hashlib.sha256(tx_data).hexdigest()

    def to_dict(self):
        
        return {
            "transaction_id": self.transaction_id,
            "inputs": [inp.to_dict() for inp in self.inputs],
            "outputs": [out.to_dict() for out in self.outputs],
        }
