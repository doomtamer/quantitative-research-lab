#!/usr/bin/env python3
"""Quantitative Research Lab — BTCUSDT daily dataset downloader (v2).

Uses public archives/APIs; no exchange credentials are needed.
Outputs data/raw/, data/processed/, reports/ relative to the project root.
See docs/DATA_DOWNLOAD.md for sources, coverage and limitations.
"""
from __future__ import annotations

import argparse
import io
import json
import threading
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW = PROJECT_ROOT / 'data' / 'raw'
PROCESSED = PROJECT_ROOT / 'data' / 'processed'
REPORTS = PROJECT_ROOT / 'reports'
CACHE = RAW / 'binance_vision_cache'
SYMBOL = 'BTCUSDT'
VISION = 'https://data.binance.vision/data/futures/um'
FAPI = 'https://fapi.binance.com'
FRED_SERIES = {
    'sp500': 'SP500', 'nasdaq': 'NASDAQCOM', 'vix': 'VIXCLS',
    'usd_broad': 'DTWEXBGS', 'us2y': 'DGS2', 'us10y': 'DGS10',
    'wti': 'DCOILWTICO', 'fedfunds': 'FEDFUNDS', 'm2': 'M2SL',
}
METRIC_RENAME = {
    'sum_open_interest': 'oi_btc',
    'sum_open_interest_value': 'oi_usd',
    'count_toptrader_long_short_ratio': 'toptrader_long_short_count',
    'sum_toptrader_long_short_ratio': 'toptrader_long_short_ratio',
    'count_long_short_ratio': 'account_long_short_ratio',
    'sum_taker_long_short_vol_ratio': 'taker_long_short_volume_ratio',
}
KLINE_COLS = [
    'open_time', 'open', 'high', 'low', 'close', 'volume', 'close_time',
    'quote_volume', 'n_trades', 'taker_buy_base_volume',
    'taker_buy_quote_volume', 'ignore',
]
USER_AGENT = {'User-Agent':'Mozilla/5.0 (compatible; QuantResearchLab/2.0; educational research)'}
WARNINGS = []
LOCK = threading.Lock()


def log(message):
    print(f'[{datetime.now().strftime("%H:%M:%S")}] {message}', flush=True)


def warn(message):
    with LOCK:
        WARNINGS.append(str(message))
    log('WARNING: ' + str(message))


def get(url, params=None, allow_404=False, attempts=4, timeout=40):
    last=None
    for i in range(attempts):
        try:
            r=requests.get(url, params=params, headers=USER_AGENT, timeout=timeout)
            if r.status_code == 404 and allow_404:
                return None
            if r.status_code in (429, 418, 500, 502, 503, 504):
                last=f'HTTP {r.status_code}'
                time.sleep(min((i+1)*1.5, 8))
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            last=str(e)
            # Geoblocking and other permanent errors should not be retried.
            if isinstance(e, requests.HTTPError) and e.response is not None and e.response.status_code in (400, 401, 403, 404, 451):
                break
            time.sleep(min((i+1)*1.5, 8))
    raise RuntimeError(f'{url}: {last}')


def zip_csv(url, local_cache:Path, optional=False):
    """Read archived CSV. Cache real ZIP bytes; skip unavailable (404) archives."""
    if not local_cache.is_file():
        response=get(url, allow_404=optional, timeout=75, attempts=3)
        if response is None:
            return None
        data=response.content
        if not zipfile.is_zipfile(io.BytesIO(data)):
            raise RuntimeError(f'Invalid ZIP response for {url}')
        local_cache.parent.mkdir(parents=True, exist_ok=True)
        tmp=local_cache.with_suffix('.tmp')
        tmp.write_bytes(data)
        tmp.replace(local_cache)
    try:
        with zipfile.ZipFile(local_cache) as z:
            members=[name for name in z.namelist() if name.lower().endswith('.csv')]
            if not members:
                raise ValueError('ZIP has no CSV')
            with z.open(members[0]) as f:
                return pd.read_csv(f, header=None, dtype=str, low_memory=False)
    except (zipfile.BadZipFile, ValueError) as e:
        local_cache.unlink(missing_ok=True)
        raise RuntimeError(f'Bad archive {local_cache}: {e}') from e


