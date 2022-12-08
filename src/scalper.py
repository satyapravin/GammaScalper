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
            self.ladder_size = int(cfg[exchange]['ladder_size'])
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

    async def get_hedge_delta(self):
        return float(self.exchange.fetch_balance({'currency': str(self.symbol)})['info']['delta_total_map'][self.hedge_lookup])

    async def get_open_orders(self, symbol):
        return self.exchange.fetch_open_orders(symbol)

    async def get_ticker(self, symbol):
        ticker = self.exchange.fetch_ticker(symbol)
        return ticker["bid"], ticker["ask"]

    async def get_order_book(self, symbol):
        orderbook = self.exchange.fetch_l2_order_book(symbol, 40)
        bids = orderbook['bids']
        asks = orderbook['asks']
        return bids, asks


    async def get_new_delta(self, hedge_delta, option_delta, option_gamma, move):
        return hedge_delta + option_delta * (1 + option_gamma * move)

    async def delta_hedge(self):
        # get greeks
        option_delta, option_gamma = await self.get_option_greeks()
        hedge_delta = await self.get_hedge_delta()
        
        self.exchange.cancel_all_orders(self.hedge_contract)

        proposed_bids = {}
        proposed_asks = {}

        # compute new ladder to publish
        bid_price, ask_price = await self.get_ticker(self.hedge_contract)

        print("bid price", bid_price, "ask price", ask_price)
        print("option delta", option_delta, "hedge delta", hedge_delta, "option gamma", option_gamma)

        net_bid_delta = 0
        net_ask_delta = 0        
        
        first_bid_price = bid_price - self.price_move
        bdelta = await self.get_new_delta(hedge_delta, option_delta, option_gamma, -self.price_move)

        if bdelta < 0:
            proposed_bids[first_bid_price] = abs(bdelta) * first_bid_price
            net_bid_delta = bdelta

        first_ask_price = ask_price + self.price_move
        adelta = await self.get_new_delta(hedge_delta, option_delta, option_gamma, self.price_move)
        
        if adelta > 0:
            proposed_asks[first_ask_price] = adelta * first_ask_price
            net_ask_delta = adelta

        for ladder in range(1, self.ladder_size):
            price_delta = self.price_move * (2**ladder)
            new_bid_price = bid_price - price_delta
            bdelta = await self.get_new_delta(hedge_delta, option_delta, option_gamma, -price_delta) - net_bid_delta

            if bdelta < 0:
                proposed_bids[new_bid_price] = abs(bdelta) * new_bid_price
                net_bid_delta += bdelta

            new_ask_price = ask_price - price_delta
            adelta = await self.get_new_delta(hedge_delta, option_delta, option_gamma, price_delta) - net_ask_delta
            if adelta > 0:
                proposed_asks[new_ask_price] = adelta * new_ask_price
                net_ask_delta += adelta

        # submit orders
        for bid_price in proposed_bids:
            print("bid", bid_price, proposed_bids[bid_price])
            #self.exchange.create_post_only_order(self.hedge_contract, 'limit', "buy", proposed_bids[bid_price], {"post_only": True})

        for ask_price in proposed_asks:
            print("ask", ask_price, proposed_asks[ask_price])
            #self.exchange.create_post_only_order(self.hedge_contract, 'limit', "sell", proposed_asks[ask_price], {"post_only": True})

       
    async def get_balance(self, symbol):
        return self.exchange.fetch_balance({'currency': self.symbol})

    async def run_loop(self):
        retry_count = 10
        while not self.done:
            try:
                self.delta_hedge()
                time.sleep(5)
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
