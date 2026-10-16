# Golden Cross 50/200 — Ouro (GC), 1h, long only

## Regras
- **Compra** quando a SMA 50 cruza acima da SMA 200 (no fechamento do candle; execução na abertura do próximo).
- **Fecha** quando a SMA 50 cruza de volta abaixo da SMA 200.
- Sem stop loss, sem take profit, sem previsão.
- Período: 01/10/2023 → 01/10/2026, capital inicial US$ 10.000.
  As médias "aquecem" com dados anteriores ao início, se o CSV os tiver.

## Tamanho da posição
GC (100 oz) e até MGC (10 oz, ~US$ 19k nocional em out/2023) custam mais que US$ 10k sem alavancagem. Então:
- `--sizing fixed` (padrão): 1 contrato MGC sobre o preço do GC (alavancado, como uma conta de futuros real de US$ 10k operaria).
- `--sizing equity`: contratos fracionários = 100% do patrimônio (sem alavancagem, benchmark teórico).
- `--multiplier 100 --contracts 1` → 1 GC cheio (exige ~US$ 10k+ de margem; risco de chamada de margem).

## Custos
Os valores padrão são **provisórios**: US$ 1,00 de comissão por contrato por lado + 1 tick (US$ 0,10/oz) de slippage por lado.
Troque pela tabela de custos da CoinQuant com `--commission` e `--slippage-ticks`.

## Rodar
```bash
pip install pandas numpy matplotlib
python backtest.py gc_1h.csv                       # 1 MGC
python backtest.py gc_1h.csv --sizing equity       # sem alavancagem
python -m pytest -q test_backtest.py
```
CSV: colunas `time` (unix s/ms ou ISO) + `open,high,low,close`. Por exemplo, exportação do TradingView de `COMEX:GC1!` no 1h.
Saída em `results/`: `summary.json`, `trades.csv`, `equity.csv`, `equity.png`.

## TradingView / Vela
`golden_cross.pine` (Pine v5) roda a mesma estratégia direto no gráfico `COMEX:GC1!` (ou `MGC1!`) 1h, com comissão por contrato configurável.

## Usando a base de ticks do ATAS (Drive "Journal Trading/ticks_MES")
```bash
# arquivos ticks_MES_1s_preco_AAAA-MM-DD.csv.gz baixados do Drive
python ticks_to_hourly.py data/mes_1h.csv /caminho/ticks_MES_1s_preco_*.csv.gz
python backtest.py data/mes_1h.csv --start 2025-11-03 --end 2026-10-13 \
    --multiplier 5 --tick-size 0.25          # 1 MES: US$ 5/ponto, tick 0,25
```
`ticks_to_hourly.py` aceita os dois formatos do export (`_preco_` = preço por segundo; sem `_preco_` = OHLC de 1 s)
e pode ser rodado várias vezes: acumula no mesmo CSV e remove duplicados.