def period_months(start, end):
    return pd.period_range(pd.Timestamp(start), pd.Timestamp(end), freq='M')


def normalize_kline(raw):
    if raw is None or raw.empty: return pd.DataFrame(columns=KLINE_COLS)
    if raw.shape[1] < 11:
        raise ValueError(f'Kline CSV unexpectedly has {raw.shape[1]} columns')
    raw=raw.iloc[:,:min(12, raw.shape[1])].copy()
    raw.columns=KLINE_COLS[:raw.shape[1]]
    raw['open_time']=pd.to_numeric(raw['open_time'],errors='coerce')
    raw=raw.dropna(subset=['open_time'])
    return raw


def klines_from_vision(start, end):
    blocks=[]
    today=pd.Timestamp(datetime.now(timezone.utc).date())
    for period in period_months(start, end):
        month_start=period.start_time.normalize()
        month_end=period.end_time.normalize()
        if month_end < today:
            ym=period.strftime('%Y-%m')
            stem=f'{SYMBOL}-1d-{ym}.zip'
            url=f'{VISION}/monthly/klines/{SYMBOL}/1d/{stem}'
            raw=zip_csv(url, CACHE/'klines'/stem, optional=True)
            if raw is not None:
                blocks.append(normalize_kline(raw))
                continue
            warn(f'Archive {stem} unavailable; trying daily archives')
        for day in pd.date_range(max(pd.Timestamp(start),month_start),min(pd.Timestamp(end),month_end),freq='D'):
            ds=day.strftime('%Y-%m-%d')
            stem=f'{SYMBOL}-1d-{ds}.zip'
            url=f'{VISION}/daily/klines/{SYMBOL}/1d/{stem}'
            raw=zip_csv(url, CACHE/'klines'/stem, optional=True)
            if raw is not None:
                blocks.append(normalize_kline(raw))
    if not blocks: return pd.DataFrame(columns=KLINE_COLS)
    return pd.concat(blocks, ignore_index=True)


def klines_from_api(start,end):
    rows=[]
    cursor=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    end_ms=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1)).timestamp()*1000)
    while cursor<=end_ms:
        j=get(f'{FAPI}/fapi/v1/klines',params={'symbol':SYMBOL,'interval':'1d','startTime':cursor,'endTime':end_ms,'limit':1000}).json()
        if not j:break
        rows.extend(j)
        nxt=int(j[-1][0])+86_400_000
        if nxt<=cursor: break
        cursor=nxt
        if len(j)<1000:break
    return normalize_kline(pd.DataFrame(rows))


def download_ohlcv(start,end):
    log('Downloading BTCUSDT USD-M 1d OHLCV from Binance Vision...')
    try:
        raw=klines_from_vision(start,end)
    except Exception as e:
        warn(f'Binance Vision OHLCV unavailable: {e}; trying REST')
        raw=pd.DataFrame(columns=KLINE_COLS)
    df=pd.DataFrame()
    if len(raw):
        raw['date']=pd.to_datetime(raw['open_time'],unit='ms',utc=True,errors='coerce').dt.normalize()
        df=raw.dropna(subset=['date']).drop_duplicates('date',keep='last').set_index('date')
    expected=pd.date_range(start,end,freq='D',tz='UTC')
    missing=expected.difference(df.index) if not df.empty else expected
    if len(missing):
        log(f'Vision is missing {len(missing)} daily candles; trying Binance REST...')
        try:
            api=klines_from_api(start,end)
            api['date']=pd.to_datetime(api['open_time'],unit='ms',utc=True,errors='coerce').dt.normalize()
            api=api.dropna(subset=['date']).drop_duplicates('date').set_index('date')
            df=pd.concat([df,api]).loc[lambda x:~x.index.duplicated(keep='first')].sort_index()
        except Exception as e:
            warn(f'Binance REST OHLCV fallback failed: {e}')
    if df.empty: raise RuntimeError('No BTCUSDT candles available from Binance Vision or API')
    for col in KLINE_COLS[1:]:
        if col!='ignore' and col in df: df[col]=pd.to_numeric(df[col],errors='coerce')
    df=df.loc[(df.index>=pd.Timestamp(start,tz='UTC')) & (df.index<=pd.Timestamp(end,tz='UTC'))]
    wanted=[x for x in KLINE_COLS if x not in ('open_time','close_time','ignore')]
    df=df[[x for x in wanted if x in df]].sort_index()
    missing=expected.difference(df.index)
    if len(missing):
        warn(f'OHLCV missing {len(missing)} requested days: '+','.join(str(x.date()) for x in missing[:12]))
        if any(x < df.index.max() for x in missing):
            raise RuntimeError('Internal daily OHLCV gaps: refusing to build a misleading dataset')
    bad=(
      (df[['open','high','low','close']]<=0).any(axis=1)
      | (df['high']<df[['open','close']].max(axis=1))
      | (df['low']>df[['open','close']].min(axis=1))
      | (df['high']<df['low'])
    )
    if bad.any(): raise RuntimeError(f'{bad.sum()} invalid daily OHLCV rows — review source')
    df.index.name='date'
    df.to_csv(RAW/'binance_btcusdt_1d.csv')
    log(f'OHLCV: {len(df)} days, {df.index.min().date()} through {df.index.max().date()}')
    return df


