import asyncio
import ccxt
import configparser
import logging
import time


class Scalper:
    def __init__(self, config_file, exchange):
        try:
            cfg = configparser.ConfigParser()
            cfg.read(config_file)
            self._api_key = cfg[exchange]['api_key']
            self._api_secret = cfg[exchange]['api_secret']
            self.symbol = cfg[exchange]['symbol']
            self.price_move = float(cfg[exchange]['price_move'])
            self.hedge_lookup = cfg[exchange]['hedge_lookup']
            self.hedge_contract = cfg[exchange]['hedge_contract']
            self.done = False
            if exchange == "Deribit":
                self.exchange = ccxt.deribit({'apiKey': self._api_key, 'secret': self._api_secret})
            else:
                raise Exception("Exchange " + exchange + " not yet supported")

            if self.symbol != "BTC" and self.symbol != "ETH":
                raise Exception("Only BTC and ETH supported symbols")

        except  Exception as e:
            logging.error("Failed to initialize configuration from file " + config_file, e)
    
    async def get_option_greeks(self):
        delta = float(self.exchange.fetch_balance({'currency': str(self.symbol)})['info']['options_delta'])
        gamma = float(self.exchange.fetch_balance({'currency': str(self.symbol)})['info']['options_gamma'])
        return delta, gamma

    def get_hedge_delta(self):
        return float(self.exchange.fetch_balance({'currency': str(self.symbol)})['info']['delta_total_map'][self.hedge_lookup])

    async def get_open_orders(self, symbol):
        return self.exchange.fetch_open_orders(symbol)

    async def get_order_book(self, symbol):
        orderbook = self.exchange.fetch_l2_order_book(symbol, 40)
        bids = orderbook['bids']
        asks = orderbook['asks']
        return bids, asks

    async def delta_hedge(self):
        bids, asks = self.get_order_book(self.hedge_contract)
        open_orders = self.get_open_orders(self.hedge_contract)
        option_delta, option_gamma = self.get_option_greeks()
        hedge_delta = self.get_hedge_delta()
        atm_delta = hedge_delta + option_delta

        # Create a ladder for hedge instrument (future/swap) 
        # of bid price, bid amount and ask price, ask amount based on self.price_move decrements/increments
        #
        # use (atm_delta + multiplier * self.price_move * gamma) * (spot price + multiplier * self.price_move)
        # replace open orders with new ladder

    async def get_balance(self, symbol):
        return self.exchange.fetch_balance({'currency': self.symbol})

    async def run_loop(self):
        retry_count = 10
        while not self.done:
            try:
                self.delta_hedge()
                time.sleep(1)
                retry_count = 0
            except Exception as e:
                logging.error("Hedge failed", e)
                retry_count += 1
                if retry_count >= 9:
                    self.done = True

    def run(self):
        self.done = False
        loop = asyncio.get_event_loop()
        loop.run_until_complete(self.run_loop())
