import time
import json
from typing import List, Optional, TYPE_CHECKING

from .utils import calculate_merkle_root, public_key_to_address, verify # Relative imports
from .transaction import Transaction, TransactionInput, TransactionOutput, COINBASE_TX_ID, COINBASE_OUTPUT_INDEX
from .block import Block
from .consensus import Consensus

if TYPE_CHECKING:
    from .mempool import Mempool
    from .utxo import UTXOSet
    from .chain import Chain

BLOCK_REWARD = 50.0 # Example reward

def mine_new_block(mempool: 'Mempool', utxo_set: 'UTXOSet', chain: 'Chain', miner_address: str, consensus: Consensus) -> Optional[Block]:
    """
    Mines a new block including transactions from the mempool and a coinbase reward.
    """
    last_block = chain.get_last_block()
    if not last_block:
        print("Miner Error: Cannot mine without a previous block.")
        return None

    previous_hash = last_block.hash
    next_index = last_block.index + 1

    valid_txs_for_block: List[Transaction] = []
    total_fees = 0.0
    temp_utxo_set = utxo_set.get_copy() # Validate against a temporary copy
    pending_txs = mempool.get_pending_transactions()

    # print(f"Miner considering {len(pending_txs)} txs for block {next_index}.")

    for tx in pending_txs:
        # Miner performs validation before including
        validation_result, tx_fee = chain.validate_transaction(tx, temp_utxo_set, check_not_in_set=False) # Expect inputs exist in temp set
        if validation_result:
            valid_txs_for_block.append(tx)
            total_fees += tx_fee
            # Update the temporary UTXO set for subsequent validation *within this block*
            for inp in tx.inputs:
                 temp_utxo_set.remove_utxo(inp.transaction_id, inp.output_index)
            for i, out in enumerate(tx.outputs):
                 temp_utxo_set.add_utxo(tx.transaction_id, i, out)
            # print(f"  Miner included tx {tx.transaction_id[:10]} fee {tx_fee:.8f}")
        # else:
            # print(f"  Miner rejected tx {tx.transaction_id[:10]} during pre-validation.")

    # Create Coinbase
    coinbase_output = TransactionOutput(amount=round(BLOCK_REWARD + total_fees, 8), lock_script=miner_address)
    coinbase_input = TransactionInput(
        transaction_id=COINBASE_TX_ID,
        output_index=COINBASE_OUTPUT_INDEX,
        unlock_script={"data": f"Block {next_index} reward"}
    )
    coinbase_tx = Transaction(tx_inputs=[coinbase_input], tx_outputs=[coinbase_output])

    all_txs_for_block = [coinbase_tx] + valid_txs_for_block
    tx_ids = [tx.transaction_id for tx in all_txs_for_block]
    merkle_root = calculate_merkle_root(tx_ids)

    timestamp = time.time()
    # print(f"Miner starting PoW for block {next_index}...")
    nonce = consensus.prove(next_index, timestamp, previous_hash, merkle_root)
    # print(f"Miner found nonce: {nonce}")

    new_block = Block(
        index=next_index,
        transactions=all_txs_for_block,
        timestamp=timestamp,
        previous_hash=previous_hash,
        merkle_root=merkle_root,
        nonce=nonce
    )
    # Hash calculated in __post_init__

    return new_block
