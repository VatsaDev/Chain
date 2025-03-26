import utils

class Wallet:

    def __init__(self, priv_key, pub_key):
        self.private_key = priv_key 
        self.public_key = pub_key
        self.address = utils.addr(pub_key)

def new():

    priv_key, pub_key = utils.gen_key_pair()

    new_wallet = Wallet(priv_key, pub_key)

    return new_wallet

def get_addr(wallet):

    return wallet.address

def sign_transaction(priv_key, trans_data):

    pass # no trans_data yet

def create_transaction(recipient_address, amount, fee, utxo_set):

    # dont have a uxto_set yet, also no searching it yet 

    uxto_set = ""

    # bunch of things I can't do yet 

    trans_data = "" # make it right 

    sign(priv_key, trans_data) # fix this to be wallet priv key

    # add to unlock_script

"""
# test

w = new()

print(get_addr(w))
"""
