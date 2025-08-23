import os
import aiohttp
import logging
from typing import Optional, List, Dict, Any
import asyncio
import json

logger = logging.getLogger(__name__)

class SecureBTCLogger:
    """Secure logger that masks sensitive BTC addresses"""
    @staticmethod
    def mask_address(address: str) -> str:
        """Mask BTC address for logging"""
        if len(address) > 16:
            return f"{address[:8]}***MASKED***{address[-4:]}"
        return "***MASKED***"

    @staticmethod
    def log_api_call(url: str, address: str = None):
        """Log API call with masked address"""
        if address:
            masked_addr = SecureBTCLogger.mask_address(address)
            logger.debug(f"BTC API call to {url} for address {masked_addr}")
        else:
            logger.debug(f"BTC price API call to {url}")

    @staticmethod
    def log_error(error: str, address: str = None):
        """Log error with masked address"""
        if address:
            masked_addr = SecureBTCLogger.mask_address(address)
            logger.warning(f"BTC API error for address {masked_addr}: {error}")
        else:
            logger.warning(f"BTC API error: {error}")

secure_logger = SecureBTCLogger()

class BTCPriceAPI:
    """Production-grade BTC price fetcher with multiple API sources"""

    def __init__(self):
        self.price_apis = self._load_price_apis()
        self.blockchain_apis = self._load_blockchain_apis()

    def _load_price_apis(self) -> List[Dict[str, Any]]:
        """Load all BTC price APIs from environment"""
        apis = []

        # Load all price APIs from environment
        for i in range(1, 21):  # 20 price APIs
            api_url = os.getenv(f"BTC_PRICE_API_{i}")
            if api_url:
                apis.append({
                    'url': api_url,
                    'name': f'API_{i}',
                    'parser': self._get_price_parser(api_url)
                })

        return apis

    def _load_blockchain_apis(self) -> List[Dict[str, Any]]:
        """Load all blockchain APIs from environment"""
        apis = []

        # Load all blockchain APIs from environment
        for i in range(1, 21):  # 20 blockchain APIs
            api_url = os.getenv(f"BTC_API_{i}")
            if api_url:
                apis.append({
                    'url': api_url,
                    'name': f'BLOCKCHAIN_API_{i}',
                    'parser': self._get_balance_parser(api_url)
                })

        return apis

    def _get_price_parser(self, url: str):
        """Get appropriate parser for price API"""
        if 'coingecko' in url:
            return lambda data: float(data['bitcoin']['usd'])
        elif 'binance' in url:
            return lambda data: float(data['price'])
        elif 'coincap' in url:
            return lambda data: float(data['data']['priceUsd'])
        elif 'cryptocompare' in url:
            return lambda data: float(data['USD'])
        elif 'coindesk' in url:
            return lambda data: float(data['bpi']['USD']['rate_float'])
        elif 'bitfinex' in url:
            return lambda data: float(data['last_price'])
        elif 'kraken' in url:
            return lambda data: float(list(data['result'].values())[0]['c'][0])
        elif 'bitstamp' in url:
            return lambda data: float(data['last'])
        elif 'gemini' in url:
            return lambda data: float(data['last'])
        elif 'bittrex' in url:
            return lambda data: float(data['lastTradeRate'])
        elif 'huobi' in url:
            return lambda data: float(data['tick']['close'])
        elif 'kucoin' in url:
            return lambda data: float(data['data']['price'])
        elif 'gate.io' in url:
            return lambda data: float(data['last'])
        elif 'okx' in url:
            return lambda data: float(data['data'][0]['last'])
        elif 'mexc' in url:
            return lambda data: float(data['price'])
        elif 'bybit' in url:
            return lambda data: float(data['result'][0]['last_price'])
        elif 'crypto.com' in url:
            return lambda data: float(data['result']['data'][0]['a'])
        elif 'bitget' in url:
            return lambda data: float(data['data']['close'])
        elif 'phemex' in url:
            return lambda data: float(data['result']['close']) / 10000  # Phemex uses scaled prices
        else:
            # Fallback for unexpected formats, trying common keys
            return lambda data: float(data.get('price', data.get('last', data.get('rate', 0))))

    def _get_balance_parser(self, url: str):
        """Get appropriate parser for balance API"""
        # Blockstream and mempool.space often return UTXO data, so we sum them
        if 'blockstream' in url or 'mempool.space' in url:
            return lambda data, addr: sum([utxo.get('value', 0) for utxo in data]) / 100000000
        elif 'blockcypher' in url:
            return lambda data, addr: data.get('balance', 0) / 100000000
        elif 'blockchain.info' in url:
            return lambda data, addr: data.get('final_balance', 0) / 100000000
        elif 'blockchair' in url:
            return lambda data, addr: data.get('data', {}).get(addr, {}).get('address', {}).get('balance', 0) / 100000000
        else:
            # Fallback for unexpected formats, trying common keys for balance
            return lambda data, addr: float(data.get('balance', 0)) / 100000000

    async def get_btc_price(self) -> float:
        """Get BTC price from multiple sources with fallback"""
        for api in self.price_apis:
            try:
                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                    secure_logger.log_api_call(api['url'])
                    async with session.get(api['url']) as response:
                        if response.status == 200:
                            data = await response.json()
                            price = api['parser'](data)
                            if price > 0:
                                logger.info(f"BTC price from {api['name']}: ${price:,.2f}")
                                return price
                            else:
                                logger.warning(f"Received non-positive price from {api['name']}: {price}")
                        else:
                            logger.warning(f"HTTP {response.status} from price source {api['name']}: {response.reason}")
            except asyncio.TimeoutError:
                secure_logger.log_error(f"{api['name']} timed out", None)
                continue
            except aiohttp.ClientConnectorError as e:
                secure_logger.log_error(f"{api['name']} connection error: {e}", None)
                continue
            except json.JSONDecodeError:
                secure_logger.log_error(f"{api['name']} returned invalid JSON", None)
                continue
            except Exception as e:
                secure_logger.log_error(f"{api['name']} failed: {type(e).__name__} - {str(e)}", None)
                continue

        # Ultimate fallback - get from environment but log warning
        fallback_price = float(os.getenv("FALLBACK_BTC_PRICE", 92000))
        logger.warning(f"All price APIs failed! Using fallback price: ${fallback_price:,.2f}")
        return fallback_price

    async def check_address_balance(self, address: str) -> float:
        """Check BTC address balance from multiple sources"""
        if not address or len(address) < 26:
            logger.warning("Invalid address provided for balance check.")
            return 0.0

        for api in self.blockchain_apis:
            try:
                # Construct URL based on API type
                if 'blockstream' in api['url'] or 'mempool.space' in api['url']:
                    url = f"{api['url']}/address/{address}/utxo"
                elif 'blockcypher' in api['url']:
                    url = f"{api['url']}/addrs/{address}/balance"
                elif 'blockchain.info' in api['url']:
                    url = f"{api['url']}/rawaddr/{address}"
                elif 'blockchair' in api['url']:
                    url = f"{api['url']}/dashboards/address/{address}"
                else:
                    logger.debug(f"Skipping unsupported blockchain API: {api['url']}")
                    continue  # Skip unsupported APIs for now

                async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as session:
                    secure_logger.log_api_call(url, address)
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            balance = api['parser'](data, address)
                            logger.debug(f"Balance from {api['name']} for {address}: {balance:.8f} BTC")
                            return balance
                        else:
                            logger.warning(f"HTTP {response.status} from blockchain source {api['name']} for {address}: {response.reason}")
                            if response.status == 404: # Address not found or invalid
                                logger.debug(f"Address {address} not found or invalid by {api['name']}.")
                                continue # Try next API

            except asyncio.TimeoutError:
                secure_logger.log_error(f"{api['name']} timed out for address {address}", address)
                continue
            except aiohttp.ClientConnectorError as e:
                secure_logger.log_error(f"{api['name']} connection error for address {address}: {e}", address)
                continue
            except json.JSONDecodeError:
                secure_logger.log_error(f"{api['name']} returned invalid JSON for address {address}", address)
                continue
            except Exception as e:
                secure_logger.log_error(f"{api['name']} failed for address {address}: {type(e).__name__} - {str(e)}", address)
                continue

        logger.error(f"All blockchain APIs failed to check balance for address {address}")
        return 0.0

    async def check_double_spend(self, address: str, expected_amount: float) -> bool:
        """Check for potential double spending by looking for multiple transactions with similar amounts"""
        if not address:
            logger.warning("No address provided for double spend check.")
            return False

        try:
            # Using blockstream.info as a primary source for transaction history
            # It's generally reliable and has a clear API for transactions
            url = f"https://blockstream.info/api/address/{address}/txs"

            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session:
                secure_logger.log_api_call(url, address)
                async with session.get(url) as response:
                    if response.status == 200:
                        txs = await response.json()
                        
                        # Count transactions where the address receives an amount close to expected_amount
                        relevant_tx_count = 0
                        for tx in txs:
                            # Check if this transaction is an inbound transaction for the address
                            is_inbound = False
                            for vin in tx.get('vin', []):
                                if vin.get('address') == address:
                                    # This check might be too simple if the address also sends some amount
                                    pass # We are primarily interested in outputs to the address
                            
                            # Check outputs to the address
                            for vout in tx.get('vout', []):
                                if vout.get('scriptpubkey_address') == address:
                                    amount_satoshis = vout.get('value', 0)
                                    amount_btc = amount_satoshis / 100000000
                                    
                                    # Check if the amount received is close to the expected amount
                                    # Using a small tolerance to account for potential minor network fees or variations
                                    if abs(amount_btc - expected_amount) < 0.00001: # Tolerance of 1 satoshi
                                        relevant_tx_count += 1
                                        # If we find a second transaction matching, it's a strong indicator of double spend
                                        if relevant_tx_count > 1:
                                            logger.warning(f"Potential double spend detected for {address}. Multiple transactions found with amount close to {expected_amount} BTC.")
                                            return True
                        
                        # If only one or no relevant transactions found, assume no double spend
                        return False

                    elif response.status == 404:
                        logger.debug(f"No transactions found for address {address} on blockstream.info.")
                        return False # No transactions means no double spend
                    else:
                        logger.warning(f"HTTP {response.status} from blockstream.info for {address}: {response.reason}")
                        # If the API fails, we can't confirm, so err on the side of caution
                        return True 

        except asyncio.TimeoutError:
            logger.error(f"Double spend check timed out for address {address}")
            return True # Err on the side of caution
        except aiohttp.ClientConnectorError as e:
            logger.error(f"Double spend check connection error for address {address}: {e}")
            return True # Err on the side of caution
        except json.JSONDecodeError:
            logger.error(f"Double spend check received invalid JSON for address {address}")
            return True # Err on the side of caution
        except Exception as e:
            logger.error(f"Error checking double spend for {address}: {type(e).__name__} - {str(e)}")
            return True # Err on the side of caution

# Global instance
btc_api = BTCPriceAPI()

# Exported functions for backward compatibility
async def get_btc_price() -> float:
    """Get current BTC price in USD"""
    return await btc_api.get_btc_price()

async def check_address_balance(address: str) -> float:
    """Check BTC address balance"""
    return await btc_api.check_address_balance(address)

async def check_double_spend(address: str, expected_amount: float) -> bool:
    """Check for potential double spending"""
    return await btc_api.check_double_spend(address, expected_amount)