def funding_from_vision(start,end):
    """Binance Vision monthly fundingRate columns: calc_time, interval_hours, last_funding_rate."""
    out=[]
    for period in period_months(start,end):
        ym=period.strftime('%Y-%m')
        stem=f'{SYMBOL}-fundingRate-{ym}.zip'
        url=f'{VISION}/monthly/fundingRate/{SYMBOL}/{stem}'
        try:
            raw=zip_csv(url,CACHE/'funding'/stem, optional=True)
        except Exception as e:
            warn(f'Funding archive {ym} failed: {e}')
            continue
        if raw is None:
            warn(f'Funding archive {ym} unavailable (may not be published yet)')
            continue
        if raw.shape[1]<3:
            warn(f'Funding ZIP {ym} has unexpected column count {raw.shape[1]}')
            continue
        a=raw.iloc[:,:3].copy()
        a.columns=['calc_time','funding_interval_hours','last_funding_rate']
        ts_num=pd.to_numeric(a['calc_time'],errors='coerce')
        a['funding_time']=pd.to_datetime(ts_num,unit='ms',utc=True,errors='coerce')
        fallback=pd.to_datetime(a['calc_time'],utc=True,errors='coerce',format='mixed')
        a['funding_time']=a['funding_time'].fillna(fallback)
        a['funding_rate']=pd.to_numeric(a['last_funding_rate'],errors='coerce')
        a['source']='binance_vision'
        out.append(a[['funding_time','funding_rate','source']].dropna(subset=['funding_time','funding_rate']))
    return pd.concat(out,ignore_index=True) if out else pd.DataFrame(columns=['funding_time','funding_rate','source'])


def funding_from_api(start,end):
    rows=[]
    cursor=int(pd.Timestamp(start,tz='UTC').timestamp()*1000)
    end_ms=int((pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1)-pd.Timedelta(milliseconds=1)).timestamp()*1000)
    while cursor<=end_ms:
        j=get(f'{FAPI}/fapi/v1/fundingRate',params={'symbol':SYMBOL,'startTime':cursor,'endTime':end_ms,'limit':1000}).json()
        if not j:break
        rows.extend(j)
        nxt=int(j[-1]['fundingTime'])+1
        if nxt<=cursor: break
        cursor=nxt
        if len(j)<1000: break
    if not rows: return pd.DataFrame(columns=['funding_time','funding_rate','source'])
    d=pd.DataFrame(rows)
    d['funding_time']=pd.to_datetime(d['fundingTime'],unit='ms',utc=True,errors='coerce')
    d['funding_rate']=pd.to_numeric(d['fundingRate'],errors='coerce')
    d['source']='binance_api'
    return d[['funding_time','funding_rate','source']].dropna()


