import json
import struct
import hashlib

import ecdsa
from ecdsa import SigningKey, NIST192p

def calc_hash(index, timestamp, data, prev_hash, proof):

    hasher = hashlib.sha256()

    hasher.update(str(index).encode())
    hasher.update(b"|")
    hasher.update(str(timestamp).encode())
    hasher.update(b"|")
    hasher.update(data.encode())
    hasher.update(b"|")
    hasher.update(previous_hash.encode())
    hasher.update(b"|")

    proof_bytes = json.dumps(proof, separators=(",", ":")).encode()
    hasher.update(proof_bytes)

    return hasher.hexdigest()

def gen_key_pair():

    sk = SigningKey.generate() # uses NIST192p
    s = sk.to_string() # priv key

    vk = sk.verifying_key

    return s, vk

def sign(priv_key, msg): 

    sk = SigningKey.from_string(priv_key, curve=NIST192p)

    msg_b = msg.encode()

    sig = sk.sign(msg_b)

    return sig

def verify(pub_key, msg, sig):

    msg_b = msg.encode()

    return pub_key.verify(sig, msg_b) 

def addr(pub_key): # currently just a hash of the pub_key, improve later

    hasher = hashlib.sha256()
    hasher.update(pub_key.to_string())

    return hasher.hexdigest()

"""
# quick tests

index = 1
timestamp = 1716239023
data = "42"
previous_hash = "a01ed479f2e155835c110992408776c2ad5ec2e30f1f2737860a3c4c21dc0b60"
proof = {"nonce": 42}  # can be any serializable object, test here

hashed_value = calc_hash(index, timestamp, data, previous_hash, proof)
print("hash: ", hashed_value)

priv_key, pub_key = gen_key_pair()
print("priv_key: ", priv_key)
print("pub_key: ", pub_key)

msg = "Fair"
sig = sign(priv_key, msg)

print("sig: ", sig)

print(verify(pub_key, msg, sig))

print(addr(pub_key))
"""
