import json
from typing import Optional, TYPE_CHECKING

from . import utils # Use relative import within package
from .transaction import Transaction, TransactionInput, TransactionOutput
from .utxo import UTXOSet # Avoid circular import

class Wallet:
    # ... (rest of the Wallet class code from previous step is fine) ...
    def __init__(self):
        self.private_key_hex: str
        self.public_key_hex: str
        self.address: str
        self._generate_new_keys()

    def _generate_new_keys(self):
        self.private_key_hex, self.public_key_hex = utils.generate_key_pair()
        self.address = utils.public_key_to_address(self.public_key_hex)
        # Keep prints minimal or use logging
        # print(f"Generated Wallet with Address: {self.address}")

    def get_address(self) -> str:
        return self.address

    def create_transaction(self, recipient_address: str, amount: float, fee: float, utxo_set: 'UTXOSet') -> Optional[Transaction]:
        """Creates a signed transaction if sufficient funds are available."""
        if amount <= 0:
            # print("Error: Transaction amount must be positive.")
            return None
        if fee < 0:
            # print("Error: Fee cannot be negative.")
            return None

        available_utxos = utxo_set.find_utxos_for_address(self.address)
        if not available_utxos:
            # print(f"Error: No funds available for address {self.address}")
            return None

        inputs: list[TransactionInput] = []
        selected_utxo_keys: list[tuple[str, int]] = []
        total_input_amount = 0.0
        target_amount = amount + fee

        # Sort UTXOs (optional, e.g., by amount) for deterministic selection or efficiency
        sorted_utxos = sorted(available_utxos.items(), key=lambda item: item[1].amount)

        for utxo_key, utxo_output in sorted_utxos:
            inputs.append(TransactionInput(utxo_key[0], utxo_key[1], {}))
            selected_utxo_keys.append(utxo_key)
            total_input_amount += utxo_output.amount
            if total_input_amount >= target_amount:
                break

        if total_input_amount < target_amount:
            # print(f"Error: Insufficient funds. Need {target_amount:.8f}, have {total_input_amount:.8f}")
            return None

        outputs: list[TransactionOutput] = []
        # Use round() carefully with floats, consider using Decimal for currency
        outputs.append(TransactionOutput(round(amount, 8), recipient_address))

        change_amount = round(total_input_amount - target_amount, 8)
        if change_amount > 0.00000001: # Dust threshold
             outputs.append(TransactionOutput(change_amount, self.address))

        unsigned_tx = Transaction(inputs, outputs) # Create dummy inputs first
        data_to_sign = unsigned_tx.get_data_to_sign()

        signed_inputs: list[TransactionInput] = []
        for i, inp_ref in enumerate(unsigned_tx.inputs): # Use the dummy inputs for references
            signature_hex = utils.sign(self.private_key_hex, data_to_sign)
            unlock_script = {
                "signature": signature_hex,
                "public_key": self.public_key_hex
            }
            signed_inputs.append(TransactionInput(
                inp_ref.transaction_id,
                inp_ref.output_index,
                unlock_script
            ))

        # Final transaction with signed inputs
        final_tx = Transaction(signed_inputs, outputs)
        # print(f"Created transaction {final_tx.transaction_id[:10]}...")
        return final_tx