def download_funding(start,end):
    log('Downloading historical funding from Binance Vision monthly archives...')
    events=funding_from_vision(start,end)
    try:
        # Use API to fill gaps and last, still-unpublished calendar month.
        recent_start=max(pd.Timestamp(start,tz='UTC'),pd.Timestamp(end,tz='UTC')-pd.Timedelta(days=45))
        recent=funding_from_api(recent_start.strftime('%Y-%m-%d'),end)
        events=pd.concat([events,recent],ignore_index=True)
    except Exception as e:
        warn(f'Funding REST fallback unavailable: {e}')
    if not events.empty:
        events=events.drop_duplicates(subset='funding_time',keep='first').sort_values('funding_time')
        events=events.loc[(events['funding_time']>=pd.Timestamp(start,tz='UTC')) & (events['funding_time']<pd.Timestamp(end,tz='UTC')+pd.Timedelta(days=1))]
    events.to_csv(RAW/'binance_funding_events.csv',index=False)
    if events.empty:
        warn('No funding data — E001 cannot run until this source is repaired')
        return pd.DataFrame(columns=['funding_mean','funding_sum','funding_min','funding_max','funding_std','funding_n'])
    events['date']=events['funding_time'].dt.normalize()
    funding=events.groupby('date')['funding_rate'].agg(
        funding_mean='mean',funding_sum='sum',funding_min='min',
        funding_max='max',funding_std='std',funding_n='count'
    )
    funding.to_csv(RAW/'binance_funding_daily.csv')
    log(f'Funding: {len(funding)} daily rows, {len(events)} events')
    return funding


def metrics_day(day):
    ds=day.strftime('%Y-%m-%d')
    stem=f'{SYMBOL}-metrics-{ds}.zip'
    url=f'{VISION}/daily/metrics/{SYMBOL}/{stem}'
    try:
        raw=zip_csv(url,CACHE/'metrics'/stem,optional=True)
        if raw is None: return ds,None,'404'
        cols=[str(x).lstrip('\ufeff').strip() for x in raw.iloc[0].tolist()]
        if 'create_time' not in cols:
            return ds,None,'unexpected_header'
        raw.columns=cols
        raw=raw.iloc[1:].copy()
        ts=pd.to_datetime(raw['create_time'],utc=True,errors='coerce')
        # Only samples with a label within the named date. Some versions label
        # the closing 5m interval as next-day 00:00; never include it.
        raw=raw.loc[(ts>=day)&(ts<day+pd.Timedelta(days=1))].copy()
        if raw.empty: return ds,None,'empty'
        raw['_time']=pd.to_datetime(raw['create_time'],utc=True,errors='coerce')
        row=raw.sort_values('_time').iloc[-1]
        vals={target:pd.to_numeric(row.get(src),errors='coerce') for src,target in METRIC_RENAME.items()}
        vals['date']=day
        return ds,vals,None
    except Exception as e:
        return ds,None,str(e)[:250]


def download_metrics(start,end,workers=6):
    log('Downloading futures OI / trader positioning archives...')
    dates=list(pd.date_range(start,end,freq='D',tz='UTC'))
    results=[];missing=[]
    with ThreadPoolExecutor(max_workers=max(1, min(workers,12))) as ex:
        jobs={ex.submit(metrics_day,day):day for day in dates}
        for n,job in enumerate(as_completed(jobs),1):
            ds,row,error=job.result()
            if row is not None: results.append(row)
            else: missing.append({'date':ds,'reason':error})
            if n%200==0: log(f'Metrics progress: {n}/{len(dates)}')
    pd.DataFrame(missing,columns=['date','reason']).to_csv(RAW/'binance_metrics_missing.csv',index=False)
    if not results:
        warn('No futures metrics available — see binance_metrics_missing.csv')
        return pd.DataFrame(columns=list(METRIC_RENAME.values()))
    df=pd.DataFrame(results).drop_duplicates('date').set_index('date').sort_index()
    df.index.name='date'
    df.to_csv(RAW/'binance_metrics_daily.csv')
    if missing: warn(f'Futures metrics missing for {len(missing)}/{len(dates)} days (see CSV)')
    log(f'Futures metrics: {len(df)} days')
    return df


