"""Crypto address lookup: Bitcoin (mempool.space) and Ethereum (Blockscout) public explorers."""
import datetime as dt
import re

from plugin_api import F, L, ToolError, session

BTC_RX = re.compile(r"^(bc1[ac-hj-np-z02-9]{25,87}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$")
ETH_RX = re.compile(r"^0x[0-9a-fA-F]{40}$")


def _ts(t):
    try:
        return dt.datetime.utcfromtimestamp(int(t)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return ""


def _btc(job, a, emit, s):
    r = s.get(f"https://mempool.space/api/address/{a}", timeout=20)
    if r.status_code != 200:
        raise ToolError(L(job, f"mempool.space yanıt vermedi (HTTP {r.status_code}).", f"mempool.space did not respond (HTTP {r.status_code})."))
    d = r.json()
    c, m = d.get("chain_stats", {}), d.get("mempool_stats", {})
    bal = (c.get("funded_txo_sum", 0) - c.get("spent_txo_sum", 0)) / 1e8
    recv = c.get("funded_txo_sum", 0) / 1e8
    emit(title=L(job, "Bitcoin adresi", "Bitcoin address"), url=f"https://mempool.space/address/{a}", status="found",
         detail=L(job, f"Bakiye {bal:.8f} BTC · toplam alınan {recv:.8f} BTC · {c.get('tx_count', 0)} işlem",
                  f"Balance {bal:.8f} BTC · total received {recv:.8f} BTC · {c.get('tx_count', 0)} transactions"),
         meta={L(job, "Onay bekleyen işlem", "Unconfirmed tx"): m.get("tx_count")})
    try:
        txs = s.get(f"https://mempool.space/api/address/{a}/txs", timeout=20).json()
        times = [t["status"]["block_time"] for t in txs if t.get("status", {}).get("block_time")]
        if times:
            emit(title=L(job, "Son etkinlik", "Last activity"), status="info", detail=_ts(max(times)),
                 meta={L(job, "Bu sayfadaki en eski işlem", "Oldest tx on this page"): _ts(min(times))})
    except Exception:
        pass


def _eth(job, a, emit, s):
    base = "https://eth.blockscout.com/api/v2/addresses/"
    r = s.get(base + a, timeout=20)
    if r.status_code == 404:
        emit(title=L(job, "Ethereum adresinde kayıt yok", "No record for this Ethereum address"), status="notfound")
        return
    if r.status_code != 200:
        raise ToolError(L(job, f"Blockscout yanıt vermedi (HTTP {r.status_code}).", f"Blockscout did not respond (HTTP {r.status_code})."))
    d = r.json()
    bal = int(d.get("coin_balance") or 0) / 1e18
    tags = ", ".join(t.get("display_name", "") for t in (d.get("public_tags") or []) if t.get("display_name"))
    meta = {"ENS": d.get("ens_domain_name"), L(job, "Etiketler", "Tags"): tags or None, L(job, "Ad", "Name"): d.get("name"),
            L(job, "Sözleşme mi", "Contract"): L(job, "evet", "yes") if d.get("is_contract") else L(job, "hayır", "no")}
    try:
        cnt = s.get(base + a + "/counters", timeout=20).json()
        meta[L(job, "İşlem sayısı", "Transactions")] = cnt.get("transactions_count")
        meta[L(job, "Token transferi", "Token transfers")] = cnt.get("token_transfers_count")
    except Exception:
        pass
    emit(title=L(job, "Ethereum adresi", "Ethereum address"), url=f"https://eth.blockscout.com/address/{a}", status="found",
         detail=L(job, f"Bakiye {bal:.6f} ETH", f"Balance {bal:.6f} ETH") + (f" · ENS: {d['ens_domain_name']}" if d.get("ens_domain_name") else ""),
         meta=meta)


def run(job, inp, emit):
    a = inp["address"].strip()
    s = session()
    if BTC_RX.match(a):
        _btc(job, a, emit, s)
        links = [("Blockchair", f"https://blockchair.com/bitcoin/address/{a}"),
                 ("WalletExplorer", f"https://www.walletexplorer.com/address/{a}"),
                 ("Arkham", f"https://intel.arkm.com/explorer/address/{a}")]
    elif ETH_RX.match(a):
        _eth(job, a, emit, s)
        links = [("Etherscan", f"https://etherscan.io/address/{a}"), ("Arkham", f"https://intel.arkm.com/explorer/address/{a}"),
                 ("DeBank", f"https://debank.com/profile/{a}")]
    else:
        raise ToolError(L(job, "Bitcoin (1…, 3…, bc1…) ya da Ethereum (0x…) adresi girin.",
                          "Enter a Bitcoin (1…, 3…, bc1…) or Ethereum (0x…) address."))
    for name, url in links:
        emit(title=name, url=url, status="info", tags=L(job, "Gezgin", "Explorer"))
    emit(title=L(job, "Web'de geçtiği yerler", "Mentions on the web"), url=f'https://www.google.com/search?q="{a}"', status="info")


PLUGIN = {
    "id": "crypto", "group": "Kripto", "title": "Kripto adresi", "icon": "hash",
    "desc": "Bitcoin ve Ethereum adreslerinin bakiyesini, işlem sayısını, ENS adını ve herkese açık etiketlerini gösterir.",
    "fields": [F("address", "Adres", required=True, placeholder="bc1… / 1… / 3… / 0x…")],
    "run": run,
    "accepts": {"crypto": {"fields": {"address": "$"}, "default": True}},
    "about": {"what": "Herkese açık blok gezginlerinden (mempool.space, Blockscout) adresin bakiyesini, toplam alınan miktarı, işlem sayısını, son etkinliğini, ENS adını ve borsa / servis etiketlerini getirir.",
              "when": "Bir dolandırıcılık ya da bağış adresinin ne kadar kullanıldığını ve kime ait olabileceğini görmek için.",
              "input": "Bitcoin ya da Ethereum adresi.", "output": "Adres özeti ve gezgin bağlantıları.",
              "tips": "Etiketli adresler (borsa, karıştırıcı) iz sürmede önemli bir ipucudur; WalletExplorer aynı cüzdana ait diğer adresleri gösterebilir."},
    "en": {"title": "Crypto address", "desc": "Shows the balance, transaction count, ENS name and public tags of Bitcoin and Ethereum addresses.",
           "fields": {"address": {"label": "Address"}},
           "about": {"what": "Fetches balance, total received, transaction count, last activity, ENS name and exchange / service tags from public block explorers (mempool.space, Blockscout).",
                     "when": "To see how much a scam or donation address was used and who might be behind it.",
                     "input": "Bitcoin or Ethereum address.", "output": "Address summary and explorer links.",
                     "tips": "Tagged addresses (exchanges, mixers) are key clues; WalletExplorer can show other addresses of the same wallet."}},
}
