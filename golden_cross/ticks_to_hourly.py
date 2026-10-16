"""Build 1h OHLCV bars from ATAS 1-second exports in the Journal Trading Drive.

Two formats are accepted:
  ticks_MES_1s_preco_*: hora_utc;preco;vol_compra;vol_venda;negocios (one row per
      second and price; order inside a second is unknown, so open/close are the first
      and last rows; high/low are exact)
  ticks_MES_1s_*:       hora_utc;abertura;maxima;minima;fechamento;volume;... (1s OHLC)
Bars are labeled by their UTC start hour.

Usage: python ticks_to_hourly.py OUT.csv FILE [FILE ...]
FILE may be a .csv.gz or the JSON result of the Drive connector ({content: base64}).
"""
import base64, gzip, io, json, sys
import pandas as pd


def read_any(path):
    raw = open(path, "rb").read()
    if raw[:1] == b"{":
        d = json.loads(raw)
        return d["title"], gzip.decompress(base64.b64decode(d["content"]))
    return path, gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw


def hourly(csv_bytes):
    df = pd.read_csv(io.BytesIO(csv_bytes), sep=";")
    if df.empty:
        return df
    df["t"] = pd.to_datetime(df["hora_utc"], utc=True)
    if "preco" in df:
        df = df.assign(abertura=df.preco, maxima=df.preco, minima=df.preco,
                       fechamento=df.preco, volume=df.vol_compra + df.vol_venda)
    g = df.groupby(df["t"].dt.floor("h"), sort=True)
    return pd.DataFrame({
        "open": g["abertura"].first(), "high": g["maxima"].max(), "low": g["minima"].min(),
        "close": g["fechamento"].last(), "volume": g["volume"].sum(),
    })


def main():
    out, files = sys.argv[1], sys.argv[2:]
    frames, seen = [], []
    for f in files:
        title, data = read_any(f)
        h = hourly(data)
        seen.append((title, len(h)))
        frames.append(h)
    new = pd.concat(frames)
    try:
        old = pd.read_csv(out, index_col=0, parse_dates=True)
        new = pd.concat([old, new])
    except FileNotFoundError:
        pass
    new = new[~new.index.duplicated(keep="last")].sort_index()
    new.index.name = "time"
    new.to_csv(out)
    for t, n in seen:
        print(f"{t}: {n} bars")
    print("total bars:", len(new), new.index.min(), "->", new.index.max())


if __name__ == "__main__":
    main()