def parse_farside_html(html):
    soup=BeautifulSoup(html,'html.parser')
    for table in soup.find_all('table'):
        header=None
        data=[]
        for tr in table.find_all('tr'):
            cells=[c.get_text(' ',strip=True) for c in tr.find_all(['td','th'],recursive=False)]
            if not cells: continue
            if header is None:
                clean=[str(x).strip() for x in cells]
                if clean[0].lower()=='date' and 'Total' in clean:
                    header=clean
                continue
            if len(cells) != len(header): continue
            try:
                date=datetime.strptime(cells[0],'%d %b %Y').date()
            except ValueError:
                continue
            out={'date':pd.Timestamp(date,tz='UTC')}
            for col,val in zip(header[1:],cells[1:]):
                text=val.strip().replace(',','')
                if text.startswith('(') and text.endswith(')'):
                    text='-'+text[1:-1]
                out['etf_flow_'+col.lower()+'_usd_m']=pd.to_numeric(text,errors='coerce')
            data.append(out)
        if data:
            return pd.DataFrame(data).drop_duplicates('date',keep='last').set_index('date').sort_index()
    raise RuntimeError('Farside HTML does not contain a Date + Total flows table')


def download_etf(start,end):
    log('Downloading complete history of US spot Bitcoin ETF flows from Farside...')
    r=get('https://farside.co.uk/bitcoin-etf-flow-all-data/',timeout=70)
    df=parse_farside_html(r.text)
    df=df.loc[(df.index>=pd.Timestamp(start,tz='UTC')) & (df.index<=pd.Timestamp(end,tz='UTC'))]
    if 'etf_flow_total_usd_m' not in df: raise RuntimeError('Missing ETF Total column')
    df.to_csv(RAW/'farside_btc_etf_flows.csv')
    log(f'ETF: {len(df)} reporting days')
    return df


def fred_one(series_id,start,end):
    r=get('https://fred.stlouisfed.org/graph/fredgraph.csv', params={'id':series_id,'cosd':start,'coed':end},timeout=70)
    csv=pd.read_csv(io.StringIO(r.text))
    if len(csv.columns)<2: raise RuntimeError('FRED did not return a 2-column CSV')
    datecol='observation_date' if 'observation_date' in csv else csv.columns[0]
    valuecol=series_id if series_id in csv else csv.columns[-1]
    index=pd.to_datetime(csv[datecol],utc=True,errors='coerce').dt.normalize()
    vals=pd.to_numeric(csv[valuecol],errors='coerce')
    return pd.Series(vals.to_numpy(),index=index,name=series_id).loc[lambda x:~x.index.isna()]


def stooq_gold(start,end):
    r=get('https://stooq.com/q/d/l/',params={'s':'xauusd','d1':start.replace('-',''),'d2':end.replace('-',''),'i':'d'},timeout=70)
    df=pd.read_csv(io.StringIO(r.text))
    if not {'Date','Close'}.issubset(df.columns): raise RuntimeError('Stooq did not return CSV Date,Close (possibly access-limited)')
    index=pd.to_datetime(df['Date'],utc=True,errors='coerce').dt.normalize()
    vals=pd.to_numeric(df['Close'],errors='coerce')
    out=pd.Series(vals.to_numpy(),index=index,name='gold')
    return out.loc[~out.index.isna()]


def download_macro(start,end):
    log('Downloading FRED macroeconomic and Stooq XAUUSD series...')
    daily=pd.date_range(start,end,freq='D',tz='UTC',name='date')
    observed=pd.DataFrame(index=daily)
    for name,sid in FRED_SERIES.items():
        try:
            s=fred_one(sid,start,end)
            observed[name]=s.reindex(daily)
            log(f'  FRED {sid}: {int(observed[name].notna().sum())} observations')
        except Exception as e:
            warn(f'FRED {sid} failed: {e}')
            observed[name]=np.nan
    try:
        gold=stooq_gold(start,end)
        observed['gold']=gold.reindex(daily)
        log(f'  Stooq gold: {int(observed["gold"].notna().sum())} observations')
    except Exception as e:
        warn(f'Stooq gold unavailable, leave missing (do not fake gold prices): {e}')
        observed['gold']=np.nan
    observed.to_csv(RAW/'fred_macro_observations.csv')
    # Explicit conservative calendar lags. This is NOT true point-in-time: US
    # market close timing, weekends, economic release lags and revisions remain.
    aligned=observed.ffill().shift(1)
    for name in ('fedfunds','m2'):
        aligned[name]=observed[name].ffill().shift(45)
    aligned.to_csv(RAW/'macro_available_lagged_proxy.csv')
    return aligned


