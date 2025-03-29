import hashlib
import json
import time
from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError # Using SECP256k1 like Bitcoin
from typing import List, Any, Tuple

# --- Hashing ---
def calculate_block_hash(index: int, timestamp: float, previous_hash: str, merkle_root: str, nonce: int) -> str:
    """Calculates the SHA-256 hash for a block header."""
    header_data = f"{index}{timestamp}{previous_hash}{merkle_root}{nonce}"
    return hashlib.sha256(header_data.encode('utf-8')).hexdigest()

def calculate_tx_hash(tx_inputs_refs: List[dict], tx_outputs_data: List[dict]) -> str:
     """Calculates the transaction ID deterministically."""
     tx_data = {
        "inputs": tx_inputs_refs, # Only references matter for txid
        "outputs": tx_outputs_data,
     }
     tx_string = json.dumps(tx_data, sort_keys=True).encode('utf-8')
     return hashlib.sha256(tx_string).hexdigest()

# --- ECDSA ---
def generate_key_pair() -> Tuple[str, str]:
    """Generates an ECDSA key pair (private, public) hex encoded."""
    sk = SigningKey.generate(curve=SECP256k1)
    vk = sk.verifying_key
    return sk.to_string().hex(), vk.to_string().hex()

def sign(private_key_hex: str, message: str) -> str:
    """Signs a message using a private key."""
    sk = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
    # Hash the message before signing - common practice
    message_hash = hashlib.sha256(message.encode('utf-8')).digest()
    signature = sk.sign_digest(message_hash) # Sign the hash
    return signature.hex()

def verify(public_key_hex: str, message: str, signature_hex: str) -> bool:
    """Verifies a signature using a public key."""
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(public_key_hex), curve=SECP256k1)
        message_hash = hashlib.sha256(message.encode('utf-8')).digest()
        return vk.verify_digest(bytes.fromhex(signature_hex), message_hash) # Verify against the hash
    except BadSignatureError:
        return False
    except Exception as e:
        # print(f"Error during verification: {e}") # Debug only
        return False

# --- Address ---
def public_key_to_address(public_key_hex: str) -> str:
    """Generates a simple address by hashing the public key."""
    # TODO: Implement proper address encoding (e.g., Base58Check)
    public_key_bytes = bytes.fromhex(public_key_hex)
    return hashlib.sha256(public_key_bytes).hexdigest()

# --- Merkle Tree ---
def calculate_merkle_root(transaction_ids: List[str]) -> str:
    """Calculates the Merkle root for a list of transaction IDs."""
    if not transaction_ids:
        return hashlib.sha256(b"").hexdigest() # Hash of empty data

    # Make copies to avoid modifying original list if needed elsewhere
    current_level = list(transaction_ids)

    while len(current_level) > 1:
         # Ensure even number of leaves for pairing
         if len(current_level) % 2 != 0:
              current_level.append(current_level[-1])

         next_level = []
         for i in range(0, len(current_level), 2):
              # Concatenate hashes as hex strings before hashing again
              combined_data = (current_level[i] + current_level[i+1]).encode('utf-8')
              combined_hash = hashlib.sha256(combined_data).hexdigest()
              next_level.append(combined_hash)
         current_level = next_level # Move to the next level up the tree

    return current_level[0] # The final root hash.