def rolling_zscore(s: pd.Series, window: int) -> pd.Series:
    mu = s.rolling(window).mean()
    sd = s.rolling(window).std()
    return (s - mu) / sd.replace(0, np.nan)


def add_features(df: pd.DataFrame) -> pd.DataFrame:
    x = df.copy()

    # ---------------- Market returns ----------------
    for n in [1, 3, 7, 14, 30, 90]:
        x[f"ret_{n}d"] = x["close"].pct_change(n)

    x["log_ret_1d"] = np.log(x["close"]).diff()

    # Candle geometry of current day.
    x["candle_body"] = (x["close"] - x["open"]) / x["open"]
    x["candle_range"] = (x["high"] - x["low"]) / x["open"]
    x["upper_wick"] = (x["high"] - x[["open", "close"]].max(axis=1)) / x["open"]
    x["lower_wick"] = (x[["open", "close"]].min(axis=1) - x["low"]) / x["open"]
    x["close_location"] = (x["close"] - x["low"]) / (x["high"] - x["low"]).replace(0, np.nan)

    # Volatility.
    for n in [7, 14, 30, 60]:
        x[f"vol_{n}d"] = x["log_ret_1d"].rolling(n).std() * np.sqrt(365)

    # ATR-like normalized range.
    prev_close = x["close"].shift(1)
    tr = pd.concat(
        [
            x["high"] - x["low"],
            (x["high"] - prev_close).abs(),
            (x["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    x["atr_14_pct"] = tr.rolling(14).mean() / x["close"]

    # Moving averages.
    for n in [7, 30, 90, 200]:
        ma = x["close"].rolling(n).mean()
        x[f"dist_ma_{n}d"] = x["close"] / ma - 1

    # Volume.
    x["volume_log"] = np.log1p(x["volume"])
    x["volume_z_30d"] = rolling_zscore(np.log1p(x["volume"]), 30)
    x["taker_buy_ratio"] = x["taker_buy_base_volume"] / x["volume"].replace(0, np.nan)
    x["taker_buy_imbalance"] = 2 * x["taker_buy_ratio"] - 1

    # ---------------- Funding ----------------
    if "funding_mean" in x:
        for n in [3, 7, 14, 30]:
            x[f"funding_mean_{n}d"] = x["funding_mean"].rolling(n).mean()
        x["funding_z_30d"] = rolling_zscore(x["funding_mean"], 30)

    # ---------------- Open interest ----------------
    if "oi_usd" in x:
        x["oi_usd_change_1d"] = x["oi_usd"].pct_change()
        for n in [3, 7, 14, 30]:
            x[f"oi_usd_change_{n}d"] = x["oi_usd"].pct_change(n)
        x["oi_usd_z_30d"] = rolling_zscore(np.log1p(x["oi_usd"]), 30)
        x["oi_usd_to_mcap_proxy"] = x["oi_usd"] / x["close"]

    if "oi_btc" in x:
        x["oi_btc_change_1d"] = x["oi_btc"].pct_change()

    # Long/short ratios.
    for col in [
        "toptrader_long_short_ratio",
        "account_long_short_ratio",
        "taker_long_short_volume_ratio",
    ]:
        if col in x:
            x[f"{col}_log"] = np.log(x[col].replace(0, np.nan))
            x[f"{col}_z_30d"] = rolling_zscore(x[col], 30)

    # ---------------- ETF flows ----------------
    # ETF data is reported on US market sessions, but BTC candles exist 7 days/week.
    # Compute trailing windows over *reported sessions*, never over calendar-day
    # NaNs (otherwise 7+/14+/30+ windows can be missing for the entire series).
    # The joined ETF series is already shifted one calendar day in main(), so
    # none of these trailing calculations use unpublished same-day ETF flows.
    # Forward-fill the most recently published feature for up to 4 days to cover
    # weekends/long weekends; a longer outage remains missing rather than stale.
    if "etf_flow_total_usd_m" in x:
        reported = pd.to_numeric(x["etf_flow_total_usd_m"], errors="coerce").dropna()
        for n in [3, 7, 14, 30]:
            trailing = reported.rolling(window=n, min_periods=n).sum()
            x[f"etf_total_flow_{n}d"] = trailing.reindex(x.index).ffill(limit=4)
        z = rolling_zscore(reported, 30)
        x["etf_total_flow_z_30d"] = z.reindex(x.index).ffill(limit=4)

    # ---------------- Macro ----------------
    for col in [
        "sp500", "nasdaq", "vix", "usd_broad",
        "us2y", "us10y", "wti", "gold", "fedfunds", "m2"
    ]:
        if col in x:
            x[f"{col}_ret_1d"] = x[col].pct_change()

    if "us10y" in x and "us2y" in x:
        x["yield_curve_10y_2y"] = x["us10y"] - x["us2y"]

    if "m2" in x:
        x["m2_growth_30d"] = x["m2"].pct_change(30)
        x["m2_growth_90d"] = x["m2"].pct_change(90)

    # ---------------- Targets: NEXT DAY candle ----------------
    # All are relative to today's close.
    next_open = x["open"].shift(-1)
    next_high = x["high"].shift(-1)
    next_low = x["low"].shift(-1)
    next_close = x["close"].shift(-1)

    x["target_open_ret"] = next_open / x["close"] - 1
    x["target_high_ret"] = next_high / x["close"] - 1
    x["target_low_ret"] = next_low / x["close"] - 1
    x["target_close_ret"] = next_close / x["close"] - 1

    x["target_range"] = x["target_high_ret"] - x["target_low_ret"]
    x["target_body"] = x["target_close_ret"] - x["target_open_ret"]
    x["target_direction"] = (x["target_close_ret"] > 0).astype(int)

    # Shape labels. These are intentionally simple first-pass labels.
    x["target_green"] = (x["target_close_ret"] > x["target_open_ret"]).astype(int)
    x["target_large_range"] = (
        x["target_range"] > x["target_range"].rolling(30).median()
    ).astype(int)

    return x




def report_summary(df,market,funding,metrics,etf,macro,start,end):
    coverage={
        'ohlcv_daily': len(market),
        'funding_daily': len(funding),
        'metrics_daily': len(metrics),
        'etf_trading_days': len(etf),
        'macro_days': int(macro.notna().any(axis=1).sum()) if not macro.empty else 0,
    }
    missing=(df.isna().mean()*100).round(2).to_dict()
    report={
        'generated_at_utc':datetime.now(timezone.utc).isoformat(),
        'symbol':SYMBOL,
        'start_requested':start,
        'end_requested':end,
        'end_actual':str(market.index.max().date()),
        'features_start':str(df.index.min().date()),
        'features_end':str(df.index.max().date()),
        'rows':len(df),
        'columns':len(df.columns),
        'source_row_counts':coverage,
        'macro_non_null_counts': {name:int(macro[name].notna().sum()) for name in macro.columns},
        'missing_pct_by_column':missing,
        'warnings':WARNINGS,
        'causality_notes':[
            'Market features day t assumed available only after UTC day t closes.',
            'Futures positioning metrics shifted by one full day: Binance changed metrics timestamp conventions in 2026.',
            'ETF Farside observed day t shifted by one full day, a conservative proxy for publication availability.',
            'ETF trailing 3/7/14/30d features count REPORTING sessions, not calendar days; last available value carried forward up to 4 days.',
            'FRED daily market data lagged one calendar day; M2/Fedfunds lagged 45 calendar days.',
            'Macro vintages/revisions not corrected: use ALFRED and release-time data for rigorous PIT research.',
            'Targets t+1 exist only for rows with a next-day candle; last daily candle is removed.',
        ],
    }
    REPORTS.mkdir(parents=True,exist_ok=True)
    (REPORTS/'data_download_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    textlines=[
        '# BTCUSDT DATA DOWNLOAD REPORT',
        '',f'Generated (UTC): {report["generated_at_utc"]}',
        f'Requested: {start} to {end}',
        f'Market: {market.index.min().date()} to {market.index.max().date()}',
        f'Features rows / cols: {len(df)} / {len(df.columns)}',
        '', '## Source row counts',
        *[f'- {key}: {n}' for key,n in coverage.items()],
        '', '## Macro columns with actual values',
        *([f'- {name}: {cnt}' for name,cnt in report['macro_non_null_counts'].items()] or ['- No macro columns downloaded']),
        '', '## Most missing columns (%)',
        *[f'- {name}: {pct}%' for name,pct in sorted(missing.items(),key=lambda x:-x[1])[:25]],
        '', '## Warnings',
        *([f'- {x}' for x in WARNINGS] or ['- None']),
        '', '## Research cautions',
        *[f'- {x}' for x in report['causality_notes']]
    ]
    (REPORTS/'data_download_report.md').write_text('\n'.join(textlines)+'\n',encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start-date',default='2021-01-01')
    parser.add_argument('--end-date',default=(datetime.now(timezone.utc)-timedelta(days=1)).strftime('%Y-%m-%d'))
    parser.add_argument('--workers',type=int,default=6)
    parser.add_argument('--no-metrics',action='store_true')
    parser.add_argument('--no-etf',action='store_true')
    parser.add_argument('--no-macro',action='store_true')
    a=parser.parse_args()
    if pd.Timestamp(a.start_date) >= pd.Timestamp(a.end_date):
        parser.error('--start-date must precede --end-date')
    yesterday=(datetime.now(timezone.utc)-timedelta(days=1)).date()
    if pd.Timestamp(a.end_date).date()>yesterday:
        parser.error('--end-date must not be later than yesterday UTC (only closed candles)')
    for folder in (RAW,PROCESSED,REPORTS,CACHE): folder.mkdir(parents=True,exist_ok=True)
    log(f'Quantitative Research Lab data dir: {PROJECT_ROOT}')
    market=download_ohlcv(a.start_date,a.end_date)
    funding=download_funding(a.start_date,str(market.index.max().date()))
    metrics=pd.DataFrame(columns=list(METRIC_RENAME.values()))
    if not a.no_metrics: metrics=download_metrics(a.start_date,str(market.index.max().date()),a.workers)
    etf=pd.DataFrame(columns=['etf_flow_total_usd_m'])
    if not a.no_etf:
        try: etf=download_etf(a.start_date,str(market.index.max().date()))
        except Exception as e: warn(f'ETF source unavailable: {e}')
    macro=pd.DataFrame(index=market.index)
    if not a.no_macro: macro=download_macro(a.start_date,str(market.index.max().date()))
    # Lag the positions and Farside ETF flows by one full UTC calendar day,
    # because archive labels/publication times may not be known at day t close.
    metrics_avail=metrics.reindex(market.index).shift(1)
    etf_avail=etf.reindex(market.index).shift(1)
    aligned=market.join(funding,how='left').join(metrics_avail,how='left').join(etf_avail,how='left').join(macro,how='left')
    aligned.index.name='date'
    aligned.to_csv(PROCESSED/'btc_daily_raw.csv')
    features=add_features(aligned)
    features=features.iloc[:-1].copy()
    if features.empty: raise RuntimeError('Not enough candles to create t+1 targets')
    features.to_csv(PROCESSED/'btc_daily_features.csv')
    try:
        features.to_parquet(PROCESSED/'btc_daily_features.parquet')
    except Exception as e:
        warn(f'Parquet could not be written (CSV is still available): {e}')
    rep=report_summary(features,market,funding,metrics,etf,macro,a.start_date,a.end_date)
    log('='*65)
    log(f'DONE. Market={len(market)} rows; research features={len(features)} rows x {len(features.columns)} columns')
    log('CSV: '+str(PROCESSED/'btc_daily_features.csv'))
    if (PROCESSED/'btc_daily_features.parquet').is_file():
        log('Parquet: '+str(PROCESSED/'btc_daily_features.parquet'))
    log('Coverage: '+str(REPORTS/'data_download_report.md'))
    log(f'Warnings: {len(rep["warnings"])} (check report)')
    log('='*65)

if __name__=='__main__':
    main